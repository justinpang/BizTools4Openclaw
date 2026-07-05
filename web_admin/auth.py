"""web_admin/auth — 登录与会话管理（多账号 + 四级角色权限 + Redis 会话，进程内降级）。"""

from __future__ import annotations

import json
import secrets
import time
from typing import Any

from fastapi import Depends, HTTPException, Request, status

from infra.logger_setup import get_logger
from infra.redis_client import get_redis
from configs.settings import settings

logger = get_logger("web_admin.auth")

SESSION_COOKIE = "admin_session"
REDIS_PREFIX = "web_admin:session:"
_PASSWORD_HASH_KEY = "web_admin:password_hash"

# ---------------------------------------------------------------------------
# 角色定义 + 权限矩阵
# ---------------------------------------------------------------------------
ROLE_SUPER_ADMIN = "super_admin"
ROLE_OPS = "ops"
ROLE_SALES = "sales"
ROLE_COMPLIANCE = "compliance"
VALID_ROLES = {ROLE_SUPER_ADMIN, ROLE_OPS, ROLE_SALES, ROLE_COMPLIANCE}

# 角色中文标签（用于 UI 展示）
ROLE_LABELS = {
    ROLE_SUPER_ADMIN: "超级管理员",
    ROLE_OPS: "运营岗",
    ROLE_SALES: "销售岗",
    ROLE_COMPLIANCE: "合规岗",
}

# 按钮/操作级别权限：每个角色对应的权限标识集合
# 说明：按钮级权限由前端 data-requires-permission 控制展示，后端 API handler 中再次校验
ROLE_PERMISSIONS: dict[str, set[str]] = {
    ROLE_SUPER_ADMIN: {
        "btn.dashboard.view",
        "btn.spider.view",
        "btn.spider.create",
        "btn.spider.delete",
        "btn.spider.run",
        "btn.spider.pause",
        "btn.spider.resume",
        "btn.spider.terminate",
        "btn.spider.retry",
        "btn.spider.view_items",
        "btn.leads.view",
        "btn.leads.approve",
        "btn.leads.reject",
        "btn.leads.add_blacklist",
        "btn.channels.view",
        "btn.channels.create",
        "btn.channels.view_secret",
        "btn.sales.view",
        "btn.sales.create",
        "btn.sales.assign",
        "btn.sales.record_followup",
        "btn.audit.view",
        "btn.audit.export",
        "btn.system.accounts",
        "btn.system.reset_password",
        "btn.system.view_secret",
        "btn.compliance.review",
        "btn.compliance.approve",
        "btn.compliance.reject",
        "btn.compliance.view_history",
        "btn.compliance.config",
        "btn.compliance.notification",
        "btn.data_center.view",
        "btn.data_center.view_raw",
    },
    ROLE_OPS: {
        "btn.dashboard.view",
        "btn.spider.view",
        "btn.spider.create",
        "btn.spider.run",
        "btn.spider.pause",
        "btn.spider.resume",
        "btn.spider.terminate",
        "btn.spider.retry",
        "btn.spider.view_items",
        "btn.leads.view",
        "btn.leads.approve",
        "btn.leads.reject",
        "btn.leads.add_blacklist",
        "btn.audit.view",
        "btn.compliance.notification",
        "btn.data_center.view",
    },
    ROLE_SALES: {
        "btn.dashboard.view",
        "btn.leads.view",
        "btn.sales.view",
        "btn.sales.assign",
        "btn.sales.record_followup",
        "btn.compliance.notification",
        "btn.data_center.view",
    },
    ROLE_COMPLIANCE: {
        "btn.dashboard.view",
        "btn.channels.view",
        "btn.channels.create",
        "btn.audit.view",
        "btn.compliance.review",
        "btn.compliance.approve",
        "btn.compliance.reject",
        "btn.compliance.view_history",
        "btn.compliance.notification",
        "btn.data_center.view",
    },
}


