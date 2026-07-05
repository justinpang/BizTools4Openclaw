"""web_admin/api/audit_enhanced — 增强版审计日志查询 + CSV 导出"""

from __future__ import annotations

import csv
import io
from datetime import datetime

from fastapi import Request, APIRouter, HTTPException

from web_admin.auth import require_permission
from web_admin.middleware import load_audit_logs_enhanced

router = APIRouter(prefix="/api/admin/audit_enhanced", tags=["admin-audit-enhanced"])


@router.get("/logs")
async def get_logs(request: Request,
                   role: str | None = None,
                   op_type: str | None = None,
                   keyword: str | None = None,
                   page: int = 1,
                   page_size: int = 20):
    """按角色/操作类型/关键字过滤的审计日志列表（分页）。

    权限：需要 btn.audit.view 或 super_admin。
    """
    require_permission(request, "btn.audit.view")

    result = load_audit_logs_enhanced(
        role=role,
        op_type=op_type,
        keyword=keyword,
        page=page,
        page_size=page_size,
    )
    return result


@router.get("/logs/export")
async def export_logs(request: Request,
                      role: str | None = None,
                      op_type: str | None = None,
                      keyword: str | None = None):
    """导出 CSV（使用 Content-Disposition 触发浏览器下载）。"""
    require_permission(request, "btn.audit.view")

    result = load_audit_logs_enhanced(
        role=role, op_type=op_type, keyword=keyword,
        page=1, page_size=2000,
    )

    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow(["ts", "datetime", "username", "role", "ip", "operation_type",
                     "path", "status", "latency_ms", "trace_id"])
    for e in result["items"]:
        ts = int(e.get("ts") or 0)
        try:
            dt = datetime.fromtimestamp(ts).strftime("%Y-%m-%d %H:%M:%S")
        except Exception:
            dt = ""
        writer.writerow([
            ts, dt,
            e.get("username") or "",
            e.get("role") or "",
            e.get("ip") or "",
            e.get("operation_type") or "",
            e.get("path") or "",
            e.get("status") or "",
            e.get("latency_ms") or 0,
            e.get("trace_id") or "",
        ])

    from fastapi.responses import PlainTextResponse
    filename = f"audit_logs_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv"
    return PlainTextResponse(
        buf.getvalue(),
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


__all__ = ["router"]
