"""销售任务 pipeline 逐组件测试，精确定位阻塞位置。"""
import os, sys, time

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, PROJECT_ROOT)
os.chdir(PROJECT_ROOT)

for k, v in {
    "DB_BACKEND": "sqlite", "DB_SQLITE_PATH": "",
    "DB_ENCRYPTION_KEY": "please-change-this-to-a-strong-random-32-chars-!!",
    "QUEUE_REDIS_HOST": "127.0.0.1", "ENV": "dev", "DEBUG": "true",
    "LOG_LEVEL": "INFO",
}.items():
    os.environ[k] = v

output_lines = []
def log(msg):
    print(msg, flush=True)
    output_lines.append(msg)

log("=" * 60)
log("Stage 1: 导入基础设施")
log("=" * 60)

t0 = time.time()
from configs.settings import settings
log(f"  ✓ settings ({time.time()-t0:.2f}s)")

t0 = time.time()
from infra.db_base import database
database.ensure_connected()
log(f"  ✓ database.ensure_connected ({time.time()-t0:.2f}s) engine={database.engine}")

log("\n" + "=" * 60)
log("Stage 2: 导入 sales_task 核心模块")
log("=" * 60)

for name in [
    "business.sales_task.models",
    "business.sales_task.storage",
    "business.sales_task.assignment_engine",
    "business.sales_task.reminder_engine",
    "business.sales_task.funnel_engine",
    "business.sales_task.push_notifier",
    "business.sales_task.pipeline",
    "business.sales_task.registry",
]:
    t0 = time.time()
    try:
        __import__(name)
        log(f"  ✓ {name} ({time.time()-t0:.2f}s)")
    except Exception as e:
        log(f"  ✗ {name}: {type(e).__name__}: {e}")
        import traceback
        log(traceback.format_exc())

log("\n" + "=" * 60)
log("Stage 3: 验证 registry 中必要的函数")
log("=" * 60)

from business.sales_task import registry
for fname in ["async_run", "run_batch", "assign", "remind", "get_funnel_stats", "transition", "add_tag", "remove_tag", "record_follow_up", "list_runs"]:
    has = hasattr(registry, fname) and callable(getattr(registry, fname))
    log(f"  {'✓' if has else '✗'} {fname}: {'present' if has else 'MISSING'}")

log("\n" + "=" * 60)
log("Stage 4: Pipeline 初始化 + dry_run 分步测试")
log("=" * 60)

from business.sales_task.pipeline import SalesTaskPipeline
from business.sales_task.models import Opportunity, OpportunityStatus, Salesperson

t0 = time.time()
pipeline = SalesTaskPipeline()
log(f"  ✓ pipeline init ({time.time()-t0:.2f}s)")

# 构造测试数据
ops = [
    Opportunity(
        opportunity_id=f"op_{i}",
        tenant_id="t1",
        customer_name=f"客户{i}",
        contact_email=f"user{i}@example.com",
        contact_phone=f"138000000{i:02d}",
        industry="软件",
        region="华东",
        need_keywords=["CRM", "数据"],
        score=80 + i,
        status=OpportunityStatus.NEW.value,
        assigned_sales_id="sp1",
    )
    for i in range(5)
]

sps = [
    Salesperson(
        sales_id=f"sp{i}",
        tenant_id="t1",
        name=f"销售{i}",
        industries=["软件"],
        regions=["华东"],
        min_score=50,
        weight=1.0,
        email=f"sales{i}@company.com",
        group="default",
    )
    for i in range(3)
]

# 分步测试
for step_name, step_fn in [
    ("run_assignment (dry_run)", lambda: pipeline.run_assignment(ops, sps, task_id="t1", dry_run=True)),
    ("run_reminder (dry_run)", lambda: pipeline.run_reminder(ops, sps, task_id="t1", dry_run=True)),
    ("run_funnel", lambda: pipeline.run_funnel("t1", task_id="t1", opportunity_count_hint=len(ops))),
]:
    t0 = time.time()
    try:
        result = step_fn()
        log(f"  ✓ {step_name} ({time.time()-t0:.2f}s)")
    except Exception as e:
        log(f"  ✗ {step_name}: {type(e).__name__}: {e}")
        import traceback
        log(traceback.format_exc())

log("\n" + "=" * 60)
log("Stage 5: 测试完整 run_batch (dry_run)")
log("=" * 60)

t0 = time.time()
try:
    result = pipeline.run_batch(ops, sps, task_id="t2", dry_run=True, enable_funnel=True)
    log(f"  ✓ run_batch dry_run ({time.time()-t0:.2f}s) keys={list(result.keys())}")
except Exception as e:
    log(f"  ✗ run_batch: {type(e).__name__}: {e}")
    import traceback
    log(traceback.format_exc())

log("\n" + "=" * 60)
log("Stage 6: 测试 async_run (dry_run=True)")
log("=" * 60)

t0 = time.time()
try:
    import asyncio
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    result = loop.run_until_complete(
        registry.async_run(task_id="t3", dry_run=True)
    )
    log(f"  ✓ async_run dry_run ({time.time()-t0:.2f}s) type={type(result).__name__}")
except Exception as e:
    log(f"  ✗ async_run: {type(e).__name__}: {e}")
    import traceback
    log(traceback.format_exc())
finally:
    loop.close() if 'loop' in dir() else None

log("\n🎉 销售任务 Pipeline 测试完成")
log("=" * 60)

with open("docker/_sales_pipeline_test.txt", "w", encoding="utf8") as f:
    f.write("\n".join(output_lines))
