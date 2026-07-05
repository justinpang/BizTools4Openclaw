# T07 任务计划：商机去重、线索合并、打分、分级算法引擎

> 定位：`core/data_core/` —— 纯算法层，不做业务入库/消息推送。
> 依赖：T02 日志告警、T03 Redis、T04 数据库模型（字段定义对齐）、T06 合规脱敏工具。

---

## 一、Repo 调研结论

### 1.1 已有数据模型（T04 `infra/db_models.py`）

| 模型 | 关键字段 | T07 用途 |
|------|---------|---------|
| `BusinessOpportunity` | `company_name`, `industry`, `contact_phone`, `contact_wechat`, `requirement_text`, `source_raw_id`, `confidence_score`, `priority`, `is_archived` | 去重、合并、打分的目标结构 |
| `SpiderRawData` | `source_url`, `source_id`, `spider_name`, `captured_at`, `raw_data` | 多来源线索聚合的源数据 |
| `SalesTask` | `opportunity_id`, `priority` | 可作为分级结果的消费方 |
| `SystemLog` | `log_type`, `detail` | 记录去重/合并/拉黑操作审计日志 |

### 1.2 目录与文件检查

- `core/data_core/` 目录已存在，需新增模块文件
- `core/compliance/` 已提供 `pii_mask`、`sensitive_filter`、`privacy_stripper`、`compliance_checker` 等可复用工具
- `core/spider_core/` 已提供 SDK 输出原始结构

### 1.3 约束确认

- 禁止新增目录、删除/重命名现有目录 → 仅在 `core/data_core/` 下新增代码文件
- 禁止硬编码 → 所有权重、阈值、文件路径从 `.env` 读取
- 禁止修改 README、DEVELOP_RULES、docs/TASK_LIST
- 所有输出需先经 T06 脱敏 → 不输出明文隐私

---

## 二、新增文件清单（5 + 1）

| # | 文件 | 核心职责 |
|---|------|---------|
| 1 | `core/data_core/dedupe_engine.py` | 多维度去重引擎（手机号/微信/用户ID/文本相似度）、Union-Find 簇合并 |
| 2 | `core/data_core/merge_engine.py` | 跨平台线索合并：同一客户多平台记录 → 单条主商机；字段合并策略（保留最新/最长/最多信息） |
| 3 | `core/data_core/scoring_engine.py` | 多维度打分模型：时效性、行业匹配度、需求强度、渠道权重、企业资质 → 0-100 综合分 |
| 4 | `core/data_core/blacklist_filter.py` | 黑名单加载、匹配、过滤；支持企业名/手机号/微信/域名多维度 |
| 5 | `core/data_core/pipeline.py` | 统一管线入口：`blacklist_filter → dedupe → merge → score → grade → output`；日志与告警联动 |
| 6 | `tests/test_t07_infra.py` | T07 单元测试：去重/合并/打分/分级/黑名单 各场景 |

**修改文件（1 处，非新增目录）**：`core/data_core/__init__.py`（填充导出符号）

---

## 三、去重匹配规则与文本相似度计算方案

### 3.1 去重维度（4 重匹配）

| 维度 | 匹配方式 | 阈值（.env 可配） | 说明 |
|------|---------|-----------------|------|
| **手机号精确匹配** | 字符串标准化后比较 | 完全相等（忽略非数字字符、空格、+86） | 最强信号；T04 SensitiveString 列已加密；去重时读取密文解密再比较，输出时重新脱敏 |
| **微信号精确匹配** | 字符串标准化后比较（大小写归一、去空格、去"-"） | 完全相等 | 次强信号；微信号可能包含前缀如 "wx_", "WeChat:" 需剥离 |
| **用户ID匹配** | `(platform, user_id)` 二元组完全匹配 | 完全相等 | 同平台用户；不同平台 user_id 不可直接比较 |
| **需求文本相似度** | 词汇 Jaccard + 2-gram 组合 | `DEDUPE_TEXT_THRESHOLD`（默认 0.70） | 处理短需求描述的重复或改写 |

