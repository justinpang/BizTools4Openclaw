# BizTools4OpenClaw
适配 OpenClaw 智能体的全链路商机自动化工具集

一款专为 OpenClaw 打造的商机采集、清洗、触达、销售跟进一体化工具套件，实现「全网商机抓取 → 结构化数据处理 → 自动化客户激活 → 销售闭环跟进」全流程无人值守，补齐 OpenClaw 商业化落地能力。

---

## ✨ 项目核心能力

- **全网全源商机采集**：覆盖网页、短视频、小红书、论坛、社群、供需平台、问答、企业公示、招投标等全场景商机来源
- **智能数据处理**：自动清洗、去重、脱敏、实体抽取、商机打分分级，输出标准化结构化数据，适配大模型调度
- **多渠道自动化触达**：支持邮件、飞书、企业微信、H5 落地页多渠道客户激活，内置风控防封号机制
- **销售流程自动化**：商机自动分配、定时跟进提醒、逾期告警、转化漏斗统计，实现业务落地闭环
- **原生适配 OpenClaw**：标准化工具注册、API 调度、异步任务回调，完美兼容 OpenClaw 智能体编排
- **全链路合规保障**：数据脱敏、隐私保护、爬虫合规、消息风控，规避商用风险
- **Web 管理后台可视化运维**（T14）：登录鉴权 + 数据看板 + 爬虫任务管理 + 商机线索复核 + 渠道账号配置 + 销售任务看板 + 操作审计日志
- **OpenClaw 标准工具注册与调度**（T13）：统一 FastAPI 网关 + Tool Registry + 任务状态查询/取消/重试

---

## 📐 整体架构

项目采用 **四层分层架构 + 业务模块拆解**：基础基建层（L1）→ 通用能力层（L2）→ 业务模块层（L3）→ 接入展示层（L4），架构解耦、可插拔、易扩展、支持单独迭代任意模块。

```
┌────────────────────────────────────── L4 接入展示层 ──────────────────────────────────────┐
│  adapter/                     │  web_admin/                                               │
│  OpenClaw 适配网关（FastAPI） │  Web 管理后台（HTML+CSS+原生JS，纯字符串模板渲染）        │
│  - main.py                    │  - pages.py（登录/看板/爬虫/线索/渠道/销售/审计）          │
│  - auth.py                    │  - auth.py（Cookie 会话 + Redis）                          │
│  - middleware.py              │  - middleware.py（行为审计 + 高危告警）                    │
│  - models.py / response.py    │  - api/*.py（6 个后台 API）                                │
│  - tool_registry.py           │  - menu.py + static/* + templates/partials                │
│  - tools_router.py            │                                                            │
│  - task_router.py             │                                                            │
├────────────────────────────────────── L3 业务模块层 ───────────────────────────────────────┤
│  business/multi_spider/       │  business/data_clean/       │  business/customer_send/    │
│  全源爬虫业务模块（T09）       │  数据清洗流水线（T10）        │  多渠道触达（T11）           │
│  - base.py / models.py         │  - normalizer.py            │  - pipeline.py              │
│  - pipeline.py / registry.py   │  - extractor.py             │  - registry.py / storage.py │
│  - sources/*.py（6 个数据源） │  - filters.py / loader.py    │  - models.py / _orm.py      │
│                              │  - pipeline.py / storage.py   │  - template_engine.py       │
│                              │  - models.py / _orm.py        │  - channels/*.py（4 渠道） │
│                              │  - compliance_step.py         │                              │
│                              │  - engine_step.py             │                              │
│                              │  - registry.py                │                              │
│─────────────────────────────────────────────────────────────────────────────────────────────│
│  business/sales_task/                                                                      │
│  销售调度与跟进闭环（T12）                                                                   │
│  - assignment_engine.py / funnel_engine.py / status_engine.py / reminder_engine.py         │
│  - push_notifier.py / pipeline.py / storage.py / models.py / _orm.py / registry.py        │
├────────────────────────────────────── L2 通用能力层 ───────────────────────────────────────┤
│  core/spider_core/           │  core/data_core/            │  core/send_core/             │
│  爬虫核心通用 SDK（T05）       │  商机去重合并打分（T07）       │  多渠道消息风控底座（T08）   │
│  - sdk.py / proxy_pool.py    │  - dedupe_engine.py          │  - account_pool.py           │
│  - ua_pool.py / rate_limiter.py │ - merge_engine.py        │  - rate_limiter.py           │
│  - risk_controller.py         │  - scoring_engine.py         │  - content_risk.py           │
│  - robots_checker.py          │  - blacklist_filter.py       │  - ban_detector.py           │
│  - checkpoint_manager.py      │  - pipeline.py                │  - failure_retry.py          │
│  - exceptions.py              │                              │  - send_pipeline.py          │
│                              │                              │  - task_status.py            │
│─────────────────────────────────────────────────────────────────────────────────────────────│
│  core/compliance/                                                                            │
│  数据合规/脱敏/敏感词检测（T04+T06）                                                         │
│  - pii_mask.py / privacy_stripper.py / sensitive_crypto.py                                  │
│  - sensitive_filter.py / compliance_checker.py / archive_mixin.py / data_lifecycle.py      │
├────────────────────────────────────── L1 基础基建层 ───────────────────────────────────────┤
│  infra/                                                                                     │
│  - logger_setup.py（统一日志，多文件轮转）                                                   │
│  - exceptions.py + exception_handler.py（全局异常捕获与处理）                                │
│  - alerting.py（可扩展告警通道：钉钉/飞书/Webhook）                                          │
│  - response.py（统一响应包装 {code,msg,data,timestamp}）                                    │
│  - redis_client.py（Redis 连接池 + 断线重连）                                                │
│  - task_queue.py（Redis List 异步任务队列）                                                  │
│  - task_scheduler.py（APScheduler 定时调度：Cron/Interval/Date）                            │
│  - task_states.py + task_exceptions.py（任务状态与异常）                                    │
│  - db_base.py + db_models.py（SQLAlchemy 2.0 ORM：Base 与核心数据模型）                    │
└──────────────────────────────────────────────────────────────────────────────────────────────┘
          ↑ 上层依赖下层，禁止反向依赖；同层模块通过 registry.py / 公共 API 解耦调用 ↑
```

