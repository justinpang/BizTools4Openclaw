# OpenClaw-BizTools 开发规范总纲

> 本文档为项目统一开发、编码、提交、架构、测试、交付规范。**所有开发者必须严格遵守**，以保证项目架构一致、代码可维护、可迭代、适配 OpenClaw 生态。
>
> 文档状态：`docs(T15)` 同步至最新架构与代码实现。
> 适用范围：本仓库所有代码与文档。

---

## 1. 架构规范

### 1.1 四层分层定义

项目严格遵循 **四层分层架构**，自上而下为：

| 层级 | 名称 | 目录 | 职责边界 |
|------|------|------|---------|
| **L4** | 接入展示层 | `adapter/`、`web_admin/` | 对外 API 网关（FastAPI）、Web 管理后台页面；**不承载任何业务逻辑**，仅做路由转发、参数校验、响应包装 |
| **L3** | 业务模块层 | `business/` | 具体业务场景实现：`multi_spider`（爬虫业务）、`data_clean`（清洗流水线）、`customer_send`（多渠道触达）、`sales_task`（销售跟进）；**业务逻辑唯一落点** |
| **L2** | 通用能力层 | `core/` | 跨业务模块共享的通用能力：`spider_core`（爬虫 SDK）、`data_core`（去重/合并/打分）、`send_core`（消息风控底座）、`compliance`（合规/脱敏/加密）；**禁止写入业务逻辑** |
| **L1** | 基础基建层 | `infra/`、`configs/`、`docker/` | 全局基础设施：日志、异常、告警、Redis 客户端、SQLAlchemy ORM、任务队列/调度、配置管理、容器化；**所有上层模块的共同依赖** |

### 1.2 跨层调用矩阵（允许 ✅ / 禁止 ❌）

| 调用方 ↓ → 被调用方 → | L4 (`adapter/`, `web_admin/`) | L3 (`business/*`) | L2 (`core/*`) | L1 (`infra/`, `configs/`) |
|----------------------|-------------------------------|-------------------|---------------|-------------------------|
| **L4** 接入展示层 | ✅ 内部调用（如 web_admin → adapter API） | ✅ 通过 `registry.py` 调用业务模块能力 | ✅ 调用通用能力 | ✅ 直接使用 |
| **L3** 业务模块层 | ❌ 禁止反向依赖接入层 | ✅ 通过 registry 调用同层其他业务模块 | ✅ 调用通用能力 | ✅ 直接使用 |
| **L2** 通用能力层 | ❌ 禁止反向依赖 | ❌ 禁止依赖业务逻辑 | ✅ 内部调用 | ✅ 直接使用 |
| **L1** 基础基建层 | ❌ 禁止反向依赖任何业务层 | ❌ 禁止依赖业务模块 | ❌ 禁止依赖通用能力 | ✅ 内部调用 |

**简明口诀**：**向下调用，向上禁止**。L4 可调用 L3/L2/L1，L3 可调用 L2/L1，L2 可调用 L1，L1 不依赖任何业务层。

### 1.3 模块可插拔设计

- 每个 `business/<子模块>` 必须包含 `registry.py`，对外暴露统一注册入口
- 每个 `business/<子模块>/sources/` 或 `channels/` 下的具体实现应遵循 **依赖倒置**：基类定义接口，具体实现继承基类
- 新增/移除数据源或触达渠道，**不应影响其它模块**（仅在对应 `registry.py` 中增删注册项）
- 业务模块之间通过 `registry.py` 暴露的公共 API 通信，**禁止直接 import 私有实现**

### 1.4 统一网关暴露

- 所有对外 HTTP API **必须**通过 `adapter/main.py` 的 FastAPI 实例挂载路由
- Web 管理后台通过 `web_admin/main.py` 的 `mount_on(app)` 挂载至 `adapter/main.py`
- 禁止在 `business/` 或 `core/` 下直接启动独立服务或暴露网络端口
- 所有 API 响应必须使用 `infra/response.py` 的统一响应包装

