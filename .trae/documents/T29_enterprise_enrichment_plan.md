# T29 — 企业信息自动补全通用节点开发计划

> 版本：T29-v1.0 | 状态：待审批 | 范围：business/data_clean/

---

## 一、设计目标

在 T10 数据清洗流水线中新增**企业信息自动补全**通用节点，对接**企查查（QCC）**渠道，实现：
1. 从商机中提取的企业名称，自动补全**联系人、联系电话、企业邮箱、注册地址、企业规模、行业分类**
2. 支持**批量补全**（异步，不阻塞主流水线）与**单条补全**（实时，调试用）两种模式
3. 查询失败、查无结果的企业自动标记「待人工补全」进入异常池
4. 完整记录补全来源渠道、更新时间、置信度，便于审计和后续扩展（天眼查、爱企查）

---

## 二、新增文件清单（不修改任何现有文件内容结构）

所有文件均新增在 `business/data_clean/` 目录下：

| 序号 | 文件路径 | 角色 | 行数估算 |
|------|----------|------|---------|
| 1 | `business/data_clean/enterprise_enrich.py` | 核心：补全节点（pipeline step） | ~350 |
| 2 | `business/data_clean/enterprise_models.py` | Pydantic 数据模型：标准化企业信息结构 | ~150 |
| 3 | `business/data_clean/channels/qcc_client.py` | 企查查渠道封装：API + 网页双模式 | ~400 |
| 4 | `business/data_clean/channels/__init__.py` | 渠道包导出 | ~10 |
| 5 | `business/data_clean/enterprise_cache.py` | 本地结果缓存（避免重复查询同一企业） | ~120 |
| 6 | `business/data_clean/enterprise_settings.py` | 企业补全配置读取（全部从 .env） | ~100 |
| 7 | `tests/test_t29_enterprise_enrich.py` | 单元测试 | ~300 |

**合计：7 个文件，约 1430 行。**

### 2.1 对现有文件的最小侵入（仅 3 处 + 3 行）

为了接入到现有流水线，需要在**3 个文件**中做**极小的增量修改**（总新增 < 15 行）：

1. **`business/data_clean/pipeline.py`** — 在 `DataCleanPipeline.__init__` 中注入可选的补全节点；在 `run()` 中 normalize 后/ storage 前，调用异步补全触发（不阻塞）
2. **`business/data_clean/models.py`** — 在 `EntityExtract` 中新增 2 个字段：`enriched: bool = False`、`enrichment_source: str = ""`；在 `CleanTaskParams` 中新增 `run_enterprise_enrich: bool = False`
3. **`configs/settings.py`** — 在 `DataCleanSettings` 中新增 6 个 .env 可配置字段（用于控制企业补全开关、限流、渠道）

不修改：
- `README.md`
- `DEVELOP_RULES.md`
- `docs/TASK_LIST.md`
- `core/` 底层（spider_core, send_core, compliance 等 —— 直接 import 使用，不改源码）
- 任何 adapter/ 路由（用户若需 HTTP API，可后续在 `adapter/v1/data_clean/routes.py` 中增量追加，不在 T29 范围）

---

## 三、数据模型设计（enterprise_models.py）

### 3.1 企业信息标准化结构

```python
# EnterpriseProfile — 统一企业画像，屏蔽渠道差异
class EnterpriseProfile(BaseModel):
    # 标识
    company_name: str                   # 原始企业名称
    matched_name: str = ""              # 渠道返回的匹配名称
    qcc_id: str = ""                    # 企查查内部 ID（便于去重/后续扩展）

    # 核心联系方式（补全目标字段）
    contact_person: str = ""            # 联系人 / 法人
    contact_phone: str = ""             # 联系电话
    contact_email: str = ""             # 企业邮箱
    registered_address: str = ""        # 注册地址

    # 画像维度
    company_scale: str = ""             # 企业规模：微型 / 小型 / 中型 / 大型
    industry_category: str = ""         # 行业分类：如 IT / 制造业 / 服务业
    registered_capital: str = ""        # 注册资本（文本格式保留原始）
    establishment_date: str = ""        # 成立日期
    business_status: str = ""           # 经营状态：在营 / 注销 / 吊销等

    # 元信息
    confidence_score: float = 0.0       # 置信度 0-1
    source_channel: str = "qcc"         # 来源渠道 qcc / tyc / aiqicha
    source_mode: str = "api"            # api / web
    query_url: str = ""                 # 原始查询 URL（用于审计）
    queried_at: str = ""                # 查询时间 ISO

# EnterpriseEnrichResult — 单条补全结果
class EnterpriseEnrichResult(BaseModel):
    success: bool
    status: str                         # "enriched" / "not_found" / "failed" / "skipped"
    company_name: str
    profile: EnterpriseProfile | None = None
    error_message: str = ""
    needs_manual_review: bool = False
    enriched_fields: list[str] = []     # 实际补全了哪些字段：["contact_phone", "contact_email"]

# EnterpriseEnrichBatchResult — 批量结果
class EnterpriseEnrichBatchResult(BaseModel):
    task_id: str
    total: int = 0
    enriched: int = 0
    not_found: int = 0
    failed: int = 0
    skipped: int = 0
    items: list[EnterpriseEnrichResult] = []
    finished_at: str = ""
```

