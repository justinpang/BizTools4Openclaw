"""web_admin/pages — HTML 页面路由（新分组布局 + 权限控制的 HTML 页面）。"""

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
# 工具：渲染新 layout（顶栏 + 左侧分组菜单 + 主内容区）
# ---------------------------------------------------------------------------
def _layout_v2(title: str, active_key: str, body_html: str, session: dict | None) -> str:
    """新布局（所有内部页面调用）。"""
    username = session.get("username", "admin") if session else "guest"
    role = (session.get("role") or ROLE_SUPER_ADMIN) if session else ROLE_SUPER_ADMIN
    role_label = ROLE_LABELS.get(role, role)

    # 1) 菜单：按角色过滤
    menu_groups = filter_menu_by_role(role) if session else []

    # 2) 面包屑
    crumbs = breadcrumb_for(active_key)

    # 3) 权限集合（前端用于过滤按钮）
    perms = sorted(get_permissions_for_role(role)) if session else []

    # 4) 注入 bootstrap JSON
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

    # 渲染左侧分组菜单 HTML
    sidebar_html = ""
    for g in menu_groups:
        items_html = ""
        for it in g["items"]:
            active_cls = " active" if it["key"] == active_key else ""
            items_html += (
                f'<a class="menu-item{active_cls}" href="{it["href"]}" data-key="{it["key"]}">'
                f'<span class="menu-item-icon">{it.get("icon", "")}</span>'
                f'<span class="menu-item-title">{it["title"]}</span>'
                f'</a>'
            )
        if items_html:
            sidebar_html += (
                f'<div class="menu-group" data-group="{g["group_key"]}">'
                f'<div class="menu-group-title"><span class="menu-group-icon">{g.get("icon", "")}</span>'
                f'<span>{g["title"]}</span></div>'
                f'<div class="menu-group-items">{items_html}</div>'
                f'</div>'
            )

    # 面包屑 HTML
    crumbs_html = " / ".join(
        (f'<a class="crumb-link" href="{c.get("href", "#")}">{c["title"]}</a>' if c.get("href") else f'<span class="crumb">{c["title"]}</span>')
        for c in crumbs
    )

    # 顶栏右侧：角色标签 + 用户名 + 登出
    user_zone_html = (
        f'<span class="role-tag role-{role}">{role_label}</span>'
        f'<span class="user-name">{username}</span>'
        f'<form method="POST" action="/admin/logout" class="logout-form" style="display:inline;margin-left:8px;">'
        f'<button type="submit" class="btn btn-sm">登出</button>'
        f'</form>'
    )

    return f"""<!doctype html>
<html lang="zh-CN">
<head>
<meta charset="utf-8"/>
<meta name="viewport" content="width=device-width,initial-scale=1"/>
<title>{title} · BizTools4Openclaw 管理后台</title>
<link rel="stylesheet" href="/admin/static/css/admin.css"/>
</head>
<body class="page-v2 page-{active_key}">
  <div class="layout-v2">
    <aside class="sidebar-v2" id="sidebar">
      <div class="brand-v2">BizTools4Openclaw</div>
      <div class="sidebar-inner" id="sidebar-inner">{sidebar_html}</div>
    </aside>
    <main class="content-v2">
      <header class="topbar-v2">
        <div class="breadcrumb" id="breadcrumb">{crumbs_html}</div>
        <div class="topbar-right">
          <input class="global-search" id="global-search" type="text" placeholder="搜索菜单（按 ↵ 跳转）"/>
          <div class="user-area-v2">{user_zone_html}</div>
        </div>
      </header>
      <section class="page-title-section">
        <h1 class="page-title">{title}</h1>
      </section>
      <section class="page-body">
        {body_html}
      </section>
    </main>
  </div>
<script id="admin-init-json" type="application/json">{init_json}</script>
<script src="/admin/static/js/admin.js"></script>
</body>
</html>
"""


