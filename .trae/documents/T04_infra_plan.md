# T04 · 数据库分层设计、ORM 模型、敏感字段加密、冷热分离基建 Plan

> 基于 T01 项目骨架、T02 日志/异常/告警、T03 Redis&定时调度基建，在 infra + core/compliance 层新增纯底层数据库能力。

---

## 一、仓库研究结论

1. **目录结构**：`core/compliance/` 已存在空 `__init__.py`，刚好可放加密与合规相关通用能力；`infra/` 已有 logger/response/alert/redis/queue/scheduler，新增 `db_base.py` / `db_models.py`
2. **依赖**：`requirements.txt` 只有 `pgvector>=0.2.5`，缺失 SQLAlchemy 与加密依赖；需补充 `SQLAlchemy>=2.0.20`、`cryptography>=41.0.0`（本 Task 实现时会一并写进 requirements.txt）
3. **现有配置**：`.env.example` 已有 `DB_HOST / DB_PORT / DB_USER / DB_PASSWORD / DB_NAME / DB_POOL_SIZE / DB_MAX_OVERFLOW`，需追加 `DB_ENCRYPTION_KEY`（AES-256 主密钥）、`DB_ARCHIVE_DAYS`（归档周期）、`DB_ARCHIVE_HOT_THRESHOLD`（价值阈值）
4. **日志/告警能力**：`get_logger("db")`、`alert_service.service_exception_async(...)` 可直接复用
5. **禁止修改**：`README.md`、`DEVELOP_RULES.md`、`docs/TASK_LIST.md`
6. **不新增目录**：全部文件直接落在 `infra/` 与 `core/compliance/` 下

---

## 二、本次新增文件完整清单

| # | 文件（完整路径） | 模块层 | 核心功能 |
|----|----------------|-------|---------|
| 1 | `configs/settings.py`（修改） | configs | 追加 `db: DBSettings` 分组（连接池大小、最大 overflow、加密密钥、归档周期、归档价值阈值、表前缀、是否启用敏感字段脱敏） |
| 2 | `.env.example`（修改） | 根 | 追加 `DB_ENCRYPTION_KEY` / `DB_ARCHIVE_DAYS` / `DB_ARCHIVE_HOT_THRESHOLD` / `DB_SENSITIVE_MASK_ENABLED` |
| 3 | `requirements.txt`（修改） | 根 | 补充 `SQLAlchemy>=2.0.20`、`cryptography>=41.0.0` |
| 4 | `infra/db_base.py` | infra | `Database` 单例（Engine / Session / scoped_session）；`Base`（delarative_base + 公共字段 id/created_at/updated_at/is_archived/tenant_id）；`paginate()`、`bulk_insert()`、`upsert()`、`mark_archived()` 通用方法；统一异常包装 |
| 5 | `infra/db_models.py` | infra | 四类核心 ORM 表：`SpiderRawData`、`BusinessOpportunity`、`SalesTask`、`SystemLog`；定义字段、主键、索引、外键、Check 约束 |
| 6 | `core/compliance/sensitive_crypto.py` | core/compliance | `AES256Crypto` 单例 + `SensitiveString`（SQLAlchemy TypeDecorator 自定义类型）：加密字段用 `SensitiveString()` 声明即可，写入自动加密、查询自动解密；提供 `mask()` 脱敏输出 |
| 7 | `core/compliance/archive_mixin.py` | core/compliance | `ArchiveMixin` 与 `archive_rules`：根据"过期天数 + 价值阈值"判定是否应归档；提供 `mark_archived()` / `hot_only_query()` 过滤工具；与定时调度对接，注册 `schedule_archive_job()` 供外部一键启用定时归档 |
| 8 | `tests/test_t04_infra.py` | tests | 单元测试（10+ 条）：加密/解密/脱敏 round-trip；ORM 基类分页/upsert；归档判定；DB 单例；异常告警；全部使用 SQLite 内存库隔离，无外部依赖 |
| 9 | `.trae/documents/T04_infra_plan.md`（本文件） | 非交付 | 开发计划文档，提交后保留 |

> 不新增目录；不动 README / DEVELOP_RULES / docs/TASK_LIST；不写业务增删改查。

---

## 三、每张数据表字段 / 主键 / 索引设计说明

### 3.1 spider_raw_data — 原始爬虫数据表（`core/spider_core` 场景）

> 由爬虫模块写入，存原始抓取 payload 与元信息；**不做任何清洗**。

