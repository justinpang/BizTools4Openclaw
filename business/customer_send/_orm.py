"""business/customer_send/_orm — SQLAlchemy 表模型。"""

from __future__ import annotations

from infra.logger_setup import get_logger

logger = get_logger("customer_send.orm")

try:
    from sqlalchemy import (
        JSON,
        Column,
        DateTime,
        Integer,
        String,
        BigInteger,
        Index,
        UniqueConstraint,
    )
    from sqlalchemy.orm import declarative_base
    from sqlalchemy.sql import func

    _Base = declarative_base()
    _HAS_SQLALCHEMY = True

    class CustomerSendJobRow(_Base):
        __tablename__ = "customer_send_job"

        id = Column(BigInteger().with_variant(Integer, "sqlite"), primary_key=True, autoincrement=True)
        task_id = Column(String(128), nullable=False)
        tenant_id = Column(String(64), nullable=False)
        channels = Column(JSON, nullable=True)
        total = Column(Integer, nullable=False, default=0)
        success = Column(Integer, nullable=False, default=0)
        failed = Column(Integer, nullable=False, default=0)
        blocked = Column(Integer, nullable=False, default=0)
        rate_limited = Column(Integer, nullable=False, default=0)
        status = Column(String(16), nullable=False, default="PENDING")
        caller = Column(String(32), nullable=True)
        started_at = Column(DateTime, nullable=True)
        finished_at = Column(DateTime, nullable=True)
        created_at = Column(DateTime, nullable=False, server_default=func.now())
        __table_args__ = (UniqueConstraint("tenant_id", "task_id", name="uq_csj_tenant_task"),)

    class CustomerSendBehaviorRow(_Base):
        __tablename__ = "customer_send_behavior"

        id = Column(BigInteger().with_variant(Integer, "sqlite"), primary_key=True, autoincrement=True)
        behavior_id = Column(String(128), nullable=False)
        tenant_id = Column(String(64), nullable=False)
        opportunity_id = Column(String(128), nullable=False)
        channel = Column(String(16), nullable=False)
        event = Column(String(16), nullable=False)
        recipient_masked = Column(String(256), nullable=True)
        h5_page_id = Column(String(128), nullable=True)
        http_path = Column(String(256), nullable=True)
        payload_snapshot = Column(JSON, nullable=True)
        remote_ip_masked = Column(String(64), nullable=True)
        user_agent_hash = Column(String(64), nullable=True)
        created_at = Column(DateTime, nullable=False, server_default=func.now())
        __table_args__ = (
            UniqueConstraint("tenant_id", "behavior_id", name="uq_csb_tenant_bid"),
            Index("idx_csb_tenant_opp", "tenant_id", "opportunity_id"),
        )

    def _row_count(_cls):
        return 1

except Exception as exc:
    _Base = None
    _HAS_SQLALCHEMY = False
    CustomerSendJobRow = None
    CustomerSendBehaviorRow = None
    logger.warning(f"SQLAlchemy 不可用，跳过表模型定义: {exc}")


def ensure_tables() -> None:
    """在实际数据库引擎上尝试创建表；失败静默。"""
    if not _HAS_SQLALCHEMY or _Base is None:
        return
    try:
        from infra.db_base import database  # type: ignore
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
    "CustomerSendJobRow",
    "CustomerSendBehaviorRow",
    "ensure_tables",
]
