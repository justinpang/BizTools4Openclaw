# TASK_LIST — 任务清单与完成进度总览

> 文档状态：`docs(T15)` 同步至 T01-T14 最新实现
> 所属项目：BizTools4Openclaw
> 架构分层：L1 基础基建 → L2 通用能力 → L3 业务模块 → L4 接入展示

---

## 一、任务总览表（按任务编号）

| 任务编号 | 任务名称 | 所属分层 | 依赖任务 | 优先级 | 状态 | Git Commit 格式建议 | 交付物（关键文件） | 完成标准 |
|---------|---------|---------|---------|-------|------|-------------------|--------------------|---------|
| **T01** | 项目骨架与基础配置搭建 | L1 基建 / 通用 | — | **P0** | ✅ 完成 | `feat(T01): 项目骨架与基础配置搭建` | `configs/settings.py`、`requirements.txt`、`.env.example`、`adapter/__init__.py` | 项目可 `pip install -r requirements.txt`，可 `import configs.settings`，配置可从环境变量加载 |
| **T02** | 全局日志 / 异常 / 告警基建 | L1 基建 | T01 | **P0** | ✅ 完成 | `feat(T02): 全局日志、异常处理与告警基建搭建` | `infra/logger_setup.py`、`infra/exceptions.py`、`infra/exception_handler.py`、`infra/alerting.py`、`infra/response.py` | 日志写入 `logs/*.log`，异常可被 FastAPI 全局捕获并返回标准 JSON，告警可触发 |
| **T03** | Redis 异步任务队列与定时调度 | L1 基建 | T01, T02 | **P0** | ✅ 完成 | `feat(T03): Redis 异步任务队列与 APScheduler 定时调度基建` | `infra/task_queue.py`、`infra/task_scheduler.py`、`infra/task_states.py`、`infra/task_exceptions.py`、`infra/redis_client.py` | 可提交异步任务并执行，Cron / Interval 定时任务可触发，Redis 不可用时降级内存缓存 |
| **T04** | 数据库分层架构与 ORM 模型 | L1 基建 | T01 | **P0** | ✅ 完成 | `feat(T04): 数据库分层架构与 SQLAlchemy ORM 模型` | `infra/db_base.py`、`infra/db_models.py` | SQLAlchemy 2.0 Base 可初始化，核心表（Lead/Task/Channel/Log/Record）可建表、可 CRUD，支持 SQLite/MySQL 双后端 |
| **T05** | 爬虫核心通用 SDK | L2 通用 | T02, T03 | **P0** | ✅ 完成 | `feat(T05): 爬虫核心通用 SDK（Playwright + 代理 + UA + 风控 + robots + 断点续爬）` | `core/spider_core/sdk.py`、`core/spider_core/proxy_pool.py`、`core/spider_core/ua_pool.py`、`core/spider_core/rate_limiter.py`、`core/spider_core/risk_controller.py`、`core/spider_core/robots_checker.py`、`core/spider_core/checkpoint_manager.py`、`core/spider_core/exceptions.py` | Playwright 可抓取任意公开页面，代理/UA 生效，robots 可校验，风控降级可触发，断点可恢复 |
| **T06** | 数据合规 / 脱敏 / 敏感词检测 | L2 通用 | T02, T04 | **P0** | ✅ 完成 | `feat(T06): 数据合规、PII 脱敏、敏感词检测与敏感字段加密核心工具` | `core/compliance/pii_mask.py`、`core/compliance/privacy_stripper.py`、`core/compliance/sensitive_crypto.py`、`core/compliance/sensitive_filter.py`、`core/compliance/compliance_checker.py`、`core/compliance/archive_mixin.py`、`core/compliance/data_lifecycle.py` | 手机号/邮箱/身份证自动掩码，敏感词可检测，敏感字段加密存储，归档逻辑可运行 |
| **T07** | 商机去重 / 合并 / 打分 / 分级 | L2 通用 | T04, T06 | **P1** | ✅ 完成 | `feat(T07): 商机去重合并打分分级引擎` | `core/data_core/dedupe_engine.py`、`core/data_core/merge_engine.py`、`core/data_core/scoring_engine.py`、`core/data_core/pipeline.py`、`core/data_core/blacklist_filter.py` | 重复商机可识别与合并，分数分级可输出，黑名单可过滤，集成进清洗流水线 |
| **T08** | 多渠道消息风控核心底座 | L2 通用 | T02, T06 | **P1** | ✅ 完成 | `feat(T08): 多渠道消息风控核心底座（账号池/限流/内容风控/封禁检测/自动重试）` | `core/send_core/account_pool.py`、`core/send_core/rate_limiter.py`、`core/send_core/content_risk.py`、`core/send_core/ban_detector.py`、`core/send_core/failure_retry.py`、`core/send_core/send_pipeline.py`、`core/send_core/task_status.py` | 多账号轮转、单账号限流、敏感词检测、封禁自动移除、失败指数退避、发送流水线可串联 |
| **T09** | 全网多源爬虫业务模块 | L3 业务 | T05, T06 | **P0** | ✅ 完成 | `feat(T09): 全网多源爬虫业务模块（6 个数据源 + 注册中心 + 流水线）` | `business/multi_spider/__init__.py`、`business/multi_spider/base.py`、`business/multi_spider/models.py`、`business/multi_spider/pipeline.py`、`business/multi_spider/registry.py`、`business/multi_spider/sources/generic_web.py`、`business/multi_spider/sources/douyin_xhs.py`、`business/multi_spider/sources/enterprise_news.py`、`business/multi_spider/sources/local_classifieds.py`、`business/multi_spider/sources/zhihu_baiduqa.py`、`business/multi_spider/sources/bid_and_gov.py` | 6 个数据源可独立抓取，BaseSpider 规范统一，registry 可注册/发现，清洗后可入库 |
| **T10** | 数据清洗 / 实体抽取 / 标准化 | L3 业务 | T06, T07 | **P1** | ✅ 完成 | `feat(T10): 数据清洗、实体抽取、标准化结构化流水线` | `business/data_clean/normalizer.py`、`business/data_clean/extractor.py`、`business/data_clean/filters.py`、`business/data_clean/compliance_step.py`、`business/data_clean/engine_step.py`、`business/data_clean/pipeline.py`、`business/data_clean/loader.py`、`business/data_clean/storage.py`、`business/data_clean/models.py`、`business/data_clean/_orm.py`、`business/data_clean/registry.py` | 原始数据 → 标准化 → 实体抽取 → 过滤 → 去重合并打分 → 入库；公司/联系人/电话/邮箱可识别 |
| **T11** | 多渠道自动化商机触达 | L3 业务 | T08 | **P1** | ✅ 完成 | `feat(T11): 多渠道自动化商机触达业务模块（邮件/飞书/企微/H5）` | `business/customer_send/pipeline.py`、`business/customer_send/registry.py`、`business/customer_send/storage.py`、`business/customer_send/models.py`、`business/customer_send/template_engine.py`、`business/customer_send/_orm.py`、`business/customer_send/channels/email_channel.py`、`business/customer_send/channels/feishu_channel.py`、`business/customer_send/channels/wechat_channel.py`、`business/customer_send/channels/h5_landing.py` | 4 个渠道可发送，模板引擎可渲染，发送记录可存储，可按 Lead 维度触达 |
| **T12** | 销售商机调度与跟进闭环 | L3 业务 | T10, T11 | **P1** | ✅ 完成 | `feat(T12): 销售商机调度与跟进闭环系统（自动分配/状态流转/漏斗统计/定时提醒）` | `business/sales_task/assignment_engine.py`、`business/sales_task/funnel_engine.py`、`business/sales_task/status_engine.py`、`business/sales_task/reminder_engine.py`、`business/sales_task/push_notifier.py`、`business/sales_task/pipeline.py`、`business/sales_task/storage.py`、`business/sales_task/models.py`、`business/sales_task/_orm.py`、`business/sales_task/registry.py` | 商机自动分配到销售，状态可流转（未触达→已触达→已跟进→已成交），转化漏斗可统计，定时提醒可触发 |
| **T13** | OpenClaw 网关与工具注册 | L4 接入 | T02, T09, T11 | **P0** | ✅ 完成 | `feat(T13): OpenClaw 适配网关、工具注册表与全链路智能体对接层` | `adapter/main.py`、`adapter/auth.py`、`adapter/middleware.py`、`adapter/models.py`、`adapter/schema_adapter.py`、`adapter/tool_registry.py`、`adapter/tools_router.py`、`adapter/task_router.py` | FastAPI 可启动，`/docs` 可浏览，工具可注册/调用，任务可轮询状态/取消/重试，全局中间件日志/告警生效 |
| **T14** | 轻量 Web 管理后台 | L4 接入 | T02, T13 | **P1** | ✅ 完成 | `feat(T14): 轻量 Web 管理后台（登录鉴权/看板/爬虫/线索/渠道/销售/审计）` | `web_admin/main.py`、`web_admin/auth.py`、`web_admin/middleware.py`、`web_admin/menu.py`、`web_admin/pages.py`、`web_admin/api/dashboard.py`、`web_admin/api/spider_task.py`、`web_admin/api/lead_mgmt.py`、`web_admin/api/channel_account.py`、`web_admin/api/sales_mgmt.py`、`web_admin/api/audit_log.py`、`web_admin/static/css/admin.css`、`web_admin/static/js/admin.js`、`web_admin/templates/login.html`、`web_admin/templates/partials/dashboard.html`、`web_admin/templates/partials/spider_task.html`、`web_admin/templates/partials/leads.html`、`web_admin/templates/partials/channels.html`、`web_admin/templates/partials/sales.html`、`web_admin/templates/partials/audit.html` | 账号密码可登录，6 大管理页面可用，操作审计日志可记录，高危操作可触发告警，前端无 npm 依赖，纯 HTML/CSS/JS 可用 |
| **T15** | 全量校对 / 完善 / 统一三份核心文档 | 文档 | T01–T14 | **P1** | ✅ 完成 | `docs(T15): 全量校对 README/DEVELOP_RULES/TASK_LIST 三份核心文档` | `README.md`、`DEVELOP_RULES.md`、`docs/TASK_LIST.md` | 三份文档内所有术语/路径/模块名与实际代码完全一致，架构图、目录树、OpenClaw 对接步骤、Git 提交规范全部同步 |

