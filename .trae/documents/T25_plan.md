# T25 开发计划：core/spider_core 底层采集能力增强

> **执行约束**：不改动 README.md、DEVELOP_RULES.md、docs/TASK_LIST.md、business/adapter/web_admin 层所有代码；仅在 `core/spider_core/` 目录内新增文件（不删除、重命名任何既有目录/文件）。

---

## 一、现有基础调研结论

### 1.1 当前 `core/spider_core` 模块清单

| 文件 | 职责 | 本次是否修改 |
|------|------|-------------|
| `__init__.py` | 对外导出符号 | ✅ 新增导出（不删除已有符号） |
| `exceptions.py` | 异常定义体系 | 不修改 |
| `ua_pool.py` | UA 池/轮换 | 不修改 |
| `proxy_pool.py` | 代理池/健康度 | 不修改 |
| `rate_limiter.py` | 域名限流 | 不修改 |
| `robots_checker.py` | robots.txt 校验 | 不修改 |
| `checkpoint_manager.py` | 断点续爬 | 不修改 |
| `risk_controller.py` | 风控检测 | 不修改 |
| `sdk.py` | SpiderSDK (HTTP + Playwright) | 不修改 |

**复用能力清单**（直接引用，不重写）：代理池、UA 轮换、域名限流、风控检测、robots 校验、断点续爬、Playwright 基础渲染。

### 1.2 配置模式

- 项目使用 `configs/settings.py`（Pydantic Settings），环境变量 `SPIDER_*` 前缀
- 日志统一：`from infra.logger_setup import get_logger`
- 异常体系：`SpiderError(BizException)`，`trigger_alert=True` 触发全局告警
- 合规检查：已有 `SPIDER_COMPLIANCE_ENABLED`、`SPIDER_PII_MASK_ENABLED` 开关

### 1.3 依赖情况

- `requests`：已接入
- `playwright[sync_api]`：已接入（可选）
- **新增可选依赖**（通过 `.env` 开关控制，缺失时自动降级）：
  - `beautifulsoup4` / `lxml`：DOM 解析（如缺失降级为 `html.parser`）
  - `pdfplumber` / `pymupdf`：PDF 文本+表格提取
  - `Pillow` + `pytesseract`（或 `easyocr`）：图片 OCR
  - `python-docx`：Word 文本提取

---

## 二、本次新增文件清单（共 11 个文件）

所有文件均位于 `core/spider_core/` 目录内。

| # | 文件路径 | 职责 |
|---|---------|------|
| 1 | `core/spider_core/page_renderer.py` | 页面智能渲染器（Playwright 封装 + DOM 结构输出） |
| 2 | `core/spider_core/smart_analyzer.py` | 智能识别算法（列表块/标题/时间/链接/附件/分页） |
| 3 | `core/spider_core/pdf_parser.py` | PDF 解析器（文本/表格/OCR 开关） |
| 4 | `core/spider_core/image_parser.py` | 图片 OCR 解析器 |
| 5 | `core/spider_core/attachment_parser.py` | 附件统一入口（PDF/图片/Word 自动识别与分发） |
| 6 | `core/spider_core/rule_models.py` | 标准化采集规则数据结构（Pydantic Models） |
| 7 | `core/spider_core/field_extractor.py` | 字段提取引擎（CSS/XPath/正则 + 清洗 + 模板） |
| 8 | `core/spider_core/rule_engine.py` | 规则化采集执行器（三级链路 + 增量去重 + 重试） |
| 9 | `core/spider_core/dedup_store.py` | 增量去重存储（基于 Redis/memory stub） |
| 10 | `core/spider_core/alert_manager.py` | 告警管理器（失败率/匹配率阈值触发） |
| 11 | `core/spider_core/config.py` | 增强能力开关与阈值配置（SPIDER_ENHANCED_*） |

> **导出策略**：在 `__init__.py` 末尾追加新导出符号，保持原有导出不变。

---

## 三、页面智能识别算法设计

