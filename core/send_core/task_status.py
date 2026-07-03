from __future__ import annotations

import json
import os
import threading
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any

from infra.logger_setup import get_logger

logger = get_logger("send_core.task_status")


class SendStatus(Enum):
    PENDING = "PENDING"
    SENDING = "SENDING"
    SUCCESS = "SUCCESS"
    FAILED = "FAILED"
    CONTENT_BLOCKED = "CONTENT_BLOCKED"
    RATE_LIMITED = "RATE_LIMITED"
    BANNED = "BANNED"


_FINAL_STATUSES = {
    SendStatus.SUCCESS.value,
    SendStatus.FAILED.value,
    SendStatus.CONTENT_BLOCKED.value,
    SendStatus.BANNED.value,
}


@dataclass
class SendTaskStatus:
    task_id: str
    channel: str = "unknown"
    account_id: str | None = None
    status: str = SendStatus.PENDING.value
    attempts: int = 0
    last_message: str | None = None
    created_at: float = field(default_factory=time.time)
    updated_at: float = field(default_factory=time.time)
    extra: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "task_id": self.task_id,
            "channel": self.channel,
            "account_id": self.account_id,
            "status": self.status,
            "attempts": self.attempts,
            "last_message": self.last_message,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "extra": self.extra,
        }

    def is_final(self) -> bool:
        return self.status in _FINAL_STATUSES


class TaskStatusStore:
    """统一任务状态管理，Redis 持久化。"""

    _KEY_PREFIX = "send:task:"

    def __init__(
        self,
        *,
        ttl_seconds: int | None = None,
        redis_client: Any = None,
    ) -> None:
        self._ttl = int(
            ttl_seconds if ttl_seconds is not None else os.environ.get("SEND_STATUS_TTL", "86400")
        )
        self._redis = redis_client
        self._lock = threading.RLock()
        self._fallback: dict[str, str] = {}

    # ---------------- Redis 访问 ----------------

    def _redis_available(self) -> bool:
        if self._redis is not None:
            return True
        try:
            from infra.redis_client import redis_client as rc
            return rc.ping(fail_silently=True)
        except Exception:
            return False

    def _get_redis(self) -> Any:
        if self._redis is not None:
            class _Ctx:
                def __init__(self, r): self.r = r
                def __enter__(self): return self.r
                def __exit__(self, exc_type, exc, tb): return None
            return _Ctx(self._redis)
        from infra.redis_client import redis_client as rc
        return rc.acquire()

    # ---------------- 读写 API ----------------

    def set_status(
        self,
        task_id: str,
        status: SendStatus,
        *,
        channel: str = "unknown",
        account_id: str | None = None,
        message: str | None = None,
        increment_attempt: bool = False,
        extra: dict[str, Any] | None = None,
    ) -> SendTaskStatus:
        """写入状态。若 task 尚不存在则创建，否则更新。"""
        existing = self.get_status(task_id)
        now = time.time()
        if existing is None:
            st = SendTaskStatus(
                task_id=task_id,
                channel=channel,
                account_id=account_id,
                status=status.value,
                attempts=1 if increment_attempt else 0,
                last_message=message,
                created_at=now,
                updated_at=now,
                extra=dict(extra or {}),
            )
        else:
            existing.status = status.value
            existing.channel = channel
            existing.updated_at = now
            if account_id is not None:
                existing.account_id = account_id
            if message is not None:
                existing.last_message = message
            if increment_attempt:
                existing.attempts += 1
            if extra:
                existing.extra.update(extra)
            st = existing

        payload = json.dumps(st.to_dict(), ensure_ascii=False)
        try:
            if self._redis_available():
                with self._get_redis() as r:
                    key = f"{self._KEY_PREFIX}{task_id}"
                    r.set(key, payload, ex=self._ttl)
            else:
                with self._lock:
                    self._fallback[task_id] = payload
        except Exception as exc:
            logger.warning(f"set_status 失败，降级到进程内：{exc}")
            with self._lock:
                self._fallback[task_id] = payload
        return st

    def get_status(self, task_id: str) -> SendTaskStatus | None:
        key = f"{self._KEY_PREFIX}{task_id}"
        raw: str | None = None
        try:
            if self._redis_available():
                with self._get_redis() as r:
                    raw = r.get(key)
            if raw is None:
                with self._lock:
                    raw = self._fallback.get(task_id)
        except Exception as exc:
            logger.warning(f"get_status 失败：{exc}")
            with self._lock:
                raw = self._fallback.get(task_id)
        if raw is None:
            return None
        try:
            data = json.loads(raw) if isinstance(raw, str) else json.loads(raw.decode("utf-8"))
            return SendTaskStatus(
                task_id=str(data.get("task_id", task_id)),
                channel=str(data.get("channel", "unknown")),
                account_id=data.get("account_id"),
                status=str(data.get("status", SendStatus.PENDING.value)),
                attempts=int(data.get("attempts", 0)),
                last_message=data.get("last_message"),
                created_at=float(data.get("created_at", time.time())),
                updated_at=float(data.get("updated_at", time.time())),
                extra=dict(data.get("extra") or {}),
            )
        except Exception as exc:
            logger.warning(f"get_status JSON 解析失败：{exc}")
            return None

    # ---------------- 便捷包装 ----------------

    def mark_pending(self, task_id: str, **kwargs) -> SendTaskStatus:
        return self.set_status(task_id, SendStatus.PENDING, **kwargs)

    def mark_sending(self, task_id: str, **kwargs) -> SendTaskStatus:
        return self.set_status(task_id, SendStatus.SENDING, increment_attempt=True, **kwargs)

    def mark_success(self, task_id: str, **kwargs) -> SendTaskStatus:
        return self.set_status(task_id, SendStatus.SUCCESS, **kwargs)

    def mark_failed(self, task_id: str, message: str, **kwargs) -> SendTaskStatus:
        return self.set_status(task_id, SendStatus.FAILED, message=message, **kwargs)

    def mark_content_blocked(self, task_id: str, message: str, **kwargs) -> SendTaskStatus:
        return self.set_status(task_id, SendStatus.CONTENT_BLOCKED, message=message, **kwargs)

    def mark_rate_limited(self, task_id: str, message: str, **kwargs) -> SendTaskStatus:
        return self.set_status(task_id, SendStatus.RATE_LIMITED, message=message, **kwargs)

    def mark_banned(self, task_id: str, message: str, **kwargs) -> SendTaskStatus:
        return self.set_status(task_id, SendStatus.BANNED, message=message, **kwargs)


# ============================================================
# 模块级单例
# ============================================================


def _build_default() -> TaskStatusStore:
    return TaskStatusStore()


task_status_store: TaskStatusStore
try:
    task_status_store = _build_default()
except Exception as exc:
    logger.warning(f"TaskStatusStore 默认实例初始化失败：{exc}")
    task_status_store = TaskStatusStore()


__all__ = ["SendStatus", "SendTaskStatus", "TaskStatusStore", "task_status_store"]
