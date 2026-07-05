# T12 销售商机调度 / 自动分配 / 多级跟进提醒 / 逾期告警 — 开发计划

## 一、仓库调研结论

**已有目录与复用点：**
- `business/customer_send/` — T11 已完成的多渠道触达模块，包含：
  - `registry.py` → `run_batch(params)` 同步入口、`async_run(params)` 队列入口
  - `channels/wechat_channel.py`、`channels/feishu_channel.py` — 复用作为推送渠道
  - `template_engine.py` — 消息模板 `{{var}}` 渲染 + PII 脱敏
  - `_orm.py` — 已建立 `customer_send_job` / `customer_send_behavior` 表模型
  - `storage.py` — 幂等 upsert 模式可直接复用
- `business/data_clean/_orm.py` — 结构化商机线索数据清洗结果表（`cleaned_opportunity`）
- `configs/settings.py` — `Settings` / `BaseSettings` 配置模型模式
- `infra/db_base.database` — SQLAlchemy 引擎 + `upsert` / `bulk_insert` 接口
- `infra/alerting.alert_service.service_exception_sync(...)` — 全局告警接口
- `infra/task_queue.task_queue.enqueue(name, payload)` — 异步队列接口

**当前状态：**
- `business/sales_task/` 目录已存在，但仅有空 `__init__.py`
- 需要新增：ORM 模型、数据模型、分配引擎、多级提醒引擎、状态流转引擎、漏斗统计引擎、消息推送联动、流水线编排、存储、公开入口、测试

---

## 二、新增文件清单（按功能拆分）

```
business/sales_task/
├── __init__.py                # 统一导出（重写）
├── _orm.py                    # SQLAlchemy 表模型 + ensure_tables
├── models.py                  # Pydantic 数据模型 + 枚举
├── storage.py                 # 商机/销售员/跟进记录/操作日志的 upsert 封装
├── assignment_engine.py       # 商机自动分配引擎（行业/地域/等级/负载均衡 + 权重）
├── reminder_engine.py         # 多级提醒引擎（分配通知 / 3天 / 7天 / 15天逾期）
├── status_engine.py           # 商机状态流转 + 销售操作（标签/跟进记录）
├── funnel_engine.py           # 商机漏斗统计（采集→清洗→触达→跟进→成交）
├── push_notifier.py           # 推送联动：复用 T11 渠道发送飞书/企微任务卡片
├── pipeline.py                # 总调度：自动分配 + 多级提醒刷新 + 逾期告警 + 漏斗刷新
└── registry.py                # 公开入口：run_batch / run_async / assign / remind / stats

tests/
└── test_t12_sales_task.py     # 单元测试（10+ 用例）

configs/
└── settings.py (修改)          # 追加 SalesTaskSettings 配置段
```

**总计：13 个文件（12 新增 + 1 修改）**

---

## 三、枚举与数据模型设计

### 3.1 商机状态枚举

```python
class OpportunityStatus(str, enum.Enum):
    NEW = "NEW"           # 刚入库未分配
    ASSIGNED = "ASSIGNED"   # 已分配销售
    FOLLOWING = "FOLLOWING"  # 跟进中（销售已首次联系）
    COMMUNICATING = "COMMUNICATING"  # 沟通中（客户有回复）
    HIGH_INTENT = "HIGH_INTENT"    # 意向高（明确需求/预算）
    CLOSED_WON = "CLOSED_WON"      # 成交
    LOST = "LOST"              # 流失
```

### 3.2 提醒级别枚举

```python
class ReminderLevel(str, enum.Enum):
    NOTIFY = "NOTIFY"       # 首次分配通知（绿色）
    FIRST = "FIRST"         # 3 天首次跟进提醒（蓝色）
    SECOND = "SECOND"       # 7 天二次回访（橙色）
    OVERDUE = "OVERDUE"     # 15 天逾期升级告警（红色）
    BATCH_OVERDUE = "BATCH_OVERDUE"  # 批量逾期 → 触发全局告警
```

### 3.3 Pydantic 数据模型

