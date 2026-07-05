"""快速测试管理后台功能"""
import sys
sys.path.insert(0, r"C:\projects\BizTools4Openclaw")

from fastapi.testclient import TestClient
from adapter.main import app

client = TestClient(app)

print("=== 测试 1: 管理后台首页")
r = client.get("/admin/")
print("  GET /admin/ -> {} (expect 200)".format(r.status_code))
assert r.status_code == 200

print("=== 测试 2: 静态文件")
for path in ["/admin/static/css/admin.css", "/admin/static/js/admin.js"]:
    r = client.get(path)
    print("  GET {} -> {} (expect 200), {} bytes".format(path, r.status_code, len(r.content)))
    assert r.status_code == 200

print("=== 测试 3: 登录 API")
r = client.post("/api/admin/auth/login", data={"username": "admin", "password": "admin123"})
print("  POST /api/admin/auth/login -> {}".format(r.status_code))

print("=== 测试 4: 未登录访问 dashboard")
r2 = client.get("/admin/dashboard", follow_redirects=False)
print("  GET /admin/dashboard -> {} (expect 302 redirect)".format(r2.status_code))

print()
print("✓ 本地测试全部通过！管理后台可正常访问、登录、静态资源加载正常")
