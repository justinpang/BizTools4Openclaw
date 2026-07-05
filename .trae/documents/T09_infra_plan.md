# T09 全源多平台商机爬虫业务模块 —— 开发计划

## 1. 现状总览

### 1.1 可复用基础能力（均已验证，业务层直接调用）

| 模块 | 关键 API | 用途 |
|---|---|---|
| `core.spider_core` | `spider_sdk.get(url, params, render, task_id, robot_check=True)` → `CrawlResponse` | 统一 HTTP/Playwright 请求，内置 UA/代理/限流/robots/风控/checkpoint |
| `core.spider_core` | `spider_sdk.batch_get(urls, task_id, render)` | 批量抓取 |
| `core.spider_core` | `SpiderError`, `RateLimitExceededError`, `CrawlerRiskDetectedError` | 异常分类 |
| `core.compliance` | `sensitive_filter.filter(text)` → `FilterResult` | 敏感词检测（T06） |
| `core.compliance` | `pii_mask.mask(text)` → `str` | PII 脱敏（手机/邮箱/身份证/银行卡/车牌/微信号/姓名等） |
| `core.compliance` | `privacy_stripper.strip(payload_dict, fields=...)` → `dict` | 结构化字典字段隐私剔除 |
| `core.compliance` | `compliance_checker.check(text_or_dict)` → `ComplianceReport` | 综合合规扫描（T06） |
| `infra.db_base` | `database.bulk_insert(SpiderRawData, rows, batch_size=200)` | 原始数据批量入库 |
| `infra.db_base` | `database.session()` | 原始数据单条入库 |
| `infra.db_models` | `SpiderRawData` | 原始爬虫数据表（T04） |
| `core.spider_core` | `CheckpointManager.save/load` | 任务进度/断点回写 Redis |

### 1.2 `SpiderRawData` 字段映射（T04 已定义）

```
id              (PK, autoincrement)
tenant_id       (默认 "default")
is_archived     (默认 False)
created_at      (默认 UTC now)
updated_at      (默认 UTC now)
spider_name     String(128)  NOT NULL  —— 爬虫唯一标识（如 "douyin_comment"）
source_url      String(1024) NOT NULL  —— 原始 URL
source_id       String(256)  NULLABLE  —— 平台唯一 ID（去重依赖，UNIQUE(tenant,spider,source_id)）
raw_payload     JSON         NOT NULL  —— 解析后的结构化字段（作者/时间等）
raw_text        Text         NULLABLE  —— 正文文本（可能为空）
fetch_status    SmallInt     0 成功 / 1 失败 / 2 风控 / 3 敏感拦截
fetch_error     String(512)  NULLABLE
captured_at     TIMESTAMP    NOT NULL  —— 抓取时间
source_country  CHAR(2)      NULLABLE
```

注意：unique key `idx_spider_raw_source_id = (tenant_id, spider_name, source_id)` —— 若平台无 ID，则 `source_id` 留空并在 raw_payload 中放哈希替代。

### 1.3 目录现状

```
business/multi_spider/            空（只有 __init__.py）
├── __init__.py                   待更新：导出模块注册器
├── base.py                        新增：BaseSpider 抽象类（统一入口 + 任务进度）
├── registry.py                    新增：爬虫注册表（spider_name → 类，供 scheduler/async_task 启动）
├── models.py                      新增：入参/出参 pydantic 模型
├── pipeline.py                    新增：通用抓取 → 解析 → 合规扫描 → 入库流水线
├── sources/                       新增：渠道目录（各渠道独立文件）
│   ├── generic_web.py             通用网页 / 行业论坛 / 社群帖子评论
│   ├── douyin_xhs.py              抖音 + 小红书作品及评论
│   ├── zhihu_baiduqa.py           知乎 + 百度知道问答
│   ├── local_classifieds.py       58 / 闲鱼 / 本地生活供需
│   ├── bid_and_gov.py             招投标 / 政府采购 / 公共资源
│   ├── enterprise_news.py         企查查 / 天眼查企业新增变更招聘
└── tests/ (不新增；tests/ 下已有 test_t09_multi_spider.py）
```

**约束**：不新增项目目录；所有业务代码在 `business/multi_spider/` 内部。

