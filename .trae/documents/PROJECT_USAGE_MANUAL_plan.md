# BizTools4Openclaw — 项目使用手册编写计划

> **文档版本**: v1.0 (T29)  
> **状态**: 待审批  
> **目标文件**: `docs/PROJECT_USAGE_MANUAL.md`（约 80-120 页）  
> **适用人群**: 运营人员、销售、合规人员、系统管理员、开发者

---

## 一、编写目标与定位

### 1.1 文档定位

| 维度 | 说明 |
|------|------|
| **定位** | 单一入口使用手册：覆盖部署、配置、各业务模块操作、API 参考、故障排查、开发扩展 |
| **与现有文档关系** | 不替代 README / QUICKSTART / DEVELOP_RULES / 各专题文档；而是它们的结构化索引+实战整合 |
| **深度** | P1 面向非技术人员的日常操作指南；P2 面向开发者的扩展指南；P3 深度参考（配置表、API） |

### 1.2 关键读者画像

| 角色 | 关注章节 | 使用频率 |
|------|---------|---------|
| 运营人员 (ops) | P3 管理后台、P4 采集、P5 清洗、P10 FAQ | 每天 |
| 销售人员 (sales) | P3 管理后台（销售模块）、P7 销售自动化 | 每天 |
| 合规人员 (compliance) | P3 管理后台（合规模块）、P11 开发者手册 | 每周 |
| 系统管理员 | P2 部署、P9 配置、P10 FAQ | 部署/问题 |
| 开发者 | P8 API 参考、P11 开发者扩展、P12 附录 | 开发/扩展 |

### 1.3 编写原则

1. **一份文档，多角色索引**：目录前标注角色标签（运维、销售、合规、开发者）
2. **示例驱动**：每章 30% 文字说明 + 50% 界面截图/示例/代码 + 20% 参数表
3. **可快速查找**：每章有「本节任务清单」、「关键参数速查表」、「常见错误」
4. **与代码同步**：所有 API / 配置字段 / 路径有明确对应，以代码可验证为准
5. **中英双语术语对照**：专业术语首次出现标注英文原文

---

## 二、文档结构（12 个部分，预估 80-120 页）

### P1 项目概述与架构（约 5 页）

内容清单：
- 项目简介与核心能力（6 大能力）
- 四层分层架构图 + 数据流动图
- 版本信息（T01-T29 里程碑速览）
- 技术栈一览（Python 3.11 + FastAPI + SQLAlchemy + Redis + Docker）
- 产品与可交付物矩阵（什么场景用哪个模块）

