from __future__ import annotations

import hashlib
import json
import time
from datetime import datetime, timezone
from typing import Any

from infra.logger_setup import get_logger
from core.spider_core import CrawlResponse, spider_sdk
from core.compliance import compliance_checker, pii_mask, sensitive_filter, RISK_HIGH
from infra.db_base import database
from infra.db_models import SpiderRawData
from configs.settings import settings

from business.multi_spider.models import RawItem, SpiderTaskParams, SpiderTaskResult

logger = get_logger("multi_spider.base")


# =====================
# 抽象基类
# =====================


class BaseSpider:
    """所有业务爬虫的基类。

    工作流：
        build_url_list(params) -> list[url]
        对每个 url:
            resp = spider_sdk.get(url, ...)
            items = parse(resp, params)
        对每个 item:
            pii_mask + sensitive_filter + compliance
            写入 SpiderRawData
    """

    # 子类必须覆盖
    name: str = ""

    # 可选：用于 Redis 任务状态 / checkpoint 回写的依赖
    # （不强制，None 则跳过 Redis 状态写入）
    redis_client: Any | None = None

    # ---------------- 子类接口 ----------------

    def build_url_list(self, params: SpiderTaskParams) -> list[str]:
        """从 seeds + keywords 生成目标 URL 列表。

        - 若 params.urls 显式提供，优先使用它
        - 否则调用子类的 _generate_from_seeds(params)
        """
        if params.urls:
            return list(params.urls)[: params.max_pages or len(params.urls)]
        return self._generate_from_seeds(params)

    def _generate_from_seeds(self, params: SpiderTaskParams) -> list[str]:
        """子类覆盖：从模板/关键词产生 URL 列表。默认返回 []。"""
        raise NotImplementedError(
            f"{self.__class__.__name__} 必须实现 _generate_from_seeds 或在 run() 中传入 urls"
        )

    def parse(self, resp: CrawlResponse, params: SpiderTaskParams) -> list[RawItem]:
        """子类覆盖：从 CrawlResponse.text 解析为 RawItem 列表。"""
        raise NotImplementedError(
            f"{self.__class__.__name__} 必须实现 parse(resp, params)"
        )

    # ---------------- 通用运行入口 ----------------

    def run(self, params: SpiderTaskParams) -> SpiderTaskResult:
        result = SpiderTaskResult(
            task_id=params.task_id,
            spider_name=self.name,
            status="ok",
        )
        started = time.monotonic()

        # 1) 生成 URL 列表
        urls: list[str] = []
        try:
            urls = self.build_url_list(params)
        except Exception as exc:
            logger.warning(f"[{self.name}] build_url_list 失败: {exc}")
            result.status = "failed"
            result.first_error = f"build_url_list: {exc}"
            return result

        result.total_attempted = len(urls)
        items: list[RawItem] = []

        # 2) 请求 + 解析
        for url in urls:
            try:
                resp = spider_sdk.get(
                    url,
                    render=params.render_js,
                    task_id=params.task_id,
                    robot_check=True,
                    risk_check=True,
                )
            except Exception as exc:
                logger.warning(f"[{self.name}] get({url}) 异常: {exc}")
                result.total_failed += 1
                if result.first_error is None:
                    result.first_error = f"request_error: {exc}"
                continue

            if not resp.ok:
                result.total_failed += 1
                # 风控 / 限流区分计数
                if resp.risk_level == "high":
                    result.risk_detected += 1
                if resp.status_code == 429:
                    result.rate_limited += 1
                if result.first_error is None:
                    result.first_error = f"http_{resp.status_code}: {url}"
                continue

            try:
                parsed = self.parse(resp, params) or []
            except Exception as exc:
                logger.warning(f"[{self.name}] parse({url}) 异常: {exc}")
                result.total_failed += 1
                if result.first_error is None:
                    result.first_error = f"parse_error: {exc}"
                continue

            # 限制单 URL 最大条目数
            if params.max_items_per_url and len(parsed) > params.max_items_per_url:
                parsed = parsed[: params.max_items_per_url]

            for item in parsed:
                # 确保 source_id 存在
                if not item.source_id:
                    item.source_id = self._build_source_id(
                        url, {"title": item.title, "content": item.content}
                    )
                # 确保 source_url 存在
                if not item.source_url:
                    item.source_url = resp.final_url or url
                items.append(item)

        # 3) 合规 + 持久化
        rows: list[dict[str, Any]] = []
        now = datetime.now(timezone.utc)
        for item in items:
            row = self._build_row(item, params, now, result)
            rows.append(row)

        if params.dry_run:
            logger.info(f"[{self.name}] dry_run 模式，不落库（len={len(rows)}）")
            result.total_persisted = len(rows)
        else:
            self._persist(rows, params, result)

        # 4) 任务状态写入 Redis
        self._write_task_status(params, result)

        # 5) 告警
        self._alert_if_needed(params, result)

        # 6) 收尾
        if result.total_failed == 0 and result.total_attempted == len(urls):
            result.status = "ok"
        elif result.total_persisted > 0:
            result.status = "partial"
        else:
            result.status = "failed"

        result.finished_at = datetime.now(timezone.utc)
        result.duration_ms = int((time.monotonic() - started) * 1000)
        return result

    # ---------------- 流水线 helper ----------------

    def _build_row(
        self,
        item: RawItem,
        params: SpiderTaskParams,
        now: datetime,
        result: SpiderTaskResult,
    ) -> dict[str, Any]:
        s_cfg = settings.spider

        # 文本脱敏（PIIMask 暴露 auto_mask(text) 对字符串做全局正则脱敏）
        masked_content: str = item.content
        masked_title: str = item.title
        masked_author: str = item.author
        if s_cfg.SPIDER_PII_MASK_ENABLED:
            try:
                masked_content = pii_mask.auto_mask(item.content or "") or ""
                masked_title = pii_mask.auto_mask(item.title or "") or ""
                masked_author = pii_mask.auto_mask(item.author or "") or ""
            except Exception as exc:
                logger.warning(f"[{self.name}] pii_mask 失败: {exc}")

        # 敏感词过滤（只要命中敏感词就标记 fetch_status=3；命中数 >= threshold 或 filter 返回 blocked 均视为拦截）
        fetch_status = 0
        if s_cfg.SPIDER_COMPLIANCE_ENABLED:
            try:
                filter_result = sensitive_filter.filter_text(masked_content or masked_title)
                if (
                    filter_result.risk == RISK_HIGH
                    or filter_result.is_blocked
                    or len(filter_result.hits or []) >= max(1, int(s_cfg.SPIDER_SENSITIVE_HIGH_THRESHOLD or 3))
                ):
                    fetch_status = 3
                    result.total_blocked_by_compliance += 1
            except Exception as exc:
                logger.warning(f"[{self.name}] sensitive_filter 失败: {exc}")

        # 合规报告（写入 raw_payload 保留审计）
        compliance_report: dict[str, Any] = {}
        if s_cfg.SPIDER_COMPLIANCE_ENABLED:
            try:
                combined = {
                    "title": masked_title,
                    "content": masked_content,
                    "author": masked_author,
                    "tags": item.tags or [],
                    "extra": item.extra or {},
                }
                report = compliance_checker.check_for_storage(combined)
                compliance_report = report.to_dict()
            except Exception as exc:
                logger.warning(f"[{self.name}] compliance_checker 失败: {exc}")
                compliance_report = {"error": str(exc)}

        raw_payload: dict[str, Any] = {
            "author": masked_author,
            "published_at": item.published_at,
            "tags": list(item.tags or []),
            "extra": item.extra or {},
            "parse_warnings": [],
            "compliance_report": compliance_report,
        }

        return {
            "spider_name": self.name,
            "source_url": item.source_url,
            "source_id": item.source_id,
            "raw_payload": raw_payload,
            "raw_text": masked_content,
            "fetch_status": fetch_status,
            "fetch_error": None,
            "captured_at": now,
            "source_country": params.country or s_cfg.SPIDER_COUNTRY_DEFAULT,
            "tenant_id": params.tenant_id,
        }

    def _persist(self, rows: list[dict[str, Any]], params: SpiderTaskParams, result: SpiderTaskResult) -> None:
        if not rows:
            return
        batch_size = int(settings.spider.SPIDER_BATCH_INSERT_SIZE or 200)
        try:
            inserted = database.bulk_insert(SpiderRawData, rows, batch_size=batch_size)
            result.total_persisted = int(inserted or len(rows))
        except Exception as exc:
            # 可能是唯一键冲突 —— 退化为逐条 upsert
            logger.info(f"[{self.name}] bulk_insert 异常（可能是唯一键冲突），尝试 upsert: {exc}")
            saved = 0
            try:
                for row in rows:
                    try:
                        database.upsert(
                            SpiderRawData,
                            conflict_columns=["tenant_id", "spider_name", "source_id"],
                            rows=[row],
                        )
                        saved += 1
                    except Exception as inner_exc:
                        logger.warning(f"[{self.name}] upsert 单条失败: {inner_exc}")
                        result.total_failed += 1
            finally:
                result.total_persisted = saved

    def _write_task_status(self, params: SpiderTaskParams, result: SpiderTaskResult) -> None:
        if self.redis_client is None:
            return
        try:
            key = f"{settings.spider.SPIDER_TASK_STATUS_PREFIX}{params.task_id}"
            payload = result.model_dump_json()
            ttl = int(settings.spider.SPIDER_TASK_STATUS_TTL_SECONDS or 86400)
            self.redis_client.set(key, payload, ex=ttl)
        except Exception as exc:
            logger.warning(f"[{self.name}] redis 状态写入失败: {exc}")

    def _alert_if_needed(self, params: SpiderTaskParams, result: SpiderTaskResult) -> None:
        try:
            from infra.alerting import alert_service
        except Exception:
            return

        need_alert = False
        reason = ""
        if result.total_attempted > 0 and result.total_failed / max(1, result.total_attempted) >= 0.05:
            need_alert = True
            reason = f"失败率 ≥5%（{result.total_failed}/{result.total_attempted}）"
        elif result.risk_detected > 0:
            need_alert = True
            reason = f"风控拦截 {result.risk_detected} 次"
        elif result.total_blocked_by_compliance > 0 and result.total_attempted > 0:
            ratio = result.total_blocked_by_compliance / max(1, result.total_attempted)
            if ratio >= 0.1:
                need_alert = True
                reason = f"合规拦截率 ≥10%（{result.total_blocked_by_compliance}/{result.total_attempted}）"

        if need_alert:
            try:
                alert_service.service_exception_sync(
                    f"[T09][{self.name}] 抓取异常提醒：{reason}",
                    extra_data={
                        "task_id": params.task_id,
                        "spider_name": self.name,
                        "total_attempted": result.total_attempted,
                        "total_failed": result.total_failed,
                        "risk_detected": result.risk_detected,
                        "blocked_by_compliance": result.total_blocked_by_compliance,
                        "rate_limited": result.rate_limited,
                        "first_error": result.first_error,
                    },
                )
            except Exception as exc:
                logger.warning(f"[{self.name}] 告警推送失败: {exc}")

    # ---------------- 工具 ----------------

    @staticmethod
    def _build_source_id(url: str, extra: dict[str, Any] | None = None) -> str:
        sig = url or ""
        if extra:
            try:
                sig += "|" + json.dumps(extra, sort_keys=True, ensure_ascii=False, default=str)
            except Exception:
                pass
        return hashlib.md5(sig.encode("utf-8")).hexdigest()

    @staticmethod
    def _safe_get_text(resp_text: str, default: str = "") -> str:
        """保底：resp.text 为空或异常时返回 default。"""
        if not resp_text:
            return default
        return resp_text.strip() or default


__all__ = ["BaseSpider"]
