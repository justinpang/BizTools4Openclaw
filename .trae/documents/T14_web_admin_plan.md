# T14 · 轻量 Web 管理后台开发计划

> 可视化运维 · 线索与任务管理 · 基于 T01~T13 现有基建

---

## 一、仓库调研结论

**关键可用底层模块**（全部复用，不重复造轮子）：

| 功能 | 底层模块 | 关键能力 |
|------|----------|----------|
| 任务调度（爬虫定时） | `infra/task_scheduler.py` | `add_cron / add_interval / remove_job / list_jobs` |
| 异步任务队列 | `infra/task_queue.py` | `enqueue / get_status / list_tasks / cancel` |
| Redis 客户端 | `infra/redis_client.py` | `get_redis()` |
| 告警服务 | `infra/alerting.py` | `service_exception_sync()` |
| 日志服务 | `infra/logger_setup.py` | `get_logger()` |
| 全局设置 | `configs/settings.py` | `settings.xxx.*` |
| 爬虫列表/执行 | `business/multi_spider/registry.py` | `list_spiders() / run_spider_by_name()` |
| 渠道账号池 | `core/send_core/account_pool.py` | `AccountPool.channels() / all_accounts() / mark_banned()` |
| 商机黑名单 | `core/data_core/blacklist_filter.py` | `BlacklistFilter.add_item() / filter_batch()` |
| PII 脱敏 | `core/compliance/pii_mask.py` | `PIIMask.auto_mask()` |
| 触达批量 | `business/customer_send/registry.py` | `run_batch() / async_run() / list_runs()` |
| 销售漏斗/分配 | `business/sales_task/registry.py` | `assign() / remind() / get_funnel_stats() / transition()` |
| 现有 FastAPI 服务 | `adapter/main.py` | `app.include_router() 挂载子路由` |

**目录约束**：`web_admin/` 目录已存在（空 `__init__.py`），前后端代码全部放置于此目录，不新增项目根目录；不修改 `README.md / DEVELOP_RULES.md / docs/TASK_LIST.md`。

---

## 二、新增文件清单

```
configs/settings.py                                    (修改：追加 WebAdminSettings 类)

web_admin/
├── __init__.py                                        （已存在，内容不变/微调）
├── main.py                                            WebAdmin 路由包注册 + 挂载到 adapter.main.app
├── auth.py                                            账号密码登录 / Cookie+Redis 会话 / Depends
├── middleware.py                                      操作行为日志 + trace_id 注入
├── menu.py                                            菜单结构常量（左侧导航栏）
├── pages.py                                           页面级 HTTP endpoint（HTML 模板渲染）
│
├── api/
│   ├── __init__.py
│   ├── dashboard.py                                   简易数据看板（抓取/有效/触达/漏斗）
│   ├── spider_task.py                                 爬虫任务 CRUD / 启停 / 日志 / 风控
│   ├── lead_mgmt.py                                   商机线索列表 + 筛选 + 人工复核 + 黑名单
│   ├── channel_account.py                             邮件/企微/飞书账号维护 + 额度查看
│   └── sales_mgmt.py                                  销售配置 / 分配记录 / 跟进看板 / 逾期
│
├── templates/
│   ├── index.html                                     SPA 入口（包含内嵌 CSS / JS / 菜单渲染）
│   ├── login.html                                     登录页
│   └── partials/
│       ├── dashboard.html                             看板（数字卡片 + 简易条形图）
│       ├── spider_task.html                           爬虫任务表格 + 表单
│       ├── leads.html                                 商机线索表格 + 筛选
│       ├── channels.html                              渠道账号表格
│       └── sales.html                                 销售管理页面
│
└── static/
    ├── css/admin.css                                  统一样式（Tailwind-less · 手写）
    └── js/admin.js                                    JS：fetch API + 分页 + 表单提交
```

**单元测试**：
```
tests/test_t14_web_admin.py
```

---

## 三、后台页面路由 & 菜单结构

**根 URL 前缀**：`/admin` （挂载到现有 FastAPI 应用，与 OpenClaw `/api/v1/` 并址）

**菜单 & 路由**：