### 3.2 文本相似度算法

采用 **轻量级词汇 Jaccard + 2-gram 组合**，避免依赖 ML 模型或大型词向量：

```
预处理：
  · 转小写
  · 剥离 HTML / URL / email / 手机号 / 微信号（调用 T06 pii_mask.detect_pii 识别并mask）
  · 分词：中文按字切 + 英文/数字按非字母数字边界切
  · 停用词过滤（常见中文停用词 ~ 50 条，可通过 .env BLACKLIST_STOPWORDS_FILE 扩展）

计算：
  · words(A), words(B) 分别为 A、B 的词汇集合
  · bigrams(A), bigrams(B) 为相邻二元组集合
  · J_word = |A ∩ B| / |A ∪ B|
  · J_bigram = |bigrams(A) ∩ bigrams(B)| / |bigrams(A) ∪ bigrams(B)|
  · final_sim = α * J_word + (1 - α) * J_bigram，默认 α = 0.5（DEDUPE_SIM_ALPHA）

判定：final_sim ≥ threshold → 判定为重复
```

### 3.3 Union-Find 簇合并

1. 将所有线索视为节点
2. 对 O(n²) 对进行四重维度匹配（实际通过哈希分桶优化：手机号 hash 分桶、微信 hash 分桶、user_id 分桶、文本 simhash 分桶）
3. 任意维度匹配 → Union-Find 合并
4. 最终返回若干簇 `{cluster_id: [clue_id, clue_id, ...]}`

### 3.4 哈希分桶优化（避免 O(n²)）

| 维度 | 哈希分桶 key |
|------|------------|
| 手机号 | `normalize(phone)[:8]` 或整体 hash |
| 微信 | `normalize(wechat)` |
| 用户 ID | `(platform, user_id)` |
| 文本 | **SimHash 64-bit** 的高 16-bit（近似签名） |

同一分桶内的线索才做精细比较，复杂度降至近似线性。

---

## 四、跨平台线索合并策略

### 4.1 簇内字段合并规则

对同一簇（同一客户）内多条线索，按如下规则合并为一条主商机：

| 字段 | 合并策略 |
|------|---------|
| **company_name** | 取最长（通常更规范）、或出现最频的名称；若唯一则直接保留 |
| **contact_phone** | 合并去重，保留所有不同手机号（最多 N 个，`MERGE_MAX_PHONES` 默认 3） |
| **contact_wechat** | 合并去重，同理 |
| **requirement_text** | 拼接各条需求文本（去重短句），以分隔符 ` | ` 连接 |
| **industry** | 多数投票；取出现频次最高的行业标签 |
| **source_raw_ids** | 保留所有来源的 raw_id 列表，便于追溯 |
| **capture_time** | 取最早（首条采集时间） |
| **latest_activity** | 取最近一条的时间 / 最近更新时间 |
| **platforms** | 去重平台名称列表 |

### 4.2 主线索选举

合并后，选举一条作为 **主线索**（master），其余标记为 **冗余**（duplicate）：
- 若有企业名称，优先保留含完整企业名称的
- 否则优先保留含联系方式数量最多的
- 否则保留采集时间最近的一条

---

## 五、商机打分权重明细

### 5.1 维度定义（总分 0-100）