### 3.2 与现有模型对接（models.py 极小增量）

```python
# 在 EntityExtract 中新增 2 个字段（位置放末尾）
class EntityExtract(BaseModel):
    company_names: list[str] = Field(default_factory=list)
    phone_numbers: list[str] = Field(default_factory=list)
    wechat_ids: list[str] = Field(default_factory=list)
    industry_tags: list[str] = Field(default_factory=list)
    region: str = ""
    keywords: list[str] = Field(default_factory=list)
    budget: dict[str, Any] = Field(default_factory=dict)
    estimated_text_length: int = 0

    # ===== T29 新增（兼容旧数据：默认值 = 空）=====
    enriched: bool = False              # 是否已通过企业补全节点处理
    enrichment_source: str = ""         # qcc / tyc / aiqicha
    enrichment_profile: dict[str, Any] = Field(default_factory=dict)  # 完整画像（JSON 存储）
```

### 3.3 与现有 CleanTaskParams 对接

```python
# 在 CleanTaskParams 末尾新增
class CleanTaskParams(BaseModel):
    # ...（现有字段不变）...
    # ===== T29 新增 =====
    run_enterprise_enrich: bool = False  # 是否启用企业信息自动补全
    enrich_mode: str = "async"           # async / sync — 批量 / 单条
    enrich_channel: str = "qcc"          # qcc / tyc / aiqicha
```

---

## 四、企查查渠道设计（business/data_clean/channels/qcc_client.py）

### 4.1 架构图

```
                ┌────────────────────────────────────────────────────────┐
                │           QccEnterpriseClient                          │
                │  ┌─────────┐    ┌─────────┐   ┌─────────┐  ┌─────────┐│
     输入企业名 → │ │ 限流层  │ → │ │ 账号池 │ → │ 代理池 │→ │ 查询层 ││
                │  │(RateLimiter)│   │轮询+熔断│   │(ProxyPool)│   │API+Web││
                │  └─────────┘    └─────────┘   └─────────┘  └─────────┘│
                │       ↓              ↓             ↓             ↓    │
                │  ┌─────────────────────────────────────────────────┐  │
                │  │                    风控层                       │  │
                │  │  • 单账号日查询上限 (SENTINEL_ACCOUNT_DAILY_LIMIT) │  │
                │  │  • 连续失败 3 次 → 切换账号/代理                  │  │
                │  │  • 账号超限 → 自动告警 + 熔断暂停                 │  │
                │  │  • 网页模式：最低 3 秒间隔，模拟 UA 轮换             │  │
                │  └─────────────────────────────────────────────────┘  │
                │                        ↓                              │
                │  ┌─────────────────────────────────────────────────┐  │
                │  │                  标准化输出                      │  │
                │  │   • 字段名统一（phone / email / address / ...）   │  │
                │  │   • 脱敏（联系方式自动 mask 后返回）                │  │
                │  │   • 置信度评分（来源字段完整性 × 渠道可信度）        │  │
                │  └─────────────────────────────────────────────────┘  │
                │                        ↓                              │
                └─────────────────────────┬────────────────────────────┘
                                          │
                                          ▼
                          EnterpriseProfile（标准结构）
```

### 4.2 双模式实现

**模式 A：官方 API 模式**（生产环境推荐）
- 通过企查查开放平台 HTTP API 查询（企业工商信息接口）
- 需要在 `.env` 配置 `QCC_API_KEY` 和 `QCC_API_BASE_URL`
- 返回 JSON 格式，字段完整，频率可控

**模式 B：网页采集模式**（API 不可用时的回退方案）
- 使用 `core.spider_core.SpiderSDK.get()` 访问企查查搜索页
- 通过正则 / XPath 提取企业详情页
- 关键规则：最低 3 秒间隔，UA 轮换，代理轮换
- 遵守 `robots.txt`（通过 spider SDK 的 robots_checker）

### 4.3 账号池与熔断

```python
# 账号池数据结构
@dataclass
class QccAccount:
    key: str                          # API Key / Cookie（取决于模式）
    mode: str                         # "api" / "web"
    daily_quota: int                  # 日查询上限（来自 .env）
    used_today: int = 0               # 今日已用计数（Redis 存储）
    failure_streak: int = 0           # 连续失败次数
    is_circuit_broken: bool = False   # 是否熔断
    circuit_break_until: float = 0.0  # 熔断到期时间戳
```

- **账号轮询策略**：Round-Robin 循环取可用账号（`is_circuit_broken = False` 且 `used_today < daily_quota`）
- **连续失败 3 次** → 该账号标记熔断 10 分钟，换下一个账号
- **日查询超限** → 该账号当日禁用，记录到 Redis（key: `qcc:account:<key>:used:<date>`）
- **全账号熔断** → 触发告警，整体任务暂停 30 分钟

