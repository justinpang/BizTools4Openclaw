"""T29 企业信息自动补全单元测试。

运行: python -m pytest tests/test_t29_enterprise_enrich.py -v
或:  python tests/test_t29_enterprise_enrich.py

注意:
  - 本测试不依赖真实的 Playwright / Redis / 爱企查网站
  - 所有外部调用通过 monkey patch 替换为 mock
  - 核心测试目标: 字段合并逻辑、优先级策略、缓存、异常处理
"""

from __future__ import annotations

import json
import sys
import time
from pathlib import Path

# 确保项目根目录在 sys.path 中
ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from business.data_clean.enterprise_cache import (
    EnterpriseCache,
    normalize_company_name,
)
from business.data_clean.enterprise_enrich import (
    EnterpriseEnrichStep,
    EnterpriseEnrichWorker,
    _has_contact_info,
    _merge_profile_into_entities,
)
from business.data_clean.enterprise_models import (
    EnterpriseEnrichBatchResult,
    EnterpriseEnrichResult,
    EnterpriseProfile,
)


# ============================================================
# 工具类
# ============================================================

class MockEntities:
    """模拟 EntityExtract（简化版，只含关键字段）。"""

    def __init__(self, company_names=None, phone_numbers=None, wechat_ids=None,
                 industry_tags=None):
        self.company_names = list(company_names or [])
        self.phone_numbers = list(phone_numbers or [])
        self.wechat_ids = list(wechat_ids or [])
        self.industry_tags = list(industry_tags or [])
        self.enriched = False
        self.enrichment_source = ""
        self.enrichment_profile = {}


class MockOpportunity:
    """模拟 StructuredOpportunity。"""

    def __init__(self, company_name, has_phone=False, has_wechat=False,
                 industry_tags=None):
        self.entities = MockEntities(
            company_names=[company_name] if company_name else [],
            phone_numbers=["138-0000-0000"] if has_phone else [],
            wechat_ids=["wx_test"] if has_wechat else [],
            industry_tags=industry_tags or [],
        )
        self.opportunity_id = f"opp_{id(self)}"
        self.tenant_id = "default"
        # 兼容 enrich_step 需要的字段
        self.source = type("S", (), {"spider_name": "test", "source_url": ""})()


# ============================================================
# 测试 1: EnterpriseProfile 标准化结构
# ============================================================

def test_profile_structure():
    prof = EnterpriseProfile(
        company_name="阿里云计算有限公司",
        contact_phone="010-12345678",
        contact_email="contact@aliyun.com",
        registered_address="浙江省杭州市余杭区文一西路 969 号",
        company_scale="大型",
        industry_category="软件和信息技术服务业",
        registered_capital="5亿元人民币",
        legal_representative="吴泳铭",
        business_status="存续",
        credit_code="91330000799655058B",
        confidence_score=0.95,
        source_channel="aiqicha",
        source_mode="web",
    )
    data = prof.model_dump_json()
    # 反序列化回来
    restored = EnterpriseProfile(**json.loads(data))
    assert restored.company_name == "阿里云计算有限公司"
    assert restored.contact_phone == "010-12345678"
    assert restored.confidence_score == 0.95
    assert restored.has_contact_info() is True
    print("  ✓ profile 序列化/反序列化 OK")


def test_profile_empty_contact():
    prof = EnterpriseProfile(company_name="小公司")
    assert prof.has_contact_info() is False
    print("  ✓ 空联系方式判断 OK")


# ============================================================
# 测试 2: 企业名称规范化 + 缓存
# ============================================================

def test_normalize_company_name():
    # 各种后缀变体 → 应统一
    names = [
        "阿里云计算有限公司",
        "阿里云计算公司",
        "阿里云计算股份有限公司",
        "阿里云计算有限责任公司",
    ]
    normalized = set(normalize_company_name(n) for n in names)
    assert len(normalized) == 1, f"不同后缀应规范化为相同: {normalized}"
    print("  ✓ 公司后缀规范化 OK")

    # 空名 / 空格
    assert normalize_company_name("") == ""
    assert normalize_company_name("  百度  ") != ""
    print("  ✓ 边界值处理 OK")