```python
class Salesperson(BaseModel):
    sales_id: str            # 销售员唯一 ID
    tenant_id: str
    name: str                # 姓名（脱敏后）
    industries: list[str] = Field(default_factory=list)   # 可处理行业
    regions: list[str] = Field(default_factory=list)      # 可处理地域
    min_score: int = 0      # 接受的最低商机分
    weight: float = 1.0     # 分配权重
    current_load: int = 0   # 当前在手商机数
    email: str | None = None
    wechat: str | None = None
    feishu: str | None = None
    group: str = "default"  # 销售分组


class Opportunity(BaseModel):
    opportunity_id: str
    tenant_id: str
    customer_name: str
    contact_email: str | None = None
    contact_phone: str | None = None
    industry: str | None = None
    region: str | None = None
    need_keywords: list[str] = Field(default_factory=list)
    score: int = 0
    status: str = "NEW"      # OpportunityStatus 值
    assigned_sales_id: str | None = None
    assigned_at: str | None = None        # ISO-8601
    last_follow_at: str | None = None      # ISO-8601
    tags: list[str] = Field(default_factory=list)
    source_batch_id: str | None = None     # 来源清洗批次
    created_at: str = Field(default_factory=lambda: datetime.utcnow().isoformat() + "Z")


class FollowUpRecord(BaseModel):
    follow_id: str
    opportunity_id: str
    tenant_id: str
    sales_id: str
    channel: str             # "wechat" / "phone" / "email" / "meeting"
    content: str             # 跟进内容摘要
    next_follow_at: str | None = None
    created_at: str = Field(default_factory=lambda: datetime.utcnow().isoformat() + "Z")


class SalesOperationLog(BaseModel):
    log_id: str
    tenant_id: str
    opportunity_id: str
    sales_id: str
    op_type: str             # "TAG_ADD" / "TAG_REMOVE" / "STATUS_CHANGE" / "ASSIGN"
    before_value: str | None = None
    after_value: str | None = None
    detail: str | None = None
    created_at: str = Field(default_factory=lambda: datetime.utcnow().isoformat() + "Z")


class AssignmentParams(BaseModel):
    task_id: str
    tenant_id: str
    opportunity_ids: list[str] | None = None   # None 表示处理全部 NEW 商机
    mode: str = "batch"                         # "batch" 定时 / "async" 高优
    dry_run: bool = False


class ReminderParams(BaseModel):
    task_id: str
    tenant_id: str
    custom_cycles: dict[str, int] | None = None  # 覆盖默认周期 {"FIRST": 3, ...}
    dry_run: bool = False


class FunnelStats(BaseModel):
    tenant_id: str
    period_start: str
    period_end: str
    collected: int = 0
    cleaned: int = 0
    reached: int = 0
    followed: int = 0
    closed_won: int = 0
    conversion_rates: dict[str, float] = Field(default_factory=dict)
```

---

## 四、数据表字段设计（SQLAlchemy 模型）

### 4.1 salesperson 表 — 销售员配置

| 字段 | 类型 | 说明 |
|---|---|---|
| sales_id | VARCHAR(64) | 主键 |
| tenant_id | VARCHAR(64) | 租户 |
| name | VARCHAR(64) | 姓名 |
| industries | JSON | 可处理行业列表 |
| regions | JSON | 可处理地域列表 |
| min_score | INT | 最低接受分数 |
| weight | FLOAT | 分配权重 |
| current_load | INT | 当前负载 |
| email | VARCHAR(128) | 邮箱（脱敏存储） |
| wechat | VARCHAR(128) | 企微（脱敏） |
| feishu | VARCHAR(128) | 飞书（脱敏） |
| group | VARCHAR(32) | 分组 |
| created_at | DATETIME | |
| updated_at | DATETIME | |

唯一约束：`(tenant_id, sales_id)`

### 4.2 opportunity 表 — 商机主表（用于销售流转）

