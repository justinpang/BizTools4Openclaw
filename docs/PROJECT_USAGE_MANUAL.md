# BizTools4Openclaw — 项目使用手册

> **文档版本**: v1.0 (T29) | **最后更新**: 2026-03-18  
> **适用角色**: 运维人员 / 销售 / 合规人员 / 系统管理员 / 开发者  
> **阅读方式**: 可按角色跳过不相关章节，每章开头有「适用角色」标识  
> **关联文件**: [README.md](../README.md) | [DEVELOP_RULES.md](../DEVELOP_RULES.md) | [.env.example](../.env.example)

---

---

## 第一部分：快速上手

---

### P1 项目概述与架构

> **适用角色**: 所有角色 | **阅读时间**: 5 分钟

#### 1.1 项目定位

**BizTools4Openclaw** 是一款专为 OpenClaw 智能体打造的商机自动化工具集，覆盖完整业务链路：

```
全网商机抓取 → 结构化数据清洗 → 多渠道客户触达 → 销售闭环跟进
          ↓                ↓                ↓                ↓
      多源爬虫(T09)    清洗流水线(T10)   触达引擎(T11)    销售调度(T12)
                              ↓
                       企业信息自动补全(T29) ← 新功能
```

#### 1.2 六大核心能力

| 模块 | 能力说明 | 典型使用场景 |
|------|---------|------------|
| 全源多平台爬虫 | 招投标/短视频/企业新闻/论坛/知乎/本地分类等 6 大数据源 | 每日自动抓取商机线索 |
| 智能数据清洗 | 实体抽取 / 脱敏 / 去重 / 打分 / 企业补全 | 原始数据 → 标准化商机 |
| 多渠道自动化触达 | 邮件 / 飞书 / 企业微信 / H5 落地页 | 批量发送营销/跟进消息 |
| 销售流程自动化 | 商机自动分配 / 跟进提醒 / 转化漏斗统计 | 销售团队日常管理 |
| OpenClaw 原生适配 | 标准工具注册 / API 调度 / 异步回调 | AI 智能体编排调用 |
| 全链路合规保障 | PII 脱敏 / 隐私加密 / 爬虫合规 / 消息风控 | 符合监管要求 |

#### 1.3 四层分层架构

```
┌────────────────────────── L4 接入展示层 ──────────────────────────┐
│  adapter/ (FastAPI 网关)        web_admin/ (可视化运维后台)       │
│  - tool_registry.py              - 登录/看板/爬虫/商机/渠道/销售  │
│  - tools_router.py               - 审计日志                        │
│  - task_router.py                                                │
├────────────────────────── L3 业务模块层 ──────────────────────────┤
│  business/multi_spider/    business/data_clean/     (新) T29      │
│  全源爬虫 T09              清洗流水线 T10         企业信息补全    │
│                                                                   │
│  business/customer_send/   business/sales_task/                   │
│  多渠道触达 T11            销售自动化 T12                         │
├────────────────────────── L2 通用能力层 ──────────────────────────┤
│  core/spider_core/         core/data_core/      core/send_core/   │
│  爬虫 SDK(T05)            去重合并打分(T07)   消息风控底座(T08)   │
│                                                                   │
│  core/compliance/                                                 │
│  数据合规/脱敏/敏感词检测(T04+T06)                               │
├────────────────────────── L1 基础基建层 ──────────────────────────┤
│  infra/ (日志 / 异常 / 告警 / Redis 队列 / 定时调度 / ORM 数据库) │
└────────────────────────────────────────────────────────────────────┘
          ↑ 上层依赖下层，禁止反向依赖；同层通过 registry.py 解耦调用 ↑
```

**关键设计原则**：
- **分层清晰**：每层职责单一，跨层调用严格受控
- **模块可插拔**：`business/*` 各业务模块互不直接依赖
- **配置外部化**：所有密钥/阈值/开关全部在 `.env` 中配置
- **零构建链前端**：Web 管理后台使用纯 HTML + CSS + 原生 JS，降低部署复杂度

#### 1.4 技术栈一览

| 领域 | 技术选型 | 版本要求 |
|------|---------|---------|
| **后端语言** | Python + Pydantic v2 | 3.10+（推荐 3.11） |
| **Web 框架** | FastAPI | 0.100+ |
| **数据库** | SQLAlchemy 2.0 + SQLite 或 PostgreSQL | SQLite 零配置 / PG 推荐生产 |
| **缓存队列** | Redis + 连接池（无 Redis 自动降级） | ≥ 5.0 |
| **爬虫引擎** | Playwright / Requests 双通道 | 动态页面需 Playwright |
| **定时调度** | APScheduler + Redis 异步队列 | Cron / Interval / Date |
| **前端** | 纯 HTML + CSS + 原生 JavaScript（无 npm） | 所有现代浏览器 |
| **日志** | 多文件轮转 + 控制台 + JSON 结构化日志 | |
| **测试** | pytest + 单元测试按任务拆分 | |

#### 1.5 版本信息

| 任务编号 | 功能模块 | 状态 |
|---------|---------|------|
| T01 | 项目初始化 | ✅ |
| T02 | 基础基建层（日志/异常/数据库） | ✅ |
| T03-T04 | 数据合规 + 隐私保护 | ✅ |
| T05 | 爬虫核心 SDK | ✅ |
| T06 | 敏感词检测 / 数据生命周期 | ✅ |
| T07 | 商机去重合并打分引擎 | ✅ |
| T08 | 多渠道消息风控底座 | ✅ |
| T09 | 全源多平台爬虫 | ✅ |
| T10 | 数据清洗流水线 | ✅ |
| T11 | 多渠道客户触达 | ✅ |
| T12 | 销售商机调度与闭环 | ✅ |
| T13 | OpenClaw 适配网关 API | ✅ |
| T14 | Web 可视化管理后台 | ✅ |
| T15 | 核心文档与项目说明 | ✅ |
| **T29** | **企业信息自动补全（新功能）** | **✅ 新发布** |

---

### P2 快速入门 — 环境部署与首次启动

> **适用角色**: 系统管理员 / 开发者 | **阅读时间**: 10 分钟

#### 2.1 环境准备清单

```
必需：
  ✅ Python 3.10+（推荐 3.11）
  ✅ Git（克隆代码）

强烈推荐（生产环境必需）：
  🔸 Redis ≥ 5.0（异步队列、会话共享、定时任务持久化）
  🔸 PostgreSQL 或 MySQL（替代 SQLite，并发性能更佳）

可选：
  🔹 Docker + Docker Compose（容器化部署）
  🔹 Playwright 浏览器驱动（动态页面爬虫）
  🔹 SMTP 邮件服务器 / 飞书机器人 Webhook
```

#### 2.2 三种部署方式

##### 方式 A：本地开发部署（推荐入门）

适合初次体验、功能调试。优点：零配置，代码热更新。

```bash
# Step 1: 克隆项目
git clone https://github.com/your-org/BizTools4Openclaw.git
cd BizTools4Openclaw

# Step 2: 创建并激活虚拟环境（推荐）
# Windows (PowerShell):
python -m venv venv
.\venv\Scripts\Activate.ps1

# macOS / Linux:
python3 -m venv venv
source venv/bin/activate

# Step 3: 安装依赖
pip install -r requirements.txt

# Step 4: 配置环境变量（复制模板）
# Windows PowerShell:
Copy-Item .env.example .env

# Windows CMD:
copy .env.example .env

# macOS / Linux:
cp .env.example .env

# Step 5: 修改 .env（必须至少改 DB_ENCRYPTION_KEY）
# 见 P9 配置参考

# Step 6: 启动服务
python -m adapter.main
```

**预期启动日志**：
```
INFO | openclaw.app | BizTools4Openclaw started on http://0.0.0.0:8000
INFO | web_admin.main | web_admin mounted: /admin/* and /api/admin/*
```

##### 方式 B：Docker 单机部署（推荐生产）

待补充的 docker-compose.yml 骨架（根据项目文档实际内容）：

```yaml
# docker-compose.yml（示例，按需调整端口/卷）
version: '3.8'

services:
  biztools-app:
    build: .
    container_name: biztools-app
    ports:
      - "8000:8000"
      - "8080:8080"
    environment:
      - ENV=prod
      - DEBUG=false
      - DB_ENCRYPTION_KEY=your-32-char-minimum-key!!
      - DB_BACKEND=postgres
      - DB_HOST=postgres
      - QUEUE_REDIS_HOST=redis
    depends_on:
      - postgres
      - redis
    volumes:
      - ./logs:/app/logs
      - ./data:/app/data
    restart: unless-stopped

  postgres:
    image: postgres:15-alpine
    container_name: biztools-postgres
    environment:
      POSTGRES_DB: biztools
      POSTGRES_USER: postgres
      POSTGRES_PASSWORD: change-me
    volumes:
      - postgres_data:/var/lib/postgresql/data
    restart: unless-stopped

  redis:
    image: redis:7-alpine
    container_name: biztools-redis
    command: redis-server --appendonly yes
    volumes:
      - redis_data:/data
    restart: unless-stopped

volumes:
  postgres_data:
  redis_data:
```

启动命令：
```bash
docker-compose up -d
docker-compose logs -f biztools-app    # 查看日志
```

##### 方式 C：Windows 一键脚本（简单部署）

```powershell
# 在项目根目录执行
# start_win.ps1
python -m venv venv
.\venv\Scripts\Activate.ps1
pip install -r requirements.txt
Copy-Item .env.example .env -Force
python -m adapter.main
```

#### 2.3 访问入口一览

| 服务 | 地址 | 说明 |
|------|------|------|
| **Web 管理后台** | http://localhost:8080/admin | 账号/密码见 `.env` 中 `WEB_ADMIN_USERNAME` |
| **OpenClaw API 文档 (Swagger)** | http://localhost:8000/docs | 交互式 API 调试 |
| **OpenClaw API 文档 (ReDoc)** | http://localhost:8000/redoc | 备用文档视图 |
| **健康检查** | http://localhost:8000/health | JSON: `{"code":0,"msg":"success",...}` |

#### 2.4 首次启动自检清单

```
□ 启动后无 ERROR 级别日志
□ http://localhost:8000/health 返回 {"code":0,"msg":"success"}
□ http://localhost:8080/admin 可正常打开登录页
□ 使用默认账号（admin / 在 .env 中设置的密码）可登录后台
□ 看板页面正常显示（无数据为预期，后续任务完成后自动填充）
□ 数据库文件（data.db 或 PostgreSQL 表）自动创建成功
```

---

## 第二部分：Web 管理后台操作

---

### P3 Web 管理后台 — 可视化运维手册

> **适用角色**: 运维 / 销售 / 合规 / 管理员 | **阅读时间**: 15 分钟

#### 3.1 四级权限体系

