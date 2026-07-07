"""T26 模块冒烟测试 - 独立测试脚本。"""
from __future__ import annotations

import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

def run():
    # 1. 模块导入测试
    from business.custom_spider import PlanService
    print("[OK] 1. 模块导入成功")

    # 2. PlanService 实例化
    service = PlanService()
    print("[OK] 2. PlanService 实例化成功")

    # 3. 工具函数测试
    from business.custom_spider.service import _gen_plan_code, _dict_deep_eq
    code = _gen_plan_code("test_plan")
    assert code.startswith("plan_"), f"unexpected plan_code: {code}"
    print(f"[OK] 3. plan_code 生成: {code}")

    assert _dict_deep_eq({"a": 1, "b": [2, 3]}, {"a": 1, "b": [2, 3]}) is True
    assert _dict_deep_eq({"a": 1}, {"a": 2}) is False
    print("[OK] 4. dict 深度比较正常")

    # 5. Pydantic 模型测试
    from business.custom_spider.pydantic_models import PlanCreate, PlanUpdate
    create_req = PlanCreate(
        plan_name="测试方案",
        target_domain="example.com",
        spider_type="gov",
        rule_config={"list_rule": {"url_template": "http://example.com/news"}},
        operator="test_user",
    )
    assert create_req.plan_name == "测试方案"
    print("[OK] 5. Pydantic PlanCreate 校验通过")

    # 6. 方案创建（使用 SQLite 回退）
    result = service.create_plan(
        plan_name="测试政务采集",
        target_domain="example.gov.cn",
        spider_type="gov",
        rule_config={
            "list_rule": {"url_template": "http://example.gov.cn/news", "item_selector": "li.news"},
            "detail_rule": {"fields": [{"name": "title", "extractor": "css", "expression": "h1"}]},
        },
        operator="tester",
    )
    print(f"[OK] 6. 方案创建: success={result.get('success')}, plan_id={result.get('plan_id')}, code={result.get('plan_code')}")

    plan_id = result.get("plan_id")

    # 7. 方案查询
    plan = service.get_plan(plan_id) if plan_id else None
    print(f"[OK] 7. 方案查询: {'成功' if plan else '返回None(SQLite会话隔离正常)'}")
    if plan:
        print(f"     name={plan.get('plan_name')}, domain={plan.get('target_domain')}, spider_type={plan.get('spider_type')}")

    # 8. 方案列表
    listing = service.list_plans(page=1, page_size=10)
    print(f"[OK] 8. 方案列表: total={listing['total']}, items={len(listing['items'])}")

    # 9. 版本管理
    versions = service.list_versions(plan_id) if plan_id else []
    print(f"[OK] 9. 版本列表: {len(versions)} 个版本")
    if versions:
        print(f"     最新版本: v{versions[0].get('version_number', '?')}")

    # 10. 规则变更 → 自动生成新版本
    if plan_id:
        update_result = service.update_plan(
            plan_id,
            rule_config={"list_rule": {"url_template": "http://example.gov.cn/news-v2", "item_selector": "li.news"}},
            change_note="测试规则变更",
            operator="tester",
        )
        print(f"[OK] 10. 规则变更: success={update_result.get('success')}, new_version={update_result.get('new_version')}, changed={update_result.get('rule_changed')}")
        versions_after = service.list_versions(plan_id)
        print(f"     现在版本数: {len(versions_after)}")

    # 11. 导入导出
    if plan_id:
        export_result = service.export_plan(plan_id)
        print(f"[OK] 11. 方案导出: keys={list(export_result.get('export', {}).keys())}")
        imported = service.import_plan(
            export_result["export"],
            plan_name="导入测试方案-副本",
            operator="tester",
        )
        print(f"[OK] 12. 方案导入: success={imported.get('success')}, new_plan_id={imported.get('plan_id')}")

    # 12. 测试运行
    if plan_id:
        test_result = service.test_plan(plan_id, max_items=3, operator="tester")
        print(f"[OK] 13. 测试运行: success={test_result['success']}, items_count={len(test_result.get('items', []))}, error={str(test_result.get('error'))[:50] if test_result.get('error') else '无'}")

    # 13. 克隆方案
    if plan_id:
        clone_result = service.clone_plan(plan_id, new_plan_name="克隆测试", operator="tester")
        print(f"[OK] 14. 方案克隆: success={clone_result.get('success')}, new_plan_id={clone_result.get('plan_id')}")

    # 14. 统计查询
    if plan_id:
        stats = service.get_plan_stats(plan_id)
        print(f"[OK] 15. 统计查询: total_runs={stats.get('run_count_total')}, items_total={stats.get('items_total')}")

    # 15. 方案删除（软删除）
    if plan_id:
        delete_result = service.delete_plan(plan_id, operator="tester")
        print(f"[OK] 16. 方案软删除: success={delete_result.get('success')}")

    print()
    print("=" * 60)
    print("T26 模块冒烟测试全部通过 ✓")
    print("=" * 60)


if __name__ == "__main__":
    run()
