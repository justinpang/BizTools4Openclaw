"""完整部署验证：健康检查 + Playwright 渲染 + HTTP 请求"""
import json
import sys
import urllib.request

sys.path.insert(0, "/app")

results = []

print("=" * 60)
print("验证 1: 应用健康检查 /health")
print("=" * 60)
try:
    resp = urllib.request.urlopen("http://127.0.0.1:8000/health", timeout=10)
    data = json.loads(resp.read().decode())
    print(f"  ✅ {json.dumps(data, ensure_ascii=False)}")
    results.append(True)
except Exception as e:
    print(f"  ❌ 失败: {e}")
    results.append(False)

print("\n" + "=" * 60)
print("验证 2: Playwright 渲染 (render_js=True) - SDK 层级")
print("=" * 60)
try:
    from core.spider_core.sdk import SpiderSDK
    sdk = SpiderSDK(base_url="https://www.example.com")
    resp = sdk.get("/", render=True, timeout=30)
    print(f"  status_code: {resp.status_code}")
    print(f"  html length: {len(resp.html or '')}")
    print(f"  error: {resp.error}")
    if resp.status_code == 200 and resp.html and len(resp.html) > 100:
        print(f"  ✅ Playwright 动态渲染成功！")
        results.append(True)
    else:
        print(f"  ⚠️  结果异常")
        results.append(False)
except Exception as e:
    print(f"  ❌ 失败: {e}")
    results.append(False)

print("\n" + "=" * 60)
print("验证 3: HTTP 请求 (render_js=False) - SDK 层级")
print("=" * 60)
try:
    resp = sdk.get("/", render=False, timeout=30)
    print(f"  status_code: {resp.status_code}")
    print(f"  html length: {len(resp.html or '')}")
    print(f"  error: {resp.error}")
    if resp.status_code == 200 and resp.html and len(resp.html) > 100:
        print(f"  ✅ HTTP 请求渲染成功！")
        results.append(True)
    else:
        print(f"  ⚠️  结果异常")
        results.append(False)
except Exception as e:
    print(f"  ❌ 失败: {e}")
    results.append(False)

print("\n" + "=" * 60)
print("验证 4: 页面渲染器 SmartPageRenderer (render_js=True)")
print("=" * 60)
try:
    from core.spider_core.page_renderer import SmartPageRenderer
    renderer = SmartPageRenderer()
    page = renderer.render("https://www.example.com", render_js=True, timeout=30, robot_check=False, risk_check=False)
    print(f"  final_url: {getattr(page, 'final_url', '')}")
    print(f"  html length: {len(getattr(page, 'html', '') or '')}")
    print(f"  links: {len(getattr(page, 'links', []) or [])}")
    print(f"  error: {getattr(page, 'error', None)}")
    if getattr(page, 'html', None) and len(getattr(page, 'html', '')) > 100:
        print(f"  ✅ SmartPageRenderer 渲染成功！")
        results.append(True)
    else:
        print(f"  ⚠️  结果异常")
        results.append(False)
except Exception as e:
    print(f"  ❌ 失败: {e}")
    results.append(False)

print("\n" + "=" * 60)
print("验证 5: Playwright Chromium 浏览器可启动")
print("=" * 60)
try:
    from playwright.sync_api import sync_playwright
    p = sync_playwright().start()
    browser = p.chromium.launch(headless=True)
    page = browser.new_page()
    page.goto("https://www.example.com", timeout=30000)
    content_len = len(page.content())
    browser.close()
    p.stop()
    print(f"  页面内容长度: {content_len}")
    if content_len > 100:
        print(f"  ✅ Playwright Chromium 浏览器运行正常！")
        results.append(True)
    else:
        print(f"  ⚠️  结果异常")
        results.append(False)
except Exception as e:
    print(f"  ❌ 失败: {e}")
    results.append(False)

print("\n" + "=" * 60)
print(f"验证结果汇总: {sum(results)}/{len(results)} 通过")
print("=" * 60)
labels = ["健康检查", "Playwright渲染", "HTTP请求", "SmartPageRenderer", "Chromium浏览器"]
for i, (ok, label) in enumerate(zip(results, labels)):
    status = "✅" if ok else "❌"
    print(f"  {i+1}. {label}: {status}")

if all(results):
    print("\n🎉 所有验证通过！部署成功。")
else:
    print("\n⚠️  部分验证失败，请检查日志。")
