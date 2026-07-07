# T26 采集方案管理模块开发计划

**目标**: 在 `business/custom_spider` 新建采集方案管理模块，实现规则持久化、方案复用、自动任务对接。

**约束边界**:
- 禁止修改：`README.md`、`DEVELOP_RULES.md`、`docs/TASK_LIST.md`、`core/spider_core` 所有代码、`business/adapter/web_admin` 所有代码
- 仅允许新增：`business/custom_spider/` 目录内的业务层代码
- 纯依赖注入模式：调用层（Web API）由上层项目提供，本模块只负责业务能力

---

## 一、整体架构（三层分层）

```
business/custom_spider/
├── data_models.py          (持久层：SQLAlchemy ORM 模型 + 建表辅助)
├── repository.py           (数据访问层：ORM CRUD 封装 + 租户隔离)
├── service.py              (业务服务层：CRUD / 版本管理 / 测试运行 / 调度对接 / 入库流水线)
├── pydantic_models.py      (数据传输对象：Pydantic 输入/输出 Schema)
└── __init__.py             (模块导出，提供 run_plan / test_url / list_plans 等便捷入口)
```

### 调用依赖方向（严格单向）
```
business/custom_spider/service.py
    ├→ business/custom_spider/repository.py   (DB 操作)
    ├→ core.spider_core.rule_engine           (T25 规则采集)
    ├→ core.spider_core.field_extractor       (T25 字段提取)
    ├→ infra.task_scheduler.TaskScheduler     (T03 定时调度)
    ├→ infra.db_models.SpiderRawData          (T04 原始数据入库)
    ├→ core.compliance.ComplianceChecker      (T06 合规预检)
    └→ infra.logger_setup                     (日志)
```

---

## 二、数据库表设计（4 张表，全部继承 Base + BaseModel）

### 2.1 `custom_spider_plans`（采集方案主表）
方案基础信息 + 规则配置 + 调度配置 + 统计，JSON 字段存储 T25 CrawlRuleSet。

| 字段 | 类型 | 约束 | 说明 |
|------|------|------|------|
| id | BigInteger | PK, autoincrement | 方案ID |
| plan_name | String(128) | NOT NULL, index | 方案名称 |
| plan_code | String(64) | UNIQUE(tenant_id+plan_code) | 方案唯一编码，供调度引用 |
| target_domain | String(256) | NOT NULL, index | 目标站点域名（如 example.com） |
| spider_type | String(32) | NOT NULL, default='generic', index | 采集类型：generic / gov / b2b / bid / custom |
| status | String(16) | NOT NULL, default='draft', index | 状态：draft(草稿) / active(已启用) / paused(已暂停) |
| created_by | String(128) | index | 创建人 |
| description | Text | NULLABLE | 方案描述/备注 |
| rule_config | JSON | NOT NULL | **核心规则配置**（T25 CrawlRuleSet 结构序列化）|
| schedule_config | JSON | NULLABLE | 调度配置：{mode, cron, interval_minutes, enabled} |
| increment_config | JSON | NULLABLE | 增量配置：{mode, key_field, date_field_window_days} |
| cookie_encrypted | SensitiveString(2048) | NULLABLE | **加密存储** Cookie/敏感 Header（AES256） |
| current_version | Integer | NOT NULL, default=1 | 当前规则版本号 |
| run_count_total | Integer | NOT NULL, default=0 | 累计运行次数 |
| run_count_success | Integer | NOT NULL, default=0 | 累计成功次数 |
| items_total | Integer | NOT NULL, default=0 | 累计采集条目数 |
| last_run_at | TIMESTAMP | NULLABLE, index | 最近一次运行时间 |
| last_run_status | String(32) | NULLABLE | 最近一次运行状态 |
| last_run_error | String(512) | NULLABLE | 最近一次运行错误 |

**索引**:
- `idx_plan_tenant_status`: (tenant_id, status)
- `idx_plan_tenant_domain`: (tenant_id, target_domain)
- `idx_plan_tenant_code`: (tenant_id, plan_code) UNIQUE

---