| 字段 | 类型 | 说明 |
|---|---|---|
| opportunity_id | VARCHAR(128) | PK |
| tenant_id | VARCHAR(64) | |
| customer_name | VARCHAR(128) | 脱敏 |
| contact_email | VARCHAR(128) | 脱敏 |
| contact_phone | VARCHAR(64) | 脱敏 |
| industry | VARCHAR(64) | |
| region | VARCHAR(64) | |
| need_keywords | JSON | |
| score | INT | 商机分值 0-100 |
| status | VARCHAR(32) | NEW / ASSIGNED / ... / LOST |
| assigned_sales_id | VARCHAR(64) | 当前所属销售 |
| assigned_at | DATETIME | 分配时间 |
| last_follow_at | DATETIME | 最近跟进时间 |
| tags | JSON | 标签列表 |
| source_batch_id | VARCHAR(128) | 来源清洗批次 |
| created_at | DATETIME | |
| updated_at | DATETIME | |

索引：`(tenant_id, status)`、`(tenant_id, assigned_sales_id)`、`(tenant_id, assigned_at)`
唯一约束：`(tenant_id, opportunity_id)`

### 4.3 follow_up_record 表 — 跟进记录

| 字段 | 类型 | 说明 |
|---|---|---|
| follow_id | VARCHAR(128) | PK |
| tenant_id | VARCHAR(64) | |
| opportunity_id | VARCHAR(128) | |
| sales_id | VARCHAR(64) | |
| channel | VARCHAR(32) | wechat/phone/email/meeting |
| content | TEXT | 内容摘要 |
| next_follow_at | DATETIME | 下次跟进时间 |
| created_at | DATETIME | |

索引：`(tenant_id, opportunity_id, created_at desc)`
唯一约束：`(tenant_id, follow_id)`

### 4.4 sales_operation_log 表 — 操作日志（全生命周期可追溯）

| 字段 | 类型 | 说明 |
|---|---|---|
| log_id | VARCHAR(128) | PK |
| tenant_id | VARCHAR(64) | |
| opportunity_id | VARCHAR(128) | |
| sales_id | VARCHAR(64) | |
| op_type | VARCHAR(32) | TAG_ADD / TAG_REMOVE / STATUS_CHANGE / ASSIGN / REMIND |
| before_value | VARCHAR(256) | 变更前值 |
| after_value | VARCHAR(256) | 变更后值 |
| detail | TEXT | 备注 |
| created_at | DATETIME | |

索引：`(tenant_id, opportunity_id, created_at desc)`
唯一约束：`(tenant_id, log_id)`

### 4.5 sales_task_job 表 — 任务执行记录

| 字段 | 类型 | 说明 |
|---|---|---|
| job_id | VARCHAR(128) | PK |
| task_id | VARCHAR(128) | |
| tenant_id | VARCHAR(64) | |
| job_type | VARCHAR(32) | ASSIGN / REMIND / FUNNEL |
| processed | INT | 处理数 |
| assigned | INT | 分配数 |
| reminded | INT | 提醒数 |
| overdue_count | INT | 逾期数 |
| status | VARCHAR(16) | OK / PARTIAL / FAILED |
| detail | JSON | 详细结果 |
| started_at | DATETIME | |
| finished_at | DATETIME | |

唯一约束：`(tenant_id, task_id, job_type)`

---

## 五、核心业务逻辑设计

### 5.1 商机自动分配引擎（assignment_engine.py）

**输入：** 一批 status=NEW 的商机 + 销售员配置表

**输出：** 每个商机被分配到一个 sales_id（或保持未分配 + 记录原因）

**分配规则优先级（加权评分模型）：**

1. **行业匹配** — 销售员 `industries` 包含商机行业 → + `industry_weight` 分
2. **地域匹配** — 销售员 `regions` 包含商机地域 → + `region_weight` 分
3. **等级匹配** — 商机 `score >= 销售员 min_score` → + `score_weight` 分
4. **负载均衡** — 每个销售员的 **有效得分 / (current_load + 1)** 作为最终排序值
5. **权重调整** — 最终分数再 × `salesperson.weight`

**算法：**

