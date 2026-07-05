import os
import sys
import warnings

warnings.filterwarnings("ignore")
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, PROJECT_ROOT)
os.chdir(PROJECT_ROOT)

# 设置环境
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

# 直接测试每个模块导入 - 有问题就报错退出
steps = [
    ("configs.settings", "from configs.settings import settings"),
    ("infra.db_base", "from infra.db_base import database, Base"),
    ("infra.db_models", "import infra.db_models"),
    ("business.customer_send._orm", "import business.customer_send._orm"),
    ("business.data_clean._orm", "import business.data_clean._orm"),
    ("business.sales_task._orm", "import business.sales_task._orm"),
]

for name, code in steps:
    print(f"[TRY] {name}", flush=True)
    try:
        exec(code)
        print(f"  ✓ OK", flush=True)
    except Exception as e:
        print(f"  ✗ FAIL: {type(e).__name__}: {e}", flush=True)
        import traceback
        traceback.print_exc()
        sys.exit(1)

# 测试数据库引擎
print("\n[TRY] database.ensure_connected()", flush=True)
try:
    from infra.db_base import database
    database.ensure_connected()
    print(f"  ✓ OK - engine={database.engine}", flush=True)
except Exception as e:
    print(f"  ✗ FAIL: {type(e).__name__}: {e}", flush=True)
    import traceback
    traceback.print_exc()
    sys.exit(1)

# 测试 create_all
print("\n[TRY] Base.metadata.create_all()", flush=True)
try:
    from infra.db_base import Base
    Base.metadata.create_all(bind=database.engine)
    print(f"  ✓ OK - 建表完成", flush=True)
except Exception as e:
    print(f"  ✗ FAIL: {type(e).__name__}: {e}", flush=True)
    import traceback
    traceback.print_exc()
    sys.exit(1)

# 测试 session & 查询
print("\n[TRY] session.query", flush=True)
try:
    sess = database.session()
    try:
        from infra.db_models import SystemLog
        rows = sess.query(SystemLog).limit(1).all()
        print(f"  ✓ OK - 查询到 {len(rows)} 行", flush=True)
    finally:
        sess.close()
except Exception as e:
    print(f"  ✗ FAIL: {type(e).__name__}: {e}", flush=True)
    import traceback
    traceback.print_exc()
    sys.exit(1)

print("\n🎉 数据库模块测试全部通过")
