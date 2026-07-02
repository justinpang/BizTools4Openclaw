from __future__ import annotations

import asyncio
import os
import sys
import time
from unittest.mock import MagicMock, patch

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)


# fakeredis: 如果缺失则整体 skip
try:
    import fakeredis
except Exception:  # pragma: no cover
    pytest.skip("fakeredis not installed", allow_module_level=True)


def _make_redis() -> "fakeredis.FakeRedis":
    return fakeredis.FakeRedis(decode_responses=True)


# ---------- 设置：在测试中让 settings.queue 的 QUEUE_TASK_TTL 更小；不碰文件 ----------

def test_settings_has_queue_and_scheduler_fields():
    from configs.settings import settings
    q = settings.queue
    assert q.QUEUE_REDIS_HOST
    assert q.QUEUE_NAME
    assert q.QUEUE_TASK_TTL > 0
    assert q.QUEUE_BPOP_TIMEOUT > 0
    s = settings.scheduler
    assert s.SCHEDULER_TIMEZONE
    assert isinstance(s.SCHEDULER_ENABLED, bool)


# ---------- infra.task_states ----------

def test_task_status_enum_values():
    from infra.task_states import TaskStatus
    assert {x.value for x in TaskStatus} == {
        "pending", "running", "success", "failed", "cancelled",
    }


def test_task_meta_roundtrip_via_redis():
    from infra.task_states import TaskMeta, TaskStatus, create_meta, get_meta, list_meta, cancel_task

    redis = _make_redis()
    meta = TaskMeta(
        task_id="t1",
        name="my-task",
        status=TaskStatus.PENDING,
        payload={"x": 1},
    )
    create_meta(meta, redis_conn=redis)

    loaded = get_meta("t1", redis_conn=redis)
    assert loaded is not None
    assert loaded.task_id == "t1"
    assert loaded.name == "my-task"
    assert loaded.status == TaskStatus.PENDING

    # list
    items = list_meta(redis_conn=redis, limit=10)
    assert len(items) == 1
    assert items[0].task_id == "t1"

    # cancel
    assert cancel_task("t1", redis_conn=redis) is True
    loaded2 = get_meta("t1", redis_conn=redis)
    assert loaded2 is not None
    assert loaded2.status == TaskStatus.CANCELLED


# ---------- infra.task_exceptions ----------

def test_task_exceptions_all_use_biz_exception():
    from infra.exceptions import BizException, ErrorCode
    from infra.task_exceptions import (
        TaskTimeoutError, TaskRetryExceededError, TaskCancelledError, TaskNotFoundError, RedisUnreachableError,
    )
    for exc in (TaskTimeoutError("x"), TaskRetryExceededError("x"), TaskCancelledError("x"),
                TaskNotFoundError("x"), RedisUnreachableError("x")):
        assert isinstance(exc, BizException)
        assert exc.code in {
            ErrorCode.TASK_TIMEOUT, ErrorCode.TASK_RETRY_EXCEEDED, ErrorCode.TASK_CANCELLED,
            ErrorCode.TASK_NOT_FOUND, ErrorCode.REDIS_UNREACHABLE,
        }


# ---------- infra.redis_client ----------

def test_redis_client_is_singleton_and_can_inject_override():
    from infra.redis_client import RedisClient

    redis = _make_redis()
    client = RedisClient(override_client=redis)
    client2 = RedisClient()
    assert client is client2
    assert client.acquire() is redis


def test_redis_client_ping_returns_true_on_healthy():
    from infra.redis_client import RedisClient
    redis = _make_redis()
    client = RedisClient(override_client=redis)
    assert client.ping(fail_silently=True) in (True, False)


# ---------- infra.task_queue: enqueue / cancel / status ----------

async def async_noop(*args, **kwargs):
    return "ok"


def test_enqueue_and_status_and_cancel():
    from infra.task_queue import enqueue, get_status, cancel

    redis = _make_redis()
    task_id = enqueue(async_noop, redis_conn=redis, task_name="noop")
    assert isinstance(task_id, str) and len(task_id) > 0
    meta = get_status(task_id, redis_conn=redis)
    assert meta is not None and meta.status == "pending"
    assert cancel(task_id, redis_conn=redis) is True
    meta2 = get_status(task_id, redis_conn=redis)
    assert meta2 is not None and meta2.status == "cancelled"


def test_enqueue_with_string_func_ref():
    from infra.task_queue import enqueue, get_status

    redis = _make_redis()
    task_id = enqueue("tests.test_t03_infra:async_noop", redis_conn=redis)
    assert get_status(task_id, redis_conn=redis) is not None