| 字段 | 类型 | 约束 | 说明 |
|------|------|------|------|
| `id` | BIGINT | PK, AUTOINCREMENT | 主键 |
| `tenant_id` | VARCHAR(64) | NOT NULL, IDX | 多租户隔离（默认 "default"） |
| `spider_name` | VARCHAR(128) | NOT NULL, IDX | 爬虫名，如 `linkedin-job` |
| `source_url` | VARCHAR(512) | NOT NULL | 来源 URL |
| `source_id` | VARCHAR(256) | NULL | 平台唯一标识，用于去重 |
| `raw_payload` | JSONB | NOT NULL | 抓取到的原始 JSON |
| `raw_text` | TEXT | NULL | 抓取到的原始文本（若为非结构化页面） |
| `fetch_status` | SMALLINT | NOT NULL, DEFAULT 0 | 0=成功, 1=代理异常, 2=风控拦截, 3=解析失败 |
| `fetch_error` | VARCHAR(512) | NULL | 失败原因 |
| `captured_at` | TIMESTAMP | NOT NULL, IDX | 抓取时间 |
| `source_country` | CHAR(2) | NULL | ISO 3166-1 两位国家码 |
| `is_archived` | BOOLEAN | NOT NULL, DEFAULT FALSE, IDX | 冷热标记 |
| `created_at` | TIMESTAMP | NOT NULL, DEFAULT now() |
| `updated_at` | TIMESTAMP | NOT NULL, DEFAULT now() |

**索引**：
- `idx_spider_raw_source_id` UNIQUE (`tenant_id`, `spider_name`, `source_id`) — 保证同租户同一爬虫下的源端去重
- `idx_spider_raw_captured` (`captured_at` DESC) — 时间范围查询加速
- `idx_spider_raw_archived_name` (`is_archived`, `spider_name`) — 热数据过滤

---

### 3.2 business_opportunities — 结构化商机表（`core/data_core` 场景）

> 清洗后的商机主表；联系方式走敏感字段加密。

| 字段 | 类型 | 约束 | 说明 |
|------|------|------|------|
| `id` | BIGINT | PK, AUTOINCREMENT |
| `tenant_id` | VARCHAR(64) | NOT NULL, IDX |
| `title` | VARCHAR(512) | NOT NULL | 商机标题 |
| `description` | TEXT | NULL | 描述 |
| `company_name` | VARCHAR(256) | NULL, IDX |
| `company_domain` | VARCHAR(256) | NULL | 公司域名（匹配线索） |
| `industry` | VARCHAR(64) | NULL, IDX | 行业标签 |
| `country` | CHAR(2) | NULL | 国家码 |
| `city` | VARCHAR(128) | NULL | 城市 |
| `contact_name` | VARCHAR(128) | NULL | 联系人姓名 |
| `contact_phone` | `SensitiveString(256)` | NULL | 手机号（自动加密） |
| `contact_email` | `SensitiveString(256)` | NULL | 邮箱（自动加密） |
| `contact_wechat` | `SensitiveString(256)` | NULL | 微信号（自动加密） |
| `estimated_value` | NUMERIC(18,2) | NULL, IDX | 预估商机价值 |
| `confidence_score` | NUMERIC(5,2) | NULL | 线索置信度 0.00~100.00 |
| `status` | VARCHAR(32) | NOT NULL, DEFAULT 'new', IDX | new/qualified/proposal/won/lost |
| `source_raw_id` | BIGINT | NULL, FK(spider_raw_data.id) | 关联原始爬虫记录 |
| `tags` | VARCHAR(512) | NULL | 逗号分隔标签 |
| `is_archived` | BOOLEAN | NOT NULL, DEFAULT FALSE, IDX | 冷热标记 |
| `last_active_at` | TIMESTAMP | NULL, IDX | 最近活动时间（用于归档判定） |
| `created_at` | TIMESTAMP | NOT NULL, DEFAULT now() |
| `updated_at` | TIMESTAMP | NOT NULL, DEFAULT now() |

**索引**：
- `idx_biz_tenant_status` (`tenant_id`, `status`)
- `idx_biz_tenant_value` (`tenant_id`, `estimated_value` DESC) — 高价值优先
- `idx_biz_company` (`company_name`)
- `idx_biz_archived_active` (`is_archived`, `last_active_at`) — 归档判定 & 过滤

---

