"""adapter/main — OpenClaw 适配网关入口（FastAPI）。"""

from __future__ import annotations

import traceback

from fastapi import FastAPI, Request, status
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from adapter.middleware import build_trace_middleware
from adapter.task_router import router as task_router
from adapter.tools_router import router as tools_router
from adapter.response import error
from adapter.middleware import TRACE_ID, new_trace_id
from infra.logger_setup import get_logger
from configs.settings import settings

logger = get_logger("openclaw.app")

app = FastAPI(
    title="OpenClaw 统一适配网关",
    description="BizTools4Openclaw · T13 智能体全链路对接层",
    version=settings.adapter.ADAPTER_VERSION,
    docs_url="/docs",
    redoc_url="/redoc",
)

# 注册中间件（Starlette 风格）
app.middleware("http")(build_trace_middleware())

# 注册路由
app.include_router(task_router)
app.include_router(tools_router)


@app.get("/health", tags=["system"])
async def health():
    return {"status": "OK", "version": settings.adapter.ADAPTER_VERSION,
            "adapter_auto_mask_pii": settings.adapter.ADAPTER_AUTO_MASK_PII}


@app.get("/api/v1/info", tags=["system"])
async def api_info():
    return error(
        0,
        msg="OpenClaw 网关信息",
        data={
            "version": settings.adapter.ADAPTER_VERSION,
            "base_url": settings.adapter.ADAPTER_BASE_URL,
            "docs": "/docs",
            "endpoints": {
                "tools": {
                    "list": "GET /api/v1/tools",
                    "detail": "GET /api/v1/tools/{tool_name}",
                    "execute": "POST /api/v1/tools/{tool_name}/execute",
                },
                "tasks": {
                    "enqueue": "POST /api/v1/tasks/enqueue",
                    "get": "GET /api/v1/tasks/{task_id}",
                    "list": "GET /api/v1/tasks",
                    "cancel": "DELETE /api/v1/tasks/{task_id}",
                    "webhook": "POST /api/v1/tasks/{task_id}/webhook",
                },
            },
        },
    )


# 全局异常处理（统一 JSON 响应）

@app.exception_handler(RequestValidationError)
async def validation_exception_handler(request: Request, exc: RequestValidationError):
    tid = TRACE_ID.get() or new_trace_id()
    return JSONResponse(
        status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
        content=error(422, f"参数校验失败: {exc.errors()}", trace_id=tid).model_dump(),
    )


@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    tid = TRACE_ID.get() or new_trace_id()
    tb = traceback.format_exc()
    logger.error(f"unhandled: {exc}\n{tb}")
    return JSONResponse(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        content=error(500, f"服务异常: {exc}", trace_id=tid).model_dump(),
    )


def run_server() -> None:
    """开发/生产统一入口。"""
    import uvicorn
    uvicorn.run(
        app,
        host=settings.adapter.ADAPTER_HOST,
        port=int(settings.adapter.ADAPTER_PORT),
        log_level=settings.adapter.ADAPTER_LOG_LEVEL.lower(),
    )


if __name__ == "__main__":
    run_server()


# ---- Web 管理后台（可选，默认启用） ----
try:
    if settings.web_admin.WEB_ADMIN_ENABLED:
        from web_admin.main import mount_on as mount_web_admin
        mount_web_admin(app)
except Exception as exc:
    logger.info(f"web_admin mount skipped: {exc}")


__all__ = ["app", "run_server"]