### 4.4 限流（复用 T08 send_core 限流思路，不造新轮子）

```python
# 不写新的限流实现，直接复用 core.spider_core.SpiderSDK 自带 DomainRateLimiter
# 再加一层业务级限流（通过 Redis 原子计数）
#
# Redis keys:
#   qcc:query:global:<date>        → 全局当日查询计数
#   qcc:query:account:<key>:<date> → 单账号当日查询计数
#   qcc:query:minute:<timestamp>   → 每分钟查询计数（用于短周期限流）
```

---

## 五、补全节点接入流水线位置（enterprise_enrich.py）

### 5.1 现有流水线回顾

```
原始记录
   ↓
 加载 (load_pending_records)
   ↓
 过滤脏数据 (DirtyFilter)
   ↓
 实体抽取 (EntityExtractor) → [企业名称, 电话, 微信, 行业, ...]
   ↓
 合规检查 (ComplianceStep)
   ↓
 引擎评分 (EngineStep)       ←——— 可选（params.run_engine）
   ↓
 标准化 (Normalizer)          ←——— 写入 StructuredOpportunity
   ↓
 持久化 (Storage)             ←——— 写入 structured_opportunity 表
   ↓
 告警 + 任务状态               ←——— 写入 Redis
```

### 5.2 T29 接入位置

```
...（前面完全不变）...
   ↓
 持久化 (Storage)             ←——— 主流程先完成存储（不阻塞）
   ↓
 ┌──────────────────────────────────────────────────────────────────┐
 │   T29: 企业信息补全节点   (EnterpriseEnrichStep)                   │
 │   触发条件: params.run_enterprise_enrich = True                    │
 │   AND entities.company_names 非空                                   │
 │   AND 当前 entities 中没有 phone/wechat（已有联系方式的不覆盖）      │
 │                                                                    │
 │   ┌─ async 模式（默认）：                                          │
 │   │   收集所有待补全企业名称 → 写入 Redis 任务队列                │
 │   │   由后台 worker 异步消费处理（不阻塞当前清洗请求）            │
 │   │   结果通过 Storage.update_opportunity_enrichment() 回写       │
 │   └─ sync 模式（调试/单条）：                                       │
 │       直接调用 QccEnterpriseClient.query() 实时返回补全结果        │
 │       合并到当前 StructuredOpportunity.entities                    │
 │                                                                    │
 │   ┌─ 优先级策略（符合"已有联系方式不覆盖"约束）：                    │
 │   │   1. 原数据 phone_numbers 非空 → 跳过该企业                    │
 │   │   2. 原数据 wechat_ids 非空 → 跳过该企业                       │
 │   │   3. 否则 → 发起补全                                          │
 │   │   4. 补全后的字段：只填写原数据为 empty 的字段                 │
 │   └─                                                              │
 │                                                                    │
 │   ┌─ 异常池标记：                                                  │
 │   │   查询失败/查无结果 → anomaly.type="enrichment_missing"       │
 │   │                          severity="info"/"warn"              │
 │   │                          needs_review=True                   │
 │   └─                                                              │
 └──────────────────────────────────────────────────────────────────┘
   ↓
 告警 + 任务状态               ←——— 原有逻辑（现在包含企业补全统计）
```

### 5.3 核心类设计