---

## 二、分层架构与依赖关系可视化

### 2.1 架构四层结构图

```
                    ┌────────────────────── L4 接入展示层 ──────────────────────┐
                    │  adapter/         web_admin/                               │
                    │  ├─ main.py       ├─ main.py                              │
                    │  ├─ auth.py       ├─ auth.py                              │
                    │  ├─ middleware.py ├─ middleware.py                        │
                    │  ├─ tool_registry ├─ menu.py / pages.py                   │
                    │  ├─ tools_router  └─ api/* (6 个后台 API) + static/*      │
                    │  └─ task_router                                             │
                    ├────────────────────── L3 业务模块层 ───────────────────────┤
                    │  business/                                                   │
                    │  ├─ multi_spider/   (6 sources, T09)                       │
                    │  ├─ data_clean/     (normalizer+extractor+filters, T10)   │
                    │  ├─ customer_send/  (email+feishu+wechat+h5, T11)          │
                    │  └─ sales_task/     (assign+funnel+status+reminder, T12)  │
                    ├────────────────────── L2 通用能力层 ───────────────────────┤
                    │  core/                                                       │
                    │  ├─ spider_core/    (sdk+proxy+ua+rate+risk+robots+ckpt)   │
                    │  ├─ data_core/      (dedupe+merge+scoring+blacklist)       │
                    │  ├─ send_core/      (account_pool+rate+risk+ban+retry)     │
                    │  └─ compliance/     (pii_mask+privacy+filter+archive)      │
                    ├────────────────────── L1 基础基建层 ───────────────────────┤
                    │  infra/           configs/          docker/                │
                    │  ├─ logger_setup    ├─ settings.py    (容器部署)            │
                    │  ├─ exceptions      ├─ templates/                          │
                    │  ├─ alerting        └─ (_orm 辅助放各 L3 模块)             │
                    │  ├─ response                                                   │
                    │  ├─ redis_client                                             │
                    │  ├─ task_queue / task_scheduler                             │
                    │  ├─ task_states / task_exceptions                           │
                    │  └─ db_base / db_models                                       │
                    └───────────────────────────────────────────────────────────────┘
                              ↑ 上层依赖下层；同层模块通过 registry.py 解耦 ↑
```

