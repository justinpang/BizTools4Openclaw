# -*- coding: utf-8 -*-
"""web_admin/pages - HTML page routing (new grouped layout + permission-controlled HTML pages)."""

from __future__ import annotations

import json
import os
from pathlib import Path

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse

from web_admin.auth import (
    ROLE_LABELS,
    ROLE_SUPER_ADMIN,
    SESSION_COOKIE,
    delete_session,
    get_current_admin,
    get_permissions_for_role,
    handle_login_post,
    has_permission,
    role_can_view_menu,
)
from web_admin.menu import (
    breadcrumb_for,
    default_href_for_role,
    filter_menu_by_role,
)
from configs.settings import settings

router = APIRouter(tags=["admin-pages"])


# ---------------------------------------------------------------------------
# Helper: render new layout (top bar + left group menu + main content area)
# ---------------------------------------------------------------------------
def _layout_v2(title: str, active_key: str, body_html: str, session: dict | None) -> str:
    """New layout (called by all internal pages)."""
    username = session.get("username", "admin") if session else "guest"
    role = (session.get("role") or ROLE_SUPER_ADMIN) if session else ROLE_SUPER_ADMIN
    role_label = ROLE_LABELS.get(role, role)

    # 1) Menu: filter by role
    menu_groups = filter_menu_by_role(role) if session else []

    # 2) Breadcrumb
    crumbs = breadcrumb_for(active_key)

    # 3) Permission set (used by frontend to filter buttons)
    perms = sorted(get_permissions_for_role(role)) if session else []

    # 4) Inject bootstrap JSON
    init_json = json.dumps({
        "username": username,
        "role": role,
        "roleLabel": role_label,
        "permissions": perms,
        "activeKey": active_key,
        "menuGroups": menu_groups,
        "breadcrumbs": crumbs,
        "pageTitle": title,
    }, ensure_ascii=False)

    # Render left-side group menu HTML
    sidebar_html = ""
    for g in menu_groups:
        items_html = ""
        for it in g["items"]:
            active_cls = " active" if it["key"] == active_key else ""
            items_html += (
                '<a class="menu-item' + active_cls + '" href="' + it["href"] + '" data-key="' + it["key"] + '">'
                '<span class="menu-item-icon">' + it.get("icon", "") + '</span>'
                '<span class="menu-item-title">' + it["title"] + '</span>'
                '</a>'
            )
        if items_html:
            # 菜单分组支持折叠：group-collapsed 类表示折叠状态
            sidebar_html += (
                '<div class="menu-group" data-group="' + g["group_key"] + '">'
                '<div class="menu-group-title" onclick="admin.toggleMenuGroup(\'' + g["group_key"] + '\')">'
                '<span class="menu-group-icon">' + g.get("icon", "") + '</span>'
                '<span>' + g["title"] + '</span>'
                '<span class="menu-group-toggle">▾</span>'
                '</div>'
                '<div class="menu-group-items">' + items_html + '</div>'
                '</div>'
            )

    # Breadcrumb HTML
    crumbs_html = " / ".join(
        ('<a class="crumb-link" href="' + c.get("href", "#") + '">' + c["title"] + '</a>' if c.get("href") else '<span class="crumb">' + c["title"] + '</span>')
        for c in crumbs
    )

    # Top bar right: role tag + username + logout
    user_zone_html = (
        '<span class="role-tag role-' + role + '">' + role_label + '</span>'
        '<span class="user-name">' + username + '</span>'
        '<form method="POST" action="/admin/logout" class="logout-form" style="display:inline;margin-left:8px;">'
        '<button type="submit" class="btn btn-sm">退出登录</button>'
        '</form>'
    )

    return (
        '<!doctype html>\n'
        '<html lang="zh-CN">\n'
        '<head>\n'
        '<meta charset="utf-8"/>\n'
        '<meta name="viewport" content="width=device-width,initial-scale=1"/>\n'
        '<meta http-equiv="Cache-Control" content="no-cache, no-store, must-revalidate"/>\n'
        '<meta http-equiv="Pragma" content="no-cache"/>\n'
        '<meta http-equiv="Expires" content="0"/>\n'
        '<title>' + title + ' · BizTools4Openclaw 管理后台</title>\n'
        '<link rel="stylesheet" href="/admin/static/css/admin.css?v=t33"/>\n'
        '</head>\n'
        '<body class="page-v2 page-' + active_key + '">\n'
        '  <div class="layout-v2">\n'
        '    <aside class="sidebar-v2" id="sidebar">\n'
        '      <div class="brand-v2">BizTools4Openclaw</div>\n'
        '      <div class="sidebar-inner" id="sidebar-inner">' + sidebar_html + '</div>\n'
        '    </aside>\n'
        '    <main class="content-v2">\n'
        '      <header class="topbar-v2">\n'
        '        <div class="breadcrumb" id="breadcrumb">' + crumbs_html + '</div>\n'
        '        <div class="topbar-right">\n'
        '          <input class="global-search" id="global-search" type="text" placeholder="搜索菜单（按回车）"/>\n'
        '          <div class="user-area-v2">' + user_zone_html + '</div>\n'
        '        </div>\n'
        '      </header>\n'
        '      <section class="page-title-section">\n'
        '        <h1 class="page-title">' + title + '</h1>\n'
        '      </section>\n'
        '      <section class="page-body">\n'
        '        ' + body_html + '\n'
        '      </section>\n'
        # T22: 全局手工操作弹窗
        '      <div class="manual-dialog-mask" id="manual-dialog-mask" style="display:none;">\n'
        '        <div class="manual-dialog" id="manual-dialog">\n'
        '          <div class="manual-dialog-head"><span id="manual-dialog-title">操作确认</span><span class="manual-dialog-close" onclick="admin.closeManualDialog()">x</span></div>\n'
        '          <div class="manual-dialog-body" id="manual-dialog-body"></div>\n'
        '          <div class="manual-dialog-foot">\n'
        '            <button class="btn" onclick="admin.closeManualDialog()">取消</button>\n'
        '            <button class="btn btn-primary" id="manual-dialog-submit" onclick="admin.submitManualDialog()">确认执行</button>\n'
        '          </div>\n'
        '        </div>\n'
        '      </div>\n'
        # T22: toast 通知浮层
        '      <div class="manual-toast" id="manual-toast" style="display:none;"></div>\n'
        '    </main>\n'
        '  </div>\n'
        '<script id="admin-init-json" type="application/json">' + init_json + '</script>\n'
        '<script src="/admin/static/js/admin.js?v=t33"></script>\n'
        '</body>\n'
        '</html>\n'
    )


# ---------------------------------------------------------------------------
# Login / Logout
# ---------------------------------------------------------------------------
def _login_page_html(error_msg: str | None = None) -> str:
    err = '<div class="login-error">' + error_msg + '</div>' if error_msg else ""
    return (
        '<!doctype html>\n'
        '<html lang="zh-CN">\n'
        '<head>\n'
        '<meta charset="utf-8"/>\n'
        '<meta name="viewport" content="width=device-width,initial-scale=1"/>\n'
        '<title>登录 · BizTools4Openclaw 管理后台</title>\n'
        '<link rel="stylesheet" href="/admin/static/css/admin.css"/>\n'
        '</head>\n'
        '<body class="login-body">\n'
        '  <div class="login-card">\n'
        '    <h1>🔒 管理后台登录</h1>\n'
        '    <p class="hint">账号 / 密码 由运维配置在 .env 中。可见菜单随角色变化。</p>\n'
        '    ' + err + '\n'
        '    <form method="POST" action="/admin/login" class="login-form">\n'
        '      <label>账号\n'
        '        <input type="text" name="username" required autocomplete="username" placeholder="请输入用户名"/>\n'
        '      </label>\n'
        '      <label>密码\n'
        '        <input type="password" name="password" required autocomplete="current-password" placeholder="请输入密码"/>\n'
        '      </label>\n'
        '      <button type="submit" class="btn btn-primary">登 录</button>\n'
        '    </form>\n'
        '    <p class="footer">&copy; BizTools4Openclaw \u00b7 会话已加密存储，自动过期</p>\n'
        '  </div>\n'
        '</body>\n'
        '</html>\n'
    )


@router.get("/")
def admin_root():
    return RedirectResponse(url="/admin/login", status_code=302)


@router.get("/login", response_class=HTMLResponse)
def login_page():
    return HTMLResponse(_login_page_html())


@router.post("/login")
def login_submit(request: Request, username: str = Form(...), password: str = Form(...)):
    client_ip = ""
    try:
        client = getattr(request, "client", None)
        client_ip = client.host if client and client.host else ""
    except Exception:
        pass
    ok, token, msg, role = handle_login_post(username, password, client_ip=client_ip)
    if not ok:
        return HTMLResponse(_login_page_html(msg))
    resp = RedirectResponse(url=default_href_for_role(role or ROLE_SUPER_ADMIN), status_code=302)
    ttl = int(settings.web_admin.WEB_ADMIN_SESSION_TTL_SECONDS or 3600)
    resp.set_cookie(SESSION_COOKIE, token, max_age=ttl, path="/", httponly=True, samesite="lax")
    return resp


@router.post("/logout")
def logout(request: Request):
    token = request.cookies.get(SESSION_COOKIE)
    if token:
        delete_session(token)
    resp = RedirectResponse(url="/admin/login", status_code=302)
    resp.delete_cookie(SESSION_COOKIE)
    return resp


# ---------------------------------------------------------------------------
# Page rendering helper: unified permission check + template render
# ---------------------------------------------------------------------------
def _render_with_permission(active_key: str, perm: str, body_html: str, session: dict | None) -> HTMLResponse:
    """Check page permission; render 403 if insufficient."""
    if not session:
        return RedirectResponse(url="/admin/login", status_code=302)
    role = session.get("role") or ROLE_SUPER_ADMIN
    if not has_permission(role, perm) or not role_can_view_menu(role, active_key):
        forbidden_body = _forbidden_body(active_key, missing_perm=perm)
        return HTMLResponse(_layout_v2("权限不足", "403", forbidden_body, session))
    return HTMLResponse(_layout_v2(_page_title(active_key), active_key, body_html, session))