---

## 2. 代码规范

### 2.1 Python 编码规范

- 严格遵循 **PEP 8**（使用 pyright / flake8 做静态检查）
- 单行不超过 120 字符（文件路径等特殊情况允许，但需对齐）
- 顶级 import 顺序：标准库 → 第三方库 → 本项目模块，每组间空一行
- 使用 **type hint**（类型注解），尤其是函数签名：
  ```python
  def fetch_leads(source: str, limit: int = 20) -> list[dict[str, str]]:
      """从指定数据源抓取商机列表。"""
  ```
- 禁止使用 `from xxx import *`（除极特殊的 `__init__.py` 需显式导出符号场景）
- 优先使用 `pathlib.Path` 而非硬编码字符串路径

### 2.2 命名约定

| 符号类型 | 规则 | 示例 |
|---------|------|------|
| 类 / 异常类 | **大驼峰** `PascalCase` | `BaseSpider`、`RateLimitExceeded`、`PipelineError` |
| 函数 / 方法 | **小蛇形** `snake_case` | `scrape_page()`、`get_status()`、`send_to_channel()` |
| 变量 / 函数参数 | **小蛇形** `snake_case` | `lead_data`、`channel_id`、`created_at` |
| 模块级常量 | **全大写蛇形** `UPPER_SNAKE_CASE` | `MAX_RETRY_COUNT`、`DEFAULT_PAGE_SIZE`、`REDIS_PREFIX` |
| 模块 / 包名 | **小蛇形** `snake_case` | `multi_spider/`、`customer_send/`、`email_channel.py` |
| 私有符号（模块/类内） | **单下划线前缀** `_private` | `_orm.py`、`_parse_raw()`、`self._cached_data` |
| 测试文件 | `test_t<T##>_<功能描述>.py` | `test_t14_web_admin.py`、`test_t09_multi_spider.py` |
| 测试函数 | `test_<场景>_<期望>` | `test_login_valid_credentials_returns_session()` |

### 2.3 注释与 docstring

- **公共类/函数必须有 docstring**，推荐 Google 风格：
  ```python
  def send_email(recipient: str, template_id: str, context: dict) -> bool:
      """通过邮件渠道发送消息。

      Args:
          recipient: 收件人邮箱地址（已通过合规检查）
          template_id: 邮件模板 ID，对应 configs/templates/ 下文件
          context: 模板渲染上下文变量 dict，如 {"company": "Acme"}

      Returns:
          bool：发送是否成功（True 表示已投递到 MTA，不表示对方必收）

      Raises:
          ChannelConfigError: 邮箱配置缺失或无效
          RateLimitExceeded: 单账号发送频率超限，已触发风控

      Example:
          >>> send_email("contact@acme.com", "welcome_v1", {"company": "Acme"})
          True
      """
  ```
- 复杂算法 / 正则 / 业务判断点 **必须** 增加行内注释说明意图
- 注释使用中文（与本项目其他文档一致），英文术语保留原拼写
- 废弃/兼容代码使用 `# TODO: <原因>` 或 `# DEPRECATED: <替代方案>` 标注，并在三个月内清理

### 2.4 配置管理

- **禁止硬编码任何配置**（URL、密钥、阈值、时间间隔、路径等）
- 所有配置统一放入 `configs/settings.py`，使用 Pydantic `BaseSettings` 模型
- 环境变量通过 `.env` 文件注入，**`.env` 禁止提交到仓库**（已在 `.gitignore` 中排除）
- `.env.example` 维护所有环境变量的**默认值与说明**，新增配置项必须同步更新
- Web 管理后台相关配置（账号、密码、会话 TTL）统一放在 `WebAdminSettings` 下
- 跨环境切换（dev/staging/prod）通过修改 `ENVIRONMENT` 环境变量实现，代码中禁止 `if hostname == 'xxx'` 判断

### 2.5 异常处理