| 维度 | 权重 | 计算方式 |
|------|------|---------|
| **需求时效性**（`SCORE_WEIGHT_TIMELINESS`） | 0.20 | `exp(-λ * days_since_capture)`，λ = `SCORE_TIMELINESS_LAMBDA`（默认 0.05）；越早分值越低 |
| **行业匹配度**（`SCORE_WEIGHT_INDUSTRY`） | 0.15 | `industry` 命中配置的高价值行业列表（`SCORE_HIGH_INDUSTRIES_JSON`）→ 1.0；普通行业 → 0.5；未标注 → 0.3 |
| **需求强度**（`SCORE_WEIGHT_INTENSITY`） | 0.25 | 基于 requirement_text：关键词匹配数量（`SCORE_INTENSITY_KEYWORDS_JSON` 配置的意向强/中/弱词）；长度分（≥ 50 字 +50，≥20 字 +20，<20 字 +5）；最终归一化 0-1 |
| **渠道权重**（`SCORE_WEIGHT_CHANNEL`） | 0.15 | 不同来源平台（B2B、社交、问答）权重不同；`SCORE_CHANNEL_WEIGHTS_JSON` 配置，默认 {b2b: 0.9, social: 0.7, forum: 0.6, other: 0.4} |
| **企业资质**（`SCORE_WEIGHT_QUALIFICATION`） | 0.15 | company_name 长度 + 是否含 "有限公司/集团/公司" 等标准后缀（+0.5）；是否在高资质列表（`SCORE_HIGH_QUALITY_JSON`，+1.0） |
| **信息完整性**（`SCORE_WEIGHT_COMPLETENESS`） | 0.10 | 已填充字段比例（company_name + phone + wechat + industry + requirement）：5/5 → 1.0，4/5 → 0.7，3/5 → 0.4，≤2 → 0.2 |

**总分公式**：
```
score = Σ(weight_i * score_i)
```

### 5.2 分级判定标准

| 级别 | 分数区间 | 标签 | 建议动作 |
|------|---------|------|---------|
| **高意向** | ≥ 70 | `HIGH_INTENT` | 优先分配销售、即时触达 |
| **普通** | 40-69 | `NORMAL` | 正常跟进 |
| **低意向** | 20-39 | `LOW_INTENT` | 观察期、暂不主动 |
| **垃圾线索** | < 20 或 黑名单命中 | `JUNK` | 过滤丢弃、记录原因 |

阈值可通过 `.env` 覆盖：
- `GRADE_HIGH_THRESHOLD=70`
- `GRADE_NORMAL_THRESHOLD=40`
- `GRADE_LOW_THRESHOLD=20`

---

## 六、黑名单加载与匹配过滤逻辑

### 6.1 文件格式（`BLACKLIST_FILE`）

支持 JSON 数组或纯文本（每行一条）：

```json
[
  {"type": "company",  "value": "某骗子公司有限公司", "reason": "known_fraud"},
  {"type": "phone",    "value": "13800000000",       "reason": "complaint"},
  {"type": "wechat",   "value": "scammer_wx",        "reason": "spam"},
  {"type": "domain",   "value": "example-scam.com",  "reason": "competitor"},
  {"type": "keyword",  "value": "代写论文",          "reason": "policy_violation"}
]
```

纯文本格式（类型可省略，默认 keyword）：
```
# 企业黑名单
某骗子公司有限公司
# 手机号
13800000000
# 微信号（带前缀 wechat:）
wechat:scammer_wx
# 关键词（默认类型）
代写论文
```

### 6.2 匹配规则

| 类型 | 匹配方式 |
|------|---------|
| `company` | 企业名称规范化（去标点、统一中文括号、去"有限公司/公司"后缀后包含比较） |
| `phone` | 手机号标准化后完全相等 |
| `wechat` | 微信号标准化后完全相等 |
| `domain` | URL host 相等或子域名包含 |
| `email` | email 完全相等或域名匹配 |
| `keyword` | 关键词在需求文本/公司名中出现（大小写不敏感） |
| `user_id` | `(platform, user_id)` 二元组匹配 |

### 6.3 处理动作

1. **完全匹配** → 整行标记为 `JUNK`，`blocked=True`，写入 `block_reason`
2. **关键词部分命中** → 降低行业匹配度/需求强度得分
3. **批量垃圾** → 触发告警（同一批 ≥ `BLACKLIST_ALERT_BATCH_SIZE` 条黑名单命中时告警）

---

## 七、管线与输出结构

### 7.1 处理流水线