# ---------------------------------------------------------------------------
# 密码哈希（bcrypt 优先，否则内置 hashlib + salt 降级）
# ---------------------------------------------------------------------------
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
    except Exception:
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


def _normalize_account(acc: dict) -> dict | None:
    """将 env 中的一项账号配置标准化；字段缺失则忽略该账号。"""
    username = (acc.get("username") or "").strip()
    if not username:
        return None
    role = (acc.get("role") or ROLE_SUPER_ADMIN).strip()
    if role not in VALID_ROLES:
        logger.warning(f"web_admin: 账号 {username} 的 role 无效: {role}，忽略")
        return None
    password_hash = (acc.get("password_hash") or "").strip()
    password_plain = (acc.get("password_plain") or "").strip()
    disabled = bool(acc.get("disabled"))
    created_at = int(acc.get("created_at") or time.time())
    # 若有 password_plain 但无 password_hash，则现场 hash 一次（不持久化明文）
    if not password_hash and password_plain:
        password_hash = _hash_password(password_plain)
    return {
        "username": username,
        "role": role,
        "password_hash": password_hash,
        "disabled": disabled,
        "created_at": created_at,
    }


# ---------------------------------------------------------------------------
# 账号加载
# ---------------------------------------------------------------------------
def load_accounts() -> list[dict]:
    """从 .env 解析账号配置。返回 list[dict]，字段同 _normalize_account。"""
    raw = (settings.web_admin.WEB_ADMIN_ACCOUNTS_JSON or "").strip()
    if raw:
        try:
            parsed = json.loads(raw)
            if not isinstance(parsed, list):
                raise ValueError("WEB_ADMIN_ACCOUNTS_JSON 必须是 JSON 数组")
            accounts: list[dict] = []
            seen: set[str] = set()
            for item in parsed:
                if not isinstance(item, dict):
                    continue
                acc = _normalize_account(item)
                if acc is None:
                    continue
                if acc["username"] in seen:
                    logger.warning(f"web_admin: 账号 {acc['username']} 重复，忽略重复项")
                    continue
                seen.add(acc["username"])
                accounts.append(acc)
            if accounts:
                logger.info(f"web_admin: 从 WEB_ADMIN_ACCOUNTS_JSON 加载 {len(accounts)} 个账号")
                return accounts
        except Exception as exc:
            logger.warning(f"web_admin: WEB_ADMIN_ACCOUNTS_JSON 解析失败: {exc}，回退到单账号模式")

    # 回退：单账号模式
    username = settings.web_admin.WEB_ADMIN_USERNAME or "admin"
    password_hash = settings.web_admin.WEB_ADMIN_PASSWORD_HASH or ""
    if not password_hash:
        password_plain = settings.web_admin.WEB_ADMIN_PASSWORD_PLAIN or ""
        if password_plain:
            password_hash = _hash_password(password_plain)
    logger.info(f"web_admin: 单账号模式 username={username}")
    return [{
        "username": username,
        "role": ROLE_SUPER_ADMIN,
        "password_hash": password_hash,
        "disabled": False,
        "created_at": int(time.time()),
    }]


_ACCOUNTS_CACHE_TS: float = 0
_ACCOUNTS_CACHE: list[dict] = []


def reload_accounts() -> None:
    """强制重载账号列表（账号变更后调用）。"""
    global _ACCOUNTS_CACHE, _ACCOUNTS_CACHE_TS
    _ACCOUNTS_CACHE = load_accounts()
    _ACCOUNTS_CACHE_TS = time.time()


def get_accounts() -> list[dict]:
    """获取账号列表（带进程级惰性缓存，每 5 分钟重新解析一次）。"""
    global _ACCOUNTS_CACHE, _ACCOUNTS_CACHE_TS
    now = time.time()
    if now - _ACCOUNTS_CACHE_TS > 300:
        _ACCOUNTS_CACHE = load_accounts()
        _ACCOUNTS_CACHE_TS = now
    return _ACCOUNTS_CACHE


