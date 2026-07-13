import requests
import json

BASE_URL = "http://localhost:8000"

# 模拟登录 - 需要先获取登录 cookie
# 由于测试环境可能需要登录，我们先尝试不登录，看是否能成功

def test_plan_save_load():
    """测试方案保存和加载流程"""
    print("=" * 60)
    print("测试方案保存和加载流程")
    print("=" * 60)
    
    # 创建一个简单的方案
    test_plan = {
        "plan_name": "测试方案-URL和步骤检查",
        "steps": [
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
                "step_type": "detail_jump",
                "title": "详情跳转",
                "config": {
                    "detail_fields": ["title", "content", "publish_date"]
                }
            },
            {
                "step_type": "field_mapping",
                "title": "字段映射",
                "config": {
                    "map": {
                        "标题": "page_access.result.title",
                        "内容": "detail_jump.result.content",
                        "发布时间": "detail_jump.result.publish_date"
                    }
                }
            }
        ]
    }
    
    print("\n1. 保存方案...")
    save_url = f"{BASE_URL}/api/admin/crawl/steps/save-plan"
    try:
        response = requests.post(save_url, json=test_plan, timeout=30)
        result = response.json()
        print(f"   响应状态: {response.status_code}")
        print(f"   响应内容: {json.dumps(result, ensure_ascii=False, indent=2)[:500]}")
        
        if result.get("code") == 0 and result.get("data"):
            plan_id = result["data"].get("plan_id")
            print(f"   ✅ 保存成功，方案 ID: {plan_id}")
            
            # 加载方案
            print(f"\n2. 加载方案 (plan_id={plan_id})...")
            load_url = f"{BASE_URL}/api/admin/crawl/steps/plan?plan_id={plan_id}"
            load_response = requests.get(load_url, timeout=30)
            load_result = load_response.json()
            
            print(f"   响应状态: {load_response.status_code}")
            if load_result.get("code") == 0 and load_result.get("data"):
                loaded_plan = load_result["data"]
                print(f"   方案名称: {loaded_plan.get('plan_name')}")
                print(f"   方案 URL: {loaded_plan.get('url')}")
                print(f"   方案步骤数: {len(loaded_plan.get('steps', []))}")
                
                # 详细检查每个步骤
                print(f"\n3. 检查步骤内容...")
                for i, step in enumerate(loaded_plan.get("steps", [])):
                    print(f"   步骤 {i+1}: {step.get('step_type')} - {step.get('title')}")
                    print(f"      配置: {json.dumps(step.get('config', {}), ensure_ascii=False)[:200]}")
                
                # 检查 URL
                if loaded_plan.get("url"):
                    print(f"\n   ✅ URL 字段已填充: {loaded_plan['url']}")
                else:
                    print(f"\n   ❌ URL 字段为空")
                
                # 检查步骤数量
                if len(loaded_plan.get("steps", [])) == len(test_plan["steps"]):
                    print(f"   ✅ 步骤数量匹配: {len(loaded_plan['steps'])}")
                else:
                    print(f"   ❌ 步骤数量不匹配: 期望 {len(test_plan['steps'])}, 实际 {len(loaded_plan.get('steps', []))}")
                
                return True
            else:
                print(f"   ❌ 加载失败: {load_result.get('msg')}")
        else:
            print(f"   ❌ 保存失败: {result.get('msg')}")
            
    except Exception as e:
        print(f"   ❌ 测试异常: {e}")
        import traceback
        traceback.print_exc()
    
    return False

if __name__ == "__main__":
    test_plan_save_load()