```
线索输入（list[dict]）
    │
    ├─→ 合规脱敏（调用 T06 pii_mask.auto_mask / compliance_checker）
    │
    ├─→ 黑名单过滤（blacklist_filter.filter_batch）
    │
    ├─→ 多维度去重（dedupe_engine.deduplicate）
    │
    ├─→ 跨平台线索合并（merge_engine.merge_clusters）
    │
    ├─→ 多维度打分（scoring_engine.score_batch）
    │
    ├─→ 分级（scoring_engine.grade_batch）
    │
    └─→ 统一输出（ScoredOpportunity 列表 + 日志 + 告警）
```

### 7.2 标准化输出结构（纯 Python dict/dataclass）

```python
@dataclass
class ScoredOpportunity:
    clue_id: str                      # 内部唯一 ID（稳定可追溯）
    master_source: str                # 主来源平台名
    merged_sources: list[str]         # 所有合并来源
    company_name: str | None          # 已脱敏（如含手机号则mask）
    contact_phones: list[str]         # 脱敏手机号列表（不保留明文）
    contact_wechats: list[str]        # 脱敏微信号列表
    requirement_text: str             # 脱敏后需求描述
    industry: str | None
    platforms: list[str]
    score: float                      # 0-100
    grade: str                        # HIGH_INTENT / NORMAL / LOW_INTENT / JUNK
    score_breakdown: dict             # 各维度分项分数（用于可解释性）
    is_blocked: bool
    block_reason: str | None
    first_capture_at: str | None
    latest_activity_at: str | None
    duplicate_of: str | None          # 非主线索时，指向 master clue_id
    raw_ids: list[int]                # 可追溯的 SpiderRawData.id

@dataclass
class PipelineResult:
    total_input: int
    blocked_by_blacklist: int
    duplicates_removed: int
    final_opportunities: int
    grade_distribution: dict          # {"HIGH_INTENT": N, "NORMAL": N, ...}
    score_histogram: list[tuple]      # [(0-19, N), (20-39, N), ...]
    items: list[ScoredOpportunity]
    logs: list[str]
    alerts: list[str]
```

### 7.3 日志与告警

| 级别 | 触发条件 |
|------|---------|
| INFO | 每次批次处理摘要（total/blocked/duplicates/各等级数量） |
| WARNING | 单条线索命中关键词黑名单（非完全匹配类型） |
| ERROR | 单次处理中 ≥ `BLACKLIST_ALERT_BATCH_SIZE`（默认 10）条被黑名单完全拦截 → 触发 alert_service 告警 |
| DEBUG | 每条具体的去重/合并/打分/分级细节 |

---

## 八、.env 配置项

| 变量 | 默认值 | 说明 |
|------|-------|------|
| `DEDUPE_TEXT_THRESHOLD` | `0.70` | 文本相似度阈值 |
| `DEDUPE_SIM_ALPHA` | `0.5` | 词汇/2-gram 的加权系数 |
| `DEDUPE_PHONE_ENABLE` | `true` | 是否启用手机号维度去重 |
| `DEDUPE_WECHAT_ENABLE` | `true` | 是否启用微信维度 |
| `DEDUPE_USERID_ENABLE` | `true` | 是否启用用户ID维度 |
| `DEDUPE_TEXT_ENABLE` | `true` | 是否启用文本相似度 |
| `MERGE_MAX_PHONES` | `3` | 合并后的最大手机号数量 |
| `MERGE_MAX_WECHATS` | `3` | 合并后的最大微信号数量 |
| `SCORE_WEIGHT_TIMELINESS` | `0.20` |
| `SCORE_WEIGHT_INDUSTRY` | `0.15` |
| `SCORE_WEIGHT_INTENSITY` | `0.25` |
| `SCORE_WEIGHT_CHANNEL` | `0.15` |
| `SCORE_WEIGHT_QUALIFICATION` | `0.15` |
| `SCORE_WEIGHT_COMPLETENESS` | `0.10` |
| `SCORE_TIMELINESS_LAMBDA` | `0.05` | 时效性衰减系数 |
| `SCORE_HIGH_INDUSTRIES_JSON` | `[]` | 高价值行业列表（JSON 数组） |
| `SCORE_INTENSITY_KEYWORDS_JSON` | `{"strong": [], "medium": [], "weak": []}` | 需求强度关键词 |
| `SCORE_CHANNEL_WEIGHTS_JSON` | `{"b2b": 0.9, "social": 0.7, "forum": 0.6, "other": 0.4}` | 渠道权重 |
| `SCORE_HIGH_QUALITY_JSON` | `[]` | 高资质企业关键字/公司名列表 |
| `GRADE_HIGH_THRESHOLD` | `70` |
| `GRADE_NORMAL_THRESHOLD` | `40` |
| `GRADE_LOW_THRESHOLD` | `20` |
| `BLACKLIST_FILE` | `""` | 黑名单文件路径（可选） |
| `BLACKLIST_STOPWORDS_FILE` | `""` | 停用词文件（可选） |
| `BLACKLIST_ALERT_BATCH_SIZE` | `10` | 单批次黑名单命中阈值（触发告警） |
| `PIPELINE_ENABLE_COMPLIANCE_CHECK` | `true` | 是否调用 T06 compliance_checker |

