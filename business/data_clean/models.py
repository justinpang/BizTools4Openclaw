from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field


# =====================
# 任务参数
# =====================


class CleanTaskParams(BaseModel):
    """数据清洗任务参数。"""

    task_id: str = Field(default_factory=lambda: uuid.uuid4().hex[:12])
    tenant_id: str = "default"
    batch_size: int = 200
    cursor: str | None = None          # 分页游标；None = 从头开始
    spider_names: list[str] | None = None  # 只处理指定 spider；None = 所有
    since: str | None = None           # 只处理 ≥ 该日期的记录（YYYY-MM-DD）
    run_engine: bool = True            # 是否运行 T07 pipeline；false = 只做实体抽取
    run_storage: bool = True           # 是否写入 DB；false = 干跑
    extra: dict[str, Any] = Field(default_factory=dict)


# =====================
# 原始记录（从 SpiderRawData 加载）
# =====================


@dataclass
class RawRecord:
    """从 raw_spider_data 表加载出的单条记录。"""

    id: int
    tenant_id: str
    spider_name: str
    source_url: str
    source_id: str
    raw_text: str
    raw_payload: dict[str, Any] = field(default_factory=dict)
    captured_at: datetime | None = None
    source_country: str | None = None
    fetch_status: int = 0
    fetch_error: str | None = None


# =====================
# 实体抽取结果
# =====================


class EntityExtract(BaseModel):
    company_names: list[str] = Field(default_factory=list)
    phone_numbers: list[str] = Field(default_factory=list)
    wechat_ids: list[str] = Field(default_factory=list)
    industry_tags: list[str] = Field(default_factory=list)
    region: str = ""
    keywords: list[str] = Field(default_factory=list)
    budget: dict[str, Any] = Field(default_factory=dict)
    estimated_text_length: int = 0


# =====================
# 合规结果
# =====================


class ComplianceResult(BaseModel):
    risk_level: str = "low"
    sensitive_hits: int = 0
    blocked: bool = False
    masked_text: str = ""
    report: dict[str, Any] = Field(default_factory=dict)


# =====================
# 引擎结果（从 T07 写入）
# =====================


class EngineScore(BaseModel):
    total: int = 0
    grade: str = "normal"
    dimension_scores: dict[str, int] = Field(default_factory=dict)
    blacklisted: bool = False
    is_duplicate_of: str | None = None


# =====================
# 标准化输出
# =====================


class SourceMeta(BaseModel):
    spider_name: str
    source_id: str
    source_url: str
    captured_at: str = ""
    raw_record_id: int | None = None


class PipelineMeta(BaseModel):
    version: str
    processed_at: str = Field(default_factory=lambda: datetime.utcnow().isoformat() + "Z")
    trace_steps: list[str] = Field(default_factory=list)


class StructuredOpportunity(BaseModel):
    """OpenClaw 标准输入格式 —— 写入 structured_opportunity 表。"""

    opportunity_id: str
    tenant_id: str
    title: str = ""
    content_snippet: str = ""
    entities: EntityExtract = Field(default_factory=EntityExtract)
    source: SourceMeta
    compliance: ComplianceResult = Field(default_factory=ComplianceResult)
    score: EngineScore = Field(default_factory=EngineScore)
    pipeline: PipelineMeta


# =====================
# 异常池记录
# =====================


class AnomalyRecord(BaseModel):
    """解析失败 / 高违规 / 引擎失败的记录，进入异常池供人工复核。"""

    anomaly_id: str
    tenant_id: str
    source_record_id: int | None = None
    type: str                      # extract_fail | high_violation | engine_fail | dirty
    severity: str = "warn"         # info / warn / error
    reason: str = ""
    raw_snippet: str = ""
    pipeline_version: str = ""
    created_at: str = Field(default_factory=lambda: datetime.utcnow().isoformat() + "Z")
    needs_review: bool = True
    reviewed_at: str | None = None
    reviewed_by: str | None = None
    review_note: str | None = None
    spider_name: str = ""
    source_url: str = ""


# =====================
# 任务运行结果
# =====================


class CleanRunResult(BaseModel):
    task_id: str
    status: str = "ok"
    processed: int = 0
    passed: int = 0
    anomalies: int = 0
    blocked: int = 0
    engine_total: int = 0
    next_cursor: str | None = None
    started_at: str = Field(default_factory=lambda: datetime.utcnow().isoformat() + "Z")
    finished_at: str | None = None
    duration_ms: int | None = None
    first_error: str | None = None


__all__ = [
    "CleanTaskParams",
    "RawRecord",
    "EntityExtract",
    "ComplianceResult",
    "EngineScore",
    "StructuredOpportunity",
    "SourceMeta",
    "PipelineMeta",
    "AnomalyRecord",
    "CleanRunResult",
]