---

## 2. 新增文件清单（完整路径 + 文件名）

```
business/multi_spider/__init__.py            (更新：空白 → 导出模块注册表 + 入口)
business/multi_spider/base.py                (新增：BaseSpider 抽象基类 + 进度/状态)
business/multi_spider/registry.py            (新增：SpiderRegistry 注册/检索)
business/multi_spider/models.py              (新增：pydantic 入参/出参模型)
business/multi_spider/pipeline.py            (新增：Fetch→Parse→Compliance→Persist 统一流水线)
business/multi_spider/sources/generic_web.py (新增：通用网页/论坛/社群评论)
business/multi_spider/sources/douyin_xhs.py  (新增：抖音+小红书)
business/multi_spider/sources/zhihu_baiduqa.py(新增：知乎+百度知道)
business/multi_spider/sources/local_classifieds.py(新增：58/闲鱼/本地生活)
business/multi_spider/sources/bid_and_gov.py (新增：招投标/政府采购)
business/multi_spider/sources/enterprise_news.py(新增：企查查/天眼查)
tests/test_t09_multi_spider.py               (新增：单元测试，所有渠道覆盖)
```

总计 **10 个业务文件 + 1 个测试文件**。

---

## 3. 爬虫任务入参 / 出参结构体

### 3.1 入参：`SpiderTaskParams`（pydantic）

```python
class SpiderTaskParams(BaseModel):
    spider_name: str                          # 渠道唯一标识，见 §6 渠道清单
    task_id: str = Field(default_factory=lambda: uuid.uuid4().hex)  # 任务唯一 ID
    urls: list[str] | None = None             # 显式 URL 列表（优先级最高）
    keywords: list[str] | None = None         # 关键词（由渠道自行拼 URL）
    max_pages: int = 20                       # 最大翻页数（从 .env 取默认，见 §5）
    max_items_per_url: int = 100              # 单 URL 最多解析条目数
    render_js: bool = False                   # 是否启用 Playwright 渲染
    use_proxy: bool = True                    # 是否走代理池
    tenant_id: str = "default"                # 租户 ID
    country: str = "CN"                       # 源国家（写入 source_country）
    dry_run: bool = False                     # 仅解析不落库
    extra: dict[str, Any] = Field(default_factory=dict)  # 渠道私有参数
```

### 3.2 出参：`SpiderTaskResult`（pydantic）

```python
class SpiderTaskResult(BaseModel):
    task_id: str
    spider_name: str
    status: Literal["ok", "partial", "failed"]
    total_attempted: int = 0
    total_persisted: int = 0
    total_failed: int = 0
    total_blocked_by_compliance: int = 0
    risk_detected: int = 0
    rate_limited: int = 0
    first_error: str | None = None
    started_at: datetime
    finished_at: datetime | None = None
    duration_ms: int | None = None
    source_ids: list[str] = Field(default_factory=list, exclude=True)  # 不序列化
```

### 3.3 单条解析结果：`RawItem`（内部结构）

```python
@dataclass
class RawItem:
    source_id: str                          # 平台唯一 ID（必填；若无则用 hash(url+text)）
    source_url: str                         # 原始 URL
    author: str = ""                        # 作者/发布者（可能为空）
    published_at: str | None = None         # 发布时间字符串（ISO/相对时间）
    title: str = ""                         # 标题
    content: str = ""                       # 正文
    tags: list[str] = field(default_factory=list)
    extra: dict[str, Any] = field(default_factory=dict)  # 渠道自有字段（如平台名、分类）
```

---

## 4. 各平台爬虫解析逻辑 / 字段提取规则

### 4.1 设计原则

- **100% 依赖 `spider_sdk.get()`**，业务模块绝不 `import requests` / 自定义 UA 池 / 自写代理。
- **所有目标 URL / 关键词 / 翻页上限 / 抓取深度从 `.env` 读**（通过 `settings.spider.*`），不硬编码。
- **解析用标准库 `re` + `html.parser`（BeautifulSoup 可选）**，不对 DOM 结构做过于紧密的耦合（使用 `find` 失败自动降级）。
- **每条解析结果在入库存前必须跑**：
  1. `pii_mask.mask(content)` + `pii_mask.mask(title)` + `pii_mask.mask(author)` → 文本脱敏
  2. `sensitive_filter.filter(content)` → 若 `risk_level == "high"` 或命中数 ≥ 3，则 **标记 fetch_status=3 但仍入库**（保留原始内容用于审计，不拦截整任务）
  3. `compliance_checker.check(...)` → 写入 `raw_payload["compliance_report"]`
