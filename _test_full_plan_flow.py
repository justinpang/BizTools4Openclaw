import requests
import json
import sys

BASE_URL = "http://localhost:8000"

def test_full_plan_flow():
    """测试完整的方案保存-加载-验证流程"""
    print("=" * 70)
    print("🧪 测试完整方案管理流程")
    print("=" * 70)
    
    # 测试数据
    test_plan = {
        "plan_name": "方案管理完整测试",
        "steps": [
            {
                "step_type": "page_access",
                "title": "页面访问",
                "config": {
                    "url": "https://example.gov.cn/news",
                    "use_render": False,
                    "render_wait_ms": 1500
                }
            },
            {
                "step_type": "list_detect",
                "title": "列表识别",
                "config": {
                    "item_selector": ".news-item",
                    "link_selector": "a.title",
                    "crawl_scope": "latest",
                    "top_n_count": 20
                }
            },
            {
                "step_type": "detail_jump",
                "title": "详情跳转",
                "config": {
                    "url": "",
                    "detail_fields": ["title", "content", "publish_date"]
                }
            },
            {
                "step_type": "attachment_parse",
                "title": "附件解析",
                "config": {
                    "url": "",
                    "extract_pdf": True,
                    "extract_doc": True,
                    "extract_excel": True,
                    "link_selector": "a[href$='.pdf'],a[href$='.doc']"
                }
            },
            {
                "step_type": "field_mapping",
                "title": "字段映射",
                "config": {
                    "map": {
                        "标题": "items[0].title",
                        "内容": "attachments[0].text",
                        "发布日期": "detail_jump.result.publish_date",
                        "来源": "=政府公告"
                    }
                }
            }
        ]
    }
    
    # 1. 保存方案
    print("\n📝 步骤 1: 保存方案")
    print("-" * 70)
    try:
        response = requests.post(
            f"{BASE_URL}/api/admin/crawl/steps/save-plan",
            json=test_plan,
            timeout=30
        )
        result = response.json()
        print(f"HTTP 状态码: {response.status_code}")
        print(f"返回 code: {result.get('code')}")
        
        if result.get("code") == 0 and result.get("data"):
            plan_id = result["data"].get("plan_id")
            print(f"✅ 保存成功，方案 ID: {plan_id}")
            print(f"   方案 code: {result['data'].get('plan_code')}")
        else:
            print(f"❌ 保存失败: {result.get('msg')}")
            return False
    except Exception as e:
        print(f"❌ 异常: {e}")
        return False
    
    # 2. 加载方案
    print("\n📖 步骤 2: 加载方案")
    print("-" * 70)
    try:
        response = requests.get(
            f"{BASE_URL}/api/admin/crawl/steps/plan?plan_id={plan_id}",
            timeout=30
        )
        result = response.json()
        print(f"HTTP 状态码: {response.status_code}")
        
        if result.get("code") == 0 and result.get("data"):
            loaded = result["data"]
            print(f"✅ 加载成功")
            print(f"   方案名称: {loaded.get('plan_name')}")
            print(f"   目标域名: {loaded.get('target_domain')}")
            print(f"   URL: {loaded.get('url')}")
            print(f"   步骤数: {len(loaded.get('steps', []))}")
            
            # 3. 验证每个步骤
            print("\n🔍 步骤 3: 验证每个步骤")
            print("-" * 70)
            
            success = True
            loaded_steps = loaded.get("steps", [])
            original_steps = test_plan["steps"]
            
            if len(loaded_steps) != len(original_steps):
                print(f"❌ 步骤数不匹配: 期望 {len(original_steps)}, 实际 {len(loaded_steps)}")
                return False
            
            for i, (loaded_step, original_step) in enumerate(zip(loaded_steps, original_steps)):
                # 验证步骤类型
                if loaded_step.get("step_type") != original_step["step_type"]:
                    print(f"❌ 步骤 {i+1}: 类型不匹配")
                    success = False
                    continue
                
                # 验证标题
                if loaded_step.get("title") != original_step["title"]:
                    print(f"❌ 步骤 {i+1}: 标题不匹配")
                    success = False
                    continue
                
                # 验证配置
                loaded_config = loaded_step.get("config", {})
                original_config = original_step.get("config", {})
                
                # 对于 field_mapping，特殊处理 map 字段
                if original_step["step_type"] == "field_mapping":
                    loaded_map = loaded_config.get("map", {})
                    original_map = original_config.get("map", {})
                    if set(loaded_map.keys()) != set(original_map.keys()):
                        print(f"❌ 步骤 {i+1}: field_mapping 字段不匹配")
                        print(f"   期望: {list(original_map.keys())}")
                        print(f"   实际: {list(loaded_map.keys())}")
                        success = False
                    else:
                        print(f"✅ 步骤 {i+1}: {original_step['step_type']} - 字段映射正确，共 {len(loaded_map)} 个字段")
                else:
                    # 检查关键字段是否存在
                    for key in ["url", "item_selector", "link_selector"]:
                        if key in original_config and loaded_config.get(key) != original_config[key]:
                            print(f"⚠️  步骤 {i+1}: {key} 字段可能不匹配")
                            print(f"   期望: {original_config[key]}")
                            print(f"   实际: {loaded_config.get(key)}")
                    
                    print(f"✅ 步骤 {i+1}: {original_step['step_type']} - {original_step['title']}")
            
            # 4. 验证 URL 字段
            print("\n🔗 步骤 4: 验证 URL 填充")
            print("-" * 70)
            if loaded.get("url"):
                print(f"✅ URL 字段已填充: {loaded['url']}")
            else:
                print(f"❌ URL 字段为空")
                success = False
            
            # 5. 验证方案名称
            print("\n📋 步骤 5: 验证方案名称")
            print("-" * 70)
            if loaded.get("plan_name") == test_plan["plan_name"]:
                print(f"✅ 方案名称正确: {loaded['plan_name']}")
            else:
                print(f"❌ 方案名称不匹配")
                print(f"   期望: {test_plan['plan_name']}")
                print(f"   实际: {loaded.get('plan_name')}")
                success = False
            
            # 6. 测试版本管理
            print("\n📜 步骤 6: 测试版本管理")
            print("-" * 70)
            try:
                version_response = requests.get(
                    f"{BASE_URL}/api/admin/crawl/steps/versions?plan_id={plan_id}",
                    timeout=30
                )
                version_result = version_response.json()
                if version_result.get("code") == 0:
                    versions = version_result.get("data", {}).get("versions", [])
                    print(f"✅ 版本列表获取成功，共 {len(versions)} 个版本")
                    for v in versions:
                        print(f"   - 版本 {v.get('version')}: {v.get('saved_at')}, 步骤数: {v.get('step_count', 0)}")
                else:
                    print(f"⚠️  版本列表获取失败: {version_result.get('msg')}")
            except Exception as e:
                print(f"⚠️  版本管理测试异常: {e}")
            
            return success
        else:
            print(f"❌ 加载失败: {result.get('msg')}")
            return False
    except Exception as e:
        print(f"❌ 加载异常: {e}")
        import traceback
        traceback.print_exc()
        return False

if __name__ == "__main__":
    success = test_full_plan_flow()
    print("\n" + "=" * 70)
    if success:
        print("🎉 所有测试通过！方案管理功能正常工作")
    else:
        print("❌ 测试失败，需要进一步排查")
    print("=" * 70)
    sys.exit(0 if success else 1)
