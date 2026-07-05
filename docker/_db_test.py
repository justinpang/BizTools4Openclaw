import os
import sys
import warnings

warnings.filterwarnings("ignore")
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, PROJECT_ROOT)
os.chdir(PROJECT_ROOT)

OUT = os.path.join(PROJECT_ROOT, "docker", "_db_test.txt")
with open(OUT, "w", encoding="utf-8") as f:
    def log(msg=""):
        print(msg, file=f, flush=True)

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

    log("[Step 1] 测试导入 configs.settings")
    try:
        from configs.settings import settings
        log(f"  ✓ OK - DB_BACKEND={settings.db.DB_BACKEND}, is_sqlite={settings.db.is_sqlite}")
    except Exception as e:
        log(f"  ✗ FAIL: {type(e).__name__}: {e}")
        import traceback
        log(traceback.format_exc())
        sys.exit(1)

    log("\n[Step 2] 测试导入 infra.db_base")
    try:
        from infra.db_base import database
        log(f"  ✓ OK")
    except Exception as e:
        log(f"  ✗ FAIL: {type(e).__name__}: {e}")
        import traceback
        log(traceback.format_exc())
        sys.exit(1)

    log("\n[Step 3] 调用 database.ensure_connected()")
    try:
        database.ensure_connected()
        log(f"  ✓ OK - engine={database.engine}")
    except Exception as e:
        log(f"  ✗ FAIL: {type(e).__name__}: {e}")
        import traceback
        log(traceback.format_exc())
        sys.exit(1)

    log("\n[Step 4] 测试 session 可用")
    try:
        sess = database.session()
        log(f"  ✓ session created: {sess}")
        try:
            from infra.db_models import SystemLog
            log(f"  ✓ ORM 可导入: SystemLog")

            # 先创建表（以防万一）
            from infra.db_base import Base
            try:
                Base.metadata.create_all(bind=database.engine)
                log(f"  ✓ 自动建表完成")
            except Exception as e2:
                log(f"  ⚠ create_all 警告: {e2}")

            rows = sess.query(SystemLog).limit(1).all()
            log(f"  ✓ system_logs 查询成功, {len(rows)} rows")
        except Exception as e2:
            log(f"  ✗ FAIL: {type(e2).__name__}: {e2}")
            import traceback
            log(traceback.format_exc())
        finally:
            sess.close()
    except Exception as e:
        log(f"  ✗ FAIL: {type(e).__name__}: {e}")
        import traceback
        log(traceback.format_exc())
        sys.exit(1)

    log("\n[Step 5] 测试 Redis")
    try:
        from infra.redis_client import get_redis
        r = get_redis()
        log(f"  Redis 客户端: {type(r).__name__}")
        r.set("test:docker", "ok")
        val = r.get("test:docker")
        r.delete("test:docker")
        assert val == b"ok"
        log(f"  ✓ set/get/delete 正常")
    except Exception as e:
        log(f"  ✗ FAIL: {type(e).__name__}: {e}")
        import traceback
        log(traceback.format_exc())
        sys.exit(1)

    log("\n" + "="*60)
    log("🎉 数据库 & Redis 测试全部通过")
    log("="*60)
    log("")
    log("应用在 Docker 容器内应该能正常运行。")
    log("")

print("测试完成，结果已写入 docker/_db_test.txt")
