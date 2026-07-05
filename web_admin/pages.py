# -*- coding: utf-8 -*-
"""web_admin/pages - HTML page routing (new grouped layout + permission-controlled HTML pages)."""

from __future__ import annotations

import json

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
            sidebar_html += (
                '<div class="menu-group" data-group="' + g["group_key"] + '">'
                '<div class="menu-group-title"><span class="menu-group-icon">' + g.get("icon", "") + '</span>'
                '<span>' + g["title"] + '</span></div>'
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
        '<button type="submit" class="btn btn-sm">Log out</button>'
        '</form>'
    )

    return (
        '<!doctype html>\n'
        '<html lang="zh-CN">\n'
        '<head>\n'
        '<meta charset="utf-8"/>\n'
        '<meta name="viewport" content="width=device-width,initial-scale=1"/>\n'
        '<title>' + title + ' \u00b7 BizTools4Openclaw Admin Panel</title>\n'
        '<link rel="stylesheet" href="/admin/static/css/admin.css"/>\n'
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
        '          <input class="global-search" id="global-search" type="text" placeholder="Search menu (press Enter)"/>\n'
        '          <div class="user-area-v2">' + user_zone_html + '</div>\n'
        '        </div>\n'
        '      </header>\n'
        '      <section class="page-title-section">\n'
        '        <h1 class="page-title">' + title + '</h1>\n'
        '      </section>\n'
        '      <section class="page-body">\n'
        '        ' + body_html + '\n'
        '      </section>\n'
        '    </main>\n'
        '  </div>\n'
        '<script id="admin-init-json" type="application/json">' + init_json + '</script>\n'
        '<script src="/admin/static/js/admin.js"></script>\n'
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
        '<title>Login \u00b7 BizTools4Openclaw Admin Panel</title>\n'
        '<link rel="stylesheet" href="/admin/static/css/admin.css"/>\n'
        '</head>\n'
        '<body class="login-body">\n'
        '  <div class="login-card">\n'
        '    <h1>[Lock] Admin Panel Login</h1>\n'
        '    <p class="hint">Username / password configured by ops in .env. Visible menus depend on role.</p>\n'
        '    ' + err + '\n'
        '    <form method="POST" action="/admin/login" class="login-form">\n'
        '      <label>Account\n'
        '        <input type="text" name="username" required autocomplete="username" placeholder="Enter username"/>\n'
        '      </label>\n'
        '      <label>Password\n'
        '        <input type="password" name="password" required autocomplete="current-password" placeholder="Enter password"/>\n'
        '      </label>\n'
        '      <button type="submit" class="btn btn-primary">LOG IN</button>\n'
        '    </form>\n'
        '    <p class="footer">&copy; BizTools4Openclaw \u00b7 Sessions encrypted, auto-expire.</p>\n'
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
        return HTMLResponse(_layout_v2("Permission denied", "403", forbidden_body, session))
    return HTMLResponse(_layout_v2(_page_title(active_key), active_key, body_html, session))


def _page_title(active_key: str) -> str:
    """Return page title from active_key."""
    map_ = {
        "dashboard": "Dashboard",
        "spider": "Spider Tasks",
        "spider_detail": "Task Detail",
        "leads": "Leads",
        "channels": "Channel Accounts",
        "sales": "Sales Assignment",
        "audit_log": "Audit Log",
        "accounts": "Account Management",
        "compliance_review": "Compliance Review",
        "compliance_config": "Compliance Rules",
        "notifications": "Message Center",
        "data_center_dashboard": "Funnel Dashboard",
        "data_center_collection": "Collection Stage",
        "data_center_cleaning": "Cleaning Stage",
        "data_center_compliance": "Compliance Stage",
        "data_center_grading": "Grading Stage",
        "data_center_outreach": "Outreach Stage",
        "data_center_sales": "Sales Closing Stage",
        "data_center_opportunity": "Opportunity Timeline",
        "empty": "Empty State Demo",
        "403": "Permission Denied",
    }
    return map_.get(active_key, "Admin Panel")


def _forbidden_body(active_key: str, missing_perm: str) -> str:
    return (
        '<div class="empty-state">\n'
        '  <div class="empty-state-icon">[NoEntry]</div>\n'
        '  <div class="empty-state-title">Permission Denied</div>\n'
        '  <div class="empty-state-desc">\n'
        '    Current role cannot access this page (<code>' + active_key + '</code>, missing permission\n'
        '    <code>' + missing_perm + '</code>). Please ask the super admin.\n'
        '  </div>\n'
        '  <div class="empty-state-actions">\n'
        '    <a class="btn btn-primary" href="/admin/dashboard">Back to Dashboard</a>\n'
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
        '  <div class="stat-card"><div class="label">Spider Tasks</div><div class="value" data-key="spider_tasks">-</div></div>\n'
        '  <div class="stat-card"><div class="label">Total Crawled</div><div class="value" data-key="crawled_total">-</div></div>\n'
        '  <div class="stat-card"><div class="label">Valid Leads</div><div class="value" data-key="leads_total">-</div></div>\n'
        '  <div class="stat-card"><div class="label">Sent Batches</div><div class="value" data-key="send_total">-</div></div>\n'
        '  <div class="stat-card"><div class="label">Channel Accounts</div><div class="value" data-key="accounts_total">-</div></div>\n'
        '</section>\n'
        '<section class="panel">\n'
        '  <h3>[Chart] Sales Conversion Funnel</h3>\n'
        '  <div id="funnel-area" class="funnel-area"><div class="empty-inline">No data</div></div>\n'
        '</section>\n'
        '<section class="panel">\n'
        '  <h3>[Clock] Recent Scheduled Tasks</h3>\n'
        '  <div id="recent-tasks"><div class="empty-inline">No data</div></div>\n'
        '</section>\n'
    )
    return _render_with_permission("dashboard", "btn.dashboard.view", body, session)


@router.get("/spider", response_class=HTMLResponse)
def spider_page(session: dict | None = Depends(get_current_admin)):
    body = (
        '<section class="panel channel-filter-row">\n'
        '  <h3>[Folder] 7-Channel Quick Entry</h3>\n'
        '  <div class="channel-cards" id="channel-cards">\n'
        '    <a class="channel-card" data-channel="generic_web" href="/admin/spider?channel=generic_web">\n'
        '      <span class="channel-icon">[Globe]</span>\n'
        '      <span class="channel-title">General Web/Forum</span>\n'
        '      <span class="channel-desc">Portal/Forum/BBS crawling</span>\n'
        '    </a>\n'
        '    <a class="channel-card" data-channel="short_video" href="/admin/spider?channel=short_video">\n'
        '      <span class="channel-icon">[Movie]</span>\n'
        '      <span class="channel-title">Short Video</span>\n'
        '      <span class="channel-desc">Douyin/Kuaishou/Video Channel</span>\n'
        '    </a>\n'
        '    <a class="channel-card" data-channel="xhs" href="/admin/spider?channel=xhs">\n'
        '      <span class="channel-icon">[Book]</span>\n'
        '      <span class="channel-title">Little Red Book</span>\n'
        '      <span class="channel-desc">Notes/Videos/Likes filtering</span>\n'
        '    </a>\n'
        '    <a class="channel-card" data-channel="qa_platform" href="/admin/spider?channel=qa_platform">\n'
        '      <span class="channel-icon">[Q]</span>\n'
        '      <span class="channel-title">Q&A Platform</span>\n'
        '      <span class="channel-desc">Zhihu/Baidu Knows</span>\n'
        '    </a>\n'
        '    <a class="channel-card" data-channel="b2b_supply" href="/admin/spider?channel=b2b_supply">\n'
        '      <span class="channel-icon">[Factory]</span>\n'
        '      <span class="channel-title">B2B Supply</span>\n'
        '      <span class="channel-desc">Alibaba/Huicong</span>\n'
        '    </a>\n'
        '    <a class="channel-card" data-channel="bidding" href="/admin/spider?channel=bidding">\n'
        '      <span class="channel-icon">[Clipboard]</span>\n'
        '      <span class="channel-title">Bidding</span>\n'
        '      <span class="channel-desc">Gov/Enterprise procurement</span>\n'
        '    </a>\n'
        '    <a class="channel-card" data-channel="company_biz" href="/admin/spider?channel=company_biz">\n'
        '      <span class="channel-icon">[Building]</span>\n'
        '      <span class="channel-title">Corporate Business</span>\n'
        '      <span class="channel-desc">Qcc/Tianyancha/Industry disclosure</span>\n'
        '    </a>\n'
        '  </div>\n'
        '</section>\n'
        '<section class="panel">\n'
        '  <h3>[+] New Collection Task</h3>\n'
        '  <div class="row">\n'
        '    <label>Channel Type <select id="task-channel-select" name="channel" data-requires-permission="btn.spider.create">\n'
        '      <option value="">Please select a channel</option>\n'
        '      <option value="generic_web">General Web/Forum</option>\n'
        '      <option value="short_video">Short Video</option>\n'
        '      <option value="xhs">Little Red Book</option>\n'
        '      <option value="qa_platform">Q&A Platform</option>\n'
        '      <option value="b2b_supply">B2B Supply</option>\n'
        '      <option value="bidding">Bidding</option>\n'
        '      <option value="company_biz">Corporate Business</option>\n'
        '    </select></label>\n'
        '  </div>\n'
        '  <form class="row-form" id="task-create-form" data-requires-permission="btn.spider.create" onsubmit="return admin.createSpiderTask(event)">\n'
        '    <input type="hidden" name="channel" id="task-channel-hidden"/>\n'
        '    <label>Task ID <input type="text" name="job_id" placeholder="e.g. sp_daily_001"/></label>\n'
        '    <label>Task Name <input type="text" name="task_name" placeholder="Task description"/></label>\n'
        '    <label>Speed Level (1-5) <input type="number" name="speed_level" value="3" min="1" max="5"/></label>\n'
        '    <label>Crawl Limit <input type="number" name="max_items" value="500" min="1"/></label>\n'
        '    <label>Schedule Mode <select name="schedule_mode"><option value="off">Manual</option><option value="hourly">Hourly</option><option value="daily">Daily</option></select></label>\n'
        '    <label>Cron <input type="text" name="cron" value="*/30 * * * *"/></label>\n'
        '    <label>Time Range <input type="text" name="time_range" placeholder="e.g. Last 7 days"/></label>\n'
        '    <div id="channel-specific-fields" style="width:100%;margin-top:12px;">\n'
        '      <span class="muted">Please select a channel type to display custom parameters</span>\n'
        '    </div>\n'
        '  </form>\n'
        '  <div class="compliance-agreement-block" style="margin-top:16px;padding:16px;border:1px solid #ddd;border-radius:6px;background:#f8f9fa;">\n'
        '    <h4 style="margin:0 0 12px 0;font-size:15px;">[Scale] Data Collection Compliance Checklist (required before save)</h4>\n'
        '    <div id="compliance-agreement-text" class="code-out" style="max-height:120px;overflow-y:auto;margin-bottom:12px;">Loading compliance agreement...</div>\n'
        '    <div class="row" style="flex-wrap:wrap;gap:12px;">\n'
        '      <label><input type="checkbox" name="compliance_agreed" value="true" form="task-create-form"/> I have read and agree to the Data Collection Compliance Agreement</label>\n'
        '    </div>\n'
        '    <div class="row" style="flex-wrap:wrap;gap:12px;margin-top:8px;">\n'
        '      <label>Data Purpose <select name="compliance_data_purpose" form="task-create-form">\n'
        '        <option value="">Please select</option>\n'
        '        <option value="opportunity">Opportunity Analysis</option>\n'
        '        <option value="market_research">Market Research</option>\n'
        '        <option value="bidding_decision">Bidding Decision</option>\n'
        '        <option value="industry_monitoring">Industry Monitoring</option>\n'
        '      </select></label>\n'
        '      <label>Retention Period <select name="compliance_retention" form="task-create-form">\n'
        '        <option value="">Please select</option>\n'
        '        <option value="30d">30 days</option>\n'
        '        <option value="90d">90 days</option>\n'
        '        <option value="180d">180 days</option>\n'
        '        <option value="1y">1 year</option>\n'
        '      </select></label>\n'
        '    </div>\n'
        '    <div class="row" style="flex-wrap:wrap;gap:12px;margin-top:8px;">\n'
        '      <label><input type="checkbox" name="compliance_privacy" value="true" form="task-create-form"/> I commit to not collecting personal privacy information (phone/email/ID number)</label>\n'
        '    </div>\n'
        '    <div class="row" style="flex-wrap:wrap;gap:12px;margin-top:8px;">\n'
        '      <label><input type="checkbox" name="compliance_site_verified" value="true" form="task-create-form"/> I verify that the collection sites do not violate compliance rules (no forbidden keywords in URLs/titles)</label>\n'
        '    </div>\n'
        '    <div class="row" style="margin-top:12px;">\n'
        '      <button class="btn btn-primary" type="submit" form="task-create-form" data-requires-permission="btn.spider.create">Save Task</button>\n'
        '    </div>\n'
        '  </div>\n'
        '</section>\n'
        '<section class="panel">\n'
        '  <h3>[Search] Task Filtering</h3>\n'
        '  <div class="row">\n'
        '    <label>Status <select id="filter-status">\n'
        '      <option value="">All</option>\n'
        '      <option value="PENDING_APPROVAL">Pending Approval</option>\n'
        '      <option value="REJECTED">Rejected</option>\n'
        '      <option value="READY">Ready</option>\n'
        '      <option value="RUNNING">Running</option>\n'
        '      <option value="PAUSED">Paused</option>\n'
        '      <option value="COMPLETED">Completed</option>\n'
        '      <option value="FAILED">Failed</option>\n'
        '      <option value="TERMINATED">Terminated</option>\n'
        '    </select></label>\n'
        '    <label>Channel <select id="filter-channel">\n'
        '      <option value="">All</option>\n'
        '      <option value="generic_web">General Web/Forum</option>\n'
        '      <option value="short_video">Short Video</option>\n'
        '      <option value="xhs">Little Red Book</option>\n'
        '      <option value="qa_platform">Q&A Platform</option>\n'
        '      <option value="b2b_supply">B2B Supply</option>\n'
        '      <option value="bidding">Bidding</option>\n'
        '      <option value="company_biz">Corporate Business</option>\n'
        '    </select></label>\n'
        '    <label>Task Name/ID <input type="text" id="filter-keyword" placeholder="Fuzzy search"/></label>\n'
        '    <button class="btn btn-primary" onclick="admin.loadSpiderFiltered()">Apply Filter</button>\n'
        '    <button class="btn" onclick="admin.loadSpiderFiltered()">Refresh</button>\n'
        '  </div>\n'
        '</section>\n'
        '<section class="panel">\n'
        '  <h3>[Clipboard] Collection Task List</h3>\n'
        '  <table class="data-table" id="tasks-table">\n'
        '    <thead><tr>\n'
        '      <th>Task ID</th><th>Channel</th><th>Task Name</th><th>Status</th>\n'
        '      <th>Count</th><th>Failed</th><th>Next Run</th><th>Actions</th>\n'
        '    </tr></thead>\n'
        '    <tbody id="tasks-body"><tr><td colspan="8" class="empty">Loading...</td></tr></tbody>\n'
        '  </table>\n'
        '</section>\n'
        '<section class="panel">\n'
        '  <h3>[Scroll] Crawl Logs</h3>\n'
        '  <div class="row">\n'
        '    <input type="text" id="log-job-id" placeholder="Enter task/job id"/>\n'
        '    <button class="btn" onclick="admin.loadSpiderLogs()">View</button>\n'
        '  </div>\n'
        '  <pre id="logs-out" class="code-out">(empty)</pre>\n'
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
        '  <h3>[Gear] Task Base Config (read-only)</h3>',
        '  <div id="detail-config" class="task-detail-config-grid">',
        '    <span class="muted">Loading task ' + job_id + ' basic config...</span>',
        '  </div>',
        '</section>',
        '<section class="panel task-detail-progress">',
        '  <h3>[Chart] Collection Progress</h3>',
        '  <div id="detail-progress">',
        '    <span class="muted">Loading collection progress...</span>',
        '  </div>',
        '</section>',
        '<section class="panel">',
        '  <h3>[Wrench] Task Actions</h3>',
        '  <div class="row">',
        '    <button class="btn btn-sm" data-requires-permission="btn.spider.run" onclick="admin.runTask(\'' + job_id + '\')">Run Now</button>',
        '    <button class="btn btn-sm" data-requires-permission="btn.spider.pause" onclick="admin.pauseTask(\'' + job_id + '\')">Pause</button>',
        '    <button class="btn btn-sm" data-requires-permission="btn.spider.resume" onclick="admin.resumeTask(\'' + job_id + '\')">Resume</button>',
        '    <button class="btn btn-sm" data-requires-permission="btn.spider.retry" onclick="admin.retryTask(\'' + job_id + '\')">Retry (resume crawl)</button>',
        '    <button class="btn btn-sm" data-requires-permission="btn.spider.terminate" onclick="admin.terminateTask(\'' + job_id + '\')">Terminate Task</button>',
        '    <button class="btn btn-sm btn-danger" data-requires-permission="btn.spider.delete" onclick="admin.deleteTask(\'' + job_id + '\')">Delete Task</button>',
        '  </div>',
        '</section>',
        '<section class="panel">',
        '  <h3>[Memo] Raw Data Collection Details (auto-desi...ensitized)</h3>',
        '  <table class="data-table spider-item-table" id="items-table">',
        '    <thead><tr>',
        '      <th>ID</th><th>Title/Content</th><th>Author</th><th>Phone</th><th>Email</th>',
        '    </tr></thead>',
        '    <tbody id="items-body"><tr><td colspan="5" class="empty">Loading...</td></tr></tbody>',
        '  </table>',
        '  <div class="row" style="margin-top:12px;" id="items-pagination"></div>',
        '</section>',
        '<section class="panel">',
        '  <h3>[Scroll] Task Run Logs (auto-refresh)</h3>',
        '  <div id="task-logs" class="spider-logs">(empty)</div>',
        '</section>',
        '<script>',
        '  (function () {',
        '    if (typeof admin !== "undefined" && admin.loadSpiderDetail) {',
        '      admin.loadSpiderDetail("' + job_id + '");',
        '    }',
        '    window.addEventListener("beforeunload", function () {',
        '      if (admin && admin.stopTaskLogRefresh) admin.stopTaskLogRefresh();',
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
        '  <h3>[Search] Filter</h3>\n'
        '  <div class="row">\n'
        '    <input type="text" id="keyword" placeholder="Keyword (title/customer)"/>\n'
        '    <select id="status">\n'
        '      <option value="">All Statuses</option>\n'
        '      <option value="PENDING">Pending Review</option>\n'
        '      <option value="APPROVED">Approved</option>\n'
        '      <option value="REJECTED">Rejected</option>\n'
        '    </select>\n'
        '    <button class="btn btn-primary" onclick="admin.loadLeads()">Query</button>\n'
        '  </div>\n'
        '</section>\n'
        '<section class="panel">\n'
        '  <h3>[Clipboard] Leads List</h3>\n'
        '  <table class="data-table">\n'
        '    <thead><tr><th>ID</th><th>Title</th><th>Customer</th><th>Status</th><th>Actions</th></tr></thead>\n'
        '    <tbody id="leads-body"><tr><td colspan="5" class="empty">Loading...</td></tr></tbody>\n'
        '  </table>\n'
        '</section>\n'
        '<section class="panel" data-requires-permission="btn.leads.add_blacklist">\n'
        '  <h3>[Stop] Blacklist Management</h3>\n'
        '  <form class="row-form" onsubmit="return admin.addBlacklist(event)">\n'
        '    <label>Type <select name="type"><option value="phone">Phone</option><option value="email">Email</option><option value="company_name">Company Name</option><option value="domain">Domain</option></select></label>\n'
        '    <label>Identifier <input type="text" name="identifier" placeholder="identifier"/></label>\n'
        '    <label>Reason <input type="text" name="reason" placeholder="e.g. Invalid opportunity"/></label>\n'
        '    <button class="btn btn-danger" type="submit">Add to Blacklist</button>\n'
        '  </form>\n'
        '  <div class="row" style="margin-top:12px;">\n'
        '    <button class="btn btn-sm" onclick="admin.loadBlacklist()">Load Blacklist</button>\n'
        '  </div>\n'
        '  <div id="blacklist-body" class="code-out">(click to load)</div>\n'
        '</section>\n'
    )
    return _render_with_permission("leads", "btn.leads.view", body, session)


@router.get("/channels", response_class=HTMLResponse)
def channels_page(session: dict | None = Depends(get_current_admin)):
    body = (
        '<section class="panel">\n'
        '  <h3>[+] New Channel Account</h3>\n'
        '  <form class="row-form" data-requires-permission="btn.channels.create" onsubmit="return admin.createAccount(event)">\n'
        '    <label>Channel <select name="channel">\n'
        '      <option value="email">Email</option>\n'
        '      <option value="wechat">WeCom</option>\n'
        '      <option value="feishu">Feishu</option>\n'
        '      <option value="dingtalk">DingTalk</option>\n'
        '    </select></label>\n'
        '    <label>Account ID <input type="text" name="account_id" placeholder="biztools_sender_01"/></label>\n'
        '    <label>Username <input type="text" name="username" placeholder="Display name"/></label>\n'
        '    <label>Password (encrypted, not echoed) <input type="password" name="password" required/></label>\n'
        '    <label>Daily Send Limit <input type="number" name="quota" value="500" min="1"/></label>\n'
        '    <button class="btn btn-primary" type="submit">Save</button>\n'
        '  </form>\n'
        '</section>\n'
        '<section class="panel">\n'
        '  <h3>[Clipboard] Channel Accounts (keys/passwords always desensitized)</h3>\n'
        '  <div id="channels-wrap"><div class="empty-inline">Loading...</div></div>\n'
        '</section>\n'
    )
    return _render_with_permission("channels", "btn.channels.view", body, session)


@router.get("/sales", response_class=HTMLResponse)
def sales_page(session: dict | None = Depends(get_current_admin)):
    body = (
        '<section class="panel">\n'
        '  <h3>[Briefcase] Sales Personnel</h3>\n'
        '  <form class="row-form" data-requires-permission="btn.sales.create" onsubmit="return admin.upsertPerson(event)">\n'
        '    <label>Sales ID <input type="text" name="sales_id" placeholder="s_001"/></label>\n'
        '    <label>Name <input type="text" name="name" placeholder="John Doe"/></label>\n'
        '    <label>Industry (comma-separated) <input type="text" name="industries" placeholder="Manufacturing,E-commerce"/></label>\n'
        '    <label>Weight <input type="number" step="0.1" name="weight" value="1.0"/></label>\n'
        '    <label>Phone (desensitized display) <input type="text" name="phone" placeholder="Stored only, not echoed in plain"/></label>\n'
        '    <label>Email (desensitized display) <input type="text" name="email" placeholder="a@b.com"/></label>\n'
        '    <button class="btn btn-primary" type="submit">Save</button>\n'
        '  </form>\n'
        '  <table class="data-table">\n'
        '    <thead><tr><th>ID</th><th>Name</th><th>Industry</th><th>Weight</th><th>Phone</th><th>Email</th></tr></thead>\n'
        '    <tbody id="persons-body"><tr><td colspan="6" class="empty">Loading...</td></tr></tbody>\n'
        '  </table>\n'
        '</section>\n'
        '<section class="panel">\n'
        '  <h3>[Target] Opportunity Assignment</h3>\n'
        '  <form class="row-form" data-requires-permission="btn.sales.assign" onsubmit="return admin.doAssign(event)">\n'
        '    <label>Opportunity ID <input type="text" name="opportunity_id" placeholder="opp_001"/></label>\n'
        '    <label>Customer <input type="text" name="customer" placeholder="ACME Inc"/></label>\n'
        '    <label>Sales <input type="text" name="sales_id" placeholder="empty=auto"/></label>\n'
        '    <button class="btn btn-primary" type="submit">Assign</button>\n'
        '  </form>\n'
        '  <table class="data-table">\n'
        '    <thead><tr><th>Assign ID</th><th>Opportunity</th><th>Sales</th><th>Status</th><th>Time</th></tr></thead>\n'
        '    <tbody id="assignments-body"><tr><td colspan="5" class="empty">Loading...</td></tr></tbody>\n'
        '  </table>\n'
        '</section>\n'
        '<section class="panel">\n'
        '  <h3>[Phone] Follow-up Records</h3>\n'
        '  <form class="row-form" data-requires-permission="btn.sales.record_followup" onsubmit="return admin.recordFollowup(event)">\n'
        '    <label>Opportunity ID <input type="text" name="opportunity_id"/></label>\n'
        '    <label>Channel <select name="channel"><option>phone</option><option>email</option><option>meeting</option><option>wechat</option></select></label>\n'
        '    <label>Content <input type="text" name="content" placeholder="Brief call notes"/></label>\n'
        '    <label>Sales ID <input type="text" name="sales_id" placeholder="empty=current user"/></label>\n'
        '    <button class="btn btn-primary" type="submit">Record</button>\n'
        '  </form>\n'
        '  <table class="data-table">\n'
        '    <thead><tr><th>ID</th><th>Opportunity</th><th>Channel</th><th>Content</th><th>Operator</th><th>Time</th></tr></thead>\n'
        '    <tbody id="followups-body"><tr><td colspan="6" class="empty">Loading...</td></tr></tbody>\n'
        '  </table>\n'
        '</section>\n'
        '<section class="panel">\n'
        '  <h3>[Clock] Overdue Follow-ups</h3>\n'
        '  <table class="data-table">\n'
        '    <thead><tr><th>Opportunity</th><th>Sales</th><th>Last</th><th>Hint</th></tr></thead>\n'
        '    <tbody id="overdue-body"><tr><td colspan="4" class="empty">Loading...</td></tr></tbody>\n'
        '  </table>\n'
        '  <div class="row" style="margin-top:12px;"><button class="btn btn-sm" onclick="admin.loadOverdue()">Refresh</button></div>\n'
        '</section>\n'
    )
    return _render_with_permission("sales", "btn.sales.view", body, session)


@router.get("/audit_log", response_class=HTMLResponse)
def audit_page(session: dict | None = Depends(get_current_admin)):
    body = (
        '<section class="panel">\n'
        '  <h3>[Search] Log Filter</h3>\n'
        '  <div class="row">\n'
        '    <label>Role <select id="f-role">\n'
        '      <option value="">All</option>\n'
        '      <option value="super_admin">Super Admin</option>\n'
        '      <option value="ops">Ops</option>\n'
        '      <option value="sales">Sales</option>\n'
        '      <option value="compliance">Compliance</option>\n'
        '    </select></label>\n'
        '    <label>Operation Type <select id="f-op">\n'
        '      <option value="">All</option>\n'
        '      <option>READ</option><option>CREATE</option><option>UPDATE</option>\n'
        '      <option>DELETE</option><option>VIEW_SECRET</option><option>EXPORT</option>\n'
        '      <option>LOGIN</option><option>LOGOUT</option>\n'
        '    </select></label>\n'
        '    <label>Keyword <input type="text" id="f-keyword" placeholder="username / path / content"/></label>\n'
        '    <button class="btn btn-primary" onclick="admin.loadAuditLogsEnhanced()">Query</button>\n'
        '    <button class="btn btn-sm" data-requires-permission="btn.audit.export" onclick="admin.exportAuditLogs()">Export CSV</button>\n'
        '  </div>\n'
        '</section>\n'
        '<section class="panel">\n'
        '  <h3>[Clipboard] Log List</h3>\n'
        '  <table class="data-table" id="audit-table">\n'
        '    <thead><tr>\n'
        '      <th>Time</th><th>User</th><th>Role</th><th>IP</th><th>Operation</th>\n'
        '      <th>Path/Content</th><th>Status</th><th>Duration</th><th>trace_id</th>\n'
        '    </tr></thead>\n'
        '    <tbody id="audit-body"><tr><td colspan="9" class="empty">Loading...</td></tr></tbody>\n'
        '  </table>\n'
        '  <div class="row pagination">\n'
        '    <span id="audit-summary" class="muted">-</span>\n'
        '    <button class="btn btn-sm" onclick="admin.prevAuditPage()">Prev</button>\n'
        '    <span id="audit-page-info">Page 1</span>\n'
        '    <button class="btn btn-sm" onclick="admin.nextAuditPage()">Next</button>\n'
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
        '  <h3>[+] New Account</h3>\n'
        '  <form class="row-form" onsubmit="return admin.createAdminAccount(event)">\n'
        '    <label>Account <input type="text" name="username" required placeholder="New username"/></label>\n'
        '    <label>Role <select name="role">\n'
        '      <option value="ops">Ops</option>\n'
        '      <option value="sales">Sales</option>\n'
        '      <option value="compliance">Compliance</option>\n'
        '      <option value="super_admin">Super Admin</option>\n'
        '    </select></label>\n'
        '    <label>Initial Password <input type="password" name="password_plain" required/></label>\n'
        '    <button class="btn btn-primary" type="submit">Create</button>\n'
        '  </form>\n'
        '  <p class="muted">Note: After creation, CREATE_ACCOUNT audit will be recorded in DB. Accounts managed in-process dict; process restart resets to .env config.</p>\n'
        '</section>\n'
        '<section class="panel">\n'
        '  <h3>[Clipboard] Account List</h3>\n'
        '  <table class="data-table" id="accounts-table">\n'
        '    <thead><tr><th>Account</th><th>Role</th><th>Status</th><th>Created At</th><th>Actions</th></tr></thead>\n'
        '    <tbody id="accounts-body"><tr><td colspan="5" class="empty">Loading...</td></tr></tbody>\n'
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
    return HTMLResponse(_layout_v2("Permission Denied", "403", body, session))


@router.get("/empty", response_class=HTMLResponse)
def page_empty(session: dict | None = Depends(get_current_admin)):
    body = (
        '<div class="empty-state">\n'
        '  <div class="empty-state-icon">[Mailbox]</div>\n'
        '  <div class="empty-state-title">Nothing here</div>\n'
        '  <div class="empty-state-desc">This is an example of an empty state component. Similar content will appear when data is not ready.</div>\n'
        '  <div class="empty-state-actions">\n'
        '    <a class="btn btn-primary" href="/admin/dashboard">Back to Dashboard</a>\n'
        '  </div>\n'
        '</div>\n'
        '<section class="panel" style="margin-top:24px;">\n'
        '  <h3>[Repeat] Loading State Example</h3>\n'
        '  <div class="loading-state" id="loading-demo"><div class="spinner"></div> <span>Loading data...</span></div>\n'
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
        '  <h3>[Scale] Pending Approval Tasks</h3>',
        '  <div class="row">',
        '    <label>Channel <select id="pending-channel-filter">',
        '      <option value="">All</option>',
        '      <option value="short_video">Short Video</option>',
        '      <option value="xhs">Little Red Book</option>',
        '      <option value="b2b_supply">B2B Supply</option>',
        '      <option value="generic_web">General Web</option>',
        '      <option value="qa_platform">Q&A Platform</option>',
        '      <option value="bidding">Bidding</option>',
        '      <option value="company_biz">Corporate Business</option>',
        '    </select></label>',
        '    <button class="btn btn-primary" data-requires-permission="btn.compliance.review" onclick="admin.loadPendingTasks()">Load Pending</button>',
        '  </div>',
        '  <table class="data-table" id="pending-tasks-table">',
        '    <thead><tr>',
        '      <th>Task ID</th><th>Channel</th><th>Task Name</th><th>Submitter</th>',
        '      <th>Submission Time</th><th>Data Purpose</th><th>Retention</th><th>Actions</th>',
        '    </tr></thead>',
        '    <tbody id="pending-tasks-body"><tr><td colspan="8" class="empty">Loading pending approval tasks...</td></tr></tbody>',
        '  </table>',
        '</section>',
        # 驳回弹窗（隐藏，点击驳回按钮显示）
        '<div id="reject-modal" class="modal" style="display:none;">',
        '  <div class="modal-content" style="max-width:500px;">',
        '    <h3 style="margin-top:0;">Reject Task</h3>',
        '    <textarea id="reject-reason" rows="5" style="width:100%;padding:8px;box-sizing:border-box;" placeholder="Please enter the reason for rejection (required)"></textarea>',
        '    <div class="row" style="justify-content:flex-end;gap:8px;margin-top:12px;">',
        '      <button class="btn" onclick="admin.closeRejectModal()">Cancel</button>',
        '      <button class="btn btn-danger" data-requires-permission="btn.compliance.reject" onclick="admin.submitReject()">Confirm Rejection</button>',
        '    </div>',
        '  </div>',
        '</div>',
        # 已审核记录
        '<section class="panel">',
        '  <h3>[Clipboard] Audit History</h3>',
        '  <div class="row">',
        '    <button class="btn" data-requires-permission="btn.compliance.review" onclick="admin.loadApprovalHistory()">Load Approval History</button>',
        '  </div>',
        '  <table class="data-table" id="approval-history-table">',
        '    <thead><tr>',
        '      <th>Task ID</th><th>Task Name</th><th>Channel</th><th>Submitter</th>',
        '      <th>Reviewer</th><th>Review Time</th><th>Decision</th><th>Rejection Reason</th>',
        '    </tr></thead>',
        '    <tbody id="approval-history-body"><tr><td colspan="8" class="empty">Click the button to load approval history...</td></tr></tbody>',
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
        '  <h3>[Gear] Channel Approval Rules</h3>',
        '  <p class="muted">High-risk channels require compliance officer approval; low-risk channels can be configured to skip review.</p>',
        '  <table class="data-table" id="channel-rules-table">',
        '    <thead><tr>',
        '      <th>Channel</th><th>Risk Level</th><th>Requires Approval</th><th>Actions</th>',
        '    </tr></thead>',
        '    <tbody id="channel-rules-body"><tr><td colspan="4" class="empty">Loading channel rules...</td></tr></tbody>',
        '  </table>',
        '</section>',
        # 合规协议文本
        '<section class="panel">',
        '  <h3>[File] Compliance Agreement Text</h3>',
        '  <p class="muted">This text will be displayed on the task creation page; the submitter must check it.</p>',
        '  <textarea id="agreement-text-edit" rows="12" style="width:100%;font-family:monospace;padding:8px;box-sizing:border-box;" placeholder="Loading compliance agreement text..."></textarea>',
        '  <div class="row" style="justify-content:flex-end;margin-top:12px;">',
        '    <button class="btn btn-primary" data-requires-permission="btn.compliance.config" onclick="admin.saveAgreementText()">Save Agreement</button>',
        '  </div>',
        '</section>',
        # 留存周期选项
        '<section class="panel">',
        '  <h3>[Calendar] Retention Period Options</h3>',
        '  <p class="muted">Comma-separated values, e.g.: 30d,90d,180d,1y</p>',
        '  <input type="text" id="retention-options-edit" style="width:100%;padding:8px;box-sizing:border-box;" placeholder="30d,90d,180d,1y"/>',
        '  <div class="row" style="justify-content:flex-end;margin-top:12px;">',
        '    <button class="btn btn-primary" data-requires-permission="btn.compliance.config" onclick="admin.saveRetentionOptions()">Save Retention Options</button>',
        '  </div>',
        '</section>',
        # 违规关键词黑名单
        '<section class="panel">',
        '  <h3>[Ban] Forbidden Keyword Blacklist</h3>',
        '  <p class="muted">Keywords included in task parameters (title, keywords, URL, etc.) will block task creation. Comma-separated values.</p>',
        '  <textarea id="forbidden-keywords-edit" rows="6" style="width:100%;font-family:monospace;padding:8px;box-sizing:border-box;" placeholder="phone,email,id card,..."></textarea>',
        '  <div class="row" style="justify-content:flex-end;margin-top:12px;">',
        '    <button class="btn btn-primary" data-requires-permission="btn.compliance.config" onclick="admin.saveForbiddenKeywords()">Save Blacklist</button>',
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
        '  <h3>[Bell] Recent Notifications</h3>',
        '  <div class="row" style="gap:8px;">',
        '    <button class="btn btn-sm" onclick="admin.loadNotificationsList()">Refresh</button>',
        '    <button class="btn btn-sm" data-requires-permission="btn.compliance.notification" onclick="admin.markAllNotificationsRead()">Mark All Read</button>',
        '  </div>',
        '  <table class="data-table" id="notifications-table">',
        '    <thead><tr>',
        '      <th>Time</th><th>Type</th><th>Title</th><th>Content</th><th>Status</th><th>Actions</th>',
        '    </tr></thead>',
        '    <tbody id="notifications-body"><tr><td colspan="6" class="empty">Loading notifications...</td></tr></tbody>',
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
        '  <div class="stat-card"><div class="label">[Sun] Today Added</div><div class="value" id="v-today-added">0</div><div class="sub" id="v-trend">—</div></div>',
        '  <div class="stat-card"><div class="label">[Folder] Total Leads</div><div class="value" id="v-total-leads">0</div></div>',
        '  <div class="stat-card"><div class="label">[Star] High Intent</div><div class="value" id="v-high-intent">0</div></div>',
        '  <div class="stat-card"><div class="label">[User] Pending Followup</div><div class="value" id="v-pending-followup">0</div></div>',
        '  <div class="stat-card"><div class="label">[Check] Closed/Won</div><div class="value" id="v-won">0</div></div>',
        '</section>',

        # 2) 6 阶段漏斗图
        '<section class="panel">',
        '  <h3>[Chart] Full-Link Funnel (6 Stages)</h3>',
        '  <div class="row" style="gap:8px;margin-bottom:12px;">',
        '    <button class="btn btn-sm" onclick="admin.loadFunnelChart()">Refresh Funnel</button>',
        '  </div>',
        '  <div id="funnel-chart" class="funnel-chart"><div class="empty-inline">Loading funnel data...</div></div>',
        '</section>',

        # 3) 6 阶段快速入口卡片
        '<section class="panel">',
        '  <h3>[Folder] 6 Stage Quick Entry</h3>',
        '  <div class="channel-cards" id="stage-cards">',
        '    <a class="channel-card" href="/admin/data_center/collection">',
        '      <span class="channel-icon">[Spider]</span><span class="channel-title">Collection Stage</span><span class="channel-desc">Crawled tasks & items</span>',
        '    </a>',
        '    <a class="channel-card" href="/admin/data_center/cleaning">',
        '      <span class="channel-icon">[Wand]</span><span class="channel-title">Cleaning Stage</span><span class="channel-desc">Structured, valid leads</span>',
        '    </a>',
        '    <a class="channel-card" href="/admin/data_center/compliance">',
        '      <span class="channel-icon">[Shield]</span><span class="channel-title">Compliance Stage</span><span class="channel-desc">PII detection, risk score</span>',
        '    </a>',
        '    <a class="channel-card" href="/admin/data_center/grading">',
        '      <span class="channel-icon">[Star]</span><span class="channel-title">Grading Stage</span><span class="channel-desc">A/B/C/D grade + score</span>',
        '    </a>',
        '    <a class="channel-card" href="/admin/data_center/outreach">',
        '      <span class="channel-icon">[Send]</span><span class="channel-title">Outreach Stage</span><span class="channel-desc">Email/IM sends + responses</span>',
        '    </a>',
        '    <a class="channel-card" href="/admin/data_center/sales">',
        '      <span class="channel-icon">[Money]</span><span class="channel-title">Sales Closing</span><span class="channel-desc">Followups, won/lost deals</span>',
        '    </a>',
        '  </div>',
        '</section>',

        # 4) 渠道分布 + 等级分布（两列）
        '<section class="panel">',
        '  <div class="row" style="gap:24px;flex-wrap:wrap;">',
        '    <div style="flex:1;min-width:320px;">',
        '      <h3>[Chart] Channel Distribution</h3>',
        '      <div id="channel-distribution" class="distribution-chart"><div class="empty-inline">Loading...</div></div>',
        '    </div>',
        '    <div style="flex:1;min-width:320px;">',
        '      <h3>[Chart] Grade Distribution</h3>',
        '      <div id="grade-distribution" class="distribution-chart"><div class="empty-inline">Loading...</div></div>',
        '    </div>',
        '  </div>',
        '</section>',

        # 5) 近 7 天趋势折线图
        '<section class="panel">',
        '  <h3>[Chart] 7-Day Trend (Leads / Won)</h3>',
        '  <div class="row" style="gap:8px;margin-bottom:12px;">',
        '    <button class="btn btn-sm" onclick="admin.loadTrendChart(\'leads\')">Leads Trend</button>',
        '    <button class="btn btn-sm" onclick="admin.loadTrendChart(\'won\')">Won Trend</button>',
        '  </div>',
        '  <div id="trend-chart" class="trend-chart"><div class="empty-inline">Loading trend data...</div></div>',
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
        '  <div class="stat-card"><div class="label">[Folder] Total Items</div><div class="value" id="' + body_id + '-total">0</div></div>',
        '  <div class="stat-card"><div class="label">[Check] Passed/Valid</div><div class="value" id="' + body_id + '-valid">0</div></div>',
        '  <div class="stat-card"><div class="label">[Alert] Exceptions</div><div class="value" id="' + body_id + '-exception">0</div></div>',
        '  <div class="stat-card"><div class="label">[Clock] Recent 24h</div><div class="value" id="' + body_id + '-recent">0</div></div>',
        '</section>',
        # 筛选栏
        '<section class="panel">',
        '  <h3>[Filter] ' + stage_title + ' — ' + stage_desc + '</h3>',
        '  <div class="row" style="gap:8px;flex-wrap:wrap;">',
        '    <label>Status <select id="' + body_id + '-filter-status">',
        '      <option value="">All</option><option value="APPROVED">Approved</option><option value="PENDING">Pending</option><option value="REJECTED">Rejected</option>',
        '    </select></label>',
        '    <label>Channel <select id="' + body_id + '-filter-channel">',
        '      <option value="">All</option><option value="generic_web">General Web</option><option value="short_video">Short Video</option><option value="xhs">Little Red Book</option><option value="qa_platform">Q&A Platform</option><option value="b2b_supply">B2B Supply</option><option value="bidding">Bidding</option><option value="company_biz">Corporate</option>',
        '    </select></label>',
        '    <label>Keyword <input type="text" id="' + body_id + '-filter-keyword" placeholder="Search..."/></label>',
        '    <button class="btn btn-sm" onclick="admin.loadStageList(\'' + stage_key + '\',\'' + body_id + '\',1)">Apply</button>',
        '    <button class="btn btn-sm" onclick="admin.loadStageList(\'' + stage_key + '\',\'' + body_id + '\',1)">Refresh</button>',
        '  </div>',
        '</section>',
        # 明细表格
        '<section class="panel">',
        '  <table class="data-table" id="' + body_id + '-table">',
        '    <thead><tr>',
        '      ' + "".join(["<th>" + h + "</th>" for h in table_headers]) + '<th>Actions</th>',
        '    </tr></thead>',
        '    <tbody id="' + body_id + '-body"><tr><td colspan="' + str(len(table_headers) + 1) + '" class="empty">Loading ' + stage_key + ' data...</td></tr></tbody>',
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
        stage_title="Collection Stage",
        stage_desc="Spider tasks and crawled items",
        table_headers=["Task ID", "Task Name", "Channel", "Status", "Crawled", "Failed", "Created At"],
        body_id="dc-collection",
    )
    return _render_with_permission("data_center_collection", "btn.data_center.view", body, session)


@router.get("/data_center/cleaning", response_class=HTMLResponse)
def data_center_cleaning_page(session: dict | None = Depends(get_current_admin)):
    """清洗结构化：结构化的商机线索条目"""
    body = _stage_detail_page_body(
        stage_key="cleaning",
        stage_title="Cleaning Stage",
        stage_desc="Structured and validated lead records",
        table_headers=["Lead ID", "Title", "Channel", "Company", "Contact", "Status", "Created"],
        body_id="dc-cleaning",
    )
    return _render_with_permission("data_center_cleaning", "btn.data_center.view", body, session)


@router.get("/data_center/compliance", response_class=HTMLResponse)
def data_center_compliance_page(session: dict | None = Depends(get_current_admin)):
    """合规校验：PII 检测、风险分数"""
    body = _stage_detail_page_body(
        stage_key="compliance",
        stage_title="Compliance Stage",
        stage_desc="PII detection and compliance scoring",
        table_headers=["Lead ID", "Title", "Channel", "Compliance Status", "Score", "Risk Level", "PII Types"],
        body_id="dc-compliance",
    )
    return _render_with_permission("data_center_compliance", "btn.data_center.view", body, session)


@router.get("/data_center/grading", response_class=HTMLResponse)
def data_center_grading_page(session: dict | None = Depends(get_current_admin)):
    """商机分级：A/B/C/D 等级 + 综合评分"""
    body = _stage_detail_page_body(
        stage_key="grading",
        stage_title="Grading Stage",
        stage_desc="Opportunity grade A/B/C/D + intent scoring",
        table_headers=["Lead ID", "Title", "Channel", "Grade", "Score", "Budget", "Urgency", "Tags"],
        body_id="dc-grading",
    )
    return _render_with_permission("data_center_grading", "btn.data_center.view", body, session)


@router.get("/data_center/outreach", response_class=HTMLResponse)
def data_center_outreach_page(session: dict | None = Depends(get_current_admin)):
    """客户触达：邮件/IM 发送批次记录"""
    body = _stage_detail_page_body(
        stage_key="outreach",
        stage_title="Outreach Stage",
        stage_desc="Email/IM sends and response tracking",
        table_headers=["Batch ID", "Title", "Target Lead", "Channel", "Target", "Success", "Failed", "Status", "Sent At"],
        body_id="dc-outreach",
    )
    return _render_with_permission("data_center_outreach", "btn.data_center.view", body, session)


@router.get("/data_center/sales", response_class=HTMLResponse)
def data_center_sales_page(session: dict | None = Depends(get_current_admin)):
    """销售闭环：跟进记录、成交/流失"""
    body = _stage_detail_page_body(
        stage_key="sales",
        stage_title="Sales Closing",
        stage_desc="Follow-ups, assignments, and won/lost deals",
        table_headers=["Lead ID", "Title", "Company", "Assignee", "Grade", "Status", "Followups", "Last Followup", "Value"],
        body_id="dc-sales",
    )
    return _render_with_permission("data_center_sales", "btn.data_center.view", body, session)


@router.get("/data_center/opportunity/{lead_id}", response_class=HTMLResponse)
def data_center_opportunity_page(lead_id: str, session: dict | None = Depends(get_current_admin)):
    """单商机全生命周期追踪：按时间线展示 6 阶段流转过程"""
    body_parts = [
        # 顶部：商机概览
        '<section class="panel">',
        '  <h3>[User] Opportunity Timeline — ' + escape_html(lead_id) + '</h3>',
        '  <div class="task-detail-config-grid" id="opp-info-grid">',
        '    <div class="kv"><div class="label">Lead ID</div><div class="value" id="opp-lead-id">' + escape_html(lead_id) + '</div></div>',
        '    <div class="kv"><div class="label">Title</div><div class="value" id="opp-title">Loading...</div></div>',
        '    <div class="kv"><div class="label">Company</div><div class="value" id="opp-company">Loading...</div></div>',
        '    <div class="kv"><div class="label">Channel</div><div class="value" id="opp-channel">Loading...</div></div>',
        '    <div class="kv"><div class="label">Grade</div><div class="value" id="opp-grade">Loading...</div></div>',
        '    <div class="kv"><div class="label">Score</div><div class="value" id="opp-score">Loading...</div></div>',
        '    <div class="kv"><div class="label">Status</div><div class="value" id="opp-status">Loading...</div></div>',
        '    <div class="kv"><div class="label">Contact (masked)</div><div class="value" id="opp-contact">Loading...</div></div>',
        '  </div>',
        '  <div class="row" style="gap:8px;margin-top:12px;">',
        '    <button class="btn btn-sm" onclick="admin.loadOpportunityTimeline(\'' + escape_html(lead_id) + '\')">Refresh Timeline</button>',
        '  </div>',
        '</section>',
        # 时间线
        '<section class="panel">',
        '  <h3>[Clock] Lifecycle Timeline</h3>',
        '  <div id="opp-timeline" class="timeline-container"><div class="empty-inline">Loading timeline data...</div></div>',
        '</section>',
        # 关联入口
        '<section class="panel">',
        '  <h3>[Link] Related Links</h3>',
        '  <div class="row" style="gap:8px;flex-wrap:wrap;">',
        '    <a class="btn btn-sm" href="/admin/spider" id="link-source-task">View Source Task</a>',
        '    <a class="btn btn-sm" href="/admin/leads">Back to Leads</a>',
        '    <a class="btn btn-sm" href="/admin/data_center/dashboard">Back to Funnel</a>',
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


# 工具：确保 escape_html 可用（在 pages.py 顶部已经导入 html 模块上下文）
def escape_html(s: str) -> str:
    return s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace('"', "&quot;").replace("'", "&#39;")


__all__ = ["router"]