### 3.3 sales_tasks — 销售跟进任务表（`core/send_core` / 下游销售系统场景）

> 商机转化为销售任务后的流转。

| 字段 | 类型 | 约束 | 说明 |
|------|------|------|------|
| `id` | BIGINT | PK, AUTOINCREMENT |
| `tenant_id` | VARCHAR(64) | NOT NULL, IDX |
| `opportunity_id` | BIGINT | NOT NULL, FK(business_opportunities.id), IDX | 关联商机 |
| `assigned_to` | VARCHAR(128) | NULL, IDX | 销售负责人 |
| `task_type` | VARCHAR(32) | NOT NULL, DEFAULT 'call' | call/email/wechat/visit/custom |
| `priority` | SMALLINT | NOT NULL, DEFAULT 1 | 1=低, 2=中, 3=高 |
| `status` | VARCHAR(32) | NOT NULL, DEFAULT 'todo', IDX | todo/doing/done/cancelled/failed |
| `scheduled_at` | TIMESTAMP | NULL, IDX | 计划执行时间 |
| `completed_at` | TIMESTAMP | NULL | 实际完成时间 |
| `result_note` | TEXT | NULL | 跟进结果 |
| `is_archived` | BOOLEAN | NOT NULL, DEFAULT FALSE, IDX |
| `created_at` | TIMESTAMP | NOT NULL, DEFAULT now() |
| `updated_at` | TIMESTAMP | NOT NULL, DEFAULT now() |

**索引**：
- `idx_sales_tenant_status_priority` (`tenant_id`, `status`, `priority` DESC) — 销售工作台主查询
- `idx_sales_scheduled` (`scheduled_at`)
- `idx_sales_opportunity` (`opportunity_id`)

---

### 3.4 system_logs — 系统操作日志表（审计 / 合规）

> 记录关键操作、异常事件、权限变更。

| 字段 | 类型 | 约束 | 说明 |
|------|------|------|------|
| `id` | BIGINT | PK, AUTOINCREMENT |
| `tenant_id` | VARCHAR(64) | NOT NULL, IDX |
| `log_level` | VARCHAR(16) | NOT NULL, DEFAULT 'info', IDX | info/warn/error/critical |
| `log_type` | VARCHAR(64) | NOT NULL, IDX | db/request/crawler/alarm/auth |
| `actor` | VARCHAR(128) | NULL | 操作者（用户/系统/模块名） |
| `target_resource` | VARCHAR(256) | NULL | 操作对象标识 |
| `message` | TEXT | NOT NULL | 日志正文 |
| `extra` | JSONB | NULL | 结构化附加信息 |
| `request_id` | VARCHAR(128) | NULL | 请求追踪 ID |
| `ip_address` | VARCHAR(64) | NULL | 源 IP |
| `duration_ms` | INTEGER | NULL | 耗时 |
| `is_archived` | BOOLEAN | NOT NULL, DEFAULT FALSE, IDX |
| `created_at` | TIMESTAMP | NOT NULL, DEFAULT now(), IDX |
| `updated_at` | TIMESTAMP | NOT NULL, DEFAULT now() |

**索引**：
- `idx_syslog_tenant_type_time` (`tenant_id`, `log_type`, `created_at` DESC)
- `idx_syslog_level_time` (`log_level`, `created_at` DESC) — 错误告警回溯
- `idx_syslog_actor` (`actor`)

---

## 四、ORM 基类通用方法、AES 加密工具代码设计方案

### 4.1 infra/db_base.py — 数据库单例

```python
class Database:
    """全局数据库单例（进程级，所有业务模块共用同一个 Engine/Session）。"""

    def __init__(self):
        from sqlalchemy import create_engine
        from sqlalchemy.orm import sessionmaker, scoped_session
        from configs.settings import settings

        url = (
            f"postgresql+psycopg2://{settings.db.DB_USER}:{settings.db.DB_PASSWORD}"
            f"@{settings.db.DB_HOST}:{settings.db.DB_PORT}/{settings.db.DB_NAME}"
        )
        self.engine = create_engine(
            url,
            pool_size=int(settings.db.DB_POOL_SIZE or 10),
            max_overflow=int(settings.db.DB_MAX_OVERFLOW or 20),
            pool_pre_ping=True,
            pool_recycle=1800,
            echo=False,
        )
        self._session_factory = sessionmaker(bind=self.engine, expire_on_commit=False)
        self.Session = scoped_session(self._session_factory)

    # 上下文
    def session(self):
        return self.Session()

    # 建表 / 删表（仅开发用）
    def create_all(self): ...
    def drop_all(self): ...
    def dispose(self): ...

    # ------- 通用工具 -------
    def paginate(self, query, /, *, page=1, page_size=20) -> PaginationResult:
        """返回 {items, page, page_size, total, total_pages}。"""

    def bulk_insert(self, model_cls, rows: list[dict]) -> int:
        """批量 insert，行数受 batch_size 控制（默认 500）。"""

    def upsert(self, instance, /, *, conflict_columns: list[str]) -> Any:
        """按 conflict_columns 做 insert-or-update（PostgreSQL ON CONFLICT）。"""

    def mark_archived(self, model_cls, /, *, where) -> int:
        """根据条件批量标记 is_archived=True，返回更新行数。"""
```

