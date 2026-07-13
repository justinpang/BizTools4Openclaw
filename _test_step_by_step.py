import requests
import json
import sys

BASE_URL = "http://localhost:8000"

def test_step_by_step():
    """逐步骤测试保存-加载流程"""
    print("=" * 60)
    print("测试步骤 1: 检查 API 是否可用")
    print("=" * 60)
    
    # 测试基本连接
    try:
        response = requests.get(f"{BASE_URL}/api/admin/crawl/plans", timeout=30)
        print(f"服务器响应状态: {response.status_code}")
        print(f"响应内容: {response.text[:500]}")
    except Exception as e:
        print(f"连接失败: {e}")
        return False
    
    print("\n" + "=" * 60)
    print("测试步骤 2: 保存方案")
    print("=" * 60)
    
    test_steps = [
        {
            "step_type": "page_access",
            "title": "页面访问",
            "config": {
                "url": "https://example.com/news",
                "use_render": False
            }
        },
        {
            "step_type": "list_detect",
            "title": "列表识别",
            "config": {
                "item_selector": ".news-item",
                "link_selector": "a.title",
                "max_items": 10
            }
        },
        {
            "step_type": "field_mapping",
            "title": "字段映射",
            "config": {
                "map": {
                    "标题": "steps[0].result.title",
                    "内容": "steps[1].result.content"
                }
            }
        }
    ]
    
    save_payload = {
        "plan_name": "测试方案-详细调试",
        "steps": test_steps,
        "target_domain": "example.com",
        "description": "这是一个测试方案"
    }
    
    print(f"\n保存请求: {json.dumps(save_payload, ensure_ascii=False, indent=2)[:500]}")
    
    try:
        response = requests.post(
            f"{BASE_URL}/api/admin/crawl/steps/save-plan",
            json=save_payload,
            timeout=30
        )
        result = response.json()
        print(f"\n保存响应状态: {response.status_code}")
        print(f"保存响应内容: {json.dumps(result, ensure_ascii=False, indent=2)}")
        
        if result.get("code") == 0 and result.get("data"):
            plan_id = result["data"].get("plan_id")
            print(f"\n✅ 保存成功，plan_id: {plan_id}")
            
            # 测试步骤 3: 加载方案
            print("\n" + "=" * 60)
            print("测试步骤 3: 加载方案")
            print("=" * 60)
            
            try:
                load_response = requests.get(
                    f"{BASE_URL}/api/admin/crawl/steps/plan?plan_id={plan_id}",
                    timeout=30
                )
                load_result = load_response.json()
                print(f"加载响应状态: {load_response.status_code}")
                print(f"加载响应内容: {json.dumps(load_result, ensure_ascii=False, indent=2)}")
                
                if load_result.get("code") == 0 and load_result.get("data"):
                    loaded_plan = load_result["data"]
                    print(f"\n✅ 加载成功")
                    print(f"方案名称: {loaded_plan.get('plan_name')}")
                    print(f"方案 URL: {loaded_plan.get('url')}")
                    print(f"步骤数量: {len(loaded_plan.get('steps', []))}")
                    
                    # 检查每个步骤
                    for i, step in enumerate(loaded_plan.get("steps", [])):
                        print(f"\n  步骤 {i+1}:")
                        print(f"    类型: {step.get('step_type')}")
                        print(f"    标题: {step.get('title')}")
                        print(f"    配置: {json.dumps(step.get('config', {}), ensure_ascii=False)}")
                    
                    # 验证数据完整性
                    print("\n" + "=" * 60)
                    print("测试步骤 4: 验证数据完整性")
                    print("=" * 60)
                    
                    # 检查 URL 是否正确填充
                    if loaded_plan.get("url"):
                        print(f"✅ URL 字段已填充: {loaded_plan['url']}")
                    else:
                        print(f"❌ URL 字段为空")
                    
                    # 检查步骤数量
                    if len(loaded_plan.get("steps", [])) == len(test_steps):
                        print(f"✅ 步骤数量匹配: {len(loaded_plan['steps'])}")
                    else:
                        print(f"❌ 步骤数量不匹配")
                    
                    # 检查字段映射是否正确
                    field_mapping_steps = [s for s in loaded_plan.get("steps", []) if s.get("step_type") == "field_mapping"]
                    if field_mapping_steps:
                        mapping = field_mapping_steps[0].get("config", {}).get("map", {})
                        print(f"✅ 字段映射已加载: {list(mapping.keys())}")
                    else:
                        print(f"❌ 没有找到字段映射步骤")
                    
                    return True
                else:
                    print(f"❌ 加载失败: {load_result.get('msg')}")
            except Exception as e:
                print(f"❌ 加载异常: {e}")
                import traceback
                traceback.print_exc()
        else:
            print(f"❌ 保存失败: {result.get('msg')}")
            
    except Exception as e:
        print(f"❌ 保存异常: {e}")
        import traceback
        traceback.print_exc()
    
    return False

if __name__ == "__main__":
    success = test_step_by_step()
    print("\n" + "=" * 60)
    if success:
        print("🎉 所有测试通过！")
    else:
        print("❌ 测试失败")
    print("=" * 60)
    sys.exit(0 if success else 1)