```python
# enterprise_enrich.py
class EnterpriseEnrichStep:
    """企业信息自动补全节点。
    - 输入: list[RawRecord], list[EntityExtract]
    - 输出: 异步任务 ID（async）或 直接更新后的 entities（sync）
    """

    def __init__(
        self,
        *,
        channel: str = "qcc",
        mode: str = "async",
        storage: Storage | None = None,
    ) -> None:
        self.channel = channel
        self.mode = mode
        self.storage = storage or Storage()
        self.cache = EnterpriseCache()
        self.client = _get_client(channel)  # 工厂函数，QccEnterpriseClient

    # ---- 主入口 ----
    def process_batch(
        self,
        opportunities: list[StructuredOpportunity],
        *,
        enrich_mode: str = "async",
    ) -> dict[str, int]:
        """处理一批商机的企业信息补全。
        返回统计: {"total": N, "enriched": N, "not_found": N, "failed": N}
        """
        # 1) 筛选需要补全的企业（排除已有联系方式的）
        pending = self._filter_pending(opportunities)
        if not pending:
            return {"total": 0, "enriched": 0, "not_found": 0, "failed": 0, "skipped": len(opportunities)}

        if enrich_mode == "sync":
            return self._process_sync(pending, opportunities)
        else:
            return self._process_async(pending, opportunities)

    # ---- 同步（单条/调试）----
    def _process_sync(self, pending: list[StructuredOpportunity], all: list[StructuredOpportunity]) -> dict:
        stats = {"total": len(pending), "enriched": 0, "not_found": 0, "failed": 0, "skipped": 0}
        for opp in pending:
            company = (opp.entities.company_names or [""])[0] if opp.entities.company_names else ""
            if not company:
                continue
            # 命中缓存
            cached = self.cache.get(company)
            if cached:
                self._apply_profile(opp, cached, cached_source="cache")
                stats["enriched"] += 1
                continue
            try:
                profile = self.client.query(company)
                if profile is not None:
                    self.cache.set(company, profile)
                    self._apply_profile(opp, profile, cached_source=self.channel)
                    stats["enriched"] += 1
                else:
                    self._mark_for_review(opp, "not_found", "企查查未查询到该企业")
                    stats["not_found"] += 1
            except Exception as exc:
                self._mark_for_review(opp, "failed", f"查询异常: {exc}")
                stats["failed"] += 1
        # 回写已补全的商机（仅更新 enrichment_* 字段）
        self.storage.update_opportunity_enrichments(pending)
        return stats

    # ---- 异步（批量，不阻塞）----
    def _process_async(self, pending: list[StructuredOpportunity], all: list[StructuredOpportunity]) -> dict:
        """通过 Redis 队列派发异步任务，立即返回。"""
        task_id = _gen_task_id()
        queue_payload = {
            "task_id": task_id,
            "items": [
                {"opportunity_id": o.opportunity_id, "tenant_id": o.tenant_id,
                 "company_name": (o.entities.company_names or [""])[0] if o.entities.company_names else ""}
                for o in pending
            ],
            "channel": self.channel,
        }
        _push_to_queue(queue_payload)
        return {"task_id": task_id, "total": len(pending), "mode": "async"}

    # ---- 辅助 ----
    def _filter_pending(self, opps: list[StructuredOpportunity]) -> list[StructuredOpportunity]:
        """筛选需要补全的商机：有企业名 + 无联系方式 + 尚未补全过。"""
        result = []
        for opp in opps:
            ent = opp.entities
            if not ent:
                continue
            # 已补全过（enriched = True）→ 跳过
            if getattr(ent, "enriched", False):
                continue
            # 已有联系方式 → 不覆盖，跳过
            if (ent.phone_numbers or []) or (ent.wechat_ids or []):
                continue
            # 至少有一个企业名称
            if not (ent.company_names or []):
                continue
            result.append(opp)
        return result

    def _apply_profile(self, opp: StructuredOpportunity, profile: EnterpriseProfile, cached_source: str) -> None:
        """将补全结果合并到原有实体字段（只填 empty 字段）。"""
        ent = opp.entities
        # 1) 空字段填充（不覆盖已有）
        if not (ent.phone_numbers or []) and profile.contact_phone:
            ent.phone_numbers = [profile.contact_phone]
        if not (ent.wechat_ids or []) and profile.contact_email:
            # email 放 wechat_ids[0] 不合适；这里存到 enrichment_profile 中
            pass
        # 2) 画像信息写入 enrichment_profile dict（结构化存储）
        ent.enrichment_profile = profile.model_dump(mode="json")
        ent.enriched = True
        ent.enrichment_source = cached_source

    def _mark_for_review(self, opp: StructuredOpportunity, reason_type: str, message: str) -> None:
        """查无结果或查询失败的企业，标记异常池。"""
        from business.data_clean.models import AnomalyRecord
        anomaly = AnomalyRecord(
            anomaly_id=f"enrich_{opp.opportunity_id}",
            tenant_id=opp.tenant_id,
            source_record_id=None,
            type=f"enrichment_{reason_type}",
            severity="warn" if reason_type == "not_found" else "error",
            reason=message,
            raw_snippet=((opp.entities.company_names or [""])[0] if opp.entities.company_names else "")[:100],
            pipeline_version="T29-v1.0",
            needs_review=True,
            spider_name=opp.source.spider_name if opp.source else "",
            source_url=opp.source.source_url if opp.source else "",
        )
        self.storage.upsert_anomalies([anomaly])


# =====================
# 异步 worker（后台消费 Redis 队列，调用 QCC API）
# =====================
class EnterpriseEnrichWorker:
    """后台 worker：从 Redis 消费补全任务 → 查询 QCC → 回写数据库。
    入口: python -m business.data_clean.enterprise_enrich worker
    （实际部署时：由 adapter/ 或 infra/ 中已有的 queue worker 挂载）
    """
    # （简化实现：轮询 Redis 列表 key，逐条执行）
    def run_once(self) -> None: ...
    def run_loop(self, poll_interval: float = 5.0) -> None: ...
```

### 5.4 存储扩展（storage.py 增量：新增 update_opportunity_enrichments 方法）

**不修改现有 upsert_opportunities 等方法**，新增一个专用于补全回写的方法：