### 3.1 `page_renderer.py` — 智能渲染器

**核心类 `SmartPageRenderer`**：

```
方法:
  render(url, *, render_js=True, wait_selector=None, wait_ms=0)
    -> RenderedPage(html, dom, interactive_elements, links, forms, screenshot)

  render_batch(urls) -> List[RenderedPage]
```

**`RenderedPage` 数据结构**：

```python
@dataclass
class RenderedPage:
    url: str                     # 请求 URL
    final_url: str               # 最终 URL（处理跳转）
    html: str                    # 完整 HTML
    title: str                   # 页面 <title>
    links: List[Link]            # 所有 <a> 标签（text, href, attrs）
    images: List[Image]          # 所有 <img> 标签
    forms: List[Form]            # 所有 <form> 结构
    interactive_elements: List[InteractiveElement]  # 按钮/下拉/可点击元素
    meta_tags: Dict[str, str]    # <meta> 标签（description, keywords, og:*)
    status_code: int
    elapsed_ms: int
    error: Optional[str]
```

**实现逻辑**：
- 优先复用 `sdk.py` 的 Playwright 渲染能力（如已可用）
- `render_js=True` → 使用 Playwright 完整渲染；`render_js=False` → 退化为 `requests` + `html.parser`
- 对渲染结果执行统一 DOM 解析产出结构化元数据（links/images/forms）

### 3.2 `smart_analyzer.py` — 智能识别引擎

**核心类 `PageAnalyzer`**：

```
方法:
  analyze(rendered_page: RenderedPage) -> PageAnalysis

  detect_list_blocks(dom) -> List[ListBlock]
  detect_titles(dom) -> List[Candidate]
  detect_publish_time(dom) -> List[Candidate]
  detect_detail_links(dom, list_blocks) -> List[Candidate]
  detect_attachment_links(dom) -> List[AttachmentLink]
  detect_pagination(dom) -> PaginationRule
```

**`PageAnalysis` 输出结构**：

```python
@dataclass
class PageAnalysis:
    page_url: str
    list_blocks: List[ListBlock]          # 识别出的列表容器块
    titles: List[CandidateSelector]        # 标题候选
    publish_times: List[CandidateSelector] # 发布时间候选
    detail_links: List[CandidateSelector]  # 详情页链接候选
    attachment_links: List[AttachmentLink] # PDF/图片/Word 附件链接
    pagination: PaginationRule             # 翻页规则（下一页按钮 / 页码参数）
    recommended_rules: Dict[str, Any]      # 基于分析自动生成的推荐规则 JSON
    confidence_score: float                # 识别置信度 (0~1)
```

#### 3.2.1 列表块识别算法

1. **结构启发式**：
   - 寻找包含重复子结构的容器（`<ul>/<ol>/<div>` 的同类子元素个数 ≥ 3）
   - 子元素相似度打分：标签名一致性、class 名称相似度、子元素数量一致性
2. **内容密度启发式**：
   - 候选块内是否同时包含「链接 + 文本标题 + 可能的时间字段」
   - 子块内 URL 数量、文本长度方差、URL pattern 一致性打分
3. **排序**：输出按 `score = 结构相似度 × 内容密度 × 子块数量` 排序的前 N 个候选

#### 3.2.2 标题识别

1. **HTML 语义优先**：`<h1>~<h6>` → `<article>` → `<header>` 内首个文本块
2. **文本特征匹配**：
   - 正则匹配：`/[《"\[]?\s*[\u4e00-\u9fa5A-Za-z0-9\s·:-]{3,200}\s*[》"\]]?/`
   - 排除导航菜单、页脚、纯数字
3. **位置启发式**：页面前 30% 位置、最粗字体、最大字号优先
4. **输出**：每个候选包含 `{text, selector, confidence, match_type}`

#### 3.2.3 发布时间识别