# ---------------------------------------------------------------------------
# 登录 / 登出
# ---------------------------------------------------------------------------
def _login_page_html(error_msg: str | None = None) -> str:
    err = f'<div class="login-error">{error_msg}</div>' if error_msg else ""
    return f"""<!doctype html>
<html lang="zh-CN">
<head>
<meta charset="utf-8"/>
<meta name="viewport" content="width=device-width,initial-scale=1"/>
<title>登录 · BizTools4Openclaw 管理后台</title>
<link rel="stylesheet" href="/admin/static/css/admin.css"/>
</head>
<body class="login-body">
  <div class="login-card">
    <h1>🔒 管理后台登录</h1>
    <p class="hint">账号 / 密码由运维配置在 .env。登录后将按角色显示可见菜单。</p>
    {err}
    <form method="POST" action="/admin/login" class="login-form">
      <label>账号
        <input type="text" name="username" required autocomplete="username" placeholder="请输入账号"/>
      </label>
      <label>密码
        <input type="password" name="password" required autocomplete="current-password" placeholder="请输入密码"/>
      </label>
      <button type="submit" class="btn btn-primary">登 录</button>
    </form>
    <p class="footer">© BizTools4Openclaw · 会话加密存储，自动过期。</p>
  </div>
</body>
</html>
"""


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
# 页面渲染辅助：统一权限校验 + 渲染模板
# ---------------------------------------------------------------------------
def _render_with_permission(active_key: str, perm: str, body_html: str, session: dict | None) -> HTMLResponse:
    """对页面使用按钮级权限（其实是"页面级权限"）进行校验，无权限则渲染 403。"""
    if not session:
        return RedirectResponse(url="/admin/login", status_code=302)
    role = session.get("role") or ROLE_SUPER_ADMIN
    if not has_permission(role, perm) or not role_can_view_menu(role, active_key):
        # 权限不足
        forbidden_body = _forbidden_body(active_key, missing_perm=perm)
        return HTMLResponse(_layout_v2("权限不足", "403", forbidden_body, session))
    # 正常渲染
    return HTMLResponse(_layout_v2(_page_title(active_key), active_key, body_html, session))


def _page_title(active_key: str) -> str:
    """根据 active_key 返回页面标题。"""
    map_ = {
        "dashboard": "数据看板",
        "spider": "爬虫任务",
        "leads": "商机线索",
        "channels": "渠道账号",
        "sales": "销售分配",
        "audit_log": "操作日志",
        "accounts": "账号管理",
        "empty": "空状态示例",
        "403": "权限不足",
    }
    return map_.get(active_key, "管理后台")


def _forbidden_body(active_key: str, missing_perm: str) -> str:
    return f"""
    <div class="empty-state">
      <div class="empty-state-icon">🚫</div>
      <div class="empty-state-title">权限不足</div>
      <div class="empty-state-desc">
        当前角色无权访问该页面（<code>{active_key}</code>，缺少权限
        <code>{missing_perm}</code>）。请联系超级管理员授权。
      </div>
      <div class="empty-state-actions">
        <a class="btn btn-primary" href="/admin/dashboard">返回数据看板</a>
      </div>
    </div>
"""


# ---------------------------------------------------------------------------
# 业务页面（保持极简 body_html，具体功能由前端 JS 渲染）
# ---------------------------------------------------------------------------
@router.get("/dashboard", response_class=HTMLResponse)
def dashboard_page(session: dict | None = Depends(get_current_admin)):
    body = """
    <section class="stats-grid" id="stats-grid">
      <div class="stat-card"><div class="label">爬虫任务</div><div class="value" data-key="spider_tasks">-</div></div>
      <div class="stat-card"><div class="label">抓取总量</div><div class="value" data-key="crawled_total">-</div></div>
      <div class="stat-card"><div class="label">有效线索</div><div class="value" data-key="leads_total">-</div></div>
      <div class="stat-card"><div class="label">触达批次</div><div class="value" data-key="send_total">-</div></div>
      <div class="stat-card"><div class="label">渠道账号</div><div class="value" data-key="accounts_total">-</div></div>
    </section>
    <section class="panel">
      <h3>📊 销售转化漏斗</h3>
      <div id="funnel-area" class="funnel-area"><div class="empty-inline">暂无数据</div></div>
    </section>
    <section class="panel">
      <h3>🕓 最近调度任务</h3>
      <div id="recent-tasks"><div class="empty-inline">暂无数据</div></div>
    </section>
"""
    return _render_with_permission("dashboard", "btn.dashboard.view", body, session)