- **入库走 `database.bulk_insert(SpiderRawData, rows)`**，冲突字段 `(tenant_id,spider_name,source_id)` 触发 UNIQUE → 用 `database.upsert(..., conflict_columns=["tenant_id","spider_name","source_id"])`。

### 4.2 各渠道解析字段映射

| 渠道 | spider_name | 解析字段 | source_id 生成 |
|---|---|---|---|
| 通用网页 / 论坛 | `generic_article` | title=<title/h1>, author=.author, content=<article>, published_at=<time> | `hashlib.md5(url.encode()).hexdigest()` |
| 社群评论 / 帖子 | `generic_comment` | title=post_title, content=comment_text, author=comment_author, published_at | `post_id + ":" + comment_id`（若缺则 hash） |
| 抖音作品 | `douyin_work` | title=<work_title>, author=<author>, content=<description>, published_at | `aweme_id` |
| 抖音评论 | `douyin_comment` | title=引用作品标题, content=评论文本, author=评论者, published_at | `aweme_id + ":" + cid` |
| 小红书笔记 | `xhs_note` | title=笔记标题, author=作者, content=笔记正文, published_at | `note_id` |
| 小红书评论 | `xhs_comment` | title=引用笔记标题, content=评论文本, author=评论者 | `note_id + ":" + comment_id` |
| 知乎问答 | `zhihu_question` | title=问题标题, author=提问者, content=问题描述 | `question_id` |
| 知乎回答 | `zhihu_answer` | title=引用问题, content=回答正文, author=回答者 | `answer_id` |
| 百度知道 | `baidu_qa` | title=问题, content=最佳回答, author=答主 | `qid` |
| 58 同城 | `58_listing` | title=标题, content=描述, author=发布者, published_at | `listing_id` |
| 闲鱼 | `xianyu_item` | title=商品标题, content=描述, author=卖家 | `item_id` |
| 本地生活供需 | `local_need` | title=需求标题, content=描述, author=用户 | `post_id` |
| 招投标公告 | `bid_notice` | title=项目名称, content=公告正文, author=发布机构, published_at | `bid_id` |
| 政府采购 | `gov_procurement` | title=项目名称, content=公告正文, author=采购方 | `proc_id` |
| 公共资源交易 | `public_resource` | title=项目名称, content=公告正文, author=交易中心 | `resource_id` |
| 企查查企业新增 | `qcc_new_company` | title=企业名称, content=经营范围/注册资本, author=法人 | `company_id` |
| 企查查变更 | `qcc_change_event` | title=变更事项, content=变更详情, author=企业名 | `company_id + ":" + change_id` |
| 天眼查招聘 | `tyc_job` | title=职位名, content=职位描述, author=公司名, published_at=发布时间 | `job_id` |

### 4.3 解析容错

- 任一字段提取失败 → 置为空字符串，**不抛异常**，在 `raw_payload["parse_warnings"]` 中记录字段名 + 当前 URL
- 整条无有效内容（title 和 content 都空）→ **跳过**，计入 `total_failed`
- HTTP 失败 / 风控 / 限流 → 计入各自 counter，记录 `fetch_error`，继续下一条

---

## 5. 配置（.env / settings.py）新增项

