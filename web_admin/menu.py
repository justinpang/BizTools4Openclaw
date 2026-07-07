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
            {"key": "dashboard", "title": "总览仪表板", "href": "/admin/dashboard", "icon": "📊",
             "roles": {"super_admin", "ops", "sales", "compliance"}},
            {"key": "data_center_dashboard", "title": "全链路看板", "href": "/admin/data_center/dashboard", "icon": "📈",
             "roles": {"super_admin", "ops", "sales", "compliance"}},
            {"key": "data_center_collection", "title": "采集阶段", "href": "/admin/data_center/collection", "icon": "🕷",
             "roles": {"super_admin", "ops"}},
            {"key": "data_center_cleaning", "title": "清洗结构化", "href": "/admin/data_center/cleaning", "icon": "🧹",
             "roles": {"super_admin", "ops", "compliance"}},
            {"key": "data_center_compliance", "title": "合规校验", "href": "/admin/data_center/compliance", "icon": "🛡",
             "roles": {"super_admin", "compliance"}},
            {"key": "data_center_grading", "title": "商机分级", "href": "/admin/data_center/grading", "icon": "🏆",
             "roles": {"super_admin", "sales"}},
            {"key": "data_center_outreach", "title": "客户触达", "href": "/admin/data_center/outreach", "icon": "📡",
             "roles": {"super_admin", "sales"}},
            {"key": "data_center_sales", "title": "销售闭环", "href": "/admin/data_center/sales", "icon": "💰",
             "roles": {"super_admin", "sales"}},
            {"key": "data_center_exception", "title": "异常数据池", "href": "/admin/data_center/exception", "icon": "⚠",
             "roles": {"super_admin", "ops", "compliance", "sales"}},
            {"key": "data_center_channel_funnel", "title": "分渠道漏斗", "href": "/admin/data_center/channel-funnel", "icon": "📊",
             "roles": {"super_admin", "ops", "sales"}},
            {"key": "data_center_batch", "title": "批量操作中心", "href": "/admin/data_center/batch", "icon": "⚙",
             "roles": {"super_admin", "ops", "compliance", "sales"}},
            {"key": "data_center_export", "title": "数据导出中心", "href": "/admin/data_center/export", "icon": "📤",
             "roles": {"super_admin", "ops", "compliance", "sales"}},
        ],
    },
    {
        "group_key": "collection",
        "title": "采集管理",
        "icon": "🕸",
        "items": [
            {"key": "spider", "title": "爬虫任务", "href": "/admin/spider", "icon": "🕷",
             "roles": {"super_admin", "ops"}},
            {"key": "spider_generic", "title": "通用网页/论坛", "href": "/admin/spider?channel=generic_web", "icon": "🌐",
             "roles": {"super_admin", "ops"}},
            {"key": "spider_video", "title": "短视频", "href": "/admin/spider?channel=short_video", "icon": "🎬",
             "roles": {"super_admin", "ops"}},
            {"key": "spider_xhs", "title": "小红书", "href": "/admin/spider?channel=xhs", "icon": "📕",
             "roles": {"super_admin", "ops"}},
            {"key": "spider_qa", "title": "问答平台", "href": "/admin/spider?channel=qa_platform", "icon": "❓",
             "roles": {"super_admin", "ops"}},
            {"key": "spider_b2b", "title": "供需B2B", "href": "/admin/spider?channel=b2b_supply", "icon": "🏭",
             "roles": {"super_admin", "ops"}},
            {"key": "spider_bidding", "title": "招投标", "href": "/admin/spider?channel=bidding", "icon": "📋",
             "roles": {"super_admin", "ops"}},
            {"key": "spider_company", "title": "企业工商", "href": "/admin/spider?channel=company_biz", "icon": "🏢",
             "roles": {"super_admin", "ops"}},
            {"key": "crawl_plans", "title": "📂 采集方案管理", "href": "/admin/crawl/plans", "icon": "📂",
             "roles": {"super_admin", "ops"}},
            {"key": "crawl_editor", "title": "🎨 可视化配置编辑器", "href": "/admin/crawl/editor", "icon": "🎨",
             "roles": {"super_admin", "ops"}},
            {"key": "crawl_monitor", "title": "📊 采集任务监控", "href": "/admin/crawl/monitor", "icon": "📊",
             "roles": {"super_admin", "ops"}},
            {"key": "crawl_fields", "title": "🏷 字段模板库", "href": "/admin/crawl/fields", "icon": "🏷",
             "roles": {"super_admin", "ops"}},
        ],
    },
    {
        "group_key": "compliance",
        "title": "合规审核",
        "icon": "🛡",
        "items": [
            {"key": "compliance_review", "title": "任务审核", "href": "/admin/compliance/review", "icon": "✅",
             "roles": {"super_admin", "compliance"}},
            {"key": "compliance_pending", "title": "待审核列表", "href": "/admin/compliance/review?tab=pending", "icon": "⏳",
             "roles": {"super_admin", "compliance"}},
            {"key": "compliance_history", "title": "审核记录", "href": "/admin/compliance/review?tab=history", "icon": "📋",
             "roles": {"super_admin", "compliance"}},
            {"key": "compliance_config", "title": "审核规则配置", "href": "/admin/compliance/config", "icon": "⚙",
             "roles": {"super_admin"}},
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
            {"key": "notifications", "title": "消息中心", "href": "/admin/notifications", "icon": "🔔",
             "roles": {"super_admin", "ops", "sales", "compliance"}},
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