**公共 ORM 基类 `Base` + `BaseModel`**：
```python
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column
from datetime import datetime

class Base(DeclarativeBase):
    pass

class BaseModel:
    """所有业务表都继承它，统一公共字段与 to_dict。"""
    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    tenant_id: Mapped[str] = mapped_column(default="default", index=True)
    is_archived: Mapped[bool] = mapped_column(default=False, index=True)
    created_at: Mapped[datetime] = mapped_column(default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(default=datetime.utcnow, onupdate=datetime.utcnow)
```

**异常捕获与告警**：
- 所有公共方法（paginate / bulk_insert / upsert / mark_archived）外层包裹 `try/except`；失败时 `logger.error(...)` 并调用 `alert_service.service_exception_async(...)`；抛出业务异常 `BizException(code=ErrorCode.DB_ERROR, http_status=500)`
- Engine 首次连接失败：捕获 `OperationalError` → 告警 + 抛 `RedisUnreachableError` 类似的专用 DB 异常（本 Plan 中定义 `DBUnreachableError` 继承 `BizException`，放在 infra/db_base.py 顶部模块级，不新文件）

---

### 4.2 core/compliance/sensitive_crypto.py — 敏感字段加密

```python
import base64
import hashlib
import os
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
from cryptography.hazmat.primitives import padding
from sqlalchemy import TypeDecorator, String

class AES256Crypto:
    """AES-256-CBC 单例；密钥从 settings.db.DB_ENCRYPTION_KEY 派生。"""
    _instance = None
    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._init()
        return cls._instance
    def _init(self):
        from configs.settings import settings
        key = str(settings.db.DB_ENCRYPTION_KEY or "").strip()
        if not key or len(key) < 16:
            raise ValueError("DB_ENCRYPTION_KEY 必须设置，且长度 >= 16")
        self._key = hashlib.sha256(key.encode("utf-8")).digest()  # 32 字节
    def encrypt(self, plaintext: str | None) -> str | None:
        if plaintext is None or plaintext == "":
            return plaintext
        iv = os.urandom(16)
        padder = padding.PKCS7(128).padder()
        data = padder.update(plaintext.encode("utf-8")) + padder.finalize()
        cipher = Cipher(algorithms.AES(self._key), modes.CBC(iv))
        ct = cipher.encryptor().update(data) + cipher.encryptor().finalize()
        return base64.b64encode(iv + ct).decode("ascii")
    def decrypt(self, ciphertext: str | None) -> str | None:
        if ciphertext is None or ciphertext == "":
            return ciphertext
        raw = base64.b64decode(ciphertext.encode("ascii"))
        iv, ct = raw[:16], raw[16:]
        cipher = Cipher(algorithms.AES(self._key), modes.CBC(iv))
        pt = cipher.decryptor().update(ct) + cipher.decryptor().finalize()
        unpad = padding.PKCS7(128).unpadder()
        return (unpad.update(pt) + unpad.finalize()).decode("utf-8")

def mask_phone(phone: str | None) -> str | None:
    """脱敏：手机号中间 4 位 -> ****。"""
def mask_email(email: str | None) -> str | None:
def mask_wechat(wx: str | None) -> str | None:
def mask_value(field_name: str, value: str | None) -> str | None:
    """统一入口：根据字段名选择策略。"""
    if not value: return value
    if "phone" in field_name or "mobile" in field_name: return mask_phone(value)
    if "email" in field_name: return mask_email(value)
    if "wechat" in field_name or "wx" in field_name: return mask_wechat(value)
    return value[:2] + "*" * max(2, len(value) - 2)
```

