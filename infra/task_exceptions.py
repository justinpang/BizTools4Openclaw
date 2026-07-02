from __future__ import annotations

from infra.exceptions import BizException, ErrorCode


class TaskTimeoutError(BizException):
    """任务执行超时。"""

    def __init__(self, msg: str = "任务执行超时", *, data: dict | None = None) -> None:
        super().__init__(
            msg,
            code=ErrorCode.TASK_TIMEOUT,
            http_status=504,
            data=data,
            trigger_alert=True,
        )


class TaskRetryExceededError(BizException):
    """任务重试次数超过上限。"""

    def __init__(self, msg: str = "任务重试次数超过上限", *, data: dict | None = None) -> None:
        super().__init__(
            msg,
            code=ErrorCode.TASK_RETRY_EXCEEDED,
            http_status=500,
            data=data,
            trigger_alert=True,
        )


class TaskCancelledError(BizException):
    """任务被取消。"""

    def __init__(self, msg: str = "任务已被取消", *, data: dict | None = None) -> None:
        super().__init__(
            msg,
            code=ErrorCode.TASK_CANCELLED,
            http_status=409,
            data=data,
            trigger_alert=False,
        )


class TaskNotFoundError(BizException):
    """任务不存在。"""

    def __init__(self, msg: str = "任务不存在", *, data: dict | None = None) -> None:
        super().__init__(
            msg,
            code=ErrorCode.TASK_NOT_FOUND,
            http_status=404,
            data=data,
            trigger_alert=False,
        )


class RedisUnreachableError(BizException):
    """Redis 连接不可达。"""

    def __init__(self, msg: str = "Redis 连接不可达", *, data: dict | None = None) -> None:
        super().__init__(
            msg,
            code=ErrorCode.REDIS_UNREACHABLE,
            http_status=503,
            data=data,
            trigger_alert=True,
        )


__all__ = [
    "TaskTimeoutError",
    "TaskRetryExceededError",
    "TaskCancelledError",
    "TaskNotFoundError",
    "RedisUnreachableError",
]