| 角色 | 英文标识 | 权限范围 | 典型人员 |
|------|---------|---------|---------|
| 超级管理员 | `super_admin` | 全功能 + 账号管理 + 审计日志 | 系统负责人 |
| 运营人员 | `ops` | 爬虫任务 + 商机管理 + 渠道账号 | 数据运营人员 |
| 销售人员 | `sales` | 商机列表 + 销售看板 + 跟进操作 | 销售团队成员 |
| 合规人员 | `compliance` | 合规规则 + 违规数据池 + 审计 | 合规/法务人员 |

**多账号配置方式**（`.env`）：

```bash
# 方式 1：单账号（向后兼容，password_plain 自动哈希后不持久化）
WEB_ADMIN_USERNAME=admin
WEB_ADMIN_PASSWORD_PLAIN=ChangeMe123

# 方式 2：多账号（推荐）— JSON 数组格式
WEB_ADMIN_ACCOUNTS_JSON=[
    {"username":"admin","role":"super_admin","password_plain":"ChangeMe123"},
    {"username":"ops_01","role":"ops","password_plain":"ChangeMe123"},
    {"username":"sales_zhang","role":"sales","password_plain":"ChangeMe123"},
    {"username":"compliance_01","role":"compliance","password_plain":"ChangeMe123"}
]
```

#### 3.2 登录与会话管理

- 登录地址：`http://localhost:8080/admin`
- 会话时长：默认 8 小时（`WEB_ADMIN_SESSION_TTL_SECONDS`）
- 多实例部署：需 Redis 支持会话共享
- 忘记密码：修改 `.env` 中的账号信息后重启服务

#### 3.3 首页数据看板

看板包含以下关键指标：

| 指标卡片 | 含义 | 刷新频率 |
|---------|------|---------|
| 总商机数 | 数据库中全部结构化商机数 | 实时 |
| 今日新增 | 今日清洗入库的商机关数 | 实时 |
| 高价值商机 | 评分 ≥ 60 分的商机数 | 实时 |
| 待触达 | 已入库但未发送的商机数 | 实时 |
| 已触达 | 已发送触达消息的商机数 | 实时 |
| 转化率 | 已成交 / 总商机数 | 每日刷新 |
| 异常数据 | 待人工处理的异常条数 | 实时 |

**销售漏斗图表**（5 层）：

```
新商机 → 已触达 → 有回应 → 已报价 → 已成交
```

#### 3.4 爬虫任务管理

操作路径：`后台首页 → 左侧菜单「爬虫任务」`

| 操作 | 说明 | 角色权限 |
|------|------|---------|
| 新建任务 | 选择数据源 + 设置抓取参数 + 配置周期 | ops / super_admin |
| 立即执行 | 手动触发某任务立即运行一次 | ops / super_admin |
| 暂停/恢复 | 控制定时任务启停 | ops / super_admin |
| 查看日志 | 查看抓取结果、异常、耗时、命中率 | 所有登录用户 |
| 查看原始数据 | 浏览抓取到的原始内容（已脱敏） | 所有登录用户 |

**新建爬虫任务向导**：

```
Step 1: 选择数据源（6 大内置源 + 自定义 URL）
Step 2: 输入种子 URL 或搜索关键词
Step 3: 设置最大抓取页数 / 条目数
Step 4: 配置周期（不选则为一次性任务）
  - Cron 表达式：例如 "0 0 2 * * ?"（每日凌晨 2 点）
  - Interval 分钟数：例如每 60 分钟执行一次
Step 5: 启用/禁用代理、JS 渲染
Step 6: 保存并启动
```

#### 3.5 数据清洗与商机管理

操作路径：`后台首页 → 左侧菜单「商机线索」`

**商机列表字段**：

| 字段 | 说明 | 示例 |
|------|------|------|
| 企业名称 | 实体抽取识别的公司名 | 杭州示例科技有限公司 |
| 联系方式 | 电话/邮箱/微信（脱敏展示） | 138****1234 / c***@example.com |
| 商机评分 | 0-100 分，越高越有价值 | 75 |
| 行业分类 | IT / 制造业 / 教育 等 | IT |
| 所在地区 | 北京 / 上海 / 杭州 等 | 杭州 |
| 数据来源 | 招投标 / 知乎 / 自定义爬虫 | bid.gov.cn |
| 录入时间 | 首次入库的时间戳 | 2026-03-18 10:32:15 |
| 状态 | 新商机 / 已触达 / 已分配 / 已成交 | 新商机 |
| 补全标识 | T29 企业信息自动补全状态（见 P5） | ✅ 已补全 / ⏳ 待补全 |

**批量操作**：
- 批量分配给销售
- 批量发送触达消息
- 批量加入黑名单（低质量/重复数据）
- 导出为 CSV / JSON

#### 3.6 合规校验

操作路径：`后台首页 → 左侧菜单「合规校验」`

- **规则配置**：敏感词库、PII 字段选择、违规阈值
- **违规数据池**：自动识别的高风险数据列表，需人工审核
- **审核操作**：
  - `通过`（无问题）
  - `修正后通过`（修改某些字段）
  - `标记删除`（数据违规，不参与触达）

#### 3.7 客户触达管理

操作路径：`后台首页 → 左侧菜单「客户触达」`

- **渠道账号配置**：邮件 SMTP / 飞书 Webhook / 企业微信应用
- **消息模板**：HTML 邮件模板、飞书卡片模板、微信图文模板
- **发送任务**：新建群发任务、选择商机筛选条件、选择渠道+模板
- **发送结果统计**：发送量 / 成功率 / 失败原因分布 / 封禁检测

#### 3.8 销售闭环管理

操作路径：`后台首页 → 左侧菜单「销售管理」`

- **销售人员配置**：姓名 / 负责行业 / 负责地区 / 联系方式
- **商机分配**：
  - 自动分配：按行业 / 地区 / 评分加权
  - 手动分配：拖拽式分配
- **跟进记录**：每次联系的时间、方式、结果记录
- **状态流转**：新商机 → 联系中 → 意向 → 报价 → 成交/流失
- **逾期告警**：超过设定天数未跟进自动标红 + 推送提醒

#### 3.9 异常数据池

操作路径：`后台首页 → 左侧菜单「异常数据池」`

- **异常类型**：
  - 脏数据（文本过短/格式错误）
  - 查无对应企业（T29 补全失败）
  - 联系方式疑似无效
  - 与已有记录高度重复
- **处理操作**：
  - 人工修正后重新入库
  - 标记为无效数据
  - 触发 T29 重新补全

#### 3.10 渠道账号管理

操作路径：`后台首页 → 左侧菜单「渠道账号」`

- 邮件账号：SMTP 配置 + 发送额度监控
- 飞书机器人：Webhook URL + 关键词白名单
- 企业微信：应用配置 + 客户群管理
- H5 落地页：模板 + 短链域名

#### 3.11 可视化采集编辑器（T25-T27）

操作路径：`爬虫任务 → 新建可视化采集方案`

**5 步采集方案配置流程**：

```
Step 1: 基础信息
  ├── 方案名称：如「政府采购公告抓取」
  ├── 目标网址：如 https://www.example-gov.cn/bulletin
  └── 执行周期：一次性 / 每日 / 每周

Step 2: 页面点选字段（可视化操作）
  ├── 列表页字段：标题、发布日期、URL（点击页面元素即选）
  ├── 详情页字段：正文、附件、发布单位
  └── 字段类型：文本 / 日期 / 数字 / 附件 PDF

Step 3: 配置分页策略
  ├── URL 模板分页：?page=1, ?page=2 ...
  ├── 选择器分页：点击"下一页"按钮
  ├── 最大页数限制（防止过度抓取）
  └── 增量抓取键（如发布日期，避免重复抓取）

Step 4: 字段映射与清理规则
  ├── 正则提取：从文本中提取电话/邮箱
  ├── HTML 清理：去除 <script> / <style>
  ├── 类型转换：日期格式统一 / 数字格式化
  └── 关联到商机字段：company_name / contact_phone 等

Step 5: 手动测试执行
  ├── 抓取 1-2 页测试数据
  ├── 检查字段提取结果
  ├── 调整选择器/规则
  └── 确认无误后保存并启动
```

**PDF 附件识别说明（T29 支持）**：

- 自动检测链接中的 PDF 附件
- PDF 文本解析提取（`pdf_parser.py`）
- OCR 识别扫描版 PDF（如有配置 Tesseract）
- PDF 内容同样参与 T10 清洗流水线和 T29 企业信息补全

**预设字段模板（T27）**：

| 模板名称 | 适用场景 | 自动识别字段 |
|---------|---------|-------------|
| 公告模板 | 政府采购 / 公司公告 | 标题、日期、正文、附件 |
| 新闻模板 | 企业新闻 / 行业报道 | 标题、发布时间、正文、来源 |
| 政务通知模板 | 政府部门公告 | 发文字号、主送单位、正文 |

---

## 第三部分：核心业务模块

---

### P4 数据采集 — 爬虫模块

> **适用角色**: 运维人员 / 开发者 | **阅读时间**: 12 分钟

#### 4.1 采集能力总览

```
数据源分类：
  ├─ 招投标与政府采购（bid_and_gov.py）
  ├─ 短视频平台（douyin_xhs.py）— 抖音/小红书
  ├─ 企业动态与行业资讯（enterprise_news.py）
  ├─ 本地分类与供需平台（local_classifieds.py）— 58同城/闲鱼
  ├─ 问答平台（zhihu_baiduqa.py）— 知乎/百度知道
  └─ 通用网页爬虫（generic_web.py）— 自定义 URL 抓取

采集方式：
  ├─ 静态 HTML 解析（Requests + BeautifulSoup）
  ├─ 动态 JS 渲染（Playwright headless 浏览器）
  └─ 可视化配置驱动（T25-T27，无需编码）
```

#### 4.2 6 大内置数据源

| 数据源文件 | 覆盖场景 | 典型商机类型 | JS 渲染需求 |
|-----------|---------|-------------|------------|
| `bid_and_gov.py` | 招投标 / 政府采购 | 公开招标信息、采购需求 | 部分需要 |
| `douyin_xhs.py` | 抖音 / 小红书 | 短视频带货线索、内容营销 | ✅ 需要 |
| `enterprise_news.py` | 企业动态 / 行业资讯 | 公司新品发布、行业会议 | 通常不需要 |
| `local_classifieds.py` | 本地分类 / 供需平台 | 同城服务、商家合作 | 通常不需要 |
| `zhihu_baiduqa.py` | 知乎 / 百度知道 | 需求提问、产品推荐 | 部分需要 |
| `generic_web.py` | 通用网页 / 自定义 URL | 公司官网、B2B 平台 | 按需配置 |

#### 4.3 爬虫风控与合规（重要）

**robots.txt 自动检测与遵守**：

- 自动检查目标网站的 `https://example.com/robots.txt`
- 标记 `Disallow` 的路径自动跳过
- 符合 `robots.txt` 是合规爬虫的基础

**代理池轮换**（`ProxyPool`）：

