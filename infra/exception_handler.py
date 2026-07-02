from __future__ import annotations

import asyncio
import traceback
from typing import Any

try:  # pragma: no cover - 允许在不依赖 FastAPI 时做单测 / 导入
    from fastapi import FastAPI, Request
    from fastapi.exceptions import HTTPException, RequestValidationError
    from fastapi.responses import JSONResponse
except Exception:  # pragma: no cover
    FastAPI = Any  # type: ignore
    Request = Any  # type: ignore
    HTTPException = Exception  # type: ignore
    RequestValidationError = Exception  # type: ignore
    JSONResponse = Any  # type: ignore

from infra.alerting import AlertType, alert_service
from infra.exceptions import BizException, ErrorCode
from infra.logger_setup import get_logger
from infra.response import ApiResponse, fail, from_exception

logger = get_logger(__name__)


def _maybe_trigger_alert(alert_type: AlertType, title: str, content: str) -> None:
    """异步触发告警，不阻塞主流程。"""
    try:
        loop = asyncio.get_event_loop()
        if loop.is_running():
            loop.create_task(
                alert_service.send_async(alert_type, title, content),
                name=f"alert-{alert_type.value}",
            )
        else:  # pragma: no cover
            alert_service.send_sync(alert_type, title, content)
    except Exception as exc:  # pragma: no cover
        logger.error(f"[exception_handler] trigger alert failed: {exc}")


# ---------- handlers ----------

async def _validation_error_handler(request: Request, exc: RequestValidationError) -> JSONResponse:
    detail = getattr(exc, "errors", lambda: [])()
    body, status = fail(
        ErrorCode.VALIDATION_ERROR,
        "请求参数校验失败",
        data={"detail": list(detail)},
        http_status=422,
    )
    logger.warning(f"[validation_error] path={getattr(request, 'url', None)} err={detail}")
    return JSONResponse(content=body.model_dump(), status_code=status)


async def _http_exception_handler(request: Request, exc: HTTPException) -> JSONResponse:
    http_status = int(getattr(exc, "status_code", 500))
    code = ErrorCode.BAD_REQUEST
    if http_status == 401:
        code = ErrorCode.UNAUTHORIZED
    elif http_status == 403:
        code = ErrorCode.FORBIDDEN
    elif http_status == 404:
        code = ErrorCode.NOT_FOUND
    elif http_status == 429:
        code = ErrorCode.TOO_MANY_REQUESTS
    elif http_status >= 500:
        code = ErrorCode.INTERNAL_ERROR
        _maybe_trigger_alert(
            AlertType.SERVICE_EXCEPTION,
            f"HTTP {http_status}",
            f"path={getattr(request, 'url', None)}\n\n{getattr(exc, 'detail', '')}",
        )

    body: ApiResponse[Any] = ApiResponse[Any](
        code=code,
        msg=str(getattr(exc, "detail", "服务异常")),
        data=None,
    )
    return JSONResponse(content=body.model_dump(), status_code=http_status)


async def _biz_exception_handler(request: Request, exc: BizException) -> JSONResponse:
    body, status = fail(exc.code, exc.msg or "业务异常", data=exc.data, http_status=exc.http_status)

    if exc.trigger_alert:
        alert_type = AlertType.SERVICE_EXCEPTION
        if exc.code == ErrorCode.TASK_FAILURE:
            alert_type = AlertType.TASK_FAILURE
        elif exc.code == ErrorCode.CRAWLER_RISK:
            alert_type = AlertType.CRAWLER_RISK

        _maybe_trigger_alert(
            alert_type,
            f"{exc.msg}",
            f"path={getattr(request, 'url', None)}\n\ndata={exc.data}",
        )

    logger.error(f"[biz_exception] code={exc.code} msg={exc.msg}")
    return JSONResponse(content=body.model_dump(), status_code=status)


async def _unhandled_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    tb = traceback.format_exc()
    logger.error(f"[unhandled_exception] path={getattr(request, 'url', None)}\n{tb}")

    _maybe_trigger_alert(
        AlertType.SERVICE_EXCEPTION,
        type(exc).__name__,
        f"path={getattr(request, 'url', None)}\n\nmessage={exc}\n\n{tb}",
    )

    body, status = from_exception(exc)
    return JSONResponse(content=body.model_dump(), status_code=status)


# ---------- 对外 API ----------

def register_exception_handlers(app: FastAPI) -> None:
    """在 FastAPI 应用上注册统一异常处理器。

    Usage:
        from infra.exception_handler import register_exception_handlers
        register_exception_handlers(app)
    """
    if RequestValidationError is not Exception:
        app.add_exception_handler(RequestValidationError, _validation_error_handler)
    if HTTPException is not Exception:
        app.add_exception_handler(HTTPException, _http_exception_handler)
    app.add_exception_handler(BizException, _biz_exception_handler)
    app.add_exception_handler(Exception, _unhandled_exception_handler)

    logger.info("exception handlers registered")


__all__ = ["register_exception_handlers"]