def _page_title(active_key: str) -> str:
    """Return page title from active_key."""
    map_ = {
        "dashboard": "仪表板",
        "spider": "爬虫任务",
        "spider_detail": "任务详情",
        "leads": "商机线索",
        "channels": "渠道账号",
        "sales": "销售分配",
        "audit_log": "操作日志",
        "accounts": "账号管理",
        "compliance_review": "合规审核",
        "compliance_config": "合规规则配置",
        "notifications": "消息中心",
        "data_center_dashboard": "全链路漏斗看板",
        "data_center_collection": "采集阶段",
        "data_center_cleaning": "清洗结构化",
        "data_center_compliance": "合规校验",
        "data_center_grading": "商机分级",
        "data_center_outreach": "客户触达",
        "data_center_sales": "销售闭环",
        "data_center_opportunity": "商机时间线",
        "crawl_steps_editor": "可视化采集配置编辑器",
        "empty": "空状态演示",
        "403": "权限不足",
    }
    return map_.get(active_key, "管理后台")


def _forbidden_body(active_key: str, missing_perm: str) -> str:
    return (
        '<div class="empty-state">\n'
        '  <div class="empty-state-icon">🚫</div>\n'
        '  <div class="empty-state-title">权限不足</div>\n'
        '  <div class="empty-state-desc">\n'
        '    当前角色无权访问此页面 (<code>' + active_key + '</code>, 缺少权限\n'
        '    <code>' + missing_perm + '</code>). 请联系超级管理员开通.\n'
        '  </div>\n'
        '  <div class="empty-state-actions">\n'
        '    <a class="btn btn-primary" href="/admin/dashboard">返回仪表板</a>\n'
        '  </div>\n'
        '</div>\n'
    )


# ---------------------------------------------------------------------------
# Business pages (keep body_html minimal; actual features rendered by frontend JS)
# ---------------------------------------------------------------------------
@router.get("/dashboard", response_class=HTMLResponse)
def dashboard_page(session: dict | None = Depends(get_current_admin)):
    body = (
        '<section class="stats-grid" id="stats-grid">\n'
        '  <div class="stat-card"><div class="label">爬虫任务数</div><div class="value" data-key="spider_tasks">-</div></div>\n'
        '  <div class="stat-card"><div class="label">累计抓取</div><div class="value" data-key="crawled_total">-</div></div>\n'
        '  <div class="stat-card"><div class="label">有效商机</div><div class="value" data-key="leads_total">-</div></div>\n'
        '  <div class="stat-card"><div class="label">触达批次</div><div class="value" data-key="send_total">-</div></div>\n'
        '  <div class="stat-card"><div class="label">渠道账号数</div><div class="value" data-key="accounts_total">-</div></div>\n'
        '</section>\n'
        '<section class="panel">\n'
        '  <h3>📊 销售转化漏斗</h3>\n'
        '  <div id="funnel-area" class="funnel-area"><div class="empty-inline">暂无数据</div></div>\n'
        '</section>\n'
        '<section class="panel">\n'
        '  <h3>🕒 最近调度任务</h3>\n'
        '  <div id="recent-tasks"><div class="empty-inline">暂无数据</div></div>\n'
        '</section>\n'
    )
    return _render_with_permission("dashboard", "btn.dashboard.view", body, session)


@router.get("/spider", response_class=HTMLResponse)
def spider_page(session: dict | None = Depends(get_current_admin)):
    body = (
        '<section class="panel channel-filter-row">\n'
        '  <h3>📁 七渠道快速入口</h3>\n'
        '  <div class="channel-cards" id="channel-cards">\n'
        '    <a class="channel-card" data-channel="generic_web" href="/admin/spider?channel=generic_web">\n'
        '      <span class="channel-icon">🌐</span>\n'
        '      <span class="channel-title">通用网页/论坛</span>\n'
        '      <span class="channel-desc">门户/论坛/BBS采集</span>\n'
        '    </a>\n'
        '    <a class="channel-card" data-channel="short_video" href="/admin/spider?channel=short_video">\n'
        '      <span class="channel-icon">🎬</span>\n'
        '      <span class="channel-title">短视频</span>\n'
        '      <span class="channel-desc">抖音/快手/视频号</span>\n'
        '    </a>\n'
        '    <a class="channel-card" data-channel="xhs" href="/admin/spider?channel=xhs">\n'
        '      <span class="channel-icon">📕</span>\n'
        '      <span class="channel-title">小红书</span>\n'
        '      <span class="channel-desc">笔记/视频/点赞筛选</span>\n'
        '    </a>\n'
        '    <a class="channel-card" data-channel="qa_platform" href="/admin/spider?channel=qa_platform">\n'
        '      <span class="channel-icon">❓</span>\n'
        '      <span class="channel-title">问答平台</span>\n'
        '      <span class="channel-desc">知乎/百度知道</span>\n'
        '    </a>\n'
        '    <a class="channel-card" data-channel="b2b_supply" href="/admin/spider?channel=b2b_supply">\n'
        '      <span class="channel-icon">🏭</span>\n'
        '      <span class="channel-title">供需B2B</span>\n'
        '      <span class="channel-desc">阿里巴巴/慧聪网</span>\n'
        '    </a>\n'
        '    <a class="channel-card" data-channel="bidding" href="/admin/spider?channel=bidding">\n'
        '      <span class="channel-icon">📋</span>\n'
        '      <span class="channel-title">招投标</span>\n'
        '      <span class="channel-desc">政府/企业采购平台</span>\n'
        '    </a>\n'
        '    <a class="channel-card" data-channel="company_biz" href="/admin/spider?channel=company_biz">\n'
        '      <span class="channel-icon">🏢</span>\n'
        '      <span class="channel-title">企业工商</span>\n'
        '      <span class="channel-desc">企查查/天眼查/行业信息披露</span>\n'
        '    </a>\n'
        '  </div>\n'
        '</section>\n'
        '<section class="panel">\n'
        '  <h3>➕ 新建采集任务</h3>\n'
        '  <div class="row">\n'
        '    <label>渠道类型 <select id="task-channel-select" name="channel" data-requires-permission="btn.spider.create">\n'
        '      <option value="">请选择渠道</option>\n'
        '      <option value="generic_web">通用网页/论坛</option>\n'
        '      <option value="short_video">短视频</option>\n'
        '      <option value="xhs">小红书</option>\n'
        '      <option value="qa_platform">问答平台</option>\n'
        '      <option value="b2b_supply">供需B2B</option>\n'
        '      <option value="bidding">招投标</option>\n'
        '      <option value="company_biz">企业工商</option>\n'
        '    </select></label>\n'
        '  </div>\n'
        '  <form class="row-form" id="task-create-form" data-requires-permission="btn.spider.create" onsubmit="return admin.createSpiderTask(event)">\n'
        '    <input type="hidden" name="channel" id="task-channel-hidden"/>\n'
        '    <label>任务ID <input type="text" name="job_id" placeholder="例如 sp_daily_001"/></label>\n'
        '    <label>任务名称 <input type="text" name="task_name" placeholder="任务描述"/></label>\n'
        '    <label>速度等级(1-5) <input type="number" name="speed_level" value="3" min="1" max="5"/></label>\n'
        '    <label>抓取上限 <input type="number" name="max_items" value="500" min="1"/></label>\n'
        '    <label>调度模式 <select name="schedule_mode"><option value="off">手动</option><option value="hourly">每小时</option><option value="daily">每天</option></select></label>\n'
        '    <label>Cron <input type="text" name="cron" value="*/30 * * * *"/></label>\n'
        '    <label>时间范围 <input type="text" name="time_range" placeholder="例如：最近7天"/></label>\n'
        '    <div id="channel-specific-fields" style="width:100%;margin-top:12px;">\n'
        '      <span class="muted">请选择渠道类型以显示自定义参数</span>\n'
        '    </div>\n'
        '  </form>\n'
        '  <div class="compliance-agreement-block" style="margin-top:16px;padding:16px;border:1px solid #ddd;border-radius:6px;background:#f8f9fa;">\n'
        '    <h4 style="margin:0 0 12px 0;font-size:15px;">⚖ 数据采集合规检查清单（保存前必须勾选）</h4>\n'
        '    <div id="compliance-agreement-text" class="code-out" style="max-height:120px;overflow-y:auto;margin-bottom:12px;font-size:12px;color:#495057;line-height:1.6;background:#fff;padding:10px;border-radius:4px;border:1px solid #dee2e6;">【数据采集合规协议】本工具仅用于合法的公开信息采集用途。使用者须遵守《网络安全法》《数据安全法》《个人信息保护法》及相关法律法规。不得采集：(1)个人隐私信息（手机号、邮箱、身份证号、地址等）；(2)国家机关/涉密单位非公开数据；(3)需登录后才能访问的数据；(4)受版权保护的内容；(5)违反目标网站 robots.txt 规则的数据。使用者对采集行为及数据使用承担全部法律责任。采集数据仅限内部业务分析使用，不得出售、出租或向第三方泄露。</div>\n'
        '    <div class="row" style="flex-wrap:wrap;gap:12px;">\n'
        '      <label><input type="checkbox" name="compliance_agreed" value="true" form="task-create-form"/> 我已阅读并同意《数据采集合规协议》</label>\n'
        '    </div>\n'
        '    <div class="row" style="flex-wrap:wrap;gap:12px;margin-top:8px;">\n'
        '      <label>数据用途 <select name="compliance_data_purpose" form="task-create-form">\n'
        '        <option value="">请选择</option>\n'
        '        <option value="opportunity">商机分析</option>\n'
        '        <option value="market_research">市场调研</option>\n'
        '        <option value="bidding_decision">招投标决策</option>\n'
        '        <option value="industry_monitoring">行业监控</option>\n'
        '      </select></label>\n'
        '      <label>保留周期 <select name="compliance_retention" form="task-create-form">\n'
        '        <option value="">请选择</option>\n'
        '        <option value="30d">30天</option>\n'
        '        <option value="90d">90天</option>\n'
        '        <option value="180d">180天</option>\n'
        '        <option value="1y">1年</option>\n'
        '      </select></label>\n'
        '    </div>\n'
        '    <div class="row" style="flex-wrap:wrap;gap:12px;margin-top:8px;">\n'
        '      <label><input type="checkbox" name="compliance_privacy" value="true" form="task-create-form"/> 我承诺不采集个人隐私信息（手机号/邮箱/身份证号）</label>\n'
        '    </div>\n'
        '    <div class="row" style="flex-wrap:wrap;gap:12px;margin-top:8px;">\n'
        '      <label><input type="checkbox" name="compliance_site_verified" value="true" form="task-create-form"/> 我确认采集站点未违反合规规则（URL/标题中不含违禁关键词）</label>\n'
        '    </div>\n'
        '    <div class="row" style="margin-top:12px;">\n'
        '      <button class="btn btn-primary" type="submit" form="task-create-form" data-requires-permission="btn.spider.create">保存任务</button>\n'
        '    </div>\n'
        '  </div>\n'
        '</section>\n'
        '<section class="panel">\n'
        '  <h3>🔍 任务筛选</h3>\n'
        '  <div class="row">\n'
        '    <label>状态 <select id="filter-status">\n'
        '      <option value="">全部</option>\n'
        '      <option value="PENDING_APPROVAL">待审核</option>\n'
        '      <option value="REJECTED">已拒绝</option>\n'
        '      <option value="READY">就绪</option>\n'
        '      <option value="RUNNING">运行中</option>\n'
        '      <option value="PAUSED">已暂停</option>\n'
        '      <option value="COMPLETED">已完成</option>\n'
        '      <option value="FAILED">失败</option>\n'
        '      <option value="TERMINATED">已终止</option>\n'
        '    </select></label>\n'
        '    <label>渠道 <select id="filter-channel">\n'
        '      <option value="">全部</option>\n'
        '      <option value="generic_web">通用网页/论坛</option>\n'
        '      <option value="short_video">短视频</option>\n'
        '      <option value="xhs">小红书</option>\n'
        '      <option value="qa_platform">问答平台</option>\n'
        '      <option value="b2b_supply">供需B2B</option>\n'
        '      <option value="bidding">招投标</option>\n'
        '      <option value="company_biz">企业工商</option>\n'
        '    </select></label>\n'
        '    <label>任务名称/ID <input type="text" id="filter-keyword" placeholder="模糊搜索"/></label>\n'
        '    <button class="btn btn-primary" onclick="admin.loadSpiderFiltered()">应用筛选</button>\n'
        '    <button class="btn" onclick="admin.loadSpiderFiltered()">刷新</button>\n'
        '  </div>\n'
        '</section>\n'
        '<section class="panel">\n'
        '  <h3>📋 采集任务列表</h3>\n'
        '  <table class="data-table" id="tasks-table">\n'
        '    <thead><tr>\n'
        '      <th>任务ID</th><th>渠道</th><th>任务名称</th><th>状态</th>\n'
        '      <th>采集数</th><th>失败</th><th>下次运行</th><th>操作</th>\n'
        '    </tr></thead>\n'
        '    <tbody id="tasks-body"><tr><td colspan="8" class="empty">加载中...</td></tr></tbody>\n'
        '  </table>\n'
        '</section>\n'
        '<section class="panel">\n'
        '  <h3>[日志] 爬虫日志</h3>\n'
        '  <div class="row">\n'
        '    <input type="text" id="log-job-id" placeholder="请输入任务/作业ID"/>\n'
        '    <button class="btn" onclick="admin.loadSpiderLogs()">查看</button>\n'
        '  </div>\n'
        '  <pre id="logs-out" class="code-out">(空)</pre>\n'
        '</section>\n'
        '<script>\n'
        '  (function () {\n'
        '    // 1) Dynamic form rendering based on channel selection\n'
        '    var sel = document.getElementById("task-channel-select");\n'
        '    var hidden = document.getElementById("task-channel-hidden");\n'
        '    if (sel && hidden && typeof admin !== "undefined" && admin.renderChannelForm) {\n'
        '      sel.addEventListener("change", function () {\n'
        '        hidden.value = sel.value;\n'
        '        admin.renderChannelForm(sel.value);\n'
        '      });\n'
        '    }\n'
        '    // 2) URL parameter ?channel=xxx preselection\n'
        '    var m = location.search.match(/[?&]channel=([^&]+)/);\n'
        '    if (m && sel) {\n'
        '      sel.value = decodeURIComponent(m[1]);\n'
        '      if (hidden) hidden.value = sel.value;\n'
        '      if (typeof admin !== "undefined" && admin.renderChannelForm) admin.renderChannelForm(sel.value);\n'
        '    }\n'
        '    // 3) Initial task list load\n'
        '    if (typeof admin !== "undefined" && admin.loadSpiderFiltered) admin.loadSpiderFiltered();\n'
        '  })();\n'
        '</script>\n'
    )
    return _render_with_permission("spider", "btn.spider.view", body, session)


