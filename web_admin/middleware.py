"""web_admin/middleware — 操作行为日志中间件（增强版：含角色/操作类型/trace_id）。"""

from __future__ import annotations

import json
import secrets
import time
import uuid
from typing import Callable

from infra.logger_setup import get_logger
from infra.redis_client import get_redis
from infra.alerting import alert_service

logger = get_logger("web_admin.audit")

AUDIT_REDIS_KEY = "web_admin:audit_log"
AUDIT_MAX_LEN = 2000
HIGH_RISK_METHODS = {"DELETE", "POST", "PUT"}
HIGH_RISK_PATH_KEYWORDS = {"/delete", "/ban", "/unban", "/reject", "/account", "/remove", "/blacklist", "/pause"}

# 依据路径推断操作类型（供审计报表过滤）
OP_TYPE_RULES = [
    (("/login",), "session.login"),
    (("/logout",), "session.logout"),
    (("/admin/accounts",), "accounts.manage"),
    (("/reset_password",), "accounts.reset_password"),
    (("/spider",), "spider.manage"),
    (("/leads",), "leads.review"),
    (("/channels",), "channels.manage"),
    (("/sales",), "sales.manage"),
    (("/audit",), "audit.view"),
    (("/dashboard",), "dashboard.view"),
    (("/admin/403",), "permission.denied"),
]


def _guess_operation_type(path: str, method: str) -> str:
    for prefixes, tag in OP_TYPE_RULES:
        for p in prefixes:
            if p in path:
                return tag
    return f"request.{method.lower()}" if method else "request.unknown"


def _gen_trace_id() -> str:
    """生成短 trace_id，便于前端/后端关联。"""
    try:
        return uuid.uuid4().hex[:16]
    except Exception:
        return secrets.token_hex(8)


def build_audit_middleware(session_getter: Callable) -> Callable:
    """返回 Starlette 风格的中间件 callable。session_getter(request) 返回 session dict 或 None。

    增强字段：
      - role / permissions：从 session 中取，用于审计过滤；
      - operation_type：依据路径/方法推断的操作标签；
      - trace_id：每次请求生成短 trace_id，便于和后端异常日志关联；
      - action_detail：可选（显式埋点可写入更详细描述）。
    """

    async def audit_middleware(request, call_next):
        start = time.time()
        trace_id = _gen_trace_id()

        # 从 headers 中优先采用调用方 trace id（若存在）
        try:
            upstream = request.headers.get("x-trace-id") or request.headers.get("x-request-id")
            if upstream:
                trace_id = str(upstream)[:32]
        except Exception:
            pass

        response = await call_next(request)
        latency_ms = int((time.time() - start) * 1000)

        method = getattr(request, "method", "")
        path = str(getattr(request, "url", "")) or ""
        client_ip = ""
        try:
            client = getattr(request, "client", None)
            client_ip = client.host if client and client.host else ""
        except Exception:
            pass

        session = session_getter(request)
        username = ""
        role = ""
        permissions: list[str] = []
        if isinstance(session, dict):
            username = session.get("username") or ""
            role = session.get("role") or ""
            if isinstance(session.get("permissions"), list):
                permissions = list(session["permissions"])

        status_code = getattr(response, "status_code", 0)

        entry = {
            "ts": int(time.time()),
            "username": username,
            "role": role,
            "permissions": permissions,
            "ip": client_ip,
            "method": method,
            "path": path,
            "operation_type": _guess_operation_type(path, method),
            "status": status_code,
            "latency_ms": latency_ms,
            "trace_id": trace_id,
        }
        line = json.dumps(entry, ensure_ascii=False, separators=(",", ":"))
        logger.info(line)

        # Redis 列表保存最近 N 条，供页面显示
        try:
            r = get_redis()
            if r is not None:
                r.lpush(AUDIT_REDIS_KEY, line)
                r.ltrim(AUDIT_REDIS_KEY, 0, AUDIT_MAX_LEN - 1)
        except Exception:
            pass

        # 高危操作触发全局告警
        if method in HIGH_RISK_METHODS and any(k in path for k in HIGH_RISK_PATH_KEYWORDS):
            try:
                alert_service.service_exception_sync(
                    service_name="web_admin",
                    message=(
                        f"[HIGH_RISK] user={username or 'unknown'} role={role or '-'} "
                        f"ip={client_ip} {method} {path} status={status_code} trace={trace_id}"
                    ),
                )
            except Exception:
                pass

        # 把 trace_id 写回响应头，便于前端关联
        try:
            if hasattr(response, "headers"):
                response.headers["X-Trace-Id"] = trace_id
        except Exception:
            pass

        return response

    return audit_middleware


