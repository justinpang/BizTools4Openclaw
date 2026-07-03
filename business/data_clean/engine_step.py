from __future__ import annotations

import uuid
from typing import TYPE_CHECKING

from infra.logger_setup import get_logger
from core.data_core import opportunity_pipeline  # T07 通用流水线
from configs.settings import settings

from business.data_clean.models import AnomalyRecord, EntityExtract, RawRecord

if TYPE_CHECKING:
    from core.data_core.pipeline import PipelineResult, ScoredOpportunity

logger = get_logger("data_clean.engine")


# =====================
# 引擎步骤：调用 T07 打分/去重/合并
# =====================


def _build_clue(rec: RawRecord, entities: EntityExtract) -> dict:
    """把 RawRecord + EntityExtract 拼成 process_batch 所需的 dict。"""
    title = ""
    if isinstance(rec.raw_payload, dict) and rec.raw_payload:
        title = str(rec.raw_payload.get("title") or "")
    if not title:
        text = (rec.raw_text or "")[:80]
        title = text.split("\n")[0] if text else rec.spider_name

    return {
        "clue_id": rec.source_id or f"clue_{rec.id}",
        "source": rec.spider_name,
        "title": title,
        "content": rec.raw_text or "",
        "company_name": (entities.company_names or [None])[0] if entities.company_names else None,
        "contact_phones": list(entities.phone_numbers),
        "contact_wechats": list(entities.wechat_ids),
        "industry": entities.industry_tags[0] if entities.industry_tags else None,
        "platforms": [rec.spider_name],
        "city": entities.region or None,
        "first_capture_at": rec.captured_at.isoformat() if rec.captured_at else None,
    }


class EngineStep:
    """调用 T07 opportunity_pipeline.process_batch。

    输入：[(RawRecord, EntityExtract), ...]
    输出：PipelineResult（含 items: list[ScoredOpportunity]）
        + 失败记录对应的 AnomalyRecord。
    """

    def __init__(self) -> None:
        pass

    def process_batch(
        self,
        pairs: list[tuple[RawRecord, EntityExtract]],
    ) -> tuple["PipelineResult", list[AnomalyRecord]]:
        """返回 (result, anomalies) —— anomalies 仅在 process_batch 抛异常时非空。"""
        if not pairs:
            from core.data_core.pipeline import PipelineResult

            return PipelineResult(total_input=0), []

        clues: list[dict] = []
        for rec, entities in pairs:
            try:
                clues.append(_build_clue(rec, entities))
            except Exception as exc:
                logger.warning(f"_build_clue failed: {exc}")

        if not clues:
            from core.data_core.pipeline import PipelineResult

            return PipelineResult(total_input=len(pairs)), []

        try:
            result = opportunity_pipeline.process_batch(clues)
        except Exception as exc:
            # 引擎整体失败：把所有记录标记为 engine_fail
            logger.error(f"opportunity_pipeline.process_batch 失败: {exc}")
            anomalies = [
                AnomalyRecord(
                    anomaly_id=f"a_eng_{uuid.uuid4().hex[:10]}_{rec.id}",
                    tenant_id=rec.tenant_id,
                    source_record_id=rec.id,
                    type="engine_fail",
                    severity="error",
                    reason=f"engine_exception: {exc}",
                    raw_snippet=(rec.raw_text or "")[:200],
                    pipeline_version=str(settings.cleaning.CLEAN_PIPELINE_VERSION),
                    needs_review=True,
                    spider_name=rec.spider_name,
                    source_url=rec.source_url,
                )
                for rec, _ in pairs
            ]
            from core.data_core.pipeline import PipelineResult

            return PipelineResult(total_input=len(pairs)), anomalies

        return result, []


__all__ = ["EngineStep"]
