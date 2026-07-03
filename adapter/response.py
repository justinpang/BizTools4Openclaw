"""adapter/response — 统一API响应。"""

from __future__ import annotations

from typing import Any

from adapter.models import ApiResponse


def ok(data: Any = None, *, trace_id: str | None = None,
       task_id: str | None = None, msg: str = "OK") -> ApiResponse:
    """成功响应。"""
    return ApiResponse(code=0, msg=msg, data=data, trace_id=trace_id, task_id=task_id)


def error(code: int, msg: str, *, data: Any = None,
          trace_id: str | None = None, task_id: str | None = None) -> ApiResponse:
    """错误响应。"""
    return ApiResponse(code=code, msg=msg, data=data, trace_id=trace_id, task_id=task_id)


__all__ = ["ok", "error"]
