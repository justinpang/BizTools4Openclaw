import requests
import json
import sys

BASE_URL = "http://localhost:8000"

# 直接测试 StepAssembler.build_rule_config
import sys
sys.path.insert(0, ".")

from business.custom_spider.step_models import StepsPackage, StepConfig
from business.custom_spider.step_service import StepAssembler

# 模拟前端传递的 steps
test_steps = [
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

print("创建 StepsPackage...")
try:
    package = StepsPackage(plan_name="测试", steps=[])
    for i, s in enumerate(test_steps):
        step = StepConfig(
            step_id=s.get("step_id") or f"step_{i}",
            step_order=s.get("step_order") or (i + 1),
            step_type=s.get("step_type") or "",
            title=s.get("title") or s.get("step_type") or "",
            config=s.get("config") or {},
        )
        package.steps.append(step)
    print(f"  ✅ 成功创建 {len(package.steps)} 个步骤")
    
    print("\n调用 StepAssembler.build_rule_config...")
    rule_config = StepAssembler.build_rule_config(package, validate_ruleset=False)
    print(f"  ✅ 成功构建 rule_config，包含以下字段:")
    for key in rule_config.keys():
        value = rule_config[key]
        if isinstance(value, (list, dict)):
            print(f"    - {key}: {type(value).__name__} (len={len(value) if isinstance(value, (list, dict)) else 'N/A'})")
        else:
            print(f"    - {key}: {repr(value)[:50]}")
    
    # 保存编辑器原始 steps
    rule_config["_editor_steps"] = [
        {"step_type": s.step_type, "title": s.title, "config": s.config}
        for s in package.steps
    ]
    print(f"\n  ✅ 添加 _editor_steps 成功")
    
    # 提取 target_domain
    target_domain = ""
    for s in package.steps:
        for key in ("url", "url_template", "start_url", "base_url"):
            val = (s.config.get(key) or "").strip() if isinstance(s.config, dict) else ""
            if val and val.startswith(("http://", "https://")):
                from urllib.parse import urlparse
                parsed = urlparse(val)
                target_domain = parsed.netloc or val[:128]
                break
        if target_domain:
            break
    
    if not target_domain:
        target_domain = rule_config.get("target_domain") or "custom-domain"
    
    print(f"  ✅ 提取 target_domain: {target_domain}")
    
    # 测试 PlanService
    print("\n测试 PlanService.create_plan...")
    from business.custom_spider.service import PlanService
    svc = PlanService()
    result = svc.create_plan(
        plan_name="测试方案",
        target_domain=target_domain,
        spider_type="generic",
        rule_config=rule_config,
        description="调试测试",
        operator="system",
    )
    print(f"  ✅ PlanService.create_plan 结果: {result}")
    
    print("\n🎉 所有本地代码执行成功！")
    print("问题可能在 API 层的异常捕获或其他处理中。")
    
except Exception as e:
    print(f"  ❌ 异常: {e}")
    import traceback
    traceback.print_exc()
    print("\n详细检查:")
    import inspect
    print(f"异常类型: {type(e)}")
    print(f"异常文件: {getattr(e, '__traceback__', None)}")
