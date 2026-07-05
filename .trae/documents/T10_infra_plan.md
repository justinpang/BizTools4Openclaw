# T10 商机数据清洗、实体抽取、结构化标准化流水线 —— 开发计划

## 1. 现状总览

### 1.1 可复用的底层通用能力

| 模块 | 关键 API | T10 使用方式 |
|---|---|---|
| `core.data_core.OpportunityPipeline` | `opportunity_pipeline.process_batch(clues)` → `PipelineResult(items=list[ScoredOpportunity])` | 已包含 **去重 + 合并 + 打分 + 分级 + 黑名单** —— T10 仅封装调用 |
| `core.data_core.ScoredOpportunity` | 字段见 §5 | 标准化输出的骨架 |
| `core.compliance.sensitive_filter` | `sensitive_filter.filter_text(text)` → `FilterResult{risk, hits, is_blocked}` | 脏数据过滤 + 违规标记 |
| `core.compliance.pii_mask` | `pii_mask.auto_mask(text)` → 脱敏文本 | 隐私字段剔除/脱敏 |
| `core.compliance.compliance_checker` | `compliance_checker.check_for_storage(dict)` → `ComplianceReport` | 整体合规评分 |
| `core.compliance.privacy_stripper` | `privacy_stripper.strip(dict, keys=None)` → 字典隐私字段剔除 | 原始 payload 自动掩码 |
| `infra.db_base.database` | `bulk_insert / upsert` | 写入结构化表 + 异常池 |
| `infra.alerting.alert_service` | `service_exception_sync(msg, extra_data)` | 异常/高违规批量告警 |

### 1.2 T10 目标与约束（原文）

> 串行链路：原始数据加载 → 脏数据过滤 → 实体抽取 → 合规校验 → 去重合并 → 打分分级 → 结构化输出入库
>
> 异常数据分流：解析失败、实体提取错乱、超高违规文本单独标记入异常池
>
> **不覆盖原始爬虫数据，单独写入结构化商机表 + 异常池**
>
> 所有阈值/关键词库读 `.env`，禁止硬编码

---

## 2. 新增文件清单

```
configs/settings.py                     (更新：新增 DataCleanSettings)
business/data_clean/__init__.py          (更新：导出公共 API)
business/data_clean/models.py            (新增：CleanTaskParams / CleanResult / StructuredOpportunity / AnomalyRecord)
business/data_clean/loader.py            (新增：从 SpiderRawData 加载原始数据)
business/data_clean/filters.py           (新增：脏数据过滤器 + 可插拔规则)
business/data_clean/extractor.py         (新增：实体抽取器)
business/data_clean/compliance_step.py   (新增：合规校验 + 隐私剔除)
business/data_clean/engine_step.py       (新增：调用 T07 opportunity_pipeline)
business/data_clean/normalizer.py        (新增：标准化/对齐 OpenClaw 输入规范)
business/data_clean/storage.py           (新增：写入结构化表 + 异常池)
business/data_clean/pipeline.py          (新增：串联所有步骤 + 任务入口)
business/data_clean/registry.py          (新增：对外暴露 run_cleaning / list_tasks)
tests/test_t10_cleaning.py               (新增：单元/集成测试)
```

---

## 3. 流水线串行执行步骤与数据流转

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                               RawSpiderData                                   │
│  (id, tenant_id, raw_payload, raw_text, source_url, source_id, spider_name) │
└──────────────────────────┬──────────────────────────────────────────────────┘
                           │  1. loader.py :: load_pending_records(batch_size=N, cursor=X)
                           │  → list[RawRecord]  （dataclass：原表一行）
                           ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│  DirtyFilterStep                                                             │
