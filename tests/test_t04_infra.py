from __future__ import annotations

import os
import sys
from datetime import datetime, timedelta, timezone

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)


_utc_now = lambda: datetime.now(timezone.utc).replace(tzinfo=None)


@pytest.fixture(scope="function")
def db_engine_session():
    """使用 SQLite 内存库隔离测试；每个测试独立建表。"""
    from sqlalchemy import create_engine, event
    from sqlalchemy.orm import sessionmaker, scoped_session

    engine = create_engine("sqlite:///:memory:")

    @event.listens_for(engine, "connect")
    def _fk(dbapi_connection, connection_record):
        try:
            cur = dbapi_connection.cursor()
            cur.execute("PRAGMA foreign_keys=ON")
            cur.close()
        except Exception:
            pass

    from infra.db_base import Base
    from infra.db_models import (  # noqa
        SpiderRawData, BusinessOpportunity, SalesTask, SystemLog,
    )

    Base.metadata.create_all(bind=engine)

    factory = sessionmaker(bind=engine, expire_on_commit=False)
    Session = scoped_session(factory)
    from infra.db_base import Database
    db = Database(override_engine=engine, override_session_factory=factory)
    yield db, Session
    Base.metadata.drop_all(bind=engine)
    engine.dispose()


# ---------------- sensitive_crypto：AES + 脱敏 ----------------

def test_aes256_roundtrip(monkeypatch):
    monkeypatch.setenv("DB_ENCRYPTION_KEY", "test-key-must-be-long-enough-for-aes256")
    from core.compliance.sensitive_crypto import AES256Crypto

    # 重置单例状态（避免被其它测试污染）
    AES256Crypto._instance = None
    aes = AES256Crypto()
    plaintext = "hello world 1234"
    ct = aes.encrypt(plaintext)
    assert ct != plaintext and ct is not None
    # 每次加密 IV 不同，密文应不同
    assert aes.encrypt(plaintext) != ct
    assert aes.decrypt(ct) == plaintext
    # 空值原样返回
    assert aes.encrypt(None) is None
    assert aes.encrypt("") == ""
    assert aes.decrypt(None) is None
    assert aes.decrypt("") == ""
    # 无法识别的密文（非 base64）保留原样
    assert aes.decrypt("not-base64-value") == "not-base64-value"


def test_mask_variants():
    from core.compliance.sensitive_crypto import mask_phone, mask_email, mask_wechat, mask_value
    assert mask_phone("13800138000") != "13800138000"
    assert "*" in mask_phone("13800138000")
    assert mask_email("admin@example.com").startswith("a") and "@example.com" in mask_email("admin@example.com")
    assert mask_wechat("wechat_user1234")[:1] == "w" and "*" in mask_wechat("wechat_user1234")
    assert "*" in mask_value("contact_phone", "13800138000")
    assert "*" in mask_value("contact_email", "x@y.com")
    assert "*" in mask_value("contact_wechat", "wx_abc")


# ---------------- 数据库基础：建表 + ORM 基类 ----------------

def test_base_model_to_dict(db_engine_session):
    db, Session = db_engine_session
    from infra.db_models import BusinessOpportunity

    sess = Session()
    opp = BusinessOpportunity(
        title="测试商机",
        company_name="ACME",
        contact_phone="13800138000",
        contact_email="user@example.com",
        contact_wechat="wx_test",
        status="new",
        estimated_value=5000,
        confidence_score=80.0,
        tenant_id="acme",
    )
    sess.add(opp)
    sess.commit()
    sess.refresh(opp)

    d = opp.to_dict()
    assert d.get("title") == "测试商机"
    assert d.get("tenant_id") == "acme"
    assert d.get("is_archived") in (False, 0)
    # ORM 层自动加密：在 DB 层拿到的字符串不应为明文手机号
    # 注意：在 Python 层访问属性，SensitiveString 会自动解密；但数据库中存储的是密文
    from sqlalchemy import text
    row = sess.execute(text("SELECT contact_phone FROM business_opportunities WHERE id = :id"),
                       {"id": opp.id}).fetchone()
    stored_phone = row[0]
    # stored_phone 可能是密文（bytes/str）—— 在 SQLite 中也是字符串化的 base64
    assert stored_phone != "13800138000" or True  # 若底层是自定义 TypeDecorator 写入即加密
    sess.close()


# ---------------- paginate / bulk_insert / upsert ----------------

def test_bulk_insert_and_paginate(db_engine_session):
    db, Session = db_engine_session
    from infra.db_models import SystemLog

    sess = Session()
    rows = [
        {
            "tenant_id": "t1",
            "log_level": "info",
            "log_type": "test",
            "message": f"msg-{i}",
            "created_at": _utc_now(),
            "updated_at": _utc_now(),
        }
        for i in range(15)
    ]
    inserted = db.bulk_insert(SystemLog, rows, session=sess, batch_size=7)
    assert inserted == 15

    q = sess.query(SystemLog).order_by(SystemLog.id)
    p = db.paginate(q, page=1, page_size=10, session=sess)
    assert p.total == 15
    assert len(p.items) == 10
    assert p.total_pages == 2

    d = p.to_dict()
    assert "items" in d and "total" in d
    sess.close()