---

## 九、分步执行开发流程

### Step 0（准备）
- 目标：验证 T04/T06 基础可用
- 操作：`python -m pytest tests/test_t04_infra.py tests/test_t06_infra.py -q` 全绿
- 备注：不修改已有代码

### Step 1 — `core/data_core/blacklist_filter.py`
- 实现 `BlacklistFilter` 类：`load_file()`、`match()`、`filter_batch()`、`add_item()`（运行时补充）
- 支持 JSON + TXT 两种文件格式
- 实现 6 种类型匹配（company/phone/wechat/domain/email/user_id）
- 新增测试 4-5 条

### Step 2 — `core/data_core/dedupe_engine.py`
- 实现 `DedupeEngine` 类：
  - `_normalize_phone/wechat/user_id`：字段标准化
  - `_simhash(text)`：64-bit simhash（用于分桶 + 近距离比较）
  - `_text_similarity(a, b)`：Jaccard 词汇 + 2-gram 组合
  - `deduplicate(clues)`：返回 `{cluster_id: [clue_ids]}` + 每对的匹配维度
- 新增测试 5-6 条（手机号/微信/用户ID/文本/混合场景）

### Step 3 — `core/data_core/merge_engine.py`
- 实现 `MergeEngine` 类：
  - `merge_clusters(clues, clusters)`：将若干簇合并为主 + 冗余列表
  - 字段合并策略（保留最长、投票、列表去重）
  - 主线索选举逻辑
- 新增测试 3-4 条

### Step 4 — `core/data_core/scoring_engine.py`
- 实现 `ScoringEngine` 类：
  - 6 维度单项打分函数（`_score_timeliness/_industry/_intensity/_channel/_qualification/_completeness`）
  - `score_one(clue)` → 返回 (score, breakdown)
  - `score_batch(clues)`
  - `grade_one(score)` → HIGH_INTENT/NORMAL/LOW_INTENT/JUNK
  - `grade_batch(items)`
- 新增测试 6-8 条（各维度边界 + 总分归一化 + 分级边界）

### Step 5 — `core/data_core/pipeline.py`
- 实现 `OpportunityPipeline` 类：
  - `__init__`：注入 blacklist_filter / dedupe_engine / merge_engine / scoring_engine / compliance_checker（均可 override，便于测试）
  - `process_batch(clues: list[dict]) -> PipelineResult`
  - 单条线索输入格式约定（dict schema）
  - 日志：`logger.info` 摘要；`logger.debug` 明细
  - 告警：批量命中黑名单 ≥ N 时，调用 `alert_service.service_exception_sync()`
- 新增测试 3-4 条（端到端小批量场景）