```python
# 在 Storage 类末尾新增
class Storage:
    # ...（原有方法不变）...

    def update_opportunity_enrichments(self, opportunities: list[StructuredOpportunity]) -> int:
        """仅更新 enrichment_* 字段的原子 upsert。
        只更新: enriched, enrichment_source, enrichment_profile。
        不触动其他业务字段（标题、评分、合规等）。
        """
        if not opportunities:
            return 0
        rows = []
        for o in opportunities:
            if not (o.entities and getattr(o.entities, "enriched", False)):
                continue
            rows.append({
                "tenant_id": o.tenant_id,
                "opportunity_id": o.opportunity_id,
                "entities_json": o.entities.model_dump(mode="json"),
                "pipeline_trace": "enrich",  # append
            })
        if not rows:
            return 0
        try:
            # 通过数据库原子更新：只覆盖 entities_json 中的 enrichment 字段
            database.bulk_update_enrichments(rows)  # 调用 infra 层的原子更新
            return len(rows)
        except Exception as exc:
            logger.warning(f"update_opportunity_enrichments 失败: {exc}")
            return 0
```

---

## 六、企业补全配置（enterprise_settings.py）

### 6.1 所有字段都从 .env 读取，零硬编码

```python
class EnterpriseEnrichSettings(BaseSettings):
    """T29 企业信息补全节点配置 —— 全部从 .env 读取。
    敏感字段不打印到日志（通过 masked_repr 过滤）。
    """
    model_config = SettingsConfigDict(env_prefix="", extra="ignore")

    # ---- 总开关 ----
    ENRICH_ENABLED: bool = False
    ENRICH_VERSION: str = "T29-v1.0"

    # ---- 渠道选择 ----
    ENRICH_CHANNEL: str = "qcc"      # qcc / tyc / aiqicha（目前只实现 qcc）
    ENRICH_MODE: str = "async"       # async / sync

    # ---- 企查查 API 配置 ----
    QCC_API_BASE_URL: str = "https://api.qcc.com/api"
    QCC_API_KEY: str = ""            # (敏感，必填)
    QCC_API_KEY_2: str = ""          # 备用 key
    QCC_API_KEY_3: str = ""          # 备用 key

    # ---- 风控/限流 ----
    # 单账号日查询上限
    ENRICH_ACCOUNT_DAILY_LIMIT: int = 200
    # 全局每日查询上限（所有账号合计）
    ENRICH_GLOBAL_DAILY_LIMIT: int = 500
    # 单账号连续失败次数阈值
    ENRICH_ACCOUNT_FAILURE_THRESHOLD: int = 3
    # 账号熔断冷却期（秒）
    ENRICH_ACCOUNT_COOLDOWN_SECONDS: int = 600
    # API 请求间隔（秒）
    ENRICH_API_INTERVAL_SECONDS: float = 3.0
    # 网页模式最小间隔（安全起见更长）
    ENRICH_WEB_INTERVAL_SECONDS: float = 5.0

    # ---- 缓存 ----
    ENRICH_CACHE_ENABLED: bool = True
    ENRICH_CACHE_TTL_SECONDS: int = 7 * 24 * 3600   # 7 天

    # ---- 字段补全策略 ----
    # 已有联系方式是否跳过（默认 True = 跳过，不覆盖）
    ENRICH_SKIP_IF_CONTACT_EXISTS: bool = True
    # 是否只补全空值字段（默认 True）
    ENRICH_FILL_EMPTY_ONLY: bool = True
    # 最低置信度阈值（< 此值的结果不写入）
    ENRICH_MIN_CONFIDENCE: float = 0.5

    # ---- PII 加密与脱敏 ----
    # 联系方式入库是否加密（默认 True，使用 DB_ENCRYPTION_KEY）
    ENRICH_ENCRYPT_CONTACT: bool = True
    # 前端展示是否自动脱敏（默认 True）
    ENRICH_MASK_IN_OUTPUT: bool = True

    # ---- 告警 ----
    ENRICH_ALERT_ON_ACCOUNT_EXHAUSTED: bool = True
    ENRICH_ALERT_ON_BATCH_FAILURE_RATIO: float = 0.2  # 批量失败率 > 20% 时告警

    def masked_repr(self) -> dict:
        data = self.model_dump()
        for key in ("QCC_API_KEY", "QCC_API_KEY_2", "QCC_API_KEY_3"):
            if data.get(key):
                data[key] = "***"
        return data

# 单例
enrich_settings = EnterpriseEnrichSettings()
```

### 6.2 .env.example 中需追加的新配置项（作为文档）

```
# ========== T29: 企业信息自动补全 ==========
ENRICH_ENABLED=true
ENRICH_CHANNEL=qcc                  # qcc / tyc / aiqicha
ENRICH_MODE=async                   # async（异步批量）/ sync（同步单条）

# 企查查 API（敏感密钥：不提交到版本控制）
QCC_API_BASE_URL=https://api.qcc.com/api
QCC_API_KEY=your-qcc-api-key-here
QCC_API_KEY_2=your-backup-key-2
QCC_API_KEY_3=your-backup-key-3

# 风控/限流（全部从 .env 读取）
ENRICH_ACCOUNT_DAILY_LIMIT=200
ENRICH_GLOBAL_DAILY_LIMIT=500
ENRICH_ACCOUNT_FAILURE_THRESHOLD=3
ENRICH_ACCOUNT_COOLDOWN_SECONDS=600
ENRICH_API_INTERVAL_SECONDS=3.0
ENRICH_WEB_INTERVAL_SECONDS=5.0

# 缓存
ENRICH_CACHE_ENABLED=true
ENRICH_CACHE_TTL_SECONDS=604800     # 7 天

# 补全策略
ENRICH_SKIP_IF_CONTACT_EXISTS=true
ENRICH_FILL_EMPTY_ONLY=true
ENRICH_MIN_CONFIDENCE=0.5

# PII 加密/脱敏
ENRICH_ENCRYPT_CONTACT=true
ENRICH_MASK_IN_OUTPUT=true

# 告警
ENRICH_ALERT_ON_ACCOUNT_EXHAUSTED=true
ENRICH_ALERT_ON_BATCH_FAILURE_RATIO=0.2
```

