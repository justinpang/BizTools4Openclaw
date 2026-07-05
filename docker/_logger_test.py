import os
import sys
import time

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

output = []
def log(msg):
    print(msg, flush=True)
    output.append(msg)

log("[TRY] configs.settings")
t0 = time.time()
from configs.settings import settings
log(f"  OK ({time.time()-t0:.2f}s)")

log(f"  DB_BACKEND={settings.db.DB_BACKEND}")
log(f"  LOG_FILE_ENABLED={settings.log.LOG_FILE_ENABLED}")
log(f"  LOG_DIR={settings.log.LOG_DIR}")
log(f"  LOG_ROTATION={settings.log.LOG_ROTATION}")
log(f"  LOG_RETENTION={settings.log.LOG_RETENTION}")
log(f"  LOG_CONSOLE_ENABLED={settings.log.LOG_CONSOLE_ENABLED}")

log("[TRY] infra.logger_setup import")
t0 = time.time()
from infra.logger_setup import get_logger
log(f"  OK ({time.time()-t0:.2f}s)")

log("[TRY] get_logger()")
t0 = time.time()
logger = get_logger("test")
log(f"  OK ({time.time()-t0:.2f}s)")

log("[TRY] logger.info")
t0 = time.time()
logger.info("Hello test")
log(f"  OK ({time.time()-t0:.2f}s)")

log("\n🎉 Logger 测试通过")
with open("docker/_logger_test.txt", "w", encoding="utf8") as f:
    f.write("\n".join(output))