```
for each opportunity in candidates:
    candidates = []
    for each salesperson in salespersons:
        if not industry_match: skip
        score = 0
        if industry_match: score += industry_weight
        if region_match:   score += region_weight
        if score_match:    score += score_weight
        # 负载均衡：分母用 (current_load + 1) 保证 load=0 优先
        final_score = score * salesperson.weight / (salesperson.current_load + 1)
        if final_score > 0: candidates.append((salesperson, final_score))

    if not candidates: mark "NO_SALES_MATCH" → 加入告警列表
    else: pick top final_score → 写入 assigned_sales_id / assigned_at
         → 销售员 current_load += 1
         → 写入 sales_operation_log (op_type=ASSIGN)
         → 触发 NOTIFY 级提醒推送（给销售）
```

**告警：** 当累计 NO_SALES_MATCH 数量超过 `batch_unassigned_alert_ratio`（默认 20%）时，触发 `alert_service.service_exception_sync("sales_task:大量商机无匹配销售")`。

### 5.2 多级提醒引擎（reminder_engine.py）

**默认周期（可通过 `custom_cycles` 覆盖）：**

| 级别 | 触发条件 | 推送渠道 |
|---|---|---|
| NOTIFY | 分配后立即（由分配引擎同步触发） | 飞书卡片 + 企微卡片（复用 T11） |
| FIRST | assigned_at 距今 ≥ 3 天 且 无任何 follow_up 记录 | 飞书/企微提醒 |
| SECOND | assigned_at 距今 ≥ 7 天 且 无 follow_up 记录或仅 1 条 | 飞书/企微 + 邮件摘要 |
| OVERDUE | assigned_at 距今 ≥ 15 天 且 status 仍未进入 HIGH_INTENT/LOST | 飞书/企微红色告警 + 邮件 + 全局告警 |

**自定义周期配置：**

```python
SalesTaskSettings:
    REMIND_CYCLE_DAYS_NOTIFY: int = 0    # 立即
    REMIND_CYCLE_DAYS_FIRST: int = 3
    REMIND_CYCLE_DAYS_SECOND: int = 7
    REMIND_CYCLE_DAYS_OVERDUE: int = 15
    OVERDUE_ALERT_THRESHOLD: int = 10    # 单次扫描超过此数量触发全局告警
    LONG_UNASSIGNED_THRESHOLD_DAYS: int = 7  # NEW 状态超 7 天未分配告警
```

**触发机制：**

- `batch_run_reminder(params)` → 扫描所有 ASSIGNED/FOLLOWING/COMMUNICATING 商机，对比 assigned_at/last_follow_at
- 使用 **幂等性**：每个 `(opportunity_id, reminder_level)` 只触发一次，由 `sales_operation_log` 的 `op_type=REMIND_{level}` 记录保证
- 每个提醒级别触发推送：调用 `push_notifier.push_to_sales(salesperson, level, opportunity)`

### 5.3 商机状态流转引擎（status_engine.py）

**暴露方法：**

```python
transition(opportunity_id, target_status, operator_sales_id, detail)
add_tag(opportunity_id, tag, operator_sales_id)
remove_tag(opportunity_id, tag, operator_sales_id)
record_follow_up(opportunity_id, sales_id, channel, content, next_follow_at)
```

**状态流转规则（防错）：**

```
NEW        → ASSIGNED（分配）
ASSIGNED   → FOLLOWING（首次跟进）/ LOST（直接流失）
FOLLOWING  → COMMUNICATING（客户有响应）/ HIGH_INTENT / LOST
COMMUNICATING → HIGH_INTENT / LOST / FOLLOWING
HIGH_INTENT → CLOSED_WON / LOST
CLOSED_WON / LOST → *不可逆向*（操作被拒绝并记录日志）
```

**每次变更都会：**
1. 更新 `opportunity.status` + `updated_at`
2. 写入 `sales_operation_log` (before_value / after_value / detail)
3. 如果是跟进记录 → 写入 `follow_up_record` + 更新 `opportunity.last_follow_at`

### 5.4 转化漏斗统计引擎（funnel_engine.py）

**漏斗五环节：**