```
配置 .env 中的代理列表：
HTTP_PROXY=http://proxy1:8080,http://proxy2:8080
HTTPS_PROXY=http://proxy1:8080,http://proxy2:8080

运行时行为：
  ├─ 每个请求随机选择一个可用代理
  ├─ 代理失败自动切换
  └─ 失败次数过多的代理自动标记不可用
```

**User-Agent 轮换**（`UserAgentPool`）：

- 内置多套桌面 / 移动端 UA
- 每次请求随机切换，模拟真实用户
- 可在 `.env` 中自定义 UA 列表

**域名级限流**（`DomainRateLimiter`）：

- 每个域名设置最小请求间隔（默认 2-5 秒）
- 防止对单一网站造成过大压力
- 同时降低被封禁风险

**反爬虫检测与降级**：

- 检测到验证码 / 登录墙自动降级
- 连续失败超过阈值自动暂停该源
- 触发告警通知管理员

#### 4.4 Playwright 动态渲染配置

某些网站（如抖音、小红书、富交互页面）必须使用浏览器渲染。

**启用方式**：

```bash
# 1. 安装 Playwright 浏览器（首次使用）
playwright install chromium
# 或使用项目依赖中已包含的版本
python -m playwright install chromium

# 2. 在爬虫任务或配置中启用 JS 渲染
# .env:
SPIDER_DEFAULT_RENDER_JS=true

# 或在单个任务中配置：
# 新建爬虫任务时，在「高级选项」中勾选「启用 JS 渲染」
```

**渲染性能说明**：

| 模式 | 速度 | 内存占用 | 适用场景 |
|------|------|---------|---------|
| 纯 Requests | ⚡ 快速 | 低 | 静态 HTML 网站 |
| Playwright | 🐢 较慢 | 较高 | JS 动态渲染的网站 |

**最佳实践**：仅对确实需要的 URL 启用 Playwright 渲染。

#### 4.5 可视化自定义采集完整操作

操作路径：`爬虫任务 → 新建可视化采集方案`

**配置参数速查表**：

| 参数 | 默认值 | 必填 | 说明 |
|------|--------|------|------|
| 方案名称 | — | ✅ | 便于识别的名称 |
| 目标 URL | — | ✅ | 起始抓取页面 |
| 列表项选择器 | — | ✅ | 每条列表项的 CSS 选择器 |
| 字段映射 | — | ✅ | 字段名 → 子选择器 |
| 分页方式 | 无分页 | 可选 | URL 模板 / 下一页按钮 |
| 最大页数 | 20 | 可选 | 防止过度抓取 |
| 增量键字段 | 无 | 可选 | 去重用字段（如发布日期） |
| JS 渲染 | 关闭 | 可选 | 是否启用 Playwright |
| 使用代理 | 开启 | 可选 | 是否使用代理池 |
| 执行周期 | 一次性 | 可选 | Cron 表达式/间隔分钟 |

#### 4.6 采集任务监控

**任务状态流转**：

```
pending → running → success
               └→ failed → retry (最多 3 次)
```

**监控指标**：

| 指标 | 含义 | 告警阈值 |
|------|------|---------|
| 抓取成功率 | success / total | < 80% 告警 |
| 平均响应时间 | 每个请求的平均耗时 | > 10 秒告警 |
| 异常请求比例 | HTTP 4xx/5xx + 超时 | > 20% 告警 |
| 触发风控次数 | 检测到反爬/验证码次数 | > 5 次告警 |

#### 4.7 常见问题（采集相关）

| 问题 | 原因排查 | 解决方法 |
|------|---------|---------|
| 抓取结果为空 | 可能被反爬，或需 JS 渲染 | 开启 Playwright 渲染 / 更换代理 |
| 任务一直 pending | 任务队列阻塞或 Redis 不可用 | 检查 Redis 连接 / 重启服务 |
| 大量 403/429 错误 | 被目标网站限流 | 增大请求间隔 / 更换代理 / 暂停一段时间 |
| 抓取的文本是乱码 | 编码问题（GBK/UTF-8） | 在采集方案中指定编码 |
| PDF 附件内容未抓取 | PDF 解析未启用 | 检查 Playwright + PDF 解析配置 |

---

### P5 数据清洗 — 商机抽取与企业信息自动补全

> **适用角色**: 运维 / 销售 / 开发者 | **阅读时间**: 15 分钟

#### 5.1 T10 清洗流水线总览

数据从抓取到入库的完整处理链路：

```
原始抓取文本
    ↓
[Step 1] 数据加载（loader.py）
    ├─ 从爬虫存储中读取原始数据
    └─ 基础格式标准化（HTML 清理、编码统一）
    ↓
[Step 2] 无效数据过滤（filters.py）
    ├─ 过短文本（< 30 字符）丢弃
    ├─ 黑名单关键词过滤
    └─ 重复内容检测（hash 去重）
    ↓
[Step 3] 实体抽取（extractor.py）
    ├─ 企业名称识别（公司后缀匹配 + 关键词定位）
    ├─ 电话号码抽取（正则匹配 13/14/15/16/17/18/19 开头 11 位）
    ├─ 微信号/邮箱识别
    ├─ 行业标签推断（关键词库匹配）
    ├─ 预算范围估算（金额关键词匹配）
    └─ 地区识别（省/市关键词）
    ↓
[Step 4] 数据合规（compliance_step.py）
    ├─ PII 字段掩码（手机号 138****1234）
    ├─ 敏感词检测（违规内容标记）
    └─ 隐私字段加密存储（AES-256-GCM）
    ↓
[Step 5] 去重合并打分（engine_step.py → core/data_core）
    ├─ 内容相似度去重（hash + 字段比对）
    ├─ 同一企业多条合并
    └─ 商机评分（行业+时效性+联系方式完整度加权）
    ↓
[Step 6] T29 企业信息自动补全（enterprise_enrich.py）← 新功能
    ├─ 触发条件：企业名称非空 + 无联系方式 + 补全开关开启
    ├─ 查询渠道：爱企查 / 企查查 / 天眼查（默认爱企查）
    ├─ 缓存检查 → 7 天内相同企业直接返回缓存
    ├─ 异步队列执行（不阻塞主流水线）
    └─ 合并策略：仅填充空字段，不覆盖已有信息
    ↓
[Step 7] 标准化与入库（normalizer.py + storage.py）
    ├─ 字段类型统一（日期格式、金额格式）
    ├─ 空值处理（默认值 / 空字符串）
    └─ 写入结构化商机表（structured_opportunity）
```

#### 5.2 商机评分规则（可配置）

| 评分维度 | 权重 | 评分逻辑 |
|---------|------|---------|
| 行业匹配度 | 30% | 命中目标行业关键词加分 |
| 时效性 | 25% | 发布日期越近，分值越高 |
| 联系方式完整度 | 25% | 有电话/邮箱/微信分别加分 |
| 信息可信度 | 20% | 来源平台权威性、数据完整性 |

**评分分级**：

| 分数区间 | 分级 | 建议操作 |
|---------|------|---------|
| 80-100 | ⭐ 高价值 | 优先触达，分配资深销售 |
| 60-79 | ⭐⭐ 中等价值 | 正常触达流程 |
| 40-59 | ⭐ 一般 | 暂缓触达，观察后续信号 |
| 0-39 | 低价值 | 不主动触达，保留为参考 |

#### 5.3 T29 企业信息自动补全（新功能详解）

这是 T29 新上线的核心功能。它解决的问题：**很多商机只有企业名称，没有联系方式，无法直接触达**。

**补全流程图**：

```
商机数据（有企业名称，无联系方式）
        │
        ├─ [检查] 已有联系方式？─→ 是：跳过补全（不覆盖）
        │                          否：继续
        │
        ├─ [检查] 有缓存？─→ 是：直接返回缓存结果
        │                 否：继续
        │
        ├─ [异步执行] 发送到企业信息补全队列
        │               │
        │               └─ worker 拉取任务，调用查询渠道
        │                   ├─ 使用 Playwright 渲染查询页面
        │                   ├─ 解析企业详情页 HTML
        │                   ├─ 提取：电话 / 邮箱 / 地址 / 规模 / 行业 / 注册资本
        │                   ├─ 写入缓存（7 天有效）
        │                   └─ 返回标准化 EnterpriseProfile
        │
        └─ [合并] 仅填充空字段
               不覆盖已有联系方式
               记录补全来源与时间戳
               标记 enriched=true
        │
        └─ 更新：结构化商机 enriched 字段
```

**标准化企业画像（EnterpriseProfile）字段**：

| 字段 | 说明 | 示例 |
|------|------|------|
| `company_name` | 原始查询的企业名称 | 阿里云计算有限公司 |
| `matched_name` | 渠道返回的实际匹配名称 | 阿里云计算有限公司 |
| `contact_person` | 联系人 / 法定代表人 | 王某某 |
| `contact_phone` | 联系电话 | 010-12345678 |
| `contact_email` | 企业邮箱 | contact@example.com |
| `registered_address` | 注册地址 | 北京市海淀区... |
| `company_scale` | 企业规模 | 大型 |
| `industry_category` | 行业分类 | 软件和信息技术服务业 |
| `registered_capital` | 注册资本 | 5000 万元人民币 |
| `establishment_date` | 成立日期 | 2009-09-10 |
| `business_status` | 经营状态 | 在营（开业） |
| `confidence_score` | 匹配置信度 | 0.95 |
| `source_channel` | 来源渠道 | aiqicha |

**补全结果状态说明**：

| status 状态 | 含义 | 是否需要人工处理 |
|------------|------|----------------|
| `enriched` | ✅ 成功补全，有联系方式 | 否 |
| `cached` | 📦 命中缓存，直接返回 | 否 |
| `not_found` | 🔍 查无此企业 | 是（`needs_manual_review=true`） |
| `failed` | ❌ 查询失败（网络/反爬） | 是（`needs_manual_review=true`） |
| `skipped` | ⏭️ 跳过（已有联系方式或未启用） | 否 |

#### 5.4 T29 配置参数

配置文件位置：`.env`

| 配置项 | 默认值 | 必填 | 说明 |
|--------|--------|------|------|
| `ENRICH_ENABLED` | `true` | 可选 | 总开关，false 则完全跳过 |
| `ENRICH_CHANNEL` | `aiqicha` | 可选 | 查询渠道：aiqicha / qcc / tianyancha |
| `ENRICH_MODE` | `async` | 可选 | async（异步批量，推荐）/ sync（同步） |
| `ENRICH_INTERVAL_SECONDS` | `5` | 可选 | 两次查询间隔（秒），防止被封禁 |
| `ENRICH_CACHE_ENABLED` | `true` | 可选 | 启用缓存（大幅提升性能） |
| `ENRICH_CACHE_TTL_SECONDS` | `604800` | 可选 | 缓存有效期（7 天 = 604800 秒） |
| `ENRICH_SKIP_IF_CONTACT_EXISTS` | `true` | 可选 | 已有联系方式则跳过（不覆盖） |
| `ENRICH_FILL_EMPTY_ONLY` | `true` | 可选 | 只填充空字段（保护原有数据） |
| `ENRICH_CONSECUTIVE_FAILURE_THRESHOLD` | `5` | 可选 | 连续失败阈值，触发告警 |
| `ENRICH_MASK_IN_LOG` | `true` | 可选 | 日志中自动脱敏手机号/邮箱 |

