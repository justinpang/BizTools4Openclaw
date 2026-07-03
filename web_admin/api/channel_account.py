"""web_admin/api/channel_account — 渠道账号管理。"""

from __future__ import annotations

import json
import time

from fastapi import APIRouter, Depends, Form, HTTPException

from infra.logger_setup import get_logger
from infra.redis_client import get_redis
from web_admin.auth import require_admin

logger = get_logger("web_admin.channels")
router = APIRouter(tags=["admin"])

ACCOUNTS_KEY_PREFIX = "web_admin:accounts:"  # per-channel hash


def _load_pool():
    try:
        from core.send_core.account_pool import _build_default  # type: ignore
        return _build_default()
    except Exception:
        return None


def _mask_password(pwd: str) -> str:
    if not pwd:
        return ""
    return "********"


@router.get("/channels")
def list_channels_and_accounts(session: dict = Depends(require_admin)):
    data = []
    pool = _load_pool()
    channels = list(pool.channels() or []) if pool is not None else ["email", "wechat", "dingtalk", "feishu"]
    for ch in channels:
        accounts = []
        try:
            accounts_raw = list(pool.all_accounts(ch) or []) if pool is not None else []
            for a in accounts_raw:
                accounts.append({
                    "account_id": getattr(a, "account_id", ""),
                    "username": getattr(a, "username", ""),
                    "password": _mask_password(getattr(a, "password", "") or ""),
                    "status": "BANNED" if getattr(a, "is_banned", False) else "ACTIVE",
                    "today_sent": getattr(a, "today_sent", 0),
                    "quota": getattr(a, "default_quota", 500),
                })
        except Exception:
            accounts = []
        # 从 Redis 加载账号
        try:
            r = get_redis()
            if r is not None:
                extra = r.hgetall(ACCOUNTS_KEY_PREFIX + ch) or {}
                for acc_id, raw in extra.items():
                    try:
                        s = raw.decode("utf-8") if isinstance(raw, bytes) else str(raw)
                        d = json.loads(s)
                        d["account_id"] = acc_id.decode("utf-8") if isinstance(acc_id, bytes) else str(acc_id)
                        d["password"] = _mask_password(d.get("password", "") or "")
                        if not any(x["account_id"] == d["account_id"] for x in accounts):
                            accounts.append({
                                "account_id": d["account_id"],
                                "username": d.get("username", ""),
                                "password": "********",
                                "status": "ACTIVE",
                                "today_sent": 0,
                                "quota": int(d.get("quota", 500)),
                            })
                    except Exception:
                        continue
        except Exception:
            pass
        data.append({"channel": ch, "accounts": accounts, "count": len(accounts)})

    return {"code": 0, "msg": "ok", "data": data}


@router.post("/channels/account")
def create_or_update_account(
    channel: str = Form(...),
    account_id: str = Form(...),
    username: str = Form(default=""),
    password: str = Form(default=""),
    quota: int = Form(default=500),
    session: dict = Depends(require_admin),
):
    channel = (channel or "").strip() or "email"
    account_id = (account_id or "").strip() or f"{channel}_{int(time.time())}"
    if not password:
        raise HTTPException(status_code=400, detail="密码不能为空")
    # 密码哈希后存储
    try:
        import hashlib
        import base64
        salted = base64.b64encode(hashlib.sha256(password.encode("utf-8")).digest()).decode("ascii")
        payload = {
            "account_id": account_id,
            "channel": channel,
            "username": username or account_id,
            "password": "salted_sha256:" + salted,  # 非明文
            "quota": int(quota or 500),
            "created_by": session.get("username", ""),
            "created_at": int(time.time()),
        }
    except Exception:
        payload = {
            "account_id": account_id,
            "channel": channel,
            "username": username or account_id,
            "password": "***",
            "quota": int(quota or 500),
            "created_by": session.get("username", ""),
            "created_at": int(time.time()),
        }
    # Redis 持久化
    try:
        r = get_redis()
        if r is not None:
            r.hset(ACCOUNTS_KEY_PREFIX + channel,
                   mapping={account_id: json.dumps(payload, ensure_ascii=False)})
    except Exception:
        pass
    # 尝试注册到 AccountPool（如果 pool 支持动态 register_account）
    try:
        pool = _load_pool()
        if pool is not None and hasattr(pool, "register_account"):
            from core.send_core.account_pool import Account  # type: ignore
            try:
                acc = Account(account_id=account_id, username=payload["username"],
                              password=password, default_quota=payload["quota"])
                pool.register_account(acc)
            except Exception:
                pass
    except Exception:
        pass
    payload["password"] = "********"
    return {"code": 0, "msg": "ok", "account": payload}


@router.post("/channels/{channel}/ban/{account_id}")
def ban_account(channel: str, account_id: str, session: dict = Depends(require_admin)):
    try:
        pool = _load_pool()
        if pool is not None and hasattr(pool, "mark_banned"):
            pool.mark_banned(channel, account_id, reason="web_admin 手动封禁", cooldown_seconds=3600)
    except Exception:
        pass
    return {"code": 0, "msg": "banned"}


@router.post("/channels/{channel}/unban/{account_id}")
def unban_account(channel: str, account_id: str, session: dict = Depends(require_admin)):
    try:
        pool = _load_pool()
        if pool is not None and hasattr(pool, "unban"):
            pool.unban(channel, account_id)
    except Exception:
        pass
    return {"code": 0, "msg": "unbanned"}


__all__ = ["router"]