```
/                          → 重定向 /admin
├── /admin/login           GET  登录页 ·  POST  登录提交
│   /admin/logout          POST 登出（销毁 Redis 会话）
│
├── /admin/dashboard       GET  数据看板页面
│   GET  /api/admin/dashboard/stats        看板数据 JSON
│
├── /admin/spider          GET  爬虫任务管理页面
│   GET  /api/admin/spider/tasks           任务列表（含定时表达式、状态）
│   POST /api/admin/spider/task            新建任务
│   PUT  /api/admin/spider/task/{id}       编辑任务
│   POST /api/admin/spider/task/{id}/run   立即触发一次
│   POST /api/admin/spider/task/{id}/pause 暂停
│   POST /api/admin/spider/task/{id}/resume恢复
│   DEL  /api/admin/spider/task/{id}       删除
│   GET  /api/admin/spider/task/{id}/logs  抓取日志
│   GET  /api/admin/spider/risks           风控异常记录
│
├── /admin/leads           GET  商机线索管理
│   GET  /api/admin/leads                  线索列表（分页 + 筛选）
│   GET  /api/admin/leads/{id}             线索详情
│   POST /api/admin/leads/{id}/approve     人工复核通过
│   POST /api/admin/leads/{id}/reject      人工复核拒绝 → 加黑名单
│   POST /api/admin/leads/blacklist/add    手动加黑名单
│
├── /admin/channels        GET  渠道账号配置
│   GET  /api/admin/channels                账号列表（邮件/企微/飞书）
│   POST /api/admin/channels/account        新增/更新账号（密码仅写 Redis 不读回）
│   POST /api/admin/channels/{c}/ban/{id}   封禁
│   POST /api/admin/channels/{c}/unban/{id} 解封
│
├── /admin/sales           GET  销售管理
│   GET  /api/admin/sales/persons           销售配置列表
│   POST /api/admin/sales/person            新增/更新销售
│   GET  /api/admin/sales/assignments       分配记录
│   GET  /api/admin/sales/followups         待跟进看板
│   GET  /api/admin/sales/overdue           逾期告警
│
└── /admin/audit_log       GET  操作日志（仅读近 N 条）
    GET  /api/admin/audit/logs              行为日志 JSON
```

**菜单常量结构**（`web_admin/menu.py`）：

```python
MENU = [
    {"key": "dashboard",  "title": "数据看板", "icon": "📊", "href": "/admin/dashboard"},
    {"key": "spider",     "title": "爬虫任务", "icon": "🕷", "href": "/admin/spider"},
    {"key": "leads",      "title": "商机线索", "icon": "💼", "href": "/admin/leads"},
    {"key": "channels",   "title": "渠道账号", "icon": "📡", "href": "/admin/channels"},
    {"key": "sales",      "title": "销售管理", "icon": "👥", "href": "/admin/sales"},
    {"key": "audit_log",  "title": "操作日志", "icon": "📜", "href": "/admin/audit_log"},
]
```

---

## 四、登录鉴权 · Redis 会话存储设计

### 4.1 新增 `WebAdminSettings`（追加到 `configs/settings.py`）

```python
class WebAdminSettings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="", extra="ignore")

    WEB_ADMIN_ENABLED: bool = True
    WEB_ADMIN_PATH_PREFIX: str = "/admin"

    # 管理员账号（密码通过 bcrypt 哈希存储）
    WEB_ADMIN_USERNAME: str = "admin"
    WEB_ADMIN_PASSWORD_HASH: str = ""   # 若为空，首次启动自动提示初始化；或读取 env 明文即时 hash
    WEB_ADMIN_PASSWORD_PLAIN: str = ""  # 用于初次部署快速设置；启动后立即 hash
    WEB_ADMIN_SESSION_TTL_SECONDS: int = 60 * 60 * 8   # 会话 8 小时
    WEB_ADMIN_PAGE_SIZE: int = 20        # 页面默认分页条数
```

### 4.2 会话存储

- **载体**：`get_redis()` 提供的 Redis 连接
- **Key 结构**：
  - `web_admin:session:{session_token}` → JSON `{"username": "admin", "created_at": ts, "last_seen": ts, "ip": "..."}`
  - TTL = `WEB_ADMIN_SESSION_TTL_SECONDS`
