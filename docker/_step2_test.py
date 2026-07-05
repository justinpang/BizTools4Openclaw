import os
import sys
import time
import warnings

warnings.filterwarnings("ignore")
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, PROJECT_ROOT)
os.chdir(PROJECT_ROOT)

os.environ["DB_BACKEND"] = "sqlite"
os.environ["DB_SQLITE_PATH"] = ""
os.environ["DB_ENCRYPTION_KEY"] = "please-change-this-to-a-strong-random-32-chars-!!"
os.environ["QUEUE_REDIS_HOST"] = "127.0.0.1"
os.environ["ENV"] = "dev"
os.environ["DEBUG"] = "true"
os.environ["LOG_LEVEL"] = "INFO"

output_lines = []
def log(msg):
    print(msg, flush=True)
    output_lines.append(msg)

steps = [
    "configs.settings",
    "infra.logger_setup",
    "infra.db_base",
    "infra.db_models",
    "business.customer_send._orm",
    "business.data_clean._orm",
    "business.sales_task._orm",
]

for s in steps:
    t0 = time.time()
    log(f"[TRY] {s}")
    try:
        exec(f"import {s}")
        log(f"  OK ({time.time()-t0:.2f}s)")
    except Exception as e:
        log(f"  FAIL: {type(e).__name__}: {e}")
        import traceback
        log(traceback.format_exc())
        with open("docker/_step2.txt", "w", encoding="utf8") as f:
            f.write("\n".join(output_lines))
        sys.exit(1)

log("\n--- 测试数据库 ---")
from infra.db_base import database, Base
database.ensure_connected()
log(f"  engine: {database.engine}")

from sqlalchemy import inspect
inspector = inspect(database.engine)
log(f"  tables: {inspector.get_table_names()}")

log("\n🎉 完成")
with open("docker/_step2.txt", "w", encoding="utf8") as f:
    f.write("\n".join(output_lines))
