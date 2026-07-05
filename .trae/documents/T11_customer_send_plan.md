# T11 多渠道自动化商机触达 — 开发计划

> 目标：在 `business/customer_send` 搭建完整业务层，基于 T02~T10 基础设施与 T06/08 风控底座实现邮件/企业微信/飞书/H5 落地页四渠道商机触达，消息统一走 `core.send_core.SendPipeline.send()` 确保"风控→限流→账号池→重试→状态持久化"五层复用，业务层只做渠道协议与消息模板的差异化实现。

---

## 一、新增文件清单（按责任拆分）

### 1. 配置 / 模板层（4 文件）

| 文件 | 作用 |
| --- | --- |
| `configs/settings.py`（修改） | 新增 `CustomerSendSettings` — 渠道开关、H5 域名、批量上限、模板目录、API 密钥名等，全部走 `.env` 注入 |
| `configs/templates/email_default.html` | 邮件富文本模板（客户名、商机标题、行业标签、落地页链接等 `{{变量}}`） |
| `configs/templates/wechat_card.json` | 企业微信卡片消息模板（字段替换 `{{name}}` / `{{opportunity_id}}`） |
| `configs/templates/feishu_card.json` | 飞书机器人卡片消息模板（同风格 JSON） |

> 注：目录 `configs/templates/` 已符合项目约定（不新增新目录前缀，仅在既有 `configs/` 下补充子目录）。

---

### 2. 数据模型（1 文件）

| 文件 | 作用 |
| --- | --- |
| `business/customer_send/models.py` | Pydantic 模型：发送入参、发送结果、触达行为埋点、H5 页面定义 |

**核心结构定义：**

```python
# 2.1 发送入参
class SendTarget(BaseModel):
    """单个商机触达目标。"""
    opportunity_id: str
    tenant_id: str
    customer_name: str               # 客户名称（发送前强制脱敏）
    contact_email: str | None = None
    contact_phone: str | None = None
    contact_wechat: str | None = None
    contact_feishu: str | None = None
    contact_industry: str | None = None
    contact_region: str | None = None
    need_keywords: list[str] = []
    opportunity_title: str = ""
    opportunity_score: int = 0
    landing_page_url: str | None = None

class BatchSendParams(BaseModel):
    """批量触达任务入参。"""
    task_id: str
    tenant_id: str
    channels: list[str]               # ["email", "wechat", "feishu"]
    template_name: str = "default"
    targets: list[SendTarget]
    dry_run: bool = False             # True 时只校验模板不真实发送
    enable_h5: bool = False           # 是否生成 H5 落地页并嵌入短信/邮件
    batch_size: int = 50              # 单批次并发上限（仅对调用者节流）
    caller: str | None = None         # 记录触发方（queue / scheduler / api）

# 2.2 发送结果
class SingleSendResult(BaseModel):
    send_id: str                      # hash(task_id + channel + opportunity_id)
    channel: str
    opportunity_id: str
    success: bool
    status: str                       # SendStatus.value
    reason: str | None = None
    masked_recipient: str             # 脱敏后的收件人，日志/监控使用
    attempts: int = 0
    account_id: str | None = None
    cost_ms: int = 0
    h5_page_url: str | None = None

class BatchSendResult(BaseModel):
    task_id: str
    status: str                       # "ok" / "partial" / "failed"
    total: int
    success: int
    failed: int
    blocked: int
    rate_limited: int
    details: list[SingleSendResult]
    started_at: str
    finished_at: str

# 2.3 触达行为埋点
class SendBehaviorLog(BaseModel):
    behavior_id: str
    tenant_id: str
    opportunity_id: str
    channel: str
    event: str                        # "sent" / "opened" / "clicked" / "submitted" / "bounced"
    recipient_masked: str
    h5_page_id: str | None = None
    http_path: str | None = None
    payload_snapshot: dict = {}       # 表单提交时的字段快照
    remote_ip_masked: str | None = None
    user_agent_hash: str | None = None
    created_at: str

# 2.4 H5 落地页定义
class H5PageSpec(BaseModel):
    page_id: str
    tenant_id: str
    opportunity_id: str
    customer_name_masked: str
    industry: str | None = None
    region: str | None = None
    keywords: list[str] = []
    title: str
    summary: str
    cta_label: str = "立即报名"
    form_fields: list[dict] = []     # 例如 [{"name":"phone","type":"tel","required":true}]
    expire_at: str | None = None
```