1. **正则模式库**（支持中文/英文日期格式）：
   ```
   YYYY-MM-DD / YYYY/MM/DD / YYYY.MM.DD / YYYY年MM月DD日
   YYYY-MM-DD HH:MM / YYYY年MM月DD日 HH:MM:SS
   MM-DD / MM月DD日  （当年补齐）
   相对日期："3 天前"、"昨天"
   ```
2. **<time> 标签优先** → meta (article:published_time) → 文本正则
3. **输出**：每个候选 `{datetime_iso, raw_text, selector, confidence}`

#### 3.2.4 详情链接识别

1. 在每个 `ListBlock` 内部，提取第一个非空 `href` 的 `<a>` 作为该条目的详情链接
2. 链接 pattern 一致性检测：所有条目的 URL 是否共享 `path`、`?id=` 等模式
3. 排除跳出站外 URL、分页 URL、JS `void(0)` 链接

#### 3.2.5 附件下载链接识别

1. **后缀匹配**：
   ```
   PDF:   .pdf
   图片:  .jpg .jpeg .png .gif .bmp .webp .tif .tiff
   Word:  .doc .docx
   Excel: .xls .xlsx
   PPT:   .ppt .pptx
   压缩:  .zip .rar .7z
   ```
2. **Content-Type 兜底**：对未知后缀链接，发起 HEAD 请求判断实际类型（可开关）
3. **去重**：URL 归一化 + 相同文件名合并

#### 3.2.6 分页规则识别

1. **DOM 候选**：
   - 文本匹配："下一页"、"下一页 »"、"Next"、">"、"»"
   - 数字页按钮：1, 2, 3, ..., N 的连续序列
2. **URL 模式分析**：
   - 检测 `?page=N` / `?p=N` / `/page/N` / `?start=N` 等页码参数
   - 从已识别的数字页按钮推断页码变量名
3. **输出 `PaginationRule`**：
   ```python
   @dataclass
   class PaginationRule:
       mode: Literal["next_button", "page_param", "infinite_scroll"]
       next_selector: Optional[str]      # CSS 选择器（next_button 模式）
       page_param_name: Optional[str]    # URL 参数名（page_param 模式）
       max_pages: int                     # 识别到的最大页码或预估上限
       sample_urls: List[str]             # 样例 URL 列表
   ```

---

## 四、附件解析引擎设计

### 4.1 `attachment_parser.py` — 统一附件入口

**核心类 `AttachmentParser`**：

```
方法:
  parse(url_or_bytes, *, filename=None, mime_type=None)
    -> AttachmentResult

  parse_batch(attachment_links, *, task_id=None)
    -> List[AttachmentResult]

  download(url, *, task_id=None) -> bytes
```

**类型识别**：优先使用 URL 后缀 → 其次使用 MIME → 最后读取文件头 Magic Bytes 判断。

**自动分发**：根据识别出的类型分发到 `PdfParser` / `ImageParser` / `DocxParser`。

**`AttachmentResult` 结构**：

```python
@dataclass
class AttachmentResult:
    source_url: str
    filename: str
    mime_type: str
    file_size_bytes: int
    text: str                           # 提取的纯文本
    tables: List[ParsedTable]           # 表格（仅 PDF/图片中有）
    images: List[ImageMeta]             # 内嵌图片元信息
    fields: Dict[str, Any]              # 结构化字段（标题、发布单位、日期...）
    ocr_applied: bool                   # 是否启用了 OCR
    parse_status: Literal["ok", "partial", "failed"]
    error: Optional[str]
    elapsed_ms: int
```

### 4.2 `pdf_parser.py` — PDF 解析器

**核心类 `PdfParser`**：

```
方法:
  extract_text(pdf_bytes, *, pages=None) -> str     # 全文档文本提取
  extract_tables(pdf_bytes) -> List[ParsedTable]   # 表格结构化
  extract_images(pdf_bytes) -> List[ImageMeta]     # 内嵌图片
  extract_metadata(pdf_bytes) -> Dict[str, Any]    # PDF meta
  full_parse(pdf_bytes, *, ocr=False) -> AttachmentResult
```

