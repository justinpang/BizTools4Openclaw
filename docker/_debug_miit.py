"""测试 miit.gov.cn 页面渲染 - 分析 PDF 不可见问题"""
import sys
sys.path.insert(0, "/app")

url = "https://www.miit.gov.cn/jgsj/xgj/APPqhyhqyzxzzxd/tzgg/art/2026/art_f693410aa105415a88d01b9018d4ba86.html"

print("=" * 80)
print("TEST 1: render_js=False (requests HTTP)")
print("=" * 80)
try:
    from core.spider_core.page_renderer import SmartPageRenderer
    renderer = SmartPageRenderer()
    page = renderer.render(url, render_js=False, timeout=60, robot_check=False, risk_check=False)
    print(f"status: {page.status_code}")
    print(f"final_url: {page.final_url}")
    print(f"html length: {len(page.html)}")
    print(f"error: {page.error}")
    print(f"links count: {len(page.links)}")
    print(f"interactive_elements count: {len(page.interactive_elements)}")
    print(f"images count: {len(page.images)}")
    print(f"\n--- Links (前 20 个):")
    for i, link in enumerate(page.links[:20]):
        href = link.href[:80] if link.href else ""
        text = (link.text or "").strip()[:50]
        print(f"  [{i}] text='{text}'  href='{href}'")
    print(f"\n--- Title: {page.title}")
    
    # 检查是否有 pdf 相关链接
    pdf_links = [l for l in page.links if '.pdf' in (l.href or '').lower()]
    print(f"\n--- PDF 链接数量: {len(pdf_links)}")
    for i, link in enumerate(pdf_links[:10]):
        print(f"  [{i}] text='{(link.text or '').strip()[:80]}' href='{link.href[:120]}'")
except Exception as e:
    print(f"Error: {e}")
    import traceback
    traceback.print_exc()

print("\n" + "=" * 80)
print("TEST 2: render_js=True (Playwright, domcontentloaded)")
print("=" * 80)
try:
    page = renderer.render(url, render_js=True, timeout=60, robot_check=False, risk_check=False)
    print(f"status: {page.status_code}")
    print(f"final_url: {page.final_url}")
    print(f"html length: {len(page.html)}")
    print(f"error: {page.error}")
    print(f"links count: {len(page.links)}")
    
    pdf_links = [l for l in page.links if '.pdf' in (l.href or '').lower()]
    print(f"\n--- PDF 链接数量: {len(pdf_links)}")
    for i, link in enumerate(pdf_links[:10]):
        print(f"  [{i}] text='{(link.text or '').strip()[:80]}' href='{link.href[:120]}'")
except Exception as e:
    print(f"Error: {e}")
    import traceback
    traceback.print_exc()

print("\n" + "=" * 80)
print("TEST 3: render_js=True + 额外滚动/等待 + HTML 预览")
print("=" * 80)
try:
    from playwright.sync_api import sync_playwright
    import time
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36")
        page = context.new_page()
        page.goto(url, wait_until="domcontentloaded", timeout=60000)
        time.sleep(3)  # 额外等待 JS 执行
        # 滚动触发懒加载
        page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
        time.sleep(2)
        html = page.content()
        print(f"html length: {len(html)}")
        
        # 查找 PDF 相关元素
        from bs4 import BeautifulSoup
        soup = BeautifulSoup(html, "html.parser")
        
        pdf_links = []
        for a in soup.find_all("a"):
            href = a.get("href", "")
            if ".pdf" in href.lower() or "PDF" in a.get_text() or "pdf" in a.get_text().lower() or "下载" in a.get_text() or "附件" in a.get_text():
                pdf_links.append(a)
        
        print(f"\n--- PDF/下载 链接: {len(pdf_links)}")
        for i, a in enumerate(pdf_links[:15]):
            text = a.get_text(" ", strip=True)[:80]
            href = a.get("href", "")[:120]
            print(f"  [{i}] text='{text}'  href='{href}'")
        
        # 查找 iframe/embed/object
        iframes = soup.find_all(["iframe", "embed", "object"])
        print(f"\n--- iframe/embed/object: {len(iframes)}")
        for i, el in enumerate(iframes):
            print(f"  [{i}] <{el.name}> src/data='{(el.get('src') or el.get('data') or '')[:120]}'")
        
        # 页面标题
        title = soup.find("title")
        print(f"\n--- Title: {title.get_text() if title else 'N/A'}")
        
        # 打印前 2000 个字符的 HTML 预览（查看结构）
        print(f"\n--- HTML 预览 (前 3000 字符):")
        print(html[:3000])
        
        browser.close()
except Exception as e:
    print(f"Error: {e}")
    import traceback
    traceback.print_exc()

print("\n" + "=" * 80)
print("DONE")
print("=" * 80)