- **Token 生成**：`secrets.token_urlsafe(32)` → `HttpOnly` Cookie `admin_session`
- **鉴权 Depends**：`require_admin(request: Request)`
  - 读取 `Cookie[admin_session]` → Redis 读 session → 存在且 TTL 刷新 → OK
  - 否则 `302 /admin/login` 或返回 `401`（按请求头 `Accept` 判断 API vs HTML）
- **密码存储**：首次启动若 `WEB_ADMIN_PASSWORD_HASH` 为空但 `WEB_ADMIN_PASSWORD_PLAIN` 非空，则 hash 后写入日志（仅一次）；不将明文写入库。

### 4.3 操作行为日志（审计）

每个写操作由 `web_admin/middleware.py` 记录：
- 记录字段：`timestamp / username / ip / method / path / query_keys / status_code / duration_ms / trace_id`
- 存储载体：Redis List `web_admin:audit_log`，保留最近 2000 条
- 高危操作（批量删除、密码修改、账号封禁）额外调用 `alerting.service_exception_sync()` 发告警

---

## 五、各功能页面数据调用链路

### 5.1 数据看板 (`web_admin/api/dashboard.py`)

| 指标 | 数据来源 | 调用方式 |
|------|----------|----------|
| 抓取总量 | `infra/task_queue.list_tasks(source="spider", limit=...)` | 统计条数 / 近 7 天 |
| 有效线索 | `business/data_clean` 清洗后存储（若暂无存储，返回 mock 数据） | 调用 pipeline 或 registry 暴露的统计接口 |
| 触达数量 | `business/customer_send/registry.list_runs()` + `AccountPool.available_count()` | 汇总近期批次 |
| 销售漏斗 | `business/sales_task/registry.get_funnel_stats(period_days=7)` | 直接调用 |

### 5.2 爬虫任务 (`web_admin/api/spider_task.py`)

| 操作 | 调用链路 |
|------|----------|
| 新增/编辑 | `TaskScheduler.add_cron(job_id=..., func=run_spider_by_name, kwargs={spider_name, keywords, ...}, expression=...)` |
| 立即触发 | 直接 `run_spider_by_name(...)` 同步执行；或 `task_queue.enqueue(source="spider")` |
| 暂停/恢复 | `TaskScheduler.remove_job(id) → 临时移除；恢复 = 重新 add`（APScheduler 原生不支持持久化的暂停，用 add/remove 替代） |
| 删除 | `TaskScheduler.remove_job(id)` |
| 任务列表 | `TaskScheduler.list_jobs()` + 注入 `business/multi_spider/registry.list_spiders()` |
| 抓取日志 | Redis 列表 `spider:log:{job_id}`（pipeline 已写入）；无则回退读 `./logs/` 文件 |
| 风控异常 | `core/spider_core/risk_controller.py` + Redis Key `spider:risk:{date}` |

### 5.3 商机线索 (`web_admin/api/lead_mgmt.py`)

| 操作 | 调用链路 |
|------|----------|
| 线索列表 | `business/data_clean/storage.py` 暴露的 `query_leads()`；无则回退到 `task_queue.list_tasks(source="data_clean")` + 摘要 |
| 线索详情 | 同上 · `get_lead(id)` |
| 人工复核 | `status = APPROVED / REJECTED` → 更新存储；REJECTED 自动触发 `BlacklistFilter.add_item(...)` |
| 手动加黑 | `BlacklistFilter.add_item(BlacklistItem(type="phone/email/company_name", value="..."))` |
| 字段脱敏 | 所有输出调用 `PIIMask.auto_mask(data)` |

### 5.4 渠道账号 (`web_admin/api/channel_account.py`)

| 操作 | 调用链路 |
|------|----------|
| 账号列表 | `AccountPool.channels()` + `AccountPool.all_accounts(channel)`；密码字段返回 `********` |
| 新增/更新 | `AccountPool.register_account(Account(account_id=..., username=..., password_hashed=..., default_quota=...))`；密码字段仅存 hash 到 Redis，不回读明文 |
| 封禁/解封 | `AccountPool.mark_banned(channel, account_id, reason, cooldown)` / `unban(...)` |
| 额度可视化 | 遍历 Account.`today_sent / default_quota` 返回条形百分比 |