# ---------------------------------------------------------------------------
# New: task detail and real-time monitoring page
# ---------------------------------------------------------------------------
@router.get("/spider/{job_id}", response_class=HTMLResponse)
def spider_detail_page(job_id: str, session: dict | None = Depends(get_current_admin)):
    body_parts = [
        '<section class="panel task-detail-config">',
        '  <h3>[配置] 任务基础配置（只读）</h3>',
        '  <div id="detail-config" class="task-detail-config-grid">',
        '    <span class="muted">加载中 task ' + job_id + ' 基础配置...</span>',
        '  </div>',
        '</section>',
        '<section class="panel task-detail-progress">',
        '  <h3>[图表] 采集进度</h3>',
        '  <div id="detail-progress">',
        '    <span class="muted">加载中 采集进度...</span>',
        '  </div>',
        '</section>',
        '<section class="panel">',
        '  <h3>[操作] 任务操作</h3>',
        '  <div class="row">',
        '    <button class="btn btn-sm" data-requires-permission="btn.spider.run" onclick="admin.runSpiderTask(\'' + job_id + '\')">立即运行</button>',
        '    <button class="btn btn-sm" data-requires-permission="btn.spider.pause" onclick="admin.pauseTask(\'' + job_id + '\')">暂停</button>',
        '    <button class="btn btn-sm" data-requires-permission="btn.spider.resume" onclick="admin.resumeTask(\'' + job_id + '\')">恢复</button>',
        '    <button class="btn btn-sm" data-requires-permission="btn.spider.retry" onclick="admin.retryTask(\'' + job_id + '\')">重试（继续采集）</button>',
        '    <button class="btn btn-sm" data-requires-permission="btn.spider.terminate" onclick="admin.terminateTask(\'' + job_id + '\')">终止任务</button>',
        '    <button class="btn btn-sm btn-danger" data-requires-permission="btn.spider.delete" onclick="admin.deleteTask(\'' + job_id + '\')">删除任务</button>',
        '  </div>',
        '</section>',
        '<section class="panel">',
        '  <h3>[数据] 原始数据采集详情（自动脱敏）</h3>',
        '  <table class="data-table spider-item-table" id="items-table">',
        '    <thead><tr>',
        '      <th>ID</th><th>标题/内容</th><th>作者</th><th>电话</th><th>邮箱</th>',
        '    </tr></thead>',
        '    <tbody id="items-body"><tr><td colspan="5" class="empty">加载中...</td></tr></tbody>',
        '  </table>',
        '  <div class="row" style="margin-top:12px;" id="items-pagination"></div>',
        '</section>',
        '<section class="panel">',
        '  <h3>[日志] 任务运行日志（自动刷新）</h3>',
        '  <div id="task-logs" class="spider-logs">(空)</div>',
        '</section>',
        '<script>',
        '  (function () {',
        '    if (typeof admin !== "undefined" && admin.loadSpiderDetail) {',
        '      admin.loadSpiderDetail("' + job_id + '");',
        '      if (admin.autoRefreshDetail) admin.autoRefreshDetail("' + job_id + '", 10);',
        '    }',
        '    window.addEventListener("beforeunload", function () {',
        '      if (admin && admin._detailTimer) clearInterval(admin._detailTimer);',
        '    });',
        '  })();',
        '</script>',
    ]
    body = "\n".join(body_parts) + "\n"
    return _render_with_permission("spider_detail", "btn.spider.view", body, session)


@router.get("/leads", response_class=HTMLResponse)
def leads_page(session: dict | None = Depends(get_current_admin)):
    body = (
        '<section class="panel">\n'
        '  <h3>🔍 筛选</h3>\n'
        '  <div class="row">\n'
        '    <input type="text" id="keyword" placeholder="关键词（标题/客户）"/>\n'
        '    <select id="status">\n'
        '      <option value="">全部状态</option>\n'
        '      <option value="PENDING">待复核</option>\n'
        '      <option value="APPROVED">已通过</option>\n'
        '      <option value="REJECTED">已拒绝</option>\n'
        '    </select>\n'
        '    <button class="btn btn-primary" onclick="admin.loadLeads()">查询</button>\n'
        '  </div>\n'
        '</section>\n'
        '<section class="panel">\n'
        '  <h3>📋 线索列表</h3>\n'
        '  <table class="data-table">\n'
        '    <thead><tr><th>ID</th><th>标题</th><th>客户</th><th>状态</th><th>操作</th></tr></thead>\n'
        '    <tbody id="leads-body"><tr><td colspan="5" class="empty">加载中...</td></tr></tbody>\n'
        '  </table>\n'
        '</section>\n'
        '<section class="panel" data-requires-permission="btn.leads.add_blacklist">\n'
        '  <h3>🛑 黑名单管理</h3>\n'
        '  <form class="row-form" onsubmit="return admin.addBlacklist(event)">\n'
        '    <label>类型 <select name="type"><option value="phone">手机号</option><option value="email">邮箱</option><option value="company_name">公司名</option><option value="domain">域名</option></select></label>\n'
        '    <label>标识 <input type="text" name="identifier" placeholder="标识内容"/></label>\n'
        '    <label>原因 <input type="text" name="reason" placeholder="例：无效商机"/></label>\n'
        '    <button class="btn btn-danger" type="submit">加入黑名单</button>\n'
        '  </form>\n'
        '  <div class="row" style="margin-top:12px;">\n'
        '    <button class="btn btn-sm" onclick="admin.loadBlacklist()">加载黑名单</button>\n'
        '  </div>\n'
        '  <div id="blacklist-body" class="code-out">(点击加载)</div>\n'
        '</section>\n'
    )
    return _render_with_permission("leads", "btn.leads.view", body, session)


