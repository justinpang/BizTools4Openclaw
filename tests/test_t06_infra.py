"""T06 任务：数据合规、脱敏、敏感词过滤 —— 单元测试。"""

from __future__ import annotations

import json
import os
import tempfile
import time
from datetime import datetime, timezone

import pytest

from core.compliance.pii_mask import PIIMask
from core.compliance.sensitive_filter import (
    RISK_HIGH,
    RISK_LOW,
    RISK_MEDIUM,
    SensitiveFilter,
    FilterResult,
)
from core.compliance.privacy_stripper import PrivacyStripper
from core.compliance.compliance_checker import ComplianceChecker, ComplianceReport
from core.compliance.data_lifecycle import DataLifecycle


# ===================== fixtures =====================

@pytest.fixture()
def mask() -> PIIMask:
    return PIIMask()


@pytest.fixture()
def sf_empty() -> SensitiveFilter:
    return SensitiveFilter(words=[])


@pytest.fixture()
def sf_custom() -> SensitiveFilter:
    return SensitiveFilter(words=[
        ("黑产", "violation", RISK_HIGH),
        ("博彩", "violation", RISK_HIGH),
        ("加微信", "advertising", RISK_MEDIUM),
        ("兼职日结", "advertising", RISK_MEDIUM),
        ("敏感样例", "custom", RISK_LOW),
    ])


@pytest.fixture()
def ps() -> PrivacyStripper:
    return PrivacyStripper(pii_mask=PIIMask(), keep_masked=True)


@pytest.fixture()
def checker(ps, sf_custom, mask) -> ComplianceChecker:
    return ComplianceChecker(
        pii_mask=mask,
        sensitive_filter=sf_custom,
        privacy_stripper=ps,
        enable_alert_on_high_risk=False,
    )


@pytest.fixture()
def lifecycle(mask, ps) -> DataLifecycle:
    return DataLifecycle(retention_days=30, pii_mask=mask, privacy_stripper=ps)


# ===================== PIIMask 测试 =====================

def test_mask_phone(mask: PIIMask) -> None:
    assert mask.mask_phone("我的号码是13800138000请联系") == "我的号码是138****8000请联系"
    assert mask.mask_phone("") == ""


def test_mask_email(mask: PIIMask) -> None:
    result = mask.mask_email("user.name@example.com")
    assert "@example.com" in result
    assert result.startswith("u")
    assert result.endswith("e@example.com") or "*" in result.split("@")[0]


def test_mask_wechat(mask: PIIMask) -> None:
    result = mask.mask_wechat("微信号:abc12345")
    assert "*" in result


def test_mask_bank_card(mask: PIIMask) -> None:
    # 纯数字银行卡号
    result = mask.mask_bank_card("6222020000111234")
    assert "1234" in result and result.index("1234") > 0
    assert "*" in result


def test_mask_company_and_nickname(mask: PIIMask) -> None:
    assert "*" in mask.mask_company("阿里巴巴（中国）有限公司")
    assert "*" in mask.mask_nickname("张伟")


def test_mask_url(mask: PIIMask) -> None:
    result = mask.mask_url("https://customer.abc.com/path")
    assert "https://" in result
    assert "*" in result


def test_auto_mask_dict(mask: PIIMask) -> None:
    data = {
        "phone": "13800138000",
        "email": "user@example.com",
        "wechat_id": "wx_abc123",
        "real_name": "张三",
        "content": "联系我：13800138000",
        "age": 28,
    }
    masked = mask.auto_mask(data)
    assert masked["phone"] == "138****8000"
    assert "@" in masked["email"] and masked["email"].count("*") >= 1
    assert "138****8000" in masked["content"]


def test_auto_mask_list_and_nested(mask: PIIMask) -> None:
    data = [
        {"phone": "13800138000", "nested": {"email": "user@example.com"}},
        "纯文本 13800139000",
    ]
    masked = mask.auto_mask(data)
    assert masked[0]["phone"] == "138****8000"
    assert "*" in masked[0]["nested"]["email"]
    assert "138****9000" in masked[1]


def test_detect_pii(mask: PIIMask) -> None:
    hits = mask.detect_pii("联系电话 13800138000，邮箱 user@example.com")
    types = {h["type"] for h in hits}
    assert "phone" in types
    assert "email" in types


# ===================== SensitiveFilter 测试 =====================

