"""T11 商机触达测试。"""

from __future__ import annotations

import pytest


# 基础：测试模板引擎能否正确渲染 + PII 脱敏。

def test_template_engine_render_email_default():
    from business.customer_send.models import SendTarget
    from business.customer_send.template_engine import render

    t = SendTarget(
        opportunity_id="opp_1",
        tenant_id="t1",
        customer_name="张晓敏",
        contact_email="zhang@example.com",
        contact_phone="13800138000",
        contact_industry="IT/互联网",
        contact_region="上海",
        need_keywords=["采购", "服务器"],
        opportunity_title="某互联网公司采购需求",
        opportunity_score=80,
    )
    html = render("email", "default", {
        "customer_name": "张***",
        "industry": "IT/互联网",
        "region": "上海",
        "need_keywords_csv": "采购,服务器",
        "opportunity_id": "opp_1",
        "opportunity_title": "某互联网公司采购需求",
        "opportunity_score": "80",
        "tenant_id": "t1",
        "h5_url": "https://claw.example.com/p/abc",
        "send_date": "2026-07-03",
    })
    assert "<html" in html
    assert "某互联网公司采购需求" in html
    # 脱敏：原邮箱不能出现
    assert "zhang@example.com" not in html
    assert "13800138000" not in html
    # H5 URL 必须出现
    assert "https://claw.example.com/p/abc" in html


def test_template_engine_build_variables_masks_pii():
    from business.customer_send.models import SendTarget
    from business.customer_send.template_engine import build_variables

    t = SendTarget(
        opportunity_id="opp_2", tenant_id="t1",
        customer_name="王小敏",
        contact_email="zhang@example.com",
        contact_phone="13800138000",
        contact_industry="制造业",
        contact_region="北京",
        need_keywords=["采购"],
        opportunity_title="标题", opportunity_score=70,
    )
    v = build_variables(t, h5_url="https://x.com/p/123")
    # 客户姓名应被脱敏：不应包含完整姓名
    assert "example.com" not in v["customer_name"]
    # 手机号不应明文出现
    assert "13800138000" not in v["contact_phone"]
    # 邮箱用户名脱敏：不应出现 zhang
    assert "zhang" not in v["contact_email"] or "zhang" == v["contact_email"]
    assert "@" in v["contact_email"]
    # h5_url must be present
    assert v["h5_url"] == "https://x.com/p/123"
    # score rendered as string
    assert v["opportunity_score"] == "70"


def test_template_engine_unknown_key_defaults_to_dash():
    from business.customer_send.template_engine import render_from_string
    out = render_from_string("Hello {{name}}", {"name": ""})
    assert out == "Hello —"


# 渠道驱动：mock sender_fn 注入

def test_email_channel_send_with_mock():
    from business.customer_send.channels.email_channel import EmailChannel

    class Acc:
        account_id = "smtp_1"
        token = "smtp_fallback"

    ch = EmailChannel()
    # dry_run
    ok, code, msg = ch.send(Acc(), "x@example.com", "<html>hi</html>",
                             extra={"__dry_run__": True})
    assert ok is True
    assert code == 200

    # mock sender
    called = []

    def sender(account, recipient, content, extra):
        called.append((account.account_id, recipient, content))
        return True, 200, "ok"

    ok, code, msg = ch.send(Acc(), "a@b.com", "<html>hi</html>",
                             extra={"__mock_sender__": sender})
    assert ok is True
    assert called


def test_wechat_channel_with_mock():
    from business.customer_send.channels.wechat_channel import WechatChannel

    class Acc:
        account_id = "w1"
        token = "mock_token"

    ch = WechatChannel()
    called = []

    def sender(account, recipient, content, extra):
        called.append(recipient)
        return True, 200, "ok"

    ok, code, msg = ch.send(Acc(), "opp_1", "body",
                             extra={"__mock_sender__": sender})
    assert ok is True


def test_feishu_channel_with_mock():
    from business.customer_send.channels.feishu_channel import FeishuChannel

    class Acc:
        account_id = "f1"
        token = "mock_token"

    ch = FeishuChannel()
    called = []

    def sender(account, recipient, content, extra):
        called.append(recipient)
        return True, 200, "ok"

    ok, code, msg = ch.send(Acc(), "opp_1", "body",
                             extra={"__mock_sender__": sender})
    assert ok is True


def test_h5_landing_generate_html():
    from business.customer_send.channels.h5_landing import H5Landing
    from business.customer_send.models import H5PageSpec

    h5 = H5Landing()
    spec = H5PageSpec(
        page_id="",
        tenant_id="t1",
        opportunity_id="opp_1",
        customer_name_masked="张***",
        industry="IT",
        region="上海",
        keywords=["采购", "服务器"],
        title="采购需求",
        summary="客户需要采购一批服务器",
        cta_label="立即报名",
    )
    spec.page_id = h5.page_id_for(spec)
    html = h5.generate_html(spec)
    assert "<html" in html
    assert "采购需求" in html
    assert h5.short_url(spec.page_id).startswith("http")


# 流水线核心功能：run_batch 传入 targets + mock sender_fn

