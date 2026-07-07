"""business/custom_spider/data_models — 采集方案 ORM 模型。

包含 4 张表：
  - custom_spider_plans          (采集方案主表)
  - custom_spider_plan_versions  (规则版本表，支持回滚)
  - custom_spider_runs           (采集运行记录表)
  - custom_spider_operation_logs (操作日志表)

所有模型继承 infra.db_base.Base + infra.db_base.BaseModel，
自动获得 id/tenant_id/is_archived/created_at/updated_at 字段。
"""

from __future__ import annotations

import json
from datetime import datetime
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
        String,
        Text,
        TIMESTAMP,
    )
    from sqlalchemy.orm import Mapped, mapped_column
except Exception:  # pragma: no cover - 环境缺 SQLAlchemy 时用占位
    Mapped = Any = type("Any", (), {})  # type: ignore[assignment,misc]

    def mapped_column(*args, **kwargs):  # type: ignore[no-redef]
        raise RuntimeError("SQLAlchemy 未安装")

    class JSON:  # type: ignore[no-redef]
        pass


from core.compliance.sensitive_crypto import SensitiveString  # noqa: E402
from infra.db_base import Base, BaseModel, _utc_now  # noqa: E402


# ============================================================
# 1. 采集方案主表
# ============================================================
class CustomSpiderPlan(Base, BaseModel):
    __tablename__ = "custom_spider_plans"

    plan_name: Mapped[str] = mapped_column(String(128), nullable=False)
    plan_code: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    target_domain: Mapped[str] = mapped_column(String(256), nullable=False, index=True)
    spider_type: Mapped[str] = mapped_column(String(32), nullable=False, default="generic", index=True)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="draft", index=True)
    created_by: Mapped[Optional[str]] = mapped_column(String(128), nullable=True)
    description: Mapped[Optional[str]] = mapped_column(Text(), nullable=True)

    # 核心规则（T25 CrawlRuleSet 序列化）
    rule_config: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    schedule_config: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)
    increment_config: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)

    # 敏感字段（AES256 自动加解密）
    cookie_encrypted: Mapped[Optional[str]] = mapped_column(SensitiveString(2048), nullable=True)

    # 版本与统计
    current_version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    run_count_total: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    run_count_success: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    items_total: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    # 最近一次运行信息
    last_run_at: Mapped[Optional[datetime]] = mapped_column(TIMESTAMP(timezone=False), nullable=True, index=True)
    last_run_status: Mapped[Optional[str]] = mapped_column(String(32), nullable=True)
    last_run_error: Mapped[Optional[str]] = mapped_column(String(512), nullable=True)

    __table_args__ = (
        Index("idx_plan_tenant_status", "tenant_id", "status"),
        Index("idx_plan_tenant_domain", "tenant_id", "target_domain"),
        Index("idx_plan_tenant_code", "tenant_id", "plan_code", unique=True),
    )

    # ---- 便捷方法 ----
    def to_public_dict(self) -> dict:
        """对外安全字典（排除 cookie_encrypted）。"""
        data = {
            "id": self.id,
            "plan_name": self.plan_name,
            "plan_code": self.plan_code,
            "target_domain": self.target_domain,
            "spider_type": self.spider_type,
            "status": self.status,
            "created_by": self.created_by,
            "description": self.description,
            "rule_config": self.rule_config,
            "schedule_config": self.schedule_config,
            "increment_config": self.increment_config,
            "current_version": self.current_version,
            "run_count_total": self.run_count_total,
            "run_count_success": self.run_count_success,
            "items_total": self.items_total,
            "last_run_status": self.last_run_status,
            "last_run_at": self.last_run_at.isoformat() if self.last_run_at else None,
            "last_run_error": self.last_run_error,
            "created_at": self.created_at.isoformat() if getattr(self.created_at, "isoformat", None) else str(self.created_at),
            "updated_at": self.updated_at.isoformat() if getattr(self.updated_at, "isoformat", None) else str(self.updated_at),
        }
        return data


# ============================================================
# 2. 规则版本表
# ============================================================
class CustomSpiderPlanVersion(Base, BaseModel):
    __tablename__ = "custom_spider_plan_versions"

    plan_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("custom_spider_plans.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    version_number: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    rule_config: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    schedule_config: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)
    change_note: Mapped[Optional[str]] = mapped_column(String(512), nullable=True)
    changed_by: Mapped[Optional[str]] = mapped_column(String(128), nullable=True)
    is_current: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, index=True)
    rollback_from_version: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)

    __table_args__ = (
        Index("idx_ver_plan_version", "plan_id", "version_number", unique=True),
        Index("idx_ver_plan_current", "plan_id", "is_current"),
    )

    def to_public_dict(self) -> dict:
        return {
            "id": self.id,
            "plan_id": self.plan_id,
            "version_number": self.version_number,
            "rule_config": self.rule_config,
            "schedule_config": self.schedule_config,
            "change_note": self.change_note,
            "changed_by": self.changed_by,
            "is_current": self.is_current,
            "rollback_from_version": self.rollback_from_version,
            "created_at": self.created_at.isoformat() if getattr(self.created_at, "isoformat", None) else str(self.created_at),
        }