**实现策略**：
- 默认：`pdfplumber`（文本+表格提取表现最佳）
- 缺失依赖降级：`pymupdf (fitz)` → `pypdf` → 记录解析失败并告警
- **OCR 开关**（`.env` 配置 `SPIDER_ENHANCED_PDF_OCR_ENABLED=false`）：
  - 关闭：对扫描版 PDF 返回空文本，标记 `parse_status="partial"` 并告警
  - 开启：将每页转图片后送入 `ImageParser` OCR，文本拼接到结果
- **PDF 兼容能力**：加密 PDF、损坏 PDF、空白 PDF 三种异常场景均需捕获并记录

### 4.3 `image_parser.py` — 图片 OCR 解析器

**核心类 `ImageParser`**：

```
方法:
  extract_text(image_bytes) -> str                # 全图 OCR
  extract_tables(image_bytes) -> List[ParsedTable] # 表格识别（需要OCR引擎支持）
  detect_layout(image_bytes) -> LayoutInfo         # 版面分析（段落/标题/表格/图片区域）
  parse(image_bytes) -> AttachmentResult
```

**实现策略**：
- 默认：`pytesseract`（Tesseract OCR，需要系统安装 tesseract 可执行）
- 后备：`easyocr`（纯 Python，首次需下载模型）
- **OCR 开关**（`.env` 配置 `SPIDER_ENHANCED_OCR_ENABLED=false`）：
  - 关闭：图片解析返回空文本，标记 `parse_status="partial"`
  - 开启：调用 tesseract/easyocr 执行 OCR
- 中文支持：语言代码 `chi_sim+eng`
- 多图拼接：同一任务关联图片按文件名排序批量执行

### 4.4 `ParsedTable` 表格结构

```python
@dataclass
class ParsedTable:
    page_index: int                     # 第几页/第几张图
    row_count: int
    column_count: int
    headers: List[str]                   # 表头（如有）
    rows: List[List[str]]                # 二维数据
    raw_markdown: str                    # Markdown 格式（便于文本流使用）
    confidence: float                    # 表格识别置信度
```

---

## 五、规则化采集执行引擎设计

### 5.1 `rule_models.py` — 标准化采集规则数据结构

**Pydantic 模型（纯 Pydantic v1/v2 兼容写法，不引入额外依赖）**：

