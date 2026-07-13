"""分析 miit.gov.cn 页面中的附件形式"""
import requests, re

base = "http://localhost:8000"

r = requests.post(f"{base}/api/admin/crawl/steps/preview-render",
    json={"url": "https://www.miit.gov.cn/jgsj/xgj/APPqhyhqyzxzzxd/tzgg/index.html"},
    timeout=30)
html = r.json()["data"]["html_preview"]

# 检查 1: 所有 href 中是否有 attachment 相关
print("=== 检查所有 href:")
hrefs = re.findall(r'href\s*=\s*["\']([^"\']+)["\']', html, re.IGNORECASE)
for h in hrefs:
    if 'attach' in h.lower() or 'pdf' in h.lower() or 'doc' in h.lower():
        print(f"  {h[:100]}")

# 检查 2: 检查是否有 src 标签指向 PDF
print("\n=== 检查 src:")
srcs = re.findall(r'src\s*=\s*["\']([^"\']+)["\']', html, re.IGNORECASE)
for s in srcs:
    if 'pdf' in s.lower() or 'attach' in s.lower() or 'doc' in s.lower():
        print(f"  {s[:100]}")

# 检查 3: PDF 附件占位符
print("\n=== 检查 PDF 占位符:")
for match in re.finditer(r'【PDF】|【DOC】|pdf-attachment|附件', html, re.IGNORECASE):
    start = max(0, match.start() - 50)
    end = min(len(html), match.end() + 100)
    print(f"  ...{html[start:end]}")

# 检查 4: 原始页面中的 <a 标签中有哪些是指向另一个包含附件页面的
print("\n=== 检查 a 标签中带有特定内容:")
from bs4 import BeautifulSoup
soup = BeautifulSoup(html, "html.parser")
for a in soup.find_all("a"):
    text = (a.get_text() or "").strip()
    href = a.get("href") or ""
    if 'pdf' in text.lower() or '附件' in text or 'pdf' in href.lower():
        print(f"  Text: {text[:60]}, href={href[:100]}")

# 检查 5: list_detect 能识别哪些链接
print("\n=== 检查 list item-like 内容链接:")
for li in soup.find_all("li"):
    text = li.get_text() or ""
    hrefs = li.find_all("a")
    if '通知' in text or '公告' in text or len(hrefs) > 0:
        for a in hrefs:
            h = a.get("href") or ""
            t = a.get_text() or ""
            print(f"  [{t[:50]}] -> {h[:100]}")