| 环节 | 数据源 | 统计字段 |
|---|---|---|
| 采集量 | `cleaned_opportunity.created_at`（或 data_clean 原始表） | `collected` |
| 有效清洗线索 | `cleaned_opportunity.is_valid=True` | `cleaned` |
| 已触达客户 | `customer_send_behavior.event IN ('sent','opened','clicked')` | `reached` |
| 销售跟进 | `opportunity.status IN (FOLLOWING, COMMUNICATING, HIGH_INTENT, CLOSED_WON)` 且存在 follow_up_record | `followed` |
| 成交 | `opportunity.status = CLOSED_WON` | `closed_won` |

**转化率计算：**

```
cleaned_rate   = cleaned    / collected    (≥1 时)
reached_rate   = reached    / cleaned
followed_rate  = followed   / reached
won_rate       = closed_won / followed
end_to_end     = closed_won / collected
```

**存储：** 每次扫描生成一条 `funnel_stats` 行（周期内可覆盖），字段包含各环节数量和转化率。

### 5.5 推送联动（push_notifier.py）

**复用 T11 的发送能力：**

```python
from business.customer_send import render, async_run
from business.customer_send.models import BatchSendParams, SendTarget

class PushNotifier:
    def push_to_sales(self, salesperson, level: str, opportunity):
        # 1) 模板渲染（{{sales_name}} / {{customer_name}} / {{industry}} / {{days_since}} / {{level}}）
        # 2) 按销售配置的渠道选择：飞书优先，其次企微，再次邮件
        # 3) 封装成 BatchSendParams，调用 async_run 或直接通过 channel.send
        # 4) 行为记录：写入 sales_operation_log (op_type=REMIND_{level})
```

**保持对 T11 的弱耦合：** 如果 T11 不可用（send_core 异常），降级为 `direct.send()` 单条发送，不阻塞提醒主流程。

### 5.6 总调度流水线（pipeline.py）

```
SalesTaskPipeline.run_batch(params):
    1) 自动分配引擎 → 处理所有 NEW 商机
    2) 多级提醒引擎 → 扫描并触发 ASSIGNED/FOLLOWING/COMMUNICATING 提醒
    3) 逾期告警检查 → 批量逾期数 > OVERDUE_ALERT_THRESHOLD → 全局告警
    4) 长期未分配检查 → NEW 超 LONG_UNASSIGNED_THRESHOLD_DAYS → 全局告警
    5) 漏斗统计 → 计算本周期漏斗数据
    6) 写入 sales_task_job → upsert
    7) 返回 SalesTaskJobResult
```

---

## 六、配置项（追加到 configs/settings.py）

```python
class SalesTaskSettings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="SALES_TASK_", extra="ignore")

    # 分配权重
    ASSIGN_INDUSTRY_WEIGHT: float = 3.0
    ASSIGN_REGION_WEIGHT: float = 2.0
    ASSIGN_SCORE_WEIGHT: float = 1.0
    ASSIGN_MIN_SCORE_THRESHOLD: int = 20

    # 批量触发告警阈值
    BATCH_UNASSIGNED_ALERT_RATIO: float = 0.2
    OVERDUE_ALERT_THRESHOLD: int = 10
    LONG_UNASSIGNED_THRESHOLD_DAYS: int = 7

    # 多级提醒周期
    REMIND_CYCLE_DAYS_NOTIFY: int = 0
    REMIND_CYCLE_DAYS_FIRST: int = 3
    REMIND_CYCLE_DAYS_SECOND: int = 7
    REMIND_CYCLE_DAYS_OVERDUE: int = 15

    # 推送渠道开关（复用 T11）
    PUSH_FEISHU_ENABLED: bool = True
    PUSH_WECHAT_ENABLED: bool = True
    PUSH_EMAIL_ENABLED: bool = False

    # 漏斗统计周期
    FUNNEL_PERIOD_DAYS: int = 7
    FUNNEL_AUTO_REFRESH: bool = True

    # 日志等级
    LOG_LEVEL: str = "INFO"
```

在 `Settings` 主类中追加字段：
```python
sales_task: SalesTaskSettings = Field(default_factory=SalesTaskSettings)
```

---

## 七、分步执行开发流程

