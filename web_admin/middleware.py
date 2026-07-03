"""web_admin/middleware — 操作行为日志中间件。"""

from __future__ import annotations

import json
import time
from typing import Callable

from infra.logger_setup import get_logger
from infra.redis_client import get_redis
from infra.alerting import alert_service

logger = get_logger("web_admin.audit")

AUDIT_REDIS_KEY = "web_admin:audit_log"
AUDIT_MAX_LEN = 2000
HIGH_RISK_METHODS = {"DELETE", "POST", "PUT"}
HIGH_RISK_PATH_KEYWORDS = {"/delete", "/ban", "/unban", "/reject", "/account", "/remove", "/blacklist", "/pause"}


def build_audit_middleware(session_getter: Callable) -> Callable:
    """返回 Starlette 风格的中间件 callable。session_getter(request) 返回 session dict 或 None。"""

    async def audit_middleware(request, call_next):
        start = time.time()
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
        username = session.get("username") if isinstance(session, dict) else ""

        status_code = getattr(response, "status_code", 0)

        entry = {
            "ts": int(time.time()),
            "username": username,
            "ip": client_ip,
            "method": method,
            "path": path,
            "status": status_code,
            "latency_ms": latency_ms,
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
                    message=f"[HIGH_RISK] user={username or 'unknown'} ip={client_ip} {method} {path} status={status_code}",
                )
            except Exception:
                pass

        return response

    return audit_middleware


def load_audit_logs(limit: int = 50) -> list[dict]:
    """读取最近 N 条审计日志。"""
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


__all__ = [
    "build_audit_middleware",
    "load_audit_logs",
    "AUDIT_REDIS_KEY",
]