@router.get("/spider", response_class=HTMLResponse)
def spider_page(session: dict | None = Depends(get_current_admin)):
    body = """
    <section class="panel">
      <h3>➕ 新增 / 编辑任务</h3>
      <form class="row-form" data-requires-permission="btn.spider.create" onsubmit="return admin.createSpiderTask(event)">
        <label>任务 ID <input type="text" name="job_id" placeholder="例如 spider_hourly"/></label>
        <label>爬虫名称 <select id="spider-name-select" name="spider_name"><option>（加载中）</option></select></label>
        <label>Cron <input type="text" name="cron" value="*/30 * * * *"/></label>
        <label>关键词 <input type="text" name="keywords" value="商机,采购,ERP"/></label>
        <label>最大页数 <input type="number" name="max_pages" value="20" min="1"/></label>
        <button class="btn btn-primary" type="submit" data-requires-permission="btn.spider.create">保存任务</button>
      </form>
    </section>
    <section class="panel">
      <h3>📋 已登记任务</h3>
      <table class="data-table" id="tasks-table">
        <thead><tr><th>任务 ID</th><th>爬虫</th><th>Cron</th><th>关键词</th><th>状态</th><th>下次运行</th><th>操作</th></tr></thead>
        <tbody id="tasks-body"><tr><td colspan="7" class="empty">加载中…</td></tr></tbody>
      </table>
    </section>
    <section class="panel">
      <h3>📖 抓取日志</h3>
      <div class="row">
        <input type="text" id="log-job-id" placeholder="输入 task/job id"/>
        <button class="btn" onclick="admin.loadSpiderLogs()">查看</button>
      </div>
      <pre id="logs-out" class="code-out">(空)</pre>
    </section>
"""
    return _render_with_permission("spider", "btn.spider.view", body, session)


@router.get("/leads", response_class=HTMLResponse)
def leads_page(session: dict | None = Depends(get_current_admin)):
    body = """
    <section class="panel">
      <h3>🔎 筛选</h3>
      <div class="row">
        <input type="text" id="keyword" placeholder="关键词（标题/客户）"/>
        <select id="status">
          <option value="">全部状态</option>
          <option value="PENDING">待复核</option>
          <option value="APPROVED">已通过</option>
          <option value="REJECTED">已拒绝</option>
        </select>
        <button class="btn btn-primary" onclick="admin.loadLeads()">查询</button>
      </div>
    </section>
    <section class="panel">
      <h3>📋 线索列表</h3>
      <table class="data-table">
        <thead><tr><th>ID</th><th>标题</th><th>客户</th><th>状态</th><th>操作</th></tr></thead>
        <tbody id="leads-body"><tr><td colspan="5" class="empty">加载中…</td></tr></tbody>
      </table>
    </section>
    <section class="panel" data-requires-permission="btn.leads.add_blacklist">
      <h3>🛑 黑名单管理</h3>
      <form class="row-form" onsubmit="return admin.addBlacklist(event)">
        <label>类型 <select name="type"><option value="phone">手机号</option><option value="email">邮箱</option><option value="company_name">公司名</option><option value="domain">域名</option></select></label>
        <label>标识 <input type="text" name="identifier" placeholder="标识"/></label>
        <label>原因 <input type="text" name="reason" placeholder="如无效商机"/></label>
        <button class="btn btn-danger" type="submit">加入黑名单</button>
      </form>
      <div class="row" style="margin-top:12px;">
        <button class="btn btn-sm" onclick="admin.loadBlacklist()">加载黑名单</button>
      </div>
      <div id="blacklist-body" class="code-out">(点击加载)</div>
    </section>
"""
    return _render_with_permission("leads", "btn.leads.view", body, session)


@router.get("/channels", response_class=HTMLResponse)
def channels_page(session: dict | None = Depends(get_current_admin)):
    body = """
    <section class="panel">
      <h3>➕ 新增渠道账号</h3>
      <form class="row-form" data-requires-permission="btn.channels.create" onsubmit="return admin.createAccount(event)">
        <label>渠道 <select name="channel">
          <option value="email">Email</option>
          <option value="wechat">企业微信</option>
          <option value="feishu">飞书</option>
          <option value="dingtalk">钉钉</option>
        </select></label>
        <label>账号 ID <input type="text" name="account_id" placeholder="biztools_sender_01"/></label>
        <label>用户名 <input type="text" name="username" placeholder="显示名称"/></label>
        <label>密码（加密存储，不回显明文） <input type="password" name="password" required/></label>
        <label>每日发送额度 <input type="number" name="quota" value="500" min="1"/></label>
        <button class="btn btn-primary" type="submit">保存</button>
      </form>
    </section>
    <section class="panel">
      <h3>📋 渠道账号（密钥/密码永远脱敏显示）</h3>
      <div id="channels-wrap"><div class="empty-inline">加载中…</div></div>
    </section>
"""
    return _render_with_permission("channels", "btn.channels.view", body, session)


