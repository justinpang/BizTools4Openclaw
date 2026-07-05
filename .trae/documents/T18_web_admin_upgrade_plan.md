# T18 — Web 管理后台基础架构升级计划

> 基于 T01~T17 现有轻量后台，升级为：四级角色权限体系 + 六模块菜单框架 + 全局组件底座 + 统一操作日志。
> **严格约束**：仅修改 `web_admin/` 目录下文件，不动业务代码；所有账号/权限/会话配置从 `.env` 读取；不新增底层依赖。

---

## 0. 现状梳理（Repo 调研结论）

### 0.1 当前文件结构

```
web_admin/
├── __init__.py
├── main.py            # 挂载入口：/admin + /api/admin
├── auth.py            # 单账号登录 + Redis 会话
├── pages.py           # 页面路由（字符串模板）
├── menu.py            # 扁平 6 项菜单
├── middleware.py      # 操作日志中间件（Redis 列表）
├── static/
│   ├── css/admin.css  # 极简样式
│   └── js/admin.js    # 原生 JS，调用 API
├── templates/
│   ├── login.html
│   └── partials/*.html  # 业务页面（不改动）
└── api/
    ├── __init__.py
    ├── dashboard.py
    ├── spider_task.py
    ├── lead_mgmt.py
    ├── channel_account.py
    ├── sales_mgmt.py
    └── audit_log.py
```

### 0.2 当前实现特征

- **认证**：单账号 `admin`，密码哈希（bcrypt 优先，降级 sha256+salt），Redis 会话（key=`web_admin:session:{token}`，TTL=8h），进程内 dict 兜底
- **权限**：无角色体系；所有登录用户可访问所有菜单与操作
- **菜单**：扁平 6 项（数据看板/爬虫任务/商机线索/渠道账号/销售管理/操作日志）
- **布局**：左侧菜单 + 顶栏标题 + 用户区（含登出）
- **日志**：`web_admin:audit_log` Redis LIST，最多 2000 条；`HIGH_RISK_METHODS={DELETE,POST,PUT}` 且路径含特定关键字触发告警
- **页面技术**：f-string 字符串模板 + 原生 JS，零前端框架；CSS/JS 极简
- **配置**（`configs/settings.py` 第 420–428 行）：
  - `WEB_ADMIN_ENABLED`, `WEB_ADMIN_PATH_PREFIX`, `WEB_ADMIN_USERNAME`
  - `WEB_ADMIN_PASSWORD_HASH`, `WEB_ADMIN_PASSWORD_PLAIN`
  - `WEB_ADMIN_SESSION_TTL_SECONDS`, `WEB_ADMIN_PAGE_SIZE`

### 0.3 计划修改范围（仅这些文件）

| 文件 | 修改类型 | 说明 |
|------|----------|------|
| `web_admin/menu.py` | 重写 | 由扁平 list → 含权限标签的分层 MENU 结构 |
| `web_admin/auth.py` | 大幅扩写 | 增加角色枚举、多账号支持、按钮级权限判定、session 内含 role |
| `web_admin/pages.py` | 扩写 + 抽取 | `_layout` 改为面包屑版本；新增空状态/异常页面；页面路由加权限依赖 |
| `web_admin/middleware.py` | 扩写 | 日志增加 `role`/`operation_type`/`action_detail` 字段，按模块分类 |
| `web_admin/main.py` | 扩写 | 注入新的账号管理 API，静态文件保持不变 |
| `web_admin/static/css/admin.css` | 扩写 | 统一组件样式（表格/表单/开关/面包屑/搜索/空状态/加载/脱敏标记） |
| `web_admin/static/js/admin.js` | 扩写 | 统一表格/表单/脱敏渲染工具函数，全局搜索，页面启动时拉取菜单 |
| `web_admin/api/__init__.py` | 扩写 | 新增 `accounts_router`、`audit_enhanced_router` |
| `web_admin/api/accounts.py` | **新增** | 账号管理（超级管理员可 CRUD） |
| `web_admin/api/audit_enhanced.py` | **新增** | 按角色/时间/操作类型筛选的日志查询 |
| `.env.example` | 扩写 | 新增账号/角色/权限相关 env 示例（不修改已部署的 `.env`） |
| `configs/settings.py` | 扩写 | 在 `WebAdminSettings` 中新增账号相关字段（从 env 读取 JSON 字符串） |

**禁止修改**：`README.md`、`DEVELOP_RULES.md`、`docs/TASK_LIST.md`、`infra/core/business/adapter/` 下的所有业务代码；`web_admin/templates/partials/*.html` 保持不变（通过 `_layout` 注入时由 JS 层控制权限展示）。

**不新增依赖**：不安装任何新 Python package（bcrypt 已是可选依赖；若不可用则保持现有 sha256+salt 降级）。

---

## 1. 四级角色权限矩阵

### 1.1 角色枚举

```
super_admin  超级管理员 — 拥有一切权限，可管理账号/角色
ops          运营岗     — 负责采集与数据中心模块
sales        销售岗     — 负责商机与销售管理模块
compliance   合规岗     — 负责渠道账号合规校验与审计
```

> 角色值存储在 session 中 `{"username", "role", "ip", ...}`，`role` 字段新增。

### 1.2 菜单级权限（√=可见 / —=不可见）

