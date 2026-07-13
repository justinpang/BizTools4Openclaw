from __future__ import annotations

from infra.logger_setup import get_logger
from configs.settings import settings

from business.data_clean.compliance_step import ComplianceStep
from business.data_clean.engine_step import EngineStep
from business.data_clean.extractor import EntityExtractor
from business.data_clean.filters import DirtyFilter
from business.data_clean.loader import load_pending_records
from business.data_clean.models import (
    AnomalyRecord,
    CleanRunResult,
    CleanTaskParams,
    ComplianceResult,
    StructuredOpportunity,
)
from business.data_clean.normalizer import Normalizer
from business.data_clean.storage import Storage
logger = get_logger("data_clean.pipeline")


# =====================
# 数据清洗流水线
# =====================


class DataCleanPipeline:
    """完整的数据清洗流水线。

    步骤：
        load → filter → extract → compliance → engine → normalize → storage
    """

    def __init__(
        self,
        *,
        dirty_filter: DirtyFilter | None = None,
        extractor: EntityExtractor | None = None,
        compliance_step: ComplianceStep | None = None,
        engine_step: EngineStep | None = None,
        normalizer: Normalizer | None = None,
        storage: Storage | None = None,
        enterprise_enrich_step: object | None = None,
    ) -> None:
        self.dirty_filter = dirty_filter or DirtyFilter()
        self.extractor = extractor or EntityExtractor()
        self.compliance_step = compliance_step or ComplianceStep()
        self.engine_step = engine_step or EngineStep()
        self.normalizer = normalizer or Normalizer()
        self.storage = storage or Storage()
        # T29 企业信息补全节点（懒加载，避免未启用时拖慢启动）
        self._enterprise_enrich_step = enterprise_enrich_step

    def run(
        self,
        params: CleanTaskParams,
        *,
        raw_records: list[object] | None = None,
    ) -> CleanRunResult:
        result = CleanRunResult(
            task_id=params.task_id,
            status="ok",
        )

        # 1) 加载
        if raw_records:
            records, next_cursor = list(raw_records), None
        else:
            records, next_cursor = load_pending_records(params)
        if not records:
            logger.info(f"[{params.task_id}] 无可处理的原始记录")
            result.status = "ok"
            result.finished_at = result.started_at
            return result
        result.processed = len(records)
        result.next_cursor = next_cursor

        # 2) 过滤脏数据
        passed, anomalies = self.dirty_filter.apply_batch(records)
        logger.info(f"[{params.task_id}] 过滤后: {len(passed)}/{len(records)}，异常 {len(anomalies)}")

        # 3) 抽取实体
        ok_pairs, extract_anomalies = self.extractor.extract_batch(passed)
        anomalies.extend(extract_anomalies)
        if not ok_pairs:
            logger.warning(f"[{params.task_id}] 没有可继续处理的记录")
            self._finalize(params, result, [], anomalies, [])
            return result

        # 4) 合规步骤
        pipeline_pairs: list[tuple] = []  # (RawRecord, EntityExtract, Compliance)
        for rec, entities in ok_pairs:
            (
                new_entities,
                compliance_anomaly,
                masked_text,
                compliance_report,
            ) = self.compliance_step.process(rec, entities)
            risk_level = "low"
            hits = 0
            if compliance_anomaly is not None:
                risk_level = "high"
            compliance = ComplianceResult(
                risk_level=risk_level,
                sensitive_hits=hits,
                blocked=bool(compliance_anomaly is not None),
                masked_text=masked_text,
                report=compliance_report or {},
            )
            if compliance_anomaly:
                anomalies.append(compliance_anomaly)
                result.blocked += 1
            pipeline_pairs.append((rec, new_entities, compliance))

        # 5) Engine
        scored_map: dict[str, object] = {}
        if params.run_engine:
            try:
                engine_input = [
                    (rec, entities) for rec, entities, _ in pipeline_pairs
                ]
                engine_result, engine_anomalies = self.engine_step.process_batch(engine_input)
                anomalies.extend(engine_anomalies)
                result.engine_total = int(getattr(engine_result, "final_opportunities", 0) or 0)
                for item in getattr(engine_result, "items", []) or []:
                    key = str(getattr(item, "clue_id", "") or "")
                    if key:
                        scored_map[key] = item
            except Exception as exc:
                logger.error(f"engine_step 异常: {exc}")
                result.status = "partial"
                if result.first_error is None:
                    result.first_error = f"engine: {exc}"

        # 6) Normalize
        opportunities: list[StructuredOpportunity] = []
        for rec, entities, compliance in pipeline_pairs:
            # 如果 high_violation，不再写入结构化商机表（只保留 anomaly）
            if compliance.blocked:
                continue
            scored = scored_map.get(rec.source_id or f"clue_{rec.id}")
            try:
                opp = self.normalizer.normalize(rec, entities, compliance, scored)
                opportunities.append(opp)
            except Exception as exc:
                logger.warning(f"normalize 失败: {exc}")
                anomalies.append(
                    AnomalyRecord(
                        anomaly_id=f"a_norm_{rec.id}_{params.task_id}",
                        tenant_id=rec.tenant_id,
                        source_record_id=rec.id,
                        type="normalize_fail",
                        severity="warn",
                        reason=f"normalize exception: {exc}",
                        raw_snippet=(rec.raw_text or "")[:200],
                        pipeline_version=str(settings.cleaning.CLEAN_PIPELINE_VERSION),
                        spider_name=rec.spider_name,
                        source_url=rec.source_url,
                    )
                )

        # 7) 持久化
        if params.run_storage:
            try:
                saved = self.storage.upsert_opportunities(opportunities)
                result.passed = saved
            except Exception as exc:
                logger.error(f"upsert_opportunities 失败: {exc}")
                result.status = "partial"
                if result.first_error is None:
                    result.first_error = f"storage_opp: {exc}"
            try:
                # 异常池独立写入
                saved_anom = self.storage.upsert_anomalies(anomalies)
                result.anomalies = saved_anom
            except Exception as exc:
                logger.error(f"upsert_anomalies 失败: {exc}")
                if result.first_error is None:
                    result.first_error = f"storage_anomaly: {exc}"
        else:
            result.passed = len(opportunities)
            result.anomalies = len(anomalies)

        # 7.5) T29 企业信息补全（可选，默认关闭；通过 CleanTaskParams 开启）
        if getattr(params, "run_enterprise_enrich", False):
            try:
                from business.data_clean.enterprise_enrich import EnterpriseEnrichStep

                if self._enterprise_enrich_step is None:
                    self._enterprise_enrich_step = EnterpriseEnrichStep()
                mode = getattr(params, "enrich_mode", "async")
                enrich_stats = self._enterprise_enrich_step.process_opportunities(
                    opportunities, mode=mode
                )
                # 写到 result 中（不阻塞主流程；如果 enrich_stats 中含 task_id，则返回给调用方）
                if enrich_stats and "enriched" in enrich_stats:
                    result.enrichment_stats = enrich_stats
            except Exception as exc:
                logger.warning(f"企业补全节点异常: {exc}")

        # 8) 告警
        self._maybe_alert(params, result)

        # 9) 任务状态 Redis（可选）
        self._write_task_status(params, result)

        result.finished_at = result.started_at
        return result

    # ---- 工具 ----

    def _maybe_alert(self, params: CleanTaskParams, result: CleanRunResult) -> None:
        try:
            from infra.alerting import alert_service
        except Exception:
            return
        ratio_anomaly = result.anomalies / max(1, result.processed)
        if ratio_anomaly >= float(settings.cleaning.CLEAN_ANOMALY_ALERT_RATIO or 0.05):
            try:
                alert_service.service_exception_sync(
                    f"[T10][{params.task_id}] 异常率过高 ({result.anomalies}/{result.processed} = {ratio_anomaly:.2%})",
                    extra_data={"tenant_id": params.tenant_id, "anomalies": result.anomalies,
                                 "blocked": result.blocked, "passed": result.passed},
                )
            except Exception as exc:
                logger.warning(f"告警推送失败: {exc}")
        elif result.blocked >= int(settings.cleaning.CLEAN_BLOCKED_ALERT_COUNT or 10):
            try:
                alert_service.service_exception_sync(
                    f"[T10][{params.task_id}] 高违规内容阈值触发 ({result.blocked} 条)",
                    extra_data={"tenant_id": params.tenant_id, "blocked": result.blocked},
                )
            except Exception as exc:
                logger.warning(f"告警推送失败: {exc}")

    def _write_task_status(self, params: CleanTaskParams, result: CleanRunResult) -> None:
        try:
            from infra.db_base import database as _
            pass  # 预留扩展
        except Exception:
            pass

    def _finalize(self, params, result, opportunities, anomalies, pipeline_pairs=None):
        if params.run_storage:
            try:
                result.passed = self.storage.upsert_opportunities(opportunities)
                result.anomalies = self.storage.upsert_anomalies(anomalies)
            except Exception as exc:
                logger.warning(f"_finalize storage 失败: {exc}")
                result.status = "partial"
        else:
            result.passed = len(opportunities)
            result.anomalies = len(anomalies)
        result.finished_at = result.started_at


__all__ = ["DataCleanPipeline"]