### 2.2 `custom_spider_plan_versions`（规则版本表）
支持方案规则的版本管理与回滚。每次保存规则时自动生成新版本。

| 字段 | 类型 | 约束 | 说明 |
|------|------|------|------|
| id | BigInteger | PK, autoincrement | 版本ID |
| plan_id | BigInteger | FK(plans.id, CASCADE), NOT NULL, index | 关联方案 |
| version_number | Integer | NOT NULL, index | 版本号（从1递增）|
| rule_config | JSON | NOT NULL | 此版本的规则配置快照 |
| schedule_config | JSON | NULLABLE | 此版本的调度配置快照 |
| change_note | String(512) | NULLABLE | 变更说明 |
| changed_by | String(128) | NULLABLE | 变更人 |
| is_current | Boolean | NOT NULL, default=False, index | 是否当前版本 |
| rollback_from_version | Integer | NULLABLE | 从哪个版本回滚（可选）|

**索引**:
- `idx_ver_plan_version`: (plan_id, version_number) UNIQUE
- `idx_ver_plan_current`: (plan_id, is_current)

---

### 2.3 `custom_spider_runs`（采集运行记录表）
每次调度或手动执行产生一条运行记录，记录采集结果和统计信息。

| 字段 | 类型 | 约束 | 说明 |
|------|------|------|------|
| id | BigInteger | PK, autoincrement | 运行ID |
| plan_id | BigInteger | FK(plans.id, CASCADE), NOT NULL, index | 关联方案 |
| run_mode | String(32) | NOT NULL, index | manual / scheduled / test |
| trigger_by | String(128) | NULLABLE | 触发人 |
| status | String(32) | NOT NULL, index | pending / running / completed / failed |
| items_total | Integer | NOT NULL, default=0 | 本次采集条目数 |
| items_success | Integer | NOT NULL, default=0 | 本次成功入库条目数 |
| items_failed | Integer | NOT NULL, default=0 | 本次失败条目数 |
| field_match_rate | Numeric(5,2) | NULLABLE | 字段匹配率（0.0-1.0） |
| error_summary | String(1024) | NULLABLE | 错误摘要 |
| alerts_json | JSON | NULLABLE | 告警详情列表（T25 AlertManager 输出） |
| duration_ms | Integer | NULLABLE | 运行耗时(ms) |
| started_at | TIMESTAMP | NOT NULL | 开始时间 |
| finished_at | TIMESTAMP | NULLABLE | 结束时间 |

**索引**:
- `idx_run_plan_status`: (plan_id, status)
- `idx_run_plan_time`: (plan_id, started_at)
- `idx_run_tenant_status`: (tenant_id, status, started_at)

---

### 2.4 `custom_spider_operation_logs`（操作日志表）
方案启停、规则修改、批量操作等操作记录。

| 字段 | 类型 | 约束 | 说明 |
|------|------|------|------|
| id | BigInteger | PK, autoincrement | 日志ID |
| plan_id | BigInteger | FK(plans.id, SET NULL), index | 关联方案 |
| operation | String(32) | NOT NULL, index | create / update / delete / start / stop / test / import / export / rollback |
| operator | String(128) | NULLABLE | 操作人 |
| detail | Text | NULLABLE | 操作详情（JSON or text） |
| ip_address | String(64) | NULLABLE | 操作IP |
| success | Boolean | NOT NULL, default=True | 是否成功 |
| error_message | String(512) | NULLABLE | 失败原因 |

**索引**:
- `idx_oplog_plan_op`: (plan_id, operation, created_at)
- `idx_oplog_tenant_time`: (tenant_id, created_at)

---

## 三、业务服务层（Service）API 定义

### 3.1 PlanService（方案 CRUD + 版本管理）

