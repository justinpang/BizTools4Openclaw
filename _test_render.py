import sys
sys.path.insert(0, ".")

url = "https://www.miit.gov.cn/jgsj/xgj/APPqhyhqyzxzzxd/tzgg/index.html"

print("Testing SmartPageRenderer...")
from core.spider_core.page_renderer import SmartPageRenderer
r = SmartPageRenderer()
page = r.render(url, render_js=False, timeout=30, robot_check=False, risk_check=False)
print("status_code:", page.status_code)
print("error:", page.error)
print("html length:", len(page.html or ""))
print("title:", page.title)
print("links:", len(page.links or []))
if page.html:
    print("html[:300]:", repr(page.html[:300]))
else:
    print("HTML is EMPTY!")