| 模块 | 子菜单 | 路径 | super_admin | ops | sales | compliance |
|------|--------|------|:---:|:---:|:---:|:---:|
| **采集管理** | 爬虫任务 | `/admin/spider` | √ | √ | — | — |
| **数据中心** | 数据看板 | `/admin/dashboard` | √ | √ | √ | — |
| | 数据字典（框架占位，不实现业务） | `/admin/data_center` | √ | √ | √ | — |
| **商机管理** | 商机线索 | `/admin/leads` | √ | — | √ | — |
| **触达管理** | 渠道账号 | `/admin/channels` | √ | — | — | √ |
| **销售管理** | 销售管理 | `/admin/sales` | √ | — | √ | — |
| **系统设置** | 操作日志 | `/admin/audit_log` | √ | √ | — | √ |
| | 账号管理 | `/admin/system/accounts` | √ | — | — | — |

### 1.3 按钮级权限（+ 操作权限元）

| 按钮标识 | 说明 | 角色可达 |
|----------|------|:--------:|
| `btn.create_task` | 创建/编辑爬虫任务 | super_admin, ops |
| `btn.delete_task` | 删除爬虫任务 | super_admin |
| `btn.view_leads` | 查看线索列表 | super_admin, sales |
| `btn.approve_lead` | 审核通过线索 | super_admin, ops |
| `btn.reject_lead` | 拒绝线索 | super_admin, ops |
| `btn.add_blacklist` | 加入黑名单 | super_admin, ops |
| `btn.create_account` | 新增渠道账号 | super_admin, compliance |
| `btn.view_account_secret` | 查看账号密钥/密码明文（仅超级管理员，且不可复制） | super_admin |
| `btn.upsert_person` | 新增/编辑销售 | super_admin |
| `btn.assign_opportunity` | 分配商机 | super_admin, sales |
| `btn.record_followup` | 记录跟进 | super_admin, sales |
| `btn.manage_accounts` | 账号 CRUD（后台账号管理） | super_admin |
| `btn.reset_password` | 重置账号密码 | super_admin |
| `btn.view_audit_log` | 查看操作日志 | super_admin, ops, compliance |
| `btn.export_audit_log` | 导出操作日志（CSV） | super_admin |

> 按钮级权限通过：前端 `data-requires-permission="btn.create_task"` + JS 启动时过滤；后端 API handler 中再次校验（"双校验"，前端只是体验，后端才是保障）。

### 1.4 权限判定工具函数（后端）

```python
# web_admin/auth.py 中新增（伪代码，非真实实现）
ROLE_PERMISSIONS = {
    "super_admin": {"spider.read", "spider.write", "spider.delete",
                    "leads.read", "leads.approve", "leads.reject",
                    "channels.read", "channels.write", "channels.view_secret",
                    "sales.read", "sales.write",
                    "audit.read", "audit.export",
                    "system.accounts", "system.reset_password"},
    "ops":          {"spider.read", "spider.write",
                     "leads.read", "leads.approve", "leads.reject",
                     "audit.read"},
    "sales":        {"leads.read", "sales.read", "sales.write"},
    "compliance":   {"channels.read", "channels.write", "audit.read"},
}

MENU_PERMISSION_MAP = {
    # active_key -> required_role_set
    "spider":    {"super_admin", "ops"},
    "dashboard": {"super_admin", "ops", "sales"},
    "leads":     {"super_admin", "sales"},
    "channels":  {"super_admin", "compliance"},
    "sales":     {"super_admin", "sales"},
    "audit_log": {"super_admin", "ops", "compliance"},
    "accounts":  {"super_admin"},
}
```

判定 API：
- `has_permission(role: str, perm: str) -> bool`
- `require_permission(perm: str)` — 返回 `Depends` 风格依赖，返回 session 或抛 403
- `role_can_view_menu(role: str, active_key: str) -> bool`

---

## 2. 菜单结构与路由清单

### 2.1 新的分组菜单（顶层模块 = 采集/数据/商机/触达/销售/系统）

```python
# web_admin/menu.py 新 MENU 结构（分组 + 权限标签 + 图标）
MENU_GROUPS: list[dict] = [
    {
        "group_key": "collection",
        "title": "采集管理",
        "icon": "🕸",
        "items": [
            {"key": "spider",   "title": "爬虫任务",   "href": "/admin/spider",    "roles": {"super_admin", "ops"}},
        ],
    },
    {
        "group_key": "data_center",
        "title": "数据中心",
        "icon": "🗂",
        "items": [
            {"key": "dashboard", "title": "数据看板",   "href": "/admin/dashboard",  "roles": {"super_admin", "ops", "sales"}},
            {"key": "data_center_placeholder", "title": "数据字典", "href": "/admin/data_center_placeholder", "roles": {"super_admin", "ops", "sales"}},
        ],
    },
    {
        "group_key": "opportunity",
        "title": "商机管理",
        "icon": "💼",
        "items": [
            {"key": "leads", "title": "商机线索", "href": "/admin/leads", "roles": {"super_admin", "sales"}},
        ],
    },
    {
        "group_key": "outreach",
        "title": "触达管理",
        "icon": "📡",
        "items": [
            {"key": "channels", "title": "渠道账号", "href": "/admin/channels", "roles": {"super_admin", "compliance"}},
        ],
    },
    {
        "group_key": "sales_mgmt",
        "title": "销售管理",
        "icon": "👥",
        "items": [
            {"key": "sales", "title": "销售管理", "href": "/admin/sales", "roles": {"super_admin", "sales"}},
        ],
    },
    {
        "group_key": "system",
        "title": "系统设置",
        "icon": "⚙",
        "items": [
            {"key": "audit_log", "title": "操作日志", "href": "/admin/audit_log", "roles": {"super_admin", "ops", "compliance"}},
            {"key": "accounts",  "title": "账号管理", "href": "/admin/system/accounts", "roles": {"super_admin"}},
        ],
    },
]
```