```python
class PlanService:
    """采集方案业务服务。

    不依赖 Web 框架，可被任何调用方（FastAPI 路由、CLI 脚本、定时任务）使用。
    """

    # ---------- 基础 CRUD ----------
    def create_plan(
        self,
        plan_name: str,
        target_domain: str,
        spider_type: str,
        rule_config: dict,           # T25 CrawlRuleSet dict
        *,
        plan_code: str | None = None,
        description: str | None = None,
        schedule_config: dict | None = None,
        increment_config: dict | None = None,
        cookie_raw: str | None = None,  # 明文 Cookie，内部自动加密
        operator: str = "system",
    ) -> dict:
        """创建新方案。自动生成 v1 版本。"""

    def update_plan(
        self,
        plan_id: int,
        *,
        plan_name: str | None = None,
        status: str | None = None,
        rule_config: dict | None = None,        # 规则变更→生成新版本
        schedule_config: dict | None = None,
        increment_config: dict | None = None,
        cookie_raw: str | None = None,
        change_note: str | None = None,
        operator: str = "system",
    ) -> dict:
        """更新方案信息。若 rule_config 变更 → 自动生成新版本。"""

    def clone_plan(self, plan_id: int, *, new_plan_name: str, new_plan_code: str | None = None,
                   operator: str = "system") -> dict:
        """克隆方案（规则 + 配置全量复制，生成新 plan_id）。"""

    def delete_plan(self, plan_id: int, *, operator: str = "system") -> bool:
        """软删除方案（is_archived = True）。停止关联调度任务。"""

    def get_plan(self, plan_id: int) -> dict | None:
        """查询方案详情（返回规则+调度配置，cookie 保持加密形式不返回）。"""

    def get_plan_by_code(self, plan_code: str) -> dict | None:
        """按 plan_code 查询（供调度任务使用）。"""

    def list_plans(
        self,
        *,
        status: str | None = None,
        spider_type: str | None = None,
        target_domain: str | None = None,
        keyword: str | None = None,
        page: int = 1,
        page_size: int = 20,
    ) -> tuple[list[dict], int]:
        """方案列表（支持筛选 + 分页）。返回 (items, total_count)。"""

    # ---------- 版本管理 ----------
    def list_versions(self, plan_id: int) -> list[dict]:
        """查询方案所有版本列表（按版本号倒序）。"""

    def get_version(self, plan_id: int, version_number: int) -> dict | None:
        """查询指定版本详情。"""

    def rollback_to_version(self, plan_id: int, version_number: int, *, operator: str = "system") -> dict:
        """回滚到指定版本。将该版本的规则/调度配置复制为新版本。"""

    # ---------- 测试运行 ----------
    def test_plan(
        self,
        plan_id: int,
        *,
        test_url: str | None = None,  # 不指定则用方案 list_rule 的首个 URL
        operator: str = "system",
        max_items: int = 5,
    ) -> dict:
        """
        单条样例 URL 测试采集效果。
        返回: { items: [...], field_match_rate: float, error: str | None, duration_ms: int }
        不入库，仅用于规则验证。
        """

    # ---------- 导入导出 ----------
    def export_plan(self, plan_id: int) -> dict:
        """导出方案配置为 JSON（不含 cookie，不含运行统计）。"""

    def import_plan(self, config: dict, *, plan_name: str | None = None, plan_code: str | None = None,
                    operator: str = "system") -> dict:
        """从 JSON 导入创建新方案。校验字段完整性。"""

    # ---------- 调度启停 ----------
    def enable_schedule(self, plan_id: int, *, operator: str = "system") -> dict:
        """启用调度：将 plan 的 schedule_config.enabled=True，注册到 TaskScheduler。"""

    def disable_schedule(self, plan_id: int, *, operator: str = "system") -> dict:
        """停用调度：将 plan 的 schedule_config.enabled=False，从 TaskScheduler 移除。"""

    def run_plan_now(self, plan_id: int, *, operator: str = "system", max_items: int | None = None) -> dict:
        """立即执行一次采集（同步执行，适合手动触发/调试）。"""

    # ---------- 统计查询 ----------
    def get_plan_stats(self, plan_id: int, *, days: int = 30) -> dict:
        """返回方案统计：总运行次数 / 成功次数 / 总采集量 / 近 N 天趋势。"""

    def list_runs(self, plan_id: int, *, status: str | None = None, page: int = 1, page_size: int = 20) -> tuple[list[dict], int]:
        """运行记录列表。"""

    def get_run_detail(self, run_id: int) -> dict | None:
        """运行记录详情（含告警列表）。"""
```

