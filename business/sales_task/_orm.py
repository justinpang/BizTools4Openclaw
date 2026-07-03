"""business/sales_task/_orm — SQLAlchemy 表模型。"""

from __future__ import annotations

from infra.logger_setup import get_logger

logger = get_logger("sales_task.orm")

try:
    from sqlalchemy import (
        JSON,
        BigInteger,
        Column,
        DateTime,
        Float,
        Index,
        Integer,
        String,
        Text,
        UniqueConstraint,
    )
    from sqlalchemy.orm import declarative_base
    from sqlalchemy.sql import func

    _Base = declarative_base()
    _HAS_SQLALCHEMY = True

    # ========== salesperson ==========
    class SalespersonRow(_Base):
        __tablename__ = "salesperson"
        id = Column(BigInteger().with_variant(Integer, "sqlite"), primary_key=True, autoincrement=True)
        sales_id = Column(String(64), nullable=False)
        tenant_id = Column(String(64), nullable=False)
        name = Column(String(64), nullable=False)
        industries = Column(JSON, nullable=True)
        regions = Column(JSON, nullable=True)
        min_score = Column(Integer, nullable=False, default=0)
        weight = Column(Float, nullable=False, default=1.0)
        current_load = Column(Integer, nullable=False, default=0)
        email = Column(String(128), nullable=True)
        wechat = Column(String(128), nullable=True)
        feishu = Column(String(128), nullable=True)
        group = Column(String(32), nullable=False, default="default")
        created_at = Column(DateTime, nullable=False, server_default=func.now())
        updated_at = Column(DateTime, nullable=False, server_default=func.now())
        __table_args__ = (
            UniqueConstraint("tenant_id", "sales_id", name="uq_sp_tenant_sales"),
            Index("idx_sp_tenant_group", "tenant_id", "group"),
        )

    # ========== opportunity ==========
    class OpportunityRow(_Base):
        __tablename__ = "opportunity"
        id = Column(BigInteger().with_variant(Integer, "sqlite"), primary_key=True, autoincrement=True)
        opportunity_id = Column(String(128), nullable=False)
        tenant_id = Column(String(64), nullable=False)
        customer_name = Column(String(128), nullable=False)
        contact_email = Column(String(128), nullable=True)
        contact_phone = Column(String(64), nullable=True)
        industry = Column(String(64), nullable=True)
        region = Column(String(64), nullable=True)
        need_keywords = Column(JSON, nullable=True)
        score = Column(Integer, nullable=False, default=0)
        status = Column(String(32), nullable=False, default="NEW")
        assigned_sales_id = Column(String(64), nullable=True)
        assigned_at = Column(DateTime, nullable=True)
        last_follow_at = Column(DateTime, nullable=True)
        tags = Column(JSON, nullable=True)
        source_batch_id = Column(String(128), nullable=True)
        created_at = Column(DateTime, nullable=False, server_default=func.now())
        updated_at = Column(DateTime, nullable=False, server_default=func.now())
        __table_args__ = (
            UniqueConstraint("tenant_id", "opportunity_id", name="uq_opp_tenant_opp"),
            Index("idx_opp_tenant_status", "tenant_id", "status"),
            Index("idx_opp_tenant_sales", "tenant_id", "assigned_sales_id"),
            Index("idx_opp_tenant_assigned", "tenant_id", "assigned_at"),
        )

    # ========== follow_up_record ==========
    class FollowUpRecordRow(_Base):
        __tablename__ = "follow_up_record"
        id = Column(BigInteger().with_variant(Integer, "sqlite"), primary_key=True, autoincrement=True)
        follow_id = Column(String(128), nullable=False)
        tenant_id = Column(String(64), nullable=False)
        opportunity_id = Column(String(128), nullable=False)
        sales_id = Column(String(64), nullable=False)
        channel = Column(String(32), nullable=False)
        content = Column(Text, nullable=False)
        next_follow_at = Column(DateTime, nullable=True)
        created_at = Column(DateTime, nullable=False, server_default=func.now())
        __table_args__ = (
            UniqueConstraint("tenant_id", "follow_id", name="uq_fur_tenant_follow"),
            Index("idx_fur_tenant_opp", "tenant_id", "opportunity_id"),
        )

    # ========== sales_operation_log ==========
    class SalesOperationLogRow(_Base):
        __tablename__ = "sales_operation_log"
        id = Column(BigInteger().with_variant(Integer, "sqlite"), primary_key=True, autoincrement=True)
        log_id = Column(String(128), nullable=False)
        tenant_id = Column(String(64), nullable=False)
        opportunity_id = Column(String(128), nullable=False)
        sales_id = Column(String(64), nullable=False)
        op_type = Column(String(32), nullable=False)
        before_value = Column(String(256), nullable=True)
        after_value = Column(String(256), nullable=True)
        detail = Column(Text, nullable=True)
        created_at = Column(DateTime, nullable=False, server_default=func.now())
        __table_args__ = (
            UniqueConstraint("tenant_id", "log_id", name="uq_sol_tenant_log"),
            Index("idx_sol_tenant_opp", "tenant_id", "opportunity_id"),
            Index("idx_sol_tenant_op", "tenant_id", "op_type"),
        )

    # ========== sales_task_job ==========
    class SalesTaskJobRow(_Base):
        __tablename__ = "sales_task_job"
        id = Column(BigInteger().with_variant(Integer, "sqlite"), primary_key=True, autoincrement=True)
        job_id = Column(String(128), nullable=False)
        task_id = Column(String(128), nullable=False)
        tenant_id = Column(String(64), nullable=False)
        job_type = Column(String(32), nullable=False)
        processed = Column(Integer, nullable=False, default=0)
        assigned = Column(Integer, nullable=False, default=0)
        reminded = Column(Integer, nullable=False, default=0)
        overdue_count = Column(Integer, nullable=False, default=0)
        long_unassigned = Column(Integer, nullable=False, default=0)
        status = Column(String(16), nullable=False, default="OK")
        reason = Column(String(512), nullable=True)
        detail = Column(JSON, nullable=True)
        started_at = Column(DateTime, nullable=True)
        finished_at = Column(DateTime, nullable=True)
        __table_args__ = (
            UniqueConstraint("tenant_id", "task_id", "job_type", name="uq_stj_tenant_task_type"),
        )

    # ========== funnel_stats ==========
    class FunnelStatsRow(_Base):
        __tablename__ = "funnel_stats"
        id = Column(BigInteger().with_variant(Integer, "sqlite"), primary_key=True, autoincrement=True)
        stats_id = Column(String(128), nullable=False)
        tenant_id = Column(String(64), nullable=False)
        period_start = Column(DateTime, nullable=False)
        period_end = Column(DateTime, nullable=False)
        collected = Column(Integer, nullable=False, default=0)
        cleaned = Column(Integer, nullable=False, default=0)
        reached = Column(Integer, nullable=False, default=0)
        followed = Column(Integer, nullable=False, default=0)
        closed_won = Column(Integer, nullable=False, default=0)
        conversion_rates = Column(JSON, nullable=True)
        created_at = Column(DateTime, nullable=False, server_default=func.now())
        __table_args__ = (
            UniqueConstraint("tenant_id", "stats_id", name="uq_fs_tenant_stats"),
            Index("idx_fs_tenant_period", "tenant_id", "period_start", "period_end"),
        )

except Exception as exc:
    _Base = None
    _HAS_SQLALCHEMY = False
    SalespersonRow = None
    OpportunityRow = None
    FollowUpRecordRow = None
    SalesOperationLogRow = None
    SalesTaskJobRow = None
    FunnelStatsRow = None
    logger.warning(f"SQLAlchemy 不可用，跳过表模型定义: {exc}")


def ensure_tables() -> None:
    """尝试在数据库引擎上建表；失败静默。"""
    if not _HAS_SQLALCHEMY or _Base is None:
        return
    try:
        from infra.db_base import database
        engine = getattr(database, "engine", None)
        if engine is None:
            if hasattr(database, "ensure_connected"):
                try:
                    database.ensure_connected()
                except Exception:
                    pass
            engine = getattr(database, "engine", None)
        if engine is None:
            return
        _Base.metadata.create_all(bind=engine)
    except Exception as exc:
        logger.info(f"ensure_tables 跳过（非阻塞）: {exc}")


__all__ = [
    "_Base",
    "SalespersonRow",
    "OpportunityRow",
    "FollowUpRecordRow",
    "SalesOperationLogRow",
    "SalesTaskJobRow",
    "FunnelStatsRow",
    "ensure_tables",
]