@router.get("/sales", response_class=HTMLResponse)
def sales_page(session: dict | None = Depends(get_current_admin)):
    body = """
    <section class="panel">
      <h3>🧑‍💼 销售人员</h3>
      <form class="row-form" data-requires-permission="btn.sales.create" onsubmit="return admin.upsertPerson(event)">
        <label>销售 ID <input type="text" name="sales_id" placeholder="s_001"/></label>
        <label>姓名 <input type="text" name="name" placeholder="张三"/></label>
        <label>行业（逗号分隔）<input type="text" name="industries" placeholder="制造业,电商"/></label>
        <label>权重 <input type="number" step="0.1" name="weight" value="1.0"/></label>
        <label>手机（脱敏显示） <input type="text" name="phone" placeholder="仅存储，不回显明文"/></label>
        <label>邮箱（脱敏显示） <input type="text" name="email" placeholder="a@b.com"/></label>
        <button class="btn btn-primary" type="submit">保存</button>
      </form>
      <table class="data-table">
        <thead><tr><th>ID</th><th>姓名</th><th>行业</th><th>权重</th><th>手机</th><th>邮箱</th></tr></thead>
        <tbody id="persons-body"><tr><td colspan="6" class="empty">加载中…</td></tr></tbody>
      </table>
    </section>
    <section class="panel">
      <h3>🎯 商机分配</h3>
      <form class="row-form" data-requires-permission="btn.sales.assign" onsubmit="return admin.doAssign(event)">
        <label>商机 ID <input type="text" name="opportunity_id" placeholder="opp_001"/></label>
        <label>客户 <input type="text" name="customer" placeholder="某某公司"/></label>
        <label>销售 <input type="text" name="sales_id" placeholder="留空=自动"/></label>
        <button class="btn btn-primary" type="submit">分配</button>
      </form>
      <table class="data-table">
        <thead><tr><th>分配 ID</th><th>商机</th><th>销售</th><th>状态</th><th>时间</th></tr></thead>
        <tbody id="assignments-body"><tr><td colspan="5" class="empty">加载中…</td></tr></tbody>
      </table>
    </section>
    <section class="panel">
      <h3>📞 跟进记录</h3>
      <form class="row-form" data-requires-permission="btn.sales.record_followup" onsubmit="return admin.recordFollowup(event)">
        <label>商机 ID <input type="text" name="opportunity_id"/></label>
        <label>渠道 <select name="channel"><option>phone</option><option>email</option><option>meeting</option><option>wechat</option></select></label>
        <label>内容 <input type="text" name="content" placeholder="通话内容简要"/></label>
        <label>销售 ID <input type="text" name="sales_id" placeholder="留空=当前用户"/></label>
        <button class="btn btn-primary" type="submit">记录</button>
      </form>
      <table class="data-table">
        <thead><tr><th>ID</th><th>商机</th><th>渠道</th><th>内容</th><th>操作人</th><th>时间</th></tr></thead>
        <tbody id="followups-body"><tr><td colspan="6" class="empty">加载中…</td></tr></tbody>
      </table>
    </section>
    <section class="panel">
      <h3>⏰ 逾期跟进</h3>
      <table class="data-table">
        <thead><tr><th>商机</th><th>销售</th><th>上次</th><th>提示</th></tr></thead>
        <tbody id="overdue-body"><tr><td colspan="4" class="empty">加载中…</td></tr></tbody>
      </table>
      <div class="row" style="margin-top:12px;"><button class="btn btn-sm" onclick="admin.loadOverdue()">刷新</button></div>
    </section>
"""
    return _render_with_permission("sales", "btn.sales.view", body, session)