def log_audit_event(username: str, role: str, operation_type: str,
                    action_detail: str | None = None, *, ip: str = "", status: int = 200,
                    path: str = "") -> str:
    """显式埋点 API。用于账号/权限等关键操作，在业务逻辑内直接调用。

    返回：当前事件的 trace_id。
    """
    trace_id = _gen_trace_id()
    entry = {
        "ts": int(time.time()),
        "username": username or "",
        "role": role or "",
        "ip": ip or "",
        "method": "ACTION",
        "path": path or action_detail or "",
        "operation_type": operation_type or "action.unknown",
        "action_detail": action_detail or "",
        "status": int(status),
        "latency_ms": 0,
        "trace_id": trace_id,
    }
    line = json.dumps(entry, ensure_ascii=False, separators=(",", ":"))
    logger.info(line)
    try:
        r = get_redis()
        if r is not None:
            r.lpush(AUDIT_REDIS_KEY, line)
            r.ltrim(AUDIT_REDIS_KEY, 0, AUDIT_MAX_LEN - 1)
    except Exception:
        pass
    return trace_id


def load_audit_logs(limit: int = 50) -> list[dict]:
    """读取最近 N 条审计日志（旧版接口，保留向后兼容）。"""
    try:
        r = get_redis()
        if r is not None:
            raws = r.lrange(AUDIT_REDIS_KEY, 0, max(0, int(limit) - 1))
            out = []
            for raw in raws:
                try:
                    s = raw.decode("utf-8") if isinstance(raw, bytes) else str(raw)
                    out.append(json.loads(s))
                except Exception:
                    continue
            return out
    except Exception:
        pass
    return []


def load_audit_logs_enhanced(*, role: str | None = None, op_type: str | None = None,
                             keyword: str | None = None, page: int = 1, page_size: int = 20) -> dict:
    """增强版查询：支持按角色/操作类型/关键字过滤 + 分页。

    返回：{"items": [...], "total": N, "page": page, "page_size": page_size}
    """
    raw_list = load_audit_logs(limit=AUDIT_MAX_LEN)

    def _match(entry: dict) -> bool:
        if role and entry.get("role") != role:
            return False
        if op_type and entry.get("operation_type") != op_type:
            return False
        if keyword:
            haystack = " ".join([
                entry.get("username") or "",
                entry.get("ip") or "",
                entry.get("path") or "",
                entry.get("action_detail") or "",
                entry.get("operation_type") or "",
                entry.get("trace_id") or "",
            ]).lower()
            if keyword.lower() not in haystack:
                return False
        return True

    filtered: list[dict] = [e for e in raw_list if _match(e)]
    total = len(filtered)
    page = max(1, int(page))
    page_size = max(1, min(int(page_size), 200))
    start = (page - 1) * page_size
    end = start + page_size
    return {
        "items": filtered[start:end],
        "total": total,
        "page": page,
        "page_size": page_size,
    }


__all__ = [
    "build_audit_middleware",
    "load_audit_logs",
    "load_audit_logs_enhanced",
    "log_audit_event",
    "AUDIT_REDIS_KEY",
]
