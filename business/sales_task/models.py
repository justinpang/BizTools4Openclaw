"""business/sales_task/models — Pydantic 数据模型 + 枚举。"""

from __future__ import annotations

import enum
import hashlib
from datetime import datetime, timezone

from pydantic import BaseModel, Field


# ========== 枚举 ==========

class OpportunityStatus(str, enum.Enum):
    NEW = "NEW"
    ASSIGNED = "ASSIGNED"
    FOLLOWING = "FOLLOWING"
    COMMUNICATING = "COMMUNICATING"
    HIGH_INTENT = "HIGH_INTENT"
    CLOSED_WON = "CLOSED_WON"
    LOST = "LOST"


class ReminderLevel(str, enum.Enum):
    NOTIFY = "NOTIFY"
    FIRST = "FIRST"
    SECOND = "SECOND"
    OVERDUE = "OVERDUE"
    BATCH_OVERDUE = "BATCH_OVERDUE"


# ========== 工具函数 ==========

def _now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _make_id(prefix: str, *parts: str) -> str:
    raw = "|".join(str(p) for p in parts) + "|" + _now_iso()
    return f"{prefix}_{hashlib.md5(raw.encode('utf-8')).hexdigest()[:12]}"


# ========== 数据模型 ==========

class Salesperson(BaseModel):
    """销售员配置。"""

    sales_id: str
    tenant_id: str
    name: str
    industries: list[str] = Field(default_factory=list)
    regions: list[str] = Field(default_factory=list)
    min_score: int = 0
    weight: float = 1.0
    current_load: int = 0
    email: str | None = None
    wechat: str | None = None
    feishu: str | None = None
    group: str = "default"


class Opportunity(BaseModel):
    """销售流程中的商机对象。"""

    opportunity_id: str
    tenant_id: str
    customer_name: str
    contact_email: str | None = None
    contact_phone: str | None = None
    industry: str | None = None
    region: str | None = None
    need_keywords: list[str] = Field(default_factory=list)
    score: int = 0
    status: str = OpportunityStatus.NEW.value
    assigned_sales_id: str | None = None
    assigned_at: str | None = None
    last_follow_at: str | None = None
    tags: list[str] = Field(default_factory=list)
    source_batch_id: str | None = None
    created_at: str = Field(default_factory=_now_iso)
    updated_at: str | None = None


class FollowUpRecord(BaseModel):
    """跟进记录。"""

    follow_id: str
    opportunity_id: str
    tenant_id: str
    sales_id: str
    channel: str
    content: str
    next_follow_at: str | None = None
    created_at: str = Field(default_factory=_now_iso)


class SalesOperationLog(BaseModel):
    """全生命周期操作日志。"""

    log_id: str
    tenant_id: str
    opportunity_id: str
    sales_id: str
    op_type: str
    before_value: str | None = None
    after_value: str | None = None
    detail: str | None = None
    created_at: str = Field(default_factory=_now_iso)


class AssignmentParams(BaseModel):
    """自动分配参数。"""

    task_id: str
    tenant_id: str
    opportunity_ids: list[str] | None = None
    mode: str = "batch"
    dry_run: bool = False


class ReminderParams(BaseModel):
    """多级提醒参数。"""

    task_id: str
    tenant_id: str
    custom_cycles: dict[str, int] | None = None
    dry_run: bool = False


class FunnelStats(BaseModel):
    """转化漏斗统计结果。"""

    tenant_id: str
    period_start: str
    period_end: str
    collected: int = 0
    cleaned: int = 0
    reached: int = 0
    followed: int = 0
    closed_won: int = 0
    conversion_rates: dict[str, float] = Field(default_factory=dict)


class SalesTaskJobResult(BaseModel):
    """任务执行结果汇总。"""

    task_id: str
    tenant_id: str
    job_type: str
    processed: int = 0
    assigned: int = 0
    reminded: int = 0
    overdue_count: int = 0
    long_unassigned: int = 0
    status: str = "OK"
    reason: str | None = None
    started_at: str = Field(default_factory=_now_iso)
    finished_at: str | None = None
    detail: dict[str, object] = Field(default_factory=dict)


__all__ = [
    "OpportunityStatus",
    "ReminderLevel",
    "Salesperson",
    "Opportunity",
    "FollowUpRecord",
    "SalesOperationLog",
    "AssignmentParams",
    "ReminderParams",
    "FunnelStats",
    "SalesTaskJobResult",
    "_make_id",
    "_now_iso",
]