### 5.5 销售管理 (`web_admin/api/sales_mgmt.py`)

| 操作 | 调用链路 |
|------|----------|
| 销售配置 | 复用 `business/sales_task/registry.assign()` 输入参数 schema；销售信息存 Redis `web_admin:salespersons:[{id,name,industries,weight,phone,email}]` |
| 分配记录 | `business/sales_task/storage.py`（若暴露）+ 回退 Redis 记录；或调用 `assign()` 产生的持久化记录 |
| 待跟进看板 | `reminder_engine.remind(...)` 返回的告警/待跟进列表 |
| 逾期列表 | `status_engine.transition(...)` 返回的逾期状态商机 |
| 字段脱敏 | phone / email 统一 `PIIMask.auto_mask` 掩码显示 |

---

## 六、前后端实现要点

### 6.1 前端技术选型（轻量，不引入 npm/builder）

- **纯 HTML + 手写 CSS + 原生 JS `fetch()`**
- 页面为 **SPA（单页应用）**：`/admin` → `templates/index.html` → JS 根据 `#/path` 动态 fetch `templates/partials/*.html` 并渲染数据
- **样式**：使用 `css/admin.css`（类 Tailwind 命名 · 卡片/表格/表单/按钮基本组件）
- **图表**：纯 CSS 条形图（`background: linear-gradient(90deg, #4f46e5 0%, #4f46e5 X%, #e5e7eb X%)`），不引入 ECharts/Chart.js

### 6.2 页面内 JS 交互

```
1. <script src="/admin/static/js/admin.js"></script>
2. admin.js 暴露：
   - admin.api(path, options)  → 自动注入 cookie、处理 401→redirect
   - admin.renderTable(el, {columns:[{key,label}], data:[], pageSize:20})
   - admin.maskRender(value, type="phone")  → *** 展示
3. 菜单点击 → hash #/path → 拉取 partials HTML → 替换主内容区
4. 分页：limit/offset 或 page/page_size，调用 API 返回 {"items":[],"total":N}
```

### 6.3 模板渲染

- FastAPI 的 `Jinja2Templates`：在 `web_admin/main.py` 中
  - `templates = Jinja2Templates(directory="web_admin/templates")`
- **静态文件**：`app.mount("/admin/static", StaticFiles(directory="web_admin/static"), name="admin_static")`
- 所有 HTML 页面带 `<meta name="csrf-token" content=token>`，登录后可读用于表单

### 6.4 服务挂载方式

`web_admin/main.py` 提供：
```python
def mount_on(app: FastAPI) -> None:
    """将 web_admin 路由与页面挂载到 FastAPI app。"""
    app.include_router(api_router, prefix="/api/admin")
    app.include_router(page_router, prefix="/admin")
    app.mount("/admin/static", StaticFiles(directory=...), name="admin_static")
```

在 `adapter/main.py` 的全局路由注册块中追加：
```python
from web_admin.main import mount_on as mount_web_admin
if settings.web_admin.WEB_ADMIN_ENABLED:
    mount_web_admin(app)
```

**（不会改动 adapter/main.py 的原有路由；仅在文件末尾追加。）**

---

## 七、隐私 & 安全约束

1. **响应数据脱敏**：所有写回浏览器的隐私字段（phone, email, password, secret_key）均强制通过 `PIIMask.auto_mask()` 处理，仅展示 `***` 或部分掩码（如 `138****5678`）
2. **渠道密码/密钥**：前端页面绝不回读明文，表单提交后哈希后存储到 Redis（`web_admin:channel_accounts:{channel}:{id}`），列表只显示 `********`
3. **登录凭证**：Cookie `HttpOnly` + `Secure`（prod 模式）+ `SameSite=lax`；Redis key TTL 自动失效
4. **操作日志**：`infra/logger_setup.get_logger("web_admin.audit")` 写入 `./logs/web_admin_audit.log`，同时保留 Redis 最近 2000 条供页面展示
5. **高危操作告警**：删除爬虫任务、拒绝商机加黑、封禁/解封渠道账号、销售删除—— 全部调用 `infra.alerting.service_exception_sync(service_name="web_admin", message=...)` 触发全局告警

---

## 八、分步执行开发流程