def _ensure_cache_populated() -> None:
    """首次访问时确保账号缓存已填充（供动态账号创建功能使用）。"""
    get_accounts()


def add_in_memory_account(username: str, password_plain: str, *,
                          role: str = ROLE_OPS, disabled: bool = False) -> bool:
    """在进程内缓存中新增账号（不持久化到 .env）。

    注意：仅在 WEB_ADMIN_ACCOUNTS_JSON 启用时有效（单账号模式下禁止动态创建）。
    返回是否新增成功。
    """
    _ensure_cache_populated()
    if username in {a["username"] for a in _ACCOUNTS_CACHE}:
        return False
    if role not in VALID_ROLES:
        return False
    if not password_plain:
        return False
    new_acc = {
        "username": username,
        "role": role,
        "password_hash": _hash_password(password_plain),
        "disabled": disabled,
        "created_at": int(time.time()),
    }
    _ACCOUNTS_CACHE.append(new_acc)
    return True


def invalidate_account_sessions(username: str) -> None:
    """禁用/重置密码后：使该账号下的所有登录会话立即失效。"""
    invalidate_user_sessions(username)


def is_super_admin(session_or_role: str | dict | None) -> bool:
    """判断某会话/角色是否为 super_admin。"""
    if isinstance(session_or_role, dict):
        role = session_or_role.get("role") or ""
    else:
        role = (session_or_role or "").strip()
    return role == ROLE_SUPER_ADMIN


def lookup_account(username: str) -> dict | None:
    for acc in get_accounts():
        if acc["username"] == username:
            return acc
    return None