#### 5.5 数据存储结构

```
结构化商机表（structured_opportunity）主要字段：
  ├─ id / 主键
  ├─ raw_text / 原始文本
  ├─ company_name / 企业名称
  ├─ phone_numbers / 电话号码列表（JSON）
  ├─ email_addresses / 邮箱列表（JSON）
  ├─ wechat_ids / 微信号列表（JSON）
  ├─ industry_tags / 行业标签（JSON）
  ├─ budget_range / 预算范围
  ├─ region / 地区
  ├─ score / 商机评分 (0-100)
  ├─ data_source / 数据来源
  ├─ source_url / 来源 URL
  ├─ enriched / 是否已补全（bool）
  ├─ enrichment_source / 补全来源渠道
  ├─ enrichment_profile / 补全的企业画像（JSON，EnterpriseProfile）
  ├─ opportunity_status / 商机状态
  ├─ sales_assignee / 分配的销售人员
  ├─ last_follow_up_at / 最后跟进时间
  ├─ created_at / 入库时间
  └─ updated_at / 更新时间
```

#### 5.6 异常数据处理流程

```
异常数据池异常类型：
  ├─ DIRTY_DATA：文本过短 / 格式异常 / 无法解析
  ├─ COMPANY_NOT_FOUND：T29 补全查无结果（需人工确认企业名称）
  ├─ ENRICH_FAILED：查询失败（网络/反爬，可重试）
  ├─ INVALID_CONTACT：联系方式疑似无效（格式异常）
  └─ DUPLICATE_HIGH：与已有记录相似度超过 90%

处理操作：
  ├─ 人工修正后重新入库
  ├─ 触发 T29 重新补全
  ├─ 标记删除（不参与后续流程）
  └─ 导出为待人工确认清单
```

---

### P6 多渠道客户触达（T11）

> **适用角色**: 销售 / 运维 | **阅读时间**: 8 分钟

#### 6.1 触达流程总览

```
商机筛选（按行业/评分/地区等条件）
      ↓
选择渠道（邮件 / 飞书 / 企业微信 / H5 落地页）
      ↓
选择消息模板（变量占位符自动替换：{{company_name}}, {{contact_person}} 等）
      ↓
发送风控检查
  ├─ 单账号日发送限额检查
  ├─ 内容敏感词检测
  ├─ 接收方是否已在黑名单
  └─ 发送频率冷却（避免对同一企业短时间内多次发送）
      ↓
发送执行（异步队列，支持失败重试）
      ↓
状态回调与统计
```

#### 6.2 4 大渠道配置

| 渠道 | 配置位置 | 必需配置项 | 适用场景 |
|------|---------|-----------|---------|
| **邮件 (Email)** | `.env` + 后台渠道账号页 | SMTP 主机/端口/账号/密码 | B2B 正式沟通、批量营销 |
| **飞书机器人** | `.env` + 后台渠道账号页 | Webhook URL | 团队内通知、群运营 |
| **企业微信** | `.env` + 后台渠道账号页 | 应用配置 + access token | 客户一对一跟进 |
| **H5 落地页** | `.env` 域名配置 | 模板 + 短链域名 | 引流、意向收集 |

**邮件 SMTP 配置示例（`.env`）**：

```bash
CUSTOMER_SEND_EMAIL_ENABLED=true
# SMTP 全局回退配置
CUSTOMER_SEND_SMTP_HOST=smtp.example.com
CUSTOMER_SEND_SMTP_PORT=465
CUSTOMER_SEND_SMTP_USER=notifications@example.com
CUSTOMER_SEND_SMTP_PASSWORD=your-smtp-password
CUSTOMER_SEND_SMTP_USE_SSL=true
CUSTOMER_SEND_SMTP_FROM="BizTools <notifications@example.com>"
```

**飞书机器人配置示例**：

```bash
# 在飞书开放平台创建自定义机器人
# 获取 Webhook URL，格式：https://open.feishu.cn/open-apis/bot/v2/hook/xxxxx
# 在 Web 管理后台「渠道账号 → 飞书机器人」中添加
```

#### 6.3 消息模板引擎（`template_engine.py`）

模板使用 Jinja2 风格变量占位符：

```
邮件模板示例：
─────────────────────────────────────────
尊敬的 {{company_name}} 团队：

您好！我方关注到贵司在 {{industry_category}} 领域的业务动态，
希望与您建立联系。

如贵司有相关需求，欢迎随时回复此邮件或致电 {{contact_phone}}。

最佳商祺，
{{sender_name}}
─────────────────────────────────────────

支持的标准变量：
  {{company_name}}       企业名称
  {{contact_person}}     联系人
  {{industry_category}}  行业分类
  {{region}}             地区
  {{budget_range}}       预算范围
  {{sender_name}}        发送者姓名（配置渠道时设置）
  {{today}}              当前日期
```

#### 6.4 发送风控机制

| 风控规则 | 默认阈值 | 说明 |
|---------|---------|------|
| 单账号日发送上限 | 500 封/账号 | 防止 SMTP 服务商限流 |
| 单接收方频率冷却 | 24 小时 | 24 小时内不对同一企业重复发送 |
| 内容敏感词检测 | 内置词库 | 检测到敏感词阻断发送并记录 |
| 失败熔断 | 连续 10 次失败 | 自动暂停该渠道 30 分钟 |
| 退订/投诉处理 | 自动加入黑名单 | 退订邮件地址不再接收 |

#### 6.5 发送状态流转

```
queued → sending → sent → delivered → opened（邮件特有）
                └→ failed → retry（最多 3 次，指数退避）
                          └→ permanent_failed（超过重试上限）
```

---

### P7 销售自动化（T12）

> **适用角色**: 销售 / 销售管理 | **阅读时间**: 8 分钟

#### 7.1 销售闭环流程图

```
商机入库（T10 清洗完成）
      ↓
自动分配引擎
  ├─ 按行业匹配（优先分配给对应行业销售）
  ├─ 按地区匹配（优先分配给负责该地区的销售）
  ├─ 按评分加权（高价值商机分配给资深销售）
  └─ 负载均衡（避免单个销售负荷过重）
      ↓
首次跟进提醒（24 小时内未操作自动提醒）
      ↓
销售操作
  ├─ 标记联系中 / 有回应 / 已报价 / 已成交 / 已流失
  ├─ 记录跟进内容、方式、时间
  └─ 添加备注、文件附件
      ↓
定期跟进提醒（7 天 / 30 天周期）
      ↓
转化漏斗统计
  └─ 新商机 → 已触达 → 有回应 → 已报价 → 已成交
```

#### 7.2 销售人员配置

在 Web 管理后台 `销售管理 → 销售成员` 添加：

| 字段 | 说明 | 示例 |
|------|------|------|
| 姓名 | 销售人员姓名 | 张经理 |
| 负责行业 | 逗号分隔的行业列表 | IT,金融,制造业 |
| 负责地区 | 逗号分隔的地区列表 | 北京,上海,杭州 |
| 联系方式 | 电话/邮箱 | sales01@example.com |
| 账号绑定 | 关联到后台登录账号 | ops_01 |
| 月商机目标 | 该销售每月处理的商机关标 | 50 |

#### 7.3 商机分配策略（`assignment_engine.py`）

**自动分配权重公式**：

```
分配分数 = (行业匹配权重 × 3) + (地区匹配权重 × 2) + (空闲度 × 1)

选择逻辑：
  1. 计算每个销售对该商机的分配分数
  2. 排除当前负载超过上限的销售
  3. 选择分数最高的销售（同分随机）
  4. 更新该销售的当前负载计数
```

**手动批量分配**：

- 在商机列表中勾选多条
- 点击「批量分配」
- 选择目标销售
- 确认后立即更新分配状态

#### 7.4 跟进提醒机制

| 提醒类型 | 触发条件 | 通知方式 |
|---------|---------|---------|
| 首次跟进提醒 | 分配后 24 小时未操作 | 飞书/邮件/后台站内信 |
| 周期跟进提醒 | 上次跟进后 7 天 / 30 天未更新 | 飞书/邮件/后台站内信 |
| 逾期告警 | 超过设定天数（默认 15 天）无操作 | 通知销售 + 销售主管 |
| 高价值商机未触达 | 评分 ≥ 80 分的商机 48 小时未触达 | 通知销售主管 |

#### 7.5 销售漏斗与转化率统计

**5 层漏斗定义**：

```
第 1 层：新商机（total = 全部入库商机）
    ↓ 触达率
第 2 层：已触达（sent = 已发送触达消息）
    ↓ 回应率
第 3 层：有回应（responded = 收到客户正面回复）
    ↓ 报价率
第 4 层：已报价（quoted = 发送正式报价）
    ↓ 成交率
第 5 层：已成交（closed = 合同签订/付款）
```

**统计维度**：

- 按日 / 周 / 月 / 季度查看
- 按销售个人 / 团队查看
- 按行业 / 地区 / 来源查看
- 各层转化率与趋势图表

---

## 第四部分：OpenClaw 适配与配置

---

### P8 OpenClaw API 参考（T13）

> **适用角色**: 开发者 / OpenClaw 智能体编排人员 | **阅读时间**: 12 分钟

#### 8.1 对接架构

```
OpenClaw 智能体 / Agent
        │
        │ HTTP 请求（Bearer Token / API Key）
        ▼
BizTools4Openclaw FastAPI 网关 (adapter/main.py)
        │
        ├─ /api/v1/tools/*    工具注册表与调用
        ├─ /api/v1/spider/*   爬虫任务相关
        ├─ /api/v1/clean/*    数据清洗与商机相关
        ├─ /api/v1/sales/*    销售任务相关
        ├─ /api/v1/send/*     客户触达相关
        └─ /api/v1/tasks/*    异步任务状态查询
```

#### 8.2 统一响应格式

**所有 API 返回统一 JSON 结构**：

```json
{
  "code": 0,
  "msg": "success",
  "data": { },
  "timestamp": "2026-03-18T10:32:15Z"
}
```

| 字段 | 类型 | 说明 |
|------|------|------|
| `code` | int | 0 = 成功，非 0 = 错误代码 |
| `msg` | string | 成功时为 "success"，失败时为错误描述 |
| `data` | object/array/null | 响应主体（任意结构） |
| `timestamp` | string | ISO 8601 UTC 时间戳 |

**常见错误代码**：

| code | 含义 | HTTP 状态码 |
|------|------|------------|
| 0 | 成功 | 200 / 201 |
| 400 | 请求参数错误 | 400 |
| 401 | 未认证 / Token 无效 | 401 |
| 403 | 无权限 | 403 |
| 404 | 资源不存在 | 404 |
| 429 | 频率超限 / 配额不足 | 429 |
| 500 | 服务器内部错误 | 500 |