**本节参考**: [README.md](file:///C:/projects/BizTools4Openclaw/README.md) 中已有的架构图和能力列表。

### P2 快速入门（约 8 页）

内容清单：
- **2.1 环境准备**：Python 3.11 安装、Docker Desktop 安装、端口占用检查
- **2.2 三种部署方式**：
  - 本地开发（venv + uvicorn，代码热重载）
  - Docker 单机（docker-compose up，推荐生产）
  - Windows 一键脚本（start_win.ps1）
- **2.3 第一步操作**：
  - `.env.example → .env` 配置向导（至少 DB_ENCRYPTION_KEY 必须改）
  - 首次启动：数据库自动初始化、默认账号、访问地址
  - 首个爬虫任务：从配置到结果
- **2.4 访问入口清单**：
  - Web 管理后台: http://localhost:8080/admin/login
  - API 文档: http://localhost:8000/docs
  - 健康检查: http://localhost:8000/health

**本节参考**: [QUICKSTART.md](file:///C:/projects/BizTools4Openclaw/QUICKSTART.md)、[docs/DEPLOY_GUIDE.md](file:///C:/projects/BizTools4Openclaw/docs/DEPLOY_GUIDE.md)

### P3 Web 管理后台操作手册（约 15 页）

内容清单：
- **3.1 权限体系**：4 角色（super_admin/ops/compliance/sales）权限矩阵
- **3.2 登录/登出/会话管理**
- **3.3 首页看板**：6 阶段数据概览、关键 KPI、异常指标
- **3.4 采集阶段管理**：爬虫任务列表、新建任务、执行监控、结果查看
- **3.5 清洗与结构化**：商机列表、字段浏览、手动分级、批量编辑
- **3.6 合规校验**：规则配置、违规数据池、审核操作
- **3.7 客户触达**：渠道配置、模板管理、发送任务、发送结果统计
- **3.8 销售闭环**：商机分配、跟进记录、状态流转、漏斗统计
- **3.9 异常数据池**：异常类型分类、批量处理、状态回写
- **3.10 渠道账号/采集方案/审计日志**：运营级页面操作指南
- **3.11 可视化采集编辑器**（T25/T26/T27）：页面点选、字段映射、分页配置、PDF 识别

**本节参考**: [docs/WEB_ADMIN_OPERATION_MANUAL.md](file:///C:/projects/BizTools4Openclaw/docs/WEB_ADMIN_OPERATION_MANUAL.md)、[docs/CUSTOM_CRAWL_GUIDE.md](file:///C:/projects/BizTools4Openclaw/docs/CUSTOM_CRAWL_GUIDE.md)

### P4 数据采集模块（约 12 页）

内容清单：
- **4.1 采集能力总览**：
  - 可视化定制采集（T26）：点选配置，规则化执行
  - 全源多平台爬虫（T09）：6 个内置数据源（招投标/短视频/企业新闻/论坛/知乎/本地分类）
- **4.2 可视化采集完整流程**（5 步实操）：
  - 步骤 1：新建采集方案（基础信息+目标网址+执行周期）
  - 步骤 2：页面点选字段（列表页字段/详情页字段/附件字段）
  - 步骤 3：配置分页与增量策略（URL 模板/选择器分页/最大页数/去重键）
  - 步骤 4：配置字段映射与清理规则（正则/HTML 清理/类型转换）
  - 步骤 5：手动执行+查看结果
- **4.3 预设字段模板**（T27）：公告/新闻/公示/政务通知模板及适用场景
- **4.4 PDF 附件识别**：PDF 解析（pdf_parser.py）、OCR、PDF 占位块（T29 新增）
- **4.5 全源爬虫（T09）**：6 个数据源的配置方式、使用限制
- **4.6 采集风控**：
  - robots.txt 自动检测与遵守
  - 代理池轮换（ProxyPool）
  - UA 轮换（UserAgentPool）
  - 域名级限流（DomainRateLimiter）
  - 风险检测（反爬虫识别）
- **4.7 采集任务监控与告警**：任务状态、失败重试、异常告警

**本节参考**: [business/data_clean/channels/aiqicha_client.py](file:///C:/projects/BizTools4Openclaw/business/data_clean/channels/aiqicha_client.py)、[core/spider_core/sdk.py](file:///C:/projects/BizTools4Openclaw/core/spider_core/sdk.py)、[docs/CUSTOM_CRAWL_GUIDE.md](file:///C:/projects/BizTools4Openclaw/docs/CUSTOM_CRAWL_GUIDE.md)

### P5 数据清洗流水线（T10 + T29，约 10 页）

内容清单：
- **5.1 清洗流水线概览**：7 步处理流程图（load → filter → extract → compliance → engine → normalize → storage）
- **5.2 实体抽取**（EntityExtractor）：
  - 识别内容：企业名称、电话、微信号、行业标签、预算范围
  - 准确率说明与边界条件
- **5.3 数据合规**（ComplianceStep）：PII 脱敏、敏感词检测
- **5.4 引擎打分**（EngineStep）：商机评分规则、置信度计算
- **5.5 标准化**（Normalizer）：字段类型统一、空值处理
- **5.6 T29 企业信息自动补全**（新功能）：
  - 补全流程图：无联系方式的商机 → 爱企查查询 → 填充电话/邮箱/地址 → 回写
  - 触发条件：`run_enterprise_enrich=true` + 企业名称非空 + 无联系方式
  - 关键配置：`ENRICH_MODE=async/sync`、`ENRICH_ACCOUNT_DAILY_LIMIT`
  - 缓存策略：7 天企业画像缓存，24 小时查无结果冷却
  - 注意事项：不覆盖已有联系方式、仅填充空字段、查询间隔防止封禁
- **5.7 数据存储**：structured_opportunity 表结构、主要字段说明
- **5.8 异常数据池**：异常类型（脏数据/查无企业/补全失败等）、处理流程

**本节参考**: [business/data_clean/pipeline.py](file:///C:/projects/BizTools4Openclaw/business/data_clean/pipeline.py)、[business/data_clean/enterprise_enrich.py](file:///C:/projects/BizTools4Openclaw/business/data_clean/enterprise_enrich.py)

### P6 多渠道客户触达（T11，约 8 页）

内容清单：
- **6.1 触达流程总览**：商机数据 → 模板渲染 → 渠道分发 → 结果统计
- **6.2 4 大渠道配置**：
  - 邮件 (EmailChannel)：SMTP 服务器/发件人配置、模板示例
  - 飞书 (FeishuChannel)：Webhook / Bot Token、卡片消息模板
  - 企业微信 (WechatChannel)：应用配置、消息模板
  - H5 落地页 (H5LandingPage)：页面生成、短链、访问统计
- **6.3 消息模板引擎**（template_engine.py）：变量占位符、条件渲染
- **6.4 发送风控**：
  - 单账号日发送上限
  - 内容风险检测（敏感词/链接检测）
  - 发送间隔与反封机制
  - 失败重试与熔断
- **6.5 发送任务管理**：任务创建、队列状态、发送统计

### P7 销售自动化（T12，约 8 页）

内容清单：
- **7.1 销售闭环流程图**：商机入库 → 分配 → 跟进 → 转化 → 成交/流失
- **7.2 自动分配引擎**（AssignmentEngine）：
  - 轮询分配、按区域分配、按能力匹配
  - 手动重新分配与批量分配
- **7.3 跟进提醒引擎**（ReminderEngine）：
  - 首次跟进提醒（24 小时内）
  - 定期跟进提醒（7 天/30 天）
  - 逾期提醒与升级告警
- **7.4 销售漏斗统计**（FunnelEngine）：
  - 5 阶段漏斗：新商机 → 已触达 → 有回应 → 已报价 → 已成交
  - 转化率与周期统计
- **7.5 状态流转规则**（StatusEngine）：自定义状态机

### P8 OpenClaw 适配 API 参考（T13，约 10 页）

内容清单：
- **8.1 OpenClaw 对接架构**：Tool Registry + Task Router + 异步回调
- **8.2 统一响应格式**：`{code, msg, data, timestamp}`
- **8.3 API 分组与列表**（按 router 划分）：
  - 工具注册与查询（`/api/v1/tools/*`）
  - 爬虫任务（`/api/v1/spider/*`）
  - 数据清洗与商机（`/api/v1/clean/*`）
  - 销售任务（`/api/v1/sales/*`）
  - 客户触达（`/api/v1/send/*`）
  - 任务状态管理（`/api/v1/tasks/*`）
- **8.4 关键 API 详解**（每个 API 包含：请求方法/路径/请求示例/响应示例/字段说明）
- **8.5 认证与鉴权**：API Key / Token（在 `.env` 中配置）
- **8.6 与 OpenClaw 智能体联调**：编排示例、异步任务回调机制

**本节参考**: [adapter/v1/](file:///C:/projects/BizTools4Openclaw/adapter/v1/)、[adapter/main.py](file:///C:/projects/BizTools4Openclaw/adapter/main.py)

### P9 完整配置参考（约 8 页）

内容清单：
- **9.1 .env 全字段速查表**（按类别分组，30+ 配置项）：
  - 基础环境（ENV/DEBUG/LOG_LEVEL）
  - 数据库（DB_BACKEND/DB_SQLITE_PATH/PostgreSQL 各字段）
  - 加密密钥（DB_ENCRYPTION_KEY — 必须 32+ 字符）
  - Redis（QUEUE_REDIS_HOST/PORT/DB）
  - 应用服务（ADAPTER_HOST/PORT/BASE_URL）
  - Web 管理后台（WEB_ADMIN_ENABLED/WEB_ADMIN_SECRET_KEY）
  - 代理配置（HTTP_PROXY/HTTPS_PROXY）
  - T29 企业信息补全相关（ENRICH_* 系列）
- **9.2 典型配置场景示例**：
  - 场景 A：单机最小化（SQLite + 内存 Redis stub）
  - 场景 B：生产环境（PostgreSQL + 真实 Redis + 多代理）
  - 场景 C：开发调试（DEBUG=true + 详细日志）
- **9.3 配置安全注意事项**：绝不提交 .env 到版本控制、密钥定期轮换

**本节参考**: [.env.example](file:///C:/projects/BizTools4Openclaw/.env.example)、[configs/settings.py](file:///C:/projects/BizTools4Openclaw/configs/settings.py)

### P10 故障排查与 FAQ（约 8 页）

内容清单：
- **10.1 部署相关问题**：
  - Q: Python 版本不对如何处理？
  - Q: Docker 启动失败，端口被占用？
  - Q: 数据库初始化失败？
  - Q: Redis 不可用怎么办？（降级内存 stub）
- **10.2 采集相关问题**：
  - Q: 爬虫任务一直 pending/不执行？
  - Q: 抓取结果为空白？（可能被反爬或 JS 渲染）
  - Q: 如何启用 Playwright 渲染？
  - Q: 代理配置但无法连接？
- **10.3 清洗相关问题**：
  - Q: 企业信息补全（T29）无结果？
  - Q: 电话/微信号识别不准？
  - Q: 商机未打分或分值异常？
- **10.4 触达相关问题**：
  - Q: 邮件发送失败？
  - Q: 飞书机器人消息无响应？
  - Q: 发送被限制/封禁？
- **10.5 管理后台问题**：
  - Q: 登录失败/会话超时？
  - Q: 页面显示空数据？
  - Q: 角色权限不足怎么办？
- **10.6 日志查看路径**：各个模块的日志文件位置、级别调整方法

### P11 开发者扩展手册（约 6 页）

内容清单：
- **11.1 四层分层速查**：各层职责边界与跨层调用规则（DEVELOP_RULES.md §1）
- **11.2 新增业务模块模板**：
  - 创建目录 `business/<模块名>/`
  - 必须文件：`models.py`、`pipeline.py`、`storage.py`、`registry.py`、`_orm.py`
  - 注册 API：在 `adapter/v1/` 添加路由，在 `web_admin/` 添加页面
- **11.3 扩展新采集源**（继承 `SourceBase` 模板）
- **11.4 扩展新触达渠道**（实现 `ChannelBase` 接口）
- **11.5 编码规范与静态检查**：PEP8、类型注解、测试覆盖率要求
- **11.6 测试编写指南**：pytest 结构、mock 模式、集成测试

**本节参考**: [DEVELOP_RULES.md](file:///C:/projects/BizTools4Openclaw/DEVELOP_RULES.md)、[tests/](file:///C:/projects/BizTools4Openclaw/tests/)

### P12 附录（约 3 页）

内容清单：
- **A.1 端口表**：8000 (API) / 8080 (Web Admin) / 5432 (PostgreSQL) / 6379 (Redis)
- **A.2 核心数据模型**：EntityExtract / StructuredOpportunity / AnomalyRecord 字段表
- **A.3 任务状态流转图**：pending → running → success/failed → retry
- **A.4 日志级别与文件列表**：各模块日志文件位置与级别
- **A.5 文档索引**：README/QUICKSTART/DEPLOY_GUIDE/各章节的链接

---

## 三、编写方法与规范

### 3.1 统一格式

- **文件格式**：Markdown（GFM，支持表格、代码块、任务列表、HTML 标签）
- **标题层级**：`#` 顶级 → `##` 章节 → `###` 小节 → `####` 细节（最多 4 级）
- **代码块**：`bash` / `python` / `json` / `text` 四种语言标签必须标注
- **表格**：至少包含标题行，对齐方式采用 `:---` / `:---:` / `---:`
- **交叉引用**：文中引用的文件/函数必须使用超链接（`[文件名](相对路径)`）

### 3.2 章节模板（每章至少包含）

```markdown
## P{n} 章节标题

> **适用角色**: [角色标签] | **预估阅读时间**: X 分钟

### {n}.1 本章任务清单

- [ ] 任务 1：具体操作目标
- [ ] 任务 2：具体操作目标
- [ ] 任务 3：具体操作目标

### {n}.2 概念与原理

（简要说明这一模块解决什么问题，流程如何）

### {n}.3 操作步骤

（分步骤图文说明，包含界面截图位置标记）

### {n}.4 配置与参数速查

| 配置项 | 默认值 | 必填 | 说明 |
|--------|--------|------|------|
| ... | ... | ... | ... |

### {n}.5 常见错误与解决

| 错误现象 | 原因 | 解决方法 |
|---------|------|---------|
| ... | ... | ... |

### {n}.6 参考

- 相关源码：`/path/to/file.py`
- 相关文档：`docs/xxx.md`
- 相关 API：`GET /api/v1/xxx`
```

### 3.3 截图与示例数据约定

- **截图**：实际开发时由开发者补充；本计划中以 `[截图位置：管理后台登录页 /]` 形式占位
- **示例数据**：使用虚构的企业名称/联系方式（示例：杭州示例科技有限公司 / 13800000000 / contact@example.com）
- **JSON 示例**：最小有效示例，省略默认值的空字段

### 3.4 术语表

| 术语 | 英文 | 含义 |
|------|------|------|
| 商机 | Opportunity/Lead | 结构化后待触达的业务线索 |
| 清洗 | Clean/Extract | 从原始文本提取结构化信息 |
| 实体抽取 | Entity Extraction | 识别企业/电话/邮箱等关键实体 |
| PII | Personally Identifiable Information | 个人可识别信息（需脱敏） |
| Playwright 渲染 | Render with Playwright | 使用 headless Chromium 执行 JS 渲染页面 |
| 企业信息补全 | Enterprise Enrichment | 自动查询并补全企业联系方式 |
| 漏斗 | Funnel | 销售阶段转化率统计 |

---

## 四、编写任务拆解与预期规模

| 章节 | 预估页数 | 主要内容 | 依赖 |
|------|---------|---------|------|
| P1 项目概述 | 5 | 架构图、能力、版本 | README.md |
| P2 快速入门 | 8 | 3 种部署、首步操作 | QUICKSTART.md、DEPLOY_GUIDE.md |
| P3 管理后台 | 15 | 4 角色、10 个模块的操作 | WEB_ADMIN_OPERATION_MANUAL.md |
| P4 数据采集 | 12 | 可视化配置、全源爬虫、风控 | CUSTOM_CRAWL_GUIDE.md、core/spider_core/ |
| P5 数据清洗 | 10 | 7 步流水线、T29 企业补全 | business/data_clean/、enterprise_models.py |
| P6 多渠道触达 | 8 | 4 大渠道、模板引擎、风控 | business/customer_send/ |
| P7 销售自动化 | 8 | 分配引擎、漏斗、状态流转 | business/sales_task/ |
| P8 OpenClaw API | 10 | 工具注册、各模块 API、认证 | adapter/v1/ |
| P9 配置参考 | 8 | .env 全字段、3 场景示例 | .env.example、configs/settings.py |
| P10 FAQ | 8 | 5 大分类、~30 个问题 | 来自测试/使用中的问题 |
| P11 开发者扩展 | 6 | 分层规则、新模块模板、测试 | DEVELOP_RULES.md、tests/ |
| P12 附录 | 3 | 端口、数据模型、日志 | |
| **合计** | **~100** | | |

---

## 五、质量保证清单（交付前自检）

- [ ] 所有文件路径/API 路径以 `[file.ext](相对路径)` 形式引用，可点击跳转
- [ ] 所有 .env 配置项与实际代码中的 `settings.py` 字段对齐
- [ ] 所有代码示例可直接复制运行（示例数据非真实密钥）
- [ ] 各角色权限描述与 `web_admin/auth.py` 权限定义一致
- [ ] T29 企业补全功能的触发条件与代码逻辑一致
- [ ] FAQ 至少覆盖 30 个真实常见问题
- [ ] Windows / Linux / macOS 三平台命令各有对应示例

---

## 六、交付物

| 项目 | 说明 |
|------|------|
| 主文档 | `docs/PROJECT_USAGE_MANUAL.md`（单一文件，100 页） |
| 附录 | 内嵌于主文档末尾（P12） |
| 相关文档 | 不修改现有 README/QUICKSTART/DEVELOP_RULES，仅在新文档中引用 |
| 版本标记 | 页眉标注 `v1.0 (T29)` 与发布日期 |

---

**计划审批状态**：待审批  
**审批通过后启动**：按 P1-P12 顺序编写，预估 2-3 天完成