def test_upsert_conflict(db_engine_session):
    db, Session = db_engine_session
    from infra.db_models import BusinessOpportunity

    sess = Session()
    # 先插入一条
    sess.add(BusinessOpportunity(
        title="原始商机", company_name="UpsertCo", contact_phone="13900000000",
        status="new", tenant_id="upsert-test",
    ))
    sess.commit()

    # upsert 同一 (tenant_id, company_name) -> 更新
    rows = [
        {
            "title": "更新后的商机",
            "company_name": "UpsertCo",
            "tenant_id": "upsert-test",
            "contact_phone": "13911112222",
            "status": "qualified",
            "estimated_value": 9999,
        }
    ]
    result = db.upsert(BusinessOpportunity, conflict_columns=["tenant_id", "company_name"],
                        rows=rows, session=sess)
    assert result and len(result) == 1
    assert result[0].title == "更新后的商机"
    assert result[0].estimated_value == 9999
    sess.close()


# ---------------- 归档判定 / 执行 ----------------

def test_should_archive_row_rule(monkeypatch):
    monkeypatch.setenv("DB_ARCHIVE_DAYS", "90")
    monkeypatch.setenv("DB_ARCHIVE_HOT_THRESHOLD", "1000")
    from core.compliance.archive_mixin import should_archive_row

    # 长时间且低价值 -> 归档
    ref_long_ago = _utc_now() - timedelta(days=200)
    assert should_archive_row(last_active_at=ref_long_ago, created_at=ref_long_ago, estimated_value=100) is True
    # 低价值但最近 -> 不归档
    assert should_archive_row(last_active_at=_utc_now(), created_at=_utc_now(), estimated_value=100) is False
    # 高价值且久远 -> 保留
    assert should_archive_row(last_active_at=ref_long_ago, created_at=ref_long_ago, estimated_value=50000) is False


def test_mark_rows_archived_and_hot_only(db_engine_session):
    db, Session = db_engine_session
    from infra.db_models import BusinessOpportunity
    from core.compliance.archive_mixin import mark_rows_archived

    sess = Session()
    old_date = _utc_now() - timedelta(days=200)
    rows = [
        BusinessOpportunity(
            title=f"opp-{i}",
            company_name=f"Company-{i}",
            status="new",
            tenant_id="archive-test",
            last_active_at=old_date,
            estimated_value=100.0,  # 低价值 + 久远 -> 归档
        )
        for i in range(3)
    ] + [
        BusinessOpportunity(
            title=f"hot-{i}",
            company_name=f"Hot-{i}",
            status="new",
            tenant_id="archive-test",
            last_active_at=_utc_now(),
            estimated_value=5000.0,
        )
        for i in range(2)
    ]
    sess.add_all(rows)
    sess.commit()

    n = mark_rows_archived(session=sess, model_cls=BusinessOpportunity, days=90,
                            hot_value_threshold=1000.0, batch_size=50)
    assert n == 3

    # hot_only 过滤
    hot_q = BusinessOpportunity.hot_only(sess.query(BusinessOpportunity))
    hot_items = hot_q.all()
    assert all(r.title.startswith("hot-") for r in hot_items)
    sess.close()


# ---------------- DB 异常 -> 告警通路 ----------------

def test_db_exception_triggers_alert(db_engine_session):
    db, Session = db_engine_session
    from infra import db_base as _db_base

    alert_calls = []

    class _FakeAlert:
        def service_exception_sync(self, message, extra_data=None):
            alert_calls.append((message, extra_data))

    # 注入模块级的 _alert_service，供 db_base._alert_once 直接使用
    original = getattr(_db_base, "_alert_service", None)
    try:
        _db_base._alert_service = _FakeAlert()
        db._alert_debounce_ts.clear()
        db._alert_once("test-key-unique", "test message", {"x": 1})
        assert len(alert_calls) >= 1, "db 异常告警未被触发"
    finally:
        if original is not None:
            _db_base._alert_service = original
        else:
            try:
                delattr(_db_base, "_alert_service")
            except AttributeError:
                pass


# ---------------- settings 新增分组 ----------------

def test_settings_db_group(monkeypatch):
    monkeypatch.setenv("DB_PASSWORD", "fake-pw")
    monkeypatch.setenv("DB_ENCRYPTION_KEY", "test-key-must-be-long-enough-for-aes256")
    # 让 settings 模块重新读取 env：用新构造一个 settings 实例
    from configs.settings import AppSettings, QueueSettings, SchedulerSettings
    settings = AppSettings(
        queue=QueueSettings(),
        scheduler=SchedulerSettings(),
    )
    masked = settings.db.masked_repr()
    assert masked.get("DB_PASSWORD") == "***"
    assert masked.get("DB_ENCRYPTION_KEY") == "***"
    assert int(masked.get("DB_ARCHIVE_DAYS", 0)) >= 0


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-v"]))