@router.get("/channels", response_class=HTMLResponse)
def channels_page(session: dict | None = Depends(get_current_admin)):
    body = (
        '<section class="panel">\n'
        '  <h3>[+] 新建渠道账号</h3>\n'
        '  <form class="row-form" data-requires-permission="btn.channels.create" onsubmit="return admin.createAccount(event)">\n'
        '    <label>渠道 <select name="channel">\n'
        '      <option value="email">邮箱</option>\n'
        '      <option value="wechat">企业微信</option>\n'
        '      <option value="feishu">飞书</option>\n'
        '      <option value="dingtalk">钉钉</option>\n'
        '    </select></label>\n'
        '    <label>账号ID <input type="text" name="account_id" placeholder="biztools_sender_01"/></label>\n'
        '    <label>用户名 <input type="text" name="username" placeholder="显示名称"/></label>\n'
        '    <label>密码（加密存储，不回显） <input type="password" name="password" required/></label>\n'
        '    <label>每日发送上限 <input type="number" name="quota" value="500" min="1"/></label>\n'
        '    <button class="btn btn-primary" type="submit">保存</button>\n'
        '  </form>\n'
        '</section>\n'
        '<section class="panel">\n'
        '  <h3>📋 渠道账号列表（密钥/密码始终脱敏）</h3>\n'
        '  <div id="channels-wrap"><div class="empty-inline">加载中...</div></div>\n'
        '</section>\n'
    )
    return _render_with_permission("channels", "btn.channels.view", body, session)


@router.get("/sales", response_class=HTMLResponse)
def sales_page(session: dict | None = Depends(get_current_admin)):
    body = (
        '<section class="panel">\n'
        '  <h3>[人员] 销售人员</h3>\n'
        '  <form class="row-form" data-requires-permission="btn.sales.create" onsubmit="return admin.upsertPerson(event)">\n'
        '    <label>销售ID <input type="text" name="sales_id" placeholder="s_001"/></label>\n'
        '    <label>姓名 <input type="text" name="name" placeholder="张三"/></label>\n'
        '    <label>行业（逗号分隔） <input type="text" name="industries" placeholder="制造业,电商"/></label>\n'
        '    <label>权重 <input type="number" step="0.1" name="weight" value="1.0"/></label>\n'
        '    <label>手机（显示脱敏） <input type="text" name="phone" placeholder="仅存储，不回显"/></label>\n'
        '    <label>邮箱（显示脱敏） <input type="text" name="email" placeholder="a@b.com"/></label>\n'
        '    <button class="btn btn-primary" type="submit">保存</button>\n'
        '  </form>\n'
        '  <table class="data-table">\n'
        '    <thead><tr><th>ID</th><th>姓名</th><th>行业</th><th>权重</th><th>手机</th><th>邮箱</th></tr></thead>\n'
        '    <tbody id="persons-body"><tr><td colspan="6" class="empty">加载中...</td></tr></tbody>\n'
        '  </table>\n'
        '</section>\n'
        '<section class="panel">\n'
        '  <h3>[分配] 商机分配</h3>\n'
        '  <form class="row-form" data-requires-permission="btn.sales.assign" onsubmit="return admin.doAssign(event)">\n'
        '    <label>商机ID <input type="text" name="opportunity_id" placeholder="opp_001"/></label>\n'
        '    <label>客户 <input type="text" name="customer" placeholder="ACME公司"/></label>\n'
        '    <label>销售 <input type="text" name="sales_id" placeholder="留空=自动分配"/></label>\n'
        '    <button class="btn btn-primary" type="submit">分配</button>\n'
        '  </form>\n'
        '  <table class="data-table">\n'
        '    <thead><tr><th>分配ID</th><th>商机</th><th>销售人员</th><th>状态</th><th>时间</th></tr></thead>\n'
        '    <tbody id="assignments-body"><tr><td colspan="5" class="empty">加载中...</td></tr></tbody>\n'
        '  </table>\n'
        '</section>\n'
        '<section class="panel">\n'
        '  <h3>[电话] 跟进记录</h3>\n'
        '  <form class="row-form" data-requires-permission="btn.sales.record_followup" onsubmit="return admin.recordFollowup(event)">\n'
        '    <label>商机ID <input type="text" name="opportunity_id"/></label>\n'
        '    <label>渠道 <select name="channel"><option>电话</option><option>邮箱</option><option>会议</option><option>微信</option></select></label>\n'
        '    <label>内容 <input type="text" name="content" placeholder="通话简要记录"/></label>\n'
        '    <label>销售ID <input type="text" name="sales_id" placeholder="留空=当前用户"/></label>\n'
        '    <button class="btn btn-primary" type="submit">记录</button>\n'
        '  </form>\n'
        '  <table class="data-table">\n'
        '    <thead><tr><th>ID</th><th>商机</th><th>渠道</th><th>内容</th><th>操作人</th><th>时间</th></tr></thead>\n'
        '    <tbody id="followups-body"><tr><td colspan="6" class="empty">加载中...</td></tr></tbody>\n'
        '  </table>\n'
        '</section>\n'
        '<section class="panel">\n'
        '  <h3>[提醒] 逾期跟进</h3>\n'
        '  <table class="data-table">\n'
        '    <thead><tr><th>商机</th><th>销售人员</th><th>上次跟进</th><th>提示</th></tr></thead>\n'
        '    <tbody id="overdue-body"><tr><td colspan="4" class="empty">加载中...</td></tr></tbody>\n'
        '  </table>\n'
        '  <div class="row" style="margin-top:12px;"><button class="btn btn-sm" onclick="admin.loadOverdue()">刷新</button></div>\n'
        '</section>\n'
    )
    return _render_with_permission("sales", "btn.sales.view", body, session)


@router.get("/audit_log", response_class=HTMLResponse)
def audit_page(session: dict | None = Depends(get_current_admin)):
    body = (
        '<section class="panel">\n'
        '  <h3>[搜索] 日志筛选</h3>\n'
        '  <div class="row">\n'
        '    <label>角色 <select id="f-role">\n'
        '      <option value="">全部</option>\n'
        '      <option value="super_admin">超级管理员</option>\n'
        '      <option value="ops">运维</option>\n'
        '      <option value="sales">销售</option>\n'
        '      <option value="compliance">合规</option>\n'
        '    </select></label>\n'
        '    <label>操作类型 <select id="f-op">\n'
        '      <option value="">全部</option>\n'
        '      <option>读取</option><option>创建</option><option>更新</option>\n'
        '      <option>删除</option><option>查看密钥</option><option>导出</option>\n'
        '      <option>登录</option><option>登出</option>\n'
        '    </select></label>\n'
        '    <label>关键词 <input type="text" id="f-keyword" placeholder="用户名 / 路径 / 内容"/></label>\n'
        '    <button class="btn btn-primary" onclick="admin.loadAuditLogsEnhanced()">查询</button>\n'
        '    <button class="btn btn-sm" data-requires-permission="btn.audit.export" onclick="admin.exportAuditLogs()">导出CSV</button>\n'
        '  </div>\n'
        '</section>\n'
        '<section class="panel">\n'
        '  <h3>📋 日志列表</h3>\n'
        '  <table class="data-table" id="audit-table">\n'
        '    <thead><tr>\n'
        '      <th>时间</th><th>用户</th><th>角色</th><th>IP</th><th>操作</th>\n'
        '      <th>路径/内容</th><th>状态</th><th>耗时</th><th>trace_id</th>\n'
        '    </tr></thead>\n'
        '    <tbody id="audit-body"><tr><td colspan="9" class="empty">加载中...</td></tr></tbody>\n'
        '  </table>\n'
        '  <div class="row pagination">\n'
        '    <span id="audit-summary" class="muted">-</span>\n'
        '    <button class="btn btn-sm" onclick="admin.prevAuditPage()">上一页</button>\n'
        '    <span id="audit-page-info">第 1 页</span>\n'
        '    <button class="btn btn-sm" onclick="admin.nextAuditPage()">下一页</button>\n'
        '  </div>\n'
        '</section>\n'
    )
    return _render_with_permission("audit_log", "btn.audit.view", body, session)


# ---------------------------------------------------------------------------
# New page: Account Management (super_admin only)
# ---------------------------------------------------------------------------
@router.get("/system/accounts", response_class=HTMLResponse)
def accounts_page(session: dict | None = Depends(get_current_admin)):
    body = (
        '<section class="panel">\n'
        '  <h3>[+] 新建账号</h3>\n'
        '  <form class="row-form" onsubmit="return admin.createAdminAccount(event)">\n'
        '    <label>账号 <input type="text" name="username" required placeholder="新用户名"/></label>\n'
        '    <label>角色 <select name="role">\n'
        '      <option value="ops">运维</option>\n'
        '      <option value="sales">销售</option>\n'
        '      <option value="compliance">合规</option>\n'
        '      <option value="super_admin">超级管理员</option>\n'
        '    </select></label>\n'
        '    <label>初始密码 <input type="password" name="password_plain" required/></label>\n'
        '    <button class="btn btn-primary" type="submit">创建</button>\n'
        '  </form>\n'
        '  <p class="muted">注意：创建后将记录一条【新建账号】审计到数据库。账号在进程字典中管理；进程重启后恢复到 .env 配置。</p>\n'
        '</section>\n'
        '<section class="panel">\n'
        '  <h3>📋 账号列表</h3>\n'
        '  <table class="data-table" id="accounts-table">\n'
        '    <thead><tr><th>账号</th><th>角色</th><th>状态</th><th>创建时间</th><th>操作</th></tr></thead>\n'
        '    <tbody id="accounts-body"><tr><td colspan="5" class="empty">加载中...</td></tr></tbody>\n'
        '  </table>\n'
        '</section>\n'
    )
    return _render_with_permission("accounts", "btn.system.accounts", body, session)


# ---------------------------------------------------------------------------
# Generic: 403 / empty state example pages
# ---------------------------------------------------------------------------
@router.get("/403", response_class=HTMLResponse)
def page_403(session: dict | None = Depends(get_current_admin)):
    body = _forbidden_body("403", missing_perm="(checked on page access)")
    return HTMLResponse(_layout_v2("权限不足", "403", body, session))


