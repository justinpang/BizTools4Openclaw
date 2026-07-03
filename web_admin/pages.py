"""web_admin/pages — HTML 页面路由（纯字符串模板，零依赖）。"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse

from web_admin.auth import (
    SESSION_COOKIE,
    delete_session,
    get_current_admin,
    handle_login_post,
)
from configs.settings import settings
from web_admin.menu import MENU

router = APIRouter(tags=["admin-pages"])


def _layout(title: str, active_key: str, body_html: str, username: str = "admin") -> str:
    menu_html = "\n".join(
        f'<a class="menu-link{" active" if m["key"] == active_key else ""}" href="{m["href"]}">'
        f'{m["icon"]} <span>{m["title"]}</span></a>'
        for m in MENU
    )
    return f"""<!doctype html>
<html lang="zh-CN">
<head>
<meta charset="utf-8"/>
<meta name="viewport" content="width=device-width,initial-scale=1"/>
<title>{title} · BizTools4Openclaw</title>
<link rel="stylesheet" href="/admin/static/css/admin.css"/>
</head>
<body class="page page-{active_key}">
  <div class="layout">
    <aside class="sidebar">
      <div class="brand">BizTools4Openclaw</div>
      {menu_html}
    </aside>
    <main class="content">
      <header class="topbar">
        <h2>{title}</h2>
        <div class="user-area">
          <span>{username}</span>
          <form method="POST" action="/admin/logout" style="display:inline;margin-left:12px;">
            <button type="submit" class="btn btn-sm">登出</button>
          </form>
        </div>
      </header>
      {body_html}
    </main>
  </div>
<script src="/admin/static/js/admin.js"></script>
<script>window.__PAGE__ = "{active_key}";</script>
</body>
</html>"""


def _login_page_html(error_msg: str | None = None) -> str:
    err = f'<div style="color:#dc2626;margin-bottom:12px;">{error_msg}</div>' if error_msg else ""
    return f"""<!doctype html>
<html lang="zh-CN">
<head>
<meta charset="utf-8"/>
<meta name="viewport" content="width=device-width,initial-scale=1"/>
<title>登录 · BizTools4Openclaw</title>
<link rel="stylesheet" href="/admin/static/css/admin.css"/>
</head>
<body class="login-body">
  <div class="login-card">
    <h1>🔒 管理后台登录</h1>
    <p class="hint">账号 / 密码由运维配置（如使用默认配置，请尽快修改）。</p>
    {err}
    <form method="POST" action="/admin/login">
      <label>账号 <input type="text" name="username" required placeholder="admin"/></label>
      <label>密码 <input type="password" name="password" required placeholder="••••••"/></label>
      <button type="submit">登 录</button>
    </form>
    <p class="footer">© BizTools4Openclaw · 会话加密存储，自动过期。</p>
  </div>
