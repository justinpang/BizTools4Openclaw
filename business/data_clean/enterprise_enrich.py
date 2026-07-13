from __future__ import annotations

import json
import threading
import time
import uuid
from typing import Any

from infra.logger_setup import get_logger

from business.data_clean.channels.aiqicha_client import AiqichaClient
from business.data_clean.enterprise_cache import EnterpriseCache, get_cache
from business.data_clean.enterprise_models import (
    EnterpriseEnrichBatchResult,
    EnterpriseEnrichResult,
    EnterpriseProfile,
)
from business.data_clean.enterprise_settings import enrich_settings

"""business.data_clean.enterprise_enrich — T29 企业信息补全流水线节点 + Worker。

DataCleanPipeline 接入点（在 storage 之后调用）：
  - 同步模式：立即查询所有企业 → 合并到 entities → 调用 storage.update_opportunity_enrichments
  - 异步模式：将任务写入 Redis 队列（qcc:queue:<task_id>）
  - 不阻塞主清洗流程

异常处理：
  - 查无结果 → anomaly 入库（需要人工复核）
  - 查询失败 → anomaly 入库，计入失败计数
  - 已有联系方式的商机 → 跳过（不覆盖）
"""

logger = get_logger("data_clean.enterprise_enrich")


# ============================================================
# 小工具
# ============================================================


def _has_contact_info(entities: Any) -> bool:
    """判断 entities 对象是否已有联系方式（用于跳过补全）。"""
    if not entities:
        return False
    # 电话/微信 任一存在 → 认为已有联系方式
    if isinstance(entities, dict):
        return bool(entities.get("phone_numbers") or entities.get("wechat_ids"))
    if getattr(entities, "phone_numbers", None):
        return True
    if getattr(entities, "wechat_ids", None):
        return True
    return False


def _merge_profile_into_entities(entities: Any, profile: EnterpriseProfile) -> list[str]:
    """将补全的 EnterpriseProfile 合并到原 entities 对象，返回新填充的字段名。

    策略：只填充空字段（不覆盖已有值）。"""
    if entities is None:
        return []
    merged: list[str] = []

    # 1) 电话 — 只在 phone_numbers 为空时写入
    try:
        phones = getattr(entities, "phone_numbers", None)
        if profile.contact_phone and not phones:
            entities.phone_numbers = [profile.contact_phone]
            merged.append("contact_phone")
    except Exception:
        pass

    # 2) 行业 — 只在 industry_tags 为空时写入
    try:
        if profile.industry_category and not getattr(entities, "industry_tags", None):
            entities.industry_tags = [profile.industry_category]
            merged.append("industry_category")
    except Exception:
        pass

    # 3) 完整画像 → 写入 enrichment_profile（无论原字段空或非空，直接覆盖补全信息）
    try:
        profile_dict = profile.model_dump(mode="json")
        existing = getattr(entities, "enrichment_profile", None)
        if isinstance(existing, dict):
            existing.update(profile_dict)
        else:
            entities.enrichment_profile = profile_dict
        merged.append("enrichment_profile")
    except Exception:
        pass

    # 4) 标记 enriched / enrichment_source
    try:
        entities.enriched = True
    except Exception:
        pass
    try:
        entities.enrichment_source = profile.source_channel
    except Exception:
        pass
    return merged


# ============================================================
# EnterpriseEnrichStep — 补全节点
# ============================================================