```python
class ListRule(BaseModel):
    """列表页规则"""
    url_template: str                        # 入口 URL（可含 {keyword}, {page} 占位符）
    item_selector: str                       # 列表项 CSS 选择器
    link_selector: str                       # 详情链接 CSS 选择器（相对 item）
    link_attribute: str = "href"
    pagination: Optional[PaginationRule] = None  # 分页规则（空=不分页）
    max_pages: int = 20                       # 最大翻页数
    use_render: bool = False                  # 是否需要 JS 渲染

class FieldRule(BaseModel):
    """单字段提取规则"""
    name: str                                # 字段名（如 title/publish_time/source）
    extractor: Literal["css", "xpath", "regex", "text"]
    expression: str                          # CSS 选择器 / XPath / 正则模式 / 固定文本
    attribute: Optional[str] = None          # CSS 模式下的属性名（None=取 innerText）
    regex_group: int = 0                     # 正则分组号（0=完整匹配）
    required: bool = False                   # 是否必填，缺失则告警
    default_value: Optional[str] = None
    cleaners: List[str] = []                 # 清洗步骤（见 field_extractor）
    date_format: Optional[str] = None        # 日期格式化（如 "%Y-%m-%d"）

class DetailRule(BaseModel):
    """详情页规则"""
    url_template: Optional[str] = None       # 不填则继承列表页解析出的 URL
    fields: List[FieldRule]                  # 字段提取规则
    use_render: bool = False

class AttachmentRule(BaseModel):
    """附件解析规则"""
    link_selector: str                       # 附件链接 CSS 选择器
    link_attribute: str = "href"
    parse_pdf: bool = True
    parse_image: bool = True
    parse_docx: bool = True
    download_limit_mb: float = 50.0          # 单附件大小限制
    max_attachments_per_page: int = 10       # 每页最多解析附件数

class CrawlRuleSet(BaseModel):
    """完整采集规则集（规则引擎唯一入口结构）"""
    name: str = "default_rule"
    task_id: str = ""                        # 任务标识（用于去重、checkpoint）
    list_rule: ListRule
    detail_rule: Optional[DetailRule] = None
    attachment_rule: Optional[AttachmentRule] = None
    field_mapping: Dict[str, str] = {}       # 字段重命名映射（规则字段名 → 业务字段名）
    dedup_mode: Literal["url", "field", "none"] = "url"  # 去重策略
    dedup_fields: List[str] = []             # 自定义去重字段（dedup_mode=field 时使用）
    retry_count: int = 3                     # 单页失败重试次数
    retry_backoff_sec: float = 2.0
    match_rate_threshold: float = 0.5        # 字段匹配率低于此值触发告警
    failure_rate_threshold: float = 0.3      # 页面失败率高于此值触发告警
    max_items: int = 1000                    # 最大采集条目数
    compliance_check: bool = True            # 是否启用合规预检

# ---------- 预设模板（纯数据，非站点专属） ----------
TEMPLATES: Dict[str, List[FieldRule]] = {
    "gov_notice": [  # 政务通告
        FieldRule(name="title", extractor="css", expression="h1", required=True, cleaners=["strip_whitespace", "normalize_space"]),
        FieldRule(name="publish_time", extractor="css", expression=".time, .date, [class*='time']", cleaners=["strip_whitespace"], date_format="%Y-%m-%d"),
        FieldRule(name="source", extractor="css", expression=".source, [class*='source']"),
        FieldRule(name="content", extractor="css", expression=".content, article", cleaners=["strip_whitespace", "remove_extra_newlines"]),
        FieldRule(name="doc_number", extractor="css", expression="[class*='doc-number'], [class*='docno']"),
    ],
    "corp_announcement": [  # 企业公示
        FieldRule(name="title", extractor="css", expression="h1, .title", required=True, cleaners=["strip_whitespace"]),
        FieldRule(name="company_name", extractor="css", expression="[class*='company'], [class*='corp']"),
        FieldRule(name="publish_time", extractor="css", expression="[class*='time'], [class*='date']", date_format="%Y-%m-%d"),
        FieldRule(name="content", extractor="css", expression=".content, .body", cleaners=["strip_whitespace", "remove_extra_newlines"]),
        FieldRule(name="announcement_type", extractor="css", expression="[class*='type'], [class*='category']"),
    ],
    "violation_report": [  # 违规通报
        FieldRule(name="title", extractor="css", expression="h1, .title", required=True, cleaners=["strip_whitespace"]),
        FieldRule(name="violator", extractor="css", expression="[class*='violat'], [class*='subject']"),
        FieldRule(name="violation_content", extractor="css", expression="[class*='content'], [class*='fact']", cleaners=["strip_whitespace"]),
        FieldRule(name="punishment", extractor="css", expression="[class*='punish'], [class*='penalty']"),
        FieldRule(name="publish_time", extractor="css", expression="[class*='time'], [class*='date']", date_format="%Y-%m-%d"),
    ],
}
```

### 5.2 `field_extractor.py` — 字段提取引擎

**核心类 `FieldExtractor`**：

```
方法:
  extract(html_or_text, rules: List[FieldRule])
    -> Dict[str, ExtractedValue]

  extract_from_element(element, rule: FieldRule)
    -> ExtractedValue

  apply_cleaners(value: str, cleaners: List[str]) -> str
```

**三种提取方式实现**：

| 方式 | 依赖 | 实现说明 |
|------|------|---------|
| `css` | `beautifulsoup4` | `soup.select_one(expression).get_text()` 或取属性 |
| `xpath` | `lxml.html` | `tree.xpath(expression)` 取文本或属性 |
| `regex` | 标准库 `re` | `re.search(expression, text).group(regex_group)` |
| `text` | 标准库 | `expression` 作为固定值或 `{field}` 模板引用已提取字段 |