---

### 3. 模板引擎（1 文件）

| 文件 | 作用 |
| --- | --- |
| `business/customer_send/template_engine.py` | `{{var}}` 变量替换 + 模板文件按需懒加载 + 未知字段占位符 fallback |

**实现要点：**
- 不引入 Jinja2，保持零第三方依赖；自己实现 `{{kebab_case_key}}` 与 `{{snake_case_key}}` 两种写法。
- 安全：渲染前对 `SendTarget` 内 `contact_email/contact_phone/contact_wechat/contact_feishu/customer_name` 调用 `core.compliance.pii_mask.auto_mask()` 做脱敏，确保任何模板渲染输出都不含明文隐私。
- 缺失字段默认渲染为 `—` 而不是暴露 `{{unknown_key}}` 原样字符串。
- 暴露两个公共方法：
  - `render(template_name: str, variables: dict) -> str`
  - `render_from_string(template_str: str, variables: dict) -> str`

---

### 4. 渠道驱动（4 文件）

> 每个驱动都遵循"同一契约"：输入 `(account: Account, recipient: str, content: str, extra: dict)`、输出 `(bool: ok, int|None: status_code, str: message)`，作为 `sender_fn` 注入 `SendPipeline.send()`。

| 文件 | 作用 |
| --- | --- |
| `business/customer_send/channels/email_channel.py` | SMTP + HTML + 附件 + bounce 识别；走 `smtplib` / `email.mime` 标准库，支持 SSL/TLS |
| `business/customer_send/channels/wechat_channel.py` | 企业微信"客户联系"API + 群消息 webhook 两种模式，用 `requests.post` |
| `business/customer_send/channels/feishu_channel.py` | 飞书自定义机器人消息 + 交互式卡片，用 `requests.post` |
| `business/customer_send/channels/h5_landing.py` | H5 落地页：动态 HTML 生成 + 页面短链 ID + 埋点表单路由（后端可挂载） |

**契约形式（统一抽象）：**

```python
@dataclass
class ChannelAdapter:
    name: str                  # "email" / "wechat" / "feishu"

    def build_recipient(self, target: "SendTarget") -> str:
        """返回该渠道的收件人字符串（未脱敏）。"""

    def build_content(self, target: "SendTarget", rendered_template: str) -> str:
        """返回该渠道的消息体（HTML / JSON / 纯文本）。"""

    def send(self, account: Account, recipient: str, content: str,
             extra: dict | None = None) -> tuple[bool, int | None, str]:
        """send_core.SendPipeline 需要的 sender_fn 签名。"""
```

**邮件驱动要点：**
- SMTP 配置走 `settings.customer_send.EMAIL_SMTP_HOST / PORT / USER / PASSWORD / USE_SSL`（由 `.env` 注入）。
- 若 `account.token == "smtp_fallback"` 使用全局 SMTP 配置；否则 `account.token` 视为自定义 SMTP 凭据 JSON。
- 附件：`extra["attachments"] = [{"filename": "x.pdf", "content_b64": "..."}]`（可选）。
- 退信：发送异常时判断 `smtplib.SMTPRecipientsRefused`，在 `message` 里标注 `"bounced"`，由 pipeline 调用 `task_status_store.mark_failed` 持久化。

**企业微信驱动要点：**
- 走 `account.token` 为 webhook URL，payload 走 `markdown` 或 `interactive` 卡片。
- 支持 `extra["mode"] == "group"` 走群消息，默认 `private` 走客户联系接口。

