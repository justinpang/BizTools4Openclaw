import os
import sys
import time

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, PROJECT_ROOT)
os.chdir(PROJECT_ROOT)

os.environ["DB_BACKEND"] = "sqlite"
os.environ["DB_SQLITE_PATH"] = ""
os.environ["DB_ENCRYPTION_KEY"] = "please-change-this-to-a-strong-random-32-chars-!!"
os.environ["QUEUE_REDIS_HOST"] = "127.0.0.1"
os.environ["ENV"] = "dev"
os.environ["DEBUG"] = "true"
os.environ["LOG_LEVEL"] = "INFO"

output = []
def log(msg):
    print(msg, flush=True)
    output.append(msg)

# 直接模拟 customer_send/_orm.py 的每一步
log("[1] infra.logger_setup get_logger")
t0 = time.time()
from infra.logger_setup import get_logger
logger = get_logger("customer_send.orm")
log(f"  OK ({time.time()-t0:.2f}s)")

log("[2] sqlalchemy imports")
t0 = time.time()
from sqlalchemy import JSON, Column, DateTime, Integer, String, BigInteger, Index, UniqueConstraint
log(f"  OK ({time.time()-t0:.2f}s)")

log("[3] declarative_base")
t0 = time.time()
from sqlalchemy.orm import declarative_base
_Base = declarative_base()
log(f"  OK ({time.time()-t0:.2f}s)")

log("[4] sqlalchemy.sql.func")
t0 = time.time()
from sqlalchemy.sql import func
log(f"  OK ({time.time()-t0:.2f}s)")

log("[5] Define CustomerSendJobRow")
t0 = time.time()
class CustomerSendJobRow(_Base):
    __tablename__ = "customer_send_job_test"
    id = Column(BigInteger().with_variant(Integer, "sqlite"), primary_key=True, autoincrement=True)
    task_id = Column(String(128), nullable=False)
    tenant_id = Column(String(64), nullable=False)
    channels = Column(JSON, nullable=True)
    status = Column(String(16), nullable=False, default="PENDING")
    created_at = Column(DateTime, nullable=False, server_default=func.now())
    __table_args__ = (UniqueConstraint("tenant_id", "task_id", name="uq_csj_tenant_task_test"),)
log(f"  OK ({time.time()-t0:.2f}s)")

log("[6] Define CustomerSendBehaviorRow")
t0 = time.time()
class CustomerSendBehaviorRow(_Base):
    __tablename__ = "customer_send_behavior_test"
    id = Column(BigInteger().with_variant(Integer, "sqlite"), primary_key=True, autoincrement=True)
    behavior_id = Column(String(128), nullable=False)
    tenant_id = Column(String(64), nullable=False)
    opportunity_id = Column(String(128), nullable=False)
    channel = Column(String(16), nullable=False)
    event = Column(String(16), nullable=False)
    created_at = Column(DateTime, nullable=False, server_default=func.now())
    __table_args__ = (
        UniqueConstraint("tenant_id", "behavior_id", name="uq_csb_tenant_bid_test"),
        Index("idx_csb_tenant_opp_test", "tenant_id", "opportunity_id"),
    )
log(f"  OK ({time.time()-t0:.2f}s)")

# 测试 data_clean
log("\n[7] infra.db_base (data_clean dependency)")
t0 = time.time()
from infra.db_base import database
log(f"  OK ({time.time()-t0:.2f}s)")

log("[8] DeclarativeBase + Mapped (data_clean style)")
t0 = time.time()
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column
class _Base2(DeclarativeBase):
    pass
log(f"  OK ({time.time()-t0:.2f}s)")

log("[9] data_clean style row")
t0 = time.time()
from datetime import datetime, timezone
class TestRow(_Base2):
    __tablename__ = "test_data_clean"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    tenant_id: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    opportunity_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    title: Mapped[str] = mapped_column(String(512), nullable=False, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=lambda: datetime.now(timezone.utc))
    __table_args__ = (Index("ix_test_unique", "tenant_id", "opportunity_id", unique=True),)
log(f"  OK ({time.time()-t0:.2f}s)")

log("\n🎉 所有 ORM 类定义通过")
with open("docker/_orm_mini_test.txt", "w", encoding="utf8") as f:
    f.write("\n".join(output))
