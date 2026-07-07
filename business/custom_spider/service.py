"""business/custom_spider/service — 采集方案业务服务层。

核心能力：
  - 方案 CRUD + 版本管理（规则变更自动生成版本，可回滚）
  - 测试运行（单条 URL 快速验证规则效果）
  - 调度启停（对接 TaskScheduler，注册/注销 cron job）
  - 采集执行（调用 T25 rule_engine → 合规预检 → 入库 spider_raw_data）
  - 导入/导出（跨环境迁移方案配置）
  - 统计查询（运行次数、成功次数、总条目数）
"""

from __future__ import annotations

import hashlib
import json
import time
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple

from infra.logger_setup import get_logger

logger = get_logger("custom_spider.service")


# ============================================================
# 工具函数
# ============================================================
def _gen_plan_code(name: str) -> str:
    """生成 plan_code：plan_{md5(name+ts)[:12]}。"""
    ts = str(int(time.time() * 1000))
    raw = f"{name}:{ts}"
    return f"plan_{hashlib.md5(raw.encode('utf-8')).hexdigest()[:12]}"


def _dict_deep_eq(a: dict, b: dict) -> bool:
    """比较两个 dict 是否深度相等（用于判断规则是否变更）。"""
    try:
        return json.dumps(a, sort_keys=True, ensure_ascii=False) == json.dumps(
            b, sort_keys=True, ensure_ascii=False
        )
    except Exception:
        return False


def _extract_rule_fields(rule_config: dict) -> Dict[str, Any]:
    """从 rule_config 提取关键信息用于版本变更判断。"""
    key_fields = ["list_rule", "detail_rule", "field_mapping", "pagination"]
    return {k: rule_config.get(k) for k in key_fields if k in rule_config}


def _call_t25_engine(rule_config: dict, *, max_items: Optional[int] = None) -> Dict[str, Any]:
    """调用 T25 规则采集引擎，返回执行结果。

    对依赖缺失/异常容错，保证上层业务能继续。
    """
    try:
        from core.spider_core.rule_engine import RuleCrawlEngine

        # 构造一个最简 CrawlRuleSet
        rule_set = dict(rule_config)
        if max_items is not None:
            rule_set["max_items"] = max_items

        engine = RuleCrawlEngine()
        return engine.run(rule_set)  # type: ignore
    except Exception as exc:
        logger.error(f"T25 引擎调用失败: {exc}")
        return {"success": False, "error": str(exc), "items": [], "success_items": 0, "total_items": 0}


def _parse_engine_result(result: Any) -> Tuple[List[dict], int, int, Optional[float], str, List[dict]]:
    """从 T25 引擎返回结果提取标准字段。

    返回: (items, success, total, match_rate, error, alerts)
    """
    items: List[dict] = []
    success_count = 0
    total_count = 0
    match_rate: Optional[float] = None
    error_msg = ""
    alerts: List[dict] = []

    if result is None:
        return items, success_count, total_count, match_rate, "T25 engine returned None", alerts

    # dict 形式
    if isinstance(result, dict):
        items = result.get("items") or result.get("extracted_items") or []
        items = [dict(it) if hasattr(it, "__dict__") else it for it in items]
        items = [it for it in items if isinstance(it, dict)]
        success_count = int(result.get("success_items") or result.get("success_count") or len(items))
        total_count = int(result.get("total_items") or result.get("item_count") or len(items))
        match_rate = result.get("field_match_rate")
        if match_rate is not None:
            match_rate = float(match_rate)
        error_msg = result.get("error") or result.get("error_msg") or ""
        alerts = result.get("alerts") or []
    else:
        # 可能是一个 EngineResult 对象
        try:
            items = getattr(result, "items", []) or []
            items = [dict(it) if hasattr(it, "__dict__") else it for it in items]
            items = [it for it in items if isinstance(it, dict)]
            success_count = int(getattr(result, "success_items", len(items)) or len(items))
            total_count = int(getattr(result, "total_items", len(items)) or len(items))
            match_rate = getattr(result, "field_match_rate", None)
            if match_rate is not None:
                match_rate = float(match_rate)
            error_msg = str(getattr(result, "error", "") or "")
            alerts = getattr(result, "alerts", []) or []
        except Exception:
            pass

    return items, success_count, total_count, match_rate, error_msg, alerts