**清洗步骤（`cleaners` 支持可组合）**：

```
"strip_whitespace"       : strip()
"normalize_space"        : 合并连续空白为单空格
"remove_extra_newlines"  : 合并连续 \n 为 \n
"remove_html_tags"       : 正则 <[^>]+> 剥离
"trim_to_length:1000"    : 截断到 N 字符
"replace:old:new"        : 文本替换
"to_uppercase" / "to_lowercase"
"normalize_date:%Y-%m-%d"
"remove_pii"             : 触发 PII mask（复用现有 SPIDER_PII_MASK_ENABLED）
```

**`ExtractedValue` 结构**：

```python
@dataclass
class ExtractedValue:
    raw: str
    cleaned: str
    matched: bool
    match_score: float  # 必填未命中=0；命中且清洗后非空=1
    rule_name: str
```

### 5.3 `rule_engine.py` — 规则化采集执行器

**核心类 `RuleCrawlEngine`**：

```
方法:
  run(rule: CrawlRuleSet, *, task_id=None) -> EngineResult
```

**执行流程（三级链路自动流转）**：

```
[阶段1] 列表页采集
  ├─ 使用 sdk.get(url, render=list_rule.use_render) 拉取列表页
  │   └─ 自动复用 UA池/代理/限流/风控/robots
  ├─ list_rule.item_selector 解析每条 ListItem
  ├─ 对每条 item 提取 detail_link
  ├─ 分页循环：pagination.mode 驱动翻页（直到 max_pages 或无下一页）
  └─ 产出：detail_url 列表 + 已去重标记（dedup_store.check）

[阶段2] 详情页采集（并发执行，可配置）
  ├─ 对每个 detail_url 调用 sdk.get(render=detail_rule.use_render)
  ├─ field_extractor.extract(详情页 HTML, detail_rule.fields)
  ├─ 字段必填校验 → 缺失触发 alert_manager
  ├─ 字段映射：{rule字段 → 业务字段} (field_mapping)
  └─ 产出：结构化 Dict（含任务元信息：url, fetched_at）

[阶段3] 附件解析（attachment_rule 存在时）
  ├─ 在详情页 DOM 中执行 attachment_rule.link_selector
  ├─ attachment_parser.parse_batch(urls) 下载并解析
  ├─ 附件内容拼接到 item 的 attachments 字段
  └─ 文本内容可送入合规检测（compliance_check=true）
```

**核心控制逻辑**：

```
增量去重（dedup_store）:
  mode="url"   → 以 detail_url 作为 key，命中则跳过
  mode="field" → 以 dedup_fields 的值拼接 hash 作为 key
  mode="none"  → 关闭去重

失败重试:
  单页请求失败 → retry_count 次指数退避重试
  retry_backoff_sec × (2^attempt) 计算等待时长
  重试仍失败 → 记录失败 URL + 告警

告警触发（alert_manager）:
  - 字段匹配率 < match_rate_threshold （必填字段未命中比例过高）
  - 页面失败率 > failure_rate_threshold
  - 附件下载失败 > max_failure
  - OCR 失败 > 阈值
```

**`EngineResult` 结构**：

```python
@dataclass
class EngineResult:
    task_id: str
    total_pages_crawled: int
    total_items: int
    success_items: int
    failed_items: int
    items: List[Dict[str, Any]]           # 结构化采集结果
    attachments: List[AttachmentResult]    # 全部附件
    field_match_rate: float                # 字段匹配率
    failure_rate: float                    # 失败率
    alerts: List[Alert]                    # 触发的告警列表
    elapsed_ms: int
    errors: List[str]                      # 错误摘要
```

### 5.4 `dedup_store.py` — 去重存储

**核心类 `DedupStore`**：