```bash
# ====== T09 · 多源爬虫 ======
SPIDER_MAX_PAGES_DEFAULT=20            # 单任务默认翻页上限
SPIDER_MAX_ITEMS_PER_URL=100           # 单 URL 最多解析条目
SPIDER_BATCH_INSERT_SIZE=200           # 批量入库 batch_size
SPIDER_DEFAULT_RENDER_JS=false         # 默认不启用 playwright
SPIDER_DEFAULT_USE_PROXY=true          # 默认走代理池
SPIDER_COUNTRY_DEFAULT=CN              # 源国家默认
SPIDER_SENSITIVE_HIGH_THRESHOLD=3      # 敏感词命中数≥此值，标记 content_blocked
SPIDER_COMPLIANCE_ENABLED=true         # 是否启用 T06 合规扫描
SPIDER_PII_MASK_ENABLED=true           # 是否启用 PII 脱敏
SPIDER_SUMMARY_FIELDS_MASK=phone,email,id_card,bank_card,license_plate,wechat,qq,name  # privacy_stripper 处理字段

# 渠道目标 URL / 关键词模板（各渠道独立，允许为空时从 keywords 参数动态生成）
SPIDER_GENERIC_WEB_SEEDS=                  # 通用网页种子，逗号分 "http://a.com,http://b.com"
SPIDER_FORUM_SEEDS=                        # 论坛种子
SPIDER_DOUYIN_SEARCH_TEMPLATE=https://www.douyin.com/search?q={keyword}
SPIDER_XHS_SEARCH_TEMPLATE=
SPIDER_ZHIHU_SEARCH_TEMPLATE=
SPIDER_BAIDU_QA_TEMPLATE=
SPIDER_58_TEMPLATE=
SPIDER_XIANYU_TEMPLATE=
SPIDER_BID_SEARCH_TEMPLATE=
SPIDER_GOV_SEARCH_TEMPLATE=
SPIDER_PUBLIC_RESOURCE_TEMPLATE=
SPIDER_QCC_SEARCH_TEMPLATE=
SPIDER_TYC_SEARCH_TEMPLATE=

# 渠道开关
SPIDER_CHANNEL_GENERIC_ENABLED=true
SPIDER_CHANNEL_DOUYIN_XHS_ENABLED=true
SPIDER_CHANNEL_ZHIHU_BAIDU_ENABLED=true
SPIDER_CHANNEL_LOCAL_ENABLED=true
SPIDER_CHANNEL_BID_GOV_ENABLED=true
SPIDER_CHANNEL_ENTERPRISE_ENABLED=true

# Redis 任务状态 key 前缀（复用 T03）
SPIDER_TASK_STATUS_PREFIX=openclaw:spider:task:
SPIDER_TASK_STATUS_TTL_SECONDS=86400     # 1 天
```

在 `configs/settings.py` 的 `AppSettings` 中新增 `SpiderSettings`（与其他 Settings 同模式）。

---

## 6. 渠道清单与对应 `spider_name` 注册表

```python
# registry.py
SPIDER_REGISTRY: dict[str, type[BaseSpider]] = {
    # ── 通用 ──
    "generic_article":       GenericWebArticleSpider,
    "generic_comment":       GenericCommentSpider,

    # ── 抖音 + 小红书 ──
    "douyin_work":           DouyinWorkSpider,
    "douyin_comment":        DouyinCommentSpider,
    "xhs_note":              XhsNoteSpider,
    "xhs_comment":           XhsCommentSpider,

    # ── 知乎 + 百度知道 ──
    "zhihu_question":        ZhihuQuestionSpider,
    "zhihu_answer":          ZhihuAnswerSpider,
    "baidu_qa":              BaiduQASpider,

    # ── 58 / 闲鱼 / 本地生活 ──
    "58_listing":            Listing58Spider,
    "xianyu_item":           XianyuItemSpider,
    "local_need":            LocalNeedSpider,

    # ── 招投标 / 政府采购 / 公共资源 ──
    "bid_notice":            BidNoticeSpider,
    "gov_procurement":       GovProcurementSpider,
    "public_resource":       PublicResourceSpider,

    # ── 企查查 / 天眼查 ──
    "qcc_new_company":       QccNewCompanySpider,
    "qcc_change_event":      QccChangeEventSpider,
    "tyc_job":               TycJobSpider,
}
```

**启动入口（供 scheduler/async_task 调用）**：

```python
# business/multi_spider/__init__.py
from business.multi_spider.registry import run_spider_by_name, list_spiders
# run_spider_by_name(spider_name: str, params: dict | SpiderTaskParams) -> SpiderTaskResult
# list_spiders() -> list[str]
```

---

## 7. 原始数据入库完整流程（Pipeline）

