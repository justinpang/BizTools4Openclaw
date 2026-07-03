from __future__ import annotations

from enum import IntEnum
from typing import Any


class ErrorCode(IntEnum):
    """全局错误码表。

    编码规则：
      - 0 成功
      - 4xxxx → HTTP 4xx 客户端侧问题
      - 5xxxx → HTTP 5xx 服务端问题
      - 1xxxx → 业务层通用异常
      - 2xxxx → 基建告警场景专用
    """

    # ===== 成功 =====
    SUCCESS = 0

    # ===== HTTP 状态层（对齐 FastAPI） =====
    BAD_REQUEST = 40000
    UNAUTHORIZED = 40100
    FORBIDDEN = 40300
    NOT_FOUND = 40400
    METHOD_NOT_ALLOWED = 40500
    VALIDATION_ERROR = 42200
    TOO_MANY_REQUESTS = 42900

    # ===== 服务端 =====
    UNKNOWN_ERROR = 50000
    INTERNAL_ERROR = 50001
    SERVICE_UNAVAILABLE = 50300

    # ===== 业务层 =====
    BIZ_ERROR = 10000
    BIZ_WARNING = 10001
    BIZ_PARAM_ERROR = 10002
    BIZ_NOT_FOUND = 10003
    BIZ_CONFLICT = 10004
    DB_ERROR = 10005                 # 数据库异常
    DB_UNREACHABLE = 10006           # 数据库连接不可达
    QUEUE_ERROR = 10007              # 队列异常
    SCHEDULER_ERROR = 10008          # 调度异常
    SPIDER_ERROR = 10009             # 爬虫通用异常
    SPIDER_RISK = 10010              # 爬虫风控触发

    # ===== 基建告警场景 =====
    TASK_FAILURE = 20001
    SERVICE_EXCEPTION = 20002
    CRAWLER_RISK = 20003
    TASK_TIMEOUT = 20004
    TASK_RETRY_EXCEEDED = 20005
    TASK_CANCELLED = 20006
    TASK_NOT_FOUND = 20007
    REDIS_UNREACHABLE = 20008
    TASK_CONFLICT = 20009


class BizException(Exception):
    """业务异常基类。

    通过全局异常处理器捕获并转为统一 JSON 响应。
    `trigger_alert=True` 时，将触发 alert_service 发送告警。
    """

    def __init__(
        self,
        msg: str = "业务异常",
        *,
        code: int = ErrorCode.BIZ_ERROR,
        http_status: int = 400,
        data: Any | None = None,
        trigger_alert: bool = False,
    ) -> None:
        super().__init__(msg)
        self.msg = msg
        self.code = int(code)
        self.http_status = int(http_status)
        self.data = data
        self.trigger_alert = bool(trigger_alert)

    def __str__(self) -> str:
        return self.msg


class BizWarning(BizException):
    """业务警告级异常（不视为接口失败，http_status 默认 200）。"""

    def __init__(
        self,
        msg: str = "业务告警",
        *,
        code: int = ErrorCode.BIZ_WARNING,
        http_status: int = 200,
        data: Any | None = None,
        trigger_alert: bool = False,
    ) -> None:
        super().__init__(
            msg,
            code=code,
            http_status=http_status,
            data=data,
            trigger_alert=trigger_alert,
        )


# ---- 便捷 raise 函数 ----

def raise_biz_error(
    msg: str = "业务异常",
    *,
    code: int = ErrorCode.BIZ_ERROR,
    http_status: int = 400,
    data: Any | None = None,
    trigger_alert: bool = False,
) -> None:
    raise BizException(
        msg,
        code=code,
        http_status=http_status,
        data=data,
        trigger_alert=trigger_alert,
    )


def raise_task_failure(msg: str, *, data: Any | None = None) -> None:
    raise BizException(
        msg,
        code=ErrorCode.TASK_FAILURE,
        http_status=500,
        data=data,
        trigger_alert=True,
    )


def raise_service_exception(msg: str, *, data: Any | None = None) -> None:
    raise BizException(
        msg,
        code=ErrorCode.SERVICE_EXCEPTION,
        http_status=500,
        data=data,
        trigger_alert=True,
    )


def raise_crawler_risk(msg: str, *, data: Any | None = None) -> None:
    raise BizException(
        msg,
        code=ErrorCode.CRAWLER_RISK,
        http_status=429,
        data=data,
        trigger_alert=True,
    )


__all__ = [
    "ErrorCode",
    "BizException",
    "BizWarning",
    "raise_biz_error",
    "raise_task_failure",
    "raise_service_exception",
    "raise_crawler_risk",
]