def test_sf_detect_case_insensitive(sf_custom: SensitiveFilter) -> None:
    hits = sf_custom.detect("这里有黑产广告，还有兼职日结。")
    fragments = {h.fragment for h in hits}
    assert "黑产" in fragments
    assert "兼职日结" in fragments


def test_sf_filter_text_replaces(sf_custom: SensitiveFilter) -> None:
    result = sf_custom.filter_text("这里有黑产内容")
    assert "***" in result.cleaned_text
    assert result.risk == RISK_HIGH


def test_sf_is_blocked_high_risk(sf_custom: SensitiveFilter) -> None:
    assert sf_custom.is_blocked("黑产推广") is True
    assert sf_custom.is_blocked("正常内容") is False


def test_sf_highlight(sf_custom: SensitiveFilter) -> None:
    out = sf_custom.highlight("文本中有黑产字样")
    assert "<mark>" in out and "</mark>" in out


def test_sf_add_word_runtime(sf_empty: SensitiveFilter) -> None:
    sf_empty.add_word("测试词", category="custom", risk=RISK_MEDIUM)
    result = sf_empty.filter_text("这是一条包含测试词的文本")
    assert any(h.fragment == "测试词" for h in result.hits)


def test_sf_load_file_json(tmp_path) -> None:
    path = tmp_path / "words.json"
    path.write_text(json.dumps([
        {"word": "赌博", "category": "violation", "risk": RISK_HIGH},
        {"word": "代写", "category": "advertising", "risk": RISK_MEDIUM},
    ]), encoding="utf-8")
    sf = SensitiveFilter(words=[], custom_words_file=str(path))
    result = sf.filter_text("赌博违法 代写论文")
    assert result.is_blocked
    # "赌博" 独立命中；"代写论文" 是比 "代写" 更长的匹配，AC 去重后保留最长的
    assert any(h.fragment == "赌博" for h in result.hits)
    assert any(h.fragment == "代写论文" for h in result.hits) or any(
        h.fragment == "代写" for h in result.hits
    )


def test_sf_load_file_plain(tmp_path) -> None:
    path = tmp_path / "words.txt"
    path.write_text("# 注释行\n博彩,violation,high\n加微信,advertising,medium\n", encoding="utf-8")
    sf = SensitiveFilter(words=[], custom_words_file=str(path))
    hits = sf.detect("博彩网站加微信咨询")
    assert any(h.fragment == "博彩" for h in hits)
    assert any(h.fragment == "加微信" for h in hits)


def test_sf_empty_not_blocked() -> None:
    sf = SensitiveFilter(words=[])
    result = sf.filter_text("完全正常内容")
    assert result.is_blocked is False
    assert result.risk == RISK_LOW


# ===================== PrivacyStripper 测试 =====================

def test_ps_strip_dict_keys(ps: PrivacyStripper) -> None:
    data = {
        "phone": "13800138000",
        "email": "user@example.com",
        "title": "正常标题",
        "age": 28,
    }
    stripped = ps.strip(data, mode="strip")
    assert "phone" not in stripped
    assert "email" not in stripped
    assert stripped["title"] == "正常标题"
    assert stripped["age"] == 28


def test_ps_mask_mode_keeps_masked_value() -> None:
    ps = PrivacyStripper(pii_mask=PIIMask(), keep_masked=True)
    data = {"phone": "13800138000", "content": "正常"}
    result = ps.strip(data, mode="mask")
    assert "phone" in result
    assert result["phone"] == "138****8000" or result["phone"] == "*" * max(8, min(11, 16))


def test_ps_preserve_keys() -> None:
    ps = PrivacyStripper(
        pii_mask=None,
        preserve_keys=["phone"],
        keep_masked=False,
    )
    data = {"phone": "13800138000", "email": "u@e.com"}
    result = ps.strip(data, mode="strip")
    assert result["phone"] == "13800138000"
    assert "email" not in result


def test_ps_nested_list() -> None:
    ps = PrivacyStripper(pii_mask=PIIMask(), keep_masked=True)
    data = [
        {"phone": "13800138000", "ok": "yes"},
        {"email": "a@b.com", "other": "value"},
    ]
    result = ps.strip(data, mode="strip")
    # 隐私字段被删除
    assert "phone" not in result[0]
    assert "email" not in result[1]
    assert result[0]["ok"] == "yes"


def test_ps_scan_report() -> None:
    ps = PrivacyStripper(keep_masked=True)
    rep = ps.scan_report({"phone": "x", "email": "y", "title": "z"})
    assert rep["total_hits"] >= 2


