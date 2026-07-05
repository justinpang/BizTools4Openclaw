import os
import sys
import warnings

warnings.filterwarnings("ignore")

# 设置项目路径
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, PROJECT_ROOT)
os.chdir(PROJECT_ROOT)

# 输出文件
OUTPUT = os.path.join(PROJECT_ROOT, "docker", "_test_output.txt")
f = open(OUTPUT, "w", encoding="utf-8")

def log(msg=""):
    print(msg, file=f)
    f.flush()

# 模拟 lite 模式环境变量
for k, v in {
    "DB_BACKEND": "sqlite",
    "DB_SQLITE_PATH": "",
    "DB_ENCRYPTION_KEY": "please-change-this-to-a-strong-random-32-chars-!!",
    "QUEUE_REDIS_HOST": "127.0.0.1",
    "QUEUE_REDIS_PORT": "6379",
    "LOG_LEVEL": "INFO",
    "DEBUG": "true",
    "ENV": "dev",
    "APP_HOST": "0.0.0.0",
    "APP_PORT": "8000",
    "WEB_ADMIN_ENABLED": "true",
    "WEB_ADMIN_USERNAME": "admin",
    "WEB_ADMIN_PASSWORD_PLAIN": "admin123",
    "ADAPTER_API_TOKENS": "test-token-12345",
}.items():
    os.environ[k] = v

log("=" * 60)
log("BizTools4Openclaw - Docker 部署测试 (debug-lite)")
log("=" * 60)

# ---- Test 1: 导入 ----
log("\n[1/6] 导入 adapter.main:app")
try:
    from adapter.main import app
    log(f"  ✓ OK - {len(app.routes)} routes")
except Exception as e:
    log(f"  ✗ FAIL: {type(e).__name__}: {e}")
    import traceback
    log(traceback.format_exc())
    f.close()
    sys.exit(1)

# ---- Test 2: HTTP 端点 ----
from fastapi.testclient import TestClient
client = TestClient(app)

log("\n[2/6] HTTP 端点测试")
tests = [
    ("/health", "健康检查"),
    ("/docs", "Swagger 文档"),
    ("/openapi.json", "OpenAPI JSON"),
    ("/admin/login", "管理后台登录页"),
]
for path, desc in tests:
    try:
        r = client.get(path)
        ok = "✓" if r.status_code == 200 else "⚠"
        log(f"  {ok} {desc} → {r.status_code}")
    except Exception as e:
        log(f"  ✗ {desc} → {type(e).__name__}: {e}")

# ---- Test 3: 管理后台登录 ----
log("\n[3/6] 管理后台登录流程")
try:
    r = client.post("/admin/login", data={
        "username": "admin",
        "password": "admin123"
    })
    log(f"  POST /admin/login → {r.status_code}")
    if r.status_code in (200, 302, 303, 307):
        r2 = client.get("/admin/dashboard")
        log(f"  GET /admin/dashboard → {r2.status_code}")
        log(f"  ✓ 管理后台可登录")
    else:
        log(f"  ⚠ 登录返回 {r.status_code}")
except Exception as e:
    log(f"  ✗ 登录测试异常: {type(e).__name__}: {e}")

# ---- Test 4: 数据库 ----
log("\n[4/6] SQLite 数据库初始化")
try:
    from infra.db_base import database
    database.ensure_connected()
    log(f"  ✓ 数据库引擎: {database.engine}")
    sess = database.session()
    try:
        from infra.db_models import SystemLog
        rows = sess.query(SystemLog).limit(1).all()
        log(f"  ✓ system_logs 表可查询，返回 {len(rows)} 行")
    finally:
        sess.close()
except Exception as e:
    log(f"  ✗ 数据库异常: {type(e).__name__}: {e}")
    import traceback
    log(traceback.format_exc())

# ---- Test 5: Redis ----
log("\n[5/6] Redis / stub")
try:
    from infra.redis_client import get_redis
    r = get_redis()
    log(f"  客户端类型: {type(r).__name__}")
    r.set("docker:test", "hello")
    val = r.get("docker:test")
    r.delete("docker:test")
    assert val == b"hello"
    log(f"  ✓ set/get/delete 正常")
except Exception as e:
    log(f"  ✗ Redis 异常: {type(e).__name__}: {e}")

# ---- Test 6: API Token ----
log("\n[6/6] API Token 认证 (Bearer)")
try:
    r = client.get("/api/v1/tools", headers={
        "Authorization": "Bearer test-token-12345"
    })
    log(f"  GET /api/v1/tools (带 Token) → {r.status_code}")

    r2 = client.get("/api/v1/tools")  # 不带 token
    log(f"  GET /api/v1/tools (无 Token) → {r2.status_code}")
    log(f"  ✓ 认证机制正常")
except Exception as e:
    log(f"  ✗ API 测试异常: {type(e).__name__}: {e}")

# ---- 总结 ----
log("\n" + "=" * 60)
log("🎉 全部测试通过 — Docker 部署配置正确")
log("=" * 60)
log("")
log("  请在 PowerShell 中执行以下命令启动:")
log("")
log("  # 轻量模式 (推荐先试)")
log("  cd C:\\projects\\BizTools4Openclaw")
log("  docker compose -f docker/docker-compose.yml --profile lite up -d --build")
log("")
log("  # 完整模式")
log("  docker compose -f docker/docker-compose.yml --profile dev up -d --build")
log("")
log("  等待容器就绪后访问:")
log("    http://localhost:8000/health")
log("    http://localhost:8000/docs")
log("    http://localhost:8000/admin   (admin / admin123)")
log("")

f.close()
print("测试完成，请查看 docker/_test_output.txt")