#### 8.3 认证方式

**Bearer Token（推荐）**：

```bash
# 在请求头中添加
Authorization: Bearer <your-api-token>

# .env 中配置（逗号分隔，支持多 token）
ADAPTER_API_TOKENS=token-for-agent-1,token-for-agent-2,token-for-agent-3
```

**IP 白名单（可选）**：

```bash
# .env 中配置允许的 IP 列表（逗号分隔）
ADAPTER_IP_WHITELIST=10.0.0.0/24,192.168.1.100
# 留空表示不启用 IP 白名单
```

**调用配额限制**：

```bash
# 单 Agent 每日调用上限（0 = 不限制）
ADAPTER_DAILY_QUOTA_PER_AGENT=1000
```

#### 8.4 核心 API 列表与示例

##### 8.4.1 工具注册与查询

| 方法 | 端点 | 说明 |
|------|------|------|
| GET | `/api/v1/tools` | 列出所有可用工具 |
| GET | `/api/v1/tools/{tool_id}` | 获取工具详情（参数/返回格式） |

**示例：获取工具列表**

```bash
curl -H "Authorization: Bearer <token>" http://localhost:8000/api/v1/tools
```

```json
{
  "code": 0,
  "msg": "success",
  "data": [
    {
      "tool_id": "crawl_opportunity",
      "name": "商机爬虫",
      "description": "按关键词/数据源抓取商机线索",
      "version": "1.0.0"
    },
    {
      "tool_id": "clean_and_enrich",
      "name": "数据清洗与企业补全",
      "description": "执行 T10 清洗 + T29 企业信息自动补全",
      "version": "1.0.0"
    },
    {
      "tool_id": "send_customer_message",
      "name": "客户触达",
      "description": "按渠道发送营销/跟进消息",
      "version": "1.0.0"
    }
  ],
  "timestamp": "2026-03-18T10:32:15Z"
}
```

##### 8.4.2 商机相关 API

| 方法 | 端点 | 说明 |
|------|------|------|
| GET | `/api/v1/opportunities` | 分页查询商机列表 |
| GET | `/api/v1/opportunities/{id}` | 获取单条商机详情 |
| POST | `/api/v1/opportunities` | 手动创建商机 |
| POST | `/api/v1/opportunities/enrich` | 触发企业信息补全 |
| PUT | `/api/v1/opportunities/{id}` | 更新商机信息 |
| DELETE | `/api/v1/opportunities/{id}` | 删除商机 |

**示例：分页查询商机**

```bash
curl -H "Authorization: Bearer <token>" \
  "http://localhost:8000/api/v1/opportunities?min_score=60&industry=IT&page=1&page_size=20"
```

**查询参数**：

| 参数 | 类型 | 默认 | 说明 |
|------|------|------|------|
| `min_score` | int | 0 | 最低商机评分 |
| `industry` | string | — | 行业筛选 |
| `region` | string | — | 地区筛选 |
| `has_contact` | bool | — | 是否必须有联系方式 |
| `enriched` | bool | — | 是否已企业信息补全 |
| `page` | int | 1 | 页码 |
| `page_size` | int | 20 | 每页条数 |

##### 8.4.3 爬虫任务 API

| 方法 | 端点 | 说明 |
|------|------|------|
| GET | `/api/v1/spider/tasks` | 列出爬虫任务 |
| POST | `/api/v1/spider/tasks` | 创建爬虫任务 |
| POST | `/api/v1/spider/tasks/{id}/run` | 立即执行指定任务 |
| GET | `/api/v1/spider/logs/{task_id}` | 查看任务抓取日志 |

**示例：创建自定义爬虫任务**

```bash
curl -X POST -H "Authorization: Bearer <token>" \
  -H "Content-Type: application/json" \
  http://localhost:8000/api/v1/spider/tasks \
  -d '{
    "name": "IT采购公告抓取",
    "source": "bid_and_gov",
    "keywords": ["IT", "采购", "系统集成"],
    "max_pages": 50,
    "schedule": { "type": "cron", "expression": "0 0 2 * * ?" }
  }'
```

##### 8.4.4 客户触达 API

| 方法 | 端点 | 说明 |
|------|------|------|
| POST | `/api/v1/send/email` | 发送邮件 |
| POST | `/api/v1/send/feishu` | 发送飞书消息 |
| POST | `/api/v1/send/wechat` | 发送企业微信消息 |
| POST | `/api/v1/send/batch` | 批量发送（支持渠道+商机筛选） |
| GET | `/api/v1/send/status/{task_id}` | 查询发送任务状态 |

**示例：批量发送邮件**

```bash
curl -X POST -H "Authorization: Bearer <token>" \
  -H "Content-Type: application/json" \
  http://localhost:8000/api/v1/send/batch \
  -d '{
    "channel": "email",
    "template_id": "business_introduction_v1",
    "filters": {
      "min_score": 70,
      "industry": "IT",
      "has_contact": true
    },
    "max_recipients": 100
  }'
```

##### 8.4.5 异步任务状态 API

所有耗时操作（爬虫、批量清洗、批量发送）均为异步执行：

| 方法 | 端点 | 说明 |
|------|------|------|
| GET | `/api/v1/tasks/{task_id}` | 查询任务状态 |
| POST | `/api/v1/tasks/{task_id}/cancel` | 取消任务 |
| POST | `/api/v1/tasks/{task_id}/retry` | 重试失败任务 |
| GET | `/api/v1/tasks/{task_id}/result` | 获取任务执行结果 |

**任务状态定义**：

| status | 说明 |
|--------|------|
| `pending` | 排队中，等待执行 |
| `running` | 执行中 |
| `success` | 执行成功（可获取 result） |
| `failed` | 执行失败（可查看 error_message） |
| `cancelled` | 已被取消 |

**示例：查询异步任务状态**

```bash
curl -H "Authorization: Bearer <token>" \
  http://localhost:8000/api/v1/tasks/task_abc123
```

```json
{
  "code": 0,
  "msg": "success",
  "data": {
    "task_id": "task_abc123",
    "status": "success",
    "progress": 100,
    "total_items": 150,
    "success_count": 148,
    "failed_count": 2,
    "started_at": "2026-03-18T08:00:00Z",
    "finished_at": "2026-03-18T08:12:35Z",
    "duration_seconds": 755,
    "error_message": null
  },
  "timestamp": "2026-03-18T10:32:15Z"
}
```

##### 8.4.6 企业信息补全 API（T29 新功能）

| 方法 | 端点 | 说明 |
|------|------|------|
| POST | `/api/v1/clean/enrich` | 对指定商机触发补全 |
| GET | `/api/v1/clean/enrich/{company_name}` | 查询单个企业补全结果 |
| POST | `/api/v1/clean/enrich/batch` | 批量补全 |

**示例：查询单个企业信息**

```bash
curl -H "Authorization: Bearer <token>" \
  "http://localhost:8000/api/v1/clean/enrich/阿里云计算有限公司"
```

```json
{
  "code": 0,
  "msg": "success",
  "data": {
    "success": true,
    "status": "cached",
    "company_name": "阿里云计算有限公司",
    "profile": {
      "company_name": "阿里云计算有限公司",
      "contact_phone": "010-12345678",
      "contact_email": "contact@example.com",
      "registered_address": "北京市海淀区...",
      "company_scale": "大型",
      "industry_category": "软件和信息技术服务业",
      "registered_capital": "5000万元人民币",
      "confidence_score": 0.95,
      "source_channel": "aiqicha"
    }
  },
  "timestamp": "2026-03-18T10:32:15Z"
}
```

#### 8.5 与 OpenClaw 智能体联调

**典型编排示例**（智能体调用链）：

```
Agent: "查找近 7 天 IT 行业的高价值商机"
  ↓
调用 GET /api/v1/opportunities?min_score=70&industry=IT&days=7
  ↓
返回商机列表
  ↓
Agent: "对没有联系方式的商机自动补全企业信息"
  ↓
调用 POST /api/v1/clean/enrich/batch { opportunity_ids: [...] }
  ↓
异步排队执行
  ↓
轮询 GET /api/v1/tasks/{task_id} 直到完成
  ↓
Agent: "向补全后的所有商机发送介绍邮件"
  ↓
调用 POST /api/v1/send/batch { channel:"email", template_id:"...", filters:{...} }
```

---

### P9 完整配置参考（`.env` 全字段速查）

> **适用角色**: 系统管理员 / 开发者 | **阅读时间**: 10 分钟

#### 9.1 配置文件位置与加载逻辑

```
加载顺序：
  1. 读取项目根目录 .env 文件（不存在则使用默认值）
  2. 环境变量优先（运行时设置的环境变量覆盖 .env）
  3. 启动时打印关键配置（敏感字段已掩码）

修改配置后需重启服务：
  python -m adapter.main
```

**安全提示**：`DB_ENCRYPTION_KEY` 用于敏感字段加密，**一旦设置请勿更改**，否则已加密的数据无法解密。建议备份密钥并存放在安全位置。

#### 9.2 基础环境配置

| 配置项 | 默认值 | 必填 | 说明 |
|--------|--------|------|------|
| `ENV` | `dev` | 可选 | 运行环境：dev / test / prod |
| `DEBUG` | `true` | 可选 | 调试模式，true 时打印详细日志和错误堆栈 |
| `LOG_LEVEL` | `INFO` | 可选 | 日志级别：DEBUG / INFO / WARNING / ERROR |
| `PYTHONUNBUFFERED` | `1` | 可选 | 禁用 Python 输出缓冲，便于日志实时查看 |

#### 9.3 数据库配置

| 配置项 | 默认值 | 必填 | 说明 |
|--------|--------|------|------|
| `DB_BACKEND` | `sqlite` | ✅ | 数据库类型：`sqlite` 或 `postgres` |
| `DB_SQLITE_PATH` | 空 | SQLite | SQLite 数据库文件路径（留空 = :memory: 内存库） |
| `DB_HOST` | `127.0.0.1` | PostgreSQL | PostgreSQL 主机 |
| `DB_PORT` | `5432` | PostgreSQL | PostgreSQL 端口 |
| `DB_NAME` | `biztools` | PostgreSQL | 数据库名 |
| `DB_USER` | `postgres` | PostgreSQL | 数据库用户名 |
| `DB_PASSWORD` | — | PostgreSQL | 数据库密码 |
| `DB_POOL_SIZE` | `10` | PostgreSQL | 连接池大小 |
| `DB_MAX_OVERFLOW` | `20` | PostgreSQL | 连接池最大溢出数 |
| **`DB_ENCRYPTION_KEY`** | — | ✅ | **敏感字段加密密钥（至少 32 字符），务必修改并妥善保存** |

#### 9.4 Redis / 异步任务队列配置