---

### 3.2 ScheduledRunService（调度执行 + 入库流水线）

由 PlanService 的调度启停触发，也可直接调用。

```python
def execute_scheduled_plan(plan_code: str) -> None:
    """
    被 TaskScheduler 调用的入口函数。
    流程:
      1. 根据 plan_code 加载 plan 配置
      2. 将 rule_config 转换为 T25 CrawlRuleSet
      3. 调用 core.spider_core.run_rule(CrawlRuleSet) 执行采集
      4. 合规预检（T06 ComplianceChecker）
      5. 写入 T04 spider_raw_data 表（标记 source="custom_spider:{plan_code}"）
      6. 记录 custom_spider_runs 表
      7. 更新 plan 的累计统计字段
      8. 触发 T10 清洗流水线信号（Redis Pub/Sub: channel="pipeline:new_raw_data"）
    """
```

---

## 四、Pydantic 数据传输对象（DTO）

文件: `business/custom_spider/pydantic_models.py`

```python
from pydantic import BaseModel, Field, ConfigDict
from typing import Any, Optional

class PlanCreate(BaseModel):
    plan_name: str = Field(..., min_length=2, max_length=128)
    plan_code: Optional[str] = None
    target_domain: str = Field(..., min_length=2, max_length=256)
    spider_type: str = "generic"
    description: Optional[str] = None
    rule_config: dict
    schedule_config: Optional[dict] = None
    increment_config: Optional[dict] = None
    cookie_raw: Optional[str] = None
    operator: str = "system"

class PlanUpdate(BaseModel):
    plan_name: Optional[str] = None
    status: Optional[str] = None
    rule_config: Optional[dict] = None
    schedule_config: Optional[dict] = None
    increment_config: Optional[dict] = None
    cookie_raw: Optional[str] = None
    change_note: Optional[str] = None
    operator: str = "system"

class PlanTest(BaseModel):
    test_url: Optional[str] = None
    max_items: int = 5
    operator: str = "system"

class PlanExport(BaseModel):
    plan_name: str
    target_domain: str
    spider_type: str
    description: Optional[str]
    rule_config: dict
    schedule_config: Optional[dict]
    increment_config: Optional[dict]
    version: int

class PlanRunResult(BaseModel):
    plan_id: int
    run_id: int
    status: str
    items_total: int
    items_success: int
    items_failed: int
    field_match_rate: Optional[float]
    duration_ms: Optional[int]
    alerts: list[dict]
```

---

## 五、数据库操作层（Repository）

文件: `business/custom_spider/repository.py`

### 设计原则
- 使用 SQLAlchemy `sessionmaker` / `scoped_session`
- 每个方法独立管理 session 生命周期（或接受外部 session 参数）
- 所有查询强制带 `tenant_id` 过滤
- 所有删除使用软删除（`is_archived = True`）
- 所有更新自动更新 `updated_at`

### Session 获取策略
```python
def _get_session():
    """从全局 db_manager 获取 session。若不可用，回退到内存 SQLite 用于测试。"""
```

---

## 六、核心业务流程

### 6.1 方案创建流程
```
输入: PlanCreate DTO
  → 校验: plan_name 非空, target_domain 非空, rule_config 含 list_rule
  → 自动生成 plan_code（如未指定）: f"plan_{md5(plan_name+ts)[:12]}"
  → cookie_raw → SensitiveString 加密存储
  → 插入 plans 表 (version=1, status='draft')
  → 插入 versions 表 (version=1, is_current=True)
  → 记录 operation_log (operation='create')
返回: { plan_id, plan_code, version_number }
```

### 6.2 规则变更 → 自动生成新版本
```
输入: PlanUpdate(rule_config=NEW_RULE)
  → 对比旧 rule_config vs 新 rule_config
  → 如有差异: current_version += 1, 新建 versions 记录, is_current=True
  → 更新 plans 表的 rule_config 与 current_version
  → 记录 operation_log (operation='update')
返回: { plan_id, new_version_number }
```