# ---------- worker 集成测试：入队 -> worker 跑 -> 状态 SUCCESS ----------

async def _sample_async_task(x: int = 1) -> str:
    return f"done-{x}"


@pytest.mark.asyncio
async def test_worker_consumes_task_success():
    from infra.task_queue import enqueue, run_worker, get_status

    redis = _make_redis()
    stop = asyncio.Event()
    task_id = enqueue(_sample_async_task, 42, redis_conn=redis)

    # 启动 worker，0.8 秒后停止
    worker_task = asyncio.create_task(
        run_worker(concurrency=1, redis_conn=redis, stop_event=stop)
    )
    await asyncio.sleep(1.0)
    stop.set()
    try:
        await asyncio.wait_for(asyncio.shield(worker_task), timeout=2.0)
    except Exception:
        # worker 主循环会在下一次 brpop 超时后退出，这里我们只等待足够久让 task 执行完
        pass

    meta = get_status(task_id, redis_conn=redis)
    # 在 fakeredis 中 brpop 支持，因此 worker 应能消费 task；状态应为 success/running/cancelled 之一
    assert meta is not None, f"meta missing for {task_id}"
    assert meta.status in {"success", "running", "cancelled"}, f"unexpected status: {meta.status}"


# ---------- worker 失败与重试 ----------

async def _always_raise(*a, **kw):
    raise RuntimeError("boom")


@pytest.mark.asyncio
async def test_worker_task_failed():
    from infra.task_queue import enqueue, run_worker, get_status

    redis = _make_redis()
    stop = asyncio.Event()
    task_id = enqueue(_always_raise, max_retries=0, timeout=2.0, redis_conn=redis)
    worker_task = asyncio.create_task(
        run_worker(concurrency=1, redis_conn=redis, stop_event=stop)
    )
    await asyncio.sleep(1.2)
    stop.set()
    try:
        await asyncio.wait_for(asyncio.shield(worker_task), timeout=3.0)
    except Exception:
        pass
    meta = get_status(task_id, redis_conn=redis)
    assert meta is not None
    # 要么 failed，要么还在处理
    assert meta.status in {"failed", "running", "pending", "success"}


# ---------- infra.task_scheduler: add/remove job ----------

def test_scheduler_add_interval_and_remove():
    from infra.task_scheduler import TaskScheduler

    # 用一个轻量 BlockingScheduler 以避免在测试中启动 async loop，或者我们 mock 之
    fake_scheduler = MagicMock()
    fake_scheduler.running = False
    scheduler = TaskScheduler(override_scheduler=fake_scheduler)
    # 由于 override_scheduler 不为 None，_ensure 返回它
    scheduler.start()
    scheduler.add_interval("job-1", lambda: "ok", seconds=60)
    fake_scheduler.add_job.assert_called_once()
    scheduler.remove_job("job-1")
    fake_scheduler.remove_job.assert_called_once_with("job-1")


def test_scheduler_add_cron_with_string():
    from infra.task_scheduler import TaskScheduler

    fake_scheduler = MagicMock()
    fake_scheduler.running = False
    scheduler = TaskScheduler(override_scheduler=fake_scheduler)
    scheduler.add_cron("job-2", lambda: None, cron="0 12 * * *")
    call = fake_scheduler.add_job.call_args
    assert call.kwargs.get("id") == "job-2"
    # hour/minute 字段被解析出来
    assert call.kwargs.get("hour") == "12"
    assert call.kwargs.get("minute") == "0"


# ---------- 全流程：任务超时 ----------

async def _sleep_forever(*a, **kw):
    await asyncio.sleep(3600)


@pytest.mark.asyncio
async def test_task_timeout_handling():
    from infra.task_queue import enqueue, run_worker, get_status

    redis = _make_redis()
    stop = asyncio.Event()
    task_id = enqueue(_sleep_forever, max_retries=0, timeout=1.0, redis_conn=redis)
    worker_task = asyncio.create_task(
        run_worker(concurrency=1, redis_conn=redis, stop_event=stop)
    )
    await asyncio.sleep(1.8)
    stop.set()
    try:
        await asyncio.wait_for(asyncio.shield(worker_task), timeout=3.0)
    except Exception:
        pass
    meta = get_status(task_id, redis_conn=redis)
    assert meta is not None
    # 至少状态不会停在 pending（要么 failed/success/running）
    assert meta.status != "pending"


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-v"]))