### 2.2 任务依赖链

```
  ┌─ T01 (项目骨架 + 配置)
  │   ├─ T02 (日志/异常/告警) ───────────────┐
  │   │                                      │
  │   └─ T03 (任务队列 + 调度) ─→ T05 (爬虫 SDK) ─→ T06 (合规/脱敏/加密) ─→ T09 (多源爬虫业务) ─┐
  │                                                                                                │
  │   └─ T04 (数据库 ORM) ───────────────────┘                                                       │
  │                                      │                                                             │
  │                                      └─ T06 (合规) ─→ T07 (去重合并打分) ─→ T10 (清洗流水线) ─┐
  │                                                                                                │
  │   T02 + T06 ─→ T08 (消息风控底座) ─→ T11 (多渠道触达) ─────────────────────────────────────┐  │
  │                                                                                                │  │
  │   └────────────────────────────────────────────────────────────────────────────────────────┘  │
  │                                                                                                   │
  │   T10 + T11 ─→ T12 (销售调度与跟进闭环) ──────────────────────────────────────────────────┐     │
  │                                                                                              │     │
  │   T02 + T09 + T11 ─→ T13 (OpenClaw 网关 + 工具注册) ─→ T14 (Web 管理后台) ─→ T15 (文档校对) │
  │                                                                                              │     │
  └────────────────────────────────────────────────────────────────────────────────────────────┘     │
                                                                                                      │
  【关键依赖链速览】                                                                                   │
  - 爬虫链: T01 → T02/T03 → T05 → T06 → T09                                                         │
  - 数据链: T01 → T04 → T06 → T07 → T10                                                             │
  - 触达链: T01 → T02/T03 → T06 → T08 → T11                                                         │
  - 销售链: T10 + T11 → T12                                                                          │
  - 接入链: T02 + T09 + T11 → T13 → T14 → T15                                                       │
```