```
Step 1. 配置模型：修改 configs/settings.py 追加 SalesTaskSettings
         └─ 验证：.env 中可配置 SALES_TASK_* 前缀变量

Step 2. 数据模型：新增 business/sales_task/models.py
         └─ Opportunity / Salesperson / FollowUpRecord /
            SalesOperationLog / AssignmentParams / ReminderParams /
            FunnelStats / SalesTaskJobResult

Step 3. ORM 表模型：新增 business/sales_task/_orm.py
         └─ salesperson / opportunity / follow_up_record /
            sales_operation_log / sales_task_job / funnel_stats
            + ensure_tables()

Step 4. 存储封装：新增 business/sales_task/storage.py
         └─ upsert_opportunity() / upsert_salesperson() /
            upsert_follow_up() / append_operation_log() /
            upsert_job() / upsert_funnel()

Step 5. 自动分配引擎：新增 business/sales_task/assignment_engine.py
         └─ assign_batch() / score_candidate() / 告警触发

Step 6. 多级提醒引擎：新增 business/sales_task/reminder_engine.py
         └─ scan_and_remind() / compute_reminder_level() / 幂等控制

Step 7. 状态流转引擎：新增 business/sales_task/status_engine.py
         └─ transition() / add_tag() / remove_tag() / record_follow_up()

Step 8. 漏斗统计：新增 business/sales_task/funnel_engine.py
         └─ compute_funnel() / save_funnel_stats()

Step 9. 推送联动：新增 business/sales_task/push_notifier.py
         └─ push_to_sales()（复用 T11 channels）

Step 10. 流水线编排：新增 business/sales_task/pipeline.py
         └─ run_batch() / run_assignment() / run_reminder() /
            run_funnel_refresh()

Step 11. 公开入口：重写 business/sales_task/registry.py + __init__.py
         └─ run_batch() / run_async() / assign() / remind() /
            get_stats() / transition() / add_tag() / record_follow_up()

Step 12. 单元测试：新增 tests/test_t12_sales_task.py
         └─ 12+ 用例：模型验证 / 分配评分 / 多级提醒周期 /
            状态流转规则 / 漏斗计算 / 推送联动 / pipeline end-to-end

Step 13. 最终验证：运行 pytest 100% passed + 字节编译 OK
Step 14. 提交：feat(T12): 完成销售商机调度/自动分配/多级提醒/逾期告警闭环
```

---

## 八、依赖与风险

**外部依赖（均已存在）：**
- `pydantic` / `pydantic-settings` — 已在 `configs/settings.py` 使用
- `SQLAlchemy` — 已在 `business/customer_send/_orm.py` 使用
- `business.customer_send.*` — T11 推送联动入口
- `infra.db_base.database` — upsert / bulk_insert
- `infra.alerting.alert_service` — 全局告警
- `infra.task_queue.task_queue` — 异步任务

**风险与应对：**

| 风险 | 影响 | 应对方案 |
|---|---|---|
| T11 发送模块不可用 | 提醒推送失败 | `push_notifier` 内 try/catch，fallback 到 `channel.send()` 直连发送；行为日志仍落库 |
| data_clean 表不存在 | 漏斗统计缺采集量 | `funnel_engine` 处理表不存在异常，用 0 值填充并记录 warning 日志 |
| 销售员配置为空 | 无法分配 | 分配失败时标记 `NO_SALES_MATCH`，超过阈值触发全局告警 |
| 重复提醒 | 骚扰销售 | 用 `sales_operation_log` 中 `op_type=REMIND_{level}` 做幂等检查 |
| 大量逾期 / 长期未分配 | 业务风险 | 内置阈值扫描，触发 `alert_service` 全局告警 |

**代码约束满足情况：**
- ✅ 所有配置从 .env 读取（`SalesTaskSettings`）
- ✅ 复用 T11 渠道发送（不重复实现 SMTP/Webhook）
- ✅ 复用 `core.send_core` 风控底座（通过 T11 pipeline 调用）
- ✅ 不新增 / 删除 / 重命名目录（仅在 `business/sales_task/` 内新增文件）
- ✅ 全生命周期操作日志落库（`sales_operation_log` 表）
- ✅ 批量异常触发全局告警（`alert_service.service_exception_sync`）
- ✅ 隐私字段在 `push_notifier` 渲染前自动脱敏（复用 T11 template_engine）