│  规则：(a) 空内容或字符少于 MIN_TEXT_LEN                                    │
│         (b) 广告灌水模式（纯链接/重复单字/Emoji 堆）                          │
│         (c) 已失效链接（可选 HEAD）                                          │
│         (d) 已在黑名单源域/关键词命中 BLACKLIST_DOMAINS                      │
│  输出：passed: list[RawRecord]  rejected: list[AnomalyRecord]               │
└──────────────────────────┬──────────────────────────────────────────────────┘
                           │  passed
                           ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│  EntityExtractStep                                                           │
│  规则：正则 + 关键词表  提取（企业/电话/微信/行业/地域/关键词/预算）           │
│  输出：每条 RawRecord → EnrichedRecord{ raw_record, entities, text_norm }   │
│  解析失败 → AnomalyRecord(type="extract_fail")                               │
└──────────────────────────┬──────────────────────────────────────────────────┘
                           │
                           ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│  ComplianceStep  (复用 T06)                                                   │
│  调用：pii_mask.auto_mask(text)  替换 author/title/content 中的 PII          │
│  调用：sensitive_filter.filter_text(content) → 标记 risk/hits               │
│  调用：compliance_checker.check_for_storage(enriched) → compliance_report   │
│  调用：privacy_stripper.strip(payload) → 原始 payload 中隐私字段掩码         │
│  risk == "high"  或  hits >= HIT_THRESHOLD → AnomalyRecord("high_violation")│
└──────────────────────────┬──────────────────────────────────────────────────┘
                           │  非 high_violation
                           ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│  EngineStep  (复用 T07)                                                        │
│  输入：list[dict] —— 将 EnrichedRecord 转成 process_batch 所需 dict          │
│  调用：opportunity_pipeline.process_batch(clues) → PipelineResult           │
│  输出：items=list[ScoredOpportunity]                                         │
└──────────────────────────┬──────────────────────────────────────────────────┘
                           │
                           ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│  NormalizeStep  (对齐 OpenClaw 智能体输入规范)                                 │
│  ScoredOpportunity → StructuredOpportunity                                   │
│  - 字段重命名、类型规范化                                                    │
│  - 补充 meta：pipeline_version, tenant_id, source_ids, pipeline_trace_ids   │
│  输出：list[StructuredOpportunity]                                           │
└──────────────────────────┬──────────────────────────────────────────────────┘
                           │
                           ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│  StorageStep                                                                 │
│  - 批量 upsert 到 structured_opportunity                                     │
│  - 批量 upsert 到 opportunity_anomaly_pool （解析失败 / 高违规 / 打分失败）   │
│  主键：tenant_id + opportunity_id，保证幂等                                   │
└──────────────────────────┬──────────────────────────────────────────────────┘
                           │
                           ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│  PipelineRunResult / 告警                                                     │