def test_cache_roundtrip():
    cache = EnterpriseCache()
    cache.clear()
    prof = EnterpriseProfile(
        company_name="Test Inc.", contact_phone="1-800-TEST",
        source_channel="aiqicha"
    )
    cache.set("Test Inc.", prof)
    cached = cache.get("Test Inc.")
    assert cached is not None
    assert cached.contact_phone == "1-800-TEST"
    print("  ✓ 缓存读写 OK")


def test_negative_cache():
    cache = EnterpriseCache()
    cache.clear()
    cache.mark_negative("不存在的公司")
    cached = cache.get("不存在的公司")
    assert cached is not None  # 返回 "查无此企业" 的 marker
    print("  ✓ 阴性缓存 OK")


# ============================================================
# 测试 3: 联系方式检测（跳过已有联系方式的企业）
# ============================================================

def test_has_contact_info():
    e1 = MockEntities(phone_numbers=["138-0000-0001"])
    assert _has_contact_info(e1) is True
    e2 = MockEntities(wechat_ids=["wx_business"])
    assert _has_contact_info(e2) is True
    e3 = MockEntities()
    assert _has_contact_info(e3) is False
    print("  ✓ 联系方式检测 OK")


# ============================================================
# 测试 4: 字段合并（只补全空字段，不覆盖已有数据）
# ============================================================

def test_merge_fill_empty():
    e = MockEntities(company_names=["腾讯科技"])
    prof = EnterpriseProfile(
        company_name="腾讯科技", contact_phone="0755-88888888",
        industry_category="软件和信息技术服务业", source_channel="aiqicha",
    )
    merged = _merge_profile_into_entities(e, prof)
    assert "contact_phone" in merged
    assert e.phone_numbers == ["0755-88888888"]
    assert e.enriched is True
    assert e.enrichment_source == "aiqicha"
    assert len(e.enrichment_profile) > 5
    print("  ✓ 空字段补全 OK")


def test_merge_does_not_overwrite_phone():
    """原数据已有电话 → 不覆盖原电话，只填充其他字段。"""
    e = MockEntities(company_names=["已有电话公司"], phone_numbers=["138-0000-9999"])
    prof = EnterpriseProfile(
        company_name="已有电话公司",
        contact_phone="0755-NEW-NEW",  # 不应覆盖
        industry_category="制造业",
        source_channel="aiqicha",
    )
    _merge_profile_into_entities(e, prof)
    # 关键断言：原电话保持不变
    assert e.phone_numbers == ["138-0000-9999"]
    # 但 enrichment_profile 中仍存新数据（供人工参考）
    assert e.enrichment_profile.get("contact_phone") == "0755-NEW-NEW"
    print("  ✓ 不覆盖已有联系方式 OK")


def test_merge_does_not_overwrite_industry():
    """原数据已有行业标签 → 不应替换。"""
    e = MockEntities(company_names=["已有行业公司"], industry_tags=["电子商务"])
    prof = EnterpriseProfile(
        company_name="已有行业公司", contact_phone="010-NEW",
        industry_category="互联网/电商", source_channel="aiqicha",
    )
    _merge_profile_into_entities(e, prof)
    assert e.industry_tags == ["电子商务"]  # 保留原数据
    print("  ✓ 不覆盖已有行业 OK")


# ============================================================
# 测试 5: EnterpriseEnrichStep — process_opportunities 过滤逻辑
# ============================================================

