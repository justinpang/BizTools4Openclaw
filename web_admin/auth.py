"""web_admin/auth — 登录与会话管理（账号密码 + Redis 会话）。"""

from __future__ import annotations

import json
import secrets
import time
from typing import Any

from fastapi import Depends, HTTPException, Request, status
from fastapi.responses import JSONResponse, RedirectResponse

from infra.logger_setup import get_logger
from infra.redis_client import get_redis
from configs.settings import settings

logger = get_logger("web_admin.auth")

SESSION_COOKIE = "admin_session"
REDIS_PREFIX = "web_admin:session:"
_PASSWORD_HASH_KEY = "web_admin:password_hash"


# ---- 密码哈希（降级方案：优先尝试 bcrypt，否则用内置 hashlib + salt） ----

def _hashlib_hash(password: str) -> str:
    """内置降级哈希：sha256 + 随机 salt，格式 'h2|{salt_b64}|{hash_b64}'。"""
    import base64
    import hashlib
    salt = secrets.token_bytes(16)
    h = hashlib.sha256(salt + password.encode("utf-8")).digest()
    return "h2|" + base64.b64encode(salt).decode("ascii") + "|" + base64.b64encode(h).decode("ascii")


def _hashlib_verify(password: str, hashed: str) -> bool:
    import base64
    import hashlib
    try:
        parts = hashed.split("|")
        if len(parts) != 3 or parts[0] != "h2":
            return False
        salt = base64.b64decode(parts[1])
        expected = base64.b64decode(parts[2])
        actual = hashlib.sha256(salt + password.encode("utf-8")).digest()
        return secrets.compare_digest(actual, expected)
    except Exception as exc:
        logger.info(f"verify failed: {exc}")
        return False


def _hash_password(password: str) -> str:
    try:
        import bcrypt  # type: ignore
        return "bc|" + bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")
    except Exception:
        return _hashlib_hash(password)


def _verify_password(password: str, hashed: str) -> bool:
    if not hashed or not password:
        return False
    if hashed.startswith("bc|"):
        try:
            import bcrypt  # type: ignore
            return bcrypt.checkpw(password.encode("utf-8"), hashed[3:].encode("utf-8"))
        except Exception:
            return False
    return _hashlib_verify(password, hashed)


def get_or_create_password_hash() -> str | None:
    """返回已有的密码 hash；如果只有 plaintext，首次 hash 后写入 Redis。"""
    # 1) env 里的 hash 优先
    env_hash = settings.web_admin.WEB_ADMIN_PASSWORD_HASH or ""
    if env_hash:
        return env_hash
    # 2) Redis 缓存 hash
    try:
        r = get_redis()
        if r is not None:
            cached = r.get(_PASSWORD_HASH_KEY)
            if cached:
                return cached.decode("utf-8") if isinstance(cached, bytes) else str(cached)
    except Exception:
        pass
    # 3) env 里的 plaintext → 一次性 hash 并缓存
    plain = settings.web_admin.WEB_ADMIN_PASSWORD_PLAIN or ""
    if plain:
        new_hash = _hash_password(plain)
        try:
            r = get_redis()
            if r is not None:
                r.set(_PASSWORD_HASH_KEY, new_hash)
        except Exception:
            pass
        logger.info("web_admin: 初始化密码 hash 完成")
        return new_hash
    return None


# ---- 会话 ----

def create_session(username: str, *, client_ip: str) -> str:
    """创建 session，返回 session_token。"""
    token = secrets.token_urlsafe(32)
    session = {
        "username": username,
        "ip": client_ip,
        "created_at": int(time.time()),
        "last_seen": int(time.time()),
    }
    try:
        r = get_redis()
        if r is not None:
            r.set(
                REDIS_PREFIX + token,
                value=json.dumps(session, ensure_ascii=False),
                ex=int(settings.web_admin.WEB_ADMIN_SESSION_TTL_SECONDS),
            )
    except Exception as exc:
        logger.info(f"redis session create fallback: {exc}")
        # 降级：进程内 dict（用于单节点、开发期）
        _INPROC_SESSION_CACHE[token] = (session, time.time() + settings.web_admin.WEB_ADMIN_SESSION_TTL_SECONDS)
    return token


