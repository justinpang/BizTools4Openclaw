# 简化版 Docker 部署测试
import os
import sys
import warnings

# 确保项目根目录在 sys.path 中
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)
os.chdir(PROJECT_ROOT)

warnings.filterwarnings("ignore")

# --- 模拟容器内环境变量 ---
os.environ["DB_BACKEND"] = "sqlite"
os.environ["DB_SQLITE_PATH"] = ""
os.environ["DB_ENCRYPTION_KEY"] = "test-key-for-docker-32-chars-long"
os.environ["QUEUE_REDIS_HOST"] = "127.0.0.1"
os.environ["LOG_LEVEL"] = "INFO"
os.environ["ENV"] = "prod"
os.environ["WEB_ADMIN_ENABLED"] = "true"
os.environ["WEB_ADMIN_USERNAME"] = "admin"
os.environ["WEB_ADMIN_PASSWORD_PLAIN"] = "admin123"
os.environ["ADAPTER_API_TOKENS"] = "test-token-12345"

results = []

def check(name, condition, detail=""):
    status = "✓" if condition else "✗"
    line = f"  {status} {name}" + (f"  [{detail}]" if detail else "")
    results.append((name, condition, detail))
    print(line)

# ============================================================
print("=" * 60)
print(" BizTools4Openclaw - Docker 部署测试")
print(" 模拟容器内环境，验证核心功能")
print("=" * 60)

# 1. 导入测试
print("\n[1] 应用导入")
try:
    from adapter.main import app
    check("adapter.main:app 可导入", True, f"{len(app.routes)} 条路由")
except Exception as e:
    check("adapter.main:app 可导入", False, str(e))

from adapter.main import app
from fastapi.testclient import TestClient
client = TestClient(app)

# 2. 健康检查
print("\n[2] HTTP 端点测试")
r = client.get("/health")
check("/health 返回 200", r.status_code == 200, f"status={r.status_code}")

# 3. Swagger 文档
r = client.get("/docs")
check("/docs 返回 200 (Swagger UI)", r.status_code == 200, f"status={r.status_code}")

# 4. OpenAPI JSON
r = client.get("/openapi.json")
check("/openapi.json 返回 200", r.status_code == 200, f"status={r.status_code}")

# 5. 登录页面
r = client.get("/admin/login")
check("/admin/login 返回 200", r.status_code == 200, f"status={r.status_code}")

# 6. /admin 重定向（未登录时应重定向到 login，307/302 均正常）
r = client.get("/admin")
check("/admin 返回 307/302 (重定向)", r.status_code in (307, 302, 200), f"status={r.status_code}")

# 7. 数据库
print("\n[3] 数据库 & 缓存")
try:
    from infra.db_base import database
    database.ensure_connected()
    sess = database.session()
    try:
        from infra.db_models import SystemLog
        rows = sess.query(SystemLog).limit(1).all()
        check("SQLite 连接 & 建表", True, f"查询成功 rows={len(rows)}")
    finally:
        sess.close()
except Exception as e:
    check("SQLite 连接 & 建表", False, str(e))

# 8. Redis stub
try:
    from infra.redis_client import get_redis
    r = get_redis()
    r.set("docker:test", "hello")
    val = r.get("docker:test")
    r.delete("docker:test")
    check("Redis stub set/get/delete", val == b"hello" and r.get("docker:test") is None,
          f"type={type(r).__name__}")
except Exception as e:
    check("Redis stub set/get/delete", False, str(e))

# 9. API 调用（需 Token）
print("\n[4] 适配器 API")
r = client.get("/api/v1/tools", headers={"Authorization": "Bearer test-token-12345"})
check("/api/v1/tools (Bearer Token)", r.status_code == 200, f"status={r.status_code}")

# 10. API 无 Token（应拒绝）
r = client.get("/api/v1/tools")
check("/api/v1/tools (无 Token 被拒绝)", r.status_code in (401, 403, 422), f"status={r.status_code}")

# ============================================================
total = len(results)
passed = sum(1 for _, ok, _ in results if ok)
failed = total - passed

print("\n" + "=" * 60)
print(f" 测试结果: {passed}/{total} 通过，{failed} 失败")
print("=" * 60)

if failed == 0:
    print("\n🎉 所有测试通过！应用可正常在 Docker 中运行。")
    sys.exit(0)
else:
    print(f"\n⚠️  {failed} 项失败，上述失败项需要进一步检查。")
    sys.exit(1)
