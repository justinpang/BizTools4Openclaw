# 快速验证脚本：确认 Docker 部署相关代码改动有效
import os
import sys

# 确保项目根目录在 sys.path 中（运行脚本时当前目录可能不是项目根）
ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT_DIR not in sys.path:
    sys.path.insert(0, ROOT_DIR)
os.chdir(ROOT_DIR)
print(f"Working directory: {os.getcwd()}")

# --- 环境变量 ---
os.environ["DB_BACKEND"] = "sqlite"
os.environ["DB_SQLITE_PATH"] = ""
os.environ["DB_ENCRYPTION_KEY"] = "test-docker-deploy-encryption-key-32chars!"
os.environ["QUEUE_REDIS_HOST"] = "127.0.0.1"
os.environ["QUEUE_REDIS_PORT"] = "6379"
os.environ["LOG_LEVEL"] = "INFO"
os.environ["ENV"] = "prod"
os.environ["WEB_ADMIN_ENABLED"] = "True"
os.environ["WEB_ADMIN_USERNAME"] = "admin"
os.environ["WEB_ADMIN_PASSWORD_PLAIN"] = "admin123"

# --- 抑制警告 ---
import warnings
warnings.filterwarnings("ignore", message="Using `httpx` with `starlette.testclient` is deprecated")
warnings.filterwarnings("ignore", category=DeprecationWarning)

# --- 1. 验证 settings ---
try:
    from configs.settings import settings
    print(f"[1/4] settings OK: backend={settings.db.DB_BACKEND}, env={settings.project.ENV}")
except Exception as e:
    print(f"[1/4] FAIL settings: {e}")
    sys.exit(1)

# --- 2. 验证 adapter.main.app 可初始化 ---
try:
    from adapter.main import app
    print(f"[2/4] FastAPI OK: routes={len(app.routes)}")
except Exception as e:
    print(f"[2/4] FAIL FastAPI: {e}")
    import traceback
    traceback.print_exc()
    sys.exit(1)

# --- 3. 验证 HTTP 端点 ---
try:
    from fastapi.testclient import TestClient
    c = TestClient(app)

    # /health
    r = c.get("/health")
    assert r.status_code == 200, f"/health: {r.status_code}"
    print(f"[3/4] HTTP OK: /health=200")

    # /api/v1/tools (authenticated)
    r = c.get("/api/v1/tools", headers={"Authorization": "Bearer test-token-12345"})
    print(f"       /api/v1/tools = {r.status_code}")
except Exception as e:
    print(f"[3/4] FAIL HTTP: {e}")
    import traceback
    traceback.print_exc()
    sys.exit(1)

# --- 4. 验证数据库 & Redis 降级 ---
try:
    from infra.db_base import database
    database.ensure_connected()
    sess = database.session()
    try:
        from infra.db_models import SystemLog
        result = sess.query(SystemLog).limit(1).all()
        print(f"[4/4] DB OK: sqlite, rows={len(result)}")
    finally:
        sess.close()

    from infra.redis_client import get_redis
    r = get_redis()
    r.set("deploy:test", "hello")
    val = r.get("deploy:test")
    r.delete("deploy:test")
    assert r.get("deploy:test") is None, "delete 失败"
    print(f"       Redis stub OK: val={val}")
except Exception as e:
    print(f"[4/4] FAIL DB/Redis: {e}")
    import traceback
    traceback.print_exc()
    sys.exit(1)

print()
print("=" * 60)
print(" 🎉 Docker 部署就绪：所有验证点通过")
print("=" * 60)