**分层调用规则**（自上而下，禁止反向）：
```
L4 接入展示层 (adapter, web_admin)  ──→  L3, L2, L1
L3 业务模块层 (business/*)            ──→  L2, L1
L2 通用能力层 (core/*)               ──→  L1
L1 基础基建层 (infra/*)              ──→  无业务层依赖
```

---

## 🛠 完整技术栈

| 领域 | 技术选型 |
|------|---------|
| **后端框架** | FastAPI + Pydantic v2 + Python 3.10+ |
| **爬虫引擎** | Playwright（动态页面渲染）+ 代理池 + UA 池 + 风控降级 |
| **任务调度** | APScheduler（Cron/Interval/Date）+ Redis List 异步队列 |
| **数据存储** | SQLAlchemy 2.0 + SQLite（默认，零配置可运行）/ MySQL（可选） |
| **缓存/会话** | Redis 5.0+ + 连接池 + 断线重连降级 |
| **消息触达** | 邮件 SMTP / 飞书 Webhook / 企业微信 / H5 落地页链接生成 |
| **前端** | 纯 HTML + CSS + 原生 JavaScript（无 npm、无构建链） |
| **测试** | pytest + 单元测试按任务拆分（test_t##_*.py） |
| **日志** | 多文件轮转 + 控制台输出 + 结构化 JSON 日志 |
| **告警** | 可扩展告警通道框架（钉钉/飞书/Webhook，按配置启用） |
| **部署** | Docker Compose 容器编排支持（配置文件参考 docs/ 目录） |

---

## 📦 完整目录树结构