```
方法:
  check_and_mark(key: str) -> bool      # True=已存在, False=新增（原子操作）
  check(key: str) -> bool
  mark(key: str) -> None
  clear(task_id: str) -> int
  count(task_id: str) -> int
```

**实现策略**：
- Redis 可用 → `SET key task_id` + `EXISTS key`（原子命令保证并发安全）
- Redis 不可用 → `threading.Lock + Dict[str, Set[str]]` 内存实现（降级）
- key 生成：`spider:dedup:{task_id}:{hash(url_or_fields)}`
- TTL：默认 7 天（通过 `.env` 可配置）

### 5.5 `alert_manager.py` — 告警管理器

**核心类 `AlertManager`**：

```
方法:
  record(alert: Alert) -> None
  check_thresholds(stats: EngineStats) -> List[Alert]
  flush(task_id: str) -> List[Alert]
```

**`Alert` 结构**：

```python
@dataclass
class Alert:
    task_id: str
    level: Literal["warning", "error", "critical"]
    category: Literal["parse", "match_rate", "failure_rate", "attachment", "ocr", "compliance"]
    message: str
    details: Dict[str, Any]
    timestamp: float
```

**触发策略**：
- 解析失败、匹配率过低、附件下载失败 → 通过 `logger.warning/error` 记录
- `SpiderError(trigger_alert=True)` 机制触发全局告警通道（复用现有告警通路）

---

## 六、配置（.env 开关）—— `config.py`

**新增环境变量（不修改现有 `.env.example`，仅在代码中读取，默认关闭）**：

| 变量 | 默认值 | 说明 |
|------|--------|------|
| `SPIDER_ENHANCED_ENABLED` | `false` | 增强能力总开关 |
| `SPIDER_ENHANCED_USE_RENDER` | `false` | 是否默认启用 JS 渲染 |
| `SPIDER_ENHANCED_PDF_OCR_ENABLED` | `false` | 扫描版 PDF 是否 OCR |
| `SPIDER_ENHANCED_OCR_ENABLED` | `false` | 图片 OCR 总开关 |
| `SPIDER_ENHANCED_OCR_LANG` | `chi_sim+eng` | OCR 语言包 |
| `SPIDER_ENHANCED_OCR_BACKEND` | `tesseract` | OCR 引擎（tesseract/easyocr） |
| `SPIDER_ENHANCED_TESSERACT_PATH` | `(空=系统 PATH)` | tesseract 可执行路径 |
| `SPIDER_ENHANCED_ATTACHMENT_MAX_MB` | `50` | 单附件大小限制 |
| `SPIDER_ENHANCED_DEDUP_TTL_DAYS` | `7` | 去重 key 存活天数 |
| `SPIDER_ENHANCED_MATCH_RATE_THRESHOLD` | `0.5` | 字段匹配率告警阈值 |
| `SPIDER_ENHANCED_FAILURE_RATE_THRESHOLD` | `0.3` | 页面失败率告警阈值 |
| `SPIDER_ENHANCED_COMPLIANCE_CHECK` | `true` | 采集数据是否走合规预检 |
| `SPIDER_ENHANCED_PII_MASK` | `true` | 采集数据是否 PII 脱敏 |

**实现方式**：`os.environ.get(name, default)` + 统一通过 `EnhancedConfig` 单例暴露。

---

## 七、与合规预检的集成

所有经 `RuleCrawlEngine.run()` 产出的 `items`：
1. 若 `SPIDER_ENHANCED_COMPLIANCE_CHECK=true` → 对 `content` / `title` 等文本字段执行敏感词检测和风险等级标记
2. 若 `SPIDER_ENHANCED_PII_MASK=true` → 对文本字段执行 PII 脱敏（邮箱/手机号/身份证/银行卡 等）
3. 合规检测结果写入 `item["_compliance"]` 字段，供上层业务判断是否拦截/告警

> 实现时通过 `try/except` 保护，合规模块不可用时自动降级为 `status=unknown` 不阻塞采集流程。

---