- 所有对外 API 由 `infra/exception_handler.py` 统一捕获，转换为标准 JSON 响应
- 业务代码抛出的异常应使用 `infra/exceptions.py` 中定义的业务异常类型（`BusinessError`、`PipelineError`、`RateLimitExceeded` 等）
- 禁止裸 `raise Exception("message")`，必须使用具名异常类
- 捕获异常时遵循「先具体后泛化」原则：先捕获 `RateLimitExceeded`，再捕获 `PipelineError`，最后捕获 `BusinessError`
- 异常发生时必须写入日志（`logger.error()` 或 `logger.warning()`），高危异常同时触发告警
- `__del__` / `atexit` 等全局清理逻辑禁止抛出异常

### 2.6 模块内部实现文件

- 内部实现文件命名约定：**单下划线前缀**，如 `_orm.py`、`_constants.py`、`_helpers.py`
- 这类文件不对外直接暴露符号，外部应通过 `registry.py` 或模块 `__init__.py` 的显式导出访问

---

## 3. 接口规范

### 3.1 统一响应格式

所有对外 API **必须**使用 `infra/response.py` 的统一响应包装：

```json
{
  "code": 0,
  "msg": "success",
  "data": { "key": "value" },
  "timestamp": 1719825600
}
```

| 字段 | 类型 | 说明 |
|------|------|------|
| `code` | `int` | 0 = 成功；非零 = 错误码（与业务异常类映射） |
| `msg` | `string` | 人类可读的提示信息 |
| `data` | `object \| array \| null` | 业务数据主体；成功必返回，失败可返回错误详情 |
| `timestamp` | `int` | Unix 时间戳（秒），由 `infra/response.py` 自动填充 |

**典型错误响应**：
```json
{
  "code": 42901,
  "msg": "Rate limit exceeded",
  "data": { "channel": "email", "retry_after_seconds": 60 },
  "timestamp": 1719825600
}
```

### 3.2 HTTP 状态码约定

| HTTP 状态码 | 使用场景 |
|------------|---------|
| **200 OK** | 查询、更新、删除等常规操作成功 |
| **201 Created** | 创建新资源成功（响应体可包含资源 ID） |
| **202 Accepted** | 异步任务已接收并排队执行（返回 `task_id`） |
| **400 Bad Request** | 参数缺失 / 格式错误 / 校验失败 |
| **401 Unauthorized** | 未登录 / 会话过期 / Token 无效 |
| **403 Forbidden** | 无权限执行该操作 |
| **404 Not Found** | 请求的资源不存在 |
| **409 Conflict** | 资源冲突（如重复提交、账号已存在） |
| **429 Too Many Requests** | 触发频率限制（配合 `Retry-After` header） |
| **500 Internal Server Error** | 服务端未预期异常（由全局异常处理器捕获，**禁止业务代码直接返回**） |

### 3.3 OpenClaw 工具调用适配

- 入参轻量化：避免大体积 payload，优先使用 ID / short key 传递
- 出参标准化：所有工具返回 JSON，必须包含 `data` 字段，结构扁平不超过 3 层
- 异步任务支持状态轮询：`GET /api/admin/tasks/<task_id>/status`
- 异步任务支持取消：`POST /api/admin/tasks/<task_id>/cancel`
- 异步任务支持失败重试：`POST /api/admin/tasks/<task_id>/retry`
- 所有工具在 `adapter/tool_registry.py` 中显式注册，含名称、描述、输入 schema、输出 schema

### 3.4 参数校验与脱敏

- 所有入参通过 Pydantic `BaseModel` 校验：`email: EmailStr`、`phone: str`（配正则）
- 日志中出现的敏感字段（手机号、邮箱、密钥、密码）必须走 `core/compliance/pii_mask.py` 自动掩码
- API 响应中的敏感字段默认脱敏；若需明文（如后台管理查看详情），必须显式授权并记录审计日志

---

## 4. 数据规范

### 4.1 数据库模型设计规范

