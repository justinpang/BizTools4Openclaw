from __future__ import annotations

import time
from dataclasses import dataclass, field, asdict
from enum import Enum
from typing import Any

from infra.logger_setup import get_logger

logger = get_logger("task_states")


class TaskStatus(str, Enum):
    """任务状态枚举。"""

    PENDING = "pending"
    RUNNING = "running"
    SUCCESS = "success"
    FAILED = "failed"
    CANCELLED = "cancelled"


@dataclass
class TaskMeta:
    """任务元数据（与存储解耦）。"""

    task_id: str
    name: str
    status: TaskStatus
    payload: dict = field(default_factory=dict)
    source: str = "queue"           # "queue" | "scheduler"
    retries: int = 0
    max_retries: int = 3
    created_at: float = field(default_factory=time.time)
    started_at: float | None = None
    finished_at: float | None = None
    error: str | None = None
    traceback: str | None = None

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["status"] = self.status.value
        return data

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "TaskMeta":
        status_raw = data.get("status", TaskStatus.PENDING.value)
        status = TaskStatus(status_raw) if isinstance(status_raw, str) else status_raw
        int_fields = ("retries", "max_retries")
        for key in int_fields:
            if key in data and data[key] is not None:
                try:
                    data[key] = int(data[key])
                except (TypeError, ValueError):
                    data[key] = 0
        float_fields = ("created_at", "started_at", "finished_at")
        for key in float_fields:
            if key in data and data[key] is not None:
                try:
                    data[key] = float(data[key])
                except (TypeError, ValueError):
                    data[key] = None
        return cls(
            task_id=str(data["task_id"]),
            name=str(data.get("name", "")),
            status=status,
            payload=data.get("payload") or {},
            source=str(data.get("source", "queue")),
            retries=int(data.get("retries", 0) or 0),
            max_retries=int(data.get("max_retries", 3) or 3),
            created_at=float(data.get("created_at", time.time())),
            started_at=data.get("started_at"),
            finished_at=data.get("finished_at"),
            error=data.get("error"),
            traceback=data.get("traceback"),
        )


# =============== Redis 存储键 ===============

def _key_prefix(source: str = "queue") -> str:
    # 延迟导入以避免循环依赖
    from configs.settings import settings
    prefix = settings.queue.QUEUE_PREFIX or "openclaw:queue"
    return f"{prefix}:{source}"


def meta_key(task_id: str, *, source: str = "queue") -> str:
    return f"{_key_prefix(source)}:task:meta:{task_id}"


def payload_key(task_id: str, *, source: str = "queue") -> str:
    return f"{_key_prefix(source)}:task:payload:{task_id}"


def index_key(source: str = "queue") -> str:
    return f"{_key_prefix(source)}:task:index"


def ready_key(*, source: str = "queue") -> str:
    return f"{_key_prefix(source)}:ready"


# =============== 读写 API ===============

def create_meta(meta: TaskMeta, *, redis_conn: Any, ttl: int | None = None) -> None:
    """创建任务元数据。"""
    from configs.settings import settings
    key = meta_key(meta.task_id, source=meta.source)
    data = meta.to_dict()
    # Redis HASH 必须是扁平结构；payload 单独存 JSON 字符串
    hash_payload: dict[str, str] = {
        "task_id": str(data["task_id"]),
        "name": str(data["name"]),
        "status": str(data["status"]),
        "source": str(data["source"]),
        "retries": str(data["retries"]),
        "max_retries": str(data["max_retries"]),
        "created_at": str(data["created_at"]),
    }
    if data.get("started_at") is not None:
        hash_payload["started_at"] = str(data["started_at"])
    if data.get("finished_at") is not None:
        hash_payload["finished_at"] = str(data["finished_at"])
    if data.get("error") is not None:
        hash_payload["error"] = str(data["error"])
    if data.get("traceback") is not None:
        hash_payload["traceback"] = str(data["traceback"])

    expire = ttl if ttl is not None else int(settings.queue.QUEUE_TASK_TTL or 604800)
    pipe = redis_conn.pipeline()
    pipe.hset(key, mapping=hash_payload)
    pipe.zadd(index_key(meta.source), {meta.task_id: float(meta.created_at)})
    pipe.expire(key, expire)
    pipe.expire(index_key(meta.source), expire)
    pipe.execute()


def update_meta(
    task_id: str,
    *,
    source: str = "queue",
    redis_conn: Any,
    **fields: Any,
) -> None:
    key = meta_key(task_id, source=source)
    if not fields:
        return
    flat: dict[str, str] = {
        k: ("" if v is None else str(v)) for k, v in fields.items()
    }
    redis_conn.hset(key, mapping=flat)


def get_meta(task_id: str, *, source: str = "queue", redis_conn: Any) -> TaskMeta | None:
    key = meta_key(task_id, source=source)
    data = redis_conn.hgetall(key)
    if not data:
        return None
    # redis >=5 返回 bytes dict；统一转 str
    if isinstance(next(iter(data.values()), ""), bytes):
        data = {k.decode("utf-8"): v.decode("utf-8") for k, v in data.items()}
    try:
        return TaskMeta.from_dict(dict(data))
    except Exception as exc:
        logger.warning(f"parse task meta failed: {task_id} -> {exc}")
        return None


def list_meta(
    *,
    source: str = "queue",
    redis_conn: Any,
    since: float | None = None,
    limit: int = 100,
) -> list[TaskMeta]:
    key = index_key(source)
    if since is None:
        task_ids = redis_conn.zrevrange(key, 0, max(0, limit - 1))
    else:
        task_ids = redis_conn.zrangebyscore(key, float(since), "+inf", start=0, num=limit)
    result: list[TaskMeta] = []
    for task_id in task_ids:
        if isinstance(task_id, bytes):
            task_id = task_id.decode("utf-8")
        meta = get_meta(task_id, source=source, redis_conn=redis_conn)
        if meta is not None:
            result.append(meta)
    return result


def cancel_task(task_id: str, *, source: str = "queue", redis_conn: Any) -> bool:
    meta = get_meta(task_id, source=source, redis_conn=redis_conn)
    if meta is None:
        return False
    update_meta(
        task_id,
        source=source,
        redis_conn=redis_conn,
        status=TaskStatus.CANCELLED.value,
        finished_at=time.time(),
    )
    logger.info(f"task cancelled: {task_id}")
    return True


__all__ = [
    "TaskStatus",
    "TaskMeta",
    "create_meta",
    "update_meta",
    "get_meta",
    "list_meta",
    "cancel_task",
    "meta_key",
    "payload_key",
    "index_key",
    "ready_key",
]