**SQLAlchemy 自定义类型 `SensitiveString`**：
```python
class SensitiveString(TypeDecorator):
    impl = String
    cache_ok = True

    def process_bind_param(self, value, dialect):
        # 写入 DB 时加密
        return AES256Crypto().encrypt(value)
    def process_result_value(self, value, dialect):
        # 从 DB 读出时解密
        try:
            return AES256Crypto().decrypt(value)
        except Exception:
            return value  # 对已有的历史明文记录保留原值
```

> 使用方式：`contact_phone: Mapped[str | None] = mapped_column(SensitiveString(256), nullable=True)`
> 对外接口中，建议额外再调用 `mask_value()` 做二次脱敏输出。

---

### 4.3 core/compliance/archive_mixin.py — 冷热分离标记

```python
from datetime import datetime, timedelta
from configs.settings import settings

class ArchiveMixin:
    """提供 is_archived 过滤与判定的 Mixin。"""

    @classmethod
    def hot_only(cls, query):
        """仅查询热数据（未归档）。"""
        return query.filter(cls.is_archived == False)

    @classmethod
    def archive_only(cls, query):
        """仅查询冷/归档数据。"""
        return query.filter(cls.is_archived == True)

def should_archive_row(last_active_at: datetime | None,
                       created_at: datetime,
                       value: float | None = None) -> bool:
    """判定规则：
    (last_active_at 或 created_at 距今超过 DB_ARCHIVE_DAYS) AND
    (value < DB_ARCHIVE_HOT_THRESHOLD 或 value 为空)
    """
    now = datetime.utcnow()
    ref = last_active_at or created_at
    days_ago = (now - ref).days
    if days_ago < int(settings.db.DB_ARCHIVE_DAYS or 90):
        return False
    threshold = float(settings.db.DB_ARCHIVE_HOT_THRESHOLD or 1000)
    return (value is None) or (float(value) < threshold)

def mark_rows_archived(session, model_cls, *, batch_size=1000) -> int:
    """对给定 model 按规则批量打归档标记；返回更新总行数。
    策略：对有 last_active_at / estimated_value 的表走组合判定，
    对 system_logs 类表仅用 created_at 判定。"""

def schedule_archive_job(scheduler, *, hour: int = 2, minute: int = 0) -> str:
    """向 APScheduler 注册每日冷数据归档任务（默认凌晨 02:00）。
    内部依次对四类表调用 mark_rows_archived。"""
```

**冷热判定规则说明**：
- `BusinessOpportunity`：`last_active_at` 距今 > `DB_ARCHIVE_DAYS` 天，且 `estimated_value < DB_ARCHIVE_HOT_THRESHOLD`（或为空）→ 标记归档
- `SpiderRawData`：`captured_at` 距今 > `DB_ARCHIVE_DAYS` 天 → 归档（原始数据过期即冷）
- `SalesTask`：状态为 `done / cancelled / failed` 的任务，`completed_at` 或 `updated_at` 距今 > `DB_ARCHIVE_DAYS` → 归档
- `SystemLog`：`created_at` 距今 > `DB_ARCHIVE_DAYS` → 归档（日志类默认 180 天）

---

## 五、冷热数据归档判定规则（汇总）

| 表 | 判定条件 | 备注 |
|----|---------|------|
| `business_opportunities` | `last_active_at` 超期 & `estimated_value < 阈值` | 保留高价值商机 |
| `spider_raw_data` | `captured_at` 超期 | 原始数据优先冷化 |
| `sales_tasks` | 终态(done/cancelled/failed) 且完成时间超期 | |
| `system_logs` | `created_at` 超期 | 默认更大的超期阈值（180d） |

**可配置项**（全走 `.env`）：
- `DB_ARCHIVE_DAYS=90` — 一般归档阈值
- `DB_ARCHIVE_HOT_THRESHOLD=1000` — 高价值保留阈值（金额单位与业务一致）
- `DB_SENSITIVE_MASK_ENABLED=true` — 对外接口二次脱敏开关

---

## 六、分步执行开发流程

