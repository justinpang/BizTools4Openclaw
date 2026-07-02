from __future__ import annotations

import asyncio
import importlib
import json
import time
import traceback
import uuid
from typing import Any, Awaitable, Callable

from infra.alerting import alert_service
from infra.logger_setup import get_logger
from infra.task_exceptions import (
    TaskCancelledError,
    TaskNotFoundError,
    TaskRetryExceededError,
    TaskTimeoutError,
)
from infra.task_states import (
    TaskMeta,
    TaskStatus,
    create_meta,
    get_meta,
    list_meta,
    payload_key,
    ready_key,
    update_meta,
)

logger = get_logger("task_queue")

TaskFn = Callable[..., Awaitable[Any]]


# =============== private 工具 ===============

def _func_to_ref(func: TaskFn | str) -> str:
    if isinstance(func, str):
        return func
    return f"{func.__module__}:{func.__qualname__}"


def _resolve_func(ref: str) -> TaskFn:
    if ":" not in ref:
        raise ValueError(f"invalid task ref: {ref}, expected module:qualname")
    module_name, qualname = ref.split(":", 1)
    module = importlib.import_module(module_name)
    obj = module
    for attr in qualname.split("."):
        obj = getattr(obj, attr)
    return obj  # type: ignore[return-value]


def _get_redis(redis_conn: Any = None) -> Any:
    """允许调用方注入 redis_conn（主要用于测试），否则使用全局单例。"""
    if redis_conn is not None:
        return redis_conn
    from infra.redis_client import get_redis
    return get_redis()


def _mark_running(task_id: str, *, source: str, redis_conn: Any) -> TaskMeta | None:
    meta = get_meta(task_id, source=source, redis_conn=redis_conn)
    if meta is None:
        return None
    if meta.status == TaskStatus.CANCELLED:
        return meta
    update_meta(
        task_id,
        source=source,
        redis_conn=redis_conn,
        status=TaskStatus.RUNNING.value,
        started_at=time.time(),
    )
    return get_meta(task_id, source=source, redis_conn=redis_conn)


def _mark_success(task_id: str, *, source: str, redis_conn: Any) -> None:
    update_meta(
        task_id,
        source=source,
        redis_conn=redis_conn,
        status=TaskStatus.SUCCESS.value,
        finished_at=time.time(),
    )


def _mark_failed(
    task_id: str,
    *,
    source: str,
    redis_conn: Any,
    error: str,
    tb: str | None = None,
) -> None:
    update_meta(
        task_id,
        source=source,
        redis_conn=redis_conn,
        status=TaskStatus.FAILED.value,
        finished_at=time.time(),
        error=error,
        traceback=tb or "",
    )


# =============== 入队 ===============

def enqueue(
    func: TaskFn | str,
    *args: Any,
    kwargs: dict[str, Any] | None = None,
    task_name: str | None = None,
    task_id: str | None = None,
    max_retries: int | None = None,
    timeout: float | None = None,
    redis_conn: Any = None,
    source: str = "queue",
) -> str:
    """将一个任务入队，返回生成的 task_id。

    - func 可以是函数对象，也可以是字符串 "module.path:func_name"
    - 所有可调项的默认值来自 settings.queue
    """
    from configs.settings import settings

    redis = _get_redis(redis_conn)
    task_id = task_id or uuid.uuid4().hex
    name = task_name or (func if isinstance(func, str) else getattr(func, "__name__", "task"))
    max_retries = int(max_retries if max_retries is not None else settings.queue.QUEUE_MAX_RETRIES)
    timeout = float(timeout if timeout is not None else settings.queue.QUEUE_TASK_TIMEOUT)

    payload_obj = {
        "func": _func_to_ref(func),
        "args": list(args),
        "kwargs": kwargs or {},
        "max_retries": max_retries,
        "timeout": timeout,
        "source": source,
    }
    # 尝试 JSON 化
    try:
        payload_str = json.dumps(payload_obj, ensure_ascii=False, default=str)
    except Exception as exc:
        raise ValueError(f"task payload 不可序列化: {exc}") from exc

    meta = TaskMeta(
        task_id=task_id,
        name=str(name),
        status=TaskStatus.PENDING,
        payload={"func": payload_obj["func"]},
        source=source,
        max_retries=max_retries,
    )
    create_meta(meta, redis_conn=redis)
    redis.set(payload_key(task_id, source=source), payload_str, ex=int(settings.queue.QUEUE_TASK_TTL))
    redis.lpush(ready_key(source=source), task_id)
    logger.info(f"task enqueued: {task_id} ({name})")
    return task_id


