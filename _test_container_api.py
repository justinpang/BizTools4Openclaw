import requests, json, sys, time
base = "http://localhost:8000"

print("=" * 80)
print("🔬 测试: 全链路测试 API")
print("=" * 80)

# 创建一个测试方案
print("\n📝 步骤 1: 发送完整 package 到 full-test API")
package = {
    "plan_name": "全链路测试方案",
    "steps": [
        {"step_type": "page_access", "title": "页面访问", "config": {"url": "https://example.com", "use_render": False}},
        {"step_type": "list_detect", "title": "列表识别", "config": {"item_selector": ".news", "link_selector": "a", "link_attribute": "href", "crawl_scope": "latest", "top_n_count": 5}},
        {"step_type": "field_mapping", "title": "字段映射", "config": {"map": {"标题": "title", "链接": "url"}}},
    ]
}

try:
    r = requests.post(f"{base}/api/admin/crawl/steps/full-test", 
                    json={"package": package}, timeout=30)
    result = r.json()
    if result.get("code") == 0:
        data = result["data"]
        print(f"✅ 全链路测试成功")
        print(f"   success: {data.get('success')}")
        print(f"   duration_ms: {data.get('duration_ms')}")
        print(f"   steps 数量: {len(data.get('steps', []))}")
        print(f"   final_items 数量: {len(data.get('final_items', []))}")
        
        for i, s in enumerate(data.get("steps", [])):
            status = "✅" if s.get("success") else "❌"
            print(f"   {status} 步骤 {i+1}: {s.get('step_type')} | msg={s.get('message', '')[:50]}")
            
        # 检查字段名
        print(f"\n🔍 字段名检查:")
        if "final_items" in data:
            print(f"   ✅ final_items 字段存在")
        if "steps" in data:
            print(f"   ✅ steps 字段存在")
        if "success" in data:
            print(f"   ✅ success 字段存在")
    else:
        print(f"❌ 测试失败: {result.get('msg')}")
        sys.exit(1)
except Exception as e:
    print(f"❌ 异常: {e}")
    import traceback
    traceback.print_exc()
    sys.exit(1)

# 测试方案保存 + 加载（之前测试过的功能）
print("\n" + "=" * 80)
print("📋 测试: 方案保存与加载")
print("=" * 80)
try:
    r = requests.post(f"{base}/api/admin/crawl/steps/save-plan", json={
        "plan_name": "完整测试方案",
        "steps": [
            {"step_type": "page_access", "title": "页面访问", "config": {"url": "https://www.example.com", "use_render": False}},
            {"step_type": "list_detect", "title": "列表识别", "config": {"item_selector": ".news-item", "link_selector": "a.title", "link_attribute": "href", "crawl_scope": "latest", "top_n_count": 20}},
            {"step_type": "detail_jump", "title": "详情跳转", "config": {"detail_fields": ["title", "content", "publish_date"]}},
            {"step_type": "attachment_parse", "title": "附件解析", "config": {"extract_pdf": True, "link_selector": "a[href$='.pdf']"}},
            {"step_type": "field_mapping", "title": "字段映射", "config": {"map": {"标题": "items[0].title", "内容": "items[0].content"}}},
        ]
    }, timeout=30)
    result = r.json()
    if result.get("code") == 0:
        plan_id = result["data"]["plan_id"]
        print(f"✅ 保存成功 plan_id={plan_id}")
        
        # 加载
        r2 = requests.get(f"{base}/api/admin/crawl/steps/plan?plan_id={plan_id}", timeout=30)
        data2 = r2.json()
        if data2.get("code") == 0:
            print(f"✅ 加载成功: 方案={data2['data'].get('plan_name')}, 步骤数={len(data2['data'].get('steps', []))}")
            print(f"   URL填充: {data2['data'].get('url', 'N/A')[:60]}")
        else:
            print(f"❌ 加载失败")
    else:
        print(f"❌ 保存失败: {result.get('msg')}")
except Exception as e:
    print(f"❌ 异常: {e}")

print("\n" + "=" * 80)
print("🎉 容器测试完成")
print("=" * 80)