def test_step_filter_opportunities():
    """构建一批混合商机：应补全 / 已有电话 / 无企业名。"""

    # Mock 掉真正的查询实现（不发起真实 HTTP 调用）
    class _DummyStep(EnterpriseEnrichStep):
        def _process_sync(self, to_enrich):
            return {"total": len(to_enrich), "enriched": len(to_enrich), "mode": "sync"}

    step = _DummyStep()
    opps = [
        MockOpportunity("需要补全公司"),                      # 应补全
        MockOpportunity("已有电话公司", has_phone=True),      # 跳过
        MockOpportunity("", has_phone=False),                 # 无企业名 → 跳过
        MockOpportunity("有微信", has_wechat=True),           # 跳过
    ]
    result = step.process_opportunities(opps, mode="sync")
    # 只有第 1 条需要补全
    assert result["total"] == 1
    print("  ✓ 补全目标过滤 OK")


# ============================================================
# 测试 6: 异步 Worker — 任务消费逻辑
# ============================================================

def test_worker_task_consumption():
    """模拟 Redis 队列中有一条任务，Worker 能消费并产出结果。"""
    worker = EnterpriseEnrichWorker()
    # 直接 mock 一个任务（不走 Redis）
    task = {
        "task_id": "test_001",
        "items": [
            {"company": "虚拟公司A", "opp_id": "a1", "tenant_id": "t1"},
            {"company": "虚拟公司B", "opp_id": "b2", "tenant_id": "t1"},
        ],
    }
    result = worker._execute_task(task)
    assert result.task_id == "test_001"
    assert result.total == 2
    # 因为没有真实查询能力，两条都应报 failed/not_found
    # 关键是：Worker 不会因为查询失败而崩溃
    assert result.enriched + result.not_found + result.failed + result.skipped == 2
    print(f"  ✓ Worker 消费任务 OK (enriched={result.enriched}, "
          f"not_found={result.not_found}, failed={result.failed}, skipped={result.skipped})")


# ============================================================
# 测试 7: EnterpriseEnrichResult 状态
# ============================================================

def test_enrich_result_states():
    # 成功
    r1 = EnterpriseEnrichResult(
        success=True, status="enriched", company_name="A公司",
        profile=EnterpriseProfile(company_name="A公司", contact_phone="1"),
    )
    assert r1.is_usable is True

    # 失败
    r2 = EnterpriseEnrichResult(
        success=False, status="failed", company_name="B公司",
        error_message="HTTP 500", needs_manual_review=True,
    )
    assert r2.is_usable is False
    assert r2.needs_manual_review is True

    # 查无结果
    r3 = EnterpriseEnrichResult(
        success=False, status="not_found", company_name="C公司",
        needs_manual_review=True,
    )
    assert r3.is_usable is False
    print("  ✓ EnterpriseEnrichResult 状态 OK")


# ============================================================
# 测试 8: 完整端到端模拟（Mock 外部依赖）
# ============================================================

