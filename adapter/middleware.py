"""adapter/middleware — Trace ID 中间件 + 上下文注入。"""

from __future__ import annotations

import time
import uuid
from contextvars import ContextVar
from typing import Callable

from infra.logger_setup import get_logger

logger = get_logger("openclaw.trace")

# 全局上下文变量，供 adapter 所有模块读取
TRACE_ID: ContextVar[str] = ContextVar("trace_id", default="")
AGENT_ID: ContextVar[str] = ContextVar("agent_id", default="")
CLIENT_IP: ContextVar[str] = ContextVar("client_ip", default="")
TOOL_NAME: ContextVar[str] = ContextVar("tool_name", default="")


def new_trace_id() -> str:
    return "oc_" + uuid.uuid4().hex[:12]


def get_context() -> dict[str, str]:
    """获取当前请求上下文（用于日志/响应）。"""
    return {
        "trace_id": TRACE_ID.get(),
        "agent_id": AGENT_ID.get(),
        "client_ip": CLIENT_IP.get(),
        "tool_name": TOOL_NAME.get(),
    }


# ---- FastAPI 中间件：Starlette 风格 ----

def build_trace_middleware() -> Callable:
    """返回一个 FastAPI 可用的中间件 callable。"""

    async def trace_middleware(request, call_next):
        # 1. 从请求头读取或生成 trace_id
        incoming_trace = request.headers.get("X-Trace-Id", "").strip()
        tid = incoming_trace if incoming_trace else new_trace_id()

        agent_id = request.headers.get("X-Agent-Id", "unknown-agent").strip()

        # 推断 client_ip
        ip = request.headers.get("X-Forwarded-For", "").strip()
        if ip and "," in ip:
            ip = ip.split(",")[0].strip()
        if not ip:
            client = request.client
            ip = client.host if client and client.host else "unknown"

        # 设置上下文
        TRACE_ID.set(tid)
        AGENT_ID.set(agent_id)
        CLIENT_IP.set(ip)

        start = time.time()
        response = await call_next(request)
        latency_ms = int((time.time() - start) * 1000)

        # 响应注入
        response.headers["X-Trace-Id"] = tid

        status_code = getattr(response, "status_code", 200)
        method = getattr(request, "method", "")
        path = getattr(request, "url", "")
        path_str = str(path.path) if hasattr(path, "path") else str(path)

        logger.info(
            f"request: method={method} path={path_str} status={status_code} "
            f"latency_ms={latency_ms} trace_id={tid} agent={agent_id} client_ip={ip}"
        )
        return response

    return trace_middleware


__all__ = [
    "TRACE_ID",
    "AGENT_ID",
    "CLIENT_IP",
    "TOOL_NAME",
    "new_trace_id",
    "get_context",
    "build_trace_middleware",
]