# =============== 查询 ===============

def get_status(task_id: str, *, redis_conn: Any = None, source: str = "queue") -> TaskMeta | None:
    return get_meta(task_id, source=source, redis_conn=_get_redis(redis_conn))


def list_tasks(
    *,
    redis_conn: Any = None,
    source: str = "queue",
    since: float | None = None,
    limit: int = 100,
) -> list[TaskMeta]:
    return list_meta(source=source, redis_conn=_get_redis(redis_conn), since=since, limit=limit)


def cancel(task_id: str, *, redis_conn: Any = None, source: str = "queue") -> bool:
    from infra.task_states import cancel_task as _inner_cancel
    return _inner_cancel(task_id, source=source, redis_conn=_get_redis(redis_conn))


# =============== 执行（worker 内部调用） ===============

async def _execute_task(
    task_id: str,
    payload: dict[str, Any],
    *,
    source: str,
    redis_conn: Any,
) -> bool:
    """执行一条任务，返回是否需要重新入队（指数退避后重试）。"""
    func_ref = payload.get("func")
    args = payload.get("args", [])
    kwargs = payload.get("kwargs", {})
    timeout = float(payload.get("timeout", 300))
    max_retries = int(payload.get("max_retries", 3))

    meta = _mark_running(task_id, source=source, redis_conn=redis_conn)
    if meta is None:
        logger.warning(f"task meta missing: {task_id}")
        return False
    if meta.status == TaskStatus.CANCELLED:
        logger.info(f"task cancelled, skip execute: {task_id}")
        return False

    try:
        func = _resolve_func(str(func_ref))
    except Exception as exc:
        tb = traceback.format_exc()
        _mark_failed(task_id, source=source, redis_conn=redis_conn, error=f"resolve_func failed: {exc}", tb=tb)
        logger.error(f"task resolve failed: {task_id} {exc}")
        _maybe_alert(task_id, exc, tb, source=source, redis_conn=redis_conn)
        return False

    try:
        coro = func(*args, **kwargs)
        result = await asyncio.wait_for(coro, timeout=timeout)
        _mark_success(task_id, source=source, redis_conn=redis_conn)
        logger.info(f"task succeeded: {task_id} -> {result!r}"[:200])
        return False
    except asyncio.TimeoutError as exc:
        wrapped = TaskTimeoutError(f"任务超时 {timeout}s", data={"task_id": task_id})
        tb = traceback.format_exc()
        logger.error(f"task timeout: {task_id} {exc}")
    except TaskCancelledError:
        _mark_failed(task_id, source=source, redis_conn=redis_conn, error="cancelled")
        return False
    except Exception as exc:
        tb = traceback.format_exc()
        logger.error(f"task failed: {task_id} {exc}")

    # 失败处理
    # 这里重新拉 meta 以保证重试数最新
    meta = get_meta(task_id, source=source, redis_conn=redis_conn)
    if meta is None:
        return False
    next_retries = int(meta.retries) + 1
    if next_retries <= max_retries:
        update_meta(
            task_id,
            source=source,
            redis_conn=redis_conn,
            status=TaskStatus.PENDING.value,
            retries=next_retries,
            error=str(exc) if "exc" in locals() else "task failed",
        )
        logger.info(f"task retry {next_retries}/{max_retries}: {task_id}")
        return True  # 需要重新入队（带指数退避）
    else:
        _mark_failed(
            task_id,
            source=source,
            redis_conn=redis_conn,
            error=getattr(exc, "message", str(exc)) if "exc" in locals() else "task failed",
            tb=tb if "tb" in locals() else None,
        )
        wrapped = TaskRetryExceededError(
            f"任务 {task_id} 重试超过上限 {max_retries}",
            data={"task_id": task_id, "name": meta.name},
        )
        _maybe_alert(task_id, wrapped, tb if "tb" in locals() else "", source=source, redis_conn=redis_conn)
        return False


