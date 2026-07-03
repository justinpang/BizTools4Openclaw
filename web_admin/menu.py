"""web_admin/menu — 左侧导航菜单常量。"""

from __future__ import annotations

MENU: list[dict[str, str]] = [
    {"key": "dashboard", "title": "数据看板",   "icon": "📊", "href": "/admin/dashboard"},
    {"key": "spider",    "title": "爬虫任务",   "icon": "🕷", "href": "/admin/spider"},
    {"key": "leads",     "title": "商机线索",   "icon": "💼", "href": "/admin/leads"},
    {"key": "channels",  "title": "渠道账号",   "icon": "📡", "href": "/admin/channels"},
    {"key": "sales",     "title": "销售管理",   "icon": "👥", "href": "/admin/sales"},
    {"key": "audit_log", "title": "操作日志",   "icon": "📜", "href": "/admin/audit_log"},
]


__all__ = ["MENU"]