```
SpiderTaskParams
     │
     ▼
BaseSpider.run()
  ├─ 1) build_url_list(params) → list[str]   # 从 seeds + keywords 拼
  │
  ├─ 2) 对每个 url：
  │      ├─ spider_sdk.get(url, render=params.render_js, task_id=params.task_id,
  │      │                    robot_check=True, risk_check=True)
  │      │         → CrawlResponse{status_code, text, content, risk_level, error, elapsed...}
  │      ├─ 若 resp.ok 为 False → 记录 failed / risk_detected / rate_limited，continue
  │      ├─ parse(resp) → list[RawItem]       # 子类实现
  │      └─ 累计 items
  │
  ├─ 3) 对每个 RawItem：
  │      ├─ raw_payload = {
  │      │    "author":    pii_mask.mask(item.author),
  │      │    "published_at": item.published_at,
  │      │    "tags":      item.tags,
  │      │    "extra":     item.extra,
  │      │    "parse_warnings": [],
  │      │    "compliance_report": compliance_checker.check(combined_text).model_dump(mode="json"),
  │      │  }
  │      ├─ masked_content = pii_mask.mask(item.content) if pii_mask_enabled else item.content
  │      ├─ sensitive_result = sensitive_filter.filter(masked_content or item.title)
  │      ├─ fetch_status = 0
  │      │    if resp.ok 为 False        → fetch_status = 1
  │      │    if resp.risk_level=="high" → fetch_status = 2
  │      │    if sensitive_result.risk_level == "high" or
  │      │       len(sensitive_result.hits) >= settings.spider.SPIDER_SENSITIVE_HIGH_THRESHOLD
  │      │                                → fetch_status = 3
  │      └─ 准备一行 SpiderRawData dict
  │           {
  │             "spider_name":  self.name,
  │             "source_url":   item.source_url,
  │             "source_id":    item.source_id,
  │             "raw_payload":  raw_payload,
  │             "raw_text":     masked_content,
  │             "fetch_status": fetch_status,
  │             "fetch_error":  first_err_msg or None,
  │             "captured_at":  datetime.utcnow(),
  │             "source_country": params.country,
  │             "tenant_id":    params.tenant_id,
  │           }
  │
  ├─ 4) 若 params.dry_run → 跳过持久化
  │    否则：database.bulk_insert(SpiderRawData, rows, batch_size=SPIDER_BATCH_INSERT_SIZE)
  │          捕获 IntegrityError（唯一键冲突） → 对冲突子组走 database.upsert(
  │              conflict_columns=["tenant_id","spider_name","source_id"])
  │
  ├─ 5) 任务状态写入 Redis（复用 T03 Redis 连接，或通过 CheckpointManager）：
  │      key = SPIDER_TASK_STATUS_PREFIX + params.task_id
  │      value = SpiderTaskResult(...).model_dump_json()
  │      TTL = SPIDER_TASK_STATUS_TTL_SECONDS
  │
  ├─ 6) 告警：
  │      · 若 total_failed ≥ 5% 或 risk_detected > 0
  │          → infra.alerting.alert_service.service_exception_sync(
  │              f"[T09][{self.name}] 抓取异常：失败 {total_failed}，风控 {risk_detected}",
  │              extra={"task_id": params.task_id})
  │
  └─ 返回 SpiderTaskResult
```

**并发控制**：默认单任务串行（由 `spider_sdk` 内部的 DomainRateLimiter 控制速率）。如 scheduler 并发多个不同渠道任务，彼此独立通过 `spider_sdk` 的域限流。

---

## 8. 分步执行开发流程