def _compliance_check_items(items: List[dict]) -> List[dict]:
    """T06 合规预检。如果合规检查模块不可用则原样返回。"""
    if not items:
        return []
    try:
        from core.compliance.pii_mask import pii_mask

        masked_items: List[dict] = []
        for item in items:
            try:
                new_item = {}
                for k, v in item.items():
                    if isinstance(v, str):
                        new_item[k] = pii_mask.mask_phone(v) if hasattr(pii_mask, "mask_phone") else v
                    else:
                        new_item[k] = v
                new_item["_compliance_masked"] = True
                masked_items.append(new_item)
            except Exception:
                masked_items.append(item)
        return masked_items
    except Exception as exc:
        logger.warning(f"T06 合规检查不可用，跳过: {exc}")
        return items


def _write_to_spider_raw(
    items: List[dict],
    *,
    plan_code: str,
    source_url: Optional[str] = None,
) -> int:
    """写入 T04 spider_raw_data 表。

    每条 item 作为一个结构化条目，spider_name 标记为 "custom_spider:{plan_code}"。
    """
    if not items:
        return 0
    written = 0
    try:
        from business.custom_spider.repository import _get_session
        from infra.db_models import SpiderRawData

        session = _get_session()
        if session is None:
            logger.warning("DB session 不可达，跳过写入 spider_raw_data")
            return 0

        for idx, item in enumerate(items):
            try:
                # 构造 source_url
                url = item.get("_source_url") or source_url or f"custom_spider:{plan_code}:item_{idx}"
                # 构造 source_id（增量去重）
                source_id_fields = [item.get("title"), item.get("url"), item.get("publish_time")]
                source_id_raw = "|".join([str(f) for f in source_id_fields if f])
                source_id = hashlib.md5(source_id_raw.encode("utf-8")).hexdigest() if source_id_raw else None

                entity = SpiderRawData(
                    spider_name=f"custom_spider:{plan_code}",
                    source_url=url[:1024],
                    source_id=source_id,
                    raw_payload=dict(item),
                    raw_text=str(item.get("content") or item.get("title") or "")[:2000],
                    fetch_status=1,
                    fetch_error=None,
                    source_country=None,
                )
                session.add(entity)
                written += 1
                # 每 50 条 flush 一次
                if written % 50 == 0:
                    session.commit()
            except Exception as exc:
                logger.warning(f"写入 spider_raw_data 失败: {exc}")

        session.commit()
        session.close()
    except Exception as exc:
        logger.error(f"_write_to_spider_raw 整体失败: {exc}")
    return written