---

## 三、Git 提交与验收核对要点

### 3.1 Git 提交规范核对清单（每次提交前自检）

| 检查项 | 要求 |
|-------|------|
| 提交消息格式 | `<type>(T##): <中文简要说明>` |
| type 枚举 | feat / fix / docs / refactor / test / chore / style / perf |
| 任务编号 | 每次提交必须带任务编号（纯跨任务清理可省略为 `chore:`） |
| 单次提交粒度 | 一次提交对应一项功能或一个修复，不混杂多个不相关变更 |
| 禁止提交内容 | 不提交 `.env`、密钥、真实手机号/邮箱、大二进制文件 |
| 分支规范 | `feature/T##_xxx` / `fix/T##_xxx`，不直接 push `main` |
| PR 描述 | 含「改动说明」「影响范围」「测试结果摘要」「任务编号」 |

### 3.2 测试验收核对清单（每次合入 main 前）

| 检查项 | 验收标准 | 对应代码/文件 |
|-------|---------|--------------|
| 单元测试通过 | `pytest tests/test_t##_*.py -v --tb=short` 全部 OK | `tests/test_t##_*.py`、`tests/conftest.py` |
| 集成测试通过 | 爬虫抓取→清洗→入库端到端可跑；触达可 mock 发送 | `business/multi_spider/pipeline.py`、`business/data_clean/pipeline.py`、`business/customer_send/pipeline.py` |
| 后台页面可用 | 登录→各菜单→核心操作全部可在浏览器完成 | `http://localhost:8000/admin` + `web_admin/pages.py` |
| 健康检查 | `GET /health` 返回 code=0 | `adapter/main.py` |
| API 文档可访问 | `GET /docs`、`GET /redoc` 正常加载 | `adapter/main.py`（FastAPI 自带） |
| 敏感字段脱敏 | 手机号/邮箱/密钥在日志与 API 默认不出现明文 | `core/compliance/pii_mask.py`、`core/compliance/sensitive_crypto.py` |
| 高危操作告警 | 删除/封禁/批量发送操作触发告警写入 | `web_admin/middleware.py` + `infra/alerting.py` |
| 离线可运行 | 不依赖真实 Redis / 外网（测试环境） | `tests/conftest.py` 中 mock 与降级 |