---

## 七、缓存设计（enterprise_cache.py）

### 7.1 策略

- **命中**：企业名称 → 直接返回缓存的 EnterpriseProfile
- **未命中**：发起查询 → 结果写入缓存
- **TTL**：7 天（避免频繁查询同一企业浪费额度）
- **存储**：Redis（优先）→ 降级到进程内 dict（本地调试）

### 7.2 Redis Key 设计

```
qcc:cache:md5("<normalized_company_name>")  →  JSON(EnterpriseProfile)
qcc:cache:negative:<md5>                    →  "not_found"（TLL 24 小时，避免死查）
qcc:cache:global:<date>                     →  计数器
qcc:cache:account:<key>:<date>              →  账号日查询计数器
```

### 7.3 企业名称规范化（关键去重逻辑）

```python
def _normalize_company(name: str) -> str:
    """企业名称规范化 → 作为缓存 key 基础。
    - 去除空格、标点
    - 统一全角/半角
    - 去除 "有限公司" / "股份有限公司" / "有限责任公司" 等后缀的差异
    - 全小写 → md5
    """
    if not name:
        return ""
    s = name.strip().lower()
    s = re.sub(r"\s+", "", s)
    s = re.sub(r"[·•.，,（）()【】\[\]【】\-·]", "", s)
    # 统一后缀变体 → 去尾
    suffixes = ["有限公司", "股份有限公司", "有限责任公司", "公司", "group", "co.,ltd", "co.,ltd.", "ltd", "inc"]
    for suf in suffixes:
        if s.endswith(suf.lower()):
            s = s[:-len(suf)]
            break
    return s
```

---

## 八、风控与异常处理

### 8.1 四级风控体系

| 级别 | 触发条件 | 处理方式 | 告警 |
|------|----------|---------|-----|
| L1 | 单账号连续失败 ≤ 2 次 | 重试当前账号，递增间隔 (1s→3s→5s) | - |
| L2 | 单账号连续失败 ≥ 3 次 | 切换下一个账号，旧账号熔断 10 分钟 | WARN |
| L3 | 单账号日查询超限 | 禁用该账号当日，切换下一账号 | WARN |
| L4 | 所有账号均熔断 / 全部超限 | 暂停整体任务 30 分钟后重试 | ERROR + 钉钉/邮件告警 |

### 8.2 异常日志与失败重跑

```python
# 每次补全任务的全量日志写入 Redis hash
#   qcc:task:<task_id> → {
#       "status": "completed" / "partial" / "failed",
#       "total": 50, "enriched": 42, "not_found": 5, "failed": 3,
#       "failures": "[{\"company\":\"XX科技\",\"error\":\"HTTP 429\"},...]"
#   }
#
# 失败任务重跑：提供 EnterpriseEnrichWorker.retry_failed(task_id)
#   从 Redis hash 中读取 failures 列表 → 对失败条目重新发起查询
```

---

## 九、PII 隐私保护与加密

### 9.1 数据流程与保护点

```
   QCC 原始响应（含明文手机号/邮箱）
            ↓
   [PII 加密层] → 写入 DB 前加密（使用 DB_ENCRYPTION_KEY）
            ↓
   数据库：structured_opportunity.entities_json
       → contact_phone: "<encrypted:AES256-GCM>"
       → contact_email: "<encrypted:AES256-GCM>"
            ↓
   [PII 脱敏层] → 前端读取时自动 mask（复用 core.compliance.pii_mask.PIIMask）
            ↓
   前端展示： 138****8000 / u***r@company.com
```

### 9.2 实现要点

- **加密**：使用项目已有的 `DB_ENCRYPTION_KEY` 作为密钥，AES-256-GCM 加密
- **脱敏**：直接调用 `core.compliance.pii_mask.pii_mask.mask_phone() / mask_email()`
- **日志不打印明文**：所有 logger 输出时自动 mask（在 QccEnterpriseClient._log_response 中处理）
- **查询 URL 也不记录明文参数**：URL 中若带 key 则替换为 `***`

---

## 十、开发分步执行计划

### Phase 1: 数据模型与配置（约 1 小时）

1. ✅ 创建 `business/data_clean/enterprise_models.py` — Pydantic models
2. ✅ 创建 `business/data_clean/enterprise_settings.py` — 配置读取
3. ✅ 更新 `business/data_clean/models.py` — 新增 3 个字段到 EntityExtract / CleanTaskParams
4. ✅ 更新 `configs/settings.py` — 在 DataCleanSettings 中注入 enrich 字段别名（可选简化路径）

