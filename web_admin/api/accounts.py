"""web_admin/api/accounts — 账号管理：查询 / 创建 / 重置密码 / 启用禁用

注意：账号配置从 .env 读取（WEB_ADMIN_ACCOUNTS_JSON 或单账号模式），
      密码哈希在 auth.py 中已统一处理，本文件仅暴露受权限保护的操作层。
"""

from __future__ import annotations

import secrets
import string
import time
from typing import Optional

from fastapi import Request, APIRouter, HTTPException, Form

from web_admin.auth import (
    require_permission,
    get_accounts,
    add_in_memory_account,
    invalidate_account_sessions,
    is_super_admin,
)
from web_admin.middleware import log_audit_event

router = APIRouter(prefix="/api/admin/accounts", tags=["admin-accounts"])


def _extract_ip(request: Request) -> str:
    try:
        client = getattr(request, "client", None)
        return client.host if client and client.host else ""
    except Exception:
        return ""


def _gen_random_password(length: int = 14) -> str:
    alphabet = string.ascii_letters + string.digits + "-_"
    return "".join(secrets.choice(alphabet) for _ in range(length))


def _session_user(request: Request):
    session = getattr(request.state, "session", None)
    if not isinstance(session, dict):
        raise HTTPException(status_code=401, detail="未登录")
    return session


@router.get("")
async def list_accounts(request: Request):
    """列出账号（脱敏密码，仅 super_admin / 有权限者可看）。"""
    require_permission(request, "btn.system.accounts")
    session = _session_user(request)
    accounts = get_accounts()
    result = []
    for username, rec in accounts.items():
        result.append({
            "username": username,
            "role": rec.get("role", "ops"),
            "disabled": bool(rec.get("disabled")),
            "created_at": int(rec.get("created_at", 0)),
        })
    return {
        "code": 0,
        "items": result,
        "total": len(result),
        "viewer": {"username": session.get("username"), "role": session.get("role")},
    }


@router.post("")
async def create_account(request: Request,
                         username: str = Form(...),
                         role: str = Form(default="ops"),
                         disabled: str = Form(default="0")):
    """创建新账号（仅 super_admin）。

    后端会生成随机密码并明文返回一次，前端负责展示并提示用户记录。
    """
    require_permission(request, "btn.system.accounts")
    session = _session_user(request)

    username = (username or "").strip()
    if len(username) < 3:
        raise HTTPException(status_code=400, detail="账号名至少 3 个字符")
    if role not in {"super_admin", "ops", "sales", "compliance"}:
        raise HTTPException(status_code=400, detail="角色不合法")

    accounts = get_accounts()
    if username in accounts:
        raise HTTPException(status_code=409, detail="账号已存在")

    password_plain = _gen_random_password()
    ok = add_in_memory_account(username, password_plain, role=role, disabled=(disabled == "1"))
    if not ok:
        raise HTTPException(status_code=500, detail="账号系统未启用动态创建（仅支持 .env JSON 模式）")

    log_audit_event(
        username=session.get("username", ""),
        role=session.get("role", ""),
        operation_type="accounts.create",
        action_detail=f"创建账号 {username}（role={role}）",
        ip=_extract_ip(request),
        status=200,
        path="/api/admin/accounts",
    )

    return {
        "code": 0,
        "msg": "创建成功",
        "username": username,
        "role": role,
        "password_plain": password_plain,
    }


@router.put("/{username}")
async def update_account(request: Request, username: str,
                         role: Optional[str] = Form(default=None),
                         disabled: Optional[str] = Form(default=None)):
    """修改账号的 role / 启用禁用（仅 super_admin）。"""
    require_permission(request, "btn.system.accounts")
    session = _session_user(request)

    accounts = get_accounts()
    if username not in accounts:
        raise HTTPException(status_code=404, detail="账号不存在")

    rec = accounts[username]
    if role is not None:
        if role not in {"super_admin", "ops", "sales", "compliance"}:
            raise HTTPException(status_code=400, detail="角色不合法")
        rec["role"] = role
    if disabled is not None:
        new_disabled = (disabled == "1")
        if rec.get("disabled") != new_disabled:
            rec["disabled"] = new_disabled
            if new_disabled:
                # 禁用后：下线所有已登录会话
                invalidate_account_sessions(username)

    log_audit_event(
        username=session.get("username", ""),
        role=session.get("role", ""),
        operation_type="accounts.update",
        action_detail=f"更新账号 {username}（role={rec.get('role')}, disabled={rec.get('disabled')}）",
        ip=_extract_ip(request),
        status=200,
        path="/api/admin/accounts/" + username,
    )
    return {"code": 0, "msg": "ok", "username": username,
            "role": rec.get("role"), "disabled": bool(rec.get("disabled"))}


@router.post("/{username}/reset_password")
async def reset_password(request: Request, username: str):
    """重置账号密码（需 btn.system.reset_password 权限）。"""
    require_permission(request, "btn.system.reset_password")
    session = _session_user(request)

    accounts = get_accounts()
    if username not in accounts:
        raise HTTPException(status_code=404, detail="账号不存在")

    rec = accounts[username]
    new_password = _gen_random_password()
    # 通过重新走一遍 hash 添加逻辑：在进程内 accounts dict 上覆盖 password_hash
    try:
        from web_admin.auth import _hash_password  # type: ignore
        rec["password_hash"] = _hash_password(new_password)
        rec["updated_at"] = int(time.time())
        # 重置后让原会话失效
        invalidate_account_sessions(username)
    except Exception:
        raise HTTPException(status_code=500, detail="密码 hash 函数不可用")

    log_audit_event(
        username=session.get("username", ""),
        role=session.get("role", ""),
        operation_type="accounts.reset_password",
        action_detail=f"重置账号 {username} 的密码",
        ip=_extract_ip(request),
        status=200,
        path="/api/admin/accounts/" + username + "/reset_password",
    )

    return {
        "code": 0,
        "msg": "密码已重置，请将以下一次性随机密码告知用户",
        "username": username,
        "password_plain": new_password,
    }


__all__ = ["router"]
