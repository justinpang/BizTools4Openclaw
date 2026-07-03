from __future__ import annotations

import hashlib
from typing import TYPE_CHECKING

from infra.logger_setup import get_logger
from configs.settings import settings

from business.data_clean.models import (
    ComplianceResult,
    EngineScore,
    EntityExtract,
    PipelineMeta,
    RawRecord,
    StructuredOpportunity,
    SourceMeta,
)

if TYPE_CHECKING:
    from core.data_core.pipeline import ScoredOpportunity

logger = get_logger("data_clean.normalizer")


# =====================
# Normalizer
# =====================


class Normalizer:
    """把 RawRecord + EntityExtract + 合规结果 + ScoredOpportunity 合并成 StructuredOpportunity。"""

    VERSION_KEY = str(settings.cleaning.CLEAN_PIPELINE_VERSION)

    def __init__(self) -> None:
        pass

    # ------- 工具 -------

    def _make_opportunity_id(self, rec: RawRecord) -> str:
        key = f"{rec.tenant_id}|{rec.spider_name}|{rec.source_id}|{self.VERSION_KEY}"
        digest = hashlib.md5(key.encode("utf-8")).hexdigest()[:12]
        return f"opp_{digest}"

    def _derive_title(self, rec: RawRecord) -> str:
        if isinstance(rec.raw_payload, dict) and rec.raw_payload:
            title = rec.raw_payload.get("title") or ""
            if title:
                return str(title)[:200]
        text = (rec.raw_text or "").strip()
        if text:
            # 取第一行
            return text.split("\n")[0][:200]
        return f"{rec.spider_name} 来源"

    def _derive_content(self, rec: RawRecord, masked_text: str = "") -> str:
        text = masked_text or rec.raw_text or ""
        return text[:2000].strip()

    # ------- 单个标准化 -------

    def normalize(
        self,
        rec: RawRecord,
        entities: EntityExtract,
        compliance: ComplianceResult,
        scored: "ScoredOpportunity | None",
    ) -> StructuredOpportunity:
        # 基本字段
        opportunity_id = self._make_opportunity_id(rec)
        title = self._derive_title(rec)
        snippet = self._derive_content(rec, compliance.masked_text if compliance else "")

        # 来源
        source = SourceMeta(
            spider_name=rec.spider_name,
            source_id=rec.source_id or "",
            source_url=rec.source_url or "",
            captured_at=(rec.captured_at.isoformat() if hasattr(rec.captured_at, "isoformat") else (rec.captured_at or "")),
            raw_record_id=rec.id,
        )

        # 评分
        if scored is not None:
            breakdown: dict[str, int] = {}
            for k, v in (scored.score_breakdown or {}).items():
                try:
                    breakdown[str(k)] = int(v)
                except Exception:
                    continue
            # 如果没有 breakdown，用总评分作为单一维度
            if not breakdown and scored.score:
                breakdown = {"total": int(scored.score)}
            engine_score = EngineScore(
                total=int(scored.score) if scored.score else 0,
                grade=str(scored.grade or "normal"),
                dimension_scores=breakdown,
                blacklisted=bool(getattr(scored, "is_blocked", False)),
                is_duplicate_of=str(scored.duplicate_of) if getattr(scored, "duplicate_of", None) else None,
            )
        else:
            engine_score = EngineScore()

        pipeline_meta = PipelineMeta(
            version=self.VERSION_KEY,
            trace_steps=["load", "filter", "extract", "compliance", "engine", "normalize"],
        )

        return StructuredOpportunity(
            opportunity_id=opportunity_id,
            tenant_id=rec.tenant_id,
            title=title,
            content_snippet=snippet,
            entities=entities,
            source=source,
            compliance=compliance,
            score=engine_score,
            pipeline=pipeline_meta,
        )


__all__ = ["Normalizer"]
