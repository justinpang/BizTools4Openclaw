from __future__ import annotations

import json
from datetime import datetime, timedelta
from pathlib import Path


# ------------------------------------------------------------
# blacklist_filter 测试
# ------------------------------------------------------------


def test_blacklist_filter_basic(tmp_path: Path):
    from core.data_core.blacklist_filter import BlacklistFilter, BlacklistItem

    bl = BlacklistFilter(
        items=[
            BlacklistItem(type="company", value="不良公司A", reason="黑名单企业"),
            BlacklistItem(type="phone", value="13800000001", reason="营销号码"),
            BlacklistItem(type="wechat", value="wx_spam", reason="违规微信"),
            BlacklistItem(type="domain", value="bad-domain.com", reason="竞品域名"),
        ]
    )

    clue_a = {
        "company_name": "正常科技公司",
        "contact_phone": "13900000001",
        "requirement_text": "需要采购机器",
    }
    [fr_a] = bl.filter_batch([clue_a])
    assert fr_a.is_blocked is False

    clue_b = {"company_name": "不良公司A销售中心", "contact_phone": "13900000002"}
    [fr_b] = bl.filter_batch([clue_b])
    assert fr_b.is_blocked is True
    assert any(m.item_type == "company" for m in fr_b.matches)

    clue_c = {"contact_phone": "13800000001"}
    [fr_c] = bl.filter_batch([clue_c])
    assert fr_c.is_blocked is True

    clue_d = {"contact_wechat": "wx_spam"}
    [fr_d] = bl.filter_batch([clue_d])
    assert fr_d.is_blocked is True


def test_blacklist_filter_from_file(tmp_path: Path):
    from core.data_core.blacklist_filter import BlacklistFilter

    file_path = tmp_path / "blacklist.json"
    data = [
        {"type": "company", "value": "竞品公司X"},
        {"type": "phone", "value": "15000000001"},
    ]
    file_path.write_text(json.dumps(data), encoding="utf-8")

    bl = BlacklistFilter(blacklist_file=str(file_path))
    [fr] = bl.filter_batch([
        {"company_name": "竞品公司X的子公司", "contact_phone": "13900000001"}
    ])
    assert fr.is_blocked is True


def test_blacklist_filter_filter_batch():
    from core.data_core.blacklist_filter import BlacklistFilter, BlacklistItem

    bl = BlacklistFilter(items=[BlacklistItem(type="phone", value="13800000001")])
    clues = [
        {"contact_phone": "13800000001"},
        {"contact_phone": "13900000001"},
        {"contact_phone": "13900000002"},
    ]
    results = bl.filter_batch(clues)
    assert len(results) == 3
    assert results[0].is_blocked is True
    assert results[1].is_blocked is False


# ------------------------------------------------------------
# dedupe_engine 测试
# ------------------------------------------------------------


def test_dedupe_engine_phone_match():
    from core.data_core.dedupe_engine import DedupeEngine

    engine = DedupeEngine(text_threshold=0.7, enable_text=False)
    clues = [
        {"clue_id": "a", "contact_phone": "13800000001"},
        {"clue_id": "b", "contact_phone": "138-0000-0001"},
        {"clue_id": "c", "contact_phone": "13900000002"},
    ]
    result = engine.deduplicate(clues)
    assert result.total_clues == 3
    assert result.matches
    assert any({m.clue_a, m.clue_b} == {"a", "b"} for m in result.matches)


def test_dedupe_engine_text_similarity():
    from core.data_core.dedupe_engine import DedupeEngine

    engine = DedupeEngine(
        text_threshold=0.35,
        enable_phone=False,
        enable_wechat=False,
        enable_user_id=False,
    )
    clues = [
        {"clue_id": "a", "requirement_text": "我们公司需要采购一批高质量的电脑服务器设备，预算充足"},
        {"clue_id": "b", "requirement_text": "我们公司需要采购一批高质量的电脑服务器设备，预算充足"},
        {"clue_id": "c", "requirement_text": "寻找海外代购合作方，长期稳定的项目合作机会"},
    ]
    result = engine.deduplicate(clues)
    a_b = [m for m in result.matches if {m.clue_a, m.clue_b} == {"a", "b"}]
    assert len(a_b) >= 1
    a_c = [m for m in result.matches if {m.clue_a, m.clue_b} == {"a", "c"}]
    assert len(a_c) == 0


def test_dedupe_engine_user_id_same_platform():
    from core.data_core.dedupe_engine import DedupeEngine

    engine = DedupeEngine(
        text_threshold=0.7,
        enable_phone=False,
        enable_wechat=False,
        enable_text=False,
    )
    clues = [
        {"clue_id": "a", "source_platform": "b2b", "user_id": "u1"},
        {"clue_id": "b", "source_platform": "b2b", "user_id": "u1"},
        {"clue_id": "c", "source_platform": "social", "user_id": "u1"},
    ]
    result = engine.deduplicate(clues)
    assert any("a" in members and "b" in members for members in result.clusters.values())


# ------------------------------------------------------------
# merge_engine 测试
# ------------------------------------------------------------


