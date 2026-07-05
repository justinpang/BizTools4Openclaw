import os, sys, time

ROOT = r"C:\projects\BizTools4Openclaw"
sys.path.insert(0, ROOT)
os.chdir(ROOT)

for k, v in {
    "DB_BACKEND": "sqlite", "DB_SQLITE_PATH": "",
    "DB_ENCRYPTION_KEY": "please-change-this-to-a-strong-random-32-chars-!!",
    "QUEUE_REDIS_HOST": "127.0.0.1", "ENV": "dev", "DEBUG": "true",
    "LOG_LEVEL": "INFO",
}.items():
    os.environ[k] = v

results = []
def log(msg):
    print(msg, flush=True)
    results.append(msg)

t_total = time.time()
steps = []

def step(name, fn):
    steps.append((name, fn))

step("settings", lambda: __import__("configs.settings", fromlist=["settings"]))
step("database.ensure_connected", lambda: __import__("infra.db_base").db_base.database.ensure_connected())
step("adapter.main", lambda: __import__("adapter.main", fromlist=["app"]))

for name, fn in steps:
    t0 = time.time()
    try:
        fn()
        log(f"[{time.time()-t0:.1f}s] OK {name}")
    except Exception as e:
        log(f"[{time.time()-t0:.1f}s] FAIL {name}: {type(e).__name__}: {e}")
        import traceback
        log(traceback.format_exc())
        break

# Test client
if 'adapter' in sys.modules:
    try:
        from adapter.main import app as _a
        from fastapi.testclient import TestClient
        client = TestClient(_a)
        
        endpoints = [
            ("/health", "GET"),
            ("/docs", "GET"),
            ("/v1/data-clean/run", "POST"),
            ("/v1/customer-send/run", "POST"),
            ("/v1/sales-task/runs", "GET"),
            ("/v1/sales-task/run", "POST"),
        ]
        
        for path, method in endpoints:
            t0 = time.time()
            try:
                if method == "GET":
                    r = client.get(path, params={"tenant_id": "test_tenant", "page_no": 1, "page_size": 10})
                else:
                    r = client.post(path, params={"tenant_id": "test_tenant", "task_id": f"t_{int(time.time())}", "dry_run": "true"})
                log(f"  [{time.time()-t0:.1f}s] {method} {path} -> {r.status_code}")
            except Exception as e:
                log(f"  [{time.time()-t0:.1f}s] {method} {path} ERROR: {type(e).__name__}: {e}")
    except Exception as e:
        log(f"client test error: {type(e).__name__}: {e}")
        import traceback
        log(traceback.format_exc())

log(f"\n=== 总耗时: {time.time()-t_total:.1f}s ===")

with open(os.path.join(ROOT, "docker", "_quick_result.txt"), "w", encoding="utf8") as f:
    f.write("\n".join(results))