> 兼容 `web_admin.menu.MENU`：保留 `MENU = [item for g in MENU_GROUPS for item in g["items"]]`（避免外部 `from web_admin.menu import MENU` 报错，但实际渲染使用分组版）。

### 2.2 页面路由清单（新增页面）

| 路由 | 方法 | 权限要求 | 说明 |
|------|------|----------|------|
| `/admin/system/accounts` | GET | super_admin | 账号管理页（新增/禁用/重置密码） |
| `/admin/empty` | GET | super_admin+ | 空状态示例（用于调试 / 展示组件样式） |
| `/admin/403` | GET | — | 权限不足展示页（中间件重定向） |

### 2.3 API 路由清单（新增）

| 路由 | 方法 | 权限要求 | 说明 |
|------|------|----------|------|
| `/api/admin/me` | GET | 任意已登录 | 返回 `{username, role, permissions[]}` |
| `/api/admin/menu` | GET | 任意已登录 | 返回按角色过滤后的 MENU_GROUPS |
| `/api/admin/accounts` | GET | super_admin | 账号列表（分页 + 关键字） |
| `/api/admin/accounts` | POST | super_admin | 新建账号 `{username, role, password_plain}` |
| `/api/admin/accounts/{id}` | PUT | super_admin | 修改角色 / 启用状态 |
| `/api/admin/accounts/{id}/reset_password` | POST | super_admin | 重置密码，返回一次性明文（脱敏回显） |
| `/api/admin/accounts/{id}` | DELETE | super_admin | 禁用/软删除账号（保留审计痕迹） |
| `/api/admin/audit/logs` | GET | super_admin, ops, compliance | 增强版日志查询：`{role?, op_type?, from_ts?, to_ts?, keyword?, page?, page_size?}` |
| `/api/admin/audit/logs/export` | GET | super_admin | CSV 导出（Content-Disposition） |

---

## 3. 公共组件设计与全局脱敏规则

### 3.1 CSS 组件层（`web_admin/static/css/admin.css` 新增）

| 组件类名 | 说明 |
|----------|------|
| `.layout-v2` | 新布局容器：顶栏 + 左侧分组菜单 + 主内容（保留原有 `.layout` 兼容） |
| `.topbar-v2` | 顶栏：左侧面包屑 + 中间全局搜索框 + 右侧用户角色标签 + 登出 |
| `.breadcrumb` | 面包屑：`采集管理 / 爬虫任务` |
| `.sidebar-v2` | 分组菜单：可展开/收起，active 项高亮 |
| `.menu-group` | 菜单组容器，点击展开/折叠 |
| `.menu-item` | 菜单项（原 `.menu-link` 保留兼容） |
| `.panel` | 统一内容块，标题 + 内容（已有，规范：圆角、阴影、内边距） |
| `.page-title` | 页面标题：h2 + 右侧描述 |
| `.global-search` | 全局搜索输入框（模糊匹配菜单标题 + 跳转到页面） |
| `.data-table-v2` | 统一表格：斑马纹、hover 高亮、固定表头、分页条、筛选行 |
| `.data-table-v2 thead tr` | 表头行 |
| `.data-table-v2 tbody tr.empty-row` | 空状态行 |
| `.data-table-v2 tbody tr.loading-row` | 加载状态行 |
| `.form-row` | 统一行内表单容器：label + input/select/textarea/switch |
| `.btn, .btn-primary, .btn-danger, .btn-sm, .btn-disabled` | 按钮规范（已有，扩展） |
| `.form-input, .form-select, .form-switch, .form-date-range` | 统一表单控件样式 |
| `.tag-role-{super_admin|ops|sales|compliance}` | 角色标签（不同颜色） |
| `.empty-state` | 全局空状态：图标 + "暂无数据" + 操作按钮 |
| `.loading-state` | 全局加载：旋转图标 + 文字 |
| `.error-state` | 全局异常：红色图标 + 错误消息 + 重试按钮 |
| `.sensitive-mask` | 脱敏标记样式（浅灰斜体）；鼠标悬停不显示明文 |
| `.sensitive-mask.phone::after` | 手机号：`138****1234` |
| `.sensitive-mask.wechat::after` | 微信：`wx_****_abcd` |
| `.sensitive-mask.secret` | 密钥：`********` + 不可选中 + 不可复制 |
| `.sensitive-mask.password` | 密码：永远 `********` + `user-select:none` + `copy: none` |

### 3.2 JS 工具函数层（`web_admin/static/js/admin.js` 新增命名空间 `admin.ui`）

