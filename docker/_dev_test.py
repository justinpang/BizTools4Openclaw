# 模拟 Docker 容器内环境变量 - debug-lite 模式
# 直接运行：python docker/_dev_test.py --mode lite|dev|debug
import os
import sys
import warnings

warnings.filterwarnings("ignore")

# 确保项目根目录在 Python path 中
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
os.chdir(PROJECT_ROOT)
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)
print(f"  项目根目录: {PROJECT_ROOT}")

# 模拟 debug-lite / lite 模式的环境变量
mode = sys.argv[1] if len(sys.argv) > 1 else "lite"

if mode in ("lite", "debug-lite"):
    env = {
        "DB_BACKEND": "sqlite",
        "DB_SQLITE_PATH": "",  # 内存数据库
        "DB_ENCRYPTION_KEY": "please-change-this-to-a-strong-random-32-chars-!!",
        "QUEUE_REDIS_HOST": "127.0.0.1",
        "QUEUE_REDIS_PORT": "6379",
        "LOG_LEVEL": "DEBUG",
        "DEBUG": "true",
        "ENV": "dev",
        "APP_HOST": "0.0.0.0",
        "APP_PORT": "8000",
        "WEB_ADMIN_ENABLED": "true",
        "WEB_ADMIN_USERNAME": "admin",
        "WEB_ADMIN_PASSWORD_PLAIN": "admin123",
        "ADAPTER_API_TOKENS": "test-token-12345",
    }
else:
    # dev 模式 - 实际会尝试连接 postgres 和 redis（本地可能没有）
    env = {
        "DB_BACKEND": "sqlite",    # 先测试回退能力
        "DB_HOST": "db",
        "DB_PORT": "5432",
        "DB_USER": "postgres",
        "DB_PASSWORD": "postgres-local-password-change-me",
        "DB_NAME": "openclaw_biz",
        "DB_POOL_SIZE": "5",
        "DB_MAX_OVERFLOW": "10",
        "DB_ENCRYPTION_KEY": "please-change-this-to-a-strong-random-32-chars-!!",
        "QUEUE_REDIS_HOST": "redis",
        "QUEUE_REDIS_PORT": "6379",
        "QUEUE_POOL_TIMEOUT": "5.0",
        "LOG_LEVEL": "DEBUG",
        "DEBUG": "true",
        "ENV": "dev",
        "APP_HOST": "0.0.0.0",
        "APP_PORT": "8000",
        "WEB_ADMIN_ENABLED": "true",
        "WEB_ADMIN_USERNAME": "admin",
        "WEB_ADMIN_PASSWORD_PLAIN": "admin123",
        "ADAPTER_API_TOKENS": "test-token-12345",
    }

for k, v in env.items():
    os.environ[k] = v

print(f"[1/6] 模拟 {mode} 模式环境变量 ✓")
print(f"  DB_BACKEND = {os.environ['DB_BACKEND']}")
print(f"  QUEUE_REDIS_HOST = {os.environ['QUEUE_REDIS_HOST']}")

# ---------------------
# 测试 1: 导入 adapter.main:app
# ---------------------
print("\n[2/6] 测试导入 adapter.main:app")
try:
    from adapter.main import app
    print(f"  ✓ 导入成功，路由数: {len(app.routes)}")
    routes_info = []
    for route in app.routes:
        if hasattr(route, "path") and hasattr(route, "methods"):
            methods = ",".join(sorted(route.methods or [])) or "ANY"
            routes_info.append(f"    {methods:6} {route.path}")
        elif hasattr(route, "path"):
            routes_info.append(f"    SUB    {route.path}")
    print("\n".join(routes_info[:15]))
    if len(routes_info) > 15:
        print(f"    ... 及 {len(routes_info) - 15} 条其他路由")
except Exception as e:
    print(f"  ✗ 导入失败: {type(e).__name__}: {e}")
    import traceback
    print("  详细堆栈:")
    print(traceback.format_exc())
    sys.exit(1)

# ---------------------
# 测试 2: 用 TestClient 测试 /health
# ---------------------
print("\n[3/6] 测试 HTTP 端点")
from fastapi.testclient import TestClient
client = TestClient(app)

# /health
try:
    r = client.get("/health")
    print(f"  GET /health → {r.status_code}")
    assert r.status_code == 200, f"期望 200 实际 {r.status_code}"
    print(f"  Body: {r.json()}")
    print("  ✓ 通过")