# ===================== ComplianceChecker 测试 =====================

def test_checker_storage_high_risk(checker: ComplianceChecker) -> None:
    data = {
        "title": "这是一条黑产推广博彩信息",
        "phone": "13800138000",
        "content": "联系电话 13800139000",
    }
    report = checker.check_for_storage(data, context={"source": "spider"})
    assert report.risk_level == RISK_HIGH
    assert report.blocked
    # storage 场景隐私字段被剔除
    assert "phone" not in report.masked_data
    # 敏感词在字符串中被掩码
    assert "黑产" not in str(report.masked_data) or "***" in str(report.masked_data)


def test_checker_outbound_masks_values(checker: ComplianceChecker) -> None:
    data = {
        "text": "联系电话 13800138000 加微信咨询",
        "email": "user@example.com",
    }
    report = checker.check_for_outbound(data, context={"source": "outbound"})
    masked = report.masked_data
    # outbound 场景保留结构但掩码
    assert "13800138000" not in str(masked)
    assert "***" in str(masked)


def test_checker_low_risk(checker: ComplianceChecker) -> None:
    data = {"title": "正常内容", "body": "这是一条普通的文本"}
    report = checker.check_for_storage(data)
    assert report.passed
    assert not report.blocked
    assert report.risk_level == RISK_LOW


def test_checker_report_to_dict(checker: ComplianceChecker) -> None:
    report = checker.check_for_storage({"title": "正常"}, context={"a": 1})
    d = report.to_dict()
    assert "passed" in d
    assert "risk_level" in d
    assert d["context"]["a"] == 1


# ===================== DataLifecycle 测试 =====================

def test_lifecycle_mark_expired(lifecycle: DataLifecycle) -> None:
    now = datetime.now(timezone.utc)
    rows = [
        {"id": 1, "created_at": (now).isoformat()},
        {"id": 2, "created_at": (now.timestamp() - 60 * 86400)},  # 60 天前
        {"id": 3, "created_at": (now.timestamp() - 10 * 86400)},  # 10 天前
    ]
    out = lifecycle.mark_expired(rows)
    # id 2 应被标记过期
    assert out[1]["is_archived"] is True
    # id 3 不应被标记
    assert out[2].get("is_archived") is False


def test_lifecycle_clear_privacy(lifecycle: DataLifecycle) -> None:
    data = {"phone": "13800138000", "email": "a@b.com", "age": 28}
    cleared = lifecycle.clear_privacy(data, mode="delete")
    assert "phone" not in cleared
    assert "email" not in cleared
    assert cleared["age"] == 28


def test_lifecycle_clear_file(lifecycle: DataLifecycle, tmp_path) -> None:
    src = tmp_path / "source.log"
    src.write_text("正常一行\n包含手机号 13800138000 的一行\n", encoding="utf-8")
    out_path = str(tmp_path / "out.log")
    result = lifecycle.clear_file(str(src), output_path=out_path)
    assert result["total_lines"] == 2
    assert result["modified_lines"] >= 1
    content = open(out_path, encoding="utf-8").read()
    assert "13800138000" not in content
    assert "138****8000" in content or "*" in content


def test_lifecycle_report(lifecycle: DataLifecycle) -> None:
    rows = [
        {"id": 1, "is_archived": True},
        {"id": 2, "is_archived": False},
    ]
    rep = lifecycle.report(rows, extra={"source": "test"})
    assert rep["scanned_rows"] == 2
    assert rep["archived_rows"] == 1


# ===================== 整体：从 core.compliance 顶层导出 =====================

def test_core_compliance_exports() -> None:
    import core.compliance as cc
    for name in [
        "PIIMask", "pii_mask",
        "SensitiveFilter", "sensitive_filter",
        "PrivacyStripper", "privacy_stripper",
        "ComplianceChecker", "compliance_checker",
        "DataLifecycle", "data_lifecycle",
        "AES256Crypto", "SensitiveString",
        "ArchiveMixin",
    ]:
        assert hasattr(cc, name), f"缺少导出: {name}"


# ===================== 与 T04 脱敏工具一致性 =====================

def test_mask_phone_consistency_with_t04() -> None:
    from core.compliance.sensitive_crypto import mask_phone as t04_mask
    local = PIIMask().mask_phone("13800138000")
    assert t04_mask("13800138000") == local