- 所有 ORM 模型必须继承 `infra/db_base.py: Base`
- 每张表**必须**包含以下基础字段：
  - `id: Integer | BigInteger` — 主键，自增
  - `created_at: DateTime` — 创建时间，默认 `datetime.utcnow()`
  - `updated_at: DateTime` — 更新时间，每次更新自动刷新
- 软删除模型额外包含 `is_deleted: Boolean`（默认 False），查询默认过滤 `is_deleted = False`
- 枚举类型使用 `sqlalchemy.Enum` + Python `Enum` 类，禁止裸字符串状态（例如不要写 `status = 'active'`，写 `status = TaskStatus.ACTIVE`）
- 表名使用小蛇形复数形式：`leads`、`task_runs`、`channel_accounts`
- 字段命名使用小蛇形：`phone_number`、`email_address`、`conversion_score`
- 敏感字段（手机号、邮箱、密钥、密码）使用 `core/compliance/sensitive_crypto.py` 加密存储，`db_models.py` 中定义时标注 `Sensitive(TypeEngine(...))`
- 外键关系必须在模型定义中显式声明 `ForeignKey(...)`，不使用裸 ID 字段模拟关联

### 4.2 数据分层存储策略

| 数据类型 | 存储位置 | 保留周期 |
|---------|---------|---------|
| 原始抓取数据（爬虫 raw） | `leads_raw` 表 / JSON 文件 | 30 天，自动归档到冷存储 |
| 结构化数据（清洗后） | `leads` 表 | 1 年，定期备份 |
| 业务数据（商机分配、触达记录） | `sales_*`、`send_records` 表 | 随业务策略，≥ 1 年 |
| 操作审计日志 | Redis 环形缓冲 + 定期落表 | 90 天 |
| 运行时日志 | `logs/*.log`（文件轮转） | 14 天 |

- 原始数据与结构化数据**禁止混表**
- 所有写操作（INSERT / UPDATE / DELETE）必须记录 `updated_at` 与操作员信息
- 高危删除操作：走软删除 + 审计日志 + `infra/alerting.py` 告警三件套

### 4.3 数据生命周期管理

- 冷数据自动归档由 `core/compliance/archive_mixin.py` 实现，通过 `task_scheduler.py` 周期性触发
- 归档数据可查询但不可修改（只读模式）
- 数据删除遵循「软删除 + 延迟物理清理」：先标记 `is_deleted = True`，30 天后由归档任务物理清除
- 归档任务可在 Web 管理后台手动触发，并记录审计日志

### 4.4 隐私与合规

- 所有用户隐私字段默认脱敏展示（详见 `core/compliance/pii_mask.py`）
- 加密密钥通过环境变量 `CRYPTO_SECRET_KEY` 配置，**禁止硬编码**
- GDPR/个保法合规：提供数据导出与删除接口，需登录后台管理员权限执行

---

## 5. 爬虫合规规范

### 5.1 robots.txt 校验

- `core/spider_core/robots_checker.py` 在每次爬虫任务启动前自动检查目标站点 `robots.txt`
- 对于明确 `Disallow` 的路径，**必须跳过并记录 WARNING 日志**
- 对于 `Crawl-delay` 指定的间隔，**必须严格遵守**并覆盖默认速率配置
- 爬虫 User-Agent 中明确声明身份：`BizTools4Openclaw/<版本> (+https://github.com/...)`

### 5.2 速率限制与代理轮换

- `core/spider_core/rate_limiter.py` 实现令牌桶算法控制请求频率
- `core/spider_core/proxy_pool.py` + `ua_pool.py` 实现代理与 UA 轮换
- 默认单站点最大 QPS 不超过 1，可在 configs 中调整
- 高频抓取场景必须启用代理池，禁止裸 IP 暴力抓取
- 速率限制触发时记录 WARNING 日志，超过阈值触发告警

### 5.3 隐私信息过滤