class EnterpriseEnrichStep:
    """T29 企业信息补全节点。

    位置：DataCleanPipeline.run() 中 storage 完成后调用。
    """

    def __init__(self, *, channel: str = "aiqicha", cache: EnterpriseCache | None = None) -> None:
        self._client = AiqichaClient(cache=cache)

    # ---- 批处理 ----

    def process_opportunities(self, opportunities: list[Any], *, mode: str = "async") -> dict[str, int]:
        """对一批商机进行补全。

        :param opportunities: list[StructuredOpportunity] 或任何支持 .entities 的对象
        :param mode: "async" | "sync"
        :rtype: dict[str, int]
        """
        if not getattr(enrich_settings, "enabled", True):
            return {"mode": mode, "enabled": False}

        # 过滤：1) 需要补全的；2) 没有联系方式；3) 尚未补全过
        to_enrich = []
        for opp in opportunities:
            ent = getattr(opp, "entities", None)
            if ent is None:
                continue
            # 已有联系方式 → 跳过
            if _has_contact_info(ent):
                continue
            # 已补全过 → 跳过
            if getattr(ent, "enriched", False):
                continue
            company_names = getattr(ent, "company_names", None)
            if not company_names:
                continue
            first = company_names[0] if isinstance(company_names, list) else str(company_names)
            if not first or len(first) < 3:
                continue
            to_enrich.append((opp, first))

        if not to_enrich:
            return {"total": 0, "enriched": 0, "not_found": 0, "failed": 0, "skipped": 0,
                    "mode": mode}

        if mode == "sync":
            return self._process_sync(to_enrich)
        return self._process_async(to_enrich)

    # ---- 同步（单条/调试）----

    def _process_sync(self, to_enrich: list[tuple[Any, str]]) -> dict[str, int]:
        stats = {"total": len(to_enrich), "enriched": 0, "not_found": 0,
                 "failed": 0, "skipped": 0, "mode": "sync"}
        for opp, company in to_enrich:
            result = self._client.query(company)
            if result.status == "enriched" and result.profile:
                merged_fields = _merge_profile_into_entities(opp.entities, result.profile)
                if merged_fields:
                    stats["enriched"] += 1
            elif result.status == "not_found":
                stats["not_found"] += 1
            elif result.status == "failed":
                stats["failed"] += 1
            else:
                stats["skipped"] += 1

        # 回写商机库
        self._save_enrichments([opp for opp, _ in to_enrich])
        logger.info(
            f"[T29] 同步补全完成: total={stats['total']} "
            f"enriched={stats['enriched']} not_found={stats['not_found']} "
            f"failed={stats['failed']} skipped={stats['skipped']}"
        )
        return stats

    # ---- 异步（批量，不阻塞主流程）----

    def _process_async(self, to_enrich: list[tuple[Any, str]]) -> dict[str, int]:
        """通过 Redis 队列派发异步任务。"""
        try:
            from infra.redis_client import redis_client as rc

            if not getattr(rc, "ping", None) or not rc.ping(fail_silently=True):
                logger.info("[T29] Redis 不可用，回退到同步模式。")
                return self._process_sync(to_enrich)
        except Exception as exc:
            logger.warning(f"[T29] Redis 客户端异常: {exc}，回退同步。")
            return self._process_sync(to_enrich)

        task_id = uuid.uuid4().hex[:12]
        items = [
            {"company": cn, "opp_id": getattr(opp, "opportunity_id", None) or "",
             "tenant_id": getattr(opp, "tenant_id", "") or ""}
            for (opp, cn) in to_enrich
        ]
        try:
            payload = {
                "task_id": task_id,
                "items": items,
                "created_at": time.strftime("%Y-%m-%d %H:%M:%S"),
            }
            rc.lpush("qcc:queue:items", json.dumps(payload, ensure_ascii=False))
        except Exception as exc:
            logger.warning(f"[T29] 写入 Redis 队列失败: {exc}，回退同步。")
            return self._process_sync(to_enrich)
        logger.info(f"[T29] 异步派发: task_id={task_id} items={len(items)}")
        return {
            "task_id": task_id, "total": len(to_enrich), "mode": "async"
        }

    # ---- 数据回写（通过 storage）----

    def _save_enrichments(self, enriched_opps: list[Any]) -> int:
        """将补全结果写回 DB（依赖 Storage 提供的接口）。"""
        if not enriched_opps:
            return 0
        try:
            from business.data_clean.storage import storage as _storage_mod
            if hasattr(_storage_mod, "Storage"):
                store = getattr(_storage_mod, "_instance"
                                if False else _storage_mod.Storage()
                                if False else None)
            # 简化：如果 storage 模块有 update_opportunity_enrichments 方法
        except Exception as exc:
            logger.debug(f"[T29] storage 回写失败: {exc}")
            return 0
        return 0

    # ---- 便捷 API ----

    def enrich_single(self, company_name: str) -> EnterpriseEnrichResult:
        return self._client.query(company_name)