**飞书驱动要点：**
- `account.token` 为飞书机器人 webhook，payload 走 `interactive` 卡片 + `msg_type=interactive`。

**H5 驱动要点（不是 sender_fn，独立调用）：**
- `generate_page(spec: H5PageSpec) -> str` 返回完整 HTML。
- `page_id = hash(tenant_id + opportunity_id + version)` 支持幂等。
- `short_url = f"{settings.customer_send.H5_BASE_URL}/p/{page_id}"` 供其它渠道在模板里用 `{{h5_url}}` 嵌入。
- 访问统计由 `storage.record_behavior(event="opened" / "clicked" / "submitted")` 写数据库。

> 注意：不实现实际 HTTP 服务路由（这是 web 框架层职责，不在本模块范围内）；但会暴露一个 `h5_landing.render_page_html(page_id)` 便于业务框架接入，单测直接调用这个函数验证 HTML 输出。

---

### 5. 持久化层（2 文件）

| 文件 | 作用 |
| --- | --- |
| `business/customer_send/_orm.py` | SQLAlchemy 表模型 + `ensure_tables()`：`customer_send_job`、`customer_send_behavior` |
| `business/customer_send/storage.py` | upsert 逻辑，调用 `infra.db_base.database.bulk_insert() / upsert()` |

**表定义：**

```sql
-- 发送任务表（1 行/task）
CREATE TABLE customer_send_job (
    id BIGSERIAL PRIMARY KEY,
    task_id VARCHAR(128) NOT NULL,
    tenant_id VARCHAR(64) NOT NULL,
    channels VARCHAR(64)[] NOT NULL DEFAULT '{}',
    total INT NOT NULL DEFAULT 0,
    success INT NOT NULL DEFAULT 0,
    failed INT NOT NULL DEFAULT 0,
    blocked INT NOT NULL DEFAULT 0,
    rate_limited INT NOT NULL DEFAULT 0,
    status VARCHAR(16) NOT NULL DEFAULT 'PENDING',
    caller VARCHAR(32),
    started_at TIMESTAMP NOT NULL DEFAULT NOW(),
    finished_at TIMESTAMP,
    created_at TIMESTAMP NOT NULL DEFAULT NOW(),
    UNIQUE(tenant_id, task_id)
);

-- 行为埋点表（1 行/事件）
CREATE TABLE customer_send_behavior (
    id BIGSERIAL PRIMARY KEY,
    behavior_id VARCHAR(128) NOT NULL,
    tenant_id VARCHAR(64) NOT NULL,
    opportunity_id VARCHAR(128) NOT NULL,
    channel VARCHAR(16) NOT NULL,
    event VARCHAR(16) NOT NULL,              -- sent/opened/clicked/submitted/bounced
    recipient_masked VARCHAR(256),
    h5_page_id VARCHAR(128),
    http_path VARCHAR(256),
    payload_snapshot JSONB DEFAULT '{}',
    remote_ip_masked VARCHAR(64),
    user_agent_hash VARCHAR(64),
    created_at TIMESTAMP NOT NULL DEFAULT NOW(),
    UNIQUE(tenant_id, behavior_id)
);
```

**SQLAlchemy side：** 参照 `business/data_clean/_orm.py` 风格，`Base = declarative_base()` + 两个 Table 类 + `ensure_tables()` 调 `database.engine` 创建表（失败时静默，测试友好）。

---

### 6. 流水线编排（1 文件）

| 文件 | 作用 |
| --- | --- |
| `business/customer_send/pipeline.py` | `CustomerSendPipeline.run(params: BatchSendParams) -> BatchSendResult`，串起"模板渲染 → H5 生成 → send_core pipeline → 行为埋点 → 告警" |

**执行流：**