```javascript
// 伪接口（真实实现见代码，此处为协议声明）
admin.ui = {
  // ---------- 表格统一渲染 ----------
  // renderTable(el, { columns, rows, pageSize, selectable, onSelect })
  //   columns = [{key, label, sortable, type}]
  //   selectable=true 则显示 checkbox 列
  renderTable(el, opts),

  // ---------- 表单统一组件 ----------
  // bindForm(el, { onSubmit, schema }) — schema 描述字段类型/默认值
  bindForm(el, opts),

  // ---------- 脱敏工具 ----------
  // maskPhone("13812341234") => "138****1234"
  maskPhone(v),
  // maskWechat("wx_1234_abcdef") => "wx****def"
  maskWechat(v),
  // maskSecret("ak_abc123") => "********"
  maskSecret(v),
  // maskPassword(any) => "********"
  maskPassword(),
  // autoMask(documentOrElement) — 遍历带 [data-sensitive] 的元素，按类型脱敏
  autoMask(root),

  // ---------- 空/加载/异常状态 ----------
  renderEmpty(el, { title, hint, actionLabel, onAction }),
  renderLoading(el, { hint }),
  renderError(el, { title, message, retry, onRetry }),

  // ---------- 权限驱动的按钮显示 ----------
  // applyPermission(documentOrElement, currentPermissionsSet)
  // 对带 [data-requires-permission="btn.xxx"] 的按钮：
  //   有权限：正常展示；无权限：display:none
  applyPermission(root, permissions),

  // ---------- 菜单渲染（基于 API 返回的 MENU_GROUPS） ----------
  // renderSidebar(el, groups, activeKey)
  renderSidebar(el, groups, activeKey),

  // ---------- 面包屑 ----------
  // renderBreadcrumb(el, crumbs)
  renderBreadcrumb(el, crumbs),

  // ---------- 全局搜索（菜单标题模糊匹配） ----------
  // bindGlobalSearch(inputEl, groups) — 回车 / 方向键 / 点击跳转
  bindGlobalSearch(inputEl, groups),
};
```

### 3.3 全局脱敏规则（强制）

| 字段类型 | 识别标记 | 前端展示 | 可复制 | 允许解锁 |
|----------|----------|----------|:------:|:--------:|
| 手机号 | `data-sensitive="phone"` | 保留前 3 + 后 4：`138****1234` | 不可（复制仍为脱敏值） | 否 |
| 微信号 | `data-sensitive="wechat"` | 前 2 + `****` + 后 3 | 不可 | 否 |
| 密钥/Token | `data-sensitive="secret"` | 永远 `********` | 不可（`user-select:none` + JS 拦截 copy） | **仅 super_admin 在独立 API 一次性查看** |
| 密码 | `data-sensitive="password"` | 永远 `********` | 不可 | 否（永远不回显明文） |
| 邮箱 | `data-sensitive="email"` | 首字母 + `****@` + 域名 | 不可 | 否 |

后端保障：**所有 JSON 响应中涉及上述字段的，由各自 API handler 在返回前调用 `mask_*()` 做服务端脱敏；前端只是"再次加固"**。本计划不修改业务 API（spider_task/lead_mgmt/channel_account/sales_mgmt/dashboard）的返回结构，但在前端对上述页中 `phone` / `password` 等已知字段做 JS 层二次脱敏，不影响后端逻辑。

> 🔒 **密钥查看特殊机制**（仅 `super_admin`）：
> - `POST /api/admin/accounts/{id}/view_secret` — 校验权限 + 记录审计日志 + 返回一次性明文（T=5 秒内仅可查看一次）
> - 前端：弹窗展示 `********` + "已解锁查看 30 秒"按钮 → 点击后调用 API → 30 秒内仍显示明文但 `copy` 事件被拦截，超时自动清除 DOM
> - 后端在每次查看成功后，记录 `operation_type="VIEW_SECRET"` 到审计日志

### 3.4 页面布局（`_layout_v2`，保留旧 `_layout` 兼容）

```
┌────────────────────────────────────────────────────────┐
│  [面包屑: 采集管理 / 爬虫任务]   [全局搜索]   [角色标签]   [用户名 · 登出] │  <- topbar-v2
├────────────┬───────────────────────────────────────────┤
│ 🕸 采集管理 │                                         │
│   · 爬虫任务  <- active                               │
│ 🗂 数据中心 │              主内容区（panel 堆叠）        │
│   · 数据看板 │                                         │
│   · 数据字典 │                                         │
│ ...        │                                         │
└────────────┴───────────────────────────────────────────┘
```

模板渲染：`pages.py` 中 `_layout(title, active_key, body_html, username)` 的签名**保持不变**，但内部实现切换为 `_layout_v2`，该版本会注入分组菜单、面包屑与全局搜索。这确保对现有 6 个页面路由（dashboard/spider/leads/channels/sales/audit_log）零侵入即可获得新布局。

---

## 4. 操作日志存储结构与埋点规则

### 4.1 增强版日志字段（向后兼容）

旧字段（保留）：`ts, username, ip, method, path, status, latency_ms`

新增字段（`middleware.py` 中注入）：