# ============================================================
# 3. 采集运行记录表
# ============================================================
class CustomSpiderRun(Base, BaseModel):
    __tablename__ = "custom_spider_runs"

    plan_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("custom_spider_plans.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    run_mode: Mapped[str] = mapped_column(String(32), nullable=False, default="manual", index=True)
    trigger_by: Mapped[Optional[str]] = mapped_column(String(128), nullable=True)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="pending", index=True)
    items_total: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    items_success: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    items_failed: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    field_match_rate: Mapped[Optional[float]] = mapped_column(Numeric(5, 2), nullable=True)
    error_summary: Mapped[Optional[str]] = mapped_column(String(1024), nullable=True)
    alerts_json: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)
    duration_ms: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    started_at: Mapped[datetime] = mapped_column(TIMESTAMP(timezone=False), nullable=False, default=_utc_now)
    finished_at: Mapped[Optional[datetime]] = mapped_column(TIMESTAMP(timezone=False), nullable=True)

    __table_args__ = (
        Index("idx_run_plan_status", "plan_id", "status"),
        Index("idx_run_plan_time", "plan_id", "started_at"),
        Index("idx_run_tenant_status", "tenant_id", "status", "started_at"),
    )

    def to_public_dict(self) -> dict:
        return {
            "id": self.id,
            "plan_id": self.plan_id,
            "run_mode": self.run_mode,
            "trigger_by": self.trigger_by,
            "status": self.status,
            "items_total": self.items_total,
            "items_success": self.items_success,
            "items_failed": self.items_failed,
            "field_match_rate": float(self.field_match_rate) if self.field_match_rate is not None else None,
            "error_summary": self.error_summary,
            "alerts": self.alerts_json or [],
            "duration_ms": self.duration_ms,
            "started_at": self.started_at.isoformat() if getattr(self.started_at, "isoformat", None) else str(self.started_at),
            "finished_at": self.finished_at.isoformat() if getattr(self.finished_at, "isoformat", None) else None,
        }


# ============================================================
# 4. 操作日志表
# ============================================================
class CustomSpiderOperationLog(Base, BaseModel):
    __tablename__ = "custom_spider_operation_logs"

    plan_id: Mapped[Optional[int]] = mapped_column(
        BigInteger,
        ForeignKey("custom_spider_plans.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    operation: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    operator: Mapped[Optional[str]] = mapped_column(String(128), nullable=True)
    detail: Mapped[Optional[str]] = mapped_column(Text(), nullable=True)
    ip_address: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    success: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    error_message: Mapped[Optional[str]] = mapped_column(String(512), nullable=True)

    __table_args__ = (
        Index("idx_oplog_plan_op", "plan_id", "operation", "created_at"),
        Index("idx_oplog_tenant_time", "tenant_id", "created_at"),
    )

    def to_public_dict(self) -> dict:
        return {
            "id": self.id,
            "plan_id": self.plan_id,
            "operation": self.operation,
            "operator": self.operator,
            "detail": self.detail,
            "ip_address": self.ip_address,
            "success": self.success,
            "error_message": self.error_message,
            "created_at": self.created_at.isoformat() if getattr(self.created_at, "isoformat", None) else str(self.created_at),
        }


# ============================================================
# 建表辅助函数
# ============================================================
def create_tables() -> bool:
    """为 custom_spider 相关模型建表。

    使用项目现有 infra.db_base.Database 单例懒加载 engine。
    """
    try:
        from infra.db_base import Database

        db = Database()
        db.ensure_connected()
        from sqlalchemy import inspect

        Base.metadata.create_all(  # type: ignore[attr-defined]
            bind=db.engine,
            tables=[
                CustomSpiderPlan.__table__,
                CustomSpiderPlanVersion.__table__,
                CustomSpiderRun.__table__,
                CustomSpiderOperationLog.__table__,
            ],
        )
        insp = inspect(db.engine)
        created = [
            t for t in [
                "custom_spider_plans",
                "custom_spider_plan_versions",
                "custom_spider_runs",
                "custom_spider_operation_logs",
            ] if insp.has_table(t)
        ]
        return len(created) == 4
    except Exception as exc:
        import traceback
        from infra.logger_setup import get_logger

        get_logger("custom_spider").error(f"create_tables failed: {exc}\n{traceback.format_exc()[:1500]}")
        return False


__all__ = [
    "CustomSpiderPlan",
    "CustomSpiderPlanVersion",
    "CustomSpiderRun",
    "CustomSpiderOperationLog",
    "create_tables",
]