```
BizTools4OpenClaw/
├── adapter/                 # L4 - OpenClaw 适配网关（T13）
│   ├── __init__.py
│   ├── main.py              # FastAPI 主入口（挂载 web_admin 路由）
│   ├── auth.py              # OpenClaw 认证
│   ├── middleware.py        # 网关中间件（trace_id / 日志 / 限流）
│   ├── models.py            # 请求/响应模型
│   ├── response.py          # 网关响应包装
│   ├── schema_adapter.py    # 参数 Schema 适配
│   ├── tool_registry.py     # 工具注册表（OpenClaw Tool 规范）
│   ├── tools_router.py      # 工具 API 路由
│   └── task_router.py       # 任务状态/回调路由
│
├── web_admin/               # L4 - Web 管理后台（T14）
│   ├── __init__.py
│   ├── main.py              # 后台挂载器（挂载到 adapter/main.py）
│   ├── auth.py              # 登录 + Cookie 会话 + Redis
│   ├── middleware.py        # 行为审计中间件 + 高危操作告警
│   ├── menu.py              # 左侧菜单定义
│   ├── pages.py             # HTML 页面路由（纯字符串模板）
│   ├── api/                 # 6 个后台 API 模块
│   │   ├── __init__.py
│   │   ├── dashboard.py     # 数据看板（抓取/线索/触达/漏斗）
│   │   ├── spider_task.py   # 爬虫任务管理
│   │   ├── lead_mgmt.py     # 商机线索管理 + 人工复核
│   │   ├── channel_account.py # 渠道账号配置
│   │   ├── sales_mgmt.py    # 销售管理 + 逾期告警
│   │   └── audit_log.py     # 操作审计日志
│   ├── static/
│   │   ├── css/admin.css    # 后台样式（卡片/表格/响应式）
│   │   └── js/admin.js      # 前端交互（fetch / 表格渲染 / 脱敏）
│   └── templates/           # HTML 模板片段
│       ├── login.html
│       └── partials/        # dashboard / spider_task / leads / channels / sales / audit
│
├── business/                # L3 - 业务模块层
│   ├── multi_spider/        # 全源爬虫业务（T09）
│   │   ├── __init__.py
│   │   ├── base.py          # 爬虫基类（BaseSpider）
│   │   ├── models.py        # 业务模型
│   │   ├── pipeline.py      # 爬虫流水线
│   │   ├── registry.py      # 任务注册表
│   │   └── sources/         # 6 个具体数据源
│   │       ├── generic_web.py       # 通用网页
│   │       ├── douyin_xhs.py        # 抖音/小红书
│   │       ├── enterprise_news.py   # 企业动态/行业资讯
│   │       ├── local_classifieds.py # 本地分类/供需平台
│   │       ├── zhihu_baiduqa.py     # 知乎/百度知道问答
│   │       └── bid_and_gov.py       # 招投标/政府采购
│   │
│   ├── data_clean/          # 数据清洗结构化（T10）
│   │   ├── __init__.py
│   │   ├── normalizer.py     # 字段标准化
│   │   ├── extractor.py      # 实体抽取（公司/联系人/电话/邮箱）
│   │   ├── filters.py        # 无效数据过滤
│   │   ├── compliance_step.py # 合规检查步骤
│   │   ├── engine_step.py    # 去重合并打分步骤
│   │   ├── pipeline.py       # 清洗流水线
│   │   ├── loader.py         # 数据加载
│   │   ├── storage.py        # 结构化数据存储
│   │   ├── models.py         # 业务模型
│   │   ├── _orm.py           # ORM 辅助
│   │   └── registry.py       # 清洗任务注册
│   │
│   ├── customer_send/       # 多渠道触达（T11）
│   │   ├── __init__.py
│   │   ├── pipeline.py       # 触达流水线
│   │   ├── registry.py       # 渠道注册表
│   │   ├── storage.py        # 发送记录存储
│   │   ├── models.py         # 业务模型
│   │   ├── template_engine.py # 消息模板引擎
│   │   ├── _orm.py           # ORM 辅助
│   │   └── channels/         # 4 个具体渠道
│   │       ├── email_channel.py   # 邮件（SMTP）
│   │       ├── feishu_channel.py  # 飞书机器人/应用
│   │       ├── wechat_channel.py  # 微信/企业微信
│   │       └── h5_landing.py      # H5 落地页链接生成
│   │
│   └── sales_task/          # 销售调度与跟进闭环（T12）
│       ├── __init__.py
│       ├── assignment_engine.py   # 商机自动分配
│       ├── funnel_engine.py       # 转化漏斗统计
│       ├── status_engine.py       # 商机状态流转
│       ├── reminder_engine.py     # 定时跟进提醒
│       ├── push_notifier.py       # 推送通知器
│       ├── pipeline.py            # 销售流水线
│       ├── storage.py             # 销售数据存储
│       ├── models.py              # 业务模型
│       ├── _orm.py                # ORM 辅助
│       └── registry.py            # 销售任务注册
│
├── core/                    # L2 - 通用能力层
│   ├── spider_core/         # 爬虫核心通用 SDK（T05）
│   │   ├── __init__.py
│   │   ├── sdk.py           # Playwright 封装 + 统一爬取接口
│   │   ├── proxy_pool.py    # 代理池管理
│   │   ├── ua_pool.py       # User-Agent 池
│   │   ├── rate_limiter.py  # 速率限制
│   │   ├── risk_controller.py # 风控降级策略
│   │   ├── robots_checker.py # robots.txt 校验
│   │   ├── checkpoint_manager.py # 断点续爬
│   │   └── exceptions.py    # 爬虫异常类型
│   │
│   ├── data_core/           # 商机去重合并打分（T07）
│   │   ├── __init__.py
│   │   ├── dedupe_engine.py  # 去重引擎
│   │   ├── merge_engine.py   # 合并引擎
│   │   ├── scoring_engine.py # 打分分级引擎
│   │   ├── blacklist_filter.py # 黑名单过滤
│   │   └── pipeline.py       # 数据处理流水线
│   │
│   ├── send_core/           # 多渠道消息风控核心底座（T08）
│   │   ├── __init__.py
│   │   ├── account_pool.py   # 多账号池负载均衡
│   │   ├── rate_limiter.py   # 发送频率限制
│   │   ├── content_risk.py   # 内容风控（敏感词检测）
│   │   ├── ban_detector.py   # 封禁检测
│   │   ├── failure_retry.py  # 失败自动重试（指数退避）
│   │   ├── send_pipeline.py  # 发送流水线
│   │   └── task_status.py    # 发送任务状态
│   │
│   └── compliance/          # 数据合规/脱敏/敏感词检测（T04+T06）
│       ├── __init__.py
│       ├── pii_mask.py       # 隐私字段掩码（手机号/邮箱脱敏）
│       ├── privacy_stripper.py # 隐私信息剥离
│       ├── sensitive_crypto.py # 敏感字段加密存储
│       ├── sensitive_filter.py # 敏感词检测
│       ├── compliance_checker.py # 合规检查器
│       ├── archive_mixin.py  # 数据归档 Mixin
│       └── data_lifecycle.py # 数据生命周期管理
│
├── infra/                   # L1 - 基础基建层
│   ├── __init__.py
│   ├── logger_setup.py      # 统一日志配置（多文件 + 控制台 + 等级过滤）
│   ├── exceptions.py        # 全局异常类型定义
│   ├── exception_handler.py # FastAPI 全局异常处理中间件
│   ├── alerting.py          # 告警推送（钉钉/飞书/Webhook 可扩展）
│   ├── response.py          # 统一响应包装 {code,msg,data,timestamp}
│   ├── redis_client.py      # Redis 客户端（连接池 + 断线重连）
│   ├── task_queue.py        # 异步任务队列（Redis List 实现）
│   ├── task_scheduler.py    # APScheduler 定时调度（Cron/Interval/Date）
│   ├── task_states.py       # 任务状态定义与持久化
│   ├── task_exceptions.py   # 任务专属异常类型
│   ├── db_base.py           # SQLAlchemy Base + 数据库连接管理
│   └── db_models.py         # 核心 ORM 数据模型（Lead/Channel/Task/Log 等）
│
├── configs/                 # 多环境配置
│   ├── __init__.py
│   ├── settings.py          # 全局 Settings（含 WebAdminSettings）
│   └── templates/           # 消息模板文件
│       ├── email_default.html
│       ├── feishu_card.json
│       └── wechat_card.json
│
├── tests/                   # 单元测试（14 份 + conftest）
│   ├── conftest.py          # pytest 全局 fixture
│   ├── test_t02_infra.py ~ test_t14_web_admin.py
│   └── __init__.py
│
├── docs/                    # 项目文档
│   ├── TASK_LIST.md         # 全量任务拆分清单与进度（T15 新建）
│   └── T02_INFRA_USAGE.md   # T02 基础设施使用说明
│
├── examples/                # OpenClaw 调用示例
│   └── openclaw_skills_demo.yaml  # OpenClaw Skill 注册示例 YAML
│
├── docker/                  # 容器部署（目录已建立，配置参考 docs/）
├── .github/                 # GitHub 配置（目录已建立）
├── logs/                    # 运行时日志输出目录（自动创建）
│
├── README.md                # 项目总说明
├── DEVELOP_RULES.md         # 开发规范总纲
├── requirements.txt         # Python 依赖清单
└── .env.example             # 环境变量示例（敏感信息不提交）
```