| 字段 | 类型 | 说明 |
|------|------|------|
| `role` | string | 操作人角色（未登录为空字符串） |
| `operation_type` | string | 操作类型枚举：`LOGIN`/`LOGOUT`/`READ`/`CREATE`/`UPDATE`/`DELETE`/`VIEW_SECRET`/`EXPORT`/`SYSTEM` |
| `action_detail` | string | 操作内容摘要，如 "创建爬虫任务 spider_hourly"；默认 `method + path` |
| `module` | string | 所属模块：`collection` / `data_center` / `opportunity` / `outreach` / `sales_mgmt` / `system` |
| `is_high_risk` | bool | 是否高危操作（旧 HIGH_RISK_* 规则保留） |
| `trace_id` | string | 每次请求的短随机 ID（8 位），便于问题排查 |

完整 JSON 行：

```json
{
  "ts": 1783104591,
  "username": "ops_01",
  "role": "ops",
  "ip": "10.0.0.5",
  "method": "POST",
  "path": "/api/admin/spider/tasks",
  "status": 200,
  "latency_ms": 42,
  "operation_type": "CREATE",
  "action_detail": "创建爬虫任务 spider_hourly",
  "module": "collection",
  "is_high_risk": true,
  "trace_id": "a1b2c3d4"
}
```

### 4.2 `operation_type` 的判定规则（中间件内自动推导）

```
operation_type :=
  method == POST   && path contains "/login"       → LOGIN
  method == POST   && path contains "/logout"      → LOGOUT
  method == GET    && path contains "/audit"       → READ
  method == GET    && path contains "/export"      → EXPORT
  method == POST   && path contains "/view_secret" → VIEW_SECRET
  method == POST                                   → CREATE
  method == PUT                                    → UPDATE
  method == DELETE                                 → DELETE
  method == GET                                    → READ
  otherwise                                         → SYSTEM
```

`module` 由 `path` 的前缀映射：`/admin/spider* -> collection`，`/admin/dashboard|data_center* -> data_center`，`/admin/leads* -> opportunity`，`/admin/channels* -> outreach`，`/admin/sales* -> sales_mgmt`，`/admin/audit|system* -> system`。

### 4.3 存储结构（不引入新依赖）

- 保留 Redis LIST `web_admin:audit_log`，单条 JSON 行
- 扩展 `AUDIT_MAX_LEN = 5000`（由 2000 提升，仍为常数，占用可接受）
- 新增 Redis HASH `web_admin:audit:by_module` — 每个 module 维护独立 LIST（可选二级索引）
- 无 Redis 时走进程内 dict（保留降级方案）

### 4.4 显式埋点（由账号管理/密钥查看 API 主动调用）

- 新增 `web_admin.middleware.write_audit_entry(request, session, operation_type, action_detail, status=200)`
- 账号管理 API 中：`CREATE_ACCOUNT`, `UPDATE_ACCOUNT`, `RESET_PASSWORD`, `DISABLE_ACCOUNT`
- 渠道账号（本计划不改动业务 API，但提供前端 `btn.view_account_secret` 需调用新 API）：`VIEW_SECRET` 由新 API `POST /api/admin/accounts/{id}/view_secret` 触发并记录

### 4.5 审计日志查询 API（增强版 `audit_enhanced.py`）

```
GET /api/admin/audit/logs
  ?role=           # 按角色过滤：super_admin|ops|sales|compliance|空=全部
  &op_type=        # 按操作类型过滤：READ|CREATE|UPDATE|DELETE|VIEW_SECRET|EXPORT|LOGIN|LOGOUT
  &module=         # 按模块过滤
  &keyword=        # 在 action_detail / path / username 中做简单包含匹配
  &from_ts=        # Unix 秒
  &to_ts=          # Unix 秒
  &page=1
  &page_size=20

返回：
{
  "code": 0,
  "msg": "ok",
  "items": [ ... 增强版 JSON 行 ... ],
  "total": <int>,
  "page": 1,
  "page_size": 20
}

GET /api/admin/audit/logs/export
  （同样的过滤参数，但不分页，返回 text/csv 文件并带 Content-Disposition）
  权限：仅 super_admin
```

> 注意：现有 `web_admin/api/audit_log.py` 的 `GET /audit/logs` **保留**，以向后兼容。新增路由加前缀 `/audit_enhanced/logs` 与 `/audit_enhanced/logs/export`，避免冲突。

---

## 5. 分步开发执行流程

### 5.1 里程碑

```
M1  权限体系就绪          （auth.py + 多账号 + 角色权限判定 + 新 env 配置解析）
M2  菜单框架与布局升级    （menu.py MENU_GROUPS + pages.py _layout_v2 + 面包屑/全局搜索）
M3  组件与脱敏工具封装    （admin.css 组件规范 + admin.js admin.ui + 自动脱敏 + 权限按钮过滤）
M4  操作日志增强与埋点    （middleware.py 新字段 + 分类 + audit_enhanced.py 查询 API + CSV 导出）
M5  账号管理与密钥查看    （accounts.py API + system/accounts 页面 + 密钥解锁机制）
M6  空/加载/异常页与收尾  （/admin/empty, /admin/403, 更新菜单高亮、登录页 v2）
M7  自测 + 回归           （启动应用，逐角色访问 + 按钮可见性 + 日志记录 + 脱敏验证）
```

### 5.2 详细步骤（按文件为单位）