def _maybe_alert(
    task_id: str,
    exc: Exception,
    tb: str,
    *,
    source: str,
    redis_conn: Any,
) -> None:
    """告警推送，同一 task_id 10 分钟内只推一次，避免告警风暴。"""
    try:
        key = f"_alert_debounce:{source}:{task_id}"
        now = int(time.time())
        if redis_conn.setnx(key, now):
            redis_conn.expire(key, 10 * 60)
            asyncio.create_task(
                alert_service.task_failure_async(str(exc), extra_data={"traceback": tb[:2000], "task_id": task_id})
            )
    except Exception as alert_exc:
        logger.warning(f"push alert failed: {alert_exc}")


# =============== worker 主循环 ===============

async def run_worker(
    *,
    concurrency: int | None = None,
    source: str = "queue",
    redis_conn: Any = None,
    stop_event: asyncio.Event | None = None,
) -> None:
    """启动 worker，协程并发消费队列。

    - concurrency 默认从 settings.queue.QUEUE_WORKER_CONCURRENCY
    - stop_event 可用于优雅关闭（测试中使用）
    """
    from configs.settings import settings

    redis = _get_redis(redis_conn)
    bpop_timeout = float(settings.queue.QUEUE_BPOP_TIMEOUT or 5.0)
    backoff_base = float(settings.queue.QUEUE_RETRY_BACKOFF or 2.0)
    concurrency = int(concurrency or settings.queue.QUEUE_WORKER_CONCURRENCY or 1)

    stop = stop_event or asyncio.Event()
    sem = asyncio.Semaphore(concurrency)
    logger.info(f"worker started (source={source}, concurrency={concurrency})")

    async def _process_one(tid: str) -> None:
        try:
            async with asyncio.timeout(bpop_timeout * 10 + 60):
                payload_raw = await asyncio.to_thread(redis.get, payload_key(tid, source=source))
                if not payload_raw:
                    logger.warning(f"payload missing for task {tid}")
                    return
                if isinstance(payload_raw, bytes):
                    payload_raw = payload_raw.decode("utf-8")
                payload = json.loads(payload_raw)

                # meta 中的 source 可能和队列不同，但我们用 source 参数
                meta = get_meta(tid, source=source, redis_conn=redis)
                if meta is None or meta.status == TaskStatus.CANCELLED:
                    logger.info(f"task cancelled/unknown, skip: {tid}")
                    return

                need_retry = await _execute_task(tid, payload, source=source, redis_conn=redis)
                if need_retry:
                    # 指数退避：简单做法是 sleep 后再 lpush
                    sleep_for = backoff_base ** int(meta.retries if meta else 0)
                    await asyncio.sleep(min(sleep_for, 30.0))
                    await asyncio.to_thread(redis.lpush, ready_key(source=source), tid)
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            tb = traceback.format_exc()
            logger.error(f"worker process error: {tid} {exc}")
            _maybe_alert(tid, exc, tb, source=source, redis_conn=redis)
        finally:
            sem.release()

    try:
        while not stop.is_set():
            try:
                await sem.acquire()
                result = await asyncio.to_thread(
                    redis.brpop,
                    ready_key(source=source),
                    int(bpop_timeout),
                )
            except Exception as exc:
                logger.warning(f"brpop error: {exc}")
                sem.release()
                await asyncio.sleep(1.0)
                continue

            if result is None:
                # 空队列，超时，下一轮
                sem.release()
                continue

            _, task_id_bytes = result
            task_id = task_id_bytes.decode("utf-8") if isinstance(task_id_bytes, bytes) else str(task_id_bytes)
            # 启动协程去跑 task
            asyncio.create_task(_process_one(task_id))
    except asyncio.CancelledError:
        logger.info("worker cancelled, stopping")
    finally:
        logger.info("worker stopped")


__all__ = [
    "TaskFn",
    "enqueue",
    "get_status",
    "list_tasks",
    "cancel",
    "run_worker",
]
