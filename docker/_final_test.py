"""模拟 Docker 容器环境的最小启动测试。"""
import os
import sys
import time
import warnings

warnings.filterwarnings("ignore")
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, PROJECT_ROOT)
os.chdir(PROJECT_ROOT)

# 模拟 .env 环境变量
for k, v in {
    "DB_BACKEND": "sqlite",
    "DB_SQLITE_PATH": "",
    "DB_ENCRYPTION_KEY": "please-change-this-to-a-strong-random-32-chars-!!",
    "QUEUE_REDIS_HOST": "127.0.0.1",
    "ENV": "dev",
    "DEBUG": "true",
    "LOG_LEVEL": "INFO",
}.items():
    os.environ[k] = v

output_lines = []
def log(msg):
    print(msg, flush=True)
    output_lines.append(msg)

log("=" * 50)
log("Stage 1: 基础模块导入")
log("=" * 50)

stage1 = [
    ("configs.settings", "from configs.settings import settings"),
    ("infra.logger_setup", "from infra.logger_setup import get_logger"),
    ("infra.db_base", "from infra.db_base import database, Base"),
]
for name, code in stage1:
    t0 = time.time()
    try:
        exec(code)
        log(f"  ✓ {name} ({time.time()-t0:.2f}s)")
    except Exception as e:
        log(f"  ✗ {name}: {type(e).__name__}: {e}")
        import traceback
        log(traceback.format_exc())
        sys.exit(1)

log("\n" + "=" * 50)
log("Stage 2: 数据库连接与建表")
log("=" * 50)

try:
    t0 = time.time()
    database.ensure_connected()
    log(f"  ✓ database.ensure_connected ({time.time()-t0:.2f}s)")
    log(f"    engine: {database.engine}")

    from sqlalchemy import inspect
    inspector = inspect(database.engine)
    tables = inspector.get_table_names()
    log(f"    tables: {tables}")
except Exception as e:
    log(f"  ✗ 数据库: {type(e).__name__}: {e}")
    import traceback
    log(traceback.format_exc())
    sys.exit(1)

log("\n" + "=" * 50)
log("Stage 3: FastAPI 应用导入")
log("=" * 50)

try:
    t0 = time.time()
    from adapter.main import app as fastapi_app
    log(f"  ✓ adapter.main:app ({time.time()-t0:.2f}s)")
    log(f"    title: {fastapi_app.title}")
    log(f"    routes: {len(fastapi_app.routes)}")
except Exception as e:
    log(f"  ✗ adapter.main: {type(e).__name__}: {e}")
    import traceback
    log(traceback.format_exc())
    sys.exit(1)

log("\n" + "=" * 50)
log("Stage 4: 测试健康检查端点")
log("=" * 50)

try:
    t0 = time.time()
    from fastapi.testclient import TestClient
    client = TestClient(fastapi_app)
    resp = client.get("/health")
    log(f"  ✓ GET /health ({time.time()-t0:.2f}s) status={resp.status_code}")
    log(f"    body: {resp.text[:200]}")
except Exception as e:
    log(f"  ✗ /health: {type(e).__name__}: {e}")
    import traceback
    log(traceback.format_exc())

log("\n" + "=" * 50)
log("Stage 5: 测试 API 文档")
log("=" * 50)

try:
    t0 = time.time()
    resp = client.get("/docs")
    log(f"  ✓ GET /docs ({time.time()-t0:.2f}s) status={resp.status_code}")
    resp = client.get("/openapi.json")
    log(f"  ✓ GET /openapi.json ({time.time()-t0:.2f}s) status={resp.status_code}")
except Exception as e:
    log(f"  ✗ /docs: {type(e).__name__}: {e}")
    import traceback
    log(traceback.format_exc())

log("\n🎉 所有核心功能测试通过！")
log("=" * 50)

with open("docker/_final_test.txt", "w", encoding="utf8") as f:
    f.write("\n".join(output_lines))
