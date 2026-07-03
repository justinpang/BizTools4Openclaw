"""数据清洗 - ORM 模型（仅在 business/data_clean 内使用）。"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from sqlalchemy import JSON, Boolean, Column, DateTime, Integer, SmallInteger, String, Text, Index
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

from infra.db_base import database


class _Base(DeclarativeBase):
    pass


# =====================
# StructuredOpportunity
# =====================


class StructuredOpportunityRow(_Base):
    __tablename__ = "structured_opportunity"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    tenant_id: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    opportunity_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    title: Mapped[str] = mapped_column(String(512), nullable=False, default="")
    content_snippet: Mapped[str] = mapped_column(Text, nullable=True)
    entities_json: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    source_spider_name: Mapped[str] = mapped_column(String(128), nullable=False, default="")
    source_id: Mapped[str] = mapped_column(String(256), nullable=True)
    source_url: Mapped[str] = mapped_column(String(1024), nullable=True)
    source_captured_at: Mapped[str] = mapped_column(String(64), nullable=True)
    source_raw_record_id: Mapped[int] = mapped_column(Integer, nullable=True)
    compliance_risk: Mapped[str] = mapped_column(String(32), nullable=False, default="low")
    compliance_hits: Mapped[int] = mapped_column(SmallInteger, nullable=False, default=0)
    compliance_blocked: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    compliance_json: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    score_total: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    score_grade: Mapped[str] = mapped_column(String(32), nullable=False, default="normal")
    score_breakdown_json: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    score_blacklisted: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    score_duplicate_of: Mapped[str] = mapped_column(String(128), nullable=True)
    pipeline_version: Mapped[str] = mapped_column(String(64), nullable=False, default="")
    pipeline_processed_at: Mapped[str] = mapped_column(String(64), nullable=True)
    pipeline_trace: Mapped[str] = mapped_column(String(512), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=lambda: datetime.now(timezone.utc), index=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc))

    __table_args__ = (
        Index("ix_struct_opp_unique", "tenant_id", "opportunity_id", unique=True),
    )


# =====================
# AnomalyPool
# =====================


class AnomalyPoolRow(_Base):
    __tablename__ = "opportunity_anomaly_pool"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    tenant_id: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    anomaly_id: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    source_record_id: Mapped[int] = mapped_column(Integer, nullable=True)
    spider_name: Mapped[str] = mapped_column(String(128), nullable=True)
    source_url: Mapped[str] = mapped_column(String(1024), nullable=True)
    type: Mapped[str] = mapped_column(String(64), nullable=False)
    severity: Mapped[str] = mapped_column(String(16), nullable=False, default="warn")
    reason: Mapped[str] = mapped_column(String(512), nullable=True)
    raw_snippet: Mapped[str] = mapped_column(Text, nullable=True)
    pipeline_version: Mapped[str] = mapped_column(String(64), nullable=True)
    created_at: Mapped[str] = mapped_column(String(64), nullable=True)
    needs_review: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    reviewed_at: Mapped[str] = mapped_column(String(64), nullable=True)
    reviewed_by: Mapped[str] = mapped_column(String(128), nullable=True)
    review_note: Mapped[str] = mapped_column(String(512), nullable=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc))
    __table_args__ = (
        Index("ix_anomaly_unique", "tenant_id", "anomaly_id", unique=True),
    )


# =====================
# 建表
# =====================


def ensure_tables() -> None:
    """确保两张表存在。"""
    if not hasattr(database, "engine") or database.engine is None:
        # 可能未配置 DB；尝试 ensure_connected 以初始化 engine
        try:
            database.ensure_connected()
        except Exception:
            pass
        if getattr(database, "engine", None) is None:
            return
    try:
        _Base.metadata.create_all(bind=database.engine)
    except Exception as exc:
        logger.info(f"表创建 (忽略): {exc}")


__all__ = ["StructuredOpportunityRow", "AnomalyPoolRow", "ensure_tables", "_Base"]