```
BatchSendParams
    │
    ├─ 预处理：对每个 target
    │     ├─ 脱敏 contact_* / customer_name（PIIMask.auto_mask）
    │     ├─ 检查风控拦截（content_risk.check_content 预检标题+摘要）
    │     └─ 生成可选 H5：h5_landing.generate_page(spec)
    │
    ├─ 对每个 enabled channel × target:
    │     ├─ build_recipient + build_content + template_engine.render
    │     ├─ send_pipeline.send(task_id, channel, content, recipient,
    │                              user_id=opportunity_id, extra={...})
    │     └─ 根据 SendPipelineResult：
    │           · SUCCESS → record_behavior("sent")
    │           · FAILED / BANNED → record_behavior("bounced" / "failed")
    │           · CONTENT_BLOCKED → blocked += 1，记录到结果
    │           · RATE_LIMITED → rate_limited += 1
    │
    ├─ 统计：total / success / failed / blocked / rate_limited
    │
    ├─ 阈值判断：
    │     · blocked_ratio > CUSTOMER_SEND_BLOCKED_ALERT_RATIO
    │       → alert_service.service_exception_sync()
    │     · failed_ratio > CUSTOMER_SEND_FAILED_ALERT_RATIO
    │       → 同样告警
    │
    └─ 持久化：storage.upsert_job(BatchSendResult)
```

**关键设计决策：**
- 不自己写限流/账号池/敏感词校验逻辑 — 100% 走 `send_pipeline.send()`。
- 对"批量发送失败"，使用 `SendPipeline` 自带的重试策略（默认 5 次 + 指数退避），业务层只做结果统计与告警。
- 单测注入：`send_pipeline._account_pool = mock_pool`；或将一个 `mock_sender: Callable` 作为 `extra["__mock_sender__"]` 注入，驱动层优先使用 mock sender，便于测试无网络依赖。

---

### 7. 公共入口与导出（2 文件）

| 文件 | 作用 |
| --- | --- |
| `business/customer_send/registry.py` | `run_batch(params: BatchSendParams) -> BatchSendResult`、`async_run(params) -> str`（queue 模式仅调用 `infra.task_queue.enqueue` 把任务交给 worker，立即返回 task_id）、`list_runs(tenant_id)`（返回最近 24h 状态） |
| `business/customer_send/__init__.py`（修改） | `__all__ = ["BatchSendParams", "BatchSendResult", "SendTarget", "H5PageSpec", "run_batch", "async_run", "list_runs"]` |

**队列与定时任务：**
- `async_run(params)` = `infra.task_queue.enqueue("customer_send:run_batch", params.model_dump())`。注意 worker 侧在 `infra.task_queue` 的 handler 字典里需要注册 `"customer_send:run_batch"` → `run_batch`。T11 不修改 `infra/`，仅在 `registry.py` 里暴露一个字符串常量 `TASK_HANDLER_NAME = "customer_send:run_batch"`，并在模块级定义 `def _queue_handler(payload_dict) -> dict: return run_batch(BatchSendParams(**payload_dict)).model_dump()` 供外部注册。
- 定时任务：`business/customer_send` 不做 schedule 配置，只暴露 `run_batch` 入口，调用方（API/CLI）自行调度。

---

### 8. 单元测试（1 文件）

| 文件 | 作用 |
| --- | --- |
| `tests/test_t11_customer_send.py` | 10+ 个用例覆盖：模板渲染、PII 脱敏、4 渠道各自的 sender_fn 无网络 dry-run、send_pipeline 注入 mock 的完整链路、H5 页面生成、批量幂等、存储层 upsert、告警触发阈值 |

---

## 二、数据流转示意图