### 6.3 测试运行流程
```
输入: PlanTest(test_url, max_items)
  → 加载 plan 的 rule_config
  → 构造 CrawlRuleSet(..., max_items=max_items, compliance_check=True)
  → 调用 core.spider_core.run_rule(CrawlRuleSet) 获取采集结果
  → 不写入 spider_raw_data 表
  → 写入 custom_spider_runs 表 (run_mode='test')
返回: { items: [...], field_match_rate, error, duration_ms }
```

### 6.4 调度任务注册流程
```
输入: enable_schedule(plan_id)
  → 加载 plan.schedule_config
  → 校验: {mode: 'cron'|'interval', cron: str, enabled: True}
  → 构造 job_id: f"custom_spider:{plan_code}"
  → 构造可序列化函数: execute_scheduled_plan(plan_code)
  → 调用 TaskScheduler.add_cron(job_id, cron=schedule_config.cron)
  → 更新 plans.status = 'active'
  → 记录 operation_log (operation='start')
```

### 6.5 执行采集 → 入库流水线
```
Step 1: 执行 T25 采集引擎
   result = core.spider_core.run_rule(CrawlRuleSet)

Step 2: 字段标准化与合规预检
   for item in result.items:
     report = ComplianceChecker().check_for_storage(item)
     item_masked = PrivacyStripper().strip(item)
     item["_compliance_report"] = report.to_dict()
     item["_source_plan_code"] = plan_code
     item["_source_run_id"] = run_id

Step 3: 写入 T04 spider_raw_data 表
   session.add(SpiderRawData(
       spider_name=f"custom_spider:{plan_code}",
       source_url=item["_source_url"] or plan.list_rule.url_template,
       source_id=item.get("_source_id"),   # 去重唯一标识
       raw_payload=item_masked,             # 完整结构化 JSON
       raw_text=item.get("_raw_text"),
       fetch_status=1 if success else 0,
       fetch_error=item.get("_error"),
       source_country=plan.increment_config.get("country", ""),
   ))

Step 4: 触发 T10 清洗信号（Redis Pub/Sub）
   try:
       r = get_redis()
       if r: r.publish("pipeline:new_raw_data",
                       json.dumps({"source_batch": f"{plan_code}:{run_id}",
                                   "count": items_success}, ensure_ascii=False))
   except Exception: pass   # 信号失败不影响入库结果

Step 5: 更新 plan 统计 & 记录 runs
```

### 6.6 增量去重逻辑
```
策略: 在 T25 DedupStore 基础上，增加 DB 级去重
   1. T25 DedupStore (Redis) → 本次运行内去重
   2. DB 级 source_id 去重 → 跨运行去重
   3. increment_config.date_field_window_days → 只取最近 N 天数据
```

---

## 七、文件清单与行数预估

| 文件 | 路径 | 预估行数 | 职责 |
|------|------|---------|------|
| `__init__.py` | `business/custom_spider/__init__.py` | 30 | 模块导出 |
| `data_models.py` | `business/custom_spider/data_models.py` | 220 | 4 个 ORM 模型 + 建表辅助 |
| `pydantic_models.py` | `business/custom_spider/pydantic_models.py` | 120 | Pydantic DTO + 校验 |
| `repository.py` | `business/custom_spider/repository.py` | 350 | 数据访问层（CRUD + 版本 + 运行） |
| `service.py` | `business/custom_spider/service.py` | 500 | 业务服务层（完整 PlanService） |
| **合计** | | **~1220** | |

---

## 八、开发步骤（有序执行）

1. **Step 1**: `data_models.py` — 定义 4 个 SQLAlchemy ORM 模型
   - 继承 `Base` + `BaseModel`，复用租户/时间戳/软删除字段
   - 使用 `SensitiveString` 类型存储 cookie_encrypted
   - 使用 `JSON` 类型存储 rule_config / schedule_config / increment_config
   - 提供 `create_tables()` 辅助函数（调用 Base.metadata.create_all）

