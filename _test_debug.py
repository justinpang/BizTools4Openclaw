import requests
import json

BASE_URL = "http://localhost:8000"

# 简单测试 - 不带权限时的行为
simple_plan = {
    "plan_name": "简单测试方案",
    "steps": [
        {
            "step_type": "page_access",
            "title": "页面访问",
            "config": {
                "url": "https://example.com"
            }
        },
        {
            "step_type": "field_mapping",
            "title": "字段映射",
            "config": {
                "map": {
                    "title": "items[0].title",
                    "content": "attachments[0].text"
                }
            }
        }
    ]
}

print("发送测试请求...")
print(f"请求体: {json.dumps(simple_plan, ensure_ascii=False)}")

try:
    response = requests.post(
        f"{BASE_URL}/api/admin/crawl/steps/save-plan",
        json=simple_plan,
        timeout=30
    )
    print(f"\nHTTP 状态: {response.status_code}")
    print(f"响应头: {dict(response.headers)}")
    
    result = response.json()
    print(f"\n响应内容: {json.dumps(result, ensure_ascii=False, indent=2)}")
    
    if result.get("code") == 0:
        plan_id = result["data"]["plan_id"]
        print(f"\n✅ 保存成功，plan_id={plan_id}")
        
        # 加载方案
        print(f"\n加载方案 plan_id={plan_id}...")
        load_response = requests.get(f"{BASE_URL}/api/admin/crawl/steps/plan?plan_id={plan_id}", timeout=30)
        load_result = load_response.json()
        
        print(f"加载响应: {json.dumps(load_result, ensure_ascii=False, indent=2)}")
        
        if load_result.get("code") == 0 and load_result.get("data"):
            data = load_result["data"]
            print(f"\n✅ 加载成功")
            print(f"方案名称: {data.get('plan_name')}")
            print(f"URL: {data.get('url')}")
            print(f"步骤数: {len(data.get('steps', []))}")
            for i, step in enumerate(data.get("steps", [])):
                print(f"\n  步骤 {i+1}:")
                print(f"    类型: {step.get('step_type')}")
                print(f"    标题: {step.get('title')}")
                print(f"    配置: {json.dumps(step.get('config', {}), ensure_ascii=False)}")
        else:
            print(f"\n❌ 加载失败: {load_result.get('msg')}")
    else:
        print(f"\n❌ 保存失败: {result.get('msg')}")
        
except Exception as e:
    print(f"\n❌ 异常: {e}")
    import traceback
    traceback.print_exc()
