"""测试详情页的附件"""
import requests, re

base = "http://localhost:8000"

# 访问详情页
detail_url = "https://www.miit.gov.cn/jgsj/xgj/APPqhyhqyzxzzxd/tzgg/art/2026/art_f693410aa105415a88d01b9018d4ba86.html"

print("=== Step 1: 加载详情页 ===")
r = requests.post(f"{base}/api/admin/crawl/steps/preview-render",
    json={"url": detail_url}, timeout=30)
data = r.json()
html = data["data"]["html_preview"]
print(f"HTML 长度: {len(html)}")

# 检查附件
print("\n=== Step 2: 检查附件相关内容 ===")
import re
from bs4 import BeautifulSoup

soup = BeautifulSoup(html, "html.parser")

# 查找所有 a 标签
for a in soup.find_all("a"):
    text = (a.get_text() or "").strip()
    href = a.get("href") or ""
    if any(k in href.lower() for k in ['.pdf', '.doc', 'attach']) or '附件' in text:
        print(f"  [{text[:60]}] -> {href[:120]}")

print("\n=== Step 3: 检查 src 中附件 ===")
for el in soup.find_all(attrs={"data-pdf-url": True}):
    print(f"  data-pdf-url: {el.get('data-pdf-url')}")

# 检查是否有 iframe/embed
print("\n=== Step 4: 检查 iframe/embed ===")
for el in soup.find_all(["iframe", "embed", "object"]):
    src_val = el.get('src') or ''
    print(f"  {el.name}: src={src_val[:120]}")

# 测试 attachment_parse
print("\n=== Step 5: 测试 attachment_parse 步骤 ===")
r2 = requests.post(f"{base}/api/admin/crawl/steps/step-test",
    json={"step_type": "attachment_parse",
          "config": {"link_selector": "a", "link_attribute": "href", "parse_pdf": True},
          "page_html": html},
    timeout=120)
data2 = r2.json()
print(f"code: {data2.get('code')}, msg: {data2.get('msg')}")
if data2.get("data") and data2["data"].get("output"):
    out = data2["data"]["output"]
    urls = out.get("attachment_urls", [])
    results = out.get("results", [])
    print(f"识别到 URL: {len(urls)} 个")
    for u in urls:
        print(f"  -> {u}")
    print(f"解析结果: {len(results)} 个")
    for r in results:
        print(f"  status={r.get('parse_status')}, err={r.get('error')}, text_len={len(r.get('text') or '')}")
        if r.get("text"):
            print(f"  text 前 200: {r['text'][:200]}")
