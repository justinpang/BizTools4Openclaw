"""web_admin/menu — 分组菜单结构 + 权限过滤（四级角色体系）。"""

from __future__ import annotations

from infra.logger_setup import get_logger

logger = get_logger("web_admin.menu")


# ---------------------------------------------------------------------------
# 分组菜单结构（每个 item.roles 是该菜单项允许访问的角色集合）
# 说明：group_key 用于菜单分组，item.key 用于 breadcrumb + 权限判定 + layout active
# ---------------------------------------------------------------------------
MENU_GROUPS: list[dict] = [
    {
        "group_key": "data_center",
        "title": "数据中心",
        "icon": "🗂",
        "items": [
            {"key": "dashboard", "title": "数据看板",  "href": "/admin/dashboard", "icon": "📊",
             "roles": {"super_admin", "ops", "sales", "compliance"}},
        ],
    },
    {
        "group_key": "collection",
        "title": "采集管理",
        "icon": "�",
        "items": [
            {"key": "spider", "title": "爬虫任务", "href": "/admin/spider", "icon": "🕷",
             "roles": {"super_admin", "ops"}},
        ],
    },
    {
        "group_key": "opportunity",
        "title": "商机管理",
        "icon": "💼",
        "items": [
            {"key": "leads", "title": "商机线索", "href": "/admin/leads", "icon": "🧾",
             "roles": {"super_admin", "sales"}},
        ],
    },
    {
        "group_key": "outreach",
        "title": "触达管理",
        "icon": "📡",
        "items": [
            {"key": "channels", "title": "渠道账号", "href": "/admin/channels", "icon": "�",
             "roles": {"super_admin", "compliance"}},
        ],
    },
    {
        "group_key": "sales",
        "title": "销售管理",
        "icon": "👥",
        "items": [
            {"key": "sales", "title": "销售分配", "href": "/admin/sales", "icon": "🗒",
             "roles": {"super_admin", "sales"}},
        ],
    },
    {
        "group_key": "system",
        "title": "系统设置",
        "icon": "⚙",
        "items": [
            {"key": "audit_log", "title": "操作日志", "href": "/admin/audit_log", "icon": "📜",
             "roles": {"super_admin", "ops", "compliance"}},
            {"key": "accounts",  "title": "账号管理", "href": "/admin/system/accounts", "icon": "👤",
             "roles": {"super_admin"}},
        ],
    },
]


# 向后兼容扁平 MENU 导出（保留 key/title/href/icon 字段）
MENU: list[dict] = [
    {"key": it["key"], "title": it["title"], "href": it["href"], "icon": it.get("icon", "·")}
    for g in MENU_GROUPS
    for it in g["items"]
]


def filter_menu_by_role(role: str) -> list[dict]:
    """返回对指定角色可见的 MENU_GROUPS（分组结构不变，但过滤子菜单）。"""
    result: list[dict] = []
    for g in MENU_GROUPS:
        visible_items = [it for it in g["items"] if role in it.get("roles", set())]
        if visible_items:
            result.append({
                "group_key": g["group_key"],
                "title": g["title"],
                "icon": g.get("icon", ""),
                "items": [
                    {
                        "key": it["key"],
                        "title": it["title"],
                        "href": it["href"],
                        "icon": it.get("icon", ""),
                    }
                    for it in visible_items
                ],
            })
    return result


def breadcrumb_for(active_key: str) -> list[dict]:
    """根据 active_key 反推面包屑：[{"title": "分组名"}, {"title": "子菜单项", "href": "..."}]。"""
    for g in MENU_GROUPS:
        for it in g["items"]:
            if it["key"] == active_key:
                return [{"title": g["title"]}, {"title": it["title"], "href": it["href"]}]
    return [{"title": "后台"}]


def default_href_for_role(role: str) -> str:
    """角色登录后的默认跳转页面（优先使用该角色可见的第一个菜单项）。"""
    for g in filter_menu_by_role(role):
        if g["items"]:
            return g["items"][0]["href"]
    return "/admin/dashboard"


__all__ = [
    "MENU_GROUPS",
    "MENU",
    "filter_menu_by_role",
    "breadcrumb_for",
    "default_href_for_role",
]