## 八、分步开发流程（按依赖顺序 8 步）

### 阶段 0：代码规范与依赖声明（0.5h）
- 确认 DEVELOP_RULES.md 中关于 import、命名、异常体系约定
- 在 `configs/settings.py` 中补充 `SPIDER_ENHANCED_*` 字段声明（作为可选字段，默认值与 `.env` 默认一致）

### 步骤 1：`config.py`（0.5h）
- 实现 `EnhancedConfig` 单例，读取上述 `.env` 变量并暴露

### 步骤 2：`rule_models.py`（1.5h）
- 定义 `ListRule / FieldRule / DetailRule / AttachmentRule / CrawlRuleSet / PaginationRule`
- 内置 `TEMPLATES` 三类场景预设字段模板
- 编写模块内 docstring 演示如何构造最简规则 JSON

### 步骤 3：`page_renderer.py`（2h）
- 实现 `SmartPageRenderer`，内部调用 `sdk.py` 的 `SpiderSDK.get(render=True|False)` 并解析 DOM
- 产出 `RenderedPage / Link / Image / Form / InteractiveElement`
- 对 DOM 解析使用 BeautifulSoup4（缺失降级 `html.parser`）

### 步骤 4：`smart_analyzer.py`（3h）
- 实现列表块识别、标题识别、时间识别、链接识别、附件识别、分页识别六套算法
- 产出 `PageAnalysis` 及推荐规则 `recommended_rules` JSON

### 步骤 5：`field_extractor.py`（2h）
- 实现 CSS / XPath / 正则 / text 四种提取器
- 实现 cleaners 清洗流水线
- 集成 PII mask（复用已有能力）

### 步骤 6：`pdf_parser.py` + `image_parser.py` + `attachment_parser.py`（3h）
- PDF：文本/表格/meta 三路径实现 + OCR 开关
- Image：OCR 文本提取 + 版面分析框架
- Attachment：统一入口 + 类型识别 + 批量处理

### 步骤 7：`dedup_store.py` + `alert_manager.py`（1.5h）
- DedupStore：Redis/内存 双通道
- AlertManager：阈值判断 + SpiderError trigger_alert

### 步骤 8：`rule_engine.py`（2.5h）
- 串联：列表页 → 详情页 → 附件 → 合规预检
- 集成：去重、重试、告警、统计全链路
- 返回 `EngineResult`

### 步骤 9：`__init__.py` 导出（0.5h）
- 在现有导出末尾追加新符号，保持向后绝对兼容

---

## 九、风险与应对

| 风险 | 应对 |
|------|------|
| 可选依赖未安装（pdfplumber/pytesseract 等） | 每个解析器 try/except ImportError，返回 `parse_status="partial"` 并打印降级提示 |
| Playwright 浏览器未安装 | 使用 `sdk.py` 既有逻辑：检测缺失抛出清晰异常 |
| OCR 引擎不可用 | OCR 开关关闭为默认，开启但执行失败时记录告警 |
| Redis 不可用 | DedupStore 自动降级为线程安全的内存 Dict |
| 规则 JSON 格式错误 | Pydantic 校验确保类型正确，错误时抛出清晰定位的异常 |
| 大型 PDF/图片导致内存/超时 | `download_limit_mb` 限制 + 流式读取 + 单页解析超时保护 |
| 并发重复采集同一 URL | DedupStore 的 check_and_mark 原子语义保证 |

---

## 十、不做的事情（Scope 边界）

1. ❌ 不包含任何站点专属规则（如 "某某政务网怎么爬"）
2. ❌ 不引入 Web UI、HTTP API、数据库模型变更
3. ❌ 不修改现有 `sdk.py` / `risk_controller.py` 等文件
4. ❌ 不改变 `__all__` 中已有导出顺序与符号名（仅追加）
5. ❌ 不写入 .env.example（保留业务层按需配置）

---

> **本文件为计划文档，不涉及实际代码修改，待审批后按步骤 0-9 执行。**