- `core/compliance/privacy_stripper.py` 在数据入库前自动扫描并剥离非必要隐私字段
- 不采集用户密码、身份证号、银行卡号等强敏感信息
- 采集到的手机号/邮箱在存储前加密，在展示前自动脱敏

### 5.4 风控降级策略

- `core/spider_core/risk_controller.py` 实时监控目标站点响应状态（429 / 403 / 验证码 / 响应时延）
- 触发风控时按阶梯策略自动降级：减速 → 切换代理 → 暂停 → 告警
- 降级过程在 `web_admin/spider_task.py` 中可视化展示，管理员可手动干预
- 风控降级事件记录高危操作审计日志并触发全局告警

### 5.5 断点续爬

- `core/spider_core/checkpoint_manager.py` 实现断点续爬
- 每个爬虫任务每 N 条保存一次 checkpoint，异常中断后可恢复
- checkpoint 存储在 Redis 中，过期时间与任务 TTL 一致

---

## 6. 消息触达规范

### 6.1 平台规则遵守

- 邮件渠道：严格遵守邮件服务商单日发送配额；主题/正文不得包含违规词
- 飞书机器人：遵守飞书开放平台机器人调用频率限制（默认 100 次/分钟）
- 企业微信：遵守企业微信消息推送规则与频率限制
- 所有渠道必须在 `core/send_core/account_pool.py` 中配置账号池并开启轮转

### 6.2 敏感词检测

- `core/send_core/content_risk.py` 发送前必检敏感词
- 敏感词库可通过 `configs/settings.py` 扩展（支持自定义词库）
- 命中敏感词的消息**强制阻断发送**并记录高危审计日志
- 模板消息与动态参数分别检测（避免模板合规但参数拼接出违规内容）

### 6.3 多账号负载均衡

- `core/send_core/account_pool.py` 将发送请求均匀分配到账号池中的可用账号
- 每个账号维护独立的发送计数器与冷却时间
- 账号被封禁/被限流时自动从可用池移除，并触发告警通知管理员
- 管理员可在 Web 管理后台 `channels/` 页面手动添加/启用/禁用账号

### 6.4 失败自动重试

- `core/send_core/failure_retry.py` 实现指数退避重试（1s → 2s → 4s → 8s → 16s，最多 5 次）
- 发送失败时保留失败原因，写入 `send_records` 表，方便后台排查
- 5 次重试仍失败则标记为「永久失败」，不再次自动重试，需人工处理
- 失败原因在 Web 管理后台 `channels/` 页面可视化展示

### 6.5 发送额度可视化

- 每个渠道/账号维护当前发送计数、剩余配额、下一次配额刷新时间
- 数据在 Web 管理后台 `channels/` 页面展示，额度临近上限时黄色告警、达到上限红色告警
- 超额度时自动切换备用账号；全部耗尽时阻断发送并触发全局告警

---

## 7. Git 提交规范

### 7.1 分支规范

| 分支名 | 说明 | 允许推送 | 合并方式 |
|--------|------|---------|---------|
| `main` | 生产主分支（稳定、可部署） | ❌ 禁止直接推送 | 通过 PR 合并 |
| `dev` | 开发集成分支 | ✅ 团队成员（建议通过 PR） | PR 合并 |
| `feature/T##_xxx` | 新功能开发 | ✅ 开发者本人 | Merge / Squash |
| `fix/T##_xxx` | 功能修复 | ✅ 开发者本人 | Merge / Squash |
| `hotfix/xxx` | 线上紧急修复 | ✅ 维护者 | 经 review 后直接 Merge |
| `chore/xxx` | 配置/文档/CI 调整 | ✅ 开发者本人 | Merge |

**分支命名格式**：`<类型>/<T##或issue-id>_<中文或英文简明描述>`，示例：
- `feature/T14_web_admin_management`
- `fix/T08_alert_not_triggered_when_rate_exceeded`
- `hotfix/login_session_expired_redis_disconnect`

### 7.2 提交消息格式（强制执行）

**格式**：
```
<type>(T##): <中文简要说明>
```

**`<type>` 枚举**：