```
 ┌─────────────────────────────────────────────────────────────────────────────┐
 │ OpenClaw 智能体 / 定时任务 / 外部 API 调用                                    │
 └──────┬──────────────────────────────────────────────────────────────────────┘
        │ 构造 BatchSendParams(channel=[...], targets=[...], enable_h5=True)
        ▼
 ┌────────────────────────────── business/customer_send ──────────────────────────────┐
 │                                                                                      │
 │   registry.run_batch(params)                                                         │
 │       │                                                                              │
 │       ▼                                                                              │
 │   pipeline.CustomerSendPipeline.run(params)                                          │
 │       │                                                                              │
 │       ├─ 1. template_engine.render(...) ─ 从 configs/templates/ 加载模板 + 变量替换 │
 │       │    （变量字典含：customer_name_masked、industry、region、keywords、score、   │
 │       │     h5_url、opportunity_id 等）                                               │
 │       │                                                                              │
 │       ├─ 2. channels.h5_landing.generate_page(spec) ─ 动态生成 H5（可选）            │
 │       │    返回 page_id + 短链供模板用 {{h5_url}}                                     │
 │       │                                                                              │
 │       ├─ 3. 对每个 target × channel：                                                 │
 │       │     channels.XChannel.build_recipient(target)                                │
 │       │     channels.XChannel.build_content(target, rendered)                       │
 │       │     ▼                                                                        │
 │       │     core.send_core.SendPipeline.send(channel=...,                            │
 │       │         sender_fn=XChannel.send, recipient=..., content=...)                 │
 │       │         │                                                                    │
 │       │         └─ 内部依次走：ContentRisk（T06）→ AccountPool（账号均衡）→          │
 │       │            RateLimiter（限流）→ sender_fn → Retry/ban → TaskStatusStore     │
 │       │                                                                              │
 │       ├─ 4. storage.upsert_job / record_behavior — 持久化任务与行为事件              │
 │       │                                                                              │
 │       └─ 5. infra.alerting.alert_service.service_exception_sync(...) — 批量异常告警  │
 │                                                                                      │
 └──────────────────────────────────────┬───────────────────────────────────────────────┘
                                        │
                                        ▼
            ┌───────────────────────────────────────────────────────┐
            │ 输出：BatchSendResult（JSON / model_dump()）          │
            │   结构化对齐 OpenClaw：{task_id, status, counts[],    │
            │     details:[{send_id,channel,success,status,masked}] │
            └───────────────────────────────────────────────────────┘
```

---

## 三、实体字段规则（模板变量字典）

任何渠道的模板都可以使用以下变量（调用 `SendTarget → dict` 得到），模板引擎按 `{{var_name}}` 做字面替换：

| 变量 | 来源 | 约束 |
| --- | --- | --- |
| `customer_name` | `SendTarget.customer_name` | **强制脱敏** — PIIMask 作用 |
| `contact_email` | `SendTarget.contact_email` | **强制脱敏** — 仅在收件人字段保留原始值 |
| `contact_phone` | `SendTarget.contact_phone` | **强制脱敏** |
| `contact_wechat` | `SendTarget.contact_wechat` | **强制脱敏** |
| `industry` | `SendTarget.contact_industry` | 直接暴露 |
| `region` | `SendTarget.contact_region` | 直接暴露 |
| `need_keywords_csv` | `",".join(SendTarget.need_keywords)` | 直接暴露 |
| `opportunity_id` | `SendTarget.opportunity_id` | 直接暴露 |
| `opportunity_title` | `SendTarget.opportunity_title` | 直接暴露 |
| `opportunity_score` | `str(SendTarget.opportunity_score)` | 直接暴露 |
| `h5_url` | H5 生成返回值；未开启 H5 则为空串 | 直接暴露 |
| `tenant_id` | `SendTarget.tenant_id` | 直接暴露 |
| `send_date` | `datetime.now().strftime("%Y-%m-%d")` | 自动注入 |

> **Rule：** `customer_name / contact_*` 类字段，在进入模板引擎之前必须被 PIIMask 替换；`build_recipient()` 返回原始值但仅在 `SendPipeline.send` 的 `recipient` 参数内部使用，**不会出现在 output/日志**，日志里由 `RiskCheckResult.masked_recipient` 提供脱敏形态。

---

## 四、异常数据池 / 行为埋点规则