---

## 🔌 全渠道商机来源清单

### 爬虫数据源（6 个，business/multi_spider/sources/）

| 数据源文件 | 覆盖场景 | 典型商机类型 |
|-----------|---------|-------------|
| `generic_web.py` | 通用网页爬取 | 公司官网产品页、行业资讯站、B2B 平台 |
| `douyin_xhs.py` | 抖音/小红书 | 短视频带货线索、内容营销转化 |
| `enterprise_news.py` | 企业动态/行业资讯 | 公司新品发布、招投标预告、行业会议 |
| `local_classifieds.py` | 本地分类信息/供需平台 | 同城服务、二手交易、本地商家合作 |
| `zhihu_baiduqa.py` | 知乎/百度知道问答 | 行业问答、需求提问、产品推荐请求 |
| `bid_and_gov.py` | 招投标/政府采购 | 公开招标信息、政府采购需求、工程发包 |

### 消息触达渠道（4 个，business/customer_send/channels/）

| 渠道文件 | 类型 | 适用场景 | 能力 |
|---------|------|---------|------|
| `email_channel.py` | 邮件 | B2B 正式沟通、批量营销 | SMTP 发送、模板渲染、附件支持、发送频率限制 |
| `feishu_channel.py` | 飞书机器人/应用 | 团队协作通知、群运营 | Webhook 推送、卡片消息、@ 提及、群组管理 |
| `wechat_channel.py` | 微信/企业微信 | 社交触达、客户一对一跟进 | 消息模板、账号池轮转、风控限流、状态回调 |
| `h5_landing.py` | H5 落地页 | 链接生成与分享、扫码引流 | 动态页面 URL、访问统计、转化追踪 |