def test_merge_engine_basic():
    from core.data_core.merge_engine import MergeEngine

    clues = [
        {
            "clue_id": "a",
            "company_name": "优秀科技有限公司",
            "source_platform": "b2b",
            "contact_phone": "13800000001",
            "requirement_text": "需要采购一批服务器",
            "industry": "IT",
            "capture_time": (datetime.now() - timedelta(days=5)).isoformat(),
            "raw_id": 101,
        },
        {
            "clue_id": "b",
            "company_name": "优秀科技",
            "source_platform": "forum",
            "contact_phone": "138-0000-0001",
            "contact_wechat": "wx_sales",
            "requirement_text": "需要采购一批服务器，预算充足",
            "industry": "IT",
            "capture_time": (datetime.now() - timedelta(days=2)).isoformat(),
            "raw_id": 102,
        },
    ]
    clusters = {"a": ["a", "b"]}
    me = MergeEngine()
    mr = me.merge_clusters(clues, clusters)
    assert mr.total_input == 2
    assert mr.total_merged == 1
    main = mr.merged[0]
    assert main.company_name is not None
    assert "服务器" in main.requirement_text


def test_merge_engine_standalone():
    from core.data_core.merge_engine import MergeEngine

    clues = [
        {
            "clue_id": "x",
            "company_name": "独立公司",
            "source_platform": "b2b",
            "contact_phone": "13900000001",
            "requirement_text": "求购办公家具",
            "capture_time": datetime.now().isoformat(),
        }
    ]
    clusters = {"x": ["x"]}
    me = MergeEngine()
    mr = me.merge_clusters(clues, clusters)
    assert mr.total_merged == 1
    assert len(mr.duplicates) == 0


# ------------------------------------------------------------
# scoring_engine 测试
# ------------------------------------------------------------


def test_scoring_engine_basic():
    from core.data_core.scoring_engine import (
        GRADE_HIGH, GRADE_JUNK, GRADE_LOW, GRADE_NORMAL, ScoringEngine,
    )

    se = ScoringEngine(
        high_industries=["it", "软件"],
        channel_weights={"b2b": 0.9, "forum": 0.5, "other": 0.3},
    )
    clue = {
        "company_name": "优质科技有限公司",
        "industry": "IT",
        "source_platform": "b2b",
        "contact_phone": "13800000001",
        "contact_wechat": "wx_hi",
        "requirement_text": "我们急需采购一批服务器，预算充足，希望立即联系",
        "capture_time": datetime.now().isoformat(),
    }
    sr = se.score_one(clue)
    assert sr.score >= 25
    assert sr.grade in (GRADE_HIGH, GRADE_NORMAL, GRADE_LOW)

    clue_junk = {
        "company_name": "",
        "source_platform": "other",
        "requirement_text": "",
        "capture_time": (datetime.now() - timedelta(days=365)).isoformat(),
    }
    sr_junk = se.score_one(clue_junk)
    assert sr_junk.score < 35


def test_scoring_engine_thresholds():
    from core.data_core.scoring_engine import (
        GRADE_HIGH, GRADE_JUNK, GRADE_LOW, GRADE_NORMAL, ScoringEngine,
    )

    se = ScoringEngine(grade_thresholds={"high": 80, "normal": 50, "low": 25})
    assert se.grade_from_score(95) == GRADE_HIGH
    assert se.grade_from_score(65) == GRADE_NORMAL
    assert se.grade_from_score(30) == GRADE_LOW
    assert se.grade_from_score(10) == GRADE_JUNK


# ------------------------------------------------------------
# pipeline 测试
# ------------------------------------------------------------


def test_pipeline_full_flow():
    from core.data_core.pipeline import OpportunityPipeline
    from core.data_core.blacklist_filter import BlacklistFilter, BlacklistItem

    bl = BlacklistFilter(items=[BlacklistItem(type="phone", value="15000000001")])
    pipeline = OpportunityPipeline(
        blacklist_filter=bl,
        enable_compliance_check=False,
    )

    now = datetime.now()
    clues = [
        {
            "clue_id": "1",
            "company_name": "优质科技有限公司",
            "industry": "IT",
            "source_platform": "b2b",
            "contact_phone": "13800000001",
            "contact_wechat": "wx_sales",
            "requirement_text": "急需采购一批服务器，预算充足",
            "capture_time": now.isoformat(),
            "raw_id": 1,
        },
        {
            "clue_id": "2",
            "company_name": "优质科技",
            "source_platform": "forum",
            "contact_phone": "138-0000-0001",
            "contact_wechat": "wx_sales",
            "requirement_text": "我们公司正在寻找服务器供应商",
            "industry": "IT",
            "capture_time": (now - timedelta(days=2)).isoformat(),
            "raw_id": 2,
        },
        {
            "clue_id": "3",
            "contact_phone": "15000000001",
            "requirement_text": "垃圾内容",
            "capture_time": (now - timedelta(days=300)).isoformat(),
        },
    ]
    result = pipeline.process_batch(clues)
    assert result.total_input == 3
    assert result.blocked_by_blacklist == 1
    assert result.duplicates_removed >= 1
    assert result.final_opportunities >= 1

    # 脱敏：不应该有明文 13800000001 / wx_sales
    for item in result.items:
        for phone in item.contact_phones:
            assert "13800000001" not in (phone or "")
        for wx in item.contact_wechats:
            assert wx != "wx_sales"


def test_pipeline_empty_input():
    from core.data_core.pipeline import OpportunityPipeline

    pl = OpportunityPipeline(enable_compliance_check=False)
    result = pl.process_batch([])
    assert result.total_input == 0
    assert result.final_opportunities == 0


# ------------------------------------------------------------
# 模块级单例可访问
# ------------------------------------------------------------


def test_module_singletons_accessible():
    import core.data_core as dc
    assert dc.blacklist_filter is not None
    assert dc.dedupe_engine is not None
    assert dc.merge_engine is not None
    assert dc.scoring_engine is not None
    assert dc.opportunity_pipeline is not None