**Step 1 —— 配置扩展**（`configs/settings.py` + `.env.example`）
- 在 `WebAdminSettings` 中新增：
  - `WEB_ADMIN_ACCOUNTS_JSON: str = ""` —— 允许通过 env 以 JSON 字符串声明多账号：`[{"username":"admin","role":"super_admin","password_hash":"..."}, ...]`
  - `WEB_ADMIN_DEFAULT_PASSWORD_PLAIN: str = ""` —— 仅当 `password_hash` 为空时，允许启动时由明文生成哈希（**仅用于首次部署，文档提示生产环境必须禁用**）
  - 保留 `WEB_ADMIN_USERNAME / WEB_ADMIN_PASSWORD_HASH / WEB_ADMIN_PASSWORD_PLAIN` 作为"单账号兼容模式"：若 `WEB_ADMIN_ACCOUNTS_JSON` 为空，则回退为单 `admin` 账号（向后兼容）
  - 新增 `WEB_ADMIN_ROLE_LABELS_JSON: str = ""` —— 角色中文展示标签（默认内置值即可，不强制配置）
- 在 `.env.example` 追加上述配置示例，并在注释中强调 `password_plain` 只用于初始化、生产环境应使用 `password_hash`

**Step 2 —— `web_admin/auth.py` 升级（M1）**
- 保留旧 API（`require_admin`, `get_current_admin`, `handle_login_post`, `delete_session`, `SESSION_COOKIE`）以保证外部引用不报错
- 新增：
  - `ROLES = {"super_admin", "ops", "sales", "compliance"}`
  - `ROLE_PERMISSIONS: dict[str, set[str]]` （见 1.4）
  - `load_accounts() -> list[dict]` — 从 env 解析账号（JSON 数组），若为空则回退到旧单账号 `{username: WEB_ADMIN_USERNAME, role: "super_admin", password_hash: ...}`
  - `lookup_account(username: str) -> dict | None`
  - `has_permission(role: str, perm: str) -> bool`
  - `require_permission(perm: str)` —— 依赖函数，校验 session 存在且 role 拥有 perm，否则抛 403
  - `build_session(username, client_ip) -> dict` —— 新 session 结构：`{username, role, ip, created_at, last_seen}`
  - `handle_login_post` 改为查 `load_accounts()`，校验密码后写入带 role 的 session
  - 新增 `me_view()` 对应 `GET /api/admin/me`，返回 `{username, role, permissions: list[str]}`

**Step 3 —— `web_admin/menu.py` 升级（M2 第一部分）**
- 保留导出 `MENU: list[dict]`（旧格式，字段保持一致：`key, title, href, icon`）
- 新增导出 `MENU_GROUPS: list[dict]`（见 2.1）
- 新增 `filter_menu_by_role(role: str) -> list[dict]`（返回过滤后的 MENU_GROUPS，用于前端渲染）

**Step 4 —— `web_admin/pages.py` 升级（M2 第二部分 + M6）**
- 保留 `_layout(title, active_key, body_html, username)` 签名；内部实现切换为 `_layout_v2`：
  - 注入 `admin.ui` 所需的 JS/CSS
  - 注入 `window.__ADMIN_INIT__ = {activeKey, username, role, permissions, menuGroups, breadcrumbs}`（由 `/api/admin/me` 和 `/api/admin/menu` 在页面请求时由后端直接渲染，减少一次 XHR 延迟；或保留 XHR 方案，二者择一——计划采用"后端渲染初始化 JSON"方案，代码更简单）
  - 面包屑：由当前 activeKey 反推 `MENU_GROUPS` 中的层级，如 `采集管理 / 爬虫任务`
  - 顶栏：左侧面包屑 + 中间 `input.global-search`（`bindGlobalSearch`）+ 右侧 `span.tag-role-{role}` + `username` + 登出按钮
- 新增路由：
  - `GET /admin/system/accounts` — 账号管理页（仅 super_admin）
  - `GET /admin/empty` — 空状态示例页（用于样式调试；实际业务页面无需改动）
  - `GET /admin/403` — 权限不足页（展示空状态样式并提供返回链接）
- 保留现有 6 个业务页面路由完全不改动其 `body_html`；通过 `_layout_v2` + JS 层自动处理布局、菜单、脱敏和按钮权限过滤

**Step 5 —— `web_admin/main.py` 升级（挂载新 API）**
- 在 `api_router` 中新增：
  - `accounts_router`（新）
  - `audit_enhanced_router`（新）
  - `GET /me`（由 `auth.me_view` 提供）
  - `GET /menu`（由 `menu.filter_menu_by_role` 提供，基于 session 中的 role）
- 静态文件挂载保持不变（`/admin/static -> web_admin/static`）

**Step 6 —— `web_admin/static/css/admin.css`（M3）**
- 保留原有样式类（`layout`, `sidebar`, `content`, `topbar`, `data-table`, `.btn`, `.panel`, 等）以兼容旧页面
- 新增：
  - `.layout-v2`, `.topbar-v2`, `.breadcrumb`, `.sidebar-v2`, `.menu-group`, `.menu-item`, `.menu-item.active`
  - `.page-title`, `.global-search`
  - `.data-table-v2` 及其 thead/tbody/empty-row/loading-row
  - `.form-row`, `.form-input`, `.form-select`, `.form-switch`, `.form-date-range`
  - `.tag-role-super_admin`, `.tag-role-ops`, `.tag-role-sales`, `.tag-role-compliance`
  - `.empty-state`, `.loading-state`, `.error-state`
  - `.sensitive-mask`, `.sensitive-mask.phone`, `.sensitive-mask.wechat`, `.sensitive-mask.secret`, `.sensitive-mask.password`

