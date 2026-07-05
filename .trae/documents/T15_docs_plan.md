# T15：全量文档校对完善计划

> 任务类型：纯文档工作，仅修改 `README.md` / `DEVELOP_RULES.md` / `docs/TASK_LIST.md`
> 前置任务：T01-T14 全部代码已提交并推送到 origin/main

---

## 一、现状调研结论

### 1.1 三份文档现状

| 文档 | 状态 | 主要问题 |
|------|------|----------|
| `README.md` | 存在（53 行，偏简陋） | 目录树描述与实际代码不一致；缺少架构图；缺少启动命令；TASK_LIST 路径错误；无 FAQ；无 web_admin 说明；无 OpenClaw 对接详细步骤；项目名与实际目录名不一致 |
| `DEVELOP_RULES.md` | 存在（40 行，8 大章节框架） | 缺少接口返回结构示例；缺少跨层调用矩阵；缺少数据库模型命名规范；缺少 Git feat(T##) 提交格式；缺少测试覆盖率要求；缺少配置管理细则；缺少联调验收标准 |
| `docs/TASK_LIST.md` | **不存在** | 需要从零新建，汇总 T01-T14 全部任务 |

### 1.2 实际代码四层架构与模块清单

```
BizTools4Openclaw/
├── infra/                    # Layer1 基础基建层
│   ├── logger_setup.py       # 统一日志配置（多文件 + 控制台 + 等级过滤）
│   ├── exceptions.py         # 全局异常类型定义
│   ├── exception_handler.py  # FastAPI 全局异常处理中间件
│   ├── alerting.py           # 告警推送（钉钉/飞书/Webhook 可扩展）
│   ├── response.py           # 统一响应包装器 {code, msg, data, timestamp}
│   ├── redis_client.py       # Redis 客户端封装（连接池 + 断线重连）
│   ├── task_queue.py         # 异步任务队列（Redis List 实现）
│   ├── task_scheduler.py     # APScheduler 定时调度（Cron/Interval/Date）
│   ├── task_states.py        # 任务状态定义与持久化
│   ├── task_exceptions.py    # 任务专属异常类型
│   ├── db_base.py            # SQLAlchemy Base + 连接管理
│   └── db_models.py          # 核心 ORM 数据模型（Lead/Channel/Task/Log 等）
├── core/                     # Layer2 通用能力层
│   ├── spider_core/          # 爬虫核心SDK（T05）
│   │   ├── sdk.py            # Playwright 封装 + 统一爬取接口
│   │   ├── proxy_pool.py     # 代理池管理
│   │   ├── ua_pool.py        # User-Agent 池
│   │   ├── rate_limiter.py   # 爬虫速率限制
│   │   ├── risk_controller.py# 风控降级策略
│   │   ├── robots_checker.py # robots.txt 校验
│   │   ├── checkpoint_manager.py  # 断点续爬
│   │   └── exceptions.py     # 爬虫异常类型
│   ├── data_core/            # 数据处理核心（T07）
│   │   ├── dedupe_engine.py  # 去重引擎
│   │   ├── merge_engine.py   # 合并引擎
│   │   ├── scoring_engine.py # 商机打分分级
│   │   ├── blacklist_filter.py # 黑名单过滤
│   │   └── pipeline.py       # 数据处理流水线
│   ├── send_core/            # 消息触达核心（T08）
│   │   ├── account_pool.py   # 多账号池负载均衡
│   │   ├── rate_limiter.py   # 发送频率限制
│   │   ├── content_risk.py   # 内容风控（敏感词检测）
│   │   ├── ban_detector.py   # 封禁检测
│   │   ├── failure_retry.py  # 失败自动重试
│   │   ├── send_pipeline.py  # 发送流水线
│   │   └── task_status.py    # 发送任务状态
│   └── compliance/           # 合规管控（T04 + T06）
│       ├── pii_mask.py       # 隐私字段掩码
│       ├── privacy_stripper.py  # 隐私信息剥离
│       ├── sensitive_crypto.py  # 敏感字段加密
│       ├── sensitive_filter.py  # 敏感词检测
│       ├── compliance_checker.py # 合规检查器
│       ├── archive_mixin.py  # 数据归档
│       └── data_lifecycle.py # 数据生命周期管理
├── business/                 # Layer3 业务模块层
│   ├── multi_spider/         # 全源爬虫业务（T09）
│   │   ├── base.py           # 爬虫基类
│   │   ├── models.py         # 爬虫业务模型
│   │   ├── pipeline.py       # 爬虫流水线
│   │   ├── registry.py       # 爬虫任务注册表
│   │   └── sources/          # 6 个具体数据源
│   │       ├── generic_web.py       # 通用网页
│   │       ├── douyin_xhs.py        # 抖音/小红书
│   │       ├── enterprise_news.py   # 企业动态/行业资讯
│   │       ├── local_classifieds.py # 本地分类信息/供需平台
│   │       ├── zhihu_baiduqa.py     # 知乎/百度知道问答
│   │       └── bid_and_gov.py       # 招投标/政府采购
│   ├── data_clean/           # 数据清洗结构化（T10）
│   │   ├── normalizer.py     # 字段标准化
│   │   ├── extractor.py      # 实体抽取（公司/联系人/电话/邮箱）
│   │   ├── filters.py        # 无效数据过滤
│   │   ├── compliance_step.py # 合规检查步骤
│   │   ├── engine_step.py    # 去重合并打分步骤
│   │   ├── pipeline.py       # 清洗流水线
│   │   ├── loader.py         # 数据加载
│   │   ├── storage.py        # 结构化数据存储
│   │   ├── models.py         # 清洗业务模型
│   │   ├── _orm.py           # ORM 辅助
│   │   └── registry.py       # 清洗任务注册
│   ├── customer_send/        # 多渠道触达（T11）
│   │   ├── pipeline.py       # 触达流水线
│   │   ├── registry.py       # 渠道注册表
│   │   ├── storage.py        # 发送记录存储
│   │   ├── models.py         # 触达业务模型
│   │   ├── template_engine.py # 消息模板引擎
│   │   ├── _orm.py           # ORM 辅助
│   │   └── channels/         # 4 个具体渠道
│   │       ├── email_channel.py   # 邮件（SMTP）
│   │       ├── feishu_channel.py  # 飞书机器人/应用
│   │       ├── wechat_channel.py  # 微信/企业微信
│   │       └── h5_landing.py      # H5 落地页链接生成
│   └── sales_task/           # 销售调度与跟进闭环（T12）
│       ├── assignment_engine.py   # 商机自动分配
│       ├── funnel_engine.py       # 转化漏斗统计
│       ├── status_engine.py        # 商机状态流转
│       ├── reminder_engine.py      # 定时跟进提醒
│       ├── push_notifier.py        # 推送通知器
│       ├── pipeline.py             # 销售流水线
│       ├── storage.py              # 销售数据存储
│       ├── models.py               # 销售业务模型
│       ├── _orm.py                 # ORM 辅助
│       └── registry.py             # 销售任务注册
├── adapter/                  # Layer4 OpenClaw 适配网关（T13）
│   ├── main.py               # FastAPI 入口（统一挂载 web_admin）
│   ├── auth.py               # OpenClaw 认证
│   ├── middleware.py         # 网关中间件（trace_id / 日志 / 限流）
│   ├── models.py             # 网关请求/响应模型
│   ├── response.py           # 网关响应包装
│   ├── schema_adapter.py     # 参数 Schema 适配
│   ├── tool_registry.py      # 工具注册表（OpenClaw Tool 规范）
│   ├── tools_router.py       # 工具 API 路由
│   ├── task_router.py        # 任务状态/回调路由
│   └── __init__.py
├── web_admin/                # Layer4 可视化管理后台（T14）
│   ├── main.py               # web_admin 挂载器（挂载到 adapter/main）
│   ├── auth.py               # 后台登录 + Cookie 会话 + Redis
│   ├── middleware.py         # 行为审计中间件（高危操作告警）
│   ├── menu.py               # 左侧菜单定义
│   ├── pages.py              # HTML 页面路由（纯字符串模板，无模板引擎）
│   ├── api/                  # 6 个后台 API 模块
│   │   ├── dashboard.py      # 数据看板（抓取/线索/触达/漏斗）
│   │   ├── spider_task.py    # 爬虫任务管理
│   │   ├── lead_mgmt.py      # 商机线索管理 + 人工复核
│   │   ├── channel_account.py # 渠道账号配置
│   │   ├── sales_mgmt.py     # 销售管理 + 逾期告警
│   │   └── audit_log.py      # 操作审计日志
│   ├── static/
│   │   ├── css/admin.css     # 后台样式
│   │   └── js/admin.js       # 前端交互（表格渲染/脱敏/菜单激活）
│   └── templates/            # HTML 模板片段
│       ├── login.html
│       └── partials/         # dashboard/spider/leads/channels/sales/audit
├── configs/                  # 多环境配置
│   ├── settings.py           # 全局 Settings（含 WebAdminSettings）
│   ├── __init__.py
│   └── templates/            # 消息模板
│       ├── email_default.html
│       ├── feishu_card.json
│       └── wechat_card.json
├── docker/                   # 容器部署（目录已建立）
├── docs/                     # 项目文档
│   └── T02_INFRA_USAGE.md    # T02 基础设施使用说明
├── examples/                 # OpenClaw 调用示例
│   └── openclaw_skills_demo.yaml  # OpenClaw Skill 注册示例
├── tests/                    # 单元测试（14 份 + conftest）
│   ├── test_t02_infra.py ~ test_t14_web_admin.py
│   └── conftest.py
├── .github/                  # GitHub 配置（目录已建立）
├── README.md
├── DEVELOP_RULES.md
└── requirements.txt / .env.example
```

### 1.3 文档与代码不一致项（需要修正的清单）

| 位置 | 文档描述 | 实际代码 | 修正方式 |
|------|---------|---------|---------|
| README 项目名 | `openclaw-business-tools/` | 实际目录 `BizTools4Openclaw` | 统一为仓库目录名 |
| README 目录树 | `web_admin/` 缩进位置错误 | `web_admin` 与 `adapter` 同级，属 Layer4 | 修正树结构 |
| README 文档链接 | `TASK_LIST.md`（根目录） | 实际在 `docs/TASK_LIST.md` | 修正链接路径 |
| README 技术栈 | "Docker Compose 一键部署" | docker/ 目录存在但暂无 docker-compose.yml | 改为 "Docker Compose 容器编排支持（配置文件参考 docs/ 目录）" |
| README 快速接入 | 仅有 5 个文字步骤，无实际命令 | 需要 `pip install -r requirements.txt`、`python -m adapter.main` 等 | 补充完整命令行步骤 |
| README 商机来源 | 描述泛泛 | 实际 6 个数据源 + 4 个触达渠道 | 列出完整清单 |
| README 模块说明 | 无 web_admin 描述 | T14 已完整实现 | 补充后台管理说明 |
| DEVELOP_RULES Git 规范 | 无 feat(T##) 格式 | 实际提交均为 `feat(T##): xxx` | 补充任务编号格式 |
| DEVELOP_RULES 测试规范 | 仅有"必须编写单元测试" | 实际每个任务均有 `test_t##_*.py` | 补充测试文件命名规范 |

### 1.4 术语统一需求

| 旧术语/不统一 | 统一为 | 出现文档 |
|--------------|--------|---------|
| 智能体 / Agent | OpenClaw 智能体 | README |
| 工具集 / 工具 / API | 工具（Tool） | README/DEVELOP_RULES |
| 触达 / 推送 / 发送 | 触达（send） | README/DEVELOP_RULES |
| 商机 / 线索 / Lead | 商机线索（Lead） | README/TASK_LIST |
| 账号 / 账户 | 账号（account） | 全文 |
| 爬虫 / 抓取 / 采集 | 爬虫（spider/crawl） | 全文 |
| Web管理后台 / 管理后台 / 可视化后台 | Web 管理后台（web_admin） | README/TASK_LIST |
| 四层分层 / 4层架构 / 分层架构 | 四层分层架构 | README/DEVELOP_RULES |

---

## 二、三份文档修改完善清单

### 2.1 README.md — 修改清单（预计 ~300+ 行）

#### 章节 1：项目标题与简介（重写）
- 将项目标题统一为 `BizTools4Openclaw`（与实际仓库目录一致）
- 重写 3 行简介，覆盖：业务目标、四层架构概览、OpenClaw 对接定位

#### 章节 2：✨ 项目核心能力（扩展）
- 从原有 6 点扩展为 8 点
- 补充"Web 管理后台可视化运维"能力点（T14 新增）
- 补充"OpenClaw 标准工具注册与调度"能力点（T13 新增）

#### 章节 3：📐 整体架构（新增 + 重写）
- 新增"四层分层架构总览"：Layer1 基础基建 → Layer2 通用能力 → Layer3 业务模块 → Layer4 接入展示
- 新增 mermaid 风格文字架构图（ASCII 版本）
- 新增"各层职责与调用方向"说明（明确禁止跨层直接调用）

#### 章节 4：🛠 完整技术栈说明（扩展）
- 后端：FastAPI + Pydantic v2 + Python 3.10+
- 爬虫：Playwright + 代理池 + UA 池 + 风控降级
- 任务调度：APScheduler + Redis List 异步队列
- 数据存储：SQLAlchemy 2.0 + SQLite（默认）/ MySQL（可选）
- 缓存/会话：Redis + 连接池
- 消息触达：邮件 SMTP / 飞书 Webhook / 企业微信 / H5 链接
- 前端：纯 HTML + CSS + 原生 JS（无 npm 依赖）
- 测试：pytest + 单元测试覆盖率（按任务拆分）
- 日志：多文件轮转 + 结构化 JSON 日志
- 告警：可扩展告警通道（钉钉/飞书/Webhook）

#### 章节 5：📦 完整目录树结构（重写）
- 基于 1.2 节实际目录结构输出完整树
- 每个一级目录标注所属分层（L1/L2/L3/L4）
- 每个关键 .py 文件简要说明职责

#### 章节 6：🔌 全渠道商机来源清单（新增）
- 列出 6 个爬虫数据源及其典型场景
- 列出 4 个触达渠道及其能力说明

#### 章节 7：🚀 快速开始 — 环境部署与启动流程（重写）
- 7.1 前置条件：Python 3.10+ / Redis 5.0+ / Git
- 7.2 依赖安装：`pip install -r requirements.txt`
- 7.3 配置：`.env` 环境变量说明（列出关键配置项）
- 7.4 启动服务：`python -m adapter.main`
- 7.5 验证访问：
  - OpenClaw 网关 API：`http://localhost:8000/docs`
  - Web 管理后台：`http://localhost:8000/admin`
  - 健康检查：`GET http://localhost:8000/health`

#### 章节 8：🔗 OpenClaw 对接完整步骤（新增）
- 8.1 在 OpenClaw 平台注册自定义工具（Skill）
- 8.2 使用 `examples/openclaw_skills_demo.yaml` 作为模板
- 8.3 配置工具 API Base URL（指向 `adapter/main.py` 的 FastAPI 服务）
- 8.4 配置认证 Token（参考 `adapter/auth.py`）
- 8.5 测试调用：获取任务列表 / 触发爬虫 / 查询商机
- 8.6 异步任务回调流程说明

#### 章节 9：📊 各模块能力说明（扩展）
- 按 L1-L4 分层简述每个模块的入口文件、核心类、典型用法
- 特别标注 web_admin 的 6 个管理功能模块

#### 章节 10：🧪 运行单元测试（新增）
- `pytest tests/ -v`
- `pytest tests/test_t14_web_admin.py -v`（单任务测试示例）
- 测试文件命名规范：`test_t##_<module>.py`

#### 章节 11：📝 开发规范与贡献指南（链接到 DEVELOP_RULES.md）
- 简要引用 DEVELOP_RULES.md
- Git 分支与 PR 流程简述

#### 章节 12：❓ 常见问题 FAQ（新增）
- Q1: Redis 未启动如何处理？→ 降级为内存缓存（部分功能受限）
- Q2: 爬虫被风控封禁如何排查？→ 查看 web_admin 爬虫日志 + 风控异常记录
- Q3: 如何新增自定义数据源？→ 继承 `business/multi_spider/base.py` BaseSpider
- Q4: 如何新增自定义触达渠道？→ 继承 `business/customer_send/channels/__init__.py` 注册接口
- Q5: 管理后台账号如何修改？→ 通过 `.env` 配置 `WEB_ADMIN_USERNAME` / `WEB_ADMIN_PASSWORD_PLAIN`
- Q6: 数据如何备份？→ SQLite 文件直接备份 / MySQL 使用 mysqldump

#### 章节 13：📚 项目文档索引（重写）
- 开发规范：`DEVELOP_RULES.md`
- 任务清单：`docs/TASK_LIST.md`
- 基础设施使用：`docs/T02_INFRA_USAGE.md`
- OpenClaw Skill 示例：`examples/openclaw_skills_demo.yaml`

#### 章节 14：开源协议（保留 + 补充免责声明）

---

### 2.2 DEVELOP_RULES.md — 修改清单（预计 ~150+ 行）

#### 章节 1：架构规范（扩展）
- **1.1 四层分层定义**：明确 L1/L2/L3/L4 各层范围与职责
- **1.2 跨层调用矩阵（允许/禁止）**：
  - ✅ L4 → L3（业务模块）、L4 → L2（通用能力）、L4 → L1（基础基建）
  - ✅ L3 → L2、L3 → L1
  - ✅ L2 → L1
  - ❌ L1 → L2/L3/L4（基础层不反向依赖）
  - ❌ L2 → L3（通用能力不依赖业务模块）
  - ❌ 同层模块间直接调用私有方法（应通过公共 API / Registry）
- **1.3 模块可插拔要求**：每个 business 子模块必须有 `registry.py` 提供统一注册入口
- **1.4 统一网关暴露**：所有对外 API 必须通过 `adapter/main.py` FastAPI 挂载，禁止直接在业务模块内启动独立服务

#### 章节 2：代码规范（扩展）
- **2.1 Python 编码**：严格 PEP8 / lint by pyright
- **2.2 命名约定**：类名大驼峰 `ClassName` / 函数变量小蛇形 `function_name` / 常量全大写 `CONSTANT_NAME`
- **2.3 模块命名**：模块级功能统一使用 `_name.py`（下划线前缀表示内部实现），如 `_orm.py`
- **2.4 注释与 docstring**：
  - 公共类/函数必须有 Google 风格 docstring
  - 包含 Args / Returns / Raises / Example
  - 复杂算法逻辑需添加行内注释
- **2.5 配置管理**：
  - 禁止硬编码（no magic numbers / strings）
  - 统一放入 `configs/settings.py`（Pydantic Settings 模型）
  - 环境变量通过 `.env` 文件注入，不提交到仓库
- **2.6 异常处理**：所有对外 API 必须使用 `infra/exception_handler.py` 统一捕获；内部抛出 `infra/exceptions.py` 中定义的业务异常

#### 章节 3：接口规范（扩展）
- **3.1 统一响应格式**（附 JSON 示例）：
  ```json
  {
    "code": 0,
    "msg": "success",
    "data": { "key": "value" },
    "timestamp": 1234567890
  }
  ```
- **3.2 HTTP 状态码约定**：
  - 200 OK / 201 Created / 202 Accepted（异步）
  - 400 参数错误 / 401 未认证 / 403 无权限 / 404 资源不存在
  - 500 服务端异常（已由全局异常处理器捕获）
- **3.3 OpenClaw 调用适配**：轻量化入参、标准 JSON 出参、异步任务支持状态轮询与取消
- **3.4 参数校验**：所有入参通过 Pydantic Model 校验；敏感参数做日志脱敏

#### 章节 4：数据规范（扩展）
- **4.1 数据库模型设计规范**：
  - 所有模型继承 `infra/db_base.py: Base`
  - 主键统一 `id: Integer/BigInteger`，创建时间 `created_at`，更新时间 `updated_at`
  - 枚举类型使用 `sqlalchemy.Enum` + Python Enum 类
  - 敏感字段（手机号/邮箱/密钥）必须使用 `core/compliance/sensitive_crypto.py` 加密
- **4.2 数据分层存储**：原始抓取 / 结构化 / 业务数据分离，不混表
- **4.3 操作留痕**：所有写操作记录日志，高危删除操作触发 `infra/alerting.py` 告警
- **4.4 数据生命周期**：冷数据通过 `core/compliance/archive_mixin.py` 自动归档

#### 章节 5：爬虫合规规范（扩展）
- **5.1 robots.txt 校验**：`core/spider_core/robots_checker.py` 自动检查并遵守
- **5.2 速率限制**：随机间隔 + 代理轮换，禁止高频暴力抓取
- **5.3 User-Agent 规范**：明确标识爬虫身份，不伪装浏览器
- **5.4 隐私过滤**：`core/compliance/privacy_stripper.py` 自动剥离非必要隐私信息
- **5.5 风控降级**：检测到平台风控时自动降速/暂停/告警

#### 章节 6：消息触达规范（扩展）
- **6.1 平台规则遵守**：严格遵守各平台（邮件/飞书/微信）发送频率限制
- **6.2 敏感词检测**：`core/send_core/content_risk.py` 发送前必检
- **6.3 多账号负载均衡**：`core/send_core/account_pool.py` 自动轮转，避免单账号超限
- **6.4 失败自动重试**：`core/send_core/failure_retry.py` 指数退避重试

#### 章节 7：Git 提交规范（重写 + 扩展）
- **7.1 分支规范**：
  - `main`（生产/主分支，受保护）
  - `dev`（开发集成分支）
  - `feature/T##_xxx`（功能分支，T## 为任务编号）
  - `fix/T##_xxx` / `fix/issue-xxx`（修复分支）
- **7.2 提交消息格式**（强制执行）：
  - 格式：`feat(T##): 功能简要说明` / `fix(T##): 修复简要说明`
  - 其他类型：`docs(T##):` / `refactor(T##):` / `test(T##):` / `chore:`
  - 消息使用中文，简明描述本次变更内容
  - 禁止无意义提交（如 "fix", "update"）
- **7.3 禁止直接推送 main**：必须通过 PR/Merge Request，review 后合并
- **7.4 单次提交粒度**：一个功能/修复一次提交，不掺杂无关变更

#### 章节 8：测试与交付规范（扩展）
- **8.1 单元测试要求**：
  - 每个任务（T##）必须对应 `tests/test_t##_<module>.py`
  - 核心类/函数必须覆盖正常路径 + 异常路径
  - `tests/conftest.py` 提供统一 fixture
- **8.2 运行命令**：`pytest tests/ -v --tb=short`
- **8.3 联调验收**：
  - 单任务完成：独立测试通过
  - 全链路联调：爬虫 → 清洗 → 触达 → 销售跟进全流程验证
  - 接口回归：`GET /docs` Swagger 全接口可调用
- **8.4 文档同步更新**：每次提交涉及功能变更必须同步更新对应文档章节

---

### 2.3 docs/TASK_LIST.md — 新建清单（预计 ~120+ 行）

#### 文档结构
- 标题：任务清单与完成进度总览
- 说明：本清单汇总 T01-T14 全部开发任务，含分层归属、优先级、完成标准、交付物、依赖关系

#### 章节 1：任务总览表（核心表格）
| 任务编号 | 任务名称 | 所属分层 | 依赖任务 | 优先级 | 状态 | Git Commit | 交付物 | 完成标准 |
|---------|---------|---------|---------|-------|------|-----------|--------|---------|
| T01 | 项目骨架与基础配置搭建 | L1 基建 | — | P0 | ✅ 完成 | `feat(T01): ...` | configs/settings.py, requirements.txt, .env.example | 项目可 import，配置可加载 |
| T02 | 全局日志/异常/告警基建 | L1 基建 | T01 | P0 | ✅ 完成 | `feat(T02): ...` | infra/logger_setup.py, infra/exceptions.py, infra/alerting.py | 日志可写入文件，异常可统一捕获，告警可推送 |
| T03 | Redis 异步任务队列与定时调度 | L1 基建 | T01, T02 | P0 | ✅ 完成 | `feat(T03): ...` | infra/task_queue.py, infra/task_scheduler.py | 可提交异步任务并执行，Cron 定时可触发 |
| T04 | 数据库分层架构与 ORM | L1 基建 | T01 | P0 | ✅ 完成 | `feat(T04): ...` | infra/db_base.py, infra/db_models.py | SQLAlchemy 模型可建表可 CRUD |
| T05 | 爬虫核心通用 SDK | L2 通用 | T02, T03 | P0 | ✅ 完成 | `feat(T05): ...` | core/spider_core/* | Playwright 可抓取，代理/UA/限流生效 |
| T06 | 数据合规/脱敏/敏感词检测 | L2 通用 | T02, T04 | P0 | ✅ 完成 | `feat(T06): ...` | core/compliance/* | 手机号/邮箱自动脱敏，敏感词可检测 |
| T07 | 商机去重合并打分分级 | L2 通用 | T04, T06 | P1 | ✅ 完成 | `feat(T07): ...` | core/data_core/* | 重复商机可合并，分数分级可输出 |
| T08 | 多渠道消息风控核心底座 | L2 通用 | T02, T06 | P1 | ✅ 完成 | `feat(T08): ...` | core/send_core/* | 账号池/限流/风控/重试全部就绪 |
| T09 | 全网多源爬虫业务模块 | L3 业务 | T05, T06 | P0 | ✅ 完成 | `feat(T09): ...` | business/multi_spider/* | 6 个数据源均可独立爬取 |
| T10 | 数据清洗实体抽取流水线 | L3 业务 | T06, T07 | P1 | ✅ 完成 | `feat(T10): ...` | business/data_clean/* | 抓取原始数据可转结构化 Lead |
| T11 | 多渠道自动化商机触达 | L3 业务 | T08 | P1 | ✅ 完成 | `feat(T11): ...` | business/customer_send/* | 4 个渠道均可发送消息 |
| T12 | 销售商机调度与跟进闭环 | L3 业务 | T10, T11 | P1 | ✅ 完成 | `feat(T12): ...` | business/sales_task/* | 商机自动分配 + 状态流转 + 漏斗统计 |
| T13 | OpenClaw 网关与工具注册 | L4 接入 | T02, T09, T11 | P0 | ✅ 完成 | `feat(T13): ...` | adapter/* | FastAPI 可启动，Swagger 可浏览 |
| T14 | 轻量 Web 管理后台 | L4 接入 | T02, T13 | P1 | ✅ 完成 | `feat(T14): ...` | web_admin/* | 登录 + 6 大管理功能全部可用 |

#### 章节 2：分层架构与依赖关系可视化
- 分层图（ASCII）：展示 L1 → L2 → L3 → L4 流向
- 关键依赖链：
  - 爬虫链：T01 → T02/T03 → T05 → T06 → T09
  - 数据链：T01 → T04 → T06 → T07 → T10
  - 触达链：T01 → T02/T03 → T06 → T08 → T11
  - 销售链：T10/T11 → T12
  - 接入层：T02 + T09/T11 → T13 → T14

#### 章节 3：Git 提交与验收核对要点
- **提交规范核对清单**：feat(T##) 格式 / 单次提交对应单次功能 / 不掺杂无关变更
- **测试验收核对清单**：对应 `tests/test_t##_*.py` 全部通过 / 不引入新的失败用例
- **文档同步核对清单**：README 功能描述与实现一致 / DEVELOP_RULES 新增规范不冲突
- **代码质量核对清单**：无硬编码 / 配置在 settings.py / 异常被捕获 / 敏感字段脱敏

---

## 三、统一术语修正对照表

见 1.4 节「术语统一需求」表格，三份文档内所有出现的旧术语统一替换为标准术语。

---

## 四、分步校对、修改、自检流程

### 阶段 1：校对（不变更文件，只做调研记录）
- 步骤 1.1：对照实际代码结构检查 README 目录树，列出所有不一致项（见 1.3 表）
- 步骤 1.2：搜索三份文档中所有旧术语（见 1.4 表），记录出现位置
- 步骤 1.3：检查文档中所有文件路径 / API 路径是否存在于代码中

### 阶段 2：修改 README.md
- 步骤 2.1：重写标题与简介
- 步骤 2.2：扩展核心能力列表（8 点）
- 步骤 2.3：新增架构总览 + ASCII 架构图
- 步骤 2.4：扩展技术栈说明（10 大类）
- 步骤 2.5：重写完整目录树（基于实际代码）
- 步骤 2.6：新增全渠道商机来源清单
- 步骤 2.7：重写快速开始章节（含完整命令）
- 步骤 2.8：新增 OpenClaw 对接完整步骤
- 步骤 2.9：扩展各模块能力说明
- 步骤 2.10：新增单元测试章节
- 步骤 2.11：新增开发规范引用章节
- 步骤 2.12：新增 FAQ 章节
- 步骤 2.13：重写文档索引章节（修正 TASK_LIST 路径）
- 步骤 2.14：保留开源协议并补充免责声明

### 阶段 3：修改 DEVELOP_RULES.md
- 步骤 3.1：扩展架构规范（新增跨层调用矩阵 + 可插拔定义）
- 步骤 3.2：扩展代码规范（新增命名约定 + 注释规范 + 配置管理细则）
- 步骤 3.3：扩展接口规范（新增统一响应 JSON 示例 + 状态码约定表）
- 步骤 3.4：扩展数据规范（新增数据库模型设计规范）
- 步骤 3.5：扩展爬虫合规规范（补充 robots/UA/隐私具体要求）
- 步骤 3.6：扩展消息触达规范（补充敏感词检测 + 多账号负载具体实现）
- 步骤 3.7：重写 Git 提交规范（强制 feat(T##) 格式 + 分支命名规则）
- 步骤 3.8：扩展测试与交付规范（测试文件命名 + 联调验收标准）

### 阶段 4：新建 docs/TASK_LIST.md
- 步骤 4.1：编写文档标题与说明
- 步骤 4.2：编写 14 行任务总览表（填充每行 9 列信息）
- 步骤 4.3：编写分层依赖关系可视化章节
- 步骤 4.4：编写 Git 提交与验收核对要点章节

### 阶段 5：全局术语统一
- 步骤 5.1：README 全文术语统一替换
- 步骤 5.2：DEVELOP_RULES 全文术语统一替换
- 步骤 5.3：docs/TASK_LIST 全文术语统一（新建时即使用标准术语）

### 阶段 6：自检与验证
- 步骤 6.1：三份文档互相引用的路径全部正确（README → DEVELOP_RULES.md → docs/TASK_LIST.md → docs/T02_INFRA_USAGE.md → examples/*.yaml）
- 步骤 6.2：README 中提到的所有 Python 文件 / 目录在代码库中实际存在
- 步骤 6.3：README 中提到的所有 URL / API 端点在 `adapter/main.py` 中实际存在
- 步骤 6.4：README 中提到的所有命令可在本地成功执行（自测）
- 步骤 6.5：三份文档术语一致，无前后矛盾
- 步骤 6.6：检查无代码/配置文件被意外修改（git diff 仅限三份 md 文件）

### 阶段 7：提交
- 步骤 7.1：git add README.md DEVELOP_RULES.md docs/TASK_LIST.md
- 步骤 7.2：git commit -m "docs(T15): 全量校对三份核心文档，同步架构与任务最新状态"
- 步骤 7.3：git push origin main

---

## 五、风险与边界

| 风险点 | 影响 | 规避措施 |
|-------|------|---------|
| 文档与代码不同步（后续新增功能未更新文档） | 用户根据过时文档操作失败 | T15 任务中在 DEVELOP_RULES.md 明确规定"每次功能提交必须同步更新对应文档" |
| 路径引用错误 | 读者点击链接 404 | 阶段 6.1 逐条核对所有路径 |
| 命令示例与实际环境不一致 | Windows/Linux 命令差异 | 统一使用跨平台命令，必要时添加注释说明差异 |
| docs/TASK_LIST.md 新建后忘记在 README 中链接 | 读者无法找到 | README 章节 13 明确添加链接 |
| 误修改代码文件 | 违反任务约束 | 使用 `git status --short` 自检，确认变更仅包含 3 个 .md 文件 |
