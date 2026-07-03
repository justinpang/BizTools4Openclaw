"""web_admin/api/audit_log — 操作日志查询。"""

from __future__ import annotations

from fastapi import APIRouter, Depends

from web_admin.auth import require_admin
from web_admin.middleware import load_audit_logs

router = APIRouter(tags=["admin"])


@router.get("/audit/logs")
def audit_logs(limit: int = 50, session: dict = Depends(require_admin)):
    items = load_audit_logs(limit=min(max(int(limit), 1), 500))
    return {"code": 0, "msg": "ok", "items": items, "total": len(items)}


__all__ = ["router"]