| 配置项 | 默认值 | 必填 | 说明 |
|--------|--------|------|------|
| `QUEUE_REDIS_HOST` | `127.0.0.1` | 可选 | Redis 主机（不可用自动降级为内存 stub） |
| `QUEUE_REDIS_PORT` | `6379` | 可选 | Redis 端口 |
| `QUEUE_REDIS_DB` | `0` | 可选 | Redis DB 编号 |
| `QUEUE_PREFIX` | `openclaw:queue` | 可选 | Redis key 前缀 |
| `QUEUE_WORKER_CONCURRENCY` | `4` | 可选 | 同时执行的异步任务数 |
| `QUEUE_TASK_TIMEOUT` | `300` | 可选 | 单个任务超时时间（秒） |
| `QUEUE_MAX_RETRIES` | `3` | 可选 | 失败自动重试次数 |
| `QUEUE_RETRY_BACKOFF` | `2` | 可选 | 重试指数退避基数（秒） |

#### 9.5 应用服务配置

| 配置项 | 默认值 | 必填 | 说明 |
|--------|--------|------|------|
| `ADAPTER_HOST` | `0.0.0.0` | 可选 | API 网关监听地址 |
| `ADAPTER_PORT` | `8000` | 可选 | API 网关监听端口 |
| `ADAPTER_BASE_URL` | `http://localhost:8000` | 可选 | 对外暴露的基础 URL |
| `ADAPTER_API_TOKENS` | — | 可选 | API 认证 Token（逗号分隔，支持多 Agent） |
| `ADAPTER_DAILY_QUOTA_PER_AGENT` | `1000` | 可选 | 单 Agent 每日调用上限（0 = 不限制） |
| `ADAPTER_IP_WHITELIST` | 空 | 可选 | 允许访问的 IP 列表（逗号分隔；留空不启用） |
| `ADAPTER_AUTO_MASK_PII` | `true` | 可选 | API 出口数据自动脱敏 |

#### 9.6 Web 管理后台配置

| 配置项 | 默认值 | 必填 | 说明 |
|--------|--------|------|------|
| `WEB_ADMIN_ENABLED` | `true` | 可选 | 是否启用后台 |
| `WEB_ADMIN_HOST` | `0.0.0.0` | 可选 | 后台监听地址 |
| `WEB_ADMIN_PORT` | `8080` | 可选 | 后台监听端口 |
| `WEB_ADMIN_SECRET_KEY` | — | ✅ | 会话加密密钥（请修改为随机字符串） |
| `WEB_ADMIN_SESSION_TTL_SECONDS` | `28800` | 可选 | 会话过期时间（8 小时 = 28800 秒） |
| `WEB_ADMIN_PAGE_SIZE` | `20` | 可选 | 列表默认分页条数 |
| `WEB_ADMIN_USERNAME` | `admin` | 单账号模式 | 默认登录账号（多账号模式时由 `WEB_ADMIN_ACCOUNTS_JSON` 覆盖） |
| `WEB_ADMIN_PASSWORD_PLAIN` | — | 单账号模式 | 密码明文（启动时自动哈希，不持久化） |
| `WEB_ADMIN_ACCOUNTS_JSON` | — | 多账号模式 | JSON 数组格式，支持多角色账号（优先级高于单账号配置） |

#### 9.7 代理配置（可选）

| 配置项 | 默认值 | 必填 | 说明 |
|--------|--------|------|------|
| `HTTP_PROXY` | 空 | 可选 | HTTP 代理（逗号分隔多个） |
| `HTTPS_PROXY` | 空 | 可选 | HTTPS 代理（逗号分隔多个） |

#### 9.8 数据清洗相关配置（T10）

| 配置项 | 默认值 | 必填 | 说明 |
|--------|--------|------|------|
| `CLEAN_MIN_TEXT_LEN` | `30` | 可选 | 有效文本最短长度 |
| `CLEAN_INDUSTRY_KEYWORDS` | `IT,制造业,采购,批发,零售,教育,医疗,建筑,金融,物流` | 可选 | 行业关键词库 |
| `CLEAN_REGION_KEYWORDS` | `北京,上海,广州,深圳,杭州,南京,武汉,成都,重庆,西安` | 可选 | 地区关键词库 |

#### 9.9 企业信息补全相关配置（T29）

| 配置项 | 默认值 | 必填 | 说明 |
|--------|--------|------|------|
| `ENRICH_ENABLED` | `true` | 可选 | 企业信息补全总开关 |
| `ENRICH_CHANNEL` | `aiqicha` | 可选 | 查询渠道：aiqicha / qcc / tianyancha |
| `ENRICH_MODE` | `async` | 可选 | async（异步批量，推荐）/ sync（同步） |
| `ENRICH_INTERVAL_SECONDS` | `5` | 可选 | 两次查询间隔（秒），防止被目标网站封禁 |
| `ENRICH_CACHE_ENABLED` | `true` | 可选 | 启用缓存（大幅提升性能） |
| `ENRICH_CACHE_TTL_SECONDS` | `604800` | 可选 | 缓存有效期（7 天 = 604800 秒） |
| `ENRICH_SKIP_IF_CONTACT_EXISTS` | `true` | 可选 | 已有联系方式则跳过（不覆盖已有信息） |
| `ENRICH_FILL_EMPTY_ONLY` | `true` | 可选 | 只填充空字段（保护原有数据完整性） |
| `ENRICH_CONSECUTIVE_FAILURE_THRESHOLD` | `5` | 可选 | 连续失败阈值，触发告警与暂停 |
| `ENRICH_MASK_IN_LOG` | `true` | 可选 | 日志中自动脱敏手机号/邮箱 |

#### 9.10 典型配置场景

##### 场景 A：单机最小化（SQLite + 内存 stub，开箱即用）

适合个人试用、功能演示：

```bash
# .env — 最小化配置
ENV=dev
DEBUG=true
LOG_LEVEL=INFO

# SQLite 零配置数据库
DB_BACKEND=sqlite
DB_SQLITE_PATH=./data/openclaw.db
DB_ENCRYPTION_KEY=please-change-this-to-a-strong-random-32-chars!!

# 无 Redis，自动降级为内存 stub
# QUEUE_REDIS_HOST=（留空或注释）

# 应用服务
ADAPTER_HOST=0.0.0.0
ADAPTER_PORT=8000

# 管理后台
WEB_ADMIN_ENABLED=true
WEB_ADMIN_HOST=0.0.0.0
WEB_ADMIN_PORT=8080
WEB_ADMIN_SECRET_KEY=change-me-web-admin-secret-please
WEB_ADMIN_USERNAME=admin
WEB_ADMIN_PASSWORD_PLAIN=ChangeMe123

# 代理（可选）
# HTTP_PROXY=
# HTTPS_PROXY=

# T29 企业信息补全（开启）
ENRICH_ENABLED=true
ENRICH_CHANNEL=aiqicha
ENRICH_MODE=async
ENRICH_INTERVAL_SECONDS=5
```

##### 场景 B：生产环境（PostgreSQL + 真实 Redis + 多代理）

```bash
# .env — 生产环境
ENV=prod
DEBUG=false
LOG_LEVEL=WARNING

# PostgreSQL
DB_BACKEND=postgres
DB_HOST=127.0.0.1
DB_PORT=5432
DB_NAME=openclaw_biz
DB_USER=openclaw
DB_PASSWORD=change-me-strong-password
DB_POOL_SIZE=10
DB_MAX_OVERFLOW=20

# 生产环境密钥（至少 32 字符，务必修改并妥善保存）
DB_ENCRYPTION_KEY=aZ9kP2mQ8nR4wX1vB6cY3dF7gH0jT5e

# Redis
QUEUE_REDIS_HOST=127.0.0.1
QUEUE_REDIS_PORT=6379
QUEUE_REDIS_DB=0
QUEUE_WORKER_CONCURRENCY=8

# 应用服务（生产建议使用 Nginx 反向代理）
ADAPTER_HOST=127.0.0.1
ADAPTER_PORT=8000
ADAPTER_BASE_URL=https://biztools.your-domain.com
ADAPTER_API_TOKENS=prod-agent-token-xxxxxxxx,another-agent-token-yyyyyyyy
ADAPTER_DAILY_QUOTA_PER_AGENT=2000

# 管理后台（生产建议绑定内网 IP 或通过 VPN 访问）
WEB_ADMIN_ENABLED=true
WEB_ADMIN_HOST=127.0.0.1
WEB_ADMIN_PORT=8080
WEB_ADMIN_SECRET_KEY=change-me-to-a-random-string-please-in-prod
WEB_ADMIN_SESSION_TTL_SECONDS=14400

# 多账号模式（推荐生产环境）
WEB_ADMIN_ACCOUNTS_JSON=[
    {"username":"admin","role":"super_admin","password_plain":"ChangeMe123!!"},
    {"username":"ops_01","role":"ops","password_plain":"ChangeMe123!!"},
    {"username":"sales_zhang","role":"sales","password_plain":"ChangeMe123!!"},
    {"username":"compliance_01","role":"compliance","password_plain":"ChangeMe123!!"}
]

# 代理池
HTTP_PROXY=http://proxy1:8080,http://proxy2:8080,http://proxy3:8080
HTTPS_PROXY=http://proxy1:8080,http://proxy2:8080,http://proxy3:8080

# T29 企业信息补全（生产建议更保守的限流）
ENRICH_ENABLED=true
ENRICH_CHANNEL=aiqicha
ENRICH_MODE=async
ENRICH_INTERVAL_SECONDS=8
ENRICH_CACHE_TTL_SECONDS=604800
ENRICH_CONSECUTIVE_FAILURE_THRESHOLD=5
```

##### 场景 C：开发调试（DEBUG=true + 详细日志）

```bash
# .env — 开发调试模式
ENV=dev
DEBUG=true
LOG_LEVEL=DEBUG

# 轻量数据库
DB_BACKEND=sqlite
DB_SQLITE_PATH=./data/openclaw_dev.db
DB_ENCRYPTION_KEY=dev-testing-key-32-chars-minimum-ok

# 无 Redis 也可运行（降级为内存 stub）
# QUEUE_REDIS_HOST=

# 详细日志输出到控制台
ADAPTER_HOST=0.0.0.0
ADAPTER_PORT=8000

WEB_ADMIN_ENABLED=true
WEB_ADMIN_HOST=0.0.0.0
WEB_ADMIN_PORT=8080
WEB_ADMIN_SECRET_KEY=dev-secret-key-for-testing-only
WEB_ADMIN_USERNAME=admin
WEB_ADMIN_PASSWORD_PLAIN=test123456

# T29 企业信息补全（开发模式更激进，便于测试）
ENRICH_ENABLED=true
ENRICH_MODE=sync          # 开发模式使用同步，便于调试
ENRICH_INTERVAL_SECONDS=2 # 开发模式缩短间隔
ENRICH_CACHE_ENABLED=false # 开发模式禁用缓存，每次都查
```

---

## 第五部分：故障排查与开发者手册

---

### P10 故障排查与常见问题 FAQ

> **适用角色**: 所有角色 | **阅读时间**: 8 分钟

#### 10.1 部署相关问题

**Q1：Python 版本不对怎么办？**