@router.get("/empty", response_class=HTMLResponse)
def page_empty(session: dict | None = Depends(get_current_admin)):
    body = (
        '<div class="empty-state">\n'
        '  <div class="empty-state-icon">📭</div>\n'
        '  <div class="empty-state-title">暂无内容</div>\n'
        '  <div class="empty-state-desc">这是空状态组件示例。当数据尚未准备好时会显示类似内容。</div>\n'
        '  <div class="empty-state-actions">\n'
        '    <a class="btn btn-primary" href="/admin/dashboard">返回仪表板</a>\n'
        '  </div>\n'
        '</div>\n'
        '<section class="panel" style="margin-top:24px;">\n'
        '  <h3>[重复] 加载中 状态示例</h3>\n'
        '  <div class="loading-state" id="loading-demo"><div class="spinner"></div> <span>数据加载中...</span></div>\n'
        '</section>\n'
    )
    return _render_with_permission("empty", "btn.dashboard.view", body, session)


# ---------------------------------------------------------------------------
# T20: Compliance Review Page
# ---------------------------------------------------------------------------
@router.get("/compliance/review", response_class=HTMLResponse)
def compliance_review_page(session: dict | None = Depends(get_current_admin)):
    body_parts = [
        # 待审核列表
        '<section class="panel">',
        '  <h3>⚖ 待审核任务</h3>',
        '  <div class="row">',
        '    <label>渠道 <select id="pending-channel-filter">',
        '      <option value="">全部</option>',
        '      <option value="short_video">短视频</option>',
        '      <option value="xhs">小红书</option>',
        '      <option value="b2b_supply">供需B2B</option>',
        '      <option value="generic_web">通用网页</option>',
        '      <option value="qa_platform">问答平台</option>',
        '      <option value="bidding">招投标</option>',
        '      <option value="company_biz">企业工商</option>',
        '    </select></label>',
        '    <button class="btn btn-primary" data-requires-permission="btn.compliance.review" onclick="admin.loadPendingTasks()">加载待审核</button>',
        '  </div>',
        '  <table class="data-table" id="pending-tasks-table">',
        '    <thead><tr>',
        '      <th>任务ID</th><th>渠道</th><th>任务名称</th><th>提交人</th>',
        '      <th>提交时间</th><th>数据用途</th><th>保留周期</th><th>操作</th>',
        '    </tr></thead>',
        '    <tbody id="pending-tasks-body"><tr><td colspan="8" class="empty">待审核任务加载中...</td></tr></tbody>',
        '  </table>',
        '</section>',
        # 驳回弹窗（隐藏，点击驳回按钮显示）
        '<div id="reject-modal" class="modal" style="display:none;">',
        '  <div class="modal-content" style="max-width:500px;">',
        '    <h3 style="margin-top:0;">驳回任务</h3>',
        '    <textarea id="reject-reason" rows="5" style="width:100%;padding:8px;box-sizing:border-box;" placeholder="请输入驳回原因（必填）"></textarea>',
        '    <div class="row" style="justify-content:flex-end;gap:8px;margin-top:12px;">',
        '      <button class="btn" onclick="admin.closeRejectModal()">取消</button>',
        '      <button class="btn btn-danger" data-requires-permission="btn.compliance.reject" onclick="admin.submitReject()">确认驳回</button>',
        '    </div>',
        '  </div>',
        '</div>',
        # 已审核记录
        '<section class="panel">',
        '  <h3>📋 审核记录</h3>',
        '  <div class="row">',
        '    <button class="btn" data-requires-permission="btn.compliance.review" onclick="admin.loadApprovalHistory()">加载审核记录</button>',
        '  </div>',
        '  <table class="data-table" id="approval-history-table">',
        '    <thead><tr>',
        '      <th>任务ID</th><th>任务名称</th><th>渠道</th><th>提交人</th>',
        '      <th>审核人</th><th>审核时间</th><th>决策</th><th>拒绝原因</th>',
        '    </tr></thead>',
        '    <tbody id="approval-history-body"><tr><td colspan="8" class="empty">点击按钮加载审核记录...</td></tr></tbody>',
        '  </table>',
        '</section>',
        # 自动初始化
        '<script>',
        '  (function () {',
        '    if (typeof admin !== "undefined") {',
        '      if (admin.loadPendingTasks) admin.loadPendingTasks();',
        '    }',
        '  })();',
        '</script>',
    ]
    body = "\n".join(body_parts) + "\n"
    return _render_with_permission("compliance_review", "btn.compliance.review", body, session)


# ---------------------------------------------------------------------------
# T20: Compliance Rules Config Page
# ---------------------------------------------------------------------------
@router.get("/compliance/config", response_class=HTMLResponse)
def compliance_config_page(session: dict | None = Depends(get_current_admin)):
    body_parts = [
        # 渠道审批规则
        '<section class="panel">',
        '  <h3>⚙ 渠道审批规则</h3>',
        '  <p class="muted">高风险渠道需要合规官审核；低风险渠道可配置为跳过审核。</p>',
        '  <table class="data-table" id="channel-rules-table">',
        '    <thead><tr>',
        '      <th>渠道</th><th>风险等级</th><th>是否需审核</th><th>操作</th>',
        '    </tr></thead>',
        '    <tbody id="channel-rules-body"><tr><td colspan="4" class="empty">渠道规则加载中...</td></tr></tbody>',
        '  </table>',
        '</section>',
        # 合规协议文本
        '<section class="panel">',
        '  <h3>📄 数据采集合规协议文本</h3>',
        '  <p class="muted">该文本将展示在爬虫任务创建页面；提交人必须勾选同意。</p>',
        '  <textarea id="agreement-text-edit" rows="12" style="width:100%;font-family:monospace;padding:8px;box-sizing:border-box;" placeholder="合规协议文本加载中..."></textarea>',
        '  <div class="row" style="justify-content:flex-end;margin-top:12px;">',
        '    <button class="btn btn-primary" data-requires-permission="btn.compliance.config" onclick="admin.saveAgreementText()">保存协议文本</button>',
        '  </div>',
        '</section>',
        # 留存周期选项
        '<section class="panel">',
        '  <h3>📅 数据留存周期选项</h3>',
        '  <p class="muted">逗号分隔的值，例如：30天,90天,180天,1年</p>',
        '  <input type="text" id="retention-options-edit" style="width:100%;padding:8px;box-sizing:border-box;" placeholder="30d,90d,180d,1y"/>',
        '  <div class="row" style="justify-content:flex-end;margin-top:12px;">',
        '    <button class="btn btn-primary" data-requires-permission="btn.compliance.config" onclick="admin.saveRetentionOptions()">保存留存选项</button>',
        '  </div>',
        '</section>',
        # 违规关键词黑名单
        '<section class="panel">',
        '  <h3>🚫 违禁关键词黑名单</h3>',
        '  <p class="muted">包含在任务参数（标题、关键词、URL等）中的这些关键词将阻止任务创建。请使用逗号分隔。</p>',
        '  <textarea id="forbidden-keywords-edit" rows="6" style="width:100%;font-family:monospace;padding:8px;box-sizing:border-box;" placeholder="手机,邮箱,身份证号..."></textarea>',
        '  <div class="row" style="justify-content:flex-end;margin-top:12px;">',
        '    <button class="btn btn-primary" data-requires-permission="btn.compliance.config" onclick="admin.saveForbiddenKeywords()">保存黑名单</button>',
        '  </div>',
        '</section>',
        # 自动加载配置
        '<script>',
        '  (function () {',
        '    if (typeof admin !== "undefined" && admin.loadComplianceConfigPage) {',
        '      admin.loadComplianceConfigPage();',
        '    }',
        '  })();',
        '</script>',
    ]
    body = "\n".join(body_parts) + "\n"
    return _render_with_permission("compliance_config", "btn.compliance.config", body, session)


# ---------------------------------------------------------------------------
# T20: Notification Center Page
# ---------------------------------------------------------------------------
@router.get("/notifications", response_class=HTMLResponse)
def notifications_page(session: dict | None = Depends(get_current_admin)):
    body_parts = [
        '<section class="panel">',
        '  <h3>[铃铛] 最近通知</h3>',
        '  <div class="row" style="gap:8px;">',
        '    <button class="btn btn-sm" onclick="admin.loadNotificationsList()">刷新</button>',
        '    <button class="btn btn-sm" data-requires-permission="btn.compliance.notification" onclick="admin.markAllNotificationsRead()">全部标记已读</button>',
        '  </div>',
        '  <table class="data-table" id="notifications-table">',
        '    <thead><tr>',
        '      <th>时间</th><th>类型</th><th>标题</th><th>内容</th><th>状态</th><th>操作</th>',
        '    </tr></thead>',
        '    <tbody id="notifications-body"><tr><td colspan="6" class="empty">通知加载中...</td></tr></tbody>',
        '  </table>',
        '</section>',
        '<script>',
        '  (function () {',
        '    if (typeof admin !== "undefined" && admin.loadNotificationsList) admin.loadNotificationsList();',
        '  })();',
        '</script>',
    ]
    body = "\n".join(body_parts) + "\n"
    return _render_with_permission("notifications", "btn.compliance.notification", body, session)


# ===========================================================================
# T21: 全链路 6 阶段管控看板 — 页面路由
# ===========================================================================

