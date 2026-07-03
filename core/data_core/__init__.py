from __future__ import annotations

from core.data_core.blacklist_filter import (
    BlacklistFilter,
    BlacklistItem,
    BlacklistFilterResult,
    blacklist_filter,
)
from core.data_core.dedupe_engine import (
    DedupMatch,
    DeduplicationResult,
    DedupeEngine,
    dedupe_engine,
)
from core.data_core.merge_engine import (
    MergedClue,
    MergeResult,
    MergeEngine,
    merge_engine,
)
from core.data_core.scoring_engine import (
    GRADE_HIGH,
    GRADE_JUNK,
    GRADE_LOW,
    GRADE_NORMAL,
    ScoreResult,
    ScoringEngine,
    scoring_engine,
)
from core.data_core.pipeline import (
    OpportunityPipeline,
    PipelineResult,
    ScoredOpportunity,
    opportunity_pipeline,
)

__all__ = [
    "BlacklistFilter", "BlacklistItem", "BlacklistFilterResult", "blacklist_filter",
    "DedupMatch", "DeduplicationResult", "DedupeEngine", "dedupe_engine",
    "MergedClue", "MergeResult", "MergeEngine", "merge_engine",
    "GRADE_HIGH", "GRADE_JUNK", "GRADE_LOW", "GRADE_NORMAL",
    "ScoreResult", "ScoringEngine", "scoring_engine",
    "OpportunityPipeline", "PipelineResult", "ScoredOpportunity", "opportunity_pipeline",
]
