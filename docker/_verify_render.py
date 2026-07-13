import sys
sys.path.insert(0, "/app")

url = "https://www.miit.gov.cn/jgsj/xgj/APPqhyhqyzxzzxd/tzgg/index.html"

print("=" * 60)
print("Test 1: Check requests library is available")
print("=" * 60)
try:
    import requests
    print("  requests:", requests.__version__)
except ImportError as e:
    print("  FAIL:", e)

print()
print("=" * 60)
print("Test 2: Check _requests_lib in SDK module")
print("=" * 60)
try:
    from core.spider_core import sdk
    print("  _requests_lib:", "available" if sdk._requests_lib else "None")
except Exception as e:
    print("  FAIL:", e)

print()
print("=" * 60)
print("Test 3: Direct HTTP request via requests")
print("=" * 60)
try:
    import requests
    r = requests.get(url, headers={"User-Agent": "Mozilla/5.0"}, timeout=30, allow_redirects=True)
    print("  Status:", r.status_code)
    print("  Content length:", len(r.content), "bytes")
    print("  Text length:", len(r.text))
    print("  Text[:200]:", repr(r.text[:200]))
except Exception as e:
    print("  FAIL:", e)

print()
print("=" * 60)
print("Test 4: SmartPageRenderer.render (render_js=False)")
print("=" * 60)
try:
    from core.spider_core.page_renderer import SmartPageRenderer
    renderer = SmartPageRenderer()
    page = renderer.render(url, render_js=False, timeout=30, robot_check=False, risk_check=False)
    print("  status_code:", page.status_code)
    print("  error:", page.error)
    print("  final_url:", page.final_url)
    print("  html length:", len(page.html or ""))
    print("  title:", page.title)
    print("  links count:", len(page.links or []))
    if page.html:
        print("  html[:200]:", repr(page.html[:200]))
except Exception as e:
    print("  FAIL:", e)
    import traceback
    traceback.print_exc()

print()
print("=" * 60)
print("Test 5: Health check endpoint")
print("=" * 60)
try:
    import requests
    r = requests.get("http://localhost:8000/health", timeout=10)
    print("  Status:", r.status_code)
    print("  Response:", r.json() if r.status_code == 200 else r.text)
except Exception as e:
    print("  FAIL:", e)

print()
print("=" * 60)
print("All tests completed")
print("=" * 60)
