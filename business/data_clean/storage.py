from __future__ import annotations

from typing import TYPE_CHECKING

from infra.logger_setup import get_logger
from infra.db_base import database

from business.data_clean._orm import AnomalyPoolRow, StructuredOpportunityRow, ensure_tables
from business.data_clean.models import AnomalyRecord, StructuredOpportunity

if TYPE_CHECKING:
    pass

logger = get_logger("data_clean.storage")


# =====================
# Storage
# =====================


class Storage:
    """写入结构化商机表 + 异常池表。"""

    def __init__(self, ensure_schema: bool = True) -> None:
        if ensure_schema:
            try:
                ensure_tables()
            except Exception as exc:
                logger.warning(f"ensure_tables 失败（可能数据库未配置）: {exc}")

    # ---- 工具：pydantic -> dict row ----

    def _row_from_opportunity(self, opp: StructuredOpportunity) -> dict:
        d = opp.model_dump(mode="json")
        entities = d.get("entities", {}) or {}
        src = d.get("source", {}) or {}
        comp = d.get("compliance", {}) or {}
        score = d.get("score", {}) or {}
        pipeline = d.get("pipeline", {}) or {}

        return {
            "tenant_id": opp.tenant_id,
            "opportunity_id": opp.opportunity_id,
            "title": opp.title or "",
            "content_snippet": opp.content_snippet or "",
            "entities_json": entities,
            "source_spider_name": src.get("spider_name", ""),
            "source_id": src.get("source_id", ""),
            "source_url": src.get("source_url", ""),
            "source_captured_at": src.get("captured_at", ""),
            "source_raw_record_id": src.get("raw_record_id"),
            "compliance_risk": comp.get("risk_level", "low"),
            "compliance_hits": int(comp.get("sensitive_hits", 0) or 0),
            "compliance_blocked": bool(comp.get("blocked", False)),
            "compliance_json": comp.get("report", {}) or {},
            "score_total": int(score.get("total", 0) or 0),
            "score_grade": str(score.get("grade", "normal") or "normal"),
            "score_breakdown_json": score.get("dimension_scores", {}) or {},
            "score_blacklisted": bool(score.get("blacklisted", False)),
            "score_duplicate_of": score.get("is_duplicate_of"),
            "pipeline_version": str(pipeline.get("version", "")),
            "pipeline_processed_at": str(pipeline.get("processed_at", "")),
            "pipeline_trace": ",".join([str(s) for s in (pipeline.get("trace_steps") or [])]),
        }

    def _row_from_anomaly(self, a: AnomalyRecord) -> dict:
        return {
            "tenant_id": a.tenant_id,
            "anomaly_id": a.anomaly_id,
            "source_record_id": a.source_record_id,
            "spider_name": a.spider_name,
            "source_url": a.source_url,
            "type": a.type,
            "severity": a.severity,
            "reason": a.reason,
            "raw_snippet": a.raw_snippet,
            "pipeline_version": a.pipeline_version,
            "created_at": a.created_at,
            "needs_review": bool(a.needs_review),
            "reviewed_at": a.reviewed_at,
            "reviewed_by": a.reviewed_by,
            "review_note": a.review_note,
        }

    # ---- 公共 API ----

    def upsert_opportunities(self, opportunities: list[StructuredOpportunity]) -> int:
        if not opportunities:
            return 0
        rows = [self._row_from_opportunity(o) for o in opportunities]
        try:
            database.upsert(
                StructuredOpportunityRow,
                conflict_columns=["tenant_id", "opportunity_id"],
                rows=rows,
            )
            return len(rows)
        except Exception as exc:
            logger.warning(f"upsert_opportunities 失败: {exc}")
            # 退化为 bulk_insert —— 若唯一键冲突会被 DB 拒绝，记录单条失败
            saved = 0
            for r in rows:
                try:
                    database.bulk_insert(StructuredOpportunityRow, [r])
                    saved += 1
                except Exception as inner:
                    logger.debug(f"bulk_insert 单条失败: {inner}")
            return saved

    def upsert_anomalies(self, anomalies: list[AnomalyRecord]) -> int:
        if not anomalies:
            return 0
        rows = [self._row_from_anomaly(a) for a in anomalies]
        try:
            database.upsert(
                AnomalyPoolRow,
                conflict_columns=["tenant_id", "anomaly_id"],
                rows=rows,
            )
            return len(rows)
        except Exception as exc:
            logger.warning(f"upsert_anomalies 失败: {exc}")
            saved = 0
            for r in rows:
                try:
                    database.bulk_insert(AnomalyPoolRow, [r])
                    saved += 1
                except Exception as inner:
                    logger.debug(f"bulk_insert 单条 anomaly 失败: {inner}")
            return saved


__all__ = ["Storage"]