# ============================================================
# PlanService — 采集方案业务服务
# ============================================================
class PlanService:
    """采集方案业务服务。

    纯 Python API，不依赖 Web 框架，可由任何上层调用方使用。
    """

    # ---------- 创建方案 ----------
    def create_plan(
        self,
        plan_name: str,
        target_domain: str,
        spider_type: str,
        rule_config: dict,
        *,
        plan_code: Optional[str] = None,
        description: Optional[str] = None,
        schedule_config: Optional[dict] = None,
        increment_config: Optional[dict] = None,
        cookie_raw: Optional[str] = None,
        operator: str = "system",
    ) -> Dict[str, Any]:
        """创建新方案，自动生成 v1 版本。"""
        from business.custom_spider.repository import PlanRepository, VersionRepository, LogRepository

        if not plan_name or not target_domain or not rule_config:
            return {"success": False, "error": "plan_name/target_domain/rule_config 必填"}

        code = plan_code or _gen_plan_code(plan_name)

        # 创建方案
        plan = PlanRepository.create(
            plan_name=plan_name,
            plan_code=code,
            target_domain=target_domain,
            spider_type=spider_type or "generic",
            rule_config=rule_config,
            description=description,
            schedule_config=schedule_config,
            increment_config=increment_config,
            cookie_raw=cookie_raw,
            created_by=operator,
        )
        if plan is None:
            LogRepository.create("create", operator=operator, success=False, error_message="DB 创建失败")
            return {"success": False, "error": "DB 创建失败"}

        plan_id = int(plan.id)

        # 创建 v1 版本
        VersionRepository.create(
            plan_id=plan_id,
            version_number=1,
            rule_config=rule_config,
            schedule_config=schedule_config,
            changed_by=operator,
            is_current=True,
        )

        LogRepository.create(
            "create", plan_id=plan_id, operator=operator, detail=f"创建方案: {plan_name} ({code})"
        )
        return {
            "success": True,
            "plan_id": plan_id,
            "plan_code": code,
            "version_number": 1,
            "plan_name": plan_name,
        }

    # ---------- 更新方案 ----------
    def update_plan(
        self,
        plan_id: int,
        *,
        plan_name: Optional[str] = None,
        status: Optional[str] = None,
        rule_config: Optional[dict] = None,
        schedule_config: Optional[dict] = None,
        increment_config: Optional[dict] = None,
        cookie_raw: Optional[str] = None,
        change_note: Optional[str] = None,
        operator: str = "system",
    ) -> Dict[str, Any]:
        """更新方案。如果 rule_config 变更则自动生成新版本。"""
        from business.custom_spider.repository import PlanRepository, VersionRepository, LogRepository

        # 获取当前方案
        plan = PlanRepository.get_by_id(plan_id)
        if plan is None:
            return {"success": False, "error": f"方案 {plan_id} 不存在"}

        # 判断规则是否变更
        current_rule = plan.rule_config or {}
        rule_changed = False
        if rule_config is not None and not _dict_deep_eq(_extract_rule_fields(current_rule), _extract_rule_fields(rule_config)):
            rule_changed = True

        # 组装更新字段
        updates: Dict[str, Any] = {}
        if plan_name:
            updates["plan_name"] = plan_name
        if status:
            updates["status"] = status
        if schedule_config is not None:
            updates["schedule_config"] = schedule_config
        if increment_config is not None:
            updates["increment_config"] = increment_config
        if cookie_raw is not None:
            updates["cookie_encrypted"] = cookie_raw

        new_version = None
        if rule_changed and rule_config is not None:
            # 规则变更：新版本号 = max_version + 1
            max_v = VersionRepository.get_max_version(plan_id)
            new_version = max_v + 1
            updates["rule_config"] = rule_config
            updates["current_version"] = new_version

            VersionRepository.create(
                plan_id=plan_id,
                version_number=new_version,
                rule_config=rule_config,
                schedule_config=schedule_config,
                change_note=change_note or "规则变更",
                changed_by=operator,
                is_current=True,
            )
            logger.info(f"方案 {plan_id} 规则变更，生成 v{new_version}")

        # 如果 schedule 变更但规则没变更，仍需更新
        if updates:
            PlanRepository.update(plan_id, updates)
            LogRepository.create(
                "update",
                plan_id=plan_id,
                operator=operator,
                detail=change_note or (f"规则变更 v{new_version}" if new_version else "配置更新"),
            )

        return {
            "success": True,
            "plan_id": plan_id,
            "new_version": new_version,
            "rule_changed": rule_changed,
        }

    # ---------- 克隆方案 ----------
    def clone_plan(
        self, plan_id: int, *, new_plan_name: str, new_plan_code: Optional[str] = None, operator: str = "system"
    ) -> Dict[str, Any]:
        """克隆一个已存在的方案，配置完全复制。"""
        from business.custom_spider.repository import PlanRepository

        plan = PlanRepository.get_by_id(plan_id)
        if plan is None:
            return {"success": False, "error": f"方案 {plan_id} 不存在"}

        return self.create_plan(
            plan_name=new_plan_name,
            target_domain=plan.target_domain,
            spider_type=plan.spider_type,
            rule_config=dict(plan.rule_config) if plan.rule_config else {},
            plan_code=new_plan_code,
            description=f"(克隆自方案 {plan.plan_name}) {plan.description or ''}",
            schedule_config=dict(plan.schedule_config) if plan.schedule_config else None,
            increment_config=dict(plan.increment_config) if plan.increment_config else None,
            cookie_raw=None,  # cookie 不克隆
            operator=operator,
        )

    # ---------- 删除方案 ----------
    def delete_plan(self, plan_id: int, *, operator: str = "system") -> Dict[str, Any]:
        """软删除方案（is_archived = True）。"""
        from business.custom_spider.repository import PlanRepository, LogRepository

        ok = PlanRepository.delete(plan_id)
        LogRepository.create(
            "delete", plan_id=plan_id if ok else None, operator=operator, success=ok,
            error_message=None if ok else "DB 删除失败"
        )
        # 停用调度
        if ok:
            try:
                self.disable_schedule(plan_id, operator=operator)
            except Exception:
                pass
        return {"success": ok}

    # ---------- 查询单条 ----------
    def get_plan(self, plan_id: int) -> Optional[Dict[str, Any]]:
        from business.custom_spider.repository import PlanRepository

        plan = PlanRepository.get_by_id(plan_id)
        if plan is None:
            return None
        return plan.to_public_dict() if hasattr(plan, "to_public_dict") else {"id": plan.id, "plan_name": plan.plan_name}

    def get_plan_by_code(self, plan_code: str) -> Optional[Dict[str, Any]]:
        from business.custom_spider.repository import PlanRepository

        plan = PlanRepository.get_by_code(plan_code)
        if plan is None:
            return None
        return plan.to_public_dict() if hasattr(plan, "to_public_dict") else {"id": plan.id, "plan_code": plan_code}

    # ---------- 列表查询 ----------
    def list_plans(
        self,
        *,
        status: Optional[str] = None,
        spider_type: Optional[str] = None,
        target_domain: Optional[str] = None,
        keyword: Optional[str] = None,
        page: int = 1,
        page_size: int = 20,
    ) -> Dict[str, Any]:
        from business.custom_spider.repository import PlanRepository

        items, total = PlanRepository.list(
            status=status,
            spider_type=spider_type,
            target_domain=target_domain,
            keyword=keyword,
            page=page,
            page_size=page_size,
        )
        out = []
        for it in items:
            if hasattr(it, "to_public_dict"):
                out.append(it.to_public_dict())
            else:
                out.append({"id": getattr(it, "id", None), "plan_name": getattr(it, "plan_name", "")})
        return {"items": out, "total": total, "page": page, "page_size": page_size}

    # ---------- 版本管理 ----------
    def list_versions(self, plan_id: int) -> List[Dict[str, Any]]:
        from business.custom_spider.repository import VersionRepository

        versions = VersionRepository.list_by_plan(plan_id)
        out = []
        for v in versions:
            if hasattr(v, "to_public_dict"):
                out.append(v.to_public_dict())
            else:
                out.append({"id": getattr(v, "id", None), "version_number": getattr(v, "version_number", 0)})
        return out

    def rollback_to_version(self, plan_id: int, version_number: int, *, operator: str = "system") -> Dict[str, Any]:
        """回滚到指定版本：把该版本的规则作为一个新版本。"""
        from business.custom_spider.repository import VersionRepository

        ver = VersionRepository.get_by_version(plan_id, version_number)
        if ver is None:
            return {"success": False, "error": f"版本 v{version_number} 不存在"}

        return self.update_plan(
            plan_id,
            rule_config=dict(ver.rule_config) if ver.rule_config else {},
            schedule_config=dict(ver.schedule_config) if ver.schedule_config else None,
            change_note=f"回滚到 v{version_number}",
            operator=operator,
        )

    # ---------- 测试运行 ----------
    def test_plan(
        self, plan_id: int, *, test_url: Optional[str] = None, max_items: int = 5, operator: str = "system"
    ) -> Dict[str, Any]:
        """单条 URL 测试运行，不入库。"""
        from business.custom_spider.repository import PlanRepository, RunRepository, LogRepository

        plan = PlanRepository.get_by_id(plan_id)
        if plan is None:
            return {"success": False, "error": f"方案 {plan_id} 不存在"}

        # 构造测试规则（如果有 test_url，则覆盖 list_rule 的 URL）
        rule_config = dict(plan.rule_config or {})
        if test_url and "list_rule" in rule_config:
            lr = dict(rule_config["list_rule"])
            lr["url_template"] = test_url
            rule_config["list_rule"] = lr

        # 1. 写入一条 running 记录
        run = RunRepository.create(plan_id=plan_id, run_mode="test", trigger_by=operator, status="running")
        run_id = int(run.id) if run else 0

        start_ts = time.monotonic()

        # 2. 调用 T25 引擎
        engine_result = _call_t25_engine(rule_config, max_items=max_items)

        # 3. 解析结果
        items, success_count, total_count, match_rate, error_msg, alerts = _parse_engine_result(engine_result)

        # 4. 合规预检（测试运行也需要合规脱敏展示）
        items_masked = _compliance_check_items(items)

        duration_ms = int((time.monotonic() - start_ts) * 1000)
        run_status = "completed" if not error_msg else "failed"

        # 5. 更新运行记录
        if run_id:
            RunRepository.update(
                run_id,
                {
                    "status": run_status,
                    "items_total": total_count,
                    "items_success": success_count,
                    "items_failed": max(0, total_count - success_count),
                    "field_match_rate": match_rate,
                    "error_summary": error_msg[:1024] if error_msg else None,
                    "alerts_json": {"alerts": alerts} if alerts else None,
                    "duration_ms": duration_ms,
                },
            )

        LogRepository.create(
            "test", plan_id=plan_id, operator=operator, detail=f"测试运行，采集 {len(items_masked)} 条"
        )

        return {
            "success": not error_msg,
            "plan_id": plan_id,
            "run_id": run_id,
            "items": items_masked[:max_items],
            "items_total": total_count,
            "items_success": success_count,
            "field_match_rate": match_rate,
            "duration_ms": duration_ms,
            "error": error_msg or None,
            "alerts": alerts,
        }

    # ---------- 立即执行采集 ----------
    def run_plan_now(
        self, plan_id: int, *, operator: str = "system", max_items: Optional[int] = None
    ) -> Dict[str, Any]:
        """立即执行一次采集（同步），结果写入 spider_raw_data。"""
        from business.custom_spider.repository import PlanRepository, RunRepository, LogRepository

        plan = PlanRepository.get_by_id(plan_id)
        if plan is None:
            return {"success": False, "error": f"方案 {plan_id} 不存在"}

        rule_config = dict(plan.rule_config or {})
        plan_code = plan.plan_code
        source_url = None
        if rule_config.get("list_rule"):
            source_url = rule_config["list_rule"].get("url_template")

        run = RunRepository.create(plan_id=plan_id, run_mode="manual", trigger_by=operator, status="running")
        run_id = int(run.id) if run else 0
        start_ts = time.monotonic()

        # 调用 T25 引擎
        engine_result = _call_t25_engine(rule_config, max_items=max_items)
        items, success_count, total_count, match_rate, error_msg, alerts = _parse_engine_result(engine_result)

        # 合规预检
        items_masked = _compliance_check_items(items)

        # 写入 spider_raw_data
        written = _write_to_spider_raw(items_masked, plan_code=plan_code, source_url=source_url)

        duration_ms = int((time.monotonic() - start_ts) * 1000)
        run_status = "completed" if not error_msg else "failed"

        # 更新运行记录
        if run_id:
            RunRepository.update(
                run_id,
                {
                    "status": run_status,
                    "items_total": total_count,
                    "items_success": written,
                    "items_failed": max(0, total_count - written),
                    "field_match_rate": match_rate,
                    "error_summary": error_msg[:1024] if error_msg else None,
                    "alerts_json": {"alerts": alerts} if alerts else None,
                    "duration_ms": duration_ms,
                },
            )

        # 更新 plan 的累计统计
        try:
            PlanRepository.update(
                plan_id,
                {
                    "run_count_total": (plan.run_count_total or 0) + 1,
                    "run_count_success": (plan.run_count_success or 0) + (1 if run_status == "completed" else 0),
                    "items_total": (plan.items_total or 0) + written,
                    "last_run_status": run_status,
                    "last_run_error": error_msg[:512] if error_msg else None,
                },
            )
        except Exception as exc:
            logger.warning(f"更新 plan 统计失败: {exc}")

        LogRepository.create(
            "run", plan_id=plan_id, operator=operator,
            detail=f"立即执行，采集 {written}/{total_count} 条，耗时 {duration_ms}ms",
            success=run_status == "completed",
            error_message=error_msg[:512] if error_msg else None,
        )

        return {
            "success": run_status == "completed",
            "plan_id": plan_id,
            "run_id": run_id,
            "items_total": total_count,
            "items_written": written,
            "field_match_rate": match_rate,
            "duration_ms": duration_ms,
            "error": error_msg or None,
            "alerts": alerts,
        }

    # ---------- 调度启停 ----------
    def enable_schedule(self, plan_id: int, *, operator: str = "system") -> Dict[str, Any]:
        """启用调度：注册到 TaskScheduler。"""
        from business.custom_spider.repository import PlanRepository, LogRepository

        plan = PlanRepository.get_by_id(plan_id)
        if plan is None:
            return {"success": False, "error": f"方案 {plan_id} 不存在"}

        schedule = dict(plan.schedule_config or {})
        cron = schedule.get("cron")
        if not cron:
            return {"success": False, "error": "schedule_config.cron 未配置"}

        try:
            from infra.task_scheduler import TaskScheduler

            scheduler = TaskScheduler()
            job_id = f"custom_spider:{plan.plan_code}"

            # 构造计划函数：通过 plan_code 反查配置
            scheduler.add_cron(
                job_id,
                _make_scheduled_runner(plan.plan_code),
                cron=cron,
            )
            PlanRepository.update(plan_id, {"status": "active"})
            LogRepository.create(
                "start", plan_id=plan_id, operator=operator, detail=f"启用调度，cron={cron}"
            )
            return {"success": True, "job_id": job_id, "cron": cron}
        except Exception as exc:
            msg = f"TaskScheduler 注册失败: {exc}"
            logger.error(msg)
            LogRepository.create("start", plan_id=plan_id, operator=operator, success=False, error_message=msg)
            return {"success": False, "error": msg}

    def disable_schedule(self, plan_id: int, *, operator: str = "system") -> Dict[str, Any]:
        """停用调度：从 TaskScheduler 移除。"""
        from business.custom_spider.repository import PlanRepository, LogRepository

        plan = PlanRepository.get_by_id(plan_id)
        if plan is None:
            return {"success": False, "error": f"方案 {plan_id} 不存在"}

        try:
            from infra.task_scheduler import TaskScheduler

            scheduler = TaskScheduler()
            job_id = f"custom_spider:{plan.plan_code}"

            # 尝试移除 job
            try:
                scheduler.remove_job(job_id)
            except Exception:
                pass

            PlanRepository.update(plan_id, {"status": "paused"})
            LogRepository.create(
                "stop", plan_id=plan_id, operator=operator, detail="停用调度"
            )
            return {"success": True, "job_id": job_id}
        except Exception as exc:
            msg = f"TaskScheduler 停用失败: {exc}"
            logger.error(msg)
            return {"success": False, "error": msg}

    # ---------- 导入/导出 ----------
    def export_plan(self, plan_id: int) -> Dict[str, Any]:
        plan = self.get_plan(plan_id)
        if not plan:
            return {"success": False, "error": f"方案 {plan_id} 不存在"}
        return {
            "success": True,
            "export": {
                "plan_name": plan.get("plan_name"),
                "target_domain": plan.get("target_domain"),
                "spider_type": plan.get("spider_type"),
                "description": plan.get("description"),
                "rule_config": plan.get("rule_config"),
                "schedule_config": plan.get("schedule_config"),
                "increment_config": plan.get("increment_config"),
                "version": plan.get("current_version"),
                "_exported_at": datetime.utcnow().isoformat() + "Z",
            },
        }

    def import_plan(
        self, config: dict, *, plan_name: Optional[str] = None, plan_code: Optional[str] = None, operator: str = "system"
    ) -> Dict[str, Any]:
        if not config or not config.get("rule_config"):
            return {"success": False, "error": "导入配置缺少 rule_config"}

        name = plan_name or config.get("plan_name") or f"imported_{int(time.time())}"
        return self.create_plan(
            plan_name=name,
            target_domain=config.get("target_domain") or "unknown",
            spider_type=config.get("spider_type") or "generic",
            rule_config=config["rule_config"],
            plan_code=plan_code,
            description=config.get("description"),
            schedule_config=config.get("schedule_config"),
            increment_config=config.get("increment_config"),
            operator=operator,
        )

    # ---------- 统计 ----------
    def get_plan_stats(self, plan_id: int) -> Dict[str, Any]:
        plan = self.get_plan(plan_id)
        if not plan:
            return {"success": False, "error": f"方案 {plan_id} 不存在"}

        runs, _ = self.list_runs(plan_id, page=1, page_size=1000)
        return {
            "success": True,
            "plan": plan,
            "run_count_total": plan.get("run_count_total") or 0,
            "run_count_success": plan.get("run_count_success") or 0,
            "items_total": plan.get("items_total") or 0,
            "last_run_status": plan.get("last_run_status"),
            "last_run_at": plan.get("last_run_at"),
            "recent_runs": runs[:10],
        }

    def list_runs(
        self, plan_id: int, *, status: Optional[str] = None, page: int = 1, page_size: int = 20
    ) -> Tuple[List[Dict[str, Any]], int]:
        from business.custom_spider.repository import RunRepository

        runs, total = RunRepository.list_by_plan(plan_id, status=status, page=page, page_size=page_size)
        out = []
        for r in runs:
            if hasattr(r, "to_public_dict"):
                out.append(r.to_public_dict())
            else:
                out.append({"id": getattr(r, "id", None), "status": getattr(r, "status", "")})
        return out, total

    def get_run_detail(self, run_id: int) -> Optional[Dict[str, Any]]:
        from business.custom_spider.repository import RunRepository

        run = RunRepository.get_by_id(run_id)
        if run is None:
            return None
        return run.to_public_dict() if hasattr(run, "to_public_dict") else {"id": run_id}


# ============================================================
# 调度执行入口 — TaskScheduler 回调函数
# ============================================================
def _make_scheduled_runner(plan_code: str):
    """构造一个可被 TaskScheduler 调用的函数。"""

    def _runner():
        try:
            service = PlanService()
            plan = service.get_plan_by_code(plan_code)
            if plan is None:
                logger.warning(f"[schedule] plan_code={plan_code} not found")
                return
            service.run_plan_now(int(plan["id"]), operator="scheduler")
        except Exception as exc:
            logger.error(f"[schedule] plan_code={plan_code} 执行异常: {exc}")

    return _runner


def execute_scheduled_plan(plan_code: str) -> Dict[str, Any]:
    """被 TaskScheduler 调用的入口函数。"""
    runner = _make_scheduled_runner(plan_code)
    try:
        runner()
        return {"success": True, "plan_code": plan_code}
    except Exception as exc:
        return {"success": False, "error": str(exc), "plan_code": plan_code}


__all__ = [
    "PlanService",
    "execute_scheduled_plan",
]
