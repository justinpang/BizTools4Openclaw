"""business/customer_send/models — Pydantic 数据模型。"""

from __future__ import annotations

from datetime import datetime, timezone

from pydantic import BaseModel, Field


class SendTarget(BaseModel):
    """单个商机触达目标。"""

    opportunity_id: str
    tenant_id: str
    customer_name: str
    contact_email: str | None = None
    contact_phone: str | None = None
    contact_wechat: str | None = None
    contact_feishu: str | None = None
    contact_industry: str | None = None
    contact_region: str | None = None
    need_keywords: list[str] = Field(default_factory=list)
    opportunity_title: str = ""
    opportunity_score: int = 0
    landing_page_url: str | None = None

    model_config = {"extra": "allow"}


class BatchSendParams(BaseModel):
    """批量触达任务入参。"""

    task_id: str
    tenant_id: str
    channels: list[str] = Field(default_factory=lambda: ["email", "wechat", "feishu"])
    template_name: str = "default"
    targets: list[SendTarget] = Field(default_factory=list)
    dry_run: bool = False
    enable_h5: bool = False
    batch_size: int = 50
    caller: str | None = None

    model_config = {"extra": "ignore"}


class SingleSendResult(BaseModel):
    """单次发送结果（1 channel × 1 target）。"""

    send_id: str
    channel: str
    opportunity_id: str
    success: bool
    status: str
    reason: str | None = None
    masked_recipient: str = ""
    attempts: int = 0
    account_id: str | None = None
    cost_ms: int = 0
    h5_page_url: str | None = None


class BatchSendResult(BaseModel):
    """批量触达汇总结果。"""

    task_id: str
    status: str = "ok"
    total: int = 0
    success: int = 0
    failed: int = 0
    blocked: int = 0
    rate_limited: int = 0
    details: list[SingleSendResult] = Field(default_factory=list)
    started_at: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat() + "Z")
    finished_at: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat() + "Z")


class SendBehaviorLog(BaseModel):
    """触达行为埋点（sent/opened/clicked/submitted/blocked/...）。"""

    behavior_id: str
    tenant_id: str
    opportunity_id: str
    channel: str
    event: str
    recipient_masked: str = ""
    h5_page_id: str | None = None
    http_path: str | None = None
    payload_snapshot: dict = Field(default_factory=dict)
    remote_ip_masked: str | None = None
    user_agent_hash: str | None = None
    created_at: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat() + "Z")


class H5PageSpec(BaseModel):
    """H5 落地页生成规格。"""

    page_id: str
    tenant_id: str
    opportunity_id: str
    customer_name_masked: str
    industry: str | None = None
    region: str | None = None
    keywords: list[str] = Field(default_factory=list)
    title: str
    summary: str = ""
    cta_label: str = "立即报名"
    form_fields: list[dict] = Field(default_factory=list)
    expire_at: str | None = None


__all__ = [
    "SendTarget",
    "BatchSendParams",
    "SingleSendResult",
    "BatchSendResult",
    "SendBehaviorLog",
    "H5PageSpec",
]