# ---------------------------------------------------------------------------
# 会话（Redis + 进程内 dict 降级）
# ---------------------------------------------------------------------------
def create_session(username: str, *, role: str | None = None, client_ip: str = "") -> str:
    """创建 session，返回 session_token。

    role 可选：未传时默认 super_admin（保持向后兼容）。
    client_ip 可选：兼容旧签名。
    """
    token = secrets.token_urlsafe(32)
    if not role:
        role = ROLE_SUPER_ADMIN
    session = {
        "username": username,
        "role": role,
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
            # 同时记录 user -> token 列表，便于单账号登出 / 重置密码使所有 session 失效
            r.lpush(REDIS_PREFIX + "by_user:" + username, token)
            r.ltrim(REDIS_PREFIX + "by_user:" + username, 0, 49)
    except Exception as exc:
        logger.info(f"redis session create fallback: {exc}")
    _INPROC_SESSION_CACHE[token] = (session, time.time() + settings.web_admin.WEB_ADMIN_SESSION_TTL_SECONDS)
    return token


def _get_session_raw(token: str) -> dict | None:
    try:
        r = get_redis()
        if r is not None:
            raw = r.get(REDIS_PREFIX + token)
            if raw is not None:
                data = raw.decode("utf-8") if isinstance(raw, bytes) else str(raw)
                return json.loads(data)
    except Exception:
        pass
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


def invalidate_user_sessions(username: str) -> None:
    """使某账号下所有 session 失效（重置密码/禁用账号时调用）。"""
    try:
        r = get_redis()
        if r is not None:
            key = REDIS_PREFIX + "by_user:" + username
            tokens = r.lrange(key, 0, -1)
            for t in tokens:
                r.delete(t.decode("utf-8") if isinstance(t, bytes) else str(t))
            r.delete(key)
    except Exception:
        pass
    for tk, (sess, _) in list(_INPROC_SESSION_CACHE.items()):
        if sess.get("username") == username:
            _INPROC_SESSION_CACHE.pop(tk, None)


def refresh_session_ttl(token: str, session: dict) -> None:
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
        _INPROC_SESSION_CACHE[token] = (session, time.time() + settings.web_admin.WEB_ADMIN_SESSION_TTL_SECONDS)


_INPROC_SESSION_CACHE: dict[str, tuple[dict, float]] = {}


# ---------------------------------------------------------------------------
# 权限判定
# ---------------------------------------------------------------------------
def get_permissions_for_role(role: str) -> set[str]:
    """返回指定角色的权限标识集合。"""
    return set(ROLE_PERMISSIONS.get(role, set()))


def has_permission(role: str, perm: str) -> bool:
    return perm in get_permissions_for_role(role)


def role_can_view_menu(role: str, active_key: str) -> bool:
    """菜单可见性：基于 active_key 判断某角色是否能访问该菜单。"""
    ops_role = {ROLE_SUPER_ADMIN, ROLE_OPS}
    compliance_role = {ROLE_SUPER_ADMIN, ROLE_COMPLIANCE}
    map_: dict[str, set[str]] = {
        "dashboard": VALID_ROLES,
        "data_center": VALID_ROLES,
        "spider": ops_role,
        "spider_generic": ops_role,
        "spider_video": ops_role,
        "spider_xhs": ops_role,
        "spider_qa": ops_role,
        "spider_b2b": ops_role,
        "spider_bidding": ops_role,
        "spider_company": ops_role,
        "spider_detail": ops_role,
        "leads": {ROLE_SUPER_ADMIN, ROLE_SALES},
        "channels": {ROLE_SUPER_ADMIN, ROLE_COMPLIANCE},
        "sales": {ROLE_SUPER_ADMIN, ROLE_SALES},
        "audit_log": {ROLE_SUPER_ADMIN, ROLE_OPS, ROLE_COMPLIANCE},
        "system": {ROLE_SUPER_ADMIN},
        "accounts": {ROLE_SUPER_ADMIN},
        "compliance_review": compliance_role,
        "compliance_pending": compliance_role,
        "compliance_history": compliance_role,
        "compliance_config": {ROLE_SUPER_ADMIN},
        "notifications": VALID_ROLES,
        "empty": VALID_ROLES,
        "403": VALID_ROLES,
        # T21: 数据中心菜单
        "data_center_dashboard": VALID_ROLES,
        "data_center_collection": ops_role,
        "data_center_cleaning": {ROLE_SUPER_ADMIN, ROLE_OPS, ROLE_COMPLIANCE},
        "data_center_compliance": compliance_role,
        "data_center_grading": {ROLE_SUPER_ADMIN, ROLE_SALES},
        "data_center_outreach": {ROLE_SUPER_ADMIN, ROLE_SALES},
        "data_center_sales": {ROLE_SUPER_ADMIN, ROLE_SALES},
        "data_center_opportunity": VALID_ROLES,
    }
    return role in map_.get(active_key, set())


async def require_admin(request: Request) -> dict[str, Any]:
    """依赖函数：要求已登录。返回 session 字典（含 role 字段）。"""
    token = request.cookies.get(SESSION_COOKIE)
    if not token:
        raise _unauthenticated(request)
    session = _get_session_raw(token)
    if not session:
        raise _unauthenticated(request)
    # 补齐向后兼容字段
    session.setdefault("role", ROLE_SUPER_ADMIN)
    refresh_session_ttl(token, session)
    return session


def _unauthenticated(request: Request) -> HTTPException:
    accept = request.headers.get("accept", "")
    is_api = "/api/admin/" in str(request.url.path)
    if is_api or "application/json" in accept:
        raise HTTPException(status_code=401, detail="未登录或会话已失效")
    raise HTTPException(status_code=401, detail="未登录或会话已失效")


async def get_current_admin(request: Request) -> dict[str, Any] | None:
    """非强制：若有有效 session 返回之，否则返回 None。"""
    token = request.cookies.get(SESSION_COOKIE)
    if not token:
        return None
    session = _get_session_raw(token)
    if session:
        session.setdefault("role", ROLE_SUPER_ADMIN)
        refresh_session_ttl(token, session)
        return session
    return None


class _PermissionDep:
    """FastAPI 依赖函数生成器：校验 session 是否具备指定权限标识。"""

    def __init__(self, perm: str, *, redirect_on_html: bool = True):
        self.perm = perm
        self.redirect_on_html = redirect_on_html

    async def __call__(self, session: dict = Depends(require_admin)) -> dict:
        role = session.get("role") or ROLE_SUPER_ADMIN
        if not has_permission(role, self.perm):
            raise HTTPException(status_code=403, detail={"code": 403, "msg": f"权限不足（缺少 {self.perm}）"})
        return session


def require_permission(request: Request, perm: str) -> dict:
    """在 handler 中主动调用：校验登录 + 具备指定权限；失败则抛 HTTPException(401/403)。

    用法（推荐在 API handler 中使用）：
        @router.get("/accounts")
        async def list_accounts(request: Request):
            session = require_permission(request, "btn.system.accounts")
            ...

    另一种用法（作为 Depends 装饰参数保留兼容）：
        @router.get("/accounts")
        async def list_accounts(session: dict = Depends(_PermissionDep("btn.system.accounts"))):
            ...
    """
    token = request.cookies.get(SESSION_COOKIE)
    if not token:
        raise HTTPException(status_code=401, detail="未登录")
    session = _get_session_raw(token)
    if not session:
        raise HTTPException(status_code=401, detail="会话已失效")
    session.setdefault("role", ROLE_SUPER_ADMIN)
    refresh_session_ttl(token, session)
    role = session.get("role") or ROLE_SUPER_ADMIN
    if not has_permission(role, perm):
        raise HTTPException(status_code=403, detail=f"权限不足（缺少 {perm}）")
    return session


def permission_depends(perm: str) -> Any:
    """返回 Depends 工厂（供 FastAPI 路径函数参数使用）。

    用法：
        @router.get("/accounts")
        async def list_accounts(session: dict = Depends(permission_depends("btn.system.accounts"))):
            ...
    """
    return Depends(_PermissionDep(perm))


# ---------------------------------------------------------------------------
# 登录处理
# ---------------------------------------------------------------------------
def handle_login_post(username: str, password: str, *, client_ip: str) -> tuple[bool, str, str, str]:
    """
    返回 (是否成功, session_token, 消息, 角色)。
    由调用方（pages.py）负责设置 Cookie。
    """
    if not username or not password:
        return False, "", "账号/密码不能为空", ""
    acc = lookup_account(username)
    if acc is None or acc.get("disabled"):
        logger.warning(f"web_admin login fail: unknown/disabled user {username} from {client_ip}")
        return False, "", "账号或密码错误", ""
    password_hash = acc.get("password_hash") or ""
    if not password_hash:
        logger.warning(f"web_admin: 账号 {username} 未配置密码哈希，禁止登录")
        return False, "", "管理员密码未配置", ""
    if not _verify_password(password, password_hash):
        logger.warning(f"web_admin login fail: wrong password for {username} from {client_ip}")
        return False, "", "账号或密码错误", ""
    token = create_session(username, role=acc["role"], client_ip=client_ip)
    return True, token, "登录成功", acc["role"]


# ---------------------------------------------------------------------------
# 导出 / 暴露给其他模块使用
# ---------------------------------------------------------------------------
__all__ = [
    "SESSION_COOKIE",
    "ROLE_SUPER_ADMIN",
    "ROLE_OPS",
    "ROLE_SALES",
    "ROLE_COMPLIANCE",
    "VALID_ROLES",
    "ROLE_LABELS",
    "ROLE_PERMISSIONS",
    "require_admin",
    "get_current_admin",
    "require_permission",
    "permission_depends",
    "has_permission",
    "is_super_admin",
    "role_can_view_menu",
    "get_permissions_for_role",
    "handle_login_post",
    "delete_session",
    "invalidate_user_sessions",
    "invalidate_account_sessions",
    "get_accounts",
    "lookup_account",
    "reload_accounts",
    "add_in_memory_account",
    "_verify_password",
    "_hash_password",
]