### Phase 2: 企查查渠道客户端（约 3 小时）

5. ✅ 创建 `business/data_clean/channels/__init__.py`
6. ✅ 创建 `business/data_clean/channels/qcc_client.py`
   - 账号池数据结构 + 轮询逻辑
   - API 模式：requests → JSON 解析 → EnterpriseProfile
   - Web 模式：SpiderSDK.get() → 正则 / XPath 解析
   - 限流（基于 Redis atomic counter）
   - 账号熔断：连续失败与额度管理
   - PII 保护：日志/存储自动 mask
7. ✅ 单元测试：`test_qcc_client_api_mode` / `test_qcc_client_web_mode` / `test_qcc_account_pool`

### Phase 3: 补全节点 + 缓存（约 2 小时）

8. ✅ 创建 `business/data_clean/enterprise_cache.py` — EnterpriseCache
9. ✅ 创建 `business/data_clean/enterprise_enrich.py` — EnterpriseEnrichStep + EnterpriseEnrichWorker
10. ✅ 更新 `business/data_clean/storage.py` — 新增 `update_opportunity_enrichments()` 方法（不修改任何已有方法）
11. ✅ 单元测试：`test_enrich_step_filter_pending` / `test_enrich_step_apply_profile` / `test_cache_hit_miss`

### Phase 4: 流水线接入（约 30 分钟）

12. ✅ 更新 `business/data_clean/pipeline.py`
   - 在 `DataCleanPipeline.__init__` 中注入 `enterprise_enrich_step`（可选，仅当 `ENRICH_ENABLED=true`）
   - 在 `DataCleanPipeline.run()` 的 storage 完成后，调用 `enterprise_enrich_step.process_batch()`（异步模式不阻塞）
   - 在 `CleanRunResult` 中新增 1 个字段：`enrichment_task_id: str | None = None`（用于追踪）

### Phase 5: 集成测试 + 文档补全（约 1 小时）

13. ✅ 创建 `tests/test_t29_enterprise_enrich.py` — 端到端测试：
   - 构造 5 条模拟商机（含 2 条已有联系方式应跳过、1 条查无结果、1 条查询失败、1 条补全成功）
   - 验证：跳过正确、标记异常正确、字段合并正确、缓存命中
14. ✅ 通过 `python -m pytest tests/test_t29_enterprise_enrich.py -v` 验收

---

## 十一、复用现有能力清单（不重复造轮子）

| 能力 | 原有实现 | 被 T29 复用方式 |
|------|---------|----------------|
| HTTP 请求 | `core.spider_core.SpiderSDK.get()` / `_http_get` | QCC API + Web 模式的底层请求实现 |
| 代理池 | `core.spider_core.proxy_pool.ProxyPool` | SpiderSDK 内部自动处理 |
| UA 轮换 | `core.spider_core.ua_pool.UserAgentPool` | SpiderSDK 内部自动处理 |
| 域名限流 | `core.spider_core.rate_limiter.DomainRateLimiter` | SpiderSDK 内部自动处理 |
| robots.txt 合规 | `core.spider_core.robots_checker.RobotsChecker` | Web 模式自动应用 |
| 风控检测 | `core.spider_core.risk_controller.RiskController` | 429/ban 检测 |
| 进程内队列 | `infra.task_queue` / Redis list | 异步任务队列 |
| 日志 | `infra.logger_setup.get_logger()` | 全链路日志 |
| PII 脱敏 | `core.compliance.pii_mask.PIIMask` | 联系方式 mask |
| 数据加密 | `infra.db_base` / `DB_ENCRYPTION_KEY` | 敏感字段存储加密 |
| 告警 | `infra.alerting.alert_service` | 账号耗尽/失败率告警 |
| 数据持久化 | `business.data_clean.storage.Storage` | 补全结果回写 |
| 异常池 | `business.data_clean.models.AnomalyRecord` | 查无结果/失败的企业 |

---

## 十二、约束与合规自检

- ✅ **目录结构不变**：所有新增文件在 `business/data_clean/` 下，不新增一级目录
- ✅ **不修改核心文档**：README.md / DEVELOP_RULES.md / docs/TASK_LIST.md 不改动
- ✅ **不改 core 层源码**：只 import 使用 core.spider_core / core.compliance / infra.*
- ✅ **配置全部从 .env 读取**：无任何硬编码密钥/URL
- ✅ **PII 保护**：联系方式入库加密 + 展示脱敏
- ✅ **网页采集合规**：最低 3 秒间隔 + robots.txt + UA 模拟 + 代理轮换
- ✅ **不覆盖已有联系方式**：`ENRICH_SKIP_IF_CONTACT_EXISTS=true`

---

## 十三、测试计划

### 13.1 单元测试（pytest）

