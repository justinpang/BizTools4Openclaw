"""web_admin/main — web_admin 挂载入口（纯 HTML 页面 + API）。"""

from __future__ import annotations

import os

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from infra.logger_setup import get_logger
from web_admin.api import (
    audit_router,
    audit_enhanced_router,
    channels_router,
    dashboard_router,
    leads_router,
    sales_router,
    spider_router,
    accounts_router,
)
from web_admin.auth import get_current_admin
from web_admin.middleware import build_audit_middleware
from web_admin.pages import router as page_router

logger = get_logger("web_admin.main")


def mount_on(app: FastAPI) -> None:
    """把 Web 管理后台挂载到现有 FastAPI app。"""
    # 0) 静态文件（CSS/JS）— 先挂载静态文件，避免被 /admin 路由拦截
    static_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "static")
    if os.path.isdir(static_dir):
        app.mount("/admin/static", StaticFiles(directory=static_dir), name="admin-static")
        logger.info(f"web_admin: static files mounted from {static_dir}")
    else:
        logger.warning(f"web_admin: static directory not found: {static_dir}")

    # 1) API 路由（/api/admin/*）
    api_router = FastAPI(title="WebAdmin API")
    api_router.include_router(dashboard_router)
    api_router.include_router(spider_router)
    api_router.include_router(leads_router)
    api_router.include_router(channels_router)
    api_router.include_router(sales_router)
    api_router.include_router(audit_router)
    api_router.include_router(audit_enhanced_router)
    api_router.include_router(accounts_router)
    app.mount("/api/admin", api_router, name="admin-api")

    # 2) 页面路由（/admin/*）
    page_app = FastAPI(title="WebAdmin Pages")
    page_app.include_router(page_router)
    app.mount("/admin", page_app, name="admin-pages")

    # 3) 行为日志中间件（挂载到主 app，不重复挂载到子 app）
    # 注意：middleware 只在主 app 中通过 decorator 注册。这里 build_audit_middleware
    # 已由 adapter/main.py 通过 middleware decorator 注入。
    build_audit_middleware(get_current_admin)  # noqa: F401  预构建，避免延迟初始化

    logger.info("web_admin mounted: /admin/* and /api/admin/*")


__all__ = ["mount_on"]
