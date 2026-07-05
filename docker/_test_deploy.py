# Docker 部署测试脚本 - 模拟容器环境验证应用正常运行
import os
import sys
import warnings

# 确保项目根目录在 sys.path 中
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)
os.chdir(PROJECT_ROOT)

warnings.filterwarnings("ignore")

# --- 模拟容器内环境变量（与 docker-compose.yml 中的一致） ---
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

passed = 0
failed = 0

def test(name, func):
    global passed, failed
    try:
        func()
        print(f"  ✓ {name}")
        passed += 1
    except AssertionError as e:
        print(f"  ✗ {name}: {e}")
        failed += 1
    except Exception as e:
        print(f"  ✗ {name}: {type(e).__name__}: {e}")
        failed += 1

# ============================================================
print("=" * 60)
print(" BizTools4Openclaw - Docker 部署测试")
print("=" * 60)

print("\n[1/6] 模块导入测试")
def t_import():
    from adapter.main import app
    assert app is not None, "app is None"
    assert len(app.routes) > 0, "no routes registered"
    print(f"    已注册路由: {len(app.routes)} 条")
test("adapter.main:app 可导入", t_import)

from adapter.main import app
from fastapi.testclient import TestClient
client = TestClient(app)

print("\n[2/6] 健康检查端点")
def t_health():
    r = client.get("/health")
    assert r.status_code == 200, f"期望 200，实际 {r.status_code}"
    data = r.json()
    assert data.get("status") == "OK", f"status 不是 OK: {data}"
    print(f"    返回: {data}")
test("/health 返回 200", t_health)

print("\n[3/6] Swagger API 文档")
def t_docs():
    r = client.get("/docs")
    assert r.status_code == 200, f"期望 200，实际 {r.status_code}"
    assert "swagger" in r.text.lower() or "openapi" in r.text.lower(), "未找到 Swagger UI"
    print(f"    页面大小: {len(r.text)} bytes")
test("/docs Swagger UI 可访问", t_docs)

print("\n[4/6] 管理后台路由")
def t_admin_routes():
    # 登录页面
    r = client.get("/admin/login")
    assert r.status_code == 200, f"/admin/login: 期望 200，实际 {r.status_code}"
    print(f"    /admin/login = 200 (页面大小: {len(r.text)} bytes)")

    # 未登录访问 /admin 应该重定向或返回某种响应
    r2 = client.get("/admin", follow_redirects=True)
    assert r2.status_code == 200, f"/admin: 期望 200，实际 {r2.status_code}"
    print(f"    /admin = {r2.status_code} (自动重定向到登录页)")
test("/admin/login & /admin 可访问", t_admin_routes)

print("\n[5/6] 数据库连接测试（SQLite 自动建表）")
def t_db():
    from infra.db_base import database
    database.ensure_connected()
    sess = database.session()
    try:
        from infra.db_models import SystemLog
        rows = sess.query(SystemLog).limit(1).all()
        print(f"    SystemLog 表存在，行数: {len(rows)}")
    finally:
        sess.close()
test("SQLite 数据库连接 & 自动建表", t_db)

print("\n[6/6] Redis stub 降级（无 Redis 服务器时）")
def t_redis():
    from infra.redis_client import get_redis
    r = get_redis()
    # set/get
    r.set("docker:test", "hello")
    val = r.get("docker:test")
    assert val == b"hello", f"set/get 失败，期望 b'hello'，实际 {val}"
    # delete
    r.delete("docker:test")
    assert r.get("docker:test") is None, "delete 失败"
    print(f"    set/get/delete 正常")
    print(f"    Redis client 类型: {type(r).__name__}")
test("Redis stub 降级可用", t_redis)

# ============================================================
print("\n" + "=" * 60)
print(f" 测试结果: {passed}/{passed + failed} 通过，{failed} 失败")
print("=" * 60)

if failed == 0:
    print("\n🎉 所有测试通过！Docker 部署配置正常。")
    print("   请在 PowerShell 中执行:")
    print("     cd C:\\projects\\BizTools4Openclaw")
    print("     docker compose -f docker/docker-compose.yml down")
    print("     docker compose -f docker/docker-compose.yml --profile lite up -d --build")
    print("   然后访问:")
    print("     http://localhost:8000/health")
    print("     http://localhost:8000/docs")
    print("     http://localhost:8000/admin  (admin / admin123)")
    sys.exit(0)
else:
    print(f"\n⚠️  有 {failed} 项失败，请检查错误信息。")
    sys.exit(1)