---

## 🚀 快速开始 — 环境部署与启动流程

### 7.1 前置条件

- **Python ≥ 3.10**（推荐 3.10 / 3.11 / 3.12）
- **Redis ≥ 5.0**（可选，未启动时自动降级为内存缓存，部分异步任务功能受限）
- **Git**（克隆项目代码）
- **操作系统**：Windows / macOS / Linux（跨平台）

### 7.2 克隆项目并安装依赖

```bash
# 1. 克隆仓库
git clone https://github.com/justinpang/BizTools4Openclaw.git
cd BizTools4Openclaw

# 2. （可选但推荐）创建虚拟环境
python -m venv venv
# Windows:
venv\Scripts\activate
# macOS/Linux:
source venv/bin/activate

# 3. 安装 Python 依赖
pip install -r requirements.txt
```

### 7.3 配置环境变量

```bash
# 复制环境变量示例文件（Windows PowerShell）
Copy-Item .env.example .env

# 或 cmd
copy .env.example .env

# 编辑 .env，按需配置以下关键项（默认值可直接运行零配置版本）：
# - LOG_LEVEL:                 日志级别（DEBUG/INFO/WARNING/ERROR）
# - REDIS_URL:                 Redis 连接 URL（留空则降级为内存缓存）
# - DATABASE_URL:              数据库连接（默认 SQLite，留空即 ./data.db）
# - WEB_ADMIN_USERNAME:        Web 管理后台登录账号
# - WEB_ADMIN_PASSWORD_PLAIN:  Web 管理后台登录密码（明文，自动 hash 存储）
# - WEB_ADMIN_SESSION_TTL_SECONDS:  后台会话过期时间（秒，默认 28800=8h）
# - 各渠道配置：EMAIL_*/FEISHU_*/WECHAT_*（按需填写，留空则该渠道不启用）
```

### 7.4 启动服务

```bash
# 以模块方式启动（推荐，统一入口）
python -m adapter.main
```

启动后控制台将输出类似日志：
```
INFO | openclaw.app | BizTools4Openclaw started on http://0.0.0.0:8000
INFO | web_admin.main | web_admin mounted: /admin/* and /api/admin/*
```

### 7.5 验证访问

| 服务 | 地址 | 说明 |
|------|------|------|
| **Web 管理后台** | http://localhost:8000/admin | `WEB_ADMIN_USERNAME` / `WEB_ADMIN_PASSWORD_PLAIN` 登录 |
| **OpenClaw 网关 API (Swagger)** | http://localhost:8000/docs | 查看/调试全部 API（需认证的端点需登录后台） |
| **OpenClaw 网关 API (ReDoc)** | http://localhost:8000/redoc | 备用文档视图 |
| **健康检查** | http://localhost:8000/health | JSON: `{"code":0,"msg":"success","data":{"status":"ok"},"timestamp":...}` |

---

## 🔗 OpenClaw 对接完整步骤

本项目通过 `adapter/` 目录暴露标准 HTTP API，可被 OpenClaw 智能体作为 Tool/Skill 注册与调用。