| 步骤 | 操作 | 产出 |
|------|------|------|
| 1 | `requirements.txt` 补充 SQLAlchemy / cryptography；`.env.example` 补 DB_ENCRYPTION_KEY / DB_ARCHIVE_* / DB_SENSITIVE_MASK_ENABLED；`configs/settings.py` 新增 `db: DBSettings` | 配置就绪 |
| 2 | `core/compliance/sensitive_crypto.py` 实现 AES256Crypto + SensitiveString 自定义类型 + mask_* 脱敏；在 `infra/db_models.py` 的 4 张表中对 contact_* 字段使用 `SensitiveString` | 加密 + 脱敏就绪 |
| 3 | `infra/db_base.py` 实现 `Database` 单例 / `Base` / `BaseModel` / `paginate / bulk_insert / upsert / mark_archived`；写入/查询异常接入 `alert_service` | ORM 基础就绪 |
| 4 | `infra/db_models.py` 定义 `SpiderRawData / BusinessOpportunity / SalesTask / SystemLog` 四张表，全部继承 `BaseModel`，字段与索引按第三、四节设计 | 表结构就绪 |
| 5 | `core/compliance/archive_mixin.py` 实现 `ArchiveMixin` + `should_archive_row` + `mark_rows_archived` + `schedule_archive_job()` | 冷热归档就绪 |
| 6 | `tests/test_t04_infra.py`：SQLite 内存库建表 → 加密/解密 round-trip → 分页/批量插入/upsert → 归档判定/打标 → 异常触发告警；`pytest -v` 全量通过 | 测试闭环 |
| 7 | Git 提交（`feat(T04): 完成数据库分层/ORM/加密/冷热分离基建`） | 交付 |

---

## 七、潜在依赖 / 注意事项 / 风险处理

| 事项 | 说明 | 风险处理 |
|------|------|---------|
| SQLAlchemy 版本 | 选用 2.0.x，使用 2.x style declarative API / Mapped/mapped_column | 在 `requirements.txt` 锁定 `>=2.0.20` |
| PostgreSQL 特性 | JSONB、ON CONFLICT upsert 是 Postgres 专有；测试用 SQLite 内存库覆盖通用能力（建表/分页/批量插入/加密字段），upsert 测试走 SQL 方言分支隔离 | `db_base.upsert()` 检测 `dialect.name`，非 Postgres 走传统先查后更 |
| 加密密钥泄漏 | 密钥通过 `DB_ENCRYPTION_KEY` env 注入，**禁止写进源码、禁止写进日志** | `settings.db.DB_ENCRYPTION_KEY` 在日志打印时自动替换为 `***`（在 `settings` 对象 repr 中重写敏感字段方法，或简单在 db_base 里打印前过滤） |
| 联系字段长度 | `SensitiveString(256)` 已预留加密后的 base64 长度膨胀 | 测试覆盖 50~255 字符手机号/邮箱 |
| 大批量归档阻塞 | `mark_rows_archived()` 以 `batch_size=1000` 分批提交；放在凌晨定时任务里跑 | 日志记录每批处理耗时，超过阈值告警 |
| 多租户隔离 | 所有表默认 `tenant_id` 字段，业务查询须通过 `BaseModel` 上的 `for_tenant()` 辅助方法过滤 | 在 `BaseModel` 里提供 `for_tenant(tenant_id)` 类方法强制过滤 |
| 告警去抖 | DB 连接失败在 5 分钟内只告警一次，避免在网络抖动时告警风暴 | 在 `db_base.py` 内使用内存级 `dict[err_key] -> last_ts` 做去抖 |
| 测试依赖 | 单元测试使用 `sqlite:///:memory:`，不依赖真实 Postgres | 可在 CI 里追加 Postgres 容器端到端测试（可选） |

---

## 八、强制约束自检

- ✅ **架构规范**：全部放在 `infra/` + `core/compliance/`；不侵入 `spider_core / data_core / send_core`
- ✅ **配置规范**：所有可调项（数据库地址/账号/密码、加密密钥、归档周期、价值阈值、脱敏开关）全走 `.env`
- ✅ **隐私规范**：所有 contact_phone / contact_email / contact_wechat 通过 `SensitiveString` 自动加密；对外查询默认 `mask_value()` 脱敏
- ✅ **异常规范**：统一 `BizException`；数据库异常自动触发 `alert_service.service_exception_async()`
- ✅ **日志规范**：`get_logger("db")` 分类打日志，记录慢查询/批量行数/失败重试次数
- ✅ **目录规范**：不新增/删除/重命名目录；不动 README / DEVELOP_RULES / docs/TASK_LIST
- ✅ **业务零侵入**：不编写任何业务增删改查代码；仅提供基建与工具