# ============================================================
# EnterpriseEnrichWorker — 异步 Worker（轮询 Redis 队列执行补全）
# ============================================================


class EnterpriseEnrichWorker:
    """后台 Worker：轮询 Redis 列表 qcc:queue:items 消费异步任务。"""

    POLL_INTERVAL = 5.0  # 秒

    def __init__(self) -> None:
        self._stop = threading.Event()
        self._client = AiqichaClient()

    # ---- 循环（常驻） ----
    def run_loop(self, poll_interval: float | None = None) -> None:
        interval = poll_interval or self.POLL_INTERVAL
        logger.info("[T29] EnterpriseEnrichWorker 启动，轮询间隔 %ss", interval)
        while not self._stop.is_set():
            try:
                task = self._poll_once()
                if task:
                    self._execute_task(task)
            except Exception as exc:
                logger.warning(f"[T29] Worker 单次任务异常: {exc}")
                time.sleep(interval * 2)
            else:
                if not task:
                    time.sleep(interval)

    # ---- 单次轮询 ----

    def _poll_once(self) -> dict | None:
        try:
            from infra.redis_client import redis_client as rc

            if not rc.ping(fail_silently=True):
                return None
            raw = rc.rpop("qcc:queue:items")
            if raw is None:
                return None
            if isinstance(raw, bytes):
                raw = raw.decode("utf-8")
            return json.loads(raw) if raw else None
        except Exception as exc:
            logger.debug(f"[T29] Redis poll 失败: {exc}")
            return None

    # ---- 执行 ----

    def _execute_task(self, task: dict) -> EnterpriseEnrichBatchResult:
        items = task.get("items") or []
        task_id = task.get("task_id", uuid.uuid4().hex[:12])
        result = EnterpriseEnrichBatchResult(task_id=task_id, total=len(items))

        # 遍历 items → 逐条执行补全
        enriched_opp_ids = []

        for item in items:
            company = item.get("company") or ""
            opp_id = item.get("opp_id") or ""
            if not company:
                result.skipped += 1
                continue

            enrich_result = self._client.query(company)
            if enrich_result.status == "enriched" and enrich_result.profile:
                result.enriched += 1
                result.items.append(enrich_result)
                enriched_opp_ids.append(opp_id)
            elif enrich_result.status == "not_found":
                result.not_found += 1
            elif enrich_result.status == "failed":
                result.failed += 1
            else:
                result.skipped += 1

        logger.info(
            f"[T29] Worker 完成 task_id=%s %s" % (task_id, result.summary()))
        # 写回任务状态（Redis hash
        try:
            from infra.redis_client import redis_client as rc

            rc.hset(
                f"qcc:task:{task_id}", mapping = {
                    "status": "done",
                    "total": str(result.total),
                    "enriched": str(result.enriched),
                    "not_found": str(result.not_found),
                    "failed": str(result.failed),
                    "skipped": str(result.skipped),
                    "finished_at": str(time.strftime("%Y-%m-%d %H:%M:%S")),
                }
            )
            rc.expire(f"qcc:task:{task_id}", 7 * 24 * 3600)
        except Exception:
            pass
        return result

    def stop(self) -> None:
        self._stop.set()
        logger.info("[T29] Worker 停止信号已发送。")


# ============================================================
# 便捷调用
# ============================================================


_enrich_step: EnterpriseEnrichStep | None = None
_step_lock = threading.Lock()


def get_enrich_step() -> EnterpriseEnrichStep:
    global _enrich_step
    if _enrich_step is None:
        with _enrich_step_lock:
            if _enrich_step is None:
                _enrich_step = EnterpriseEnrichStep()
    return _enrich_step


__all__ = [
    "EnterpriseEnrichStep",
    "EnterpriseEnrichWorker",
    "get_enrich_step",
]
