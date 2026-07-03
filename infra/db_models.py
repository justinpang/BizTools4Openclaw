from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional

try:
    from sqlalchemy import (
        BigInteger,
        Boolean,
        Column,
        ForeignKey,
        Index,
        Integer,
        JSON,
        Numeric,
        SmallInteger,
        String,
        Text,
        CHAR,
        TIMESTAMP,
    )
    from sqlalchemy.orm import Mapped, mapped_column, relationship
except Exception:  # pragma: no cover - 环境缺 SQLAlchemy 时用占位，不影响 import
    Mapped = Any = type("Any", (), {})  # type: ignore[assignment,misc]

    def mapped_column(*args, **kwargs):  # type: ignore[misc,no-redef]
        raise RuntimeError("SQLAlchemy 未安装")

    class JSON:  # type: ignore[no-redef]
        pass

from core.compliance.sensitive_crypto import SensitiveString
from infra.db_base import Base, BaseModel, _utc_now


# ========== 原始爬虫数据表 ==========

class SpiderRawData(Base, BaseModel):
    __tablename__ = "spider_raw_data"

    spider_name: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    source_url: Mapped[str] = mapped_column(String(1024), nullable=False)
    source_id: Mapped[Optional[str]] = mapped_column(String(256), nullable=True)
    raw_payload: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    raw_text: Mapped[Optional[str]] = mapped_column(Text(), nullable=True)
    fetch_status: Mapped[int] = mapped_column(SmallInteger(), nullable=False, default=0)
    fetch_error: Mapped[Optional[str]] = mapped_column(String(512), nullable=True)
    captured_at: Mapped[datetime] = mapped_column(TIMESTAMP(timezone=False), nullable=False,
                                                   default=_utc_now, index=True)
    source_country: Mapped[Optional[str]] = mapped_column(CHAR(2), nullable=True)

    __table_args__ = (
        Index("idx_spider_raw_source_id", "tenant_id", "spider_name", "source_id", unique=True),
        Index("idx_spider_raw_captured", "captured_at"),
        Index("idx_spider_raw_archived_name", "is_archived", "spider_name"),
    )


# ========== 结构化商机表 ==========

class BusinessOpportunity(Base, BaseModel):
    __tablename__ = "business_opportunities"

    title: Mapped[str] = mapped_column(String(512), nullable=False)
    description: Mapped[Optional[str]] = mapped_column(Text(), nullable=True)
    company_name: Mapped[Optional[str]] = mapped_column(String(256), nullable=True, index=True)
    company_domain: Mapped[Optional[str]] = mapped_column(String(256), nullable=True)
    industry: Mapped[Optional[str]] = mapped_column(String(64), nullable=True, index=True)
    country: Mapped[Optional[str]] = mapped_column(CHAR(2), nullable=True)
    city: Mapped[Optional[str]] = mapped_column(String(128), nullable=True)
    contact_name: Mapped[Optional[str]] = mapped_column(String(128), nullable=True)
    contact_phone: Mapped[Optional[str]] = mapped_column(SensitiveString(256), nullable=True)
    contact_email: Mapped[Optional[str]] = mapped_column(SensitiveString(256), nullable=True)
    contact_wechat: Mapped[Optional[str]] = mapped_column(SensitiveString(256), nullable=True)
    estimated_value: Mapped[Optional[float]] = mapped_column(Numeric(18, 2), nullable=True, index=True)
    confidence_score: Mapped[Optional[float]] = mapped_column(Numeric(5, 2), nullable=True)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="new", index=True)
    source_raw_id: Mapped[Optional[int]] = mapped_column(
        BigInteger(), ForeignKey("spider_raw_data.id", ondelete="SET NULL"), nullable=True, index=True
    )
    tags: Mapped[Optional[str]] = mapped_column(String(512), nullable=True)
    last_active_at: Mapped[Optional[datetime]] = mapped_column(TIMESTAMP(timezone=False), nullable=True, index=True)

    # 关系（用于级联查询 / JOIN）
    spider_raw = relationship("SpiderRawData", remote_side="SpiderRawData.id")

    __table_args__ = (
        Index("idx_biz_tenant_status", "tenant_id", "status"),
        Index("idx_biz_tenant_value", "tenant_id", "estimated_value"),
        Index("idx_biz_archived_active", "is_archived", "last_active_at"),
    )


# ========== 销售跟进任务表 ==========

class SalesTask(Base, BaseModel):
    __tablename__ = "sales_tasks"

    opportunity_id: Mapped[int] = mapped_column(
        BigInteger(), ForeignKey("business_opportunities.id", ondelete="CASCADE"), nullable=False, index=True
    )
    assigned_to: Mapped[Optional[str]] = mapped_column(String(128), nullable=True, index=True)
    task_type: Mapped[str] = mapped_column(String(32), nullable=False, default="call")
    priority: Mapped[int] = mapped_column(SmallInteger(), nullable=False, default=1)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="todo", index=True)
    scheduled_at: Mapped[Optional[datetime]] = mapped_column(TIMESTAMP(timezone=False), nullable=True, index=True)
    completed_at: Mapped[Optional[datetime]] = mapped_column(TIMESTAMP(timezone=False), nullable=True)
    result_note: Mapped[Optional[str]] = mapped_column(Text(), nullable=True)

    opportunity = relationship("BusinessOpportunity", remote_side="BusinessOpportunity.id")

    __table_args__ = (
        Index("idx_sales_tenant_status_priority", "tenant_id", "status", "priority"),
    )


# ========== 系统操作日志表 ==========

class SystemLog(Base, BaseModel):
    __tablename__ = "system_logs"

    log_level: Mapped[str] = mapped_column(String(16), nullable=False, default="info", index=True)
    log_type: Mapped[str] = mapped_column(String(64), nullable=False, default="system", index=True)
    actor: Mapped[Optional[str]] = mapped_column(String(128), nullable=True)
    target_resource: Mapped[Optional[str]] = mapped_column(String(256), nullable=True)
    message: Mapped[str] = mapped_column(Text(), nullable=False)
    extra: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)
    request_id: Mapped[Optional[str]] = mapped_column(String(128), nullable=True)
    ip_address: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    duration_ms: Mapped[Optional[int]] = mapped_column(Integer(), nullable=True)

    __table_args__ = (
        Index("idx_syslog_tenant_type_time", "tenant_id", "log_type", "created_at"),
        Index("idx_syslog_level_time", "log_level", "created_at"),
        Index("idx_syslog_actor", "actor"),
    )


__all__ = [
    "SpiderRawData",
    "BusinessOpportunity",
    "SalesTask",
    "SystemLog",
]