@router.get("/data_center/dashboard", response_class=HTMLResponse)
def data_center_dashboard_page(session: dict | None = Depends(get_current_admin)):
    """全链路漏斗总览看板：核心指标卡 + 6 阶段漏斗 + 渠道/等级分布图 + 趋势图"""
    body_parts = [
        # 1) 顶部核心指标卡
        '<section class="stats-grid" id="dc-summary-grid">',
        '  <div class="stat-card"><div class="label">☀ 今日新增</div><div class="value" id="v-today-added">0</div><div class="sub" id="v-trend">—</div></div>',
        '  <div class="stat-card"><div class="label">📁 商机总数</div><div class="value" id="v-total-leads">0</div></div>',
        '  <div class="stat-card"><div class="label">⭐ 高意向</div><div class="value" id="v-high-intent">0</div></div>',
        '  <div class="stat-card"><div class="label">👤 待跟进</div><div class="value" id="v-pending-followup">0</div></div>',
        '  <div class="stat-card"><div class="label">✅ 已成交</div><div class="value" id="v-won">0</div></div>',
        '</section>',

        # 2) 6 阶段漏斗图
        '<section class="panel">',
        '  <h3>[图表] 全链路漏斗（六阶段）</h3>',
        '  <div class="row" style="gap:8px;margin-bottom:12px;">',
        '    <button class="btn btn-sm" onclick="admin.loadFunnelChart()">刷新漏斗</button>',
        '  </div>',
        '  <div id="funnel-chart" class="funnel-chart"><div class="empty-inline">漏斗数据加载中...</div></div>',
        '</section>',

        # 3) 6 阶段快速入口卡片
        '<section class="panel">',
        '  <h3>[文件夹] 六阶段快速入口</h3>',
        '  <div class="channel-cards" id="stage-cards">',
        '    <a class="channel-card" href="/admin/data_center/collection">',
        '      <span class="channel-icon">[爬虫]</span><span class="channel-title">采集阶段</span><span class="channel-desc">爬虫任务与抓取条目</span>',
        '    </a>',
        '    <a class="channel-card" href="/admin/data_center/cleaning">',
        '      <span class="channel-icon">[清洗]</span><span class="channel-title">清洗结构化</span><span class="channel-desc">结构化、校验后的商机</span>',
        '    </a>',
        '    <a class="channel-card" href="/admin/data_center/compliance">',
        '      <span class="channel-icon">[合规]</span><span class="channel-title">合规校验</span><span class="channel-desc">敏感信息检测 + 风险评分</span>',
        '    </a>',
        '    <a class="channel-card" href="/admin/data_center/grading">',
        '      <span class="channel-icon">[分级]</span><span class="channel-title">商机分级</span><span class="channel-desc">A/B/C/D 等级 + 综合评分</span>',
        '    </a>',
        '    <a class="channel-card" href="/admin/data_center/outreach">',
        '      <span class="channel-icon">[触达]</span><span class="channel-title">客户触达</span><span class="channel-desc">邮件/IM 发送 + 响应追踪</span>',
        '    </a>',
        '    <a class="channel-card" href="/admin/data_center/sales">',
        '      <span class="channel-icon">[成交]</span><span class="channel-title">销售闭环</span><span class="channel-desc">跟进记录、成交/流失</span>',
        '    </a>',
        '  </div>',
        '</section>',

        # 4) 渠道分布 + 等级分布（两列）
        '<section class="panel">',
        '  <div class="row" style="gap:24px;flex-wrap:wrap;">',
        '    <div style="flex:1;min-width:320px;">',
        '      <h3>[图表] 渠道分布</h3>',
        '      <div id="channel-distribution" class="distribution-chart"><div class="empty-inline">加载中...</div></div>',
        '    </div>',
        '    <div style="flex:1;min-width:320px;">',
        '      <h3>[图表] 等级分布</h3>',
        '      <div id="grade-distribution" class="distribution-chart"><div class="empty-inline">加载中...</div></div>',
        '    </div>',
        '  </div>',
        '</section>',

        # 5) 近 7 天趋势折线图
        '<section class="panel">',
        '  <h3>[图表] 近 7 天趋势（商机线索 / 成交）</h3>',
        '  <div class="row" style="gap:8px;margin-bottom:12px;">',
        '    <button class="btn btn-sm" onclick="admin.loadTrendChart(\'leads\')">商机趋势</button>',
        '    <button class="btn btn-sm" onclick="admin.loadTrendChart(\'won\')">成交趋势</button>',
        '  </div>',
        '  <div id="trend-chart" class="trend-chart"><div class="empty-inline">趋势数据加载中...</div></div>',
        '</section>',

        # 页面加载脚本
        '<script>',
        '  (function () {',
        '    if (typeof admin !== "undefined") {',
        '      if (admin.loadDataCenterSummary) admin.loadDataCenterSummary();',
        '      if (admin.loadFunnelChart) admin.loadFunnelChart();',
        '      if (admin.loadDistributionCharts) admin.loadDistributionCharts();',
        '      if (admin.loadTrendChart) admin.loadTrendChart("leads");',
        '    }',
        '  })();',
        '</script>',
    ]
    body = "\n".join(body_parts) + "\n"
    return _render_with_permission("data_center_dashboard", "btn.data_center.view", body, session)


def _stage_detail_page_body(stage_key: str, stage_title: str, stage_desc: str,
                            table_headers: list[str], body_id: str) -> str:
    """通用阶段明细页模板：阶段汇总指标 + 筛选栏 + 分页表格 + 点击跳转商机追踪"""
    body_parts = [
        # 阶段汇总指标
        '<section class="stats-grid" id="' + body_id + '-stats">',
        '  <div class="stat-card"><div class="label">📁 条目总数</div><div class="value" id="' + body_id + '-total">0</div></div>',
        '  <div class="stat-card"><div class="label">✅ 已通过/有效</div><div class="value" id="' + body_id + '-valid">0</div></div>',
        '  <div class="stat-card"><div class="label">⚠ 异常数</div><div class="value" id="' + body_id + '-exception">0</div></div>',
        '  <div class="stat-card"><div class="label">🕓 近24小时新增</div><div class="value" id="' + body_id + '-recent">0</div></div>',
        '</section>',
        # 筛选栏
        '<section class="panel">',
        '  <h3>🔍 筛选：' + stage_title + ' — ' + stage_desc + '</h3>',
        '  <div class="row" style="gap:8px;flex-wrap:wrap;">',
        '    <label>状态 <select id="' + body_id + '-filter-status">',
        '      <option value="">全部</option><option value="APPROVED">已通过</option><option value="PENDING">待处理</option><option value="REJECTED">已拒绝</option>',
        '    </select></label>',
        '    <label>渠道 <select id="' + body_id + '-filter-channel">',
        '      <option value="">全部</option><option value="generic_web">通用网页</option><option value="short_video">短视频</option><option value="xhs">小红书</option><option value="qa_platform">问答平台</option><option value="b2b_supply">供需B2B</option><option value="bidding">招投标</option><option value="company_biz">企业工商</option>',
        '    </select></label>',
        '    <label>关键词 <input type="text" id="' + body_id + '-filter-keyword" placeholder="输入关键词搜索..."/></label>',
        '    <button class="btn btn-sm" onclick="admin.loadStageList(\'' + stage_key + '\',\'' + body_id + '\',1)">应用</button>',
        '    <button class="btn btn-sm" onclick="admin.loadStageList(\'' + stage_key + '\',\'' + body_id + '\',1)">刷新</button>',
        '  </div>',
        '</section>',
        # T22: 阶段操作工具栏
        '<section class="panel" data-stage="' + stage_key + '">',
        '  <h3>🛠 阶段手工管控</h3>',
        '  <div class="row" data-stage-actions="' + stage_key + '" style="gap:8px;flex-wrap:wrap;">',
        '  </div>',
        '</section>',
        # 明细表格
        '<section class="panel">',
        '  <table class="data-table" id="' + body_id + '-table">',
        '    <thead><tr>',
        '      ' + "".join(["<th>" + h + "</th>" for h in table_headers]) + '<th>操作</th>',
        '    </tr></thead>',
        '    <tbody id="' + body_id + '-body"><tr><td colspan="' + str(len(table_headers) + 1) + '" class="empty">数据加载中...</td></tr></tbody>',
        '  </table>',
        '  <div class="row" id="' + body_id + '-pager" style="margin-top:12px;gap:8px;"></div>',
        '</section>',
        # 分页 & 加载脚本
        '<script>',
        '  (function () {',
        '    if (typeof admin !== "undefined" && admin.loadStageList) admin.loadStageList("' + stage_key + '","' + body_id + '",1);',
        '  })();',
        '</script>',
    ]
    return "\n".join(body_parts) + "\n"


@router.get("/data_center/collection", response_class=HTMLResponse)
def data_center_collection_page(session: dict | None = Depends(get_current_admin)):
    """采集阶段：爬虫任务 + 已抓取条目"""
    body = _stage_detail_page_body(
        stage_key="collection",
        stage_title="采集阶段",
        stage_desc="爬虫任务 + 抓取条目",
        table_headers=["任务ID", "任务名称", "渠道", "状态", "已抓取", "失败", "创建时间"],
        body_id="dc-collection",
    )
    return _render_with_permission("data_center_collection", "btn.data_center.view", body, session)


@router.get("/data_center/cleaning", response_class=HTMLResponse)
def data_center_cleaning_page(session: dict | None = Depends(get_current_admin)):
    """清洗结构化：结构化的商机线索条目"""
    body = _stage_detail_page_body(
        stage_key="cleaning",
        stage_title="清洗结构化",
        stage_desc="结构化并校验的商机记录",
        table_headers=["商机ID", "标题", "渠道", "公司", "联系方式", "状态", "创建时间"],
        body_id="dc-cleaning",
    )
    return _render_with_permission("data_center_cleaning", "btn.data_center.view", body, session)


@router.get("/data_center/compliance", response_class=HTMLResponse)
def data_center_compliance_page(session: dict | None = Depends(get_current_admin)):
    """合规校验：PII 检测、风险分数"""
    body = _stage_detail_page_body(
        stage_key="compliance",
        stage_title="合规校验",
        stage_desc="敏感信息检测 + 合规评分",
        table_headers=["商机ID", "标题", "渠道", "合规状态", "合规分数", "风险等级", "敏感信息类型"],
        body_id="dc-compliance",
    )
    return _render_with_permission("data_center_compliance", "btn.data_center.view", body, session)


@router.get("/data_center/grading", response_class=HTMLResponse)
def data_center_grading_page(session: dict | None = Depends(get_current_admin)):
    """商机分级：A/B/C/D 等级 + 综合评分"""
    body = _stage_detail_page_body(
        stage_key="grading",
        stage_title="商机分级",
        stage_desc="商机等级A/B/C/D + 意向评分",
        table_headers=["商机ID", "标题", "渠道", "等级", "评分", "预算", "紧急程度", "标签"],
        body_id="dc-grading",
    )
    return _render_with_permission("data_center_grading", "btn.data_center.view", body, session)


@router.get("/data_center/outreach", response_class=HTMLResponse)
def data_center_outreach_page(session: dict | None = Depends(get_current_admin)):
    """客户触达：邮件/IM 发送批次记录"""
    body = _stage_detail_page_body(
        stage_key="outreach",
        stage_title="客户触达",
        stage_desc="邮件/IM 发送 + 响应追踪",
        table_headers=["批次ID", "标题", "目标商机", "渠道", "目标数", "成功", "失败", "状态", "发送时间"],
        body_id="dc-outreach",
    )
    return _render_with_permission("data_center_outreach", "btn.data_center.view", body, session)