| 类型 | 含义 | 使用场景 |
|------|------|---------|
| `feat` | 新功能 | 新增业务能力、模块、API（如 feat(T14): Web 管理后台基础框架） |
| `fix` | Bug 修复 | 修复代码缺陷、运行异常、逻辑错误 |
| `docs` | 文档更新 | README、DEVELOP_RULES、docs/ 下文档变更 |
| `refactor` | 代码重构 | 重命名/抽取函数/结构调整，**无功能变更** |
| `test` | 测试补充 | 新增/修改 `tests/test_t##_*.py` |
| `chore` | 构建/工具/配置 | 更新 `requirements.txt`、Dockerfile、CI 脚本 |
| `style` | 代码格式调整 | 仅空格、缩进、换行等格式调整，不涉及逻辑 |
| `perf` | 性能优化 | 提升性能但无功能变更 |

**提交示例（推荐写法）**：

```bash
# 新功能
feat(T14): 新增 Web 管理后台登录与会话管理

# Bug 修复（写清楚修复内容）
fix(T08): 修复消息发送频率超限时未触发全局告警的问题

# 文档
docs(T15): 同步 README 架构图与 DEVELOP_RULES 跨层调用矩阵

# 重构（明确说明不改变功能）
refactor(T10): 抽取清洗流水线公共步骤到 Mixin 类

# 测试
test(T14): 补充登录过期与 CSRF 场景的单元测试

# 依赖/配置
chore: 更新 requirements.txt 中 fastapi 版本至 0.111
```

**禁止的写法**：
```bash
git commit -m "update"            # 无意义，信息为零
git commit -m "fix bug"           # 无任务编号、无具体内容
git commit -m "feat: something"   # 缺任务编号
git commit -m "Feat(T14) xxx"     # 大小写不规范
git commit -m "feat(T14) xxx"     # 缺冒号
```

### 7.3 单次提交粒度

- **一个功能 / 一个修复 = 一次提交**，禁止一次提交中混杂多个不相关变更
- 单份提交的修改行数建议控制在合理范围；大变更拆分多份提交，每份附完整说明
- 提交前本地执行对应任务的单元测试（`pytest tests/test_t##_*.py`），确认全部通过

### 7.4 PR / Merge Request 流程

1. 从 `main` 创建 `feature/T##_xxx` 分支
2. 完成开发与本地自测
3. 提交 PR，标题使用与 commit 相同的格式（如 `feat(T14): Web 管理后台基础框架`）
4. PR 描述中包含：**改动说明**、**影响范围**、**测试结果摘要**、**相关任务编号**
5. 至少 1 人 review 通过后合并至 `main`
6. 合并后删除已合并分支

---

## 8. 测试与交付规范

### 8.1 单元测试要求

- **每个任务（T##）必须对应至少一份测试文件**：`tests/test_t##_<module>.py`
- 核心类 / 核心函数 / API 端点必须覆盖：
  - **正常路径**（Happy path）
  - **异常路径**（参数缺失、配置错误、外部依赖失败）
  - **边界条件**（空输入、超长输入、最大/最小值）
- 测试文件按模块组织，禁止单文件超过 1000 行
- `tests/conftest.py` 提供全局共享 fixture：临时 SQLite 数据库、Redis mock、FastAPI TestClient、mock 消息渠道等
- 测试命名：`test_<场景>_<期望行为>`（示例：`test_login_valid_credentials_returns_session_token`）
- 所有测试**必须可离线运行**（不依赖真实 Redis / 真实网络）：使用 mock 或临时实例
- 使用 `pytest`：
  ```bash
  pytest tests/ -v --tb=short           # 全量
  pytest tests/test_t14_web_admin.py -v # 指定任务
  ```

### 8.2 集成测试要求

- 每个业务模块提供从「输入 → 处理 → 输出」的端到端测试（如爬虫抓取 → 清洗 → 入库）
- L4 接入层必须测试 `/health`、登录、各页面路由、核心 API 返回码
- 异步任务队列必须覆盖：提交 → 状态轮询 → 结果获取 → 取消 → 重试

