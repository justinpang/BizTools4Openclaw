# T17：全项目端到端集成回归测试 · 全链路闭环验证 · 缺陷统一修复闭环

> 文档版本：T17-v1.0  
> 适用版本：BizTools4Openclaw (T01-T16 全部完成)  
> 计划阶段：T17  
> 运行环境：Windows 10/11 / Docker Desktop / PostgreSQL 16 / Redis 7.2  
> 测试用例总数：~180 条（分层模块 + 端到端 + 异常专项 + 部署验证）  
> 目标：测试通过率 100%，无 P0/P1 缺陷，文档与代码完全一致

---

## 一、现状调研结论

### 1.1 测试结构（tests/ 目录）

| 测试文件 | 任务 | 用例数 | 覆盖模块 |
|---------|-----|-------|---------|
| `test_t02_infra.py` | T02 | 11 | configs/settings, infra/response, infra/exceptions, infra/alerting, infra/logger_setup, infra/exception_handler |
| `test_t03_infra.py` | T03 | 13 | infra/redis_client, infra/task_queue, infra/task_states, infra/task_exceptions, infra/task_scheduler |
| `test_t04_infra.py` | T04 | 10 | infra/db_base, infra/db_models, core/compliance/sensitive_crypto |
| `test_t05_infra.py` | T05 | 17 | core/spider_core/* (UA, Proxy, RateLimiter, Robots, Checkpoint, Risk, SpiderSDK) |
| `test_t06_infra.py` | T06 | 30 | core/compliance/* (pii_mask, privacy_stripper, sensitive_filter, compliance_checker, archive_mixin, data_lifecycle) |
| `test_t07_infra.py` | T07 | 14 | core/data_core/* (blacklist_filter, dedupe_engine, merge_engine, scoring_engine, pipeline) |
| `test_t08_infra.py` | T08 | 16 | core/send_core/* (account_pool, rate_limiter, content_risk, ban_detector, failure_retry, send_pipeline, task_status) |
| `test_t09_multi_spider.py` | T09 | 29 | business/multi_spider/* (base, models, pipeline, registry, sources/*) |
| `test_t10_cleaning.py` | T10 | 15 | business/data_clean/* (filters, extractor, normalizer, storage, pipeline, registry, engine_step, compliance_step) |
| `test_t11_customer_send.py` | T11 | 13 | business/customer_send/* (template_engine, channels/email, channels/wechat, channels/feishu, channels/h5_landing, pipeline, storage, registry) |
| `test_t12_sales_task.py` | T12 | 24 | business/sales_task/* (assignment_engine, reminder_engine, status_engine, funnel_engine, push_notifier, pipeline, storage, registry, models) |
| `test_t13_openclaw_adapter.py` | T13 | 10 | adapter/main, adapter/models, adapter/auth, adapter/tool_registry, adapter/schema_adapter |
| `test_t14_web_admin.py` | T14 | 11 | web_admin/main, web_admin/auth, web_admin/pages, web_admin/menu, web_admin/middleware, web_admin/api/* |
| **合计** | T02-T14 | **221** | |

### 1.2 基线测试结果

```
221 passed, 89 warnings in 60.90s
```

全部通过，但存在 **89 个 deprecation warnings**，集中在：

1. `datetime.datetime.utcnow()` — 被 Python 3.12 废弃（影响 business/multi_spider/models.py:51, base.py:147/172, data_clean/models.py:109/143/166, customer_send/template_engine.py:82, pipeline.py:123/325, adapter/models.py:34, tests/test_t09_multi_spider.py:168）
2. `redis.setex()` → 推荐使用 `redis.set()` + `ex` 参数（影响 web_admin/auth.py:115）
3. `fastapi.testclient` 中的 StarletteDeprecationWarning（仅影响测试）

### 1.3 关键文件与代码结构

| 层 | 文件/目录 | 关键能力 |
|---|---------|---------|
| **入口** | `python -m adapter.main` | FastAPI 应用 + web_admin 路由挂载 |
| **infra/** (L1) | 13 个文件 | 日志 / 告警 / 响应 / Redis / 任务队列 / 调度器 / 数据库 ORM |
| **core/spider_core/** | SDK + Proxy + UA + RateLimiter + Robots + Risk + Checkpoint | 爬虫底层 |
| **core/compliance/** | PII Mask / SensitiveCrypto / PrivacyStripper / Filter / Checker / ArchiveMixin / Lifecycle | 合规/脱敏/加密 |
| **core/data_core/** | Blacklist + Dedupe + Merge + Score | 商机去重/合并/评分 |
| **core/send_core/** | AccountPool + RateLimiter + ContentRisk + BanDetector + FailureRetry + SendPipeline | 多渠道消息风控 |
| **business/multi_spider/** | BaseSpider + 16 种渠道源 + 注册中心 + 流水线 | 全源爬虫业务 |
| **business/data_clean/** | Normalizer + Extractor + Filters + Pipeline + Storage + Registry | 清洗/结构化/评分 |
| **business/customer_send/** | TemplateEngine + 4 渠道 + Pipeline + Storage | 多渠道触达 |
| **business/sales_task/** | Assignment + Reminder + Status + Funnel + PushNotifier | 销售调度闭环 |
| **adapter/** | FastAPI + Tool Registry + Schema Adapter + Webhook | OpenClaw 网关 |
| **web_admin/** | Pages + Auth + Menu + Middleware + 6 APIs + Static | 可视化管理后台 |

### 1.4 部署方式

- **本地直启**：`python -m adapter.main` → http://localhost:8000
- **Windows一键**：`.\start_win.ps1`（交互式 / docker-prod / docker-dev / local）
- **Docker**：`docker compose --profile prod up -d` (PostgreSQL + Redis + App)
- **Dockerfile**：三阶段分层构建（builder-base → builder-deps → final）
- **init_db.sql**：4 表 + pgvector 扩展 + 索引

### 1.5 潜在问题（已识别）

1. **`datetime.utcnow()` 弃用警告**（80+ warnings）— 需在 T17 中统一替换为 `datetime.now(timezone.utc)`
2. **Redis 未启动时降级** — 已实现但测试未覆盖降级路径
3. **Web 管理后台 API 未登录访问** — 已有 basic 测试，但缺少细粒度权限测试
4. **环境变量敏感信息** — `DB_ENCRYPTION_KEY` / `WEB_ADMIN_PASSWORD_PLAIN` 需验证是否在日志中泄露
5. **文档与代码一致性** — 需验证 README / DEPLOY_GUIDE 中所有命令、路径、URL 实际可执行
6. **部署脚本** — `start_win.ps1` / `docker-compose.yml` 缺少自动化测试
7. **`ADAPTER_API_TOKENS`** — 网关 token 认证缺少正反向测试

---

## 二、分层分模块测试计划

### 阶段 1：基础设施层（infra/ · 13 files）

| # | 测试用例 | 目标模块 | 测试方法 | 优先级 |
|---|---------|---------|---------|-------|
| 1.1 | 配置默认值与类型校验 | configs/settings.py | pytest — 验证所有分层配置的类型 | P1 |
| 1.2 | 配置脱敏打印（masked_repr）返回 `***` | DBSettings | pytest — 验证敏感字段不泄露 | P0 |
| 1.3 | 响应规范一致性（所有 API 必须使用 infra/response 格式） | infra/response.py + adapter | 代码扫描 + 集成测试 | P1 |
| 1.4 | 异常类型与全局处理（FastAPI exception_handler） | infra/exceptions.py + exception_handler.py | pytest — 触发所有异常类型 | P1 |
| 1.5 | 告警系统 — 钉钉签名、邮件格式、通道静默 | infra/alerting.py | pytest mock | P1 |
| 1.6 | 日志文件轮转 + 控制台输出验证 | infra/logger_setup.py | pytest — 创建临时目录验证日志文件生成 | P1 |
| 1.7 | Redis 客户端连接 / 超时 / 断线降级 | infra/redis_client.py | pytest mock + fakeredis | P0 |
| 1.8 | 任务队列 — enqueue / consume / status / cancel 全流程 | infra/task_queue.py | pytest mock | P0 |
| 1.9 | 任务状态 — 完整状态流转（pending → running → success / failed / canceled） | infra/task_states.py | pytest mock | P0 |
| 1.10 | 任务异常 — 各种 failure reason 映射 | infra/task_exceptions.py | pytest | P1 |
| 1.11 | 定时调度 — interval / cron / 并发控制 | infra/task_scheduler.py | pytest mock APScheduler | P1 |
| 1.12 | 数据库 — Base 模型 + CRUD + 分页 + upsert | infra/db_base.py, db_models.py | pytest SQLite in-memory | P0 |
| 1.13 | 数据库 — 加密字段 roundtrip（AES256） | core/compliance/sensitive_crypto.py + db_models.py | pytest — 加密后不包含明文 | P0 |
| 1.14 | 数据归档 / 冷热分离 | core/compliance/archive_mixin.py, data_lifecycle.py | pytest — 插入过期数据 → 触发归档 → 验证 hot-only | P1 |
| 1.15 | `datetime.utcnow()` → `datetime.now(timezone.utc)` 替换与验证 | 多个文件 | grep + 编译验证 | P1 |

### 阶段 2：通用能力层（core/ · 3 子模块）

| # | 测试用例 | 目标模块 | 测试方法 | 优先级 |
|---|---------|---------|---------|-------|
| 2.1 | 爬虫 SDK — HTTP GET/POST 正常流程 | core/spider_core/sdk.py | pytest mock requests | P0 |
| 2.2 | 爬虫 SDK — 网络异常、超时、403 风控触发 | core/spider_core/sdk.py | pytest mock network error | P0 |
| 2.3 | User-Agent 池 — 轮换、刷新、负载均衡 | core/spider_core/ua_pool.py | pytest | P1 |
| 2.4 | 代理池 — 失败阈值、健康度评估 | core/spider_core/proxy_pool.py | pytest mock | P1 |
| 2.5 | Rate Limiter — 令牌桶、并发限制、超频阻断 | core/spider_core/rate_limiter.py | pytest 并发测试 | P0 |
| 2.6 | robots.txt 校验 — allow / disallow / 禁用模式 | core/spider_core/robots_checker.py | pytest mock | P1 |
| 2.7 | Checkpoint 断点续爬 | core/spider_core/checkpoint_manager.py | pytest — 模拟中断 → 恢复 | P1 |
| 2.8 | Risk Controller — 多种风控触发与告警 | core/spider_core/risk_controller.py | pytest | P0 |
| 2.9 | PII Mask 全集测试（电话/邮箱/微信/银行卡/公司/URL） | core/compliance/pii_mask.py | pytest 参数化 | P0 |
| 2.10 | Privacy Stripper — 字典 key 清洗 | core/compliance/privacy_stripper.py | pytest | P1 |
| 2.11 | Sensitive Filter — 敏感词检测 + 运行时添加词 | core/compliance/sensitive_filter.py | pytest | P1 |
| 2.12 | Compliance Checker — 风险分级 high/medium/low | core/compliance/compliance_checker.py | pytest | P1 |
| 2.13 | 去重引擎 — 多重匹配规则 | core/data_core/dedupe_engine.py | pytest — 相同电话号码/相似文本/相同 uid | P0 |
| 2.14 | 合并引擎 — 字段合并策略 | core/data_core/merge_engine.py | pytest | P1 |
| 2.15 | 评分引擎 — 全阈值 + 加权评分 | core/data_core/scoring_engine.py | pytest | P0 |
| 2.16 | 黑名单过滤 | core/data_core/blacklist_filter.py | pytest | P1 |
| 2.17 | 数据流水线 — 正常 + 空输入 + 异常数据 | core/data_core/pipeline.py | pytest | P1 |
| 2.18 | 发送账号池 — 轮询、封禁跳过 | core/send_core/account_pool.py | pytest mock | P0 |
| 2.19 | 发送限流 — 单用户/单账号/全局三级 | core/send_core/rate_limiter.py | pytest — 模拟并发请求 | P0 |
| 2.20 | 内容风控 — 敏感词阻断、通过率 | core/send_core/content_risk.py | pytest — 注入违规内容 | P0 |
| 2.21 | 封禁检测 — 响应识别、自动加入黑名单 | core/send_core/ban_detector.py | pytest mock | P1 |
| 2.22 | 失败重试 — 指数退避、5 次重试、永久失败 | core/send_core/failure_retry.py | pytest | P1 |
| 2.23 | 发送流水线 — 全流程串联 | core/send_core/send_pipeline.py | pytest 集成 | P0 |
| 2.24 | 发送任务状态存储 | core/send_core/task_status.py | pytest | P1 |

### 阶段 3：业务模块层（business/ · 4 子模块）

| # | 测试用例 | 目标模块 | 测试方法 | 优先级 |
|---|---------|---------|---------|-------|
| 3.1 | BaseSpider 抽象基类 — 抓取 + 清洗 pipeline | multi_spider/base.py | pytest mock HTTP | P0 |
| 3.2 | 16 种渠道源 — 每个都验证 name + url 构造 | multi_spider/sources/* | pytest 参数化 | P1 |
| 3.3 | 爬虫任务状态持久化（Redis） | multi_spider/registry.py | pytest mock Redis | P1 |
| 3.4 | PII 在 raw_payload 中自动脱敏 | multi_spider/base.py | pytest — 检查 payload 无明文手机号 | P0 |
| 3.5 | 爬虫流水线 — upsert 幂等性 | multi_spider/pipeline.py | pytest — 两次相同输入 → 一条记录 | P1 |
| 3.6 | 数据清洗 — dirty filter（空文本/超短文本） | data_clean/filters.py | pytest | P1 |
| 3.7 | 实体抽取 — 公司名 / 电话 / 微信 / 邮箱 / 金额 | data_clean/extractor.py | pytest 参数化 | P0 |
| 3.8 | Normalizer — 生成标准 Opportunity 对象 | data_clean/normalizer.py | pytest — 验证字段完整性 | P1 |
| 3.9 | Compliance Step — 合规报告生成 | data_clean/compliance_step.py | pytest | P1 |
| 3.10 | Engine Step — 去重 + 评分 | data_clean/engine_step.py | pytest | P1 |
| 3.11 | 清洗流水线 — End-to-End（raw → opportunity） | data_clean/pipeline.py | pytest | P0 |
| 3.12 | 清洗流水线 — 幂等性（两次相同输入不重复） | data_clean/pipeline.py | pytest | P1 |
| 3.13 | Registry — 任务注册与执行 | data_clean/registry.py | pytest | P1 |
| 3.14 | 模板引擎 — 邮件/微信/飞书/H5 模板渲染 | customer_send/template_engine.py | pytest — 验证渲染结果 | P1 |
| 3.15 | 4 发送渠道 — mock SMTP / mock Webhook / mock H5 | customer_send/channels/* | pytest mock | P0 |
| 3.16 | 发送流水线 — dry-run / 单目标 / 多目标 | customer_send/pipeline.py | pytest | P0 |
| 3.17 | 发送记录 upsert 行为 | customer_send/storage.py | pytest | P1 |
| 3.18 | 商机分配 — 行业/区域加权评分 | sales_task/assignment_engine.py | pytest | P0 |
| 3.19 | 定时跟进提醒 — 首次跟进、二次跟进、逾期、已关闭跳过 | sales_task/reminder_engine.py | pytest | P1 |
| 3.20 | 状态引擎 — 合法流转 / 非法阻断 | sales_task/status_engine.py | pytest | P1 |
| 3.21 | 转化漏斗统计 — 数据采样 / 空值处理 | sales_task/funnel_engine.py | pytest | P1 |
| 3.22 | 推送通知器 — dry-run / 多通道 | sales_task/push_notifier.py | pytest mock | P1 |
| 3.23 | 销售调度全流水线 | sales_task/pipeline.py | pytest | P1 |

### 阶段 4：接入展示层（adapter/ + web_admin/）

| # | 测试用例 | 目标模块 | 测试方法 | 优先级 |
|---|---------|---------|---------|-------|
| 4.1 | FastAPI 路由完整性 — /health / /docs / /tools / /tasks / /admin/* | adapter/main.py | TestClient — 遍历路由 | P0 |
| 4.2 | OpenClaw 工具注册 — 列出已注册工具 + schema | adapter/tool_registry.py | pytest — 验证 ≥ 5 个工具 | P0 |
| 4.3 | Schema Adapter — 字典 / None / 嵌套字典 | adapter/schema_adapter.py | pytest | P1 |
| 4.4 | API 响应模型 — success / error 两种格式 | adapter/models.py | pytest | P1 |
| 4.5 | 网关认证 — Bearer Token 有效/无效/空 | adapter/auth.py + middleware | TestClient | P0 |
| 4.6 | Web 管理后台登录 — 正确账号 + 错误密码 + CSRF | web_admin/auth.py + pages | TestClient | P0 |
| 4.7 | 后台会话 — 创建 / 过期 / 登出 | web_admin/auth.py | TestClient + mock Redis | P1 |
| 4.8 | 后台页面 — 看板/爬虫/商机/渠道/销售/审计 页面可访问 | web_admin/pages.py | TestClient — 返回 200 | P1 |
| 4.9 | 后台 API — 6 个 API 模块返回 JSON 响应 | web_admin/api/* | TestClient — 验证 JSON 格式 | P1 |
| 4.10 | 菜单结构 — 与 pages.py 路由一一对应 | web_admin/menu.py | pytest — 静态对比 | P1 |
| 4.11 | 中间件 — 行为审计日志 / 高危操作告警 | web_admin/middleware.py | pytest mock alerting | P1 |
| 4.12 | 后台脱敏 — API 响应中不包含明文手机号/邮箱 | web_admin/api/* | TestClient — grep 响应内容 | P0 |
| 4.13 | 未登录访问 — 所有 /admin/* 页面重定向登录 | adapter/main.py | TestClient | P1 |

---

## 三、端到端全链路测试（核心）

### 测试场景：从"爬虫抓取"到"销售转化"

```
步骤 1：定时触发爬虫任务
  ↓
步骤 2：multi_spider 抓取原始数据（mock HTTP response）
  ↓
步骤 3：原始数据写入 spider_raw_data 表（含合规报告）
  ↓
步骤 4：data_clean 流水线提取实体 + 评分分级
  ↓
步骤 5：结构化数据写入 business_opportunities 表（自动去重）
  ↓
步骤 6：customer_send 多渠道推送客户（mock Webhook）
  ↓
步骤 7：sales_task 自动分配销售人员 + 设置跟进提醒
  ↓
步骤 8：模拟手动触达 → 更新商机状态 from "new" → "following"
  ↓
步骤 9：转化漏斗统计 — 计算商机数量 / 转化数 / 转化数
  ↓
步骤 10：Web 管理后台查看看板数据 + 审计日志

关键验证点：
 ✓ 每个步骤的输入数据与输出数据类型正确
 ✓ 每个步骤都产生正确的 system_logs 记录
 ✓ 敏感字段全程脱敏（数据库、API、前端）
 ✓ 状态流转符合预期（new → following → closed / lost）
 ✓ 发送渠道正确轮转，无账号超限
 ✓ Redis 任务状态正确记录
```

### 用例清单（端到端）

| # | 场景 | 目标 | 测试方法 | 优先级 |
|---|------|-----|---------|-------|
| E2E-1 | 完整正向流程（上述 10 步） | 全链路畅通 | 集成测试（mock HTTP / SMTP） | **P0** |
| E2E-2 | 相同 raw 数据 → 再次触发 → 自动去重（upsert） | 去重逻辑正确 | 集成测试 | P1 |
| E2E-3 | 触发多个商机 → 多个发送渠道并行 → 验证账号池轮转正确 | 多账号调度 | 集成测试 | P1 |
| E2E-4 | 高优先级商机 → 分配给高技能销售 → 验证分配权重 | 销售分配逻辑 | 集成测试 | P1 |
| E2E-5 | 逾期商机 → 自动升级告警 → 触发 service_exception_sync | 告警联动 | 集成测试 | P1 |
| E2E-6 | OpenClaw 工具调用 → 异步任务 → Webhook 回调 | 网关对接 | 集成测试 + TestClient | **P0** |
| E2E-7 | 后台登录 → 查看商机 → 标记跟进 → 记录审计日志 | 后台操作闭环 | 集成测试 | **P0** |
| E2E-8 | 无 Redis 环境 → 降级为内存缓存 → 全流程验证 | 容错能力 | 集成测试 | P1 |
| E2E-9 | 使用 .env 真实生产配置 → 启动服务 → 验证所有 API 响应 | 配置正确性 | 手动/集成混合 | **P0** |
| E2E-10 | 多次重复 E2E-1 → 验证幂等性（数据库不产生重复记录） | 幂等性 | 集成测试 | P1 |

---

## 四、合规与异常专项测试

### 4.1 隐私合规专项

| # | 测试用例 | 验证点 | 优先级 |
|---|---------|-------|-------|
| C-1 | `core/compliance/pii_mask.py` 所有 mask 函数 → 验证输出不包含可识别隐私 | mask_phone / mask_email / mask_wechat / mask_company / mask_url 的单元测试全部通过 | P0 |
| C-2 | 数据库敏感字段 — `business_opportunities` 中 phone/email 字段为加密格式 | 直接读取数据库原始字节 → 不包含明文 | P0 |
| C-3 | API 响应中敏感字段（phone, email, wechat）均为脱敏格式（* 填充） | curl `/api/admin/*` → grep 响应内容 | P0 |
| C-4 | Web 后台页面 HTML 中不含明文手机号/邮箱 | 用 TestClient 获取页面 → HTML 内容 grep | P0 |
| C-5 | `DB_ENCRYPTION_KEY` ≥ 32 bytes 且可正确 roundtrip | 加密 → 解密 → 原文一致 | P0 |
| C-6 | 日志文件中搜索敏感字段（手机号/邮箱/密钥） | grep 所有 `logs/*.log` → 不应包含 | P0 |
| C-7 | `DB_SENSITIVE_MASK_ENABLED=true` 配置生效验证 | settings → API 返回一致 | P1 |
| C-8 | 合规报告生成（compliance_checker.report_to_dict） | 确保 high risk 标记正确 | P1 |

### 4.2 风控场景专项

| # | 测试用例 | 目标模块 | 验证点 | 优先级 |
|---|---------|---------|-------|-------|
| R-1 | 爬虫高频访问检测（连续 >10 req/min → medium） | core/spider_core/rate_limiter.py + risk_controller.py | 触发 WARN + 速率限制 | P0 |
| R-2 | 403/429/验证码 → 自动降级（减速 + 切换代理） | core/spider_core/risk_controller.py | delay > 0 + agent 已切换 | P1 |
| R-3 | 多渠道批量发送 → 账号池轮转正确 | core/send_core/account_pool.py | 10 次请求分布到所有账号 | P0 |
| R-4 | 敏感词内容 → 阻断发送 + 记录高危日志 | core/send_core/content_risk.py | 返回 Blocked 状态 | P0 |
| R-5 | 黑名单线索 → 过滤不进入下游 pipeline | core/data_core/blacklist_filter.py | 屏蔽特定 phone/email | P1 |
| R-6 | 发送频率超限 → 自动延迟下一条 | core/send_core/rate_limiter.py | 超过阈值 → 阻塞等待 | P1 |
| R-7 | 连续失败检测 → 账号自动标记封禁 | core/send_core/ban_detector.py | 连续 N 次失败 → account.status = banned | P1 |
| R-8 | 发送失败 → 自动指数退避重试 → 最终成功/失败 | core/send_core/failure_retry.py | 退避间隔递增到最大值 | P1 |

### 4.3 异常场景专项

| # | 测试用例 | 目标模块 | 验证点 | 优先级 |
|---|---------|---------|-------|-------|
| E-1 | 网络中断（HTTP 全部失败） | core/spider_core/sdk.py | 捕获异常 → 记录 error log → 不崩溃 | P0 |
| E-2 | 数据库宕机 → 重连机制 | infra/db_base.py | 模拟断连 → 自动重连 + 告警触发 | P0 |
| E-3 | Redis 断开 → 自动降级内存缓存 | infra/redis_client.py | 测试中 disable Redis → 流程继续 | P0 |
| E-4 | 发送账号全部被封禁 → 优雅失败 | core/send_core/account_pool.py | 返回明确错误 → 不抛 Unhandled Exception | P1 |
| E-5 | 任务超时 → 自动 cancel → 状态更新 | infra/task_queue.py | task_timeout → status=canceled | P1 |
| E-6 | 无效输入数据 → pipeline 正确处理空数据 | business/data_clean/pipeline.py | 不崩溃，返回空 opportunity | P1 |
| E-7 | 无效商机 ID → 状态引擎拒绝操作 | business/sales_task/status_engine.py | 明确错误消息 | P1 |
| E-8 | 配置项缺失 → 清晰错误提示 | configs/settings.py | 缺 DB_HOST → 明确错误信息 | P1 |
| E-9 | Web 后台恶意登录尝试（多次错密码） | web_admin/auth.py + middleware | 记录高危审计日志 + 告警 | P1 |
| E-10 | OpenClaw 网关 API 请求超时 | adapter/main.py | 返回标准 error JSON，不崩溃 | P1 |

### 4.4 告警验证

| # | 测试用例 | 目标模块 | 验证点 | 优先级 |
|---|---------|---------|-------|-------|
| A-1 | 数据库异常 → 触发 service_exception_sync | infra/exception_handler.py | mock alert_service → 验证被调用 | P0 |
| A-2 | 爬虫高风险触发 → 触发告警（带 debounce） | core/spider_core/risk_controller.py | 5 min 内只告警 1 次 | P0 |
| A-3 | 商机分配失败率 > 5% → 告警 | business/sales_task/assignment_engine.py | 告警触发 | P1 |
| A-4 | 发送失败率 > 20% → 告警 | business/customer_send/pipeline.py | 告警触发 | P1 |
| A-5 | 后台高危操作（批量删除商机/渠道） → 告警 | web_admin/middleware.py | 操作后 audit log 存在 | P0 |

---

## 五、OpenClaw 智能体联调测试

### 5.1 联调步骤

```
步骤 1：准备 OpenClaw 智能体配置（examples/openclaw_skills_demo.yaml）
  ↓
步骤 2：启动 BizTools4Openclaw（python -m adapter.main）
  ↓
步骤 3：智能体调用 /tools 接口 → 验证响应 schema 正确
  ↓
步骤 4：智能体调用工具（如 spider/run → 触发异步任务）
  ↓
步骤 5：智能体轮询 /tasks/{task_id}/status 直至完成
  ↓
步骤 6：智能体获取 /api/admin/leads 商机列表
  ↓
步骤 7：智能体触发 customer_send 推送
  ↓
步骤 8：智能体查询销售转化漏斗
  ↓
步骤 9：验证全程响应脱敏（API 返回无明文隐私）
```

### 5.2 联调用例清单

| # | 场景 | 目标 | 测试方法 | 优先级 |
|---|------|-----|---------|-------|
| O-1 | 工具列表接口响应格式 | `/api/v1/tools` 返回正确 JSON | TestClient | P0 |
| O-2 | 工具 schema 描述完整 | 每个 tool 的 schema 包含 input/output | pytest | P1 |
| O-3 | 调用不存在的工具 → 标准错误响应 | 404 / error JSON | TestClient | P1 |
| O-4 | 异步任务提交 → 状态查询 → 结果获取 | 完整 async 流程 | TestClient + polling | P0 |
| O-5 | 任务取消 → 状态不再更新 | POST /tasks/{id}/cancel | TestClient | P1 |
| O-6 | 任务重试 → 失败后可重新提交 | 提交失败任务 → POST /tasks/{id}/retry | TestClient | P1 |
| O-7 | OpenClaw Token 认证 → 有效/无效/过期 | Authorization header | TestClient | P0 |
| O-8 | Webhook 回调机制 → 业务事件通知 | adapter/tool_registry.py | mock webhook | P1 |
| O-9 | 数据脱敏验证 — 所有 OpenClaw 响应中不含明文隐私 | 检查所有工具的 data 字段 | 代码扫描 + 集成测试 | **P0** |
| O-10 | 批量并发调用 → 速率限制生效 | 模拟高并发 → 验证 429/限流 | pytest + threading | P1 |

---

## 六、多部署环境兼容性测试

### 6.1 Windows 本地部署

| # | 场景 | 验证步骤 | 优先级 |
|---|------|---------|-------|
| D-1 | `.\start_win.ps1 -Mode local` | Python 依赖安装、Web 后台可访问 | P0 |
| D-2 | `.\start_win.ps1 -Mode docker-dev` | 3 容器正常启动、健康检查通过 | P0 |
| D-3 | `.\start_win.ps1 -Mode docker-prod` | 3 容器 + 不可变部署 + 代码无本地修改 | P1 |
| D-4 | `.\start_win.ps1 -Stop` | 所有服务停止（Python 进程 / Docker 容器） | P1 |
| D-5 | `.\start_win.ps1 -Logs` | 显示最近日志文件 | P1 |
| D-6 | 端口冲突检测（8000/5432/6379 已占用时） | 脚本给出清晰提示 + 解决建议 | P1 |
| D-7 | 缺少 Python / Docker 时 → 友好提示 | 脚本检测并打印安装指引 | P1 |
| D-8 | `.env` 缺失 → 自动从 `.env.example` 生成 | 生成后提示用户填写密码 | P1 |
| D-9 | 虚拟环境创建 → 依赖安装 → 启动全流程 | 脚本一次执行成功 | P0 |

### 6.2 Docker 容器化部署

| # | 场景 | 验证步骤 | 优先级 |
|---|------|---------|-------|
| D-10 | `docker compose --profile prod up -d` | 3 容器启动、健康检查 green | P0 |
| D-11 | 容器重启 / stop + start | 数据持久化（PG / Redis 数据保留） | P0 |
| D-12 | 容器重建 `docker compose up -d --build` | 新镜像可替换旧镜像，服务不中断 | P1 |
| D-13 | PostgreSQL 初始化脚本 init_db.sql 执行 | 4 张表 + 索引 + pgvector 扩展创建 | P0 |
| D-14 | Dockerfile 三阶段构建最终镜像大小 | 目标 ≤ 500 MB | P1 |
| D-15 | Redis 数据持久化 AOF 写入正常 | 重启后数据保留 | P1 |
| D-16 | 容器内 Python 进程以非 root 用户运行 | docker exec id → uid != 0 | P1 |
| D-17 | 日志文件挂载到本地目录 | docker logs → 文件内容可读 | P1 |
| D-18 | 端口映射：8000 → 宿主可访问 | curl localhost:8000/health | P0 |

### 6.3 Linux 原生部署（可选验证）

| # | 场景 | 验证步骤 | 优先级 |
|---|------|---------|-------|
| D-19 | Python venv + requirements.txt 安装 | pip install 成功 | P2 |
| D-20 | uvicorn adapter.main:app --host 0.0.0.0 --port 8000 | 服务可访问 | P2 |
| D-21 | systemd 服务文件（可选） | 服务启停 | P2 |

---

## 七、文档一致性校验

| # | 测试项目 | 目标文档 | 验证方法 | 优先级 |
|---|---------|---------|---------|-------|
| DOC-1 | README.md 中列出的所有模块 → 对应代码文件存在 | README.md | ls / glob 验证 | P0 |
| DOC-2 | README.md 架构图 4 层划分 → 与代码目录一致 | README.md | 手动对比 | P1 |
| DOC-3 | README.md 中所有命令 → 实际可执行（`python -m adapter.main`、`pip install -r requirements.txt` 等） | README.md | 实际执行 | P0 |
| DOC-4 | README.md 中 11 个爬虫数据源 → 代码中对应存在 | README.md | grep / glob | P0 |
| DOC-5 | README.md 中 4 个发送渠道 → 代码中对应存在 | README.md | grep / glob | P0 |
| DOC-6 | README.md 中部署 URL（/admin, /docs, /health）→ 实际可访问 | README.md | TestClient 验证 | P0 |
| DOC-7 | DEVELOP_RULES.md 代码规范 → 实际代码符合 | DEVELOP_RULES.md | flake8 / pyright / 手动代码评审 | P1 |
| DOC-8 | DEPLOY_GUIDE.md 中所有部署命令 → 成功执行 | docs/DEPLOY_GUIDE.md | 实际执行 | P0 |
| DOC-9 | docs/TASK_LIST.md 任务状态 → 与当前提交一致 | docs/TASK_LIST.md | 对比 T01-T14 代码 | P1 |
| DOC-10 | examples/openclaw_skills_demo.yaml 中 API 路径 → 实际存在 | examples/*.yaml | grep 验证 | P1 |
| DOC-11 | Dockerfile 中 FROM 语句基础镜像 → 存在且可 pull | docker/Dockerfile | docker pull | P1 |
| DOC-12 | docker-compose.yml 中所有服务名 → 与 DEPLOY_GUIDE.md 描述一致 | docker-compose.yml | 交叉对比 | P1 |
| DOC-13 | 所有文档中端口号（8000/5432/6379）→ 与代码配置一致 | 所有文档 | grep 验证 | P0 |
| DOC-14 | 文档中提及的配置项（DB_ENCRYPTION_KEY, WEB_ADMIN_PASSWORD_PLAIN 等） → configs/settings.py 实际定义 | 所有文档 | grep 验证 | P0 |
| DOC-15 | 所有文档内部链接（README → DEPLOY_GUIDE / TASK_LIST.md 等）→ 可跳转 | 所有文档 | 手动点击验证 | P1 |

---

## 八、缺陷记录与复测闭环流程

### 8.1 缺陷记录模板

```
缺陷 ID: T17-DEF-{序号}
标题: 简要描述
模块: (infra/core/business/adapter/web_admin/deploy/docs)
严重等级: P0 / P1 / P2 / P3
步骤复现: 1. ... 2. ... 3. ...
期望结果: ...
实际结果: ...
测试环境: (本地 / Docker)
测试人员: (执行 T17 的工程师)
发现日期: YYYY-MM-DD
修复者: (待分配)
修复完成日期:
复测结果: PASS / FAIL (附证据: 测试日志 / 截图)
备注:
```

### 8.2 严重等级定义

| 等级 | 定义 | 典型场景 | 修复时限 |
|---|------|---------|---------|
| **P0** | 阻断 / 崩溃 / 数据丢失 / 隐私泄露 | 服务崩溃、明文手机号暴露、数据库丢失 | 立即 |
| **P1** | 严重功能缺陷 / 显著性能问题 | 爬虫失败、消息无法发送、核心 API 500 | 24h |
| **P2** | 一般功能缺陷 / 文档不一致 | 小 bug、过时文档、非核心 API 异常 | 本任务内 |
| **P3** | 建议性改进 / minor issue | 代码风格、日志格式优化、deprecation warnings | 非强制 |

### 8.3 闭环流程

```
步骤 1：测试发现 → 填写缺陷记录（T17-DEF-XXX.md）
  ↓
步骤 2：优先级评估 → P0 立即告警通知
  ↓
步骤 3：代码修复（仅限此任务允许修改代码）
  ↓
步骤 4：回归测试 → 运行相关 tests/test_t*.py 全部通过
  ↓
步骤 5：端到端复测 → E2E-* 场景再次通过
  ↓
步骤 6：缺陷关闭 → 在记录中填写 PASS / FAIL + 证据
  ↓
步骤 7：如 FAIL → 回到步骤 3 重新修复
  ↓
步骤 8：所有 P0/P1 关闭 → 本任务完成
```

### 8.4 测试报告格式

```
BizTools4Openclaw T17 测试报告
================================

一、测试概览
  - 执行日期: YYYY-MM-DD
  - 环境: (Windows 11 + Python 3.11 + Docker Desktop)
  - 测试用例总数: ~180
  - 通过: N
  - 失败: M
  - 跳过: K
  - 通过率: N/180 = X%
  - 执行时长: HH:MM:SS

二、分层测试结果
  - 基础设施层（infra/）: N1 / N1_total 通过
  - 通用能力层（core/）: N2 / N2_total 通过
  - 业务模块层（business/）: N3 / N3_total 通过
  - 接入展示层（adapter/ + web_admin/）: N4 / N4_total 通过

三、端到端测试
  - E2E-1 ~ E2E-10: 10/10 通过

四、合规与异常专项
  - 隐私合规 (C-1 ~ C-8): 8/8
  - 风控场景 (R-1 ~ R-8): 8/8
  - 异常场景 (E-1 ~ E-10): 10/10
  - 告警验证 (A-1 ~ A-5): 5/5

五、OpenClaw 联调
  - O-1 ~ O-10: 10/10

六、部署兼容性
  - D-1 ~ D-18: 18/18

七、文档一致性
  - DOC-1 ~ DOC-15: 15/15

八、缺陷列表
  共发现 X 个缺陷：
  - T17-DEF-001 P1 xxx → 已修复 → 复测 PASS
  - T17-DEF-002 P2 xxx → 已修复 → 复测 PASS
  - ...

九、结论
  - 本项目是否达到交付标准: YES / NO
  - 剩余 P0 缺陷: 0
  - 剩余 P1 缺陷: 0
  - 建议: ...
```

---

## 九、完整测试执行计划

### 9.1 执行顺序

1. 阶段 1 → 基础设施层（infra/）
2. 阶段 2 → 通用能力层（core/）
3. 阶段 3 → 业务模块层（business/）
4. 阶段 4 → 接入展示层（adapter/ + web_admin/）
5. 阶段 5 → 端到端全链路（E2E-1 ~ E2E-10）
6. 阶段 6 → 合规与异常专项（C-*, R-*, E-*, A-*）
7. 阶段 7 → OpenClaw 联调（O-1 ~ O-10）
8. 阶段 8 → 部署兼容性（D-1 ~ D-18）
9. 阶段 9 → 文档一致性（DOC-1 ~ DOC-15）
10. 阶段 10 → 缺陷修复闭环（根据发现）

### 9.2 允许修改的代码范围

| # | 允许的修改范围 | 说明 |
|---|-------------|------|
| 1 | `*.py` 业务代码 | 仅限修复 P0/P1 缺陷（如 deprecation warnings、小 bug） |
| 2 | `configs/settings.py` | 修复配置问题、添加缺失的配置项 |
| 3 | `docker/Dockerfile` | 修复构建问题、优化镜像大小 |
| 4 | `docker/docker-compose.yml` | 修复编排问题、端口冲突 |
| 5 | `docker/init_db.sql` | 修复数据库初始化脚本 |
| 6 | `start_win.ps1` | 修复 Windows 部署脚本 |
| 7 | `docs/*.md` | 修复文档与代码不一致 |
| 8 | `tests/test_t*.py` | 增加/修改测试用例覆盖新场景 |

**严格禁止：** 架构重构、目录重命名、新增底层基础设计（除非 P0 问题，需单独评审）。

### 9.3 测试工具清单

| 工具 | 用途 |
|------|-----|
| pytest | 单元/集成测试 |
| fastapi.testclient.TestClient | 接口测试 |
| unittest.mock | Mock HTTP / SMTP / Redis |
| fakeredis | Redis mock（可选） |
| SQLite in-memory | 数据库集成测试 |
| shell / PowerShell | 部署脚本测试 |
| grep / findstr | 隐私字段扫描、代码一致性扫描 |

### 9.4 环境准备

- Python 3.10+
- Docker Desktop 4.0+（可选）
- PostgreSQL 16（可选，或使用 SQLite in-memory）
- Redis 7.2（可选，或使用降级内存缓存）
- 浏览器：Chrome / Edge（用于 Web 管理后台手动验证）
- IDE：VS Code / PyCharm

### 9.5 验收标准

✅ **必须满足所有项：**

1. 基线测试：`pytest tests/ -v --tb=short` 全部通过（≥ 221 tests）
2. 新编写的 T17 用例：**全部通过**
3. E2E 场景：**10 个场景全部通过**
4. P0 缺陷：**0 个未关闭**
5. P1 缺陷：**0 个未关闭**
6. Web 管理后台：**所有页面可访问、所有 API 响应正确**
7. OpenClaw 网关：**工具注册正确、可调用、响应脱敏**
8. Docker 部署：**`docker compose --profile prod up -d` 成功，3 容器 healthy**
9. Windows 一键脚本：**`.\start_win.ps1 -Mode docker-prod` 成功**
10. 文档一致性：**DOC-1 ~ DOC-15 全部通过**

### 9.6 交付物清单

| # | 交付物 | 格式 |
|---|-------|-----|
| 1 | T17 测试计划（本文档） | .md |
| 2 | T17 测试代码（新增/修改的 tests/test_t*.py） | .py |
| 3 | T17 测试报告 | .md |
| 4 | T17 缺陷记录（如有） | .md |
| 5 | T17 测试执行日志（pytest 输出） | .log |
| 6 | 缺陷修复的 git commits | Git 提交历史 |
| 7 | 部署验证截图（可选） | .png |

---

## 十、风险与应对

| 风险 | 概率 | 影响 | 应对措施 |
|---|------|-----|---------|
| 测试用例发现 P0 缺陷 | 中 | 阻塞 T17 交付 | 立即修复，修复后重新全量回归 |
| Docker 环境不可用（网络问题） | 中 | 部署测试无法执行 | 降级测试本地模式 + 手动 Docker Hub 验证 |
| 外部 API 限流 / 反爬导致测试失败 | 低 | 爬虫测试误判 | 使用 mock HTTP 响应，不依赖真实外网 |
| 测试数据不一致导致间歇性失败 | 中 | 不可靠测试 | 使用 fixture setup/teardown；确保每个用例独立 |
| deprecation warnings 修复引入新 bug | 低 | 回归失败 | 每次修改后运行 pytest 全量；单独提交修复 |
| 文档与代码不一致的批量修正 | 中 | 工作量大 | 优先自动化代码扫描 + grep 验证；文档按模块分批修正 |
| 运行时间过长 | 中 | 测试效率低 | 并行执行 pytest（`pytest -n 4`）；可按模块分批执行 |

---

## 十一、执行阶段总结

```
阶段 1：基础设施层测试   → ~25 用例  → 目标全部 PASS
阶段 2：通用能力层测试     → ~25 用例  → 目标全部 PASS
阶段 3：业务模块层测试     → ~30 用例  → 目标全部 PASS
阶段 4：接入展示层测试     → ~15 用例  → 目标全部 PASS
阶段 5：端到端全链路测试   → 10 个场景 → 目标全部 PASS
阶段 6：合规与异常专项     → ~30 用例  → 目标全部 PASS
阶段 7：OpenClaw 联调     → 10 个场景 → 目标全部 PASS
阶段 8：部署兼容性测试     → 18 个场景 → 目标全部 PASS
阶段 9：文档一致性校验     → 15 个检查 → 目标全部 PASS
阶段 10：缺陷修复闭环       → 全部 P0/P1 关闭
====================================================================
总计：约 180 条用例 + 端到端场景（60 分钟内完成）
目标通过率：100%
```
