import os, sys, time

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, PROJECT_ROOT)
os.chdir(PROJECT_ROOT)

os.environ["DB_BACKEND"] = "sqlite"
os.environ["DB_SQLITE_PATH"] = ""
os.environ["DB_ENCRYPTION_KEY"] = "test-key-1234567890"
os.environ["ENV"] = "dev"
os.environ["DEBUG"] = "true"
os.environ["LOG_LEVEL"] = "INFO"

results = []
def log(msg):
    print(msg, flush=True)
    results.append(msg)

t0 = time.time()
log("Step 1: 导入 adapter.main ...")
from adapter.main import app
log(f"  OK ({time.time()-t0:.2f}s) title={app.title}")

t0 = time.time()
log("Step 2: 初始化数据库 ...")
from infra.db_base import database
database.ensure_connected()
log(f"  OK ({time.time()-t0:.2f}s) engine={database.engine}")

log("Step 3: 列出所有路由 ...")
for r in app.routes:
    if hasattr(r, "path") and hasattr(r, "methods"):
        method = list(r.methods)[0] if r.methods else "ANY"
        log(f"  {method} {r.path}")

log("Step 4: TestClient 端点测试 ...")
from fastapi.testclient import TestClient
client = TestClient(app)

tests = [
    ("GET /health", lambda: client.get("/health")),
    ("GET /docs", lambda: client.get("/docs")),
    ("POST /v1/data-clean/run", lambda: client.post("/v1/data-clean/run", json={"tenant_id": "test", "raw_records": []})),
    ("POST /v1/customer-send/run", lambda: client.post("/v1/customer-send/run", json={"tenant_id": "test", "opportunities": []})),
    ("GET /v1/sales-task/runs", lambda: client.get("/v1/sales-task/runs")),
    ("POST /v1/sales-task/run (dry_run)", lambda: client.post("/v1/sales-task/run", json={"opportunities": [], "salespersons": [], "task_id": "t1", "dry_run": True})),
]

for name, fn in tests:
    t0 = time.time()
    try:
        r = fn()
        log(f"  {name} -> {r.status_code} ({time.time()-t0:.2f}s)")
    except Exception as e:
        log(f"  {name} -> ERROR: {type(e).__name__}: {e}")

log("\n🎉 所有核心功能测试完成！")

with open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "_final_check_result.txt"), "w", encoding="utf8") as f:
    f.write("\n".join(results))
