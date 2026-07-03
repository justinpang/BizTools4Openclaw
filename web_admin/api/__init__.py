"""web_admin/api — 聚合 API routers。"""

from __future__ import annotations

from web_admin.api.dashboard import router as dashboard_router
from web_admin.api.spider_task import router as spider_router
from web_admin.api.lead_mgmt import router as leads_router
from web_admin.api.channel_account import router as channels_router
from web_admin.api.sales_mgmt import router as sales_router
from web_admin.api.audit_log import router as audit_router

__all__ = [
    "dashboard_router",
    "spider_router",
    "leads_router",
    "channels_router",
    "sales_router",
    "audit_router",
]