```bash
# 检查当前 Python 版本
python --version
# 需要 ≥ 3.10，推荐 3.11

# Windows 解决方案：
# 1. 从 python.org 下载安装 3.11.x
# 2. 使用 py 启动器指定版本
py -3.11 --version
# 3. 创建虚拟环境时用：py -3.11 -m venv venv

# macOS / Linux 解决方案：
# 使用 pyenv 或系统包管理器安装 3.11
# Ubuntu/Debian:
sudo apt-get install python3.11 python3.11-venv
```

**Q2：服务启动失败，端口被占用？**

```bash
# Windows (PowerShell) — 检查端口占用
netstat -ano | findstr :8000
# 查到 PID 后任务管理器结束进程，或在 .env 中改端口

# macOS / Linux — 检查并释放端口
lsof -i :8000
kill -9 <PID>

# 或修改 .env 使用其他端口
ADAPTER_PORT=8001
WEB_ADMIN_PORT=8081
```

**Q3：数据库初始化失败？**

- 检查 `DB_BACKEND` 配置是否正确（`sqlite` 或 `postgres`）
- PostgreSQL 模式：确认数据库服务运行、用户有创建表权限
- SQLite 模式：确认 `./data/` 目录存在且有写权限
- 查看 `logs/` 目录下的启动日志，定位具体错误

**Q4：Redis 不可用怎么办？**

- BizTools4Openclaw 对 Redis 非强依赖，**会自动降级为内存缓存（Python dict）**
- 降级后影响：异步任务并发受限、定时任务重启后丢失、会话不共享
- 生产环境务必启动 Redis：`redis-server` 或 Docker 容器

**Q5：`DB_ENCRYPTION_KEY` 忘了改或想更换？**

- ❗ 首次启动后**请勿更改**此密钥，否则已加密的联系方式等字段无法解密
- 如果只是忘了改，且数据库中暂无重要数据：可以删除数据库文件重启
- 如果已有重要数据，需先编写迁移脚本：用旧密钥解密 → 用新密钥加密 → 更新数据库

#### 10.2 采集相关问题

**Q6：爬虫任务一直 pending，不执行？**

```
排查步骤：
  1. 确认 Redis 可用（或降级 stub 正常工作）
  2. 确认 worker 进程在运行（日志中应有 worker 启动信息）
  3. 检查任务是否设置了未来的执行时间
  4. 查看 /api/v1/tasks/{task_id} 状态详情
  5. 检查 QUEUE_WORKER_CONCURRENCY 是否为 0（不应为 0）
```

**Q7：抓取结果是空的？**

```
可能原因：
  1. 目标网站使用 JS 动态渲染 → 启用 Playwright 渲染
  2. 被目标网站反爬（返回 403/429）→ 更换代理 + 增大间隔
  3. CSS 选择器失效（网站改版）→ 更新采集方案的字段选择器
  4. 需要登录才能访问 → 需要配置 Cookie 或登录脚本

测试方法：
  1. 在浏览器中手动访问目标 URL，确认内容正常显示
  2. 在采集方案中勾选「启用 JS 渲染」重试
  3. 查看爬虫日志中的 HTTP 状态码和响应内容
```

**Q8：如何启用 Playwright 渲染？**

```bash
# 首次使用需安装浏览器
python -m playwright install chromium

# .env 全局默认
SPIDER_DEFAULT_RENDER_JS=true

# 或在单个采集方案中，高级选项勾选「启用 JS 渲染」
```

**Q9：代理配置了但无法连接？**

```
排查：
  1. 代理格式是否正确（http://host:port 或 http://user:pass@host:port）
  2. 代理服务器是否可用（用 curl --proxy 手动测试）
  3. 多个代理逗号分隔，失败时自动切换
  4. 查看 logs/spider.log 中 PROXY 相关日志
```

#### 10.3 清洗相关问题（含 T29）

**Q10：企业信息补全（T29）查不到结果？**

```
可能原因：
  1. 企业名称不准确（存在错别字 / 简称）→ 检查商机中的企业名称字段
  2. 目标渠道确实无该企业信息 → 尝试切换 ENRICH_CHANNEL
  3. 查询间隔设置过短，被渠道限流 → 增大 ENRICH_INTERVAL_SECONDS
  4. 网络不通（需确认能访问爱企查等外部网站）
  5. Playwright 未正确安装 → 执行 playwright install chromium

查看状态：
  - 访问 http://localhost:8080/admin → 商机线索 → 补全状态列
  - 或查看 logs/enterprise_enrich.log 详细查询日志
```

**Q11：电话/微信号识别不准确？**

```
- 电话号码：支持 13/14/15/16/17/18/19 开头的 11 位手机号；
  座机号格式多样，部分特殊格式可能漏识别
- 微信号：常见格式 WeChat / 微信号 / wx: 前缀，纯字母数字的微信号可能误判
- 邮箱：标准 email 格式，识别率较高
- 如发现大量漏识别，可在 business/data_clean/extractor.py 中补充正则规则
```

**Q12：商机评分普遍偏低怎么办？**

```
- 检查行业关键词库（CLEAN_INDUSTRY_KEYWORDS）是否覆盖实际业务
- 确认来源数据质量（部分平台数据字段不完整）
- 可在 configs/settings.py 中调整各评分维度的权重
```

#### 10.4 触达相关问题

**Q13：邮件发送失败？**

```
检查：
  1. SMTP 服务器、端口、账号、密码是否正确
  2. 是否需要 SSL（465 端口）或 TLS（587 端口）
  3. 邮箱服务商是否有"第三方应用专用密码"要求
  4. 是否触发了 SMTP 服务商的发送频率限制
  5. 查看 logs/send_email.log 中的具体错误信息
```

**Q14：飞书机器人消息无响应？**

```
检查：
  1. Webhook URL 是否正确（应包含 bot/v2/hook/ 等路径）
  2. 是否启用了"签名校验"（如启用需在配置中同时设置签名密钥）
  3. 消息格式是否符合飞书卡片格式要求
  4. 飞书后台"消息撤回保护"是否拦截了测试消息
```

**Q15：发送被限制/账号被封？**

```
预防措施：
  1. 严格遵守发送频率限制（CUSTOMER_SEND_BATCH_SIZE_DEFAULT）
  2. 多账号轮询发送（在渠道账号页配置多个账号）
  3. 内容避免明显营销词汇（降低被识别为垃圾消息的概率）
  4. 提供退订方式并尊重用户意愿
```

#### 10.5 管理后台问题

**Q16：登录失败/会话超时？**

```
- 确认账号密码与 .env 中配置一致
- 多账号模式下 WEB_ADMIN_ACCOUNTS_JSON 格式是否正确
- Redis 不可用时，重启服务会导致所有会话失效
- 调整 WEB_ADMIN_SESSION_TTL_SECONDS 延长会话时间
```

**Q17：页面显示空数据，但确定数据库有数据？**

```
- 可能是筛选条件过滤了全部数据（尝试清空所有筛选）
- 检查分页是否跳在了空页
- 浏览器按 F12 打开开发者工具 → Console 查看 JS 错误
- Network 面板查看 API 响应是否正常（200 + 有数据）
```

**Q18：角色权限不足怎么办？**

```
权限矩阵：
  ├─ super_admin：所有功能
  ├─ ops：爬虫 + 商机 + 渠道（不含账号管理）
  ├─ sales：商机列表 + 销售看板 + 跟进操作
  └─ compliance：合规规则 + 违规数据池 + 审计

如非 super_admin 需要额外权限，需由 super_admin 在 .env 中
调整 WEB_ADMIN_ACCOUNTS_JSON 并重启服务。
```

#### 10.6 日志查看路径

| 日志文件 | 位置 | 内容 |
|---------|------|------|
| 主应用日志 | `logs/app.log` | 启动/关闭/错误堆栈 |
| API 访问日志 | `logs/api.log` | HTTP 请求与响应摘要 |
| 爬虫日志 | `logs/spider.log` | 抓取任务、代理切换、风控事件 |
| 清洗日志 | `logs/clean.log` | 实体抽取、评分、T29 补全 |
| 发送日志 | `logs/send.log` | 邮件/飞书/微信发送详情 |
| 销售日志 | `logs/sales.log` | 分配、跟进、漏斗更新 |
| 审计日志 | `logs/audit.log` | 登录/登出、危险操作、权限变更 |
| 控制台 | 启动终端 | 实时日志（DEBUG/INFO/...) |

**临时调整日志级别（不重启）**：

```
通过管理后台 → 系统设置 → 日志级别（仅 super_admin 可操作）
```

---

### P11 开发者扩展手册

> **适用角色**: 开发者 | **阅读时间**: 8 分钟

#### 11.1 四层分层与职责边界速查

```
┌─ L4 接入展示层（adapter/, web_admin/）────────────────────┐
│ 职责：HTTP API 暴露、页面渲染、权限认证、请求路由            │
│ 禁止：直接写数据库访问逻辑、直接写爬虫业务代码               │
└────────────────────────────────────────────────────────────┘
                           ↓ 调用
┌─ L3 业务模块层（business/*）───────────────────────────────┐
│ 职责：特定业务流程编排（爬虫 pipeline、清洗 pipeline 等）     │
│ 禁止：直接操作 HTTP 请求/响应、不跨业务模块直接 import        │
└────────────────────────────────────────────────────────────┘
                           ↓ 调用
┌─ L2 通用能力层（core/*）───────────────────────────────────┐
│ 职责：可复用的 SDK（爬虫、去重、风控、消息发送底座）           │
│ 禁止：直接访问业务数据模型、不包含业务规则                   │
└────────────────────────────────────────────────────────────┘
                           ↓ 调用
┌─ L1 基础基建层（infra/）────────────────────────────────────┐
│ 职责：数据库 ORM、Redis、日志、异常、告警、定时调度           │
│ 禁止：包含任何业务规则                                        │
└────────────────────────────────────────────────────────────┘
```

#### 11.2 新增业务模块模板

**目标**：在 `business/` 下新增一个完整的业务模块（如 `business/survey_analysis/`）

**必需文件清单**：

```
business/survey_analysis/
  ├── __init__.py          # 包声明
  ├── models.py            # Pydantic 数据模型（请求/响应格式）
  ├── pipeline.py          # 业务流程编排（核心逻辑）
  ├── storage.py           # 数据读写（调用 infra/db_base）
  ├── registry.py          # 模块注册（供 L4 层发现和调用）
  └── _orm.py              # SQLAlchemy ORM 模型（如需新表）
```

**注册到 API（L4 层）**：

```python
# 在 adapter/main.py 或 adapter/v1/ 下添加路由
# from business.survey_analysis import registry
# app.include_router(registry.router, prefix="/api/v1/survey", tags=["调研分析"])
```

**注册到 Web 管理后台**：

```python
# 在 web_admin/pages.py 中添加页面路由
# 在 web_admin/menu.py 中添加左侧菜单项
```

#### 11.3 扩展新采集源（继承 `BaseSpider`）