│  total/passed/failed/blocked/anomalies + 运行时间，写入 Redis 并返回          │
│  当异常率 ≥ ANOMALY_ALERT_RATIO  或  blocked ≥ BLOCKED_ALERT_COUNT            │
│  → alert_service.service_exception_sync(...)                                  │
└─────────────────────────────────────────────────────────────────────────────┘
```

---

## 4. 实体抽取字段规则

| 字段 | 规则来源 | 示例 | 输出类型 |
|---|---|---|---|
| `company_names` | 正则 + `COMPANY_KEYWORDS`（"公司/有限公司/工作室/集团/科技…"） | `["广州 XXX 科技有限公司"]` | `list[str]` |
| `phone_numbers` | 中国手机号 11 位（1[3-9]\d{9}）、座机带区号 | `["13800138000", "020-8888888"]` | `list[str]` |
| `wechat_ids` | "微信/wx/vx:xxx" 或 6-20 位字母数字下划线的典型微信号 | `["wxid_a1b2c3"]` | `list[str]` |
| `industry_tags` | `INDUSTRY_KEYWORDS` 环境变量，逗号分隔词典匹配 | `["制造业", "IT服务"]` | `list[str]` |
| `region` | 中国省市表（`REGION_KEYWORDS`），取出现最多的地名 | `"广东省广州市"` | `str` |
| `keywords` | 原文切词 + `NEED_KEYWORDS` 交集，Top-K | `["采购", "代理", "合作"]` | `list[str]` |
| `budget` | "预算 X 万元"、"投资 X"、"预算：X~Y" 等常见金额正则 | `{"value": 50000, "unit": "CNY", "range": [30000, 80000]}` | `dict` |
| `estimated_text_length` | 原文字符长度 | 287 | `int` |

注意：所有关键词库、Top-K、正则阈值都从 `.env` 读取。

---

## 5. 标准化结构化输出 JSON（`StructuredOpportunity`）

```jsonc
{
  "opportunity_id": "opp_d12a6b3c_20260703t104400",   // hash(tenant_id + source_id + version)
  "tenant_id": "acme_01",
  "title": "关于 XXX 采购需求征询合作",
  "content_snippet": "本公司拟采购服务器集群 3~5 台…",   // 已脱敏
  "entities": {
    "company_names": ["广州 XXX 科技有限公司"],
    "phone_numbers": ["138***"],                       // 已脱敏
    "wechat_ids": ["wxid_***"],                         // 已脱敏
    "industry_tags": ["IT服务", "采购"],
    "region": "广东省广州市",
    "keywords": ["服务器", "采购", "合作"],
    "budget": {"value": 50000, "unit": "CNY", "range": [30000, 80000]}
  },
  "source": {
    "spider_name": "bid_notice",
    "source_id": "bid_22881",
    "source_url": "https://example.com/bid/22881",
    "captured_at": "2026-07-02T09:14:00Z",
    "raw_record_id": 881
  },
  "compliance": {
    "risk_level": "low",
    "sensitive_hits": 0,
    "blocked": false,
    "report_hash": "sha256:..."
  },
  "score": {
    "total": 82,
    "grade": "high",
    "dimension_scores": {"intent": 80, "quality": 85, "value": 79},
    "blacklisted": false,
    "is_duplicate_of": null                   // 或指向另一个 opportunity_id
  },
  "pipeline": {
    "version": "T10-v1.0",
    "processed_at": "2026-07-03T10:44:00Z",
    "trace_steps": ["load", "filter", "extract", "compliance", "engine", "normalize"]
  }
}
```

### 异常池 `AnomalyRecord`

```jsonc
{
  "anomaly_id": "anom_xxx",
  "tenant_id": "acme_01",
  "source_record_id": 881,
  "type": "high_violation",           // "extract_fail" | "high_violation" | "engine_fail" | "dirty"
  "severity": "warn",                 // "info" | "warn" | "error"
  "reason": "命中敏感词 4 次：[A、B、C、D]，risk=high",
  "raw_snippet": "<前 200 字符，已脱敏>",
  "pipeline_version": "T10-v1.0",
  "created_at": "2026-07-03T10:44:00Z",
  "needs_review": true,               // 供后台人工复核
  "reviewed_at": null,
  "reviewed_by": null,
  "review_note": null
}
```

---

## 6. 配置项（DataCleanSettings）

```
# ====== T10 数据清洗 ======
CLEAN_BATCH_SIZE=200                       # 单次加载量
CLEAN_MIN_TEXT_LEN=30                      # 低于该字符数视为空内容
CLEAN_COMPANY_ENABLED=true
CLEAN_PHONE_ENABLED=true
CLEAN_WECHAT_ENABLED=true
CLEAN_INDUSTRY_KEYWORDS=IT,制造业,采购,批发,零售,教育,医疗,建筑,金融,物流
CLEAN_REGION_KEYWORDS=北京,上海,广州,深圳,杭州,南京,武汉,成都,重庆,西安
CLEAN_NEED_KEYWORDS=采购,合作,代理,招聘,外包,加盟,招商,寻求,需求,寻找,招标,投标
CLEAN_KEYWORDS_TOPK=8
CLEAN_BUDGET_ENABLED=true
CLEAN_HIGH_VIOLATION_RISK=high            # 触发分流的最小 risk 等级
CLEAN_HIGH_VIOLATION_HITS=3               # 或敏感词命中数 >= 此值
CLEAN_AD_JUNK_PATTERNS=                    # 广告灌水模式（正则，逗号分隔）
CLEAN_BLACKLIST_DOMAINS=                  # 黑名单源域
CLEAN_PIPELINE_VERSION=T10-v1.0
CLEAN_ANOMALY_ALERT_RATIO=0.05            # 异常率 >=5% 告警
CLEAN_BLOCKED_ALERT_COUNT=10              # 单次 blocked 条数 >= 10 告警
CLEAN_REDIS_STATUS_PREFIX=openclaw:clean:task:
CLEAN_REDIS_STATUS_TTL=86400
```

---

## 7. 对外任务入口

```python
# business/data_clean/__init__.py  导出
from business.data_clean.registry import run_cleaning, list_runs, get_run_status

