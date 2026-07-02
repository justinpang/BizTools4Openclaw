from __future__ import annotations

import asyncio
import inspect
import time
import traceback
from typing import Any, Callable

from infra.exceptions import ErrorCode, BizException
from infra.logger_setup import get_logger

logger = get_logger("task_scheduler")


class TaskScheduler:
    """APScheduler 封装（单例）。

    - 支持 cron / interval / date 三种触发
    - job 装饰器接入 T02 告警 & 任务状态存储
    - 与 asyncio 事件循环共存：使用 AsyncIOScheduler
    """

    _instance: "TaskScheduler | None" = None

    def __new__(cls, *args: Any, **kwargs: Any) -> "TaskScheduler":
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._initialized = False
        return cls._instance

    def __init__(self, *, override_scheduler: Any = None) -> None:
        if getattr(self, "_initialized", False):
            if override_scheduler is not None:
                self._scheduler = override_scheduler
            return
        self._initialized = True
        self._scheduler: Any = None
        self._lock: Any = None
        try:
            import threading
            self._lock = threading.Lock()
        except Exception:
            self._lock = None

    # ============= private =============

    def _build_scheduler(self) -> Any:
        """惰性构建 AsyncIOScheduler。"""
        from apscheduler.schedulers.asyncio import AsyncIOScheduler  # 延迟导入
        from apscheduler.jobstores.memory import MemoryJobStore
        from apscheduler.executors.pool import ThreadPoolExecutor

        from configs.settings import settings

        scheduler = AsyncIOScheduler(
            timezone=str(settings.scheduler.SCHEDULER_TIMEZONE or "Asia/Shanghai"),
        )
        if settings.scheduler.SCHEDULER_JOBSTORES_REDIS:
            try:
                from apscheduler.jobstores.redis import RedisJobStore  # type: ignore
                scheduler.add_jobstore(
                    RedisJobStore(
                        host=str(settings.queue.QUEUE_REDIS_HOST),
                        port=int(settings.queue.QUEUE_REDIS_PORT),
                        password=str(settings.queue.QUEUE_REDIS_PASSWORD) or None,
                        db=int(settings.queue.QUEUE_REDIS_DB),
                        jobs_key=f"{settings.scheduler.SCHEDULER_STORE_PREFIX}:jobs",
                        run_times_key=f"{settings.scheduler.SCHEDULER_STORE_PREFIX}:runtimes",
                    ),
                    alias="redis",
                )
            except Exception as exc:
                logger.warning(f"scheduler redis jobstore unavailable: {exc}")
                scheduler.add_jobstore(MemoryJobStore(), alias="default")
        else:
            scheduler.add_jobstore(MemoryJobStore(), alias="default")

        scheduler.add_executor(
            ThreadPoolExecutor(int(settings.scheduler.SCHEDULER_MAX_CONCURRENT or 10))
        )
        scheduler.configure(
            job_defaults={
                "coalesce": bool(settings.scheduler.SCHEDULER_COALESCE),
                "misfire_grace_time": int(settings.scheduler.SCHEDULER_MISFIRE_GRACE_TIME or 60),
                "max_instances": int(settings.scheduler.SCHEDULER_MAX_CONCURRENT or 10),
            }
        )
        return scheduler

    def _ensure(self) -> Any:
        if self._scheduler is not None:
            return self._scheduler
        if self._lock is not None:
            with self._lock:
                if self._scheduler is None:
                    self._scheduler = self._build_scheduler()
        else:
            self._scheduler = self._build_scheduler()
        return self._scheduler

    # ============= public =============

    def start(self) -> None:
        from configs.settings import settings
        if not settings.scheduler.SCHEDULER_ENABLED:
            logger.info("scheduler disabled by config")
            return
        scheduler = self._ensure()
        if not getattr(scheduler, "running", False):
            scheduler.start()
            logger.info("scheduler started")

    def stop(self, *, wait: bool = False) -> None:
        if self._scheduler is not None and getattr(self._scheduler, "running", False):
            self._scheduler.shutdown(wait=wait)
            logger.info("scheduler stopped")

    def add_cron(
        self,
        job_id: str,
        func: Callable[..., Any],
        *,
        cron: str | None = None,
        year: Any = None,
        month: Any = None,
        day: Any = None,
        week: Any = None,
        day_of_week: Any = None,
        hour: Any = None,
        minute: Any = None,
        second: Any = None,
        args: tuple[Any, ...] | None = None,
        kwargs: dict[str, Any] | None = None,
        **extra_kwargs: Any,
    ) -> str:
        """以 cron 表达式新增任务。"""
        self.start()
        scheduler = self._ensure()
        wrapped = _wrap_job(job_id, func)

        trigger_kwargs: dict[str, Any] = {
            k: v for k, v in {
                "year": year,
                "month": month,
                "day": day,
                "week": week,
                "day_of_week": day_of_week,
                "hour": hour,
                "minute": minute,
                "second": second,
            }.items() if v is not None
        }

        if cron and not trigger_kwargs:
            # 允许传入 "0 12 * * *" 这样的单字符串，拆成 6 个字段（无秒时补 0）
            parts = str(cron).split()
            if len(parts) == 5:
                minute, hour, day, month, dow = parts
                scheduler.add_job(
                    wrapped,
                    "cron",
                    id=job_id,
                    minute=minute,
                    hour=hour,
                    day=day,
                    month=month,
                    day_of_week=dow,
                    args=args,
                    kwargs=kwargs,
                    replace_existing=True,
                    **extra_kwargs,
                )
            else:
                raise ValueError(f"invalid cron: {cron}, expected 5 fields")
        else:
            scheduler.add_job(
                wrapped,
                "cron",
                id=job_id,
                args=args,
                kwargs=kwargs,
                replace_existing=True,
                **trigger_kwargs,
                **extra_kwargs,
            )
        logger.info(f"scheduler add_cron: {job_id}")
        return job_id

    def add_interval(
        self,
        job_id: str,
        func: Callable[..., Any],
        *,
        weeks: int = 0,
        days: int = 0,
        hours: int = 0,
        minutes: int = 0,
        seconds: int = 0,
        args: tuple[Any, ...] | None = None,
        kwargs: dict[str, Any] | None = None,
        **extra_kwargs: Any,
    ) -> str:
        self.start()
        scheduler = self._ensure()
        wrapped = _wrap_job(job_id, func)
        scheduler.add_job(
            wrapped,
            "interval",
            id=job_id,
            weeks=weeks,
            days=days,
            hours=hours,
            minutes=minutes,
            seconds=seconds,
            args=args,
            kwargs=kwargs,
            replace_existing=True,
            **extra_kwargs,
        )
        logger.info(f"scheduler add_interval: {job_id}")
        return job_id

    def add_date(
        self,
        job_id: str,
        func: Callable[..., Any],
        *,
        run_date: Any = None,
        args: tuple[Any, ...] | None = None,
        kwargs: dict[str, Any] | None = None,
        **extra_kwargs: Any,
    ) -> str:
        self.start()
        scheduler = self._ensure()
        wrapped = _wrap_job(job_id, func)
        scheduler.add_job(
            wrapped,
            "date",
            id=job_id,
            run_date=run_date,
            args=args,
            kwargs=kwargs,
            replace_existing=True,
            **extra_kwargs,
        )
        logger.info(f"scheduler add_date: {job_id}")
        return job_id

    def remove_job(self, job_id: str) -> bool:
        scheduler = self._ensure()
        try:
            scheduler.remove_job(job_id)
            logger.info(f"scheduler remove_job: {job_id}")
            return True
        except Exception:
            return False

    def get_job(self, job_id: str) -> Any | None:
        scheduler = self._ensure()
        try:
            return scheduler.get_job(job_id)
        except Exception:
            return None

    def list_jobs(self) -> list[Any]:
        scheduler = self._ensure()
        try:
            return list(scheduler.get_jobs())
        except Exception:
            return []

    @property
    def scheduler(self) -> Any:
        return self._ensure()


