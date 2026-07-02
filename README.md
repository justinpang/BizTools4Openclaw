# openclaw-business-tools
适配 OpenClaw 智能体的全链路商机自动化工具集
一款专为 OpenClaw 打造的商机采集、清洗、触达、销售跟进一体化工具套件，实现「全网商机抓取→结构化数据处理→自动化客户激活→销售闭环跟进」全流程无人值守，补齐 OpenClaw 商业化落地能力。
## ✨ 项目核心能力
- 全网全源商机采集：覆盖网页、短视频、小红书、论坛、社群、供需平台、问答、企业公示、招聘、招投标等全场景商机来源
- 智能数据处理：自动清洗、去重、脱敏、实体抽取、商机打分分级，输出标准化结构化数据，适配大模型调度
- 多渠道自动化触达：支持微信、飞书、邮件、H5落地页多渠道客户激活，内置风控防封号机制
- 销售流程自动化：商机自动分配、定时跟进提醒、逾期告警、转化数据统计，实现业务落地闭环
- 原生适配OpenClaw：标准化工具注册、API调度、异步任务回调，完美兼容OpenClaw智能体编排
- 全链路合规保障：数据脱敏、隐私保护、爬虫合规、消息风控，规避商用风险
## 整体架构
项目采用 四层分层+业务模块拆解 架构：基础基建层 → 通用能力层 → 业务模块层 → 接入展示层，架构解耦、可插拔、易扩展、支持单独迭代任意模块。
## 技术栈
- 后端框架：FastAPI（轻量化、高性能、适配智能体调用）
- 爬虫引擎：Playwright（动态页面渲染、全平台适配）
- 任务调度：Redis + APScheduler（分布式异步任务）
- 数据存储：MySQL / SQLite（轻量适配）
- 部署方式：Docker Compose 一键部署
## 快速接入
1. 克隆项目，配置多环境配置文件
2. 初始化数据库，启动基础服务
3. 在OpenClaw中注册工具集API
4. 配置爬虫任务、触达渠道、销售提醒规则
5. 启动全链路自动化流程
## 项目文档
- 开发规范：DEVELOP_RULES.md
- 任务清单：TASK_LIST.md
## 开源协议
MIT License，可自由二次开发、商用部署。
## 完整目录结构
openclaw-business-tools/
├── .github/            # GitHub 配置、CI/CD
├── infra/              # Layer1 基础基建层
├── core/               # Layer2 通用能力层
│   ├── spider_core/    # 爬虫核心能力
│   ├── data_core/      # 数据处理核心
│   ├── send_core/      # 触达核心风控
│   └── compliance/     # 合规管控
├── business/           # Layer3 业务模块层
│   ├── multi_spider/   # 全源爬虫业务
│   ├── data_clean/     # 数据清洗结构化
│   ├── customer_send/  # 多渠道触达
│   └── sales_task/     # 销售调度跟进
├── adapter/            # Layer4 OpenClaw适配网关
├── web_admin/         # 可视化后台
├── configs/           # 多环境配置
├── docker/            # 容器部署
├── docs/              # 项目文档
├── examples/          # OpenClaw调用示例
├── tests/             # 单元测试
├── README.md          # 项目总说明
├── DEVELOP_RULES.md   # 开发规范总纲
└── TASK_LIST.md       # 全量任务拆分