@router.get("/data_center/sales", response_class=HTMLResponse)
def data_center_sales_page(session: dict | None = Depends(get_current_admin)):
    """销售闭环：跟进记录、成交/流失"""
    body = _stage_detail_page_body(
        stage_key="sales",
        stage_title="销售闭环",
        stage_desc="跟进、分配、成交流转",
        table_headers=["商机ID", "标题", "公司", "负责人", "等级", "状态", "跟进次数", "最近跟进", "预估价值"],
        body_id="dc-sales",
    )
    return _render_with_permission("data_center_sales", "btn.data_center.view", body, session)


@router.get("/data_center/opportunity/{lead_id}", response_class=HTMLResponse)
def data_center_opportunity_page(lead_id: str, session: dict | None = Depends(get_current_admin)):
    """单商机全生命周期追踪：按时间线展示 6 阶段流转过程"""
    body_parts = [
        # 顶部：商机概览
        '<section class="panel">',
        '  <h3>👤 商机追踪时间线 — ' + escape_html(lead_id) + '</h3>',
        '  <div class="task-detail-config-grid" id="opp-info-grid">',
        '    <div class="kv"><div class="label">商机ID</div><div class="value" id="opp-lead-id">' + escape_html(lead_id) + '</div></div>',
        '    <div class="kv"><div class="label">标题</div><div class="value" id="opp-title">加载中...</div></div>',
        '    <div class="kv"><div class="label">公司</div><div class="value" id="opp-company">加载中...</div></div>',
        '    <div class="kv"><div class="label">渠道</div><div class="value" id="opp-channel">加载中...</div></div>',
        '    <div class="kv"><div class="label">等级</div><div class="value" id="opp-grade">加载中...</div></div>',
        '    <div class="kv"><div class="label">评分</div><div class="value" id="opp-score">加载中...</div></div>',
        '    <div class="kv"><div class="label">状态</div><div class="value" id="opp-status">加载中...</div></div>',
        '    <div class="kv"><div class="label">联系方式(已脱敏)</div><div class="value" id="opp-contact">加载中...</div></div>',
        '  </div>',
        '  <div class="row" style="gap:8px;margin-top:12px;">',
        '    <button class="btn btn-sm" onclick="admin.loadOpportunityTimeline(\'' + escape_html(lead_id) + '\')">刷新时间线</button>',
        '  </div>',
        '</section>',
        # 时间线
        '<section class="panel">',
        '  <h3>🕓 生命周期时间线</h3>',
        '  <div id="opp-timeline" class="timeline-container"><div class="empty-inline">时间线数据加载中...</div></div>',
        '</section>',
        # 关联入口
        '<section class="panel">',
        '  <h3>🔗 相关链接</h3>',
        '  <div class="row" style="gap:8px;flex-wrap:wrap;">',
        '    <a class="btn btn-sm" href="/admin/spider" id="link-source-task">查看源任务</a>',
        '    <a class="btn btn-sm" href="/admin/leads">返回商机列表</a>',
        '    <a class="btn btn-sm" href="/admin/data_center/dashboard">返回漏斗看板</a>',
        '  </div>',
        '</section>',
        # 加载脚本
        '<script>',
        '  (function () {',
        '    if (typeof admin !== "undefined" && admin.loadOpportunityTimeline) {',
        '      admin.loadOpportunityTimeline("' + escape_html(lead_id) + '");',
        '    }',
        '  })();',
        '</script>',
    ]
    body = "\n".join(body_parts) + "\n"
    return _render_with_permission("data_center_opportunity", "btn.data_center.view", body, session)


# ===========================================================================
# T23: 运营配套工具页面
# ===========================================================================

@router.get("/data_center/exception", response_class=HTMLResponse)
def data_center_exception_page(session: dict | None = Depends(get_current_admin)):
    """异常数据池：异常集中管理，支持批量处理"""
    body_parts = [
        # 顶部：统计卡
        '<section class="panel">',
        '  <h3>⚠ 异常数据池 — 异常集中管理</h3>',
        '  <div class="stats-grid" id="exception-stats-grid">',
        '    <div class="stat-card"><div class="stat-label">总数</div><div class="stat-value" id="exception-total">-</div></div>',
        '    <div class="stat-card"><div class="stat-label">待处理</div><div class="stat-value" id="exception-pending">-</div></div>',
        '    <div class="stat-card"><div class="stat-label">已处理</div><div class="stat-value" id="exception-resolved">-</div></div>',
        '    <div class="stat-card"><div class="stat-label">7日趋势</div><div class="stat-value" id="exception-trend">-</div></div>',
        '  </div>',
        '</section>',
        # 类型分布（条形图）
        '<section class="panel">',
        '  <h3>📊 异常类型分布</h3>',
        '  <div class="type-distribution" id="exception-type-dist">',
        '    <div class="empty-inline">加载中...</div>',
        '  </div>',
        '</section>',
        # 筛选栏
        '<section class="panel">',
        '  <h3>🔍 筛选：异常条目过滤</h3>',
        '  <div class="row" style="gap:8px;flex-wrap:wrap;">',
        '    <label>类型 <select id="exception-filter-type">',
        '      <option value="">全部类型</option>',
        '    </select></label>',
        '    <label>渠道 <select id="exception-filter-channel">',
        '      <option value="">全部渠道</option>',
        '    </select></label>',
        '    <label>状态 <select id="exception-filter-status">',
        '      <option value="">全部</option><option value="pending">待处理</option><option value="resolved">已处理</option><option value="discarded">已废弃</option><option value="false_positive">误判</option>',
        '    </select></label>',
        '    <button class="btn btn-sm" onclick="admin.loadExceptionList()">应用筛选</button>',
        '    <button class="btn btn-sm" onclick="admin.loadExceptionList()">刷新</button>',
        '  </div>',
        '</section>',
        # T23 手工操作入口
        '<section class="panel" data-stage="exception">',
        '  <h3>🛠 手工操作</h3>',
        '  <div class="row" data-stage-actions="exception" style="gap:8px;flex-wrap:wrap;"></div>',
        '</section>',
        # 列表
        '<section class="panel">',
        '  <h3>📋 异常条目列表</h3>',
        '  <div id="exception-list" class="table-container">',
        '    <table class="data-table" id="exception-table">',
        '      <thead><tr><th>异常ID</th><th>类型</th><th>渠道</th><th>标题</th><th>状态</th><th>创建时间</th><th>操作</th></tr></thead>',
        '      <tbody id="exception-tbody"><tr><td colspan="7" class="empty">加载中...</td></tr></tbody>',
        '    </table>',
        '    <div id="exception-pagination" class="pagination"></div>',
        '  </div>',
        '</section>',
        # 脚本
        '<script>',
        '  (function () {',
        '    if (typeof admin !== "undefined") {',
        '      admin.loadExceptionStats();',
        '      admin.loadExceptionList();',
        '    }',
        '  })();',
        '</script>',
    ]
    body = "\n".join(body_parts) + "\n"
    return _render_with_permission("data_center_exception", "btn.data_center.view_exception", body, session)


@router.get("/data_center/channel-funnel", response_class=HTMLResponse)
def data_center_channel_funnel_page(session: dict | None = Depends(get_current_admin)):
    """分渠道转化漏斗看板：按渠道展示6阶段漏斗+核心指标+排行"""
    body_parts = [
        '<section class="panel">',
        '  <h3>📊 分渠道漏斗 — 分渠道转化效果看板</h3>',
        '  <div class="row" style="gap:8px;flex-wrap:wrap;margin-bottom:12px;">',
        '    <label>周期 <select id="channel-period">',
        '      <option value="week">最近4周</option><option value="month">最近3个月</option>',
        '    </select></label>',
        '    <label>天数 <input type="number" id="channel-days" value="30" min="1" max="365" style="width:80px;"></label>',
        '    <button class="btn btn-sm" onclick="admin.loadChannelFunnel()">重新加载</button>',
        '  </div>',
        '  <div class="stats-grid" id="channel-total-stats">',
        '    <div class="stat-card"><div class="stat-label">累计抓取</div><div class="stat-value" id="total-crawl">-</div></div>',
        '    <div class="stat-card"><div class="stat-label">累计成交</div><div class="stat-value" id="total-won">-</div></div>',
        '    <div class="stat-card"><div class="stat-label">综合转化率</div><div class="stat-value" id="total-conv">-</div></div>',
        '  </div>',
        '</section>',
        # 各渠道卡片网格
        '<section class="panel">',
        '  <h3>📇 各渠道表现</h3>',
        '  <div class="channel-funnel-grid" id="channel-funnel-grid">',
        '    <div class="empty-inline">加载中 channel data...</div>',
        '  </div>',
        '</section>',
        # 排行榜
        '<section class="panel">',
        '  <h3>🏆 分类渠道排名</h3>',
        '  <div class="rankings-grid" id="channel-rankings">',
        '    <div class="empty-inline">加载中...</div>',
        '  </div>',
        '</section>',
        # 趋势
        '<section class="panel">',
        '  <h3>🕓 周期趋势</h3>',
        '  <div class="trend-chart" id="channel-trend">',
        '    <div class="empty-inline">加载中...</div>',
        '  </div>',
        '</section>',
        '<script>',
        '  (function () {',
        '    if (typeof admin !== "undefined") {',
        '      admin.loadChannelFunnel();',
        '    }',
        '  })();',
        '</script>',
    ]
    body = "\n".join(body_parts) + "\n"
    return _render_with_permission("data_center_channel_funnel", "btn.data_center.view", body, session)