# 1) 异步队列模式 —— 手动调用（由 OpenClaw 调度器/消费者进程触发）
result = run_cleaning({
    "tenant_id": "acme_01",
    "batch_size": 200,
    "cursor": None,           # None = 从最老未处理的一批
    "spider_names": ["bid_notice", "zhihu_question"],
    "since": "2026-07-01",
})
# 返回 CleanRun{task_id, processed, passed, anomalies, blocked, next_cursor}

# 2) 定时批量模式 —— 由 settings 中 TASK_SCHEDULE_CRON 驱动（外部进程）
#    重复调用 run_cleaning(cursor=None, batch_size=CRON_BATCH) 直到无更多数据
```

---

## 8. 分步开发流程

```
Step 1 · configs/settings.py
  - 新增 DataCleanSettings（§6 所有字段的 env 读入）
  - 在 AppSettings 注册：cleaning: DataCleanSettings

Step 2 · business/data_clean/models.py
  - CleanTaskParams（pydantic：tenant_id、batch_size、cursor、spider_names、since）
  - CleanRunResult（pydantic：task_id, processed, passed, anomalies, blocked, next_cursor, started_at, finished_at）
  - StructuredOpportunity（pydantic：§5 JSON 字段）
  - AnomalyRecord（pydantic：§5 JSON 字段）

Step 3 · business/data_clean/loader.py
  - load_pending_records(params) → list[RawRecord]
  - RawRecord 简单 dataclass：raw_payload, raw_text, source_url, source_id, id, spider_name, captured_at
  - 支持 cursor 分页（按 captured_at 排序）

Step 4 · business/data_clean/filters.py
  - DirtyFilter：按空内容/广告灌水/失效链接/黑名单源域过滤
  - 可插拔函数：apply_filters(records) → (passed, anomalies)
  - 注：失效链接检测可关闭（通过配置，避免网络请求影响单测）

Step 5 · business/data_clean/extractor.py
  - EntityExtractor：关键词库读 settings.cleaning.CLEAN_*_KEYWORDS
  - 正则提取 company/phone/wechat/budget/region/industry/keywords
  - 每条记录 → EnrichedRecord（pydantic）
  - 抽取失败（无实体、且 text 太短）记录为 extract_fail 异常

Step 6 · business/data_clean/compliance_step.py
  - pii_mask.auto_mask 覆盖 title/content/author
  - sensitive_filter.filter_text 计算命中数 + risk
  - compliance_checker.check_for_storage 生成合规报告
  - privacy_stripper.strip 掩码原始 payload 中的隐私字段
  - 命中 high_violation 条件 → AnomalyRecord + 不入结构化表

Step 7 · business/data_clean/engine_step.py
  - 将 EnrichedRecord 列表转换成 T07 OpportunityPipeline 所需的 dict 列表
  - 调用 opportunity_pipeline.process_batch(clues) → PipelineResult
  - 对 scoring_engine 抛异常的行转为 engine_fail 异常