### 8.1 在 OpenClaw 平台注册自定义工具（Skill）

登录 OpenClaw 管理后台，进入「工具管理 → 新建自定义 Skill」。

### 8.2 使用项目提供的示例 YAML 作为模板

复制并编辑项目内的 Skill 定义模板：

```yaml
# examples/openclaw_skills_demo.yaml
# 根据 .env 中配置的实际服务地址修改 baseUrl
```

### 8.3 配置工具 API Base URL

将 Base URL 指向本项目的 FastAPI 服务（即 `python -m adapter.main` 启动的服务）：

```
Base URL: http(s)://<your-host>:<port>   # 默认 http://localhost:8000
```

### 8.4 配置认证 Token（参考 adapter/auth.py）

- 若部署在公网，建议设置 Token；本地调试可留空
- 实现细节见 `adapter/auth.py`，支持 Header Token 与 Cookie 会话

### 8.5 测试典型调用（可在 http://localhost:8000/docs 中直接试调用）

| 操作 | 方法 | 端点 | 说明 |
|------|------|------|------|
| 健康检查 | GET | `/health` | 确认服务可用 |
| 获取商机列表 | GET | `/api/admin/leads/` | 分页查询结构化商机线索 |
| 触发爬虫任务 | POST | `/api/admin/spider/<source>/run` | 立即执行指定数据源抓取 |
| 查询爬虫日志 | GET | `/api/admin/spider/logs` | 查看抓取结果与异常记录 |
| 触发消息触达 | POST | `/api/admin/channels/<channel>/send` | 向指定 Lead 发送消息 |

### 8.6 异步任务回调流程

1. 客户端 POST 触发长时间任务 → 服务端立即返回 `task_id`
2. 客户端通过 `GET /api/admin/tasks/<task_id>/status` 轮询任务状态（pending / running / success / failed）
3. 任务完成后可通过 `GET /api/admin/tasks/<task_id>/result` 获取结构化结果
4. 如需主动取消任务，调用 `POST /api/admin/tasks/<task_id>/cancel`
5. 全流程由 `infra/task_queue.py` + `infra/task_scheduler.py` + `adapter/task_router.py` 协作完成

---

## 📊 各模块能力说明

### L1 基础基建层
- **`infra/logger_setup.py`**：统一日志入口，自动创建 `logs/` 目录，多文件按级别轮转，控制台同步输出
- **`infra/exceptions.py` + `exception_handler.py`**：定义业务异常分层，FastAPI 全局捕获转为统一 JSON 响应
- **`infra/alerting.py`**：可扩展告警框架，支持钉钉/飞书/Webhook，web_admin 高危操作自动触发
- **`infra/response.py`**：统一响应包装 `{code, msg, data, timestamp}`，所有对外 API 强制使用
- **`infra/redis_client.py`**：Redis 连接池 + 断线自动降级内存缓存，会话存储与任务队列共用
- **`infra/task_queue.py` + `task_scheduler.py`**：异步任务队列 + Cron 定时调度双引擎
- **`infra/db_base.py` + `db_models.py`**：SQLAlchemy 2.0 ORM，Base 类 + 核心数据模型（Lead/Task/Log/ChannelAccount/SalesRecord 等）

### L2 通用能力层
- **`core/spider_core/sdk.py`**：Playwright 封装，统一 `fetch_html / fetch_json / scrape_list` 接口
- **`core/spider_core/risk_controller.py`**：风控降级，检测到平台反爬策略自动降速/暂停/告警
- **`core/data_core/dedupe_engine.py`**：基于内容哈希 + 字段相似度的双重去重引擎
- **`core/data_core/scoring_engine.py`**：商机打分分级，根据关键字、来源、时效性加权
- **`core/send_core/account_pool.py`**：多账号轮转载均衡，避免单账号超限
- **`core/send_core/content_risk.py`**：发送前敏感词检测，违规内容阻断发送并记录
- **`core/compliance/pii_mask.py`**：手机号/邮箱/身份证等 PII 自动掩码展示
- **`core/compliance/sensitive_crypto.py`**：密钥/密码等字段入库加密、使用时解密

### L3 业务模块层
- **`business/multi_spider/registry.py`**：爬虫任务注册中心，L4 层通过它触发/查询爬虫任务
- **`business/data_clean/pipeline.py`**：清洗流水线：原始数据 → 标准化 → 抽取 → 过滤 → 去重 → 打分 → 入库
- **`business/customer_send/channels/*.py`**：4 个触达渠道，统一 `send(recipient, content, template_id)` 接口
- **`business/sales_task/assignment_engine.py`**：根据销售人员负载、区域、行业自动分配商机

