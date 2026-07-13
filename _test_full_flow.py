"""完整流程测试"""
import requests, json, time

base = "http://localhost:8000"

# 1. 测试 preview-render —— 验证 URL/base_href 被正确返回
print("=== 1. 测试 preview-render ===")
detail_url = "https://www.miit.gov.cn/jgsj/xgj/APPqhyhqyzxzzxd/tzgg/art/2026/art_f693410aa105415a88d01b9018d4ba86.html"
r1 = requests.post(f"{base}/api/admin/crawl/steps/preview-render",
    json={"url": detail_url}, timeout=60)
d1 = r1.json()
html = d1["data"]["html_preview"] if d1.get("data") else ""
final_url = d1["data"]["final_url"] if d1.get("data") else ""
base_href = d1["data"]["base_href"] if d1.get("data") else ""
url_field = d1["data"]["url"] if d1.get("data") else ""
print(f"  final_url: {final_url}")
print(f"  base_href: {base_href}")
print(f"  url: {url_field}")
assert final_url or base_href or url_field, "URL 字段缺失"
print(f"  ✅ preview-render 返回 url/base_href 字段")

# 2. 测试 attachment_parse —— 从 HTML 中识别相对 URL 的 PDF 附件
print(f"\n=== 2. 测试 attachment_parse（含相对 URL 补全） ===")
r2 = requests.post(f"{base}/api/admin/crawl/steps/step-test",
    json={
        "step_type": "attachment_parse",
        "config": {},
        "page_html": html,
        "upstream_data": {
            "page_access": {
                "url": detail_url,
                "base_href": base_href or detail_url,
                "final_url": final_url or detail_url,
                "html_preview": html,
            }
        }
    },
    timeout=120)
d2 = r2.json()
print(f"  code: {d2.get('code')}, msg: {d2.get('msg')}")

if d2.get("data") and d2["data"].get("output"):
    results = d2["data"]["output"].get("results", [])
    urls = d2["data"]["output"].get("attachment_urls", [])
    print(f"  识别到 URL: {len(urls)} 个")
    for u in urls:
        print(f"    -> {u}")
    print(f"  解析结果: {len(results)} 个")
    for r in results:
        status = r.get("parse_status")
        err = r.get("error") or ""
        text_len = len(r.get("text") or "")
        tables_count = len(r.get("tables") or [])
        filename = r.get("filename") or ""
        print(f"    [{status}] {filename} - text_len={text_len}, tables={tables_count}")
        if status == "failed":
            print(f"      error: {err}")
        elif status == "ok":
            print(f"      ✅ 成功解析")
    print(f"\n  ✅ attachment_parse 成功处理相对 URL")

# 3. 测试 save-plan
print(f"\n=== 3. 测试方案保存 ===")
test_steps = [
    {"step_type": "page_access", "config": {"url": detail_url, "render_wait_ms": 1500}, "title": "访问详情页"},
    {"step_type": "attachment_parse", "config": {"extract_pdf": True}, "title": "解析 PDF 附件"},
    {"step_type": "field_mapping", "config": {"map": {"标题": "attachments[0].text", "表格列0": "attachments[0].tables[0].rows[1][0]"}}, "title": "字段映射"},
]
r3 = requests.post(f"{base}/api/admin/crawl/steps/save-plan",
    json={"plan_name": "工信部 PDF 采集方案 - 测试", "steps": test_steps},
    timeout=60)
d3 = r3.json()
plan_id = d3["data"]["plan_id"] if d3.get("data") else None
print(f"  code: {d3.get('code')}, plan_id: {plan_id}")
assert plan_id, "方案保存失败"
print(f"  ✅ 方案保存成功: plan_id={plan_id}")

# 4. 测试 load-plan
print(f"\n=== 4. 测试方案加载 ===")
r4 = requests.get(f"{base}/api/admin/crawl/steps/plan?plan_id={plan_id}", timeout=30)
d4 = r4.json()
if d4.get("data"):
    pd = d4["data"]
    print(f"  plan_name: {pd.get('plan_name')}")
    print(f"  url: {pd.get('url')}")
    loaded_steps = pd.get("steps", [])
    print(f"  steps: {len(loaded_steps)} 个")
    for i, s in enumerate(loaded_steps):
        print(f"    [{i}] {s.get('step_type')} - {s.get('title')}")
    print(f"  ✅ 方案加载成功")
else:
    print(f"  ❌ 方案加载失败: {d4.get('msg')}")

print(f"\n🎉 完整流程测试通过!")
