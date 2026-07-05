# T06 任务计划：开发全局数据合规、脱敏、敏感词过滤核心工具

> 定位：`core/compliance/` —— 全局合规基建。上层业务（爬虫/清洗/触达）统一复用，不写业务逻辑。
> 依赖：T02 日志 & 告警、T04 AES 加密（敏感字段入库加密能力保持不变）

---

## 一、Repo 调研结论

### 1.1 已有文件（可复用 / 需扩展）

| 文件 | 现状 | 计划动作 |
|------|------|---------|
| [`core/compliance/__init__.py`](file:///c:/projects/BizTools4Openclaw/core/compliance/__init__.py) | 空 | 填充导出符号（含 T04 + T06） |
| [`core/compliance/sensitive_crypto.py`](file:///c:/projects/BizTools4Openclaw/core/compliance/sensitive_crypto.py) | 已提供 `AES256Crypto`、`SensitiveString`、`mask_phone/email/wechat` | **不动**，保持零改动；T06 在 *展示脱敏层* 上扩展新字段类型 |
| [`core/compliance/archive_mixin.py`](file:///c:/projects/BizTools4Openclaw/core/compliance/archive_mixin.py) | 已提供 `should_archive_row` / `mark_rows_archived` / `hot_only` | **不动**，作为生命周期工具的已建基础 |

### 1.2 现有约束

- `README.md`、`DEVELOP_RULES.md`、`docs/TASK_LIST.md` —— 禁止修改
- 不新增 / 删除 / 重命名项目目录，仅在 `core/compliance/` 内新增代码
- 所有路径、掩码样式、留存周期从 `.env` 读取，零硬编码
- 脱敏仅做展示隐藏，数据库底层加密仍复用 T04 `AES256Crypto` / `SensitiveString`

---

## 二、新增文件清单（5 + 1）

| # | 文件 | 说明 |
|---|------|------|
| 1 | `core/compliance/pii_mask.py` | 隐私脱敏算法库 —— 手机号 / 微信号 / QQ / 邮箱 / 固话 / 身份证片段 / 昵称 / 企业名称掩码 |
| 2 | `core/compliance/sensitive_filter.py` | 敏感词过滤引擎 —— AC 自动机 + DFA 快速匹配、支持内置词库 + 自定义词库文件、片段标记与高亮 |
| 3 | `core/compliance/privacy_stripper.py` | 隐私字段自动剔除工具 —— 遍历 dict/list/JSON 原始数据，识别并清除无授权隐私字段 |
| 4 | `core/compliance/compliance_checker.py` | 统一合规校验入口 —— `precheck()` 方法 + 结构化报告；适用于爬虫入库、消息发送两大场景 |
| 5 | `core/compliance/data_lifecycle.py` | 数据生命周期工具 —— 批量过期数据标记、隐私信息一键清除、生命周期报表导出 |
| 6 | `tests/test_t06_infra.py` | T06 单元测试（覆盖脱敏、过滤、剔除、预检、生命周期） |

**修改文件（1 处，非新增目录）：** `core/compliance/__init__.py`（填充导出符号）

---

## 三、脱敏算法规则设计

### 3.1 字段类型与掩码规则

| 字段类型 | 示例 | 算法 | 输出 |
|---------|------|------|------|
| **手机号** | `13800138000` | 前 3 位保留，后 4 位保留，中间 4 位用 `*` 掩码 | `138****8000` |
| **固话** | `010-12345678`、`(021)88887777` | 区号 + 前 1~2 位保留，其余掩码 | `010-****5678`、`(021)***87777` |
| **微信号** | `wx_abc123`、`WeChat_Amy` | 首字符 + 中间 `*` + 尾字符；长度 ≤ 2 全部掩码 | `w*******3`、`W*******y` |
| **QQ号** | `1234567`、`12345678901` | 首 2 位 + 中间 `*` + 末 2 位；长度 ≤ 4 全部掩码 | `12***67`、`12*******01` |
| **邮箱** | `user.name@example.com` | 用户名：首字符 + `***` + 末字符（长度 ≤ 2 全部 `*`）；域名原样保留 | `u***e@example.com` |
| **身份证片段** | `110101199003077777` | 前 6 位 + `********` + 后 4 位（18 位标准） | `110101********7777` |
| **URL 中的域名** | `https://customer.abc.com/path` | 顶级域保留，二级域 + 子域掩码；纯 IP 场景保留首段 | `https://***.***.com/path` |
| **用户昵称** | `张伟`、`AliceWang` | 首字符保留，其余 `*`；纯 ASCII 昵称保留首字母 | `张*`、`A*******g` |
| **企业名称** | `阿里巴巴（中国）有限公司` | 首 2 个汉字 + `***` + 末 2 个汉字；全英文同样保留首末片段 | `阿里***限公司` |
| **银行卡号** | `6222 0200 0011 1234` | 前 6 位 + `********` + 后 4 位 | `622202********1234` |

### 3.2 自动识别（`auto_mask()`）

- 输入：字符串 / dict / list / 嵌套结构
- 策略：
  1. **key 名称识别**：若 dict 的 key 匹配 `pii_key_patterns`（如 `phone`, `mobile`, `tel`, `wechat`, `wx`, `qq`, `email`, `mail`, `nickname`, `name`, `id_card`, `company`, `address`, `bank_card` 及其常见变体 + 大小写 + 下划线/连字符），对 value 执行对应脱敏
  2. **正则匹配 value**：对字符串 value 跑多类正则（手机号 `1[3-9]\d{9}`、QQ `\b[1-9]\d{4,11}\b`、邮箱、身份证等），命中即脱敏
  3. **保留结构**：dict/list 深度遍历，保留原结构；字符串返回新字符串
- 输出：与输入同结构的脱敏副本

### 3.3 公共 API 签名

```python
# core/compliance/pii_mask.py
from typing import Any

class PIIMask:
    # 单例：共享 .env 中的掩码字符、正则配置
    def __init__(
        self,
        *,
        mask_char: str = "*",                    # .env: PII_MASK_CHAR
        mask_short_length: int = 8,              # .env: PII_MASK_SHORT_LEN
        custom_keywords: list[str] | None = None, # .env: PII_EXTRA_KEYS_JSON
    )

    # 单个字段脱敏
    def mask_phone(self, value: str) -> str
    def mask_landline(self, value: str) -> str
    def mask_wechat(self, value: str) -> str        # 覆盖 T04 已有，保持一致
    def mask_qq(self, value: str) -> str
    def mask_email(self, value: str) -> str         # 覆盖 T04 已有，保持一致
    def mask_id_card(self, value: str) -> str
    def mask_nickname(self, value: str) -> str
    def mask_company(self, value: str) -> str
    def mask_bank_card(self, value: str) -> str
    def mask_url(self, value: str) -> str

    # 自动识别 + 脱敏
    def auto_mask(self, data: Any, *, deep: bool = True) -> Any

    # 检测是否包含隐私（不修改数据）
    def detect_pii(self, text: str) -> list[dict]
        # 返回: [{'type': 'phone', 'text': '13800138000', 'start': 10, 'end': 21}, ...]

# 模块级实例
pii_mask = PIIMask()
```

---

## 四、敏感词过滤引擎设计

### 4.1 词库来源

| 词库类型 | 路径 / 来源 | 说明 |
|---------|------------|------|
| 内置通用违规词 | `core/compliance/_builtin_badwords.py`（独立文件，纯常量） | 包含广告、违规、涉敏通用词 ≈ 200 条；不含真实隐私样例 |
| 外部词库文件 | `.env` 的 `SENSITIVE_WORDS_FILE` | 一行一个词；`#` 注释；支持 UTF-8 |
| 动态扩展 | 运行时调用 `filter.add_word()` / `filter.add_words()` | 业务侧按需要临时添加 |

### 4.2 匹配算法：Aho-Corasick 自动机（AC 自动机）

- **构建复杂度**：O(Σ len(词))；构建一次后多模式匹配 O(文本长度)
- **优势**：对 200~500 词库 + 长文本（5k~50k 字符）一次性扫描，性能远高于多次 `str.find()`
- **实现细节**：
  - 使用 `dict` + `list` 结构手写 trie；每个节点包含 `next: dict[str, int]`、`fail: int`、`outputs: list[str]`
  - 构造 fail 指针用 BFS；扫描时在 fail 链上合并 outputs
  - **大小写不敏感匹配**，但在结果中保留原文字片段（以支持高亮）
  - **中文**：直接按字符存储，天然支持 Unicode（Python 3 字符串即可）

### 4.3 公共 API 签名

```python
# core/compliance/sensitive_filter.py
from typing import Iterable

# 风险等级
RISK_LOW = "low"
RISK_MEDIUM = "medium"
RISK_HIGH = "high"

@dataclass
class SensitiveHit:
    word: str              # 匹配到的词（在词库中的规范化形式）
    fragment: str          # 在原文中的片段（保留原始大小写）
    start: int             # 原文中起始索引
    end: int               # 原文中结束索引
    category: str          # "advertising" / "violation" / "political" / "custom"
    risk: str              # RISK_LOW/MEDIUM/HIGH

@dataclass
class FilterResult:
    text: str              # 原始文本
    hits: list[SensitiveHit]
    cleaned_text: str      # 已替换敏感词为 `***` 或掩码
    risk: str              # 最高风险等级
    is_blocked: bool       # 是否触发拦截（按阈值或命中高风险）

class SensitiveFilter:
    def __init__(
        self,
        *,
        mask_char: str = "*",                     # .env: SENSITIVE_MASK_CHAR
        mask_length: int = 3,                     # .env: SENSITIVE_MASK_LEN
        block_threshold: str = "medium",          # .env: SENSITIVE_BLOCK_THRESHOLD
        custom_words_file: str | None = None,     # .env: SENSITIVE_WORDS_FILE
        words: Iterable[str] | None = None,       # 运行时注入（测试用）
    )

    # 词库管理
    def add_word(self, word: str, *, category: str = "custom", risk: str = RISK_LOW) -> None
    def add_words(self, items: Iterable[tuple[str, str, str]]) -> None  # (word, category, risk)
    def load_file(self, path: str) -> None

    # 核心检测 / 清洗
    def detect(self, text: str) -> list[SensitiveHit]        # 纯检测，不改数据
    def filter_text(self, text: str) -> FilterResult         # 检测 + 替换 + 生成结果
    def highlight(self, text: str, *, open_tag: str = "<mark>", close_tag: str = "</mark>") -> str
    def is_blocked(self, text: str) -> bool                   # 仅判断是否需要拦截

# 模块级单例
sensitive_filter = SensitiveFilter()
```

### 4.4 内置词库（示意）

- **广告类**（category=`advertising`, risk=`medium`）：
  `加微信`, `加QQ`, `代开发`, `代写论文`, `刷钻`, `流量充值`, `加粉`, `代写`, `兼职日结`, `加v`, `v信`
- **违规类**（category=`violation`, risk=`high`）：
  `博彩`, `澳门`, `线上赌场`, `枪支`, `毒品`, `黄色`, `色情`, `代孕`, `洗钱`, `假币`, `办证`, `黑产`
- **涉敏政治类**（category=`political`, risk=`high`）：
  `反政府`, `颠覆国家`, `台独`, `港独`, `藏独`, `疆独`

> 实际 `_builtin_badwords.py` 中只写词 + 分类常量，不写业务逻辑。该文件**不作为目录**新增文件，仅包含一个常量 `BUILTIN_BADWORDS: list[tuple[str, str, str]]`。

---

## 五、隐私字段自动剔除工具设计

### 5.1 目标

对爬虫抓取的原始 HTML/JSON、业务中间数据做隐私字段自动清除，避免无授权隐私信息被存储。

### 5.2 行为

- 对 `dict`：遍历 keys，若 key 匹配隐私字段名正则，直接 `del dict[key]` 或置 `None`
- 对 `list`：递归处理每个元素
- 对 `str`：对整串扫描，替换正则匹配到的隐私片段（手机号 / 邮箱 / 微信 / QQ 等）为 `***`
- 对其他类型：原样保留
- 支持两种**工作模式**：
  - `STRIP`：直接删除整个字段（对结构字段，如 `{"phone": "..."}`）
  - `MASK`：在字段原值上做掩码保留（对文本字段，如 `{"remark": "联系138..."}`）

### 5.3 API 签名

```python
# core/compliance/privacy_stripper.py
class PrivacyStripper:
    def __init__(
        self,
        *,
        pii_mask: PIIMask | None = None,              # 注入脱敏器
        strip_keys: list[str] | None = None,          # .env: PRIVACY_STRIP_KEYS_JSON
        keep_masked: bool = True,                     # True → 保留掩码; False → 直接删除
    )

    def strip(self, data: Any, *, mode: str = "auto") -> Any
        # mode: "auto" / "strip" / "mask"

    def scan_report(self, data: Any) -> dict
        # 返回 {"stripped_keys": [...], "masked_values": [...], "total_hits": N}

# 模块级单例
privacy_stripper = PrivacyStripper()
```

### 5.4 默认识别字段（可在 `.env` 中覆盖）

```json
["phone", "mobile", "tel", "telephone", "wechat", "wx", "wx_id", "qq", "qq_id",
 "email", "mail", "id_card", "idcard", "id_number", "bank_card", "card_number",
 "address", "home", "nickname", "nick_name", "real_name", "realname",
 "contact", "contact_info", "contact_person", "user_name", "username",
 "password", "pwd", "passwd", "secret", "api_key", "token", "cookie"]
```

**大小写 / 下划线不敏感匹配**：`PhoneNumber`、`phone_number`、`phonenumber` 均命中。

---

## 六、统一合规校验入口设计

### 6.1 入口方法

提供一个 `ComplianceChecker` 类，两个场景共用：

| 场景 | 来源 | 调用方式 | 目标 |
|------|------|---------|------|
| **爬虫入库** | `core/spider_core/sdk.py` 的抓取结果 | `checker.check_for_storage(raw_data, context={"source": "spider", "task_id": "..."})` | 敏感词检测 + 隐私字段剔除 + 日志记录 |
| **消息发送** | 业务触达模块（未来扩展） | `checker.check_for_outbound(message_text, context={"source": "outbound", "channel": "..."})` | 敏感词检测 + 隐私字段掩码 + 决定是否放行/降级 |

### 6.2 公共 API 签名

```python
# core/compliance/compliance_checker.py
from dataclasses import dataclass, field

@dataclass
class ComplianceReport:
    passed: bool                          # 是否通过合规校验
    blocked: bool                        # 是否触发拦截
    risk_level: str                      # 最高风险等级
    masked_data: Any                     # 脱敏/过滤后的输出
    sensitive_hits: list[dict] = field(default_factory=list)  # 敏感词命中
    privacy_hits: list[dict] = field(default_factory=list)    # 隐私字段命中
    logs: list[str] = field(default_factory=list)             # 逐条日志
    context: dict = field(default_factory=dict)               # 原样返回 context

    def to_dict(self) -> dict

class ComplianceChecker:
    def __init__(
        self,
        *,
        pii_mask: PIIMask | None = None,
        sensitive_filter: SensitiveFilter | None = None,
        privacy_stripper: PrivacyStripper | None = None,
        enable_alert_on_high_risk: bool = True,     # .env: COMPLIANCE_ALERT_HIGH_RISK
    )

    def check_for_storage(self, data: Any, *, context: dict | None = None) -> ComplianceReport
        # 爬虫入库场景：敏感词检测 + 隐私字段剔除 + 记录日志
    def check_for_outbound(self, data: Any, *, context: dict | None = None) -> ComplianceReport
        # 消息发送场景：敏感词检测 + 隐私字段掩码
    def precheck(self, data: Any, *, context: dict | None = None, mode: str = "storage") -> ComplianceReport
        # 通用入口，mode ∈ {"storage", "outbound"}

# 模块级单例
compliance_checker = ComplianceChecker()
```

### 6.3 日志 & 告警联动

- 每次 `precheck` 调用记录 `logger.info`（概要：risk_level + 命中数）
- 敏感词 `risk=high` 或 隐私字段数量 ≥ 3 条 → 自动触发 `alert_service.crawler_risk_sync()` / 未来的 `service_exception_sync`
- 告警去抖：同一 context.task_id + 同一 day 只告警一次

---

## 七、数据生命周期工具设计

### 7.1 工具分类

| 工具 | 功能 | 适用层 |
|------|------|--------|
| 过期数据标记 | 对数据库/字典数据中的 `created_at < now - retention_days` 打 `is_archived = True` | DB 层（复用 T04 `archive_mixin`） + 通用字典 |
| 隐私信息一键清除 | 批量扫描指定结构，对所有隐私字段置 `None` / 空串 / 掩码形式 | 内存结构 + 纯文本文件（UTF-8） |
| 生命周期报表 | 返回 `{ "archived": N, "privacy_cleared": M, "blocked": K, "scan_time": "..." }` | JSON 报告 |

### 7.2 API 签名

```python
# core/compliance/data_lifecycle.py
class DataLifecycle:
    def __init__(
        self,
        *,
        retention_days: int = 90,              # .env: COMPLIANCE_RETENTION_DAYS
        privacy_stripper: PrivacyStripper | None = None,
        pii_mask: PIIMask | None = None,
    )

    # 批量过期标记
    def mark_expired(
        self,
        rows: list[dict],
        *,
        created_at_field: str = "created_at",
        archived_field: str = "is_archived",
    ) -> list[dict]
        # 返回修改后的副本；不修改原输入

    # 隐私信息一键清除（适用于 "数据过期后彻底消除隐私" 场景）
    def clear_privacy(self, data: Any, *, mode: str = "delete") -> Any
        # mode ∈ {"delete", "mask"}

    # 文本/日志文件级清除（文件路径输入）
    def clear_file(self, file_path: str, *, output_path: str | None = None, mode: str = "mask") -> dict
        # 返回 {"total_lines": N, "modified_lines": M, "output": path}

    # 生成生命周期报告
    def report(self, rows: list[dict] | None = None, *, extra: dict | None = None) -> dict

# 模块级单例
data_lifecycle = DataLifecycle()
```

### 7.3 与 T04 的衔接

- T04 的 `core/compliance/archive_mixin.py` 已在数据库层提供 `should_archive_row` 和 `mark_rows_archived`
- 本模块的 `DataLifecycle.mark_expired()` 是**通用结构层**的兄弟实现：可在不依赖 SQLAlchemy 的场景下使用（如纯内存数据、消息队列内容）
- 两者不冲突：数据库操作走 `archive_mixin`；非结构化数据走 `data_lifecycle`

---

## 八、.env 新增配置项

```dotenv
# ==================== Compliance (T06) ====================

# --- 隐私字段掩码 ---
PII_MASK_CHAR=*                 # 用于替换的掩码字符
PII_MASK_SHORT_LEN=8            # 掩码默认中间段长度
PII_EXTRA_KEYS_JSON=            # 可选: ["custom_pii_key1", "custom_pii_key2"]

# --- 敏感词过滤 ---
SENSITIVE_MASK_CHAR=*           # 敏感词替换字符
SENSITIVE_MASK_LEN=3            # 敏感词替换长度
SENSITIVE_BLOCK_THRESHOLD=medium # low/medium/high - 命中何种风险即拦截
SENSITIVE_WORDS_FILE=           # 可选: 自定义词库文件路径（一行一个：词,分类,风险等级）

# --- 隐私字段剔除 ---
PRIVACY_STRIP_KEYS_JSON=        # 可选: 自定义字段名列表（默认已内置常见 20+ 条）
PRIVACY_KEEP_MASKED=true        # true=保留掩码值; false=完全删除字段

# --- 合规校验 ---
COMPLIANCE_ALERT_HIGH_RISK=true # 命中高风险时是否触发告警
COMPLIANCE_ALERT_DEBOUNCE_SECS=600  # 告警去抖

# --- 数据生命周期 ---
COMPLIANCE_RETENTION_DAYS=90    # 数据留存周期（天）
```

---

## 九、分步开发流程

### Step 0（准备）
- 目标：验证现有基础设施可用、测试文件可被 pytest 发现
- 操作：`python -m pytest tests/test_t04_infra.py tests/test_t05_infra.py -q` 全绿
- 备注：不修改已有代码，仅确认可跑

### Step 1 — `core/compliance/pii_mask.py` 隐私脱敏库
- 实现 `PIIMask` 类、10 个字段级 `mask_*()` 方法、`auto_mask()`、`detect_pii()`
- 新增 `tests/test_t06_infra.py` 第一组用例（10+）：
  - 手机号 / 固话 / 微信 / QQ / 邮箱 / 身份证 / 昵称 / 企业名称 / 银行卡 / URL 各 1 条
  - `auto_mask` 嵌套 dict/list 用例 1 条
  - `detect_pii` 多类型检测用例 1 条

### Step 2 — `core/compliance/sensitive_filter.py` 敏感词引擎
- 手写 AC 自动机（Trie + BFS fail 指针 + 扫描合并 outputs）
- 内置广告/违规/涉敏词库；支持文件加载；`detect/filter_text/highlight/is_blocked`
- 新增测试：词库加载、AC 扫描正确性、大小写不敏感、中文多词同时命中、`filter_text` 输出结构、`is_blocked` 阈值判断

### Step 3 — `core/compliance/privacy_stripper.py` 隐私字段剔除
- 对 dict/list/str 深度遍历；支持 `strip` 与 `mask` 模式
- 默认隐私 key 列表 + `.env` 覆盖
- 新增测试：dict 字段删除、list 递归、字符串隐私片段掩码、保留模式 vs 删除模式

### Step 4 — `core/compliance/compliance_checker.py` 统一合规校验入口
- 组合 `pii_mask` / `sensitive_filter` / `privacy_stripper`
- `check_for_storage` / `check_for_outbound` / `precheck`
- 日志 & 告警联动（`logger.info` / `alert_service.crawler_risk_sync()`）
- 新增测试：storage 场景合规报告字段、outbound 场景掩码行为、高风险触发告警去抖

### Step 5 — `core/compliance/data_lifecycle.py` 数据生命周期工具
- `mark_expired` / `clear_privacy` / `clear_file` / `report`
- 新增测试：过期标记（基于相对时间，monkeypatch 冻结时间）、隐私清除两种模式、文件级清除（tmp_path）、report 结构

### Step 6 — `core/compliance/__init__.py` 导出符号 + `tests/test_t06_infra.py`
- 导出 `PIIMask`、`SensitiveFilter`、`PrivacyStripper`、`ComplianceChecker`、`DataLifecycle`、以及各自的模块级单例
- 更新测试、补充 `.env` 相关参数的覆盖测试（通过 `monkeypatch.setenv`）

### Step 7 — 运行全量测试 + 提交
- `python -m pytest tests/ -v`
- 确认 55 + N 全部通过（无 warning / deprecation 触发失败）
- git commit

---

## 十、风险与边界

| 风险 | 后果 | 预案 |
|------|------|------|
| AC 自动机中文字符边界问题（Python str 天然 Unicode，但 regex 对中文需小心） | 敏感词漏匹配 | `detect` 中使用 `casefold()` 规范化；测试覆盖 10+ 中文敏感词连续场景 |
| 隐私字段 key 匹配太宽 → 误删合法字段 | 数据丢失 | 默认模式为 `mask` 而非 `delete`；`PRIVACY_KEEP_MASKED=true`；对业务关键 key 提供白名单机制（`PRIVACY_PRESERVE_KEYS_JSON`），白名单内的 key 不被删除 |
| 敏感词库路径文件不存在 | 启动失败 | `load_file` 中 `logger.warning` 但不抛异常；内置词库保证最基本可用 |
| `.env` 中 JSON 数组格式错误 | 解析失败 | 用 `json.JSONDecodeError` try/except，fallback 为空列表；`logger.warning` |
| 与 T04 脱敏函数不一致 | 出现两套掩码规则 | `PIIMask.mask_phone/mask_email/mask_wechat` **调用链上复用 T04 同名函数** 或**确保输出格式完全一致**（已验证：T04 `mask_phone("13800138000") = "138****8000"`，本计划输出一致） |
| 数据生命周期文件级清除大文件（>1GB） | 内存爆 | `clear_file` 使用**逐行读取**；默认 `mode="mask"`，无需整体加载到内存 |

---

## 十一、验收标准

1. `python -m pytest tests/` → 全部通过（原 55 + 新增 ≈ 25-30）
2. 新增模块均位于 `core/compliance/`，不新增目录、不改 README/DEVELOP_RULES
3. 敏感词库路径、掩码字符、留存天数从 `.env` 读取；代码无硬编码字面量（除内置词库常量外）
4. `ComplianceChecker.precheck(raw_data)` 返回结构化 `ComplianceReport`，含 masked_data + hits + risk_level
5. 高风险场景触发 `alert_service` 告警（测试中通过 monkeypatch 注入 mock alert_service 验证）
6. 代码中所有 `from __future__ import annotations` + 中文注释 + 类型提示 对齐已有规范