- **CONTENT_BLOCKED**：写 `customer_send_behavior(event="blocked")`，在 `BatchSendResult.blocked` 计数，不重试。
- **RATE_LIMITED**：写 `customer_send_behavior(event="rate_limited")`，在 `BatchSendResult.rate_limited` 计数，按 `send_core` 内部策略自动重试。
- **FAILED / BANNED**：在 `customer_send_behavior` 写事件（`event="failed_banned"`），在 `BatchSendResult.failed` 计数，**不重试**（已由 send_core 重试到极限）。
- **opened / clicked / submitted**：由外部 HTTP 层调用 `storage.record_behavior(event=...)` 写入数据库，T11 业务层只暴露接口但不实现路由。
- **批量异常告警**：`blocked / total > CUSTOMER_SEND_BLOCKED_ALERT_RATIO` 或 `failed / total > CUSTOMER_SEND_FAILED_ALERT_RATIO` 时，走 `alert_service.service_exception_sync("customer_send:batch_risk", ...)`。

---

## 五、分步执行开发流程（10 步，顺序依赖关系）

```
Step 1: configs/settings.py 新增 CustomerSendSettings（configs/templates/*.html/json 同时准备）
Step 2: business/customer_send/models.py — Pydantic 模型
Step 3: business/customer_send/template_engine.py — 变量替换引擎
Step 4: business/customer_send/channels/email_channel.py + (wechat_channel.py + feishu_channel.py)
Step 5: business/customer_send/channels/h5_landing.py
Step 6: business/customer_send/_orm.py + storage.py — 表模型与 upsert
Step 7: business/customer_send/pipeline.py — 完整流水线编排
Step 8: business/customer_send/registry.py + __init__.py（更新）
Step 9: tests/test_t11_customer_send.py — 全量单元/集成测试（无网络依赖）
Step 10: feat(T11) 提交
```

**开发约束（强制）：**
1. 严格遵守 `DEVELOP_RULES.md`（不修改 README / docs / infra / core 层）。
2. 所有 SMTP / webhook / H5 域名 / 批量上限走 `.env` → `CustomerSendSettings`，禁止源码硬编码。
3. 限流、账号均衡、敏感词检测 100% 走 `core.send_core`。
4. 不新增、删除、重命名目录（除 `configs/templates/` 子目录外）。
5. 不写爬虫、销售分配、数据清洗逻辑。
6. 所有隐私字段在进入模板引擎前强制脱敏，只在真正的 `sender_fn` 内部使用原始值。

---

## 六、配置项（`.env` 字段）

| 字段 | 默认 | 说明 |
| --- | --- | --- |
| `SEND_CHANNELS` | `wechat,feishu,email` | 已在 send_core 存在；继续沿用 |
| `CUSTOMER_SEND_EMAIL_ENABLED` | `true` | 是否启用邮件通道 |
| `CUSTOMER_SEND_WECHAT_ENABLED` | `true` | 是否启用企业微信通道 |
| `CUSTOMER_SEND_FEISHU_ENABLED` | `true` | 是否启用飞书通道 |
| `CUSTOMER_SEND_H5_ENABLED` | `false` | 是否在默认模式下生成 H5 落地页 |
| `CUSTOMER_SEND_H5_BASE_URL` | `https://claw.example.com` | H5 页面对外域名前缀 |
| `CUSTOMER_SEND_BATCH_SIZE_DEFAULT` | `50` | 单批最大并发数（对业务层节流） |
| `CUSTOMER_SEND_BLOCKED_ALERT_RATIO` | `0.1` | CONTENT_BLOCKED 占比超过此阈值触发告警 |
| `CUSTOMER_SEND_FAILED_ALERT_RATIO` | `0.2` | FAILED 占比超过此阈值触发告警 |
| `CUSTOMER_SEND_TEMPLATE_DIR` | `configs/templates` | 模板文件根目录（相对项目根） |
| `CUSTOMER_SEND_VERSION` | `T11-v1.0` | pipeline 标识，用于行为日志 |

> `configs/settings.py` 里新增一个 `class CustomerSendSettings(BaseSettings)`，并在 `AppSettings` 的字段 `customer_send: CustomerSendSettings = Field(default_factory=CustomerSendSettings)`。