| 测试用例 | 目标 | 位置 |
|---------|------|-----|
| test_enterprise_profile_serialization | EnterpriseProfile JSON 往返 | enterprise_models.py |
| test_qcc_api_mode_happy_path | Mock API → 返回合法 JSON → 解析成 EnterpriseProfile | qcc_client.py |
| test_qcc_api_mode_not_found | Mock API 返回"查无此公司" → 返回 None 且不抛异常 | qcc_client.py |
| test_qcc_account_pool_round_robin | 3 个账号 → 第 1 个失败 3 次熔断 → 切到第 2 个 | qcc_client.py |
| test_qcc_account_pool_quota | 账号用完额度 → 自动切下一账号 | qcc_client.py |
| test_enrich_step_filter_pending | 已有联系方式的商机被跳过；无企业名的被跳过 | enterprise_enrich.py |
| test_enrich_step_apply_profile | 只填充 empty 字段，不覆盖已有数据 | enterprise_enrich.py |
| test_cache_hit_miss | 命中缓存不发起查询；未命中后写入缓存 | enterprise_cache.py |
| test_pii_mask_in_output | 返回给前端的 phone/email 被脱敏 | qcc_client.py + compliance |

### 13.2 集成测试

```
# tests/test_t29_enterprise_enrich.py
def test_e2e_enrichment_pipeline():
    """
    构造 5 条 StructuredOpportunity:
      1. 企业名 = "阿里云计算有限公司" + 无联系方式 → 应补全
      2. 企业名 = "腾讯科技深圳有限公司" + 已有 phone_numbers=["138xxxxxxxxx"] → 应跳过
      3. 企业名 = "不存在的公司xyz123" + 无联系方式 → 查无结果 → 入异常池
      4. 企业名 = "" + 无联系方式 → 跳过
      5. 企业名 = "华为技术有限公司" + 无联系方式 + (Mock HTTP Error) → 查询失败 → 入异常池
    断言：
      - enriched = 1, not_found = 1, failed = 1, skipped = 2
      - 结果第 1 条的 entities.phone_numbers 应含 1 个号码
      - 结果第 1 条的 entities.enriched = True
      - 结果第 2 条的 entities.phone_numbers 保持原样（不被覆盖）
      - anomaly_pool 中应有 2 条 type="enrichment_not_found" / "enrichment_failed"
    """
```

### 13.3 手动验收

```bash
# 1) 安装依赖（无新增第三方依赖；仅使用已有: requests + playwright）
# 2) 配置 .env 中 QCC_API_KEY
# 3) 启动服务
docker compose -f docker/docker-compose.yml up app-dev -d

# 4) 触发一次单条补全（通过 adapter HTTP API 或 python 脚本）
python -c "
from business.data_clean.channels.qcc_client import QccEnterpriseClient
client = QccEnterpriseClient(mode='api')
profile = client.query('阿里云计算有限公司')
print(profile.model_dump_json(indent=2))
"

# 5) 查看日志 + 异常池确认
```

---

## 十四、风险与应对

| 风险 | 概率 | 影响 | 应对策略 |
|-----|------|------|---------|
| 企查查 API 响应字段变更（版本升级） | 中 | 解析失败 → 补全不生效 | 字段提取使用 `get()` + try/except；默认空值 → 不阻塞主流程 |
| 账号额度耗尽 | 高 | 补全任务失效 | 账号池 3 个 key 轮询 + 熔断 + 告警 |
| 查询被反爬虫封禁（网页模式） | 高 | 网页模式失效，回退 API | 代理池轮换 + UA 轮换 + 5 秒间隔 |
| Redis 不可用 → 计数器/队列失效 | 低 | 限流失效，可能触发超量查询 | Redis 降级 → 进程内 dict 计数器（单进程内仍有效），并告警 |
| 企业名称规范化导致匹配错误 | 中 | 查不到 → 补全失败 | 规范化只去空格/大小写/常见后缀；保留原文用于二次查询 |
| 补全后的数据与商机中已有联系方式冲突 | 低 | 覆盖用户原有数据 | `ENRICH_SKIP_IF_CONTACT_EXISTS=true`（默认启用） |

---

## 十五、后续扩展点（不在 T29 范围内）

1. **天眼查 / 爱企查 渠道**：通过 `EnterpriseEnrichStep._get_client(channel)` 工厂模式扩展
2. **HTTP API 端点**：在 `adapter/v1/data_clean/routes.py` 中新增 `/enterprise/enrich`
3. **Web 管理后台页面**：在 `web_admin/pages.py` 中新增企业补全管理页
4. **多渠道聚合**：同时查询 qcc + tyc，取置信度最高的结果或合并去重
5. **定时自动重跑**：每天定时检测 `anomaly_pool` 中 `needs_review=True` 的企业，自动重试

---

**计划编写人：** BizTools4Openclaw Team
**版本：** T29-v1.0
**预计代码量：** ~1430 行（不含测试）
**预计开发时间：** 约 7-8 小时（含测试）
**依赖审批项：** 需用户提供 QCC API Key（配置 .env），以及 Redis 服务可用（项目已有）