### 8.3 联调验收标准

新功能 / 修复合入 `main` 前必须通过以下清单检查：

| 检查项 | 标准 |
|-------|------|
| 单元测试 | `tests/test_t##_*.py` 全部通过 |
| 代码风格 | 符合 DEVELOP_RULES.md 第 2 节规范 |
| 接口回归 | `GET /docs` 中所有端点 schema 无破坏式变更 |
| 文档同步 | README 能力说明 / DEVELOP_RULES 相应章节已更新 |
| 手动验证 | 在本地 `python -m adapter.main` 实际操作一遍核心场景 |
| 敏感信息 | 提交中无 `.env`、密钥、真实手机号 / 邮箱等 |

### 8.4 版本迭代与文档同步

- 每次 `main` 分支合入后，若涉及对外 API 变更，**必须同步更新 README 的接口说明**
- 若涉及新增配置项，**必须同步更新 `.env.example`**
- 架构调整（如新增分层目录、新增业务模块）必须同步更新 README 架构图与目录树

### 8.5 部署与回滚

- 默认零配置可运行（SQLite + 内存缓存），生产环境建议 MySQL + Redis
- 部署前执行：`python -m adapter.main` 本地启动并验证 `/health` 通过
- 版本回滚使用 `git revert <commit-id>` 而非 force push
- 重大变更前建议做数据库备份（详见 README FAQ Q6）

---

## 附录 A：术语表

本仓库文档与代码命名统一使用以下术语，出现不一致时以此表为基准纠正：

| 中文术语 | 英文 / 缩写 | 对应代码符号 | 说明 |
|---------|------------|-------------|------|
| 商机线索 | Lead | `Lead`、`lead_` | 结构化的潜在客户数据 |
| 爬虫 | Spider / Crawl | `spider_`、`crawl_` | 从网络自动采集数据 |
| 触达 | Send | `send_`、`channel_` | 通过邮件/飞书/企微/H5 发送消息 |
| 渠道 | Channel | `Channel`、`channel_` | 具体发送渠道（email/feishu/wechat/h5） |
| 账号 | Account | `Account`、`account_` | 渠道账号池中的单个账号 |
| 会话 | Session | `session_` | 登录后的 Redis 会话 |
| 脱敏 | Mask / PII Mask | `mask_`、`pii_mask` | 隐私字段掩码展示 |
| 加密 | Encrypt | `crypto_`、`sensitive_crypto` | 敏感字段存储加密 |
| 告警 | Alert | `alert_` | 通过钉钉/飞书/Webhook 推送异常 |
| 流水线 | Pipeline | `pipeline_` | 多步骤串联处理流程 |
| 注册表 | Registry | `registry.py` | 模块对外注册与调用入口 |
| 漏斗 | Funnel | `funnel_` | 商机转化漏斗统计 |

---

## 附录 B：跨层调用错误示例速查

| 错误做法 | 为什么错 | 正确做法 |
|---------|---------|---------|
| `business/multi_spider/` 中直接 import `adapter/main.py` | L3 依赖 L4，违反分层原则 | 将需要的能力下沉为公共 API 或通用函数 |
| `core/spider_core/` 中实现某特定网站登录逻辑 | L2 写入业务细节，丧失通用性 | 在 `business/multi_spider/sources/` 下实现特定源登录 |
| `infra/db_base.py` 中 import `business/` | L1 反向依赖 L3 | 数据库层保持纯 ORM，业务逻辑放 L3 |
| L4 直接 import 业务模块私有符号 | 破坏模块边界 | 通过 `registry.py` 的公共 API 调用 |
| `infra/exceptions.py` 定义具体业务异常 | L1 不承载业务语义 | 业务异常放在对应 L3 模块（或 infra 中作为通用异常） |

---

*最后更新：docs(T15) 同步至 T01-T14 最新实现。*