2. **Step 2**: `pydantic_models.py` — 定义输入输出 DTO
   - `PlanCreate` / `PlanUpdate` / `PlanTest` / `PlanRunResult`
   - 字段长度校验、枚举值约束

3. **Step 3**: `repository.py` — 数据访问层
   - `_get_session()` session 管理
   - PlanRepository: create/get/update/delete/list
   - VersionRepository: list/get/rollback
   - RunRepository: create/update/get/list
   - LogRepository: create/list

4. **Step 4**: `service.py` — 业务服务层（核心）
   - 实现 PlanService 所有方法
   - 实现 `execute_scheduled_plan(plan_code)` 全局函数
   - 对接 T25 rule_engine / field_extractor
   - 对接 T03 TaskScheduler
   - 对接 T06 ComplianceChecker / PrivacyStripper
   - 对接 T04 SpiderRawData 入库
   - Redis Pub/Sub 信号触发 T10 清洗

5. **Step 5**: `__init__.py` — 模块统一导出
   - 提供便捷入口: `PlanService` / `execute_scheduled_plan` / `create_tables`

6. **Step 6**: 冒烟测试（手动或单元测试验证）
   - 建表: `create_tables()` → 检查 4 张表创建成功
   - 创建方案: `PlanService().create_plan()` → 检查 plan + version 记录
   - 规则变更: `PlanService().update_plan(rule_config=NEW)` → 检查新版本
   - 测试运行: `PlanService().test_plan()`（使用 mock 数据，模拟 T25 响应）
   - 导入导出: `export_plan()` / `import_plan()` → JSON 往返一致性
   - 调度启停: `enable_schedule()` / `disable_schedule()` → TaskScheduler 注册/注销

---

## 九、关键依赖与容错设计

### 依赖组件
| 组件 | 用途 | 失败回退 |
|------|------|---------|
| `core.spider_core.rule_engine.run_rule` | 执行采集 | 记录 error 到 runs 表 + 更新 plan.last_run_error |
| `infra.task_scheduler.TaskScheduler` | 调度注册 | 调度失败记录 operation_log.error + 保持 plan.status=paused |
| `infra.db_models.SpiderRawData` | 原始数据入库 | DB 不可达时缓存到 Redis（`custom_spider:pending:{plan_code}`），下次重试 |
| `core.compliance.ComplianceChecker` | 合规预检 | 合规检查失败→标记 raw_payload._compliance_risk=high，仍入库 |
| `infra.redis_client.get_redis` | Pub/Sub 信号 | Redis 不可达→跳过信号，写入 operation_log.warning |
| `core.compliance.sensitive_crypto.AES256Crypto` | Cookie 加密 | 密钥缺失→不存储 cookie，记录 warning |

### 配置注入
- 数据库连接: 复用项目现有 `configs.settings.settings.db` 配置
- 合规开关: 复用 `settings.compliance` 配置
- 调度开关: 复用 `settings.scheduler` 配置
- 无需新增 `.env` 变量

---

## 十、风险与处理

| 风险 | 概率 | 影响 | 处理方案 |
|------|------|------|---------|
| T25 `run_rule` 对真实站点请求超时 / 失败 | 中 | 单次采集失败 | 记录 error → 更新 plan.last_run_error → alert_manager 触发告警 |
| DB session 在长任务中连接中断 | 低 | 部分数据入库失败 | 每个 session 独立事务，try/except 包裹；失败数据写入 Redis 等待队 |
| 相同 plan_code 在多实例重复注册调度 | 低 | 重复执行 | plan_code + tenant_id 唯一索引；TaskScheduler job_id 全局唯一；调度函数内再次校验 plan.status |
| 规则 JSON schema 变更导致旧规则解析失败 | 中 | 历史方案不可用 | Pydantic `model_config(extra="allow")` 兼容新增字段；关键缺失字段使用默认值 + warning |
| Cookie 明文不慎泄露到日志 | 低 | 安全风险 | SensitiveString 类型自动脱敏；service 层 cookie_raw 不进入日志 |