def test_e2e_with_mock_client():
    """Mock 爱企查客户端 → 验证从"查询→补全→写回"的完整链路。"""

    # 构造一批商机（混合情况）
    opps = [
        MockOpportunity("阿里云计算有限公司"),                   # 应被补全
        MockOpportunity("腾讯科技深圳有限公司"),                # 应被补全
        MockOpportunity("百度在线网络技术有限公司", has_phone=True),  # 已有电话 → 跳过
        MockOpportunity("", has_phone=False),                   # 无企业名 → 跳过
        MockOpportunity("小公司A", has_wechat=True),            # 有微信 → 跳过
    ]

    class _MockClient:
        """模拟爱企查客户端，按企业名返回不同结果。"""

        def __init__(self, cache=None):
            self._cache = cache or EnterpriseCache()

        def query(self, company_name: str) -> EnterpriseEnrichResult:
            if "阿里" in company_name:
                prof = EnterpriseProfile(
                    company_name=company_name, contact_phone="0571-85022088",
                    contact_email="aliyun@alibaba-inc.com",
                    industry_category="软件和信息技术服务业",
                    registered_address="浙江省杭州市余杭区文一西路",
                    confidence_score=0.95, source_channel="aiqicha", source_mode="web",
                )
                return EnterpriseEnrichResult(
                    success=True, status="enriched", company_name=company_name,
                    profile=prof, enriched_fields=["contact_phone", "industry_category"],
                )
            elif "腾讯" in company_name:
                prof = EnterpriseProfile(
                    company_name=company_name, contact_phone="0755-86013388",
                    industry_category="软件和信息技术服务业",
                    confidence_score=0.90, source_channel="aiqicha", source_mode="web",
                )
                return EnterpriseEnrichResult(
                    success=True, status="enriched", company_name=company_name,
                    profile=prof,
                )
            else:
                return EnterpriseEnrichResult(
                    success=False, status="not_found", company_name=company_name,
                    needs_manual_review=True,
                )

    # 用 mock 客户端替换
    step = EnterpriseEnrichStep()
    step._client = _MockClient()

    # 执行补全
    stats = step.process_opportunities(opps, mode="sync")

    # 验证：
    #   - total = 2 (阿里 + 腾讯)
    #   - enriched = 2
    #   - 百度 / 空名 / 小公司A 被跳过
    assert stats["total"] == 2, f"应处理 2 条，实际: {stats['total']}"
    assert stats["enriched"] == 2, f"应补全 2 条，实际: {stats['enriched']}"

    # 验证补全后的实体字段
    assert opps[0].entities.phone_numbers == ["0571-85022088"], "电话应被写入"
    assert opps[0].entities.enriched is True
    assert opps[0].entities.enrichment_source == "aiqicha"

    # 验证"已有联系方式"的商机没被修改
    assert opps[2].entities.phone_numbers == ["138-0000-0000"]
    assert opps[2].entities.enriched is False  # 从未调用 merge，保持 False

    print(f"  ✓ 端到端验证 OK: {stats}")


# ============================================================
# 测试 9: 置信度阈值（低置信度的不写入）
# ============================================================

def test_confidence_threshold_logic():
    """EnterpriseProfile.has_contact_info 不依赖置信度，
    但实际补全时我们可以判断 confidence_score。"""
    prof_low = EnterpriseProfile(company_name="低匹配", contact_phone="123",
                                 confidence_score=0.1, source_channel="aiqicha")
    prof_high = EnterpriseProfile(company_name="高匹配", contact_phone="123",
                                  confidence_score=0.9, source_channel="aiqicha")

    assert prof_low.has_contact_info() is True  # 字段存在
    assert prof_high.has_contact_info() is True

    # 实际补全时，Client 会检查 confidence_score 作为过滤（可选）
    print("  ✓ 置信度逻辑 OK")


# ============================================================
# 主入口
# ============================================================

def main():
    print("\n=== T29 企业信息补全 — 单元测试 ===\n")

    tests = [
        ("1. EnterpriseProfile 序列化", test_profile_structure),
        ("1b. 空联系方式判断", test_profile_empty_contact),
        ("2. 企业名称规范化", test_normalize_company_name),
        ("2b. 缓存读写", test_cache_roundtrip),
        ("2c. 阴性缓存", test_negative_cache),
        ("3. 联系方式检测", test_has_contact_info),
        ("4. 空字段补全", test_merge_fill_empty),
        ("4b. 不覆盖已有电话", test_merge_does_not_overwrite_phone),
        ("4c. 不覆盖已有行业", test_merge_does_not_overwrite_industry),
        ("5. 补全目标过滤", test_step_filter_opportunities),
        ("6. Worker 任务消费", test_worker_task_consumption),
        ("7. 补全结果状态", test_enrich_result_states),
        ("8. 端到端 Mock 客户端", test_e2e_with_mock_client),
        ("9. 置信度逻辑", test_confidence_threshold_logic),
    ]

    failed = 0
    for name, fn in tests:
        try:
            fn()
        except Exception as exc:
            print(f"  ✗ {name}: {exc}")
            import traceback
            traceback.print_exc()
            failed += 1

    print(f"\n=== 结果: {len(tests) - failed}/{len(tests)} 通过 ===")
    if failed > 0:
        sys.exit(1)
    else:
        print("✓ 所有测试通过\n")


if __name__ == "__main__":
    main()