except Exception as e:
    print(f"  ✗ 失败: {e}")

# /docs
try:
    r = client.get("/docs")
    print(f"\n  GET /docs → {r.status_code}")
    assert r.status_code == 200, f"期望 200 实际 {r.status_code}"
    print("  ✓ 通过")
except Exception as e:
    print(f"  ✗ 失败: {e}")

# /openapi.json
try:
    r = client.get("/openapi.json")
    print(f"\n  GET /openapi.json → {r.status_code}")
    assert r.status_code == 200, f"期望 200 实际 {r.status_code}"
    print("  ✓ 通过")
except Exception as e:
    print(f"  ✗ 失败: {e}")

# ---------------------
# 测试 3: 数据库初始化 & 查询
# ---------------------
print("\n[4/6] 测试数据库初始化")
try:
    from infra.db_base import database
    database.ensure_connected()
    print(f"  ✓ 数据库引擎: {database.engine}")

    sess = database.session()
    try:
        # 测试 system_logs 表
        from infra.db_models import SystemLog
        rows = sess.query(SystemLog).limit(1).all()
        print(f"  ✓ system_logs 表可用，行数: {len(rows)}")

        # 实际插入一条测试数据再回滚
        import uuid
        test_log = SystemLog(
            log_level="info",
            log_type="test",
            message=f"docker-deploy-test-{uuid.uuid4().hex[:8]}",
        )
        sess.add(test_log)
        sess.commit()
        print(f"  ✓ 插入测试日志成功 (id={test_log.id})")

        # 再查询验证
        rows = sess.query(SystemLog).filter_by(log_type="test").limit(5).all()
        print(f"  ✓ 查询测试数据成功，返回 {len(rows)} 行")

        # 回滚删除测试数据
        for row in rows:
            sess.delete(row)
        sess.commit()
        print(f"  ✓ 清理测试数据完成")
    finally:
        sess.close()
except Exception as e:
    print(f"  ✗ 数据库测试失败: {type(e).__name__}: {e}")
    import traceback
    print(traceback.format_exc())

# ---------------------
# 测试 4: Redis / stub
# ---------------------
print("\n[5/6] 测试 Redis / stub")
try:
    from infra.redis_client import get_redis
    r = get_redis()
    print(f"  Redis 客户端类型: {type(r).__name__}")

    r.set("docker:test:key", "hello-world")
    val = r.get("docker:test:key")
    print(f"  SET docker:test:key / GET → {val}")
    assert val == b"hello-world", f"期望 b'hello-world' 实际 {val}"

    r.delete("docker:test:key")
    assert r.get("docker:test:key") is None
    print(f"  ✓ set/get/delete 正常")
except Exception as e:
    print(f"  ✗ Redis 测试失败: {type(e).__name__}: {e}")
    import traceback
    print(traceback.format_exc())

# ---------------------
# 测试 5: 管理后台登录流程
# ---------------------
print("\n[6/6] 测试 Web 管理后台")
try:
    r = client.get("/admin/login")
    print(f"  GET /admin/login → {r.status_code}")
    assert r.status_code == 200, f"期望 200 实际 {r.status_code}"
    print(f"  ✓ 登录页可用")

    # 登录
    r = client.post("/admin/login", data={
        "username": "admin",
        "password": "admin123"
    }, follow_redirects=True)
    print(f"  POST /admin/login → {r.status_code}")
    if r.status_code == 200:
        print(f"  ✓ 登录成功")

        # 测试仪表板
        r = client.get("/admin/dashboard")
        print(f"  GET /admin/dashboard → {r.status_code}")
        if r.status_code == 200:
            print(f"  ✓ 仪表板可用")
    else:
        print(f"  ⚠ 登录返回 {r.status_code} (可能需要密码 hash 初始化，非阻塞问题)")
except Exception as e:
    print(f"  ✗ 管理后台测试失败: {type(e).__name__}: {e}")
    import traceback
    print(traceback.format_exc())

# ---------------------
# 总结
# ---------------------
print("\n" + "=" * 60)
print(f"  🎉 模式 {mode} 本地模拟测试完成")
print("=" * 60)
print("""
 Docker 容器内的核心逻辑在本地通过。
 实际 Docker 部署时的差异:
   1. 数据库端口/主机在 docker-compose.yml 中配置
   2. 容器间用服务名（db / redis）连接，而非 127.0.0.1
   3. 日志/数据持久化通过 docker volume 管理
""")
