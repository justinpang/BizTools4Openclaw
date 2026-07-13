import sys
sys.path.insert(0, "/app")

url = "https://www.miit.gov.cn/jgsj/xgj/APPqhyhqyzxzzxd/tzgg/index.html"

print("Test 1: Direct requests...")
try:
    import requests
    r = requests.get(url, headers={"User-Agent": "Mozilla/5.0"}, timeout=30, allow_redirects=True)
    print("Status:", r.status_code, "len:", len(r.text))
except Exception as e:
    print("Error:", e)

print()
print("Test 2: SmartPageRenderer...")
try:
    from core.spider_core.page_renderer import SmartPageRenderer
    r = SmartPageRenderer()
    page = r.render(url, render_js=False, timeout=30, robot_check=False, risk_check=False)
    print("status_code:", page.status_code)
    print("error:", page.error)
    print("title:", page.title)
    html = page.html or ""
    print("html length:", len(html))
    if html:
        print("html[:300]:", repr(html[:300]))
    else:
        print("HTML IS EMPTY!")
except Exception as e:
    print("Error:", e)
    import traceback
    traceback.print_exc()

print()
print("Test 3: requests library check...")
try:
    from core.spider_core import sdk as spider_sdk
    print("_requests_lib:", spider_sdk._requests_lib)
except Exception as e:
    print("Error:", e)