### Step 0 · 配置层

| 步骤 | 文件 | 说明 |
|------|------|------|
| 0.1 | `configs/settings.py` | 追加 `WebAdminSettings(BearerSettings class, get_tokens) 类似；新增到 `AppSettings.web_admin: "WebAdminSettings" = Field(...)`，但更直接：追加 WebAdminSettings`类，并在 AppSettings 中注入 settings.web_admin

### Step 1 · 登录与会话模块

| 步骤 | 文件 | 说明 |
|------|------|------|
| 1.1 | `web_admin/__init__.py` | 保留（内容不变） |
| 1.2 | `web_admin/auth.py` | session Redis 存取 + Depends `require_admin` + 密码 hash 初始化 |
| 1.3 | `web_admin/middleware.py` | 行为日志中间件（记录 method/path/user/ip/status） |
| 1.4 | `web_admin/menu.py` | 常量 `MENU = [...]` |

### Step 2 · 后端 API

| 步骤 | 文件 | 说明 |
|------|------|------|
| 2.1 | `web_admin/api/__init__.py` | 空或导出 router 组合 |
| 2.2 | `web_admin/api/dashboard.py` | `GET /stats` 调用 `get_funnel_stats() / list_runs() / task_queue` 汇总 |
| 2.3 | `web_admin/api/spider_task.py` | `tasks CRUD / run / pause / resume / logs / risks` |
| 2.4 | `web_admin/api/lead_mgmt.py` | leads 列表 / 详情 / 复核 / 黑名单 |
| 2.5 | `web_admin/api/channel_account.py` | channels / account / ban / unban |
| 2.6 | `web_admin/api/sales_mgmt.py` | persons / assignments / followups / overdue |
| 2.7 | `web_admin/api/audit_log.py` | 操作日志读取 |

### Step 3 · 前端页面 + 静态资源

| 步骤 | 文件 | 说明 |
|------|------|------|
| 3.1 | `web_admin/templates/login.html` | 简洁登录表单 |
| 3.2 | `web_admin/templates/index.html` | SPA 主框架（含菜单 / 内容容器 / cookie 注入） |
| 3.3 | `web_admin/templates/partials/dashboard.html` | 数字卡片 + 漏斗条形 |
| 3.4 | `web_admin/templates/partials/spider_task.html` | 任务表格 + 新增/编辑弹窗 |
| 3.5 | `web_admin/templates/partials/leads.html` | 线索列表 + 筛选表单 |
| 3.6 | `web_admin/templates/partials/channels.html` | 渠道账号表格 |
| 3.7 | `web_admin/templates/partials/sales.html` | 销售管理 + 待跟进 + 逾期 |
| 3.8 | `web_admin/static/css/admin.css` | 统一样式（约 150~200 行） |
| 3.9 | `web_admin/static/js/admin.js` | fetch/api + 表格 + 脱敏 + hash 路由 |

### Step 4 · 入口与挂载

| 步骤 | 文件 | 说明 |
|------|------|------|
| 4.1 | `web_admin/main.py` | `mount_on(app)` 注册 `/admin/*` 页面路由 + `/api/admin/*` API 路由 + 静态文件挂载 |
| 4.2 | `web_admin/pages.py` | 页面 HTML 渲染（`Jinja2Templates`） |
| 4.3 | `adapter/main.py` | 在文件末尾追加：`if settings.web_admin.WEB_ADMIN_ENABLED: mount_web_admin(app)`（**不破坏原有路由**，仅追加） |

### Step 5 · 测试 & 验证

| 步骤 | 文件 | 说明 |
|------|------|------|
| 5.1 | `tests/test_t14_web_admin.py` | FastAPI TestClient 测试：登录 / 未登录 401 / 看板 / 线索脱敏 / 渠道密码不回显 / 审计日志写入 |
| 5.2 | `git status` & 手动 smoke test | `python -m adapter.main` → 浏览器访问 `http://localhost:8000/admin` |

### Step 6 · 提交

| 步骤 | 操作 |
|------|------|
| 6.1 | `git add web_admin/ configs/settings.py tests/test_t14_web_admin.py` |
| 6.2 | `git commit -m "feat(T14): 轻量 Web 管理后台 · 可视化运维 / 线索 / 任务 / 销售"` |
| 6.3 | `git push origin main` |