</body>
</html>"""


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
    ok, token, msg = handle_login_post(username, password, client_ip=client_ip)
    if not ok:
        return HTMLResponse(_login_page_html(msg))
    resp = RedirectResponse(url="/admin/dashboard", status_code=302)
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


@router.get("/dashboard", response_class=HTMLResponse)
def dashboard_page(session: dict | None = Depends(get_current_admin)):
    if not session:
        return RedirectResponse(url="/admin/login", status_code=302)
    body = """
    <section class="stats-grid" id="stats-grid"></section>
    <section class="panel">
      <h3>📊 销售转化漏斗（近 7 天）</h3>
      <div id="funnel-area" class="funnel-area"></div>
    </section>
    <section class="panel">
      <h3>🕓 最近调度任务</h3>
      <div id="recent-tasks"></div>
    </section>"""
    return HTMLResponse(_layout("数据看板", "dashboard", body, session.get("username", "admin")))


@router.get("/spider", response_class=HTMLResponse)
def spider_page(session: dict | None = Depends(get_current_admin)):
    if not session:
        return RedirectResponse(url="/admin/login", status_code=302)
    body = """
    <section class="panel">
      <h3>➕ 新增 / 编辑任务</h3>
      <form class="row-form" onsubmit="return admin.createSpiderTask(event)">
        <label>任务 ID <input type="text" name="job_id" placeholder="例如 spider_hourly"/></label>
        <label>爬虫名称 <select id="spider-name-select" name="spider_name"></select></label>
        <label>Cron <input type="text" name="cron" value="*/30 * * * *"/></label>
        <label>关键词 <input type="text" name="keywords" value="商机,采购,ERP"/></label>
        <label>最大页数 <input type="number" name="max_pages" value="20" min="1"/></label>
        <button class="btn btn-primary" type="submit">保存任务</button>
      </form>
    </section>
    <section class="panel">
      <h3>📋 已登记任务</h3>
      <table class="data-table">
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
    <section class="panel">
      <h3>⚠️ 风控异常记录</h3>
      <div id="risks-out" class="code-out">(点击刷新查看)</div>
      <button class="btn btn-sm" onclick="admin.loadRisks()">刷新</button>
    </section>"""
    return HTMLResponse(_layout("爬虫任务", "spider", body, session.get("username", "admin")))


@router.get("/leads", response_class=HTMLResponse)
def leads_page(session: dict | None = Depends(get_current_admin)):
    if not session:
        return RedirectResponse(url="/admin/login", status_code=302)
    body = """
    <section class="panel">
      <h3>🔎 筛选</h3>
      <div class="row">
        <input type="text" id="keyword" placeholder="关键词（标题/客户）"/>
        <select id="status">
          <option value="">全部状态</option><option value="PENDING">待复核</option>
          <option value="APPROVED">已通过</option><option value="REJECTED">已拒绝</option>
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
    <section class="panel">
      <h3>🛑 手动添加黑名单</h3>
      <form class="row-form" onsubmit="return admin.addBlacklist(event)">
        <label>类型 <select name="type">
          <option value="phone">手机号</option>
          <option value="email">邮箱</option>
          <option value="company_name">公司名</option>
          <option value="domain">域名</option>
        </select></label>
        <label>标识 <input type="text" name="identifier" placeholder="标识"/></label>
        <label>原因 <input type="text" name="reason" placeholder="如无效商机"/></label>
        <button class="btn btn-danger" type="submit">加入黑名单</button>
      </form>
    </section>
    <section class="panel">
      <h3>📚 当前黑名单</h3>
      <div id="blacklist-body" class="code-out">(点击加载)</div>
      <button class="btn btn-sm" onclick="admin.loadBlacklist()">加载</button>
    </section>"""
    return HTMLResponse(_layout("商机线索", "leads", body, session.get("username", "admin")))


@router.get("/channels", response_class=HTMLResponse)
def channels_page(session: dict | None = Depends(get_current_admin)):
    if not session:
        return RedirectResponse(url="/admin/login", status_code=302)
    body = """
    <section class="panel">
      <h3>➕ 新增账号</h3>
      <form class="row-form" onsubmit="return admin.createAccount(event)">
        <label>渠道 <select name="channel">
          <option value="email">Email</option><option value="wechat">企业微信</option>
          <option value="feishu">飞书</option><option value="dingtalk">钉钉</option>
        </select></label>
        <label>账号 ID <input type="text" name="account_id" placeholder="biztools_sender_01"/></label>
        <label>用户名 <input type="text" name="username" placeholder="显示名称"/></label>
        <label>密码（加密存储，不回显明文）<input type="password" name="password" required/></label>
        <label>每日发送额度 <input type="number" name="quota" value="500" min="1"/></label>
        <button class="btn btn-primary" type="submit">保存</button>
      </form>
    </section>
    <section class="panel">
      <h3>📋 渠道账号（密码永远以 ******** 显示）</h3>
      <div id="channels-wrap"></div>
    </section>"""
    return HTMLResponse(_layout("渠道账号", "channels", body, session.get("username", "admin")))


@router.get("/sales", response_class=HTMLResponse)
def sales_page(session: dict | None = Depends(get_current_admin)):
    if not session:
        return RedirectResponse(url="/admin/login", status_code=302)
    body = """
    <section class="panel">
      <h3>🧑‍💼 销售人员</h3>
      <form class="row-form" onsubmit="return admin.upsertPerson(event)">
        <label>销售 ID <input type="text" name="sales_id" placeholder="s_001"/></label>
        <label>姓名 <input type="text" name="name" placeholder="张三"/></label>
        <label>行业（逗号分隔）<input type="text" name="industries" placeholder="制造业,电商"/></label>
        <label>权重 <input type="number" step="0.1" name="weight" value="1.0"/></label>
        <label>手机 <input type="text" name="phone" placeholder="仅存储，不回显明文"/></label>
        <label>邮箱 <input type="text" name="email" placeholder="a@b.com"/></label>
        <button class="btn btn-primary" type="submit">保存</button>
      </form>
      <table class="data-table">
        <thead><tr><th>ID</th><th>姓名</th><th>行业</th><th>权重</th><th>手机</th><th>邮箱</th></tr></thead>
        <tbody id="persons-body"><tr><td colspan="6" class="empty">加载中…</td></tr></tbody>
      </table>
    </section>
    <section class="panel">
      <h3>🎯 商机分配</h3>
      <form class="row-form" onsubmit="return admin.doAssign(event)">
        <label>商机 ID <input type="text" name="opportunity_id" placeholder="opp_001"/></label>
        <label>客户 <input type="text" name="customer" placeholder="某某公司"/></label>
        <label>销售 <input type="text" name="sales_id" placeholder="留空=自动"/></label>
        <button class="btn btn-primary" type="submit">分配</button>
      </form>
      <table class="data-table">
        <thead><tr><th>分配 ID</th><th>商机</th><th>销售</th><th>状态</th><th>时间</th></tr></thead>
        <tbody id="assignments-body"></tbody>
      </table>
    </section>
    <section class="panel">
      <h3>📞 跟进记录</h3>
      <form class="row-form" onsubmit="return admin.recordFollowup(event)">
        <label>商机 ID <input type="text" name="opportunity_id"/></label>
        <label>渠道 <select name="channel"><option>phone</option><option>email</option><option>meeting</option><option>wechat</option></select></label>
        <label>内容 <input type="text" name="content" placeholder="通话内容简要"/></label>
        <label>销售 ID <input type="text" name="sales_id" placeholder="留空=当前用户"/></label>
        <button class="btn btn-primary" type="submit">记录</button>
      </form>
      <table class="data-table">
        <thead><tr><th>ID</th><th>商机</th><th>渠道</th><th>内容</th><th>操作人</th><th>时间</th></tr></thead>
        <tbody id="followups-body"></tbody>
      </table>
    </section>
    <section class="panel">
      <h3>⏰ 逾期跟进</h3>
      <table class="data-table">
        <thead><tr><th>商机</th><th>销售</th><th>上次</th><th>提示</th></tr></thead>
        <tbody id="overdue-body"></tbody>
      </table>
      <button class="btn btn-sm" onclick="admin.loadOverdue()">刷新</button>
    </section>"""
    return HTMLResponse(_layout("销售管理", "sales", body, session.get("username", "admin")))


@router.get("/audit_log", response_class=HTMLResponse)
def audit_page(session: dict | None = Depends(get_current_admin)):
    if not session:
        return RedirectResponse(url="/admin/login", status_code=302)
    body = """
    <section class="panel">
      <div class="row">
        <label>近 <input type="number" id="limit" value="50" min="10" max="500"/> 条</label>
        <button class="btn btn-primary" onclick="admin.loadAuditLogs()">刷新</button>
      </div>
      <table class="data-table">
        <thead><tr><th>时间</th><th>用户</th><th>IP</th><th>路径</th><th>状态</th><th>耗时 ms</th></tr></thead>
        <tbody id="audit-body"><tr><td colspan="6" class="empty">加载中…</td></tr></tbody>
      </table>
    </section>"""
    return HTMLResponse(_layout("操作日志", "audit_log", body, session.get("username", "admin")))


__all__ = ["router", "_login_page_html", "_layout"]