Step 8 · business/data_clean/normalizer.py
  - ScoredOpportunity + EnrichedRecord 的合规结果 → StructuredOpportunity
  - opportunity_id = sha1(tenant_id + source_id + CLEAN_PIPELINE_VERSION)[:12]
  - 注入 pipeline 元数据

Step 9 · business/data_clean/storage.py
  - upsert_structured(rows) —— 按 tenant_id + opportunity_id 唯一键 upsert
  - upsert_anomalies(rows) —— 写入机会异常池，唯一键 tenant_id + anomaly_id
  - 写入前把 pydantic 转为 dict（按字段名映射）

Step 10 · business/data_clean/pipeline.py
  - CleaningPipeline.run(params: CleanTaskParams) -> CleanRunResult
  - 串联：Step3→Step4→Step5→Step6→Step7→Step8→Step9
  - Redis 状态写入（key = CLEAN_REDIS_STATUS_PREFIX + task_id）
  - 告警：满足条件调用 infra.alerting.alert_service

Step 11 · business/data_clean/registry.py + __init__.py
  - run_cleaning(params: dict | CleanTaskParams) -> CleanRunResult
  - list_runs() -> list[str]（仅列出内存中最新 N 个，Redis 可选）
  - 导出 StructuredOpportunity, AnomalyRecord, CleanRunResult 等供外部使用

Step 12 · tests/test_t10_cleaning.py
  - Monkey-patch：database（SQLite 内存），Redis（dict），compliance 工具（真实调用，无需 mock）
  - 用例：
      · 空内容记录被过滤
      · 含 "加微信/广告" 文本被分流到 high_violation
      · 实体抽取能识别 phone/company/budget
      · 合规校验保留合规报告
      · EngineStep 调用 opportunity_pipeline.process_batch 并生成 scored 项
      · Normalizer 生成 opportunity_id，字段对齐 OpenClaw 规范
      · Storage 写入两张表且重复 upsert 不产生新行
      · 告警阈值触发/不触发两条分支
  - 最后运行 pytest tests/ --tb=short，T01~T10 全绿

Step 13 · 最终提交 feat(T10)
  - 只提交 business/data_clean 新增文件 + configs/settings.py 扩展 + tests/test_t10_cleaning.py
```

---

## 9. 风险 / 依赖 / 注意事项

| 风险 | 应对 |
|---|---|
| `opportunity_pipeline.process_batch` 的输入字段与 EnrichedRecord 字段不一致 | 在 `engine_step.py` 中显式写出字段映射：`clue = {"id": r.source_id, "title": r.title, "content": r.content, "source": r.spider_name, ...}`，单测严格验证 |
| 数据库 schema 中没有 `structured_opportunity` 表 | `storage.py` 通过 `database.bulk_insert(MODEL_NAME, rows)` 动态写入，表不存在时由 SQLAlchemy create_all（在 `infra/db_base.py` 已存在 `create_tables_if_needed`）；如果没有专门的 ORM 类，则新增一个简单 ORM 定义放在 `business/data_clean/_orm.py`（只在 T10 内使用） |
| 关键词库过大影响性能 | 先切原文成 token，用 set 交集，`CLEAN_KEYWORDS_TOPK` 控制上限；正则预编译为模块级常量 |
| 大数据量（10k+）单次运行太久 | 通过 `cursor + batch_size` 分页，`run_cleaning()` 可以在一个 while 循环中多次调用；外部定时任务每次只处理一批 |
| 幂等性不足 | `opportunity_id` 与 `source_id + tenant_id + version` 一一对应，upsert 保证重跑不重复 |
| 单测需要真实数据库 | 使用 SQLite `:memory:` + monkey-patch `database.bulk_insert/upsert`（与 T09 同样的 mock 策略） |
| `opportunity_pipeline` 单例在多进程环境的问题 | T10 只在单进程/多线程模式下调用；T07 内部已做线程锁 |