### L4 接入展示层 - 管理后台
Web 管理后台共 **7 个页面 + 6 个 API 模块**，纯 HTML/CSS/原生 JS 实现：

| 页面 | 说明 | API |
|------|------|-----|
| 登录页 | 账号密码登录，Redis 会话，8h 过期 | `/admin/login` |
| 数据看板 | 抓取总量/有效线索/触达数/转化漏斗 | `dashboard.py` |
| 爬虫任务 | 新建/启停/编辑定时抓取、查看日志 | `spider_task.py` |
| 商机线索 | 列表/筛选/详情、人工复核、黑名单 | `lead_mgmt.py` |
| 渠道账号 | 邮件/飞书/企微账号配置、发送额度 | `channel_account.py` |
| 销售管理 | 销售人员配置、商机分配、逾期告警 | `sales_mgmt.py` |
| 操作审计 | 全操作行为日志，高危操作标红 | `audit_log.py` |

### L4 接入展示层 - OpenClaw 网关
- `adapter/main.py`：统一 FastAPI 入口，挂载 web_admin 路由 + API 路由 + 静态文件
- `adapter/tool_registry.py`：工具注册表，定义可被 OpenClaw 智能体调用的 Tool 清单
- `adapter/tools_router.py`：工具调用 API
- `adapter/task_router.py`：异步任务状态查询/取消/重试 API

---

## 🧪 运行单元测试

本项目所有单元测试按任务编号拆分，文件命名规范：`tests/test_t##_<module>.py`。

```bash
# 全量运行所有任务的单元测试（verbose 模式 + 短回溯）
pytest tests/ -v --tb=short

# 只运行特定任务的测试（示例：T14 Web 管理后台）
pytest tests/test_t14_web_admin.py -v

# 查看测试覆盖率（需额外安装 coverage）
pip install coverage
coverage run -m pytest tests/
coverage report -m
```

测试文件清单（`tests/` 目录）：
- `test_t02_infra.py` ~ `test_t14_web_admin.py`（共 13 个任务测试文件）
- `conftest.py`（全局共享 fixture：临时数据库、Redis mock 等）

---

## 📝 开发规范与贡献指南

完整开发规范请阅读 [DEVELOP_RULES.md](DEVELOP_RULES.md)，以下为快速要点：

### Git 分支规范
- `main`：生产主分支（受保护，禁止直接推送）
- `dev`：开发集成分支
- `feature/T##_xxx`：功能分支（T## 为任务编号）
- `fix/T##_xxx` / `fix/issue-xxx`：修复分支

### Git 提交消息规范（强制执行）
```bash
# 格式：<type>(T##): <中文简要说明>
# 推荐示例：
feat(T14): 轻量 Web 管理后台 - 可视化运维/商机线索/渠道账号/销售管理
fix(T08): 修复消息发送频率超限未正确触发告警的问题
docs(T15): 全量校对三份核心文档，同步架构与任务最新状态
refactor(T10): 重构清洗流水线实体抽取模块，提升实体识别准确率
test(T07): 补充打分引擎边界用例
chore: 更新 requirements.txt 依赖版本
```

### 贡献流程
1. 从 `main` 创建 `feature/T##_xxx` 分支
2. 完成功能开发，确保对应 `tests/test_t##_*.py` 全部通过
3. 同步更新相关文档章节（README 能力说明 / DEVELOP_RULES 新增规范）
4. 提交 PR，关联任务编号，等待 Review
5. Review 通过后合并至 `main`

---

## ❓ 常见问题 FAQ

### Q1: Redis 未启动或连接失败如何处理？
A: 本项目对 Redis 非强依赖。`infra/redis_client.py` 在 Redis 不可用时会**自动降级为内存缓存**（Python dict 实现），服务可正常启动，仅影响以下功能：
- 异步任务队列（降级为同步执行，无并发）
- 定时任务持久化（重启后丢失）
- web_admin 会话共享（多实例部署时仅单进程有效）
- 告警去重

**建议**：开发环境可不启动 Redis；生产环境务必启动 Redis ≥ 5.0。