def _get_session_raw(token: str) -> dict | None:
    try:
        r = get_redis()
        if r is not None:
            raw = r.get(REDIS_PREFIX + token)
            if raw is None:
                return None
            data = raw.decode("utf-8") if isinstance(raw, bytes) else str(raw)
            return json.loads(data)
    except Exception:
        pass
    # 降级到进程内
    entry = _INPROC_SESSION_CACHE.get(token)
    if entry is None or entry[1] < time.time():
        return None
    return entry[0]


def delete_session(token: str) -> None:
    try:
        r = get_redis()
        if r is not None:
            r.delete(REDIS_PREFIX + token)
    except Exception:
        pass
    _INPROC_SESSION_CACHE.pop(token, None)


def refresh_session_ttl(token: str, session: dict) -> None:
    """每次成功鉴权，刷新 session TTL。"""
    try:
        session["last_seen"] = int(time.time())
        r = get_redis()
        if r is not None:
            r.set(
                REDIS_PREFIX + token,
                value=json.dumps(session, ensure_ascii=False),
                ex=int(settings.web_admin.WEB_ADMIN_SESSION_TTL_SECONDS),
            )
    except Exception:
        # 降级：进程内重写
        _INPROC_SESSION_CACHE[token] = (session, time.time() + settings.web_admin.WEB_ADMIN_SESSION_TTL_SECONDS)


_INPROC_SESSION_CACHE: dict[str, tuple[dict, float]] = {}


# ---- Depends ----

async def require_admin(request: Request) -> dict[str, Any]:
    """依赖函数：要求已登录。返回 session 字典。"""
    token = request.cookies.get(SESSION_COOKIE)
    if not token:
        return _reject(request)
    session = _get_session_raw(token)
    if not session:
        return _reject(request)
    refresh_session_ttl(token, session)
    return session


def _reject(request: Request):
    # 浏览器页面请求 → 重定向到登录页；API 请求 → 401 JSON
    accept = request.headers.get("accept", "")
    if "application/json" in accept or (request.method == "GET" and "/api/admin/" in str(request.url)):
        raise HTTPException(status_code=401, detail="未登录或会话已失效")
    raise HTTPException(status_code=401, detail="未登录或会话已失效")


async def get_current_admin(request: Request) -> dict[str, Any] | None:
    """非强制：若有有效 session 返回之，否则返回 None。"""
    token = request.cookies.get(SESSION_COOKIE)
    if not token:
        return None
    session = _get_session_raw(token)
    if session:
        refresh_session_ttl(token, session)
        return session
    return None


# ---- 登录/登出接口（供 web_admin.main 中直接调用 handler，或在 pages.py 中使用） ----

def handle_login_post(username: str, password: str, *, client_ip: str) -> tuple[bool, str, str]:
    """
    返回 (是否成功, session_token, 消息)。
    由调用方（pages.py）负责设置 Cookie。
    """
    if not username or not password:
        return False, "", "账号/密码不能为空"
    expected_username = settings.web_admin.WEB_ADMIN_USERNAME or "admin"
    if username != expected_username:
        logger.warning(f"web_admin login fail: unknown user {username} from {client_ip}")
        return False, "", "账号或密码错误"

    password_hash = get_or_create_password_hash()
    if not password_hash:
        logger.warning("web_admin: 未配置密码，禁止登录")
        return False, "", "管理员密码未配置"

    if not _verify_password(password, password_hash):
        logger.warning(f"web_admin login fail: wrong password from {client_ip}")
        return False, "", "账号或密码错误"

    token = create_session(username, client_ip=client_ip)
    return True, token, "登录成功"


__all__ = [
    "SESSION_COOKIE",
    "require_admin",
    "get_current_admin",
    "handle_login_post",
    "delete_session",
]