**Step 7 —— `web_admin/static/js/admin.js`（M3）**
- 保留原有 `admin` 命名空间与现有业务函数（`admin.createSpiderTask`, `admin.loadLeads`, ...）**完全不改动**
- 新增命名空间 `admin.ui`（见 3.2）
- 新增启动脚本 `admin.ui.bootstrap(rootElement)`，在 DOMContentLoaded 时：
  - 从 `window.__ADMIN_INIT__` 读取 `{activeKey, role, permissions, menuGroups, breadcrumbs}`
  - 渲染侧边栏（分组菜单，activeKey 自动高亮）
  - 渲染面包屑
  - 绑定全局搜索
  - 调用 `autoMask(document)` 对全页敏感字段脱敏
  - 调用 `applyPermission(document, permissions)` 过滤按钮可见性
  - 对已有业务页面的旧 `data-table` 表格行中出现的 phone/wechat/secret/password 字段应用 `autoMask`（仅前端，不改变业务 API）
- 全局搜索：对 `menuGroups` 进行标题模糊匹配，`Enter`/`ArrowDown` 聚焦第一项，点击或回车跳转到对应 `href`

**Step 8 —— `web_admin/middleware.py` 升级（M4）**
- 保留 `build_audit_middleware`, `load_audit_logs`, `AUDIT_REDIS_KEY`（兼容旧 API）
- 新增：
  - `AUDIT_MAX_LEN = 5000`
  - `_derive_operation_type(method, path) -> str`（规则见 4.2）
  - `_derive_module(path) -> str`（规则见 4.2）
  - `_trace_id() -> str`（8 位 base64 无符号随机）
  - `write_audit_entry(request, session, operation_type, action_detail, status=200)` —— 供显式埋点调用
  - 中间件内注入新字段并写回 Redis LIST
  - 高危操作告警规则保持不变

**Step 9 —— 新增 `web_admin/api/accounts.py`（M5）**
- CRUD 与密码重置：
  - `GET /accounts` 列表（按 username 模糊匹配；返回字段脱敏：`password_hash` 不回显，`role/disabled/created_at` 展示）
  - `POST /accounts` 创建：校验 role 合法；password_plain→hash；禁止重复 username；写审计 `CREATE_ACCOUNT`
  - `PUT /accounts/{username}` 更新：可切换 role / 启用状态；写审计 `UPDATE_ACCOUNT`
  - `POST /accounts/{username}/reset_password` 重置：生成随机 16 位明文并返回（仅一次性），同时记录 `RESET_PASSWORD` 审计并标记 `is_high_risk=true`
  - `DELETE /accounts/{username}` 软删除：设 `disabled=true`（保留账号以便审计）；禁止删除当前登录账号
  - `POST /accounts/{username}/view_secret` **（仅针对"后台账号密码"密钥；本项目无其他密钥字段，故主要演示与扩展位）**
- 所有路由使用 `require_permission("system.accounts")` 依赖（隐含 role=super_admin）

**Step 10 —— 新增 `web_admin/api/audit_enhanced.py`（M4 第二部分）**
- `GET /audit_enhanced/logs`（见 4.5）
- `GET /audit_enhanced/logs/export`（CSV，仅 super_admin）
- 在 `web_admin/api/__init__.py` 导出 `audit_enhanced_router`, `accounts_router`

**Step 11 —— `web_admin/pages.py` 账号管理页实现（M5 第二部分）**
- 页面 `GET /admin/system/accounts`：
  - 表格展示账号列表（username, role, enabled, created_at）
  - 顶部操作：新增账号（弹窗表单）
  - 每行操作：
    - 编辑角色 / 启用状态
    - 重置密码（生成随机明文并一次性显示）
    - 禁用 / 启用
  - 使用 `admin.ui.renderTable` 渲染统一表格；按钮使用 `data-requires-permission` 标签

**Step 12 —— 空状态 / 加载 / 异常页（M6）**
- `GET /admin/empty`：演示页
- `GET /admin/403`：权限不足展示；同时在 `auth.require_permission` 中对 HTML 请求返回 `302 -> /admin/403`，对 JSON 请求返回 `403 {code: 403, msg: "权限不足"}`

**Step 13 —— 登录页小幅美化（M6 可选）**
- 保留旧 `_login_page_html` 签名不变
- 增加："当前登录后将根据角色自动可见菜单"提示；移除账号输入框中硬编码的"admin"默认值（改为空），符合"不硬编码账号"要求

**Step 14 —— 自测清单（M7）**

