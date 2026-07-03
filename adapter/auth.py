"""adapter/auth — Bearer Token 鉴权 + IP 白名单 + 配额限流。"""

from __future__ import annotations

from datetime import datetime, timezone

from fastapi import Header, HTTPException, Request, status

from infra.logger_setup import get_logger
from configs.settings import settings

logger = get_logger("openclaw.auth")


# ---- 工具函数 ----

def _alert(kind: str, detail: str) -> None:
    """统一触发全局告警。"""
    try:
        from infra.alerting import alert_service
        if hasattr(alert_service, "service_exception_sync"):
            alert_service.service_exception_sync(
                service_name="openclaw_adapter",
                message=f"[{kind}] {detail}",
            )
    except Exception:
        pass


# ---- Depends 函数 ----

async def require_token(authorization: str | None = Header(default=None)) -> str:
    """校验 Bearer Token。若失败返回 401。"""
    if not authorization:
        logger.warning("auth: missing Authorization header")
        _alert("AUTH_MISSING", "缺少 Authorization 请求头")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="缺少 Authorization header (Bearer Token)",
            headers={"WWW-Authenticate": "Bearer"},
        )
    parts = authorization.strip().split()
    if len(parts) != 2 or parts[0].lower() != "bearer":
        logger.warning("auth: invalid Authorization format")
        _alert("AUTH_INVALID", "Authorization 格式应为 'Bearer <token>'")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authorization 格式错误，应为 'Bearer <token>'",
            headers={"WWW-Authenticate": "Bearer"},
        )
    token = parts[1].strip()
    valid_tokens = settings.adapter.get_tokens()
    if token not in valid_tokens:
        logger.warning("auth: invalid token provided")
        _alert("AUTH_FAIL", "Token 校验失败")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token 无效",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return token


async def check_ip_whitelist(request: Request) -> None:
    """IP 白名单校验（若配置为空则直接放行）。"""
    allowed = settings.adapter.get_ips()
    if not allowed:
        return
    # 推断 client_ip
    ip = request.headers.get("X-Forwarded-For", "").strip()
    if ip and "," in ip:
        ip = ip.split(",")[0].strip()
    if not ip:
        client = request.client
        ip = client.host if client and client.host else ""
    if ip and ip not in allowed:
        logger.warning(f"auth: ip {ip} not in whitelist")
        _alert("IP_BLOCKED", f"IP {ip} 不在白名单")
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=f"IP {ip} 不在白名单",
        )


async def check_agent_quota(
    request: Request,
    x_agent_id: str | None = Header(default=None),
) -> str:
    """单 Agent 每日配额限流。返回 agent_id。"""
    agent_id = (x_agent_id or "unknown-agent").strip()
    quota = int(settings.adapter.ADAPTER_DAILY_QUOTA_PER_AGENT or 0)
    if quota <= 0:
        return agent_id

    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    key = f"openclaw:quota:{agent_id}:{today}"

    # Redis 原子计数（若不可用，降级为放行+告警）
    try:
        from infra.redis_client import get_redis_client
        r = get_redis_client()
        if r is None:
            raise RuntimeError("redis unavailable")

        current = r.incr(key)
        # 首次设置 TTL
        if current == 1:
            try:
                r.expire(key, 60 * 60 * 24 + 300)
            except Exception:
                pass
        if current > quota:
            logger.warning(f"auth: agent {agent_id} quota exceeded: {current}/{quota}")
            _alert("QUOTA_EXCEEDED", f"agent={agent_id} 今日调用 {current}/{quota}，超出配额")
            raise HTTPException(
                status_code=429,
                detail=f"超出每日配额 {quota}，明日再试（今日已调用 {current} 次）",
                headers={"Retry-After": "3600"},
            )
    except HTTPException:
        raise
    except Exception as exc:
        # Redis 不可用 → 降级，不阻断业务
        logger.info(f"auth: quota check skipped ({exc})")

    return agent_id


__all__ = [
    "require_token",
    "check_ip_whitelist",
    "check_agent_quota",
]