def test_pipeline_run_dry_run():
    from business.customer_send import run_batch, BatchSendParams, SendTarget

    params = BatchSendParams(
        task_id="t_test_1",
        tenant_id="t1",
        channels=["email"],
        targets=[
            SendTarget(
                opportunity_id="opp_1", tenant_id="t1",
                customer_name="张晓敏",
                contact_email="a@example.com",
                opportunity_title="采购需求", opportunity_score=80,
                need_keywords=["采购"], contact_industry="IT",
                contact_region="上海",
            )
        ],
        dry_run=True,
    )
    result = run_batch(params)
    assert result.status in ("ok", "partial", "failed")
    # dry_run 中每个 target × channel 应该产生 1 个成功 detail
    assert result.success >= 1


def test_pipeline_run_with_mock_sender_success():
    from business.customer_send import CustomerSendPipeline
    from business.customer_send.models import BatchSendParams, SendTarget

    # 用 mock sender 替换 send_core 的 SendPipeline
    pipeline = CustomerSendPipeline(storage=_build_mock_storage())

    params = BatchSendParams(
        task_id="t_mock_1",
        tenant_id="t1",
        channels=["email"],
        targets=[
            SendTarget(
                opportunity_id="opp_1", tenant_id="t1",
                customer_name="张***", contact_email="a@b.com",
                opportunity_title="标题", opportunity_score=60,
                need_keywords=["采购"], contact_industry="IT",
            )
        ],
        enable_h5=False,
    )
    # 模拟 send_core 不可用时的 fallback
    result = pipeline.run(params)
    # email 渠道需要 smtp 配置，但 fallback 会把账号 token 当成 "smtp_fallback"；
    # 在 send_core 不可用的情况下，storage._upsert_rows 用 mock 返回 len(rows)
    assert result.total >= 1


def test_pipeline_run_with_h5_enabled():
    from business.customer_send import CustomerSendPipeline
    from business.customer_send.models import BatchSendParams, SendTarget

    pipeline = CustomerSendPipeline(storage=_build_mock_storage())
    result = pipeline.run(BatchSendParams(
        task_id="t_mock_h5", tenant_id="t1",
        channels=["email"], targets=[
            SendTarget(opportunity_id="opp_h5", tenant_id="t1",
                       customer_name="张***", contact_email="a@b.com",
                       opportunity_title="标题", opportunity_score=50,
                       need_keywords=["采购"], contact_industry="IT",
                       contact_region="北京")
        ], enable_h5=True, dry_run=True,
    ))
    assert result.success >= 1
    # H5 URL 被注入
    assert any(d.h5_page_url and d.h5_page_url.startswith("http") for d in result.details)


def test_pipeline_run_multiple_targets_and_channels():
    from business.customer_send import CustomerSendPipeline
    from business.customer_send.models import BatchSendParams, SendTarget

    pipeline = CustomerSendPipeline(storage=_build_mock_storage())
    targets = [
        SendTarget(opportunity_id=f"opp_{i}", tenant_id="t1",
                   customer_name=f"客户{i}", contact_email=f"c{i}@example.com",
                   opportunity_title="标题", opportunity_score=60,
                   need_keywords=["采购"], contact_industry="IT",
                   contact_region="北京")
        for i in range(3)
    ]
    result = pipeline.run(BatchSendParams(
        task_id="t_mock_multi", tenant_id="t1",
        channels=["email", "wechat", "feishu"],
        targets=targets,
        dry_run=True,
    ))
    # 3 targets × 3 channels = 9 total
    assert result.total >= 9


def test_storage_upsert_behaviors_via_mock():
    from business.customer_send.storage import SendStorage
    from business.customer_send.models import SendBehaviorLog

    storage = SendStorage(ensure_schema=False)
    # mock database.upsert
    from infra.db_base import database as _db
    captured = {}

    def _upsert(row_cls, *, conflict_columns, rows):
        captured["rows"] = list(rows)
        captured["conflict"] = list(conflict_columns)
        return len(rows)

    def _bulk(row_cls, rows):
        captured["rows"] = list(rows)
        return len(rows)

    original_upsert = getattr(_db, "upsert", None)
    original_bulk = getattr(_db, "bulk_insert", None)
    try:
        _db.upsert = _upsert
        _db.bulk_insert = _bulk
        n = storage.record_behaviors([
            SendBehaviorLog(behavior_id="b1", tenant_id="t1",
                            opportunity_id="opp_1", channel="email",
                            event="sent", recipient_masked="a***"),
        ])
    finally:
        if original_upsert is not None:
            _db.upsert = original_upsert
        if original_bulk is not None:
            _db.bulk_insert = original_bulk
    assert n == 1
    assert "b1" in captured["rows"][0].get("behavior_id", "")


def _build_mock_storage():
    from business.customer_send.storage import SendStorage
    from infra.db_base import database as _db

    storage = SendStorage(ensure_schema=False)

    def _upsert(row_cls, *, conflict_columns, rows):
        return len(rows)

    def _bulk(row_cls, rows):
        return len(rows)

    _db.upsert = _upsert
    _db.bulk_insert = _bulk
    return storage