---

## 九、技术风险与降级路径

| 风险 | 应对 |
|------|------|
| `infra/task_scheduler` 未暴露 `pause/resume` 语义 | 用 `remove_job → 内部 Redis 记录 "paused jobs" → 恢复时重新 add_cron` 替代 |
| `business/data_clean/storage.py` 未暴露 `query_leads()` 列表 API | 降级为读取 `infra/task_queue.list_tasks(source="data_clean")` 并展示任务摘要，或在 `storage.py` 追加只读 `query()` 接口（T05~T10 既有模块，不破坏契约前提下扩展） |
| `AccountPool` 账号信息来自 env 不可动态新增 | 在 `web_admin/api/channel_account.py` 中用 Redis `web_admin:accounts:{channel}:{id}` 额外存储动态账号，并在 AccountPool 加载时合并；不修改 `core/send_core/account_pool.py` |
| 渠道密码回读风险 | 所有读接口强制返回 `password: "********"`；写接口接收明文但立即 bcrypt hash 再写 Redis，且不记录日志 |
| 销售数据无持久化 | 用 Redis `web_admin:salespersons / web_admin:assignments / web_admin:followups` 承载；每次 `assign() / remind() / transition()` 触发后同步写入（通过 Decorator 封装） |

---

## 十、单元测试设计

| TestCase | 覆盖场景 |
|----------|----------|
| `TestT14Auth` | 未登录访问 API → 401；Cookie 有效 → 200；登录失败 → 401；登出 → 会话消失 |
| `TestT14Dashboard` | `GET /api/admin/dashboard/stats` 返回 JSON；字段脱敏；包含各指标 |
| `TestT14SpiderTasks` | 新增任务 → 200；立即触发 → 状态更新；删除 → 从列表消失 |
| `TestT14Leads` | 线索列表分页；复核通过/拒绝 → 状态变化；手动加黑 → 调用 blacklist_filter |
| `TestT14Channels` | 账号列表不回显密码（=="********"）；新增账号 → 列表出现；封禁 → 状态变化 |
| `TestT14Sales` | 销售 CRUD；分配记录写入；逾期列表返回非空 |
| `TestT14AuditLog` | 高危操作 → 调用 alerting / 写入 Redis 审计日志 |

---

## 十一、启动与验证路径

```bash
# 1. 启动 FastAPI（承载 OpenClaw 网关 + Web 管理后台）
python -m adapter.main

# 2. 浏览器访问管理后台
#    http://localhost:8000/admin
#    默认账号: admin / 密码: WEB_ADMIN_PASSWORD_PLAIN（env）

# 3. 功能验证顺序
#    登录 → 数据看板 → 爬虫任务 → 商机线索 → 渠道账号 → 销售管理 → 操作日志

# 4. 自动化测试
python tests/test_t14_web_admin.py
```

---

## 十二、最终交付清单

1. ✅ `configs/settings.py` 追加 `WebAdminSettings`
2. ✅ `web_admin/auth.py` 登录/会话/Depends
3. ✅ `web_admin/middleware.py` 行为日志中间件
4. ✅ `web_admin/menu.py` 菜单常量
5. ✅ `web_admin/pages.py` 页面路由
6. ✅ `web_admin/main.py` 挂载入口
7. ✅ `web_admin/api/dashboard.py` 看板数据
8. ✅ `web_admin/api/spider_task.py` 爬虫任务
9. ✅ `web_admin/api/lead_mgmt.py` 商机线索+黑名单
10. ✅ `web_admin/api/channel_account.py` 渠道账号
11. ✅ `web_admin/api/sales_mgmt.py` 销售管理
12. ✅ `web_admin/templates/login.html, index.html, partials/*`
13. ✅ `web_admin/static/css/admin.css`
14. ✅ `web_admin/static/js/admin.js`
15. ✅ `tests/test_t14_web_admin.py` 单元测试

---

> 本计划遵循 DEVELOP_RULES.md 全部规范：强类型注解 / 单文件职责清晰 / 全部配置来自 env / 不新增底层调度与采集逻辑 / 统一 `get_logger / alert_service / PIIMask / get_redis()` 调用链。