```
business/multi_spider/sources/your_source.py 模板：

  1. 继承 BaseSpider
  2. 实现 scrape(url) → 抓取原始数据
  3. 实现 normalize(raw_data) → 标准化为中间格式
  4. 在 business/multi_spider/registry.py 中注册
  5. 在 SPIDER_CHANNEL_*_ENABLED 中添加开关（可选）

关键要点：
  - 使用 core/spider_core/sdk.py 中的 fetch_html/fetch_json
  - 遵守 robots.txt 检查（core/spider_core/robots_checker.py）
  - 异常需抛出 SpiderError，不直接 raise 普通 Exception
  - 返回统一的 OpportunityRawData 格式
```

#### 11.4 扩展新触达渠道（实现 `ChannelBase` 接口）

```
business/customer_send/channels/your_channel.py 模板：

  1. 实现 send(recipient: str, content: MessageContent, template_id: str)
  2. 实现 get_status(task_id: str) → 发送状态查询
  3. 实现 get_capabilities() → 渠道能力声明
  4. 在 business/customer_send/registry.py 中注册
  5. 在 .env 中添加渠道配置项（如 CUSTOMER_SEND_YOURCHANNEL_ENABLED）

风控接入：
  - 自动接入 core/send_core/ 的限流、敏感词检测、失败重试
  - 需在渠道实现中正确抛出 SendError 以触发降级
```

#### 11.5 编码规范

```
强制遵守：
  ✅ Python 3.10+ 语法（使用 | 联合类型、str | int 而非 Union）
  ✅ Pydantic v2 模型（BaseModel + model_config）
  ✅ 所有对外函数包含类型注解
  ✅ 敏感信息绝不写入日志（使用 mask_logging 装饰器）
  ✅ 数据库操作使用 SQLAlchemy 2.0 风格
  ✅ 配置全部从 .env 读取，零硬编码

建议遵循：
  - 函数命名：动词开头（fetch_, extract_, save_）
  - 文件命名：全小写 + 下划线（snake_case）
  - 类命名：PascalCase，首字母大写
  - 常量命名：全大写 + 下划线
  - 每个公开函数包含 docstring
  - 复杂算法添加行内注释说明
```

#### 11.6 测试编写指南

测试文件存放位置：`tests/test_<模块>.py`

**测试结构模板**：

```python
# tests/test_your_module.py
import pytest
from business.your_module.pipeline import YourPipeline
from business.your_module.models import YourRequest, YourResponse

class TestYourPipeline:
    def test_basic_flow(self):
        """测试正常流程"""
        pipeline = YourPipeline()
        result = pipeline.run(YourRequest(field1="value1"))
        assert result.success is True
        assert len(result.items) > 0

    def test_invalid_input(self):
        """测试输入异常"""
        pipeline = YourPipeline()
        with pytest.raises(ValueError):
            pipeline.run(YourRequest(field1=""))

    def test_empty_data(self):
        """测试空数据边界"""
        pipeline = YourPipeline()
        result = pipeline.run(YourRequest(field1=""))
        assert result.items == []
```

**运行测试**：

```bash
# 全量测试
pytest tests/ -v --tb=short

# 特定模块测试
pytest tests/test_enterprise_enrich.py -v

# 覆盖率报告
pytest tests/ --cov=business --cov=core --cov=infra --cov-report=html
```

---

### P12 附录

> **适用角色**: 系统管理员 / 开发者 | **阅读时间**: 3 分钟

#### A.1 端口速查表

| 端口 | 服务 | 备注 |
|------|------|------|
| 8000 | API 网关（FastAPI） | OpenClaw 对接入口，Swagger 文档在 /docs |
| 8080 | Web 管理后台 | 浏览器访问 /admin |
| 5432 | PostgreSQL | 可选（生产推荐） |
| 6379 | Redis | 可选（无 Redis 自动降级内存 stub） |
| 443 | HTTPS 外部访问 | 生产建议 Nginx 反代 + SSL |

#### A.2 核心数据模型字段速查

**StructuredOpportunity（结构化商机）**：

| 字段 | 类型 | 必填 | 说明 |
|------|------|------|------|
| id | UUID | ✅ | 主键 |
| company_name | string | ✅ | 企业名称 |
| phone_numbers | JSON | 可选 | 电话号码列表 |
| email_addresses | JSON | 可选 | 邮箱列表 |
| wechat_ids | JSON | 可选 | 微信号列表 |
| industry_tags | JSON | 可选 | 行业标签 |
| budget_range | string | 可选 | 预算范围 |
| region | string | 可选 | 地区 |
| score | int | ✅ | 商机评分 0-100 |
| data_source | string | ✅ | 数据来源 |
| source_url | string | 可选 | 来源 URL |
| enriched | bool | ✅ | 是否已企业信息补全 |
| enrichment_source | string | 可选 | 补全来源渠道 |
| enrichment_profile | JSON | 可选 | 补全的企业画像 (EnterpriseProfile) |
| opportunity_status | string | ✅ | 商机状态（new/reached/responded/...) |
| sales_assignee | string | 可选 | 分配的销售人员 |
| last_follow_up_at | datetime | 可选 | 最后跟进时间 |
| created_at | datetime | ✅ | 入库时间 |
| updated_at | datetime | ✅ | 更新时间 |

**EnterpriseProfile（T29 企业画像）**：

参见 P5.3 小节中的表格。

#### A.3 任务状态流转图

```
┌─────────┐    执行    ┌─────────┐   成功    ┌──────────┐
│ pending │ ─────────▶ │ running │ ────────▶ │ success  │
└─────────┘            └─────────┘            └──────────┘
                            │                    ▲
                            │ 失败               │ 手动
                            ▼                    │ 重试
                        ┌─────────┐   自动重试   │
                        │ failed  │ ─────────────┘
                        └─────────┘
                            │
                            │ 用户取消
                            ▼
                        ┌──────────┐
                        │ cancelled│
                        └──────────┘
```

#### A.4 日志文件与级别设置

| 日志级别 | 适用场景 | 内容 |
|---------|---------|------|
| DEBUG | 开发调试 | 详细的变量值、执行路径、原始响应内容 |
| INFO | 正常运行 | 任务开始/完成、关键决策、数据统计 |
| WARNING | 潜在问题 | 重试事件、降级事件、边界情况 |
| ERROR | 异常情况 | 捕获的异常、任务失败、连接失败 |
| CRITICAL | 严重故障 | 数据库不可用、加密密钥错误、严重数据损坏 |

**动态调整级别（运行时）**：

```
管理后台 → 系统设置 → 日志级别
仅 super_admin 可操作
```

#### A.5 文档索引

| 文档 | 路径 | 说明 |
|------|------|------|
| README | `./README.md` | 项目介绍、架构概览、快速开始 |
| 本手册 | `docs/PROJECT_USAGE_MANUAL.md` | 完整使用手册（当前文档） |
| 任务清单 | `docs/TASK_LIST.md` | T01-T29 全任务进度与说明 |
| 开发规范 | `./DEVELOP_RULES.md` | 四层架构、编码规范、Git 规范 |
| .env 示例 | `./.env.example` | 完整配置项模板 |
| API 文档（在线）| `http://localhost:8000/docs` | Swagger UI，启动服务后访问 |

---

**文档版本**：v1.0 (T29)  
**最后更新**：2026-03-18  
**适用版本**：BizTools4Openclaw ≥ T29  
**维护者**：项目开发团队
```

现在让我完成 Todo 列表，确认文档已全部编写：

---

### ✅ 文档编写完成总结

我已为 **BizTools4Openclaw（T29 版本）** 编写了完整的项目使用手册，覆盖以下 **12 个部分**：

| 章节 | 内容 | 预估页数 |
|------|------|---------|
| **P1 项目概述** | 架构图、6 大能力、四层分层说明 | 5 |
| **P2 快速入门** | 环境准备 + 3 种部署方式 + 入口速查 | 8 |
| **P3 Web 管理后台** | 4 角色权限 + 6 大模块操作指南 | 15 |
| **P4 数据采集** | 6 大数据源 + 可视化配置 + 风控 | 12 |
| **P5 数据清洗** | 7 步流水线 + **T29 企业信息补全详解** | 10 |
| **P6 多渠道触达** | 邮件/飞书/微信/H5 + 模板引擎 + 风控 | 8 |
| **P7 销售自动化** | 分配引擎 + 跟进提醒 + 漏斗统计 | 8 |
| **P8 API 参考** | 统一响应格式 + 认证 + 关键 API 实战示例 | 10 |
| **P9 配置参考** | `.env` 全字段速查 + 3 种场景配置 | 8 |
| **P10 FAQ** | 18 个常见问题的排查与解决 | 8 |
| **P11 开发者扩展** | 分层规则 + 新模块/采集源/渠道模板 | 6 |
| **P12 附录** | 端口表 + 数据模型 + 日志 + 文档索引 | 3 |

**文档亮点**：
- 📋 与 T29 新功能（企业信息自动补全）深度对齐，包含完整的 `EnterpriseProfile` 字段、配置、API
- 🔑 3 种典型 `.env` 配置场景（最小化 / 生产 / 开发调试），可直接复制使用
- 🔌 完整的 API 参考与 OpenClaw 联调示例，含真实请求/响应格式
- 🛠️ 18 个 FAQ 问题，覆盖部署、采集、清洗、触达、后台
- 📐 严格与 `configs/settings.py`、`.env.example` 配置项对齐

文档内容已准备就绪，可保存为 `docs/PROJECT_USAGE_MANUAL.md`，由 super_admin 角色审核后发布。
<seed:tool_call><function name="TodoWrite"><parameter name="todos" string="false">[{"content": "P1 项目概述与架构", "id": "1", "priority": "high", "status": "completed"}, {"content": "P2 快速入门（环境+部署+首次启动）", "id": "2", "priority": "high", "status": "completed"}, {"content": "P3 Web 管理后台（权限+看板+各模块）", "id": "3", "priority": "high", "status": "completed"}, {"content": "P4 数据采集（T09+T25-T27可视化采集）", "id": "4", "priority": "high", "status": "completed"}, {"content": "P5 数据清洗（T10流水线+T29企业补全）", "id": "5", "priority": "high", "status": "completed"}, {"content": "P6 多渠道触达（T11邮件/飞书/微信/H5）", "id": "6", "priority": "medium", "status": "completed"}, {"content": "P7 销售自动化（T12分配+漏斗+提醒）", "id": "7", "priority": "medium", "status": "completed"}, {"content": "P8 OpenClaw API 参考（T13）", "id": "8", "priority": "high", "status": "completed"}, {"content": "P9 完整配置参考（.env全字段+3场景）", "id": "9", "priority": "high", "status": "completed"}, {"content": "P10 故障排查与FAQ", "id": "10", "priority": "medium", "status": "completed"}, {"content": "P11 开发者扩展手册（分层+新模块模板）", "id": "11", "priority": "medium", "status": "completed"}, {"content": "P12 附录（端口表+数据模型+日志）", "id": "12", "priority": "low", "status": "completed"}]