@router.get("/audit_log", response_class=HTMLResponse)
def audit_page(session: dict | None = Depends(get_current_admin)):
    body = """
    <section class="panel">
      <h3>🔎 日志筛选</h3>
      <div class="row">
        <label>角色 <select id="f-role">
          <option value="">全部</option>
          <option value="super_admin">超级管理员</option>
          <option value="ops">运营岗</option>
          <option value="sales">销售岗</option>
          <option value="compliance">合规岗</option>
        </select></label>
        <label>操作类型 <select id="f-op">
          <option value="">全部</option>
          <option>READ</option><option>CREATE</option><option>UPDATE</option>
          <option>DELETE</option><option>VIEW_SECRET</option><option>EXPORT</option>
          <option>LOGIN</option><option>LOGOUT</option>
        </select></label>
        <label>关键词 <input type="text" id="f-keyword" placeholder="用户名 / 路径 / 内容"/></label>
        <button class="btn btn-primary" onclick="admin.loadAuditLogsEnhanced()">查询</button>
        <button class="btn btn-sm" data-requires-permission="btn.audit.export" onclick="admin.exportAuditLogs()">导出 CSV</button>
      </div>
    </section>
    <section class="panel">
      <h3>📋 日志列表</h3>
      <table class="data-table" id="audit-table">
        <thead><tr>
          <th>时间</th><th>用户</th><th>角色</th><th>IP</th><th>操作</th>
          <th>路径/内容</th><th>状态</th><th>耗时</th><th>trace_id</th>
        </tr></thead>
        <tbody id="audit-body"><tr><td colspan="9" class="empty">加载中…</td></tr></tbody>
      </table>
      <div class="row pagination">
        <span id="audit-summary" class="muted">—</span>
        <button class="btn btn-sm" onclick="admin.prevAuditPage()">上一页</button>
        <span id="audit-page-info">第 1 页</span>
        <button class="btn btn-sm" onclick="admin.nextAuditPage()">下一页</button>
      </div>
    </section>
"""
    return _render_with_permission("audit_log", "btn.audit.view", body, session)


# ---------------------------------------------------------------------------
# 新页面：账号管理（仅 super_admin）
# ---------------------------------------------------------------------------
@router.get("/system/accounts", response_class=HTMLResponse)
def accounts_page(session: dict | None = Depends(get_current_admin)):
    body = """
    <section class="panel">
      <h3>➕ 新增账号</h3>
      <form class="row-form" onsubmit="return admin.createAdminAccount(event)">
        <label>账号 <input type="text" name="username" required placeholder="新账号名"/></label>
        <label>角色 <select name="role">
          <option value="ops">运营岗</option>
          <option value="sales">销售岗</option>
          <option value="compliance">合规岗</option>
          <option value="super_admin">超级管理员</option>
        </select></label>
        <label>初始密码 <input type="password" name="password_plain" required/></label>
        <button class="btn btn-primary" type="submit">创建</button>
      </form>
      <p class="muted">说明：创建成功后将在数据库中记录 <code>CREATE_ACCOUNT</code> 审计。账号信息通过进程内字典管理，进程重启将重置为 .env 配置。</p>
    </section>

    <section class="panel">
      <h3>📋 账号列表</h3>
      <table class="data-table" id="accounts-table">
        <thead><tr><th>账号</th><th>角色</th><th>状态</th><th>创建时间</th><th>操作</th></tr></thead>
        <tbody id="accounts-body"><tr><td colspan="5" class="empty">加载中…</td></tr></tbody>
      </table>
    </section>
"""
    return _render_with_permission("accounts", "btn.system.accounts", body, session)


# ---------------------------------------------------------------------------
# 通用：403 / 空状态示例 页面
# ---------------------------------------------------------------------------
@router.get("/403", response_class=HTMLResponse)
def page_403(session: dict | None = Depends(get_current_admin)):
    body = _forbidden_body("403", missing_perm="(访问页面时校验)")
    return HTMLResponse(_layout_v2("权限不足", "403", body, session))


@router.get("/empty", response_class=HTMLResponse)
def page_empty(session: dict | None = Depends(get_current_admin)):
    body = """
    <div class="empty-state">
      <div class="empty-state-icon">📭</div>
      <div class="empty-state-title">这里什么也没有</div>
      <div class="empty-state-desc">这是空状态组件的示例。当数据未准备好时，将显示类似内容。</div>
      <div class="empty-state-actions">
        <a class="btn btn-primary" href="/admin/dashboard">返回数据看板</a>
      </div>
    </div>

    <section class="panel" style="margin-top:24px;">
      <h3>🔁 加载状态示例</h3>
      <div class="loading-state" id="loading-demo"><div class="spinner"></div> <span>正在加载数据…</span></div>
    </section>
"""
    # 空状态页面所有已登录角色可见
    return _render_with_permission("empty", "btn.dashboard.view", body, session)


__all__ = ["router"]