@router.get("/data_center/batch", response_class=HTMLResponse)
def data_center_batch_page(session: dict | None = Depends(get_current_admin)):
    """批量操作中心：提交批量任务 + 查看执行进度 + 历史列表"""
    body_parts = [
        # 提交区
        '<section class="panel">',
        '  <h3>⚙ 提交批量操作</h3>',
        '  <div class="batch-form-grid" style="display:flex;flex-direction:column;gap:12px;">',
        '    <label>操作类型 <select id="batch-op-type" style="padding:6px 8px;"></select></label>',
        '    <label>条目ID（英文逗号分隔，最多1000条）',
        '      <textarea id="batch-item-ids" rows="3" style="width:100%;font-family:monospace;padding:6px 8px;font-size:12px;" placeholder="例如：LEAD-123,LEAD-456,RAW-789..."></textarea>',
        '    </label>',
        '    <label>操作原因 <input type="text" id="batch-reason" placeholder="请说明本次批量操作的原因" style="width:100%;padding:6px 8px;"></label>',
        '    <div class="row" style="gap:8px;">',
        '      <button class="btn btn-primary" onclick="admin.submitBatch()">提交批量操作</button>',
        '      <button class="btn btn-sm" onclick="admin.fillBatchDemo()">填充示例ID</button>',
        '    </div>',
        '  </div>',
        '</section>',
        # 当前进度
        '<section class="panel" id="batch-progress-section" style="display:none;">',
        '  <h3>⏳ 批量执行进度</h3>',
        '  <div id="batch-progress-info"></div>',
        '  <div class="progress-bar-container"><div class="progress-bar-fill" id="batch-progress-bar"></div></div>',
        '  <div class="row" style="gap:8px;margin-top:12px;">',
        '    <button class="btn btn-sm" onclick="admin.refreshBatchStatus()">刷新状态</button>',
        '  </div>',
        '</section>',
        # 历史批量任务
        '<section class="panel">',
        '  <h3>📋 最近批量操作</h3>',
        '  <div id="batch-list" class="table-container">',
        '    <table class="data-table">',
        '      <thead><tr><th>批次ID</th><th>操作</th><th>操作人</th><th>总数</th><th>成功数</th><th>失败数</th><th>状态</th><th>风险等级</th><th>开始时间</th></tr></thead>',
        '      <tbody id="batch-list-body"><tr><td colspan="9" class="empty">加载中...</td></tr></tbody>',
        '    </table>',
        '  </div>',
        '</section>',
        '<script>',
        '  (function () {',
        '    if (typeof admin !== "undefined") {',
        '      admin.loadBatchOpTypes();',
        '      admin.loadBatchList();',
        '    }',
        '  })();',
        '</script>',
    ]
    body = "\n".join(body_parts) + "\n"
    return _render_with_permission("data_center_batch", "btn.data_center.batch_operation", body, session)


@router.get("/data_center/export", response_class=HTMLResponse)
def data_center_export_page(session: dict | None = Depends(get_current_admin)):
    """数据导出中心：各阶段数据导出，支持脱敏/明文，下载历史"""
    body_parts = [
        # 提交区
        '<section class="panel">',
        '  <h3>📥 数据导出中心</h3>',
        '  <div style="display:flex;flex-direction:column;gap:12px;">',
        '    <label>阶段 <select id="export-stage" style="padding:6px 8px;"></select></label>',
        '    <label><input type="checkbox" id="export-plaintext" style="margin-right:8px;"> 导出明文（仅超级管理员）</label>',
        '    <label>导出原因 <input type="text" id="export-reason" placeholder="简要说明本次导出的用途" style="width:100%;padding:6px 8px;"></label>',
        '    <div class="row" style="gap:8px;">',
        '      <button class="btn btn-primary" onclick="admin.submitExport()">提交导出</button>',
        '    </div>',
        '    <div class="manual-dialog-stage" style="margin-top:8px;">⚠ 所有默认导出为脱敏数据，明文导出需 超级管理员 权限，且全程留痕</div>',
        '  </div>',
        '</section>',
        # 当前导出任务
        '<section class="panel" id="export-progress-section" style="display:none;">',
        '  <h3>⏳ 当前导出</h3>',
        '  <div id="export-progress-info"></div>',
        '  <div class="progress-bar-container"><div class="progress-bar-fill" id="export-progress-bar"></div></div>',
        '</section>',
        # 导出历史
        '<section class="panel">',
        '  <h3>📋 导出历史</h3>',
        '  <div id="export-list" class="table-container">',
        '    <table class="data-table">',
        '      <thead><tr><th>导出ID</th><th>阶段</th><th>操作人</th><th>行数</th><th>大小</th><th>脱敏</th><th>状态</th><th>时间</th><th>下载</th></tr></thead>',
        '      <tbody id="export-list-body"><tr><td colspan="9" class="empty">加载中...</td></tr></tbody>',
        '    </table>',
        '  </div>',
        '</section>',
        '<script>',
        '  (function () {',
        '    if (typeof admin !== "undefined") {',
        '      admin.loadExportStages();',
        '      admin.loadExportList();',
        '    }',
        '  })();',
        '</script>',
    ]
    body = "\n".join(body_parts) + "\n"
    return _render_with_permission("data_center_export", "btn.data_center.export_data", body, session)


# 工具：确保 escape_html 可用（在 pages.py 顶部已经导入 html 模块上下文）
def escape_html(s: str) -> str:
    return s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace('"', "&quot;").replace("'", "&#39;")


__all__ = ["router"]


# ============================================================
# T27: 采集配置中心页面
# ============================================================

@router.get("/crawl/plans", response_class=HTMLResponse)
def crawl_plans_page(session: dict | None = Depends(get_current_admin)):
    """采集方案管理列表页"""
    body = (
        '<section class="panel">\n'
        '  <div class="crawl-plans-header" style="display:flex;justify-content:space-between;align-items:center;margin-bottom:15px;">\n'
        '    <h2 style="margin:0;">📂 采集方案管理</h2>\n'
        '    <div>\n'
        '      <button class="btn btn-primary" onclick="crawlPlans.openEditor()">+ 新建方案</button>\n'
        '      <button class="btn" onclick="crawlPlans.openImport()">批量导入</button>\n'
        '      <button class="btn" onclick="crawlPlans.refresh()">🔄 刷新</button>\n'
        '    </div>\n'
        '  </div>\n'
        '  <div class="crawl-filter" style="margin-bottom:15px;padding:10px;background:#f7f9fc;border-radius:6px;">\n'
        '    <input type="text" id="crawl-keyword" placeholder="搜索方案名称/域名..." style="width:200px;padding:6px 10px;border:1px solid #ddd;border-radius:4px;margin-right:10px;" />\n'
        '    <select id="crawl-status" style="padding:6px 10px;border:1px solid #ddd;border-radius:4px;margin-right:10px;">\n'
        '      <option value="">全部状态</option>\n'
        '      <option value="draft">草稿</option>\n'
        '      <option value="active">运行中</option>\n'
        '      <option value="paused">已暂停</option>\n'
        '      <option value="deleted">已删除</option>\n'
        '    </select>\n'
        '    <button class="btn btn-sm" onclick="crawlPlans.load()">筛选</button>\n'
        '  </div>\n'
        '  <div id="crawl-plans-container">加载中...</div>\n'
        '</section>\n'
        '\n'
        '<script src="/admin/static/js/crawl_plans.js?v=t31"></script>\n'
    )
    return _render_with_permission("crawl_plans", "btn.spider.view", body, session)


@router.get("/crawl/monitor", response_class=HTMLResponse)
def crawl_monitor_page(session: dict | None = Depends(get_current_admin)):
    """采集任务监控页"""
    body = (
        '<section class="panel">\n'
        '  <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:15px;">\n'
        '    <h2 style="margin:0;">📊 采集任务监控</h2>\n'
        '    <button class="btn btn-sm" onclick="crawlMonitor.refresh()">🔄 刷新</button>\n'
        '    <button class="btn btn-sm" onclick="crawlMonitor.autoToggle()" id="btn-auto">⏱ 自动刷新: 关</button>\n'
        '  </div>\n'
        '\n'
        '  <!-- 状态卡片 -->\n'
        '  <div id="crawl-stats" style="display:grid;grid-template-columns:repeat(4,1fr);gap:10px;margin-bottom:20px;"></div>\n'
        '\n'
        '  <!-- 运行记录列表 -->\n'
        '  <h3>🕒 最近运行记录</h3>\n'
        '  <div id="crawl-runs-container">加载中...</div>\n'
        '</section>\n'
        '\n'
        '<script src="/admin/static/js/crawl_monitor.js"></script>\n'
    )
    return _render_with_permission("crawl_monitor", "btn.spider.view", body, session)


@router.get("/crawl/fields", response_class=HTMLResponse)
def crawl_fields_page(session: dict | None = Depends(get_current_admin)):
    """字段模板库管理页"""
    body = (
        '<section class="panel">\n'
        '  <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:20px;">\n'
        '    <h2 style="margin:0;">🏷 字段模板库</h2>\n'
        '    <button class="btn btn-primary" onclick="crawlFields.addField()">+ 新增自定义字段</button>\n'
        '  </div>\n'
        '\n'
        '  <!-- 模板分类 -->\n'
        '  <div id="crawl-field-categories" style="margin-bottom:20px;">加载中...</div>\n'
        '\n'
        '  <!-- 字段列表 -->\n'
        '<div id="crawl-fields-list">加载中...</div>\n'
        '</section>\n'
        '\n'
        '<script src="/admin/static/js/crawl_fields.js"></script>\n'
    )
    return _render_with_permission("crawl_fields", "btn.spider.view", body, session)


# ============================================================================
# T31: 可视化采集配置编辑器（原子化步骤向导 + 三栏布局）
# 入口: /admin/crawl/steps-editor 或 /admin/crawl/steps-editor?plan_id=xxx
# ============================================================================

@router.get("/crawl/steps-editor", response_class=HTMLResponse)
def crawl_steps_editor_page(session: dict | None = Depends(get_current_admin)):
    partials_path = Path(__file__).parent / "templates" / "partials" / "crawl_step_editor.html"
    try:
        partial_html = partials_path.read_text(encoding="utf-8")
    except Exception:
        partial_html = (
            '<section class="panel"><h3>⚠ 编辑器模板未找到</h3>'
            '<p class="muted">未能加载 templates/partials/crawl_step_editor.html。请检查文件存在性和权限。</p>'
            '</section>'
        )
    body = (
        '<section class="panel">\n'
        '  <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:12px;">\n'
        '    <h2 style="margin:0;">🧩 可视化采集配置编辑器</h2>\n'
        '    <div>\n'
        '      <a class="btn btn-primary" href="/admin/crawl/steps-editor">新建方案</a>\n'
        '      <span class="muted"> 可通过 URL 参数 plan_id=xxx 打开旧方案进行编辑/自动转换</span>\n'
        '    </div>\n'
        '  </div>\n'
        '</section>\n'
        '\n'
        + partial_html
        + '\n'
        '<script src="/admin/static/js/crawl_step_editor.js?v=t33"></script>\n'
        '<link rel="stylesheet" href="/admin/static/css/admin.css?v=t33"/>\n'
    )
    return _render_with_permission("crawl_steps_editor", "btn.spider.view", body, session)