# =============== job wrapper ===============

def _wrap_job(job_id: str, func: Callable[..., Any]) -> Callable[..., Any]:
    """包装一个 job，使其接入 T02 告警与状态存储。"""
    from infra.alerting import alert_service
    from infra.redis_client import get_redis
    from infra.task_states import (
        TaskMeta,
        TaskStatus,
        create_meta,
        update_meta,
    )
    from configs.settings import settings

    async def _async_inner(*args: Any, **kwargs: Any) -> Any:
        redis = get_redis()
        meta = TaskMeta(
            task_id=job_id,
            name=job_id,
            status=TaskStatus.RUNNING,
            payload={"args": list(args), "kwargs": kwargs},
            source="scheduler",
            max_retries=int(settings.queue.QUEUE_MAX_RETRIES),
        )
        create_meta(meta, redis_conn=redis)
        try:
            result = func(*args, **kwargs)
            if asyncio.iscoroutine(result):
                result = await result
            update_meta(
                job_id,
                source="scheduler",
                redis_conn=redis,
                status=TaskStatus.SUCCESS.value,
                finished_at=time.time(),
            )
            logger.info(f"scheduler job ok: {job_id}")
            return result
        except Exception as exc:
            tb = traceback.format_exc()
            logger.error(f"scheduler job failed: {job_id} {exc}")
            update_meta(
                job_id,
                source="scheduler",
                redis_conn=redis,
                status=TaskStatus.FAILED.value,
                finished_at=time.time(),
                error=str(exc),
                traceback=tb,
            )
            try:
                asyncio.create_task(
                    alert_service.task_failure_async(
                        str(exc), extra_data={"traceback": tb[:2000], "job_id": job_id}
                    )
                )
            except Exception as alert_exc:
                logger.warning(f"scheduler alert failed: {alert_exc}")
            return None

    def _sync_inner(*args: Any, **kwargs: Any) -> Any:
        # 同步 job：用 run_until_complete 调用 async 版本
        try:
            loop = asyncio.get_event_loop()
        except Exception:
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
        if loop.is_running():
            return asyncio.create_task(_async_inner(*args, **kwargs))
        return loop.run_until_complete(_async_inner(*args, **kwargs))

    # 若 func 为异步，返回异步包装；否则返回同步包装
    if inspect.iscoroutinefunction(func):
        _async_inner.__name__ = f"async_wrap_{job_id}"
        return _async_inner
    _sync_inner.__name__ = f"sync_wrap_{job_id}"
    return _sync_inner


# =============== 模块级单例 ===============

scheduler = TaskScheduler()


def start_scheduler() -> None:
    scheduler.start()


def stop_scheduler(*, wait: bool = False) -> None:
    scheduler.stop(wait=wait)


__all__ = [
    "TaskScheduler",
    "scheduler",
    "start_scheduler",
    "stop_scheduler",
    "ErrorCode",
    "BizException",
]