### Step 6 — `core/data_core/__init__.py` 导出符号 + `tests/test_t07_infra.py`
- `__init__.py`：导出 `BlacklistFilter`、`DedupeEngine`、`MergeEngine`、`ScoringEngine`、`OpportunityPipeline`、`ScoredOpportunity`、`PipelineResult`
- `test_t07_infra.py`：约 25-30 条测试（黑盒覆盖各模块 + 端到端）

### Step 7 — 全量测试 + 提交
- `python -m pytest tests/ -v`
- 确认 T01-T07 全量通过（预计 110+ 条）
- git commit

---

## 十、输入输出数据约定

### 单条线索输入（dict）

```python
{
    "clue_id": "raw_12345",              # 可选；未提供则生成
    "source_platform": "b2b_site_a",     # 平台名（必填，用于渠道权重）
    "source_id": "abc-789",              # 平台内部ID（可选）
    "user_id": "u_abc",                  # 用户ID（可选）
    "company_name": "某某有限公司",       # 可选
    "contact_phone": "13800138000",       # 可选（多个可用 list）
    "contact_wechat": "wx_abc",           # 可选
    "requirement_text": "需要采购10套空调",  # 必填（打分依赖）
    "industry": "零售",                   # 可选
    "capture_time": "2026-07-01T10:20:30+08:00",  # 必填（时效性依赖）
    "email": "contact@example.com",        # 可选
    "source_url": "https://...",           # 可选
    "raw_id": 123,                        # 可选，对应 SpiderRawData.id
}
```

### 输出：`PipelineResult`（见第七节）

---

## 十一、风险与边界

| 风险 | 后果 | 预案 |
|------|------|------|
| 需求文本过短（<10 字） | Jaccard 不稳定 | 文本相似度降级；对短文本走"完全相等或关键词匹配"逻辑 |
| 手机号加密存储 → 去重前需解密 | 明文暴露风险 | 只在去重函数中做一次性解密比较，结果不缓存明文 |
| 行业匹配度依赖静态列表 | 列表未覆盖则得分偏低 | 配置 `SCORE_HIGH_INDUSTRIES_JSON` 可动态补充；未命中时分数 = 0.3（保底） |
| 线索量巨大（>10w）→ 纯内存去重 O(n²) | 内存/时间不足 | 默认用哈希分桶优化，复杂度 ~O(n)；对超大数据集，调用方可通过 Redis 辅助分桶 |
| 中文企业名称不规范（繁体/简体/标点差异） | 合并漏判 | `_normalize_company_name()`：统一简体、去空格/标点、归一"公司/有限公司/集团"后缀 |
| 不同平台 user_id 重叠 | 误合并为同一客户 | user_id 维度强制要求 `(platform, user_id)` 二元组 |
| 与 T06 脱敏冲突：打分前已脱敏会丢失信息 | 打分不准 | 设计为"先打分后脱敏"：pipeline 在最终 output 阶段调用 T06 pii_mask；input 数据中的隐私字段仅用于打分内部比较，不输出 |

---

## 十二、验收标准

1. `python -m pytest tests/` 全量通过（T01-T07 全部 pass，预计 ≥ 110）
2. 新增模块均位于 `core/data_core/`，不新增目录、不改 README/DEVELOP_RULES
3. 所有权重、阈值、文件路径均从 `.env` 读取；`__init__` 中没有数字字面量（除了 0/1 这样的计算常量）
4. `OpportunityPipeline.process_batch([clue, ...])` 返回结构化 `PipelineResult`，含脱敏输出 + 分数明细 + 分级 + 日志摘要
5. 输出中无明文隐私（phone/wechat/email 已脱敏；可断言 `1[3-9]\d{9}` 不出现于输出文本）
6. 黑名单完全匹配 → `grade == JUNK` 且 `is_blocked == True`
7. 批量黑名单 ≥ N 条 → 触发 `alert_service` 告警（测试中用 mock 验证调用）
8. 代码含中文注释 + 类型注解，对齐 DEVELOP_RULES.md 风格