### 3.3 文档同步核对清单

| 检查项 | 验收标准 |
|-------|---------|
| README 架构图更新 | 与 `infra/`、`core/`、`business/`、`adapter/`、`web_admin/` 目录结构一致 |
| README 目录树更新 | 与 `git ls-files` 实际存在的 py/html/css/js 文件完全对齐 |
| README OpenClaw 对接步骤 | 与 `adapter/main.py`、`adapter/tool_registry.py`、`adapter/task_router.py` 实际 API 完全一致 |
| README FAQ | 覆盖 Redis 未启动、数据库备份、新增数据源/渠道等高频问题 |
| DEVELOP_RULES 分层定义 | 与 README 中架构分层完全一致 |
| DEVELOP_RULES Git 规范 | 与实际提交历史（`feat(T01)` 至 `feat(T14)`）风格一致 |
| DEVELOP_RULES 测试规范 | 与 `tests/` 实际测试文件命名一致 |
| TASK_LIST 任务状态 | 与实际提交历史一致（T01–T15 均完成并已 commit） |
| TASK_LIST 依赖关系 | 与实际模块 import 方向一致（只允许上层依赖下层） |
| 三份文档术语统一 | 「商机线索」「爬虫」「触达」「渠道」「账号」「脱敏」「漏斗」等术语跨文档完全统一 |

### 3.4 交付物核对清单

合入 `main` 前确认本次任务新增/修改的关键交付物已在 commit 中：

- ✅ 对应 `tests/test_t##_*.py` 单元测试文件
- ✅ README.md 中相应章节已更新（若涉及新能力/新模块/新路径）
- ✅ DEVELOP_RULES.md 中相应章节已更新（若涉及新规范/新约束）
- ✅ 若涉及新配置项，`.env.example` 已同步
- ✅ 若涉及新模块/新能力，本 TASK_LIST 已追加任务行（或更新状态）

---

## 四、优先级定义

| 优先级 | 含义 | 典型任务 |
|-------|------|---------|
| **P0** | 阻塞性基础能力，没有就无法构建完整链路 | 项目骨架、配置、日志/异常/告警、数据库 ORM、爬虫 SDK、数据合规、OpenClaw 网关 |
| **P1** | 核心业务能力，没有就无法交付价值 | 去重合并打分、消息风控底座、爬虫业务、清洗流水线、多渠道触达、销售调度、Web 管理后台、文档校对 |
| **P2** | 增强能力，可延后迭代 | 高级 BI 可视化、多租户隔离、A/B 测试框架、国际化等 |

---

## 五、状态图例

| 图标 | 含义 |
|------|------|
| ✅ 完成 | 已在当前分支提交并通过验收 |
| 🟡 进行中 | 正在开发或联调中 |
| 🔴 未开始 | 排期内但尚未启动 |

---

*最后更新：docs(T15) 同步至 T01-T14 全部任务最新实现。*
