import requests
import json

BASE_URL = "http://localhost:8000"

# 测试 detail_jump 步骤
test_cases = [
    {
        "name": "基础方案（不带 detail_jump）",
        "plan": {
            "plan_name": "基础测试",
            "steps": [
                {
                    "step_type": "page_access",
                    "title": "页面访问",
                    "config": {"url": "https://example.com"}
                },
                {
                    "step_type": "field_mapping",
                    "title": "字段映射",
                    "config": {"map": {"title": "items[0].title"}}
                }
            ]
        }
    },
    {
        "name": "带 detail_jump（字符串字段列表）",
        "plan": {
            "plan_name": "Detail Jump 测试",
            "steps": [
                {
                    "step_type": "page_access",
                    "title": "页面访问",
                    "config": {"url": "https://example.com"}
                },
                {
                    "step_type": "list_detect",
                    "title": "列表识别",
                    "config": {
                        "item_selector": ".item",
                        "link_selector": "a",
                        "top_n_count": 20
                    }
                },
                {
                    "step_type": "detail_jump",
                    "title": "详情跳转",
                    "config": {
                        "detail_fields": ["title", "content", "date"]
                    }
                },
                {
                    "step_type": "field_mapping",
                    "title": "字段映射",
                    "config": {"map": {"title": "items[0].title"}}
                }
            ]
        }
    },
    {
        "name": "带 detail_jump（字典字段列表）",
        "plan": {
            "plan_name": "Detail Jump 测试2",
            "steps": [
                {
                    "step_type": "page_access",
                    "title": "页面访问",
                    "config": {"url": "https://example.com"}
                },
                {
                    "step_type": "detail_jump",
                    "title": "详情跳转",
                    "config": {
                        "detail_fields": [
                            {"name": "title", "extractor": "css", "expression": "h1"},
                            {"name": "content", "extractor": "css", "expression": ".content"}
                        ]
                    }
                }
            ]
        }
    },
    {
        "name": "带 attachment_parse",
        "plan": {
            "plan_name": "附件解析测试",
            "steps": [
                {
                    "step_type": "page_access",
                    "title": "页面访问",
                    "config": {"url": "https://example.com"}
                },
                {
                    "step_type": "attachment_parse",
                    "title": "附件解析",
                    "config": {
                        "extract_pdf": True,
                        "extract_doc": True,
                        "extract_excel": True,
                        "link_selector": "a[href$='.pdf']"
                    }
                },
                {
                    "step_type": "field_mapping",
                    "title": "字段映射",
                    "config": {
                        "map": {
                            "标题": "attachments[0].text",
                            "来源": "=测试"
                        }
                    }
                }
            ]
        }
    }
]

for i, test_case in enumerate(test_cases):
    print(f"\n{'='*70}")
    print(f"测试 {i+1}: {test_case['name']}")
    print('='*70)
    
    try:
        response = requests.post(
            f"{BASE_URL}/api/admin/crawl/steps/save-plan",
            json=test_case["plan"],
            timeout=30
        )
        result = response.json()
        
        if result.get("code") == 0 and result.get("data"):
            plan_id = result["data"]["plan_id"]
            print(f"✅ 保存成功 plan_id={plan_id}")
            
            # 加载并验证
            load_resp = requests.get(
                f"{BASE_URL}/api/admin/crawl/steps/plan?plan_id={plan_id}",
                timeout=30
            )
            load_result = load_resp.json()
            
            if load_result.get("code") == 0 and load_result.get("data"):
                loaded = load_result["data"]
                print(f"   方案名称: {loaded.get('plan_name')}")
                print(f"   URL: {loaded.get('url')}")
                print(f"   步骤数: {len(loaded.get('steps', []))}")
                print(f"   ✅ 加载成功")
            else:
                print(f"   ❌ 加载失败: {load_result.get('msg')}")
        else:
            print(f"❌ 保存失败: {result.get('msg')}")
            print(f"   完整响应: {json.dumps(result, ensure_ascii=False)}")
            
    except Exception as e:
        print(f"❌ 异常: {e}")
        import traceback
        traceback.print_exc()

print(f"\n{'='*70}")
print("🎉 所有测试完成")
print('='*70)
