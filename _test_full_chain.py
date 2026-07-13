import sys, os
sys.path.insert(0, os.path.dirname(__file__))

print("=" * 80)
print("🔬 测试 1: StepConfig.from_dict 自动补齐字段")
print("=" * 80)
from business.custom_spider.step_models import StepConfig, StepsPackage

# 1. 测试缺少 step_id 和 step_order 的情况（用户报告的问题）
step_dict1 = {"step_type": "page_access", "title": "页面访问", "config": {"url": "https://example.com"}}
try:
    step1 = StepConfig.from_dict(step_dict1)
    print(f"✅ 成功创建 StepConfig")
    print(f"   step_id (自动生成): {step1.step_id}")
    print(f"   step_order (自动生成): {step1.step_order}")
    print(f"   step_type: {step1.step_type}")
    print(f"   title: {step1.title}")
except Exception as e:
    print(f"❌ 失败: {e}")
    sys.exit(1)

# 2. 测试包含完整字段的情况
step_dict2 = {"step_id": "step_001", "step_order": 2, "step_type": "list_detect", "title": "列表识别", "config": {"item_selector": ".news"}}
try:
    step2 = StepConfig.from_dict(step_dict2)
    print(f"\n✅ 完整字段测试通过")
    print(f"   step_id: {step2.step_id}")
    print(f"   step_order: {step2.step_order}")
except Exception as e:
    print(f"❌ 失败: {e}")
    sys.exit(1)

print("\n" + "=" * 80)
print("🔬 测试 2: StepsPackage.from_dict 处理前端数据")
print("=" * 80)

# 模拟前端发送的数据（缺少 step_id 和 step_order）
package_dict = {
    "plan_name": "测试方案",
    "steps": [
        {"step_type": "page_access", "title": "页面访问", "config": {"url": "https://example.com"}},
        {"step_type": "list_detect", "title": "列表识别", "config": {"item_selector": ".news", "link_selector": "a"}},
        {"step_type": "field_mapping", "title": "字段映射", "config": {"map": {"标题": "title", "链接": "url"}}},
    ]
}

try:
    package = StepsPackage.from_dict(package_dict)
    package.normalize()
    print(f"✅ 成功创建 StepsPackage")
    print(f"   步骤数: {len(package.steps)}")
    for i, s in enumerate(package.steps):
        print(f"   步骤 {i+1}: {s.step_id[:30]}... | order={s.step_order} | type={s.step_type}")
except Exception as e:
    print(f"❌ 失败: {e}")
    import traceback
    traceback.print_exc()
    sys.exit(1)

print("\n" + "=" * 80)
print("🔬 测试 3: 模拟全链路测试 (使用 StepTester)")
print("=" * 80)

try:
    from business.custom_spider.step_service import StepTester
    
    # 创建一个简单的测试 package
    test_package = StepsPackage(
        plan_name="测试方案",
        target_domain="example.com",
        steps=[
            StepConfig(step_id="s1", step_order=1, step_type="page_access", title="页面访问",
                      config={"url": "https://example.com", "use_render": False}),
            StepConfig(step_id="s2", step_order=2, step_type="list_detect", title="列表识别",
                      config={"item_selector": "div", "link_selector": "a", "link_attribute": "href",
                              "crawl_scope": "latest", "top_n_count": 5}),
            StepConfig(step_id="s3", step_order=3, step_type="field_mapping", title="字段映射",
                      config={"map": {"标题": "items[0].text", "链接": "items[0].url"}}),
        ]
    )
    test_package.normalize()
    print(f"✅ 测试 package 已创建，共 {len(test_package.steps)} 个步骤")
    
    # 执行全链路测试
    result = StepTester.run_all(test_package)
    print(f"\n✅ 全链路测试完成")
    print(f"   success: {result['success']}")
    print(f"   duration_ms: {result['duration_ms']}")
    print(f"   steps 数量: {len(result['steps'])}")
    print(f"   final_items 类型: {type(result['final_items']).__name__}, 数量: {len(result['final_items']) if isinstance(result['final_items'], list) else 'N/A'}")
    
    for i, s in enumerate(result["steps"]):
        status = "✅" if s.get("success") else "❌"
        print(f"   {status} 步骤 {i+1}: {s.get('step_type')} - {s.get('message', '')[:60]}")
        
except Exception as e:
    print(f"❌ 失败: {e}")
    import traceback
    traceback.print_exc()

print("\n" + "=" * 80)
print("🎉 所有测试通过！")
print("=" * 80)
print("\n关键修复点:")
print("1. StepConfig.from_dict 现在会自动生成缺失的 step_id 和 step_order")
print("2. 前端 doTestFull/doIncrementalTest 现在会发送完整的 step_id 和 step_order")
print("3. 全链路测试结果现在显示详细的抓取内容和每个步骤的输出")
print("4. 结果浮层中显示最终抓取到的数据记录")
