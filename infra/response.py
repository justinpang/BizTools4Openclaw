from __future__ import annotations

from datetime import datetime
from typing import Any, Generic, TypeVar

from pydantic import BaseModel, Field

T = TypeVar("T")


class ApiResponse(BaseModel, Generic[T]):
    """全局统一 API 响应结构体。

    字段顺序必须保持: code / msg / data / timestamp
    """

    code: int = Field(default=0, description="业务状态码；0 成功，其余失败")
    msg: str = Field(default="ok", description="状态描述")
    data: T | None = Field(default=None, description="业务数据体")
    timestamp: int = Field(
        default_factory=lambda: int(datetime.now().timestamp()),
        description="服务端 Unix 时间戳（秒）",
    )

    model_config = {
        "json_encoders": {},
    }


def ok(data: T | None = None, msg: str = "ok") -> ApiResponse[T]:
    """成功响应工厂。"""
    return ApiResponse[T](code=0, msg=msg, data=data)


def fail(
    code: int,
    msg: str,
    data: Any | None = None,
    http_status: int = 400,
) -> tuple[ApiResponse[Any], int]:
    """失败响应工厂。返回 (响应体, HTTP 状态码) 二元组。"""
    return ApiResponse[Any](code=code, msg=msg, data=data), http_status


def from_exception(
    exc: Exception,
    default_code: int = 50000,
    default_msg: str = "服务内部异常",
    http_status: int = 500,
) -> tuple[ApiResponse[Any], int]:
    """从异常对象构建统一响应体。"""
    # 延迟导入，避免循环依赖（BizException 依赖本模块中的错误码常量）
    try:
        from infra.exceptions import BizException

        if isinstance(exc, BizException):
            http_status = getattr(exc, "http_status", http_status) or http_status
            return (
                ApiResponse[Any](
                    code=getattr(exc, "code", default_code),
                    msg=str(exc) or getattr(exc, "msg", default_msg),
                    data=getattr(exc, "data", None),
                ),
                http_status,
            )
    except Exception:
        pass

    return ApiResponse[Any](code=default_code, msg=default_msg, data=None), http_status


__all__ = ["ApiResponse", "ok", "fail", "from_exception"]