```
Step 1 · 配置扩展（configs/settings.py）
  - 新增 SpiderSettings（纯 .env 读取，不硬编码）
  - 在 AppSettings 中注册：spider: SpiderSettings

Step 2 · models.py：pydantic 入参/出参
  - SpiderTaskParams（带默认值与校验）
  - SpiderTaskResult（含 counter 字段）
  - RawItem dataclass

Step 3 · base.py：BaseSpider 抽象类
  - 抽象方法：name / build_url_list(params) / parse(resp, params) -> list[RawItem]
  - 提供：run(params) -> SpiderTaskResult（实现 §7 流水线）
  - 提供：_persist(items, params) / _write_task_status(result) / _alert_if_needed(result)
  - 提供：_build_source_id(url, extra_fields) -> str（hash fallback）
  - 提供：_mask_text(text) / _safe_get_text(soup_or_text, selector)

Step 4 · pipeline.py（可选拆分）：
  - 实际就是 BaseSpider 的流程 helper（run 里直接调用即可）

Step 5 · registry.py：
  - SPIDER_REGISTRY dict[str, type[BaseSpider]]
  - register(name, cls) / get(name) / list_spiders()
  - run_spider_by_name(spider_name, params) -> SpiderTaskResult

Step 6 · sources/*.py：逐个实现
  (a) generic_web.py  → 通用网页/论坛帖子 + 评论（2 个 spider）
  (b) douyin_xhs.py   → 抖音作品 + 评论；小红书笔记 + 评论（4 个 spider）
  (c) zhihu_baiduqa.py → 知乎问题 + 回答；百度知道（3 个 spider）
  (d) local_classifieds.py → 58 / 闲鱼 / 本地生活（3 个 spider）
  (e) bid_and_gov.py  → 招投标 / 政府采购 / 公共资源（3 个 spider）
  (f) enterprise_news.py → 企查查新增+变更；天眼查招聘（3 个 spider）
  - 每个 spider 子类提供：
      class XxxSpider(BaseSpider):
          name: ClassVar[str] = "xxx"
          def build_url_list(self, params: SpiderTaskParams) -> list[str]: ...
          def parse(self, resp: CrawlResponse, params: SpiderTaskParams) -> list[RawItem]: ...

Step 7 · __init__.py：暴露模块 API
  - from business.multi_spider.registry import run_spider_by_name, list_spiders, SPIDER_REGISTRY
  - from business.multi_spider.models import SpiderTaskParams, SpiderTaskResult
  - from business.multi_spider.base import BaseSpider, RawItem
  - __all__ = [...]

Step 8 · tests/test_t09_multi_spider.py：
  - 构造 1 fake spider 继承 BaseSpider，用 mock 的 spider_sdk（注入单例：
    monkey_patch 到 business/multi_spider.base 引用的 spider_sdk），验证
    · 正常抓取 → 正确入库（SQLite in-memory）
    · HTTP 失败 → counter 更新，不入库
    · 敏感词高风险 → fetch_status=3
    · 重复 source_id → upsert 生效，total_persisted 不重复
    · 所有渠道 spider_class().build_url_list(keywords=[...]) 非空且有效
  - 注入 test-specific database（SQLite in-memory engine）与 test-specific
    spider_sdk（返回预设 CrawlResponse，避免外网依赖）
  - 要求：全部用单测验证，无真实网络请求，无外部 Redis
  - 最后运行 pytest tests/ --tb=short，确保 T01~T09 全绿

Step 9 · 最终提交 feat(T09)
  - commit message 严格按照本 plan 的「核心执行内容」撰写
  - 不修改 README、TASK_LIST、其他业务模块文件
```

---

## 9. 风险 / 依赖 / 注意事项

| 风险 | 应对 |
|---|---|
| 爬虫对 DOM 结构强耦合，平台改版即失效 | 用 `_safe_get_text` 兜底；解析失败不抛异常、记 warning；每个 spider 只依赖 2~3 个候选选择器 |
| 目标平台需要登录 / 反爬较严 | `render_js=True` + UA/代理池走 SDK 内置；无法突破时记录为 fetch_status=2 |
| PII 字段可能位于 payload 深层嵌套 | 用 `privacy_stripper.strip(payload, fields=["phone","email",...])` 递归处理 |
| 大量数据入库 → 连接池压力 | 用 `bulk_insert` + 可调 batch_size（`.env` 读取） |
| 同一任务重复调度 → 重复数据 | `(tenant_id, spider_name, source_id)` UNIQUE，配合 upsert 幂等 |
| 测试无法联网 → 用假 SDK 响应 | 单测全部 monkey-patch `spider_sdk.get` 与 `database` |
| 各渠道开关需要可配置 | `SPIDER_CHANNEL_*_ENABLED` 控制注册表暴露 |