### Q2: 爬虫被风控封禁如何排查？
A: 有三个入口可联合排查：
1. **Web 管理后台 → 爬虫任务**：查看 `logs/` 中的抓取日志与风控异常记录
2. **`logs/*.log` 文件**：所有反爬触发均会记录 `WARNING` / `ERROR` 级别日志
3. **告警通道**：风控降级会自动触发 `infra/alerting.py` 推送告警（需配置告警目标）

### Q3: 如何新增自定义数据源？
A: 三步完成：
1. 在 `business/multi_spider/sources/` 下新增文件 `your_source.py`
2. 继承 `business/multi_spider/base.py` 中的 `BaseSpider`，实现 `scrape()` / `normalize()` 方法
3. 在 `business/multi_spider/registry.py` 中注册新数据源

可直接参考 `generic_web.py` 的实现模式。

### Q4: 如何新增自定义触达渠道？
A: 三步完成：
1. 在 `business/customer_send/channels/` 下新增文件 `your_channel.py`
2. 实现统一接口 `send(recipient, content, template_id, **kwargs)` + `get_status(task_id)`
3. 在 `business/customer_send/registry.py` 中注册新渠道

可直接参考 `email_channel.py` 的实现模式。

### Q5: Web 管理后台账号如何修改？
A: 管理后台账号完全通过 `.env` 文件配置，不存储在代码中：
- `WEB_ADMIN_USERNAME`：登录账号（默认 `admin`）
- `WEB_ADMIN_PASSWORD_PLAIN`：登录密码（明文，服务启动时自动 hash 存储）
- `WEB_ADMIN_SESSION_TTL_SECONDS`：会话过期时间（默认 28800 秒 = 8 小时）
- `WEB_ADMIN_PAGE_SIZE`：后台列表每页条数（默认 20）

修改 `.env` 后重启 `python -m adapter.main` 即可生效。

### Q6: 数据如何备份？
A: 根据存储类型选择：
- **SQLite（默认）**：直接复制 `./data.db` 文件即可；建议每天自动备份
- **MySQL（可选）**：使用 `mysqldump -u <user> -p <db> > backup_YYYYMMDD.sql`
- **Redis（可选）**：`redis-cli BGSAVE` 生成 `dump.rdb`
- 冷数据归档由 `core/compliance/archive_mixin.py` 自动处理，无需手动操作

### Q7: 为什么选择纯 HTML + 原生 JS 做前端，不使用 React/Vue？
A: 两个核心设计决策：
1. **零构建链**：无需 npm/yarn/pnpm、无需 Webpack/Vite，`python -m adapter.main` 即可完整运行，降低部署和维护复杂度
2. **轻量化后台**：管理后台以表格/列表/表单为主，交互复杂度不高，原生 JavaScript + fetch 完全覆盖需求
如未来交互复杂度显著提升，可在 `web_admin/static/js/` 内平滑引入框架，对架构无侵入。

### Q8: 数据库默认使用 SQLite，如何切换到 MySQL？
A: 修改 `.env` 中 `DATABASE_URL` 即可：
```
# 默认 SQLite（零配置，文件自动创建）
DATABASE_URL=sqlite:///./data.db

# 切换 MySQL（需先 pip install pymysql sqlalchemy）
DATABASE_URL=mysql+pymysql://user:password@host:3306/biztools
```
ORM 层由 `infra/db_base.py` / `db_models.py` 统一管理，切换数据库无需修改业务代码。

---

## 📚 项目文档索引

| 文档 | 说明 |
|------|------|
| [README.md](README.md) | 项目总说明（本文件） |
| [DEVELOP_RULES.md](DEVELOP_RULES.md) | 开发规范总纲（架构/编码/Git/测试/交付） |
| [docs/TASK_LIST.md](docs/TASK_LIST.md) | 全量任务清单与完成进度（T01-T14） |
| [docs/T02_INFRA_USAGE.md](docs/T02_INFRA_USAGE.md) | T02 基础设施使用说明 |
| [examples/openclaw_skills_demo.yaml](examples/openclaw_skills_demo.yaml) | OpenClaw Skill 注册示例 YAML |

---

## 📄 开源协议与免责声明

MIT License，可自由二次开发、商用部署。

**免责声明**：
- 本项目仅提供技术框架，使用者需自行确保爬虫行为符合目标网站 `robots.txt` 与相关法律法规
- 消息触达功能的发送频率、内容合规性由使用者自行负责
- 所有敏感字段（手机号、邮箱、密钥、密码）默认脱敏展示与加密存储，建议使用者定期审计日志与数据库访问权限
- 请勿将本项目用于非法用途