| # | 场景 | 操作 | 期望结果 |
|---|------|------|----------|
| 1 | 单账号兼容 | `.env` 仅配置旧单账号 | 登录后 role=`super_admin`，所有菜单可见 |
| 2 | 多账号登录 | 配置 `WEB_ADMIN_ACCOUNTS_JSON` 含 4 角色账号 | 各自登录后菜单/按钮权限正确过滤 |
| 3 | 菜单权限过滤 | 以 `sales` 角色登录 | 不可见 `spider`, `channels`, `accounts` |
| 4 | 按钮权限过滤 | 以 `sales` 角色登录访问 `leads` | 无 `approve/reject/blacklist` 按钮 |
| 5 | API 权限校验 | 以 `sales` 角色直接调 `POST /api/admin/accounts` | 返回 403 |
| 6 | 操作日志记录 | 执行任意 `POST/PUT/DELETE` 请求 | audit_log 中存在含 `role/operation_type/module/trace_id` 的行 |
| 7 | 审计日志筛选 | 用 `op_type=DELETE, role=super_admin` 筛选 | 仅返回对应行 |
| 8 | CSV 导出 | 以 super_admin 调 export | 返回 CSV，文件名含时间戳 |
| 9 | 手机号脱敏 | 访问 sales 页面的 `phone` 字段 | 前端显示 `138****1234`；不可复制明文 |
| 10 | 密码永远脱敏 | 访问 channels 页面的 password 列 | 永远显示 `********`；`user-select:none` |
| 11 | 密钥查看（后台账号） | super_admin 调用 `view_secret` | 30 秒内可查看明文；记录 `VIEW_SECRET` 审计 |
| 12 | 403 重定向 | 未登录直接访问 `system/accounts` | 跳 `/admin/login` |
| 13 | 会话过期 | 超过 8 小时未操作 | Cookie 失效，重新登录 |
| 14 | Redis 不可达 | 手动关闭 Redis | 自动降级到进程内 dict，功能正常 |
| 15 | bcrypt 不可用 | 无 bcrypt 环境 | 自动使用 sha256+salt，登录成功 |

### 5.3 风险与处置

| 风险 | 影响 | 处置 |
|------|------|------|
| 旧版 `MENU` 被外部引用（如 adapter/main.py 未导入，但仍可能被未来代码导入） | 旧代码读取扁平列表 | 保留 `MENU = flatten(MENU_GROUPS)`，字段完全兼容 |
| 新增 env 配置格式错误（JSON 不合法） | 启动后账号解析失败 | `load_accounts()` try-catch 并以 WARNING 级别日志提示，回退到单账号模式 |
| 会话 JSON 结构新增字段导致旧 session 反序列化失败 | 登录后缺 role | `_get_session_raw` 返回后做 normalize：若缺 `role` 则默认 `super_admin`（向后兼容） |
| 新增 `/api/admin/audit_enhanced/logs` 与旧路由风格不一致 | API 不统一 | 旧 `GET /audit/logs` 保留并 `307 Temporary Redirect` 到新路由（可选，默认直接保留） |
| 业务页面 `data-table` 中的密码/手机号在旧 JS 直接渲染未脱敏 | 敏感信息泄露 | 通过 `admin.ui.autoMask` 在 DOMContentLoaded 时统一二次脱敏 |
| 无新依赖引入失败 | —— | 计划严格限制：仅使用 Python 标准库 + FastAPI + 现有 infra；不新增 pip 包 |

---

## 6. 变更文件清单汇总

### 6.1 修改文件（5 + 1 CSS + 1 JS）

| 文件 | 修改幅度 |
|------|---------:|
| `web_admin/auth.py` | 大 |
| `web_admin/menu.py` | 中 |
| `web_admin/pages.py` | 中 |
| `web_admin/main.py` | 小 |
| `web_admin/middleware.py` | 中 |
| `web_admin/static/css/admin.css` | 中（大量新增类，保留原类） |
| `web_admin/static/js/admin.js` | 中（新增 `admin.ui` 命名空间；旧业务函数不动） |
| `web_admin/api/__init__.py` | 小 |
| `configs/settings.py` | 小（`WebAdminSettings` 追加字段） |
| `.env.example` | 小（追加示例注释） |

### 6.2 新增文件（2）

| 文件 | 用途 |
|------|------|
| `web_admin/api/accounts.py` | 账号管理 API（super_admin 可 CRUD / 重置密码） |
| `web_admin/api/audit_enhanced.py` | 增强版审计日志查询 + CSV 导出 |

### 6.3 明确不修改的文件

- `README.md`, `DEVELOP_RULES.md`, `docs/TASK_LIST.md`
- `infra/core/business/adapter/` 目录全部业务代码
- `web_admin/templates/partials/*.html` 业务页面（由 `_layout_v2` + JS 控制展示，不改 HTML）
- `web_admin/api/spider_task.py`, `web_admin/api/lead_mgmt.py`, `web_admin/api/channel_account.py`, `web_admin/api/sales_mgmt.py`, `web_admin/api/dashboard.py`（业务 API 保持原样；前端通过 `autoMask` 脱敏即可）

---

## 7. 验证与交付物

1. 启动应用后，用 4 种角色账号分别登录，逐一验证：
   - 菜单可见性（按 1.2 矩阵）
   - 按钮可见性（按 1.3 矩阵）
   - 无权限时 API 返回 403 / HTML 跳 403
   - 敏感字段脱敏显示
   - 操作日志中角色/操作类型/模块正确写入
   - 审计日志筛选与导出功能正常
2. 交付物：
   - 上述修改/新增文件的完整代码
   - `.env.example` 中新增的账号/角色配置示例与使用说明注释
3. 文档约束：本计划本身为规划文档，**不在仓库中新增部署文档**（避免违反"禁止修改/新增文档类文件"约束）。
