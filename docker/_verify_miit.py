"""验证 miit.gov.cn PDF 能被识别"""
import sys
sys.path.insert(0, "/app")

url = "https://www.miit.gov.cn/jgsj/xgj/APPqhyhqyzxzzxd/tzgg/art/2026/art_f693410aa105415a88d01b9018d4ba86.html"

print("=" * 80)
print("TEST 1: render_js=False (纯 HTML requests 模式)")
print("=" * 80)
try:
    from core.spider_core.page_renderer import SmartPageRenderer
    renderer = SmartPageRenderer()
    page = renderer.render(url, render_js=False, timeout=60, robot_check=False, risk_check=False)
    print(f"  status: {page.status_code}")
    print(f"  html length: {len(page.html)}")
    print(f"  links count: {len(page.links)}")
    print(f"  error: {page.error}")
    pdf_hits = [l for l in page.links if any(k in (l.href or '').lower() for k in ('.pdf', 'pdf', 'viewer', 'iframe')) or 'PDF' in (l.text or '').upper() or 'IFRAME' in (l.text or '').upper()]
    if pdf_hits:
        print(f"  ✅ 发现 {len(pdf_hits)} 个 PDF/嵌入文档链接:")
        for i, l in enumerate(pdf_hits):
            print(f"     [{i}] text='{l.text[:80]}' | href='{l.href[:100]}'")
    else:
        print(f"  ⚠️  未发现 PDF/嵌入文档（该模式只能获取静态 HTML）")
except Exception as e:
    print(f"  ❌ 失败: {e}")

print("\n" + "=" * 80)
print("TEST 2: render_js=True (Playwright 模式 + 滚动)")
print("=" * 80)
try:
    page = renderer.render(url, render_js=True, timeout=60, robot_check=False, risk_check=False)
    print(f"  status: {page.status_code}")
    print(f"  html length: {len(page.html)}")
    print(f"  links count: {len(page.links)}")
    print(f"  error: {page.error}")
    pdf_hits = [l for l in page.links if any(k in (l.href or '').lower() for k in ('.pdf', 'pdf', 'viewer', 'iframe')) or 'PDF' in (l.text or '').upper() or 'IFRAME' in (l.text or '').upper() or '附件' in (l.text or '') or '嵌入' in (l.text or '')]
    if pdf_hits:
        print(f"  ✅ 发现 {len(pdf_hits)} 个 PDF/嵌入文档链接:")
        for i, l in enumerate(pdf_hits):
            print(f"     [{i}] text='{l.text[:80]}' | href='{l.href[:100]}'")
    else:
        print(f"  ⚠️  未发现 PDF/嵌入文档")
except Exception as e:
    print(f"  ❌ 失败: {e}")
    import traceback
    traceback.print_exc()

print("\n" + "=" * 80)
print("TEST 3: 模拟 crawl_config API 的 clickable_elements 提取")
print("=" * 80)
try:
    # 使用修改后的逻辑
    links_typed = page.links
    clickable = []
    for link in links_typed[:100]:
        if hasattr(link, "text"):
            text = getattr(link, "text", "") or ""
            href = getattr(link, "href", "") or ""
            attrs = getattr(link, "attrs", {}) or {}
            clickable.append({
                "tag": "a",
                "text": text[:200],
                "href": href[:200],
            })
        elif isinstance(link, dict):
            clickable.append({
                "tag": link.get("tag", "a"),
                "text": (link.get("text") or "")[:200],
                "href": (link.get("href") or "")[:200],
            })
    
    # 过滤显示 PDF/附件相关的
    pdf_clickable = [c for c in clickable if any(k in (c.get("href") or "").lower() for k in (".pdf", "pdf", "viewer")) or "PDF" in (c.get("text") or "").upper() or "附件" in (c.get("text") or "") or "IFRAME" in (c.get("text") or "").upper()]
    print(f"  clickable total: {len(clickable)}")
    print(f"  pdf_clickable count: {len(pdf_clickable)}")
    if pdf_clickable:
        print(f"  ✅ PDF 可点击元素能被正确识别:")
        for i, c in enumerate(pdf_clickable):
            print(f"     [{i}] text='{c.get('text', '')[:80]}' | href='{c.get('href', '')[:100]}'")
    else:
        print(f"  ⚠️  clickable 中没有 PDF 元素")
except Exception as e:
    print(f"  ❌ 失败: {e}")
    import traceback
    traceback.print_exc()

print("\n" + "=" * 80)
print("TEST 4: 简单测试一个带 PDF 链接的 HTML")
print("=" * 80)
try:
    from core.spider_core.page_renderer import _parse_html, RenderedPage
    test_html = """<html><body>
      <a href="/files/report.pdf">下载 PDF 报告</a>
      <iframe src="/pdfjs/web/viewer.html?file=/files/embedded-doc.pdf"></iframe>
      <embed src="/doc.xls" type="application/xls" />
      <object data="/attachment.doc"></object>
    </body></html>"""
    test_page = RenderedPage(url="test")
    _parse_html(test_html, test_page)
    print(f"  links count: {len(test_page.links)}")
    pdf_found = [l for l in test_page.links if '.pdf' in (l.href or '').lower() or 'PDF' in (l.text or '').upper() or '附件' in (l.text or '') or '嵌入' in (l.text or '')]
    print(f"  ✅ PDF/嵌入链接: {len(pdf_found)}")
    for i, l in enumerate(test_page.links):
        print(f"     [{i}] text='{l.text[:80]}' | href='{l.href[:100]}'")
except Exception as e:
    print(f"  ❌ 失败: {e}")
    import traceback
    traceback.print_exc()

print("\n" + "=" * 80)
print("DONE")
print("=" * 80)
