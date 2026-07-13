"""核心渲染引擎完整测试"""
import asyncio
import sys
sys.path.insert(0, "/app")

results = []
labels = []

# 1. SmartPageRenderer render_js=True
print("=" * 60)
print("1. SmartPageRenderer render_js=True")
print("=" * 60)
try:
    from core.spider_core.page_renderer import SmartPageRenderer
    renderer = SmartPageRenderer()
    page = renderer.render("https://www.example.com", render_js=True, timeout=30, robot_check=False, risk_check=False)
    html_len = len(getattr(page, "html", "") or "")
    print(f"  final_url: {getattr(page, 'final_url', '')}")
    print(f"  html length: {html_len}")
    print(f"  error: {getattr(page, 'error', None)}")
    if html_len > 100:
        print("  ✅ 通过")
        results.append(True)
    else:
        print("  ❌ 失败: HTML 长度不足")
        results.append(False)
except Exception as e:
    print(f"  ❌ 异常: {e}")
    results.append(False)
labels.append("SmartPageRenderer render_js=True")

# 2. SmartPageRenderer render_js=False (requests)
print("\n" + "=" * 60)
print("2. SmartPageRenderer render_js=False (requests)")
print("=" * 60)
try:
    page = renderer.render("https://www.example.com", render_js=False, timeout=30, robot_check=False, risk_check=False)
    html_len = len(getattr(page, "html", "") or "")
    print(f"  final_url: {getattr(page, 'final_url', '')}")
    print(f"  html length: {html_len}")
    print(f"  error: {getattr(page, 'error', None)}")
    if html_len > 100:
        print("  ✅ 通过")
        results.append(True)
    else:
        print("  ❌ 失败: HTML 长度不足")
        results.append(False)
except Exception as e:
    print(f"  ❌ 异常: {e}")
    results.append(False)
labels.append("SmartPageRenderer render_js=False")

# 3. SpiderSDK render=True (Playwright 动态渲染)
print("\n" + "=" * 60)
print("3. SpiderSDK render=True (Playwright 动态渲染)")
print("=" * 60)
try:
    from core.spider_core.sdk import SpiderSDK
    sdk = SpiderSDK()
    resp = sdk.get("https://www.example.com", render=True, timeout=30)
    html_len = len(getattr(resp, "html", "") or "")
    print(f"  status_code: {getattr(resp, 'status_code', 0)}")
    print(f"  html length: {html_len}")
    print(f"  error: {getattr(resp, 'error', None)}")
    if html_len > 100:
        print("  ✅ 通过")
        results.append(True)
    else:
        print("  ❌ 失败: HTML 长度不足")
        results.append(False)
except Exception as e:
    print(f"  ❌ 异常: {e}")
    results.append(False)
labels.append("SpiderSDK render=True")

# 4. SpiderSDK render=False (requests HTTP)
print("\n" + "=" * 60)
print("4. SpiderSDK render=False (requests HTTP)")
print("=" * 60)
try:
    resp = sdk.get("https://www.example.com", render=False, timeout=30)
    html_len = len(getattr(resp, "html", "") or "")
    print(f"  status_code: {getattr(resp, 'status_code', 0)}")
    print(f"  html length: {html_len}")
    print(f"  error: {getattr(resp, 'error', None)}")
    if html_len > 100:
        print("  ✅ 通过")
        results.append(True)
    else:
        print("  ❌ 失败: HTML 长度不足")
        results.append(False)
except Exception as e:
    print(f"  ❌ 异常: {e}")
    results.append(False)
labels.append("SpiderSDK render=False")

# 5. 模拟 asyncio 事件循环中调用 (模拟 FastAPI 路由)
print("\n" + "=" * 60)
print("5. 在 asyncio 事件循环中调用 (模拟 FastAPI)")
print("=" * 60)
async def test_in_event_loop():
    """模拟 FastAPI async def 路由中的行为"""
    # 使用 loop.run_in_executor 调用渲染
    loop = asyncio.get_event_loop()
    result = await loop.run_in_executor(
        None,
        lambda: renderer.render("https://www.example.com", render_js=True, timeout=30, robot_check=False, risk_check=False),
    )
    html_len = len(getattr(result, "html", "") or "")
    print(f"  final_url: {getattr(result, 'final_url', '')}")
    print(f"  html length: {html_len}")
    print(f"  error: {getattr(result, 'error', None)}")
    return html_len > 100

try:
    ok = asyncio.run(test_in_event_loop())
    if ok:
        print("  ✅ 通过 - asyncio 事件循环中调用正常")
        results.append(True)
    else:
        print("  ❌ 失败")
        results.append(False)
except Exception as e:
    print(f"  ❌ 异常: {e}")
    results.append(False)
labels.append("asyncio 事件循环调用")

# 6. Playwright 浏览器测试
print("\n" + "=" * 60)
print("6. Playwright Chromium 浏览器")
print("=" * 60)
try:
    from playwright.sync_api import sync_playwright
    p = sync_playwright().start()
    browser = p.chromium.launch(headless=True)
    page_obj = browser.new_page()
    page_obj.goto("https://www.example.com", timeout=30000)
    html_len = len(page_obj.content())
    browser.close()
    p.stop()
    print(f"  页面内容长度: {html_len}")
    if html_len > 100:
        print("  ✅ 通过")
        results.append(True)
    else:
        print("  ❌ 失败")
        results.append(False)
except Exception as e:
    print(f"  ❌ 异常: {e}")
    results.append(False)
labels.append("Playwright Chromium")

# 汇总
print("\n" + "=" * 60)
print(f"总结果: {sum(results)}/{len(results)} 通过")
print("=" * 60)
for i, (ok, label) in enumerate(zip(results, labels)):
    status = "✅" if ok else "❌"
    print(f"  {i+1}. {label}: {status}")
if all(results):
    print("\n🎉 全部通过！部署完成，核心渲染引擎工作正常。")
else:
    print("\n⚠️ 部分测试未通过。")
