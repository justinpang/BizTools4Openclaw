# T31 计划：可视化采集配置编辑器重构（原子化步骤编排 + 向导式交互 + 自动选最新）

## 1. 现状与问题分析（Repo Research Conclusion）

### 1.1 现有技术栈
| 层级 | 模块 | 说明 |
|---|---|---|
| 底层引擎 | `core/spider_core/rule_engine.py` + `smart_analyzer.py` + `page_renderer.py` | T25 通用规则解析引擎，提供 CrawlRuleSet → 采集执行 |
| 底层模型 | `core/spider_core/rule_models.py` | CrawlRuleSet / ListRule / DetailRule / FieldRule / PaginationRule / AttachmentRule |
| 业务层 | `business/custom_spider/service.py` + `repository.py` + `data_models.py` | T26 采集方案 CRUD、版本管理、测试运行、调度启停 |
| API | `web_admin/api/crawl_config.py` | 现有 10+ 个 API（plan list/detail/create/update/test/start/stop/import/export/preview/analyze） |
| 前端 | `web_admin/static/js/crawl_editor.js` + `templates/` | 5 步线性流程（URL 预览 → 列表 → 详情 → 附件 → 保存） |

### 1.2 现状痛点
1. **线性流程僵化**：5 步固定顺序，无法按需增删步骤；多页级联列表/多级详情无法支持
2. **智能识别弱**：smart_analyzer 识别结果仅做推荐，无"按时间自动选最新"能力
3. **单步测试缺失**：仅能全链路测试，选择器/字段提取等细粒度调试困难
4. **历史方案兼容**：旧 rule_config 无 step 概念，新编辑器需自动转换
5. **页面布局**：单页滚动，无右侧步骤竖栏管理，无步骤高亮/拖拽/增删交互

### 1.3 强制约束（必须严格遵守）
```
✅ 禁止修改：README.md、DEVELOP_RULES.md、docs/TASK_LIST.md
✅ 禁止修改：core/spider_core 目录下任何解析逻辑文件
✅ 100% 复用 T25 CrawlRuleSet 规则引擎
✅ 100% 复用 T26 PlanService（CRUD/版本/调度/测试）
✅ 不新增/删除/重命名项目目录（文件可新增）
✅ 敏感信息自动脱敏，操作日志自动记录
```

---

## 2. 总体设计方案

```
                    ┌────────────────────────────────────────────┐
                    │               web_admin 前端               │
                    │  crawl_step_editor.html + .js + .css       │
                    │    · 三栏布局                              │
                    │    · 步骤可视化编排                        │
                    │    · 智能识别结果交互                      │
                    │    · 单步/全链路测试                       │
                    └──────────────┬─────────────────────────────┘
                                   │ HTTP / JSON
          ┌────────────────────────┼───────────────────────────────┐
          │                        ▼                               │
          │   web_admin/api/crawl_config.py  （新增 8 个 API）      │
          │   · /crawl/steps/smart-detect    智能识别                 │
          │   · /crawl/steps/step-test       单步测试                 │
          │   · /crawl/steps/full-test       全链路测试               │
          │   · /crawl/steps/assemble        组装 rule_config         │
          │   · /crawl/steps/draft-save/load 草稿保存/加载            │
          │   · /crawl/steps/compat-convert  旧方案转换               │
          │   · /crawl/steps/template-apply  模板一键应用             │
          │   · /crawl/steps/preview-render  页面预览                 │
          └────────────────────────┬───────────────────────────────┘
                                   │
          ┌────────────────────────┼───────────────────────────────┐
          │                        ▼                               │
          │  business/custom_spider/  （新增 4 个文件）              │
          │   · step_models.py           步骤模型 + StepsPackage     │
          │   · step_service.py          编排服务：组装/测试/草稿    │
          │   · smart_detector.py        列表+时间智能识别增强器     │
          │   · step_pydantic_models.py  新 API 的 Pydantic 模型     │
          └──────────────┬─────────────────┬───────────────────────┘
                         ▼                 ▼
              T25 rule_engine          T26 PlanService
              （100% 复用）             （100% 复用）
```

**核心思路**：前端维护一个 `StepsPackage` 状态（有序步骤数组），编辑过程以步骤为单元；保存时通过 `StepAssembler` 将 StepsPackage 组装为 T25 的 `CrawlRuleSet`（`rule_config` JSON），复用 T26 原有保存逻辑。旧方案打开时通过 `CompatConverter` 将 `rule_config` 反向转换为 StepsPackage。

---

## 3. 编辑器三栏布局详细设计与交互说明

### 3.1 整体页面结构

```
┌────────────────────────────────────────────────────────────────────────────┐
│  crawl-step-topbar（固定高度 56px，position:sticky top:0）                  │
│  ┌───────────┐ ┌──────────┐                       ┌────────┐┌──────┐┌────┐ │
│  │ URL 输入框 │ │ 加载预览 │  （步骤导航：← 上一步  下一步→） │ │测试步骤 │ │保存 │
│  └───────────┘ └──────────┘                       └────────┘└──────┘└────┘ │
├──────────┬─────────────────────────────────────────────────────────────────┤
│          │                                                │                │
│  canvas  │  主画布区（动态切换）                            │  右侧步骤栏    │
│  区域    │  ┌─────────────────────────────┐                │ （width:340px） │
│          │  │  Step #N 配置面板            │                │ ┌────────────┐ │
│  flex:1  │  │                             │                │ │ + 新增步骤  │ │
│          │  │  · 配置表单                 │                │ ├────────────┤ │
│          │  │  · 自动识别候选              │                │ │ #1 页面访问│ │
│          │  │  · 本步测试结果              │                │ │ #2 列表识别│ │
│          │  │  · 上游数据展示              │                │ │ #3 详情跳转│ ◀ 当前高亮
│          │  └─────────────────────────────┘                │ │ #4 附件解析│ │
│          │                                                 │ │ #5 字段映射│ │
│          │                                                 │ │ #6 结果预览│ │
│          │                                                 │ └────────────┘ │
│          │                                                 │  (拖拽排序)    │
└──────────┴─────────────────────────────────────────────────┴────────────────┘
```

### 3.2 顶部操作栏（topbar）
| 组件 | 位置 | 交互说明 |
|---|---|---|
| `URL 输入框` | 左侧，`flex: 0 0 360px` | 初始值来自 `rule_config.list_rule.url_template`；编辑后更新 Step#1 |
| `加载预览` 按钮 | URL 输入框右侧 | 调用 `/crawl/steps/preview-render`，返回渲染后的 HTML 预览（带隐私脱敏） |
| `上一步 / 下一步` | 中部 | 切换当前步骤 `activeStep`，按钮在边界禁用；切换保留所有步骤配置 |
| `测试当前步骤` | 右侧 | 调用 `/crawl/steps/step-test`，结果在画布底部以 tabular 形式展示 |
| `全链路测试` | 右侧（可选小按钮） | 调用 `/crawl/steps/full-test`，所有步骤串行执行 |
| `保存方案` | 最右（主按钮） | 调用 StepAssembler 组装 → PlanService.update / create；高危操作二次确认弹窗 |

### 3.3 右侧步骤管理竖栏（sidebar）

**视觉规范**（写在 `web_admin/static/css/admin.css` 追加段）
```
.step-card {
  padding: 12px;
  margin-bottom: 10px;
  border: 2px solid #e5e7eb;
  border-radius: 8px;
  cursor: pointer;
  transition: all 0.2s;
  background: #fff;
}
.step-card.active {
  border-color: #2563eb;
  background: #eff6ff;
  box-shadow: 0 2px 6px rgba(37,99,235,0.15);
}
.step-card.untested  .status-dot { background:#eab308; }
.step-card.tested    .status-dot { background:#16a34a; }
.step-card.error     .status-dot { background:#dc2626; }
.step-card .order-badge {
  display: inline-block; width: 26px; height: 26px; line-height:26px;
  background: #374151; color: #fff; text-align:center; border-radius:50%;
  font-weight:600; font-size: 12px;
}
.step-card.active .order-badge { background: #2563eb; }
```

**交互行为**：
- 点击步骤卡 → 切换 `activeStep`，主画布重新渲染该步配置面板
- 点击 `+ 新增步骤` → 弹步骤类型选择（6 种标准），插入至当前步骤后
- 步骤卡悬停显示 `删除` / `上移` / `下移` 按钮（仅多于 1 步时显示）
- HTML5 `draggable` 支持拖拽排序；拖拽结束后重新编号 `step_order`
- 每个步骤卡片显示状态圆点（未测试/已测试/错误）

### 3.4 主画布区（canvas）

每个步骤独立的 `<section class="step-panel" data-step-type="XXX">` 模板，非活动步调用 `display:none`。

```html
<div id="canvas-wrap">
  <section class="step-panel" data-step-type="page_access">...</section>
  <section class="step-panel" data-step-type="list_detect">
    <!-- 智能识别结果区 -->
    <div class="smart-candidates">
      <h4>识别候选容器（按置信度降序）</h4>
      <table><thead><tr><th>选择器</th><th>条目数</th><th>置信度</th><th></th></tr></thead>
      <tbody>...</tbody></table>
      <!-- 采集范围模式 -->
      <div class="crawl-scope">
        <label><input type="radio" name="scope" value="latest"> 自动选最新条目</label>
        <label><input type="radio" name="scope" value="top_n"> 采集前 N 条</label>
        <label><input type="radio" name="scope" value="all"> 全量采集</label>
      </div>
    </div>
  </section>
  <section class="step-panel" data-step-type="detail_jump">...</section>
  <section class="step-panel" data-step-type="attachment_parse">...</section>
  <section class="step-panel" data-step-type="field_mapping">...</section>
  <section class="step-panel" data-step-type="result_preview">...</section>
</div>
```

**切换流程（JS）**：
```javascript
window.__crawlSteps = {
  activeStepId: "step_1",
  steps: [ /* 每步配置对象 */ ],
  // 每步输出数据缓存（供下一步读取）
  upstream: { step_1: { html: "", url: "" }, step_2: { items: [...] }, ... }
};
function switchStep(stepId) {
  document.querySelectorAll(".step-card").forEach(/* 更新高亮 */);
  document.querySelectorAll(".step-panel").forEach(/* 显隐切换 */);
  // 步骤间数据自动传递：上一步 upstream.xxx 注入当前步 hidden 输入
  window.__crawlSteps.activeStepId = stepId;
  // 自动草稿持久化
  saveDraftAuto();
}
```

### 3.5 操作日志与高危二次确认

- 所有"保存方案""启用调度""删除步骤"操作调用 `PlanService` 时写入 `custom_spider_operation_logs`（复用 T26 现有机制）
- 保存/删除前弹出原生 confirm 对话框（文案："确认保存该采集方案？此操作将创建新版本并可影响后续调度任务。"）

---

## 4. 6 种原子步骤的配置项与输入/输出结构体定义

新增文件：`business/custom_spider/step_models.py`

```python
from __future__ import annotations
from dataclasses import dataclass, field
from typing import Any, Dict, List, Literal, Optional

# 步骤类型枚举常量
STEP_TYPES = {
    "PAGE_ACCESS":    "page_access",    # 1. 页面访问
    "LIST_DETECT":    "list_detect",    # 2. 列表识别
    "DETAIL_JUMP":    "detail_jump",    # 3. 详情跳转
    "ATTACHMENT_PARSE": "attachment_parse",  # 4. 附件解析
    "FIELD_MAPPING":  "field_mapping",  # 5. 字段映射
    "RESULT_PREVIEW": "result_preview", # 6. 结果预览
}

# 采集范围模式
CRAWL_SCOPE_MODES = {
    "LATEST": "latest",   # 自动选最新
    "TOP_N":  "top_n",    # 采集前 N 条
    "ALL":    "all",      # 全量采集
}

@dataclass
class StepConfig:
    """单步配置。StepsPackage 按 step_order 排序。"""
    step_id: str                     # 前端生成：step_{idx}_{ts}
    step_type: str                   # STEP_TYPES 值之一
    step_order: int                  # 1-based 排序号
    status: str = "pending"          # pending/ok/error
    title: str = ""                  # 用户可自定义标题（默认=步骤类型中文名）
    config: Dict[str, Any] = field(default_factory=dict)
    auto_detect: bool = True         # 是否启用自动识别
    validated: bool = False
    last_tested_at: Optional[str] = None
    test_result: Optional[Dict[str, Any]] = None
    warnings: List[str] = field(default_factory=list)
    errors: List[str] = field(default_factory=list)

@dataclass
class StepTestResult:
    """单步测试结果，用于前端画布展示。"""
    step_id: str
    step_type: str
    success: bool
    duration_ms: int
    message: str = ""
    output: Dict[str, Any] = field(default_factory=dict)  # 具体输出（items/html/fields...）
    masked: bool = True  # 输出是否已脱敏

@dataclass
class StepsPackage:
    """整个编辑器的状态对象。
    可序列化为 JSON，作为 draft 存 Redis 或嵌入 rule_config 的 "_steps_package" 扩展字段。
    """
    version: int = 1
    plan_name: str = ""
    target_domain: str = ""
    spider_type: str = "generic"
    steps: List[StepConfig] = field(default_factory=list)
    schedule_config: Optional[Dict[str, Any]] = None
    increment_config: Optional[Dict[str, Any]] = None
    # 兼容标记：由旧 rule_config 自动转换时设为 True
    migrated_from_legacy: bool = False
```

### 4.1 Step#1 page_access（页面访问）

**config 结构**
```json
{
  "url": "https://example.gov.cn/news/list",
  "use_render": true,
  "render_wait_ms": 1500,
  "http_method": "GET",
  "headers": {},
  "cookie_raw": "string | null（写入时自动加密，UI 仅显示 ***）"
}
```

**输入**：无（或使用 `upstream.step_N.url` 作为级联访问）
**输出**：`{ url, title, html_preview, screenshot_data_url | null, status_code }`
**T25 映射**：对应 `ListRule.url_template` 或 `DetailRule.url_template`

### 4.2 Step#2 list_detect（列表识别）

**config 结构**
```json
{
  "item_selector": "ul.news-list > li",
  "link_selector": "a",
  "link_attribute": "href",
  "title_selector": ".title",
  "time_selector": ".time",
  "time_format": "%Y-%m-%d",
  "crawl_scope": "latest",          // latest | top_n | all
  "top_n_count": 10,
  "pagination": {
    "mode": "none | next_button | page_param | infinite_scroll",
    "next_selector": null,
    "page_param_name": null,
    "max_pages": 20
  },
  "use_render": false
}
```

**输入**：`upstream[step_1].html_preview`（来自页面访问）或用户贴入的 HTML
**输出**：
```json
{
  "items": [
    { "title": "…", "link": "https://…", "publish_time": "2025-01-02", "_raw_time": "01/02/2025" }
  ],
  "total_detected": 42,
  "confidence": 0.87,
  "candidates": { "container_selectors": [...], "time_selectors": [...] }
}
```

**T25 映射**：对应 `ListRule` 全部字段 + `PaginationRule` + 新增 `increment_config`

### 4.3 Step#3 detail_jump（详情跳转）

**config 结构**
```json
{
  "detail_fields": [
    { "name": "content",    "extractor": "css",   "expression": ".article-body", "required": true },
    { "name": "author",     "extractor": "css",   "expression": ".author" },
    { "name": "publish_at", "extractor": "text",  "expression": null, "date_format": "%Y-%m-%d" }
  ],
  "use_render": false,
  "render_wait_ms": 1000
}
```

**输入**：`upstream[step_2].items[*].link`（列表步骤输出的链接数组）
**输出**：`{ detail_items: [{ title, content, author, publish_at, _source_url }, ...] }`
**T25 映射**：对应 `DetailRule.fields` 数组

### 4.4 Step#4 attachment_parse（附件解析）

**config 结构**
```json
{
  "link_selector": "a.attachment",
  "link_attribute": "href",
  "parse_pdf": true,
  "parse_image": true,
  "parse_docx": true,
  "max_attachment_size_kb": 10240
}
```

**输入**：`upstream[step_3].detail_items[*]._source_url` 或 step#2 的 `items[*].link`
**输出**：`{ attachments: [ { filename, mime, text_preview, url } ] }`
**T25 映射**：对应 `AttachmentRule`

### 4.5 Step#5 field_mapping（字段映射）

**config 结构**
```json
{
  "map": {
    "title": "title",
    "publish_time": "publish_time",
    "body": "content",
    "source_url": "_source_url"
  },
  "extra_defaults": {
    "source_domain": "{{domain}}",
    "category": "gov_notice"
  }
}
```

**输入**：step#3/detail 或 step#2/list 的 items
**输出**：`{ mapped_items: [...] }`
**T25 映射**：对应 `CrawlRuleSet.field_mapping`

### 4.6 Step#6 result_preview（结果预览）

**config 结构**
```json
{
  "sample_size": 20,
  "compare_raw": true,   // 是否并列展示原始字段
  "mask_pii": true       // 自动脱敏
}
```

**输入**：`upstream[step_5].mapped_items`
**输出**：表格化展示（仅对前端渲染有意义）
**T25 映射**：无底层字段，纯前端呈现

---

## 5. 列表智能识别与"自动选最新"算法逻辑 + 降级方案

新增文件：`business/custom_spider/smart_detector.py`

> ⚠️ **不改动** `core/spider_core/smart_analyzer.py`，而是在业务层封装一个 `SmartDetector`，以 T25 已识别结果为输入做增强：
> - 时间字段多格式正则识别
> - 候选容器打分排序
> - 按时间取最新条目 / top_N / 全量
> - 识别失败降级入口（返回推荐手动填写提示）

### 5.1 算法流程

```
输入：html_content（字符串）或 RenderedPage 对象；可选 target_url
输出：{
  "success": bool,
  "containers": [ { selector, item_count, confidence, sample_items } ],
  "time_fields": [ { selector, sample_values, format_hint, confidence } ],
  "items": [ { title, link, publish_time_iso, _raw_time, _rank_score } ],
  "item_count_total": int,
  "confidence": float,
  "crawl_scope_suggestion": "latest | top_n | all",
  "degrade_reason": null | "low_confidence" | "no_time_field" | "no_container"
}
```

**步骤 1 — 容器识别**（容器打分）
- 取 `<ul>/<ol>/<div class="...list...">/table > tr` 等节点
- 每个候选容器计算得分：`score = 条目数 * 0.4 + 子节点平均文本长度 * 0.3 + 链接密度 * 0.3`
- 链接密度 = 容器内 `<a>` 数 / 子节点数
- 返回 Top 3 容器（按 score 降序）

**步骤 2 — 时间字段识别**（多格式正则）
```python
TIME_PATTERNS = [
    r"(\d{4})[-/年\.](\d{1,2})[-/月\.](\d{1,2})",          # 2024-01-02, 2024/1/2, 2024年1月2日
    r"(\d{1,2})[-/\.](\d{1,2})[-/\.](\d{2,4})",            # 01-02-2024, 1.2.24
    r"(\d{4})(\d{2})(\d{2})",                               # 20240102
    r"发布时间[:：]?\s*(\d{4}[-/年\. ]\d{1,2}[-/月\. ]\d{1,2})",
    r"时间[:：]?\s*(\d{4}[-/年\. ]\d{1,2}[-/月\. ]\d{1,2})",
]
```
- 对每个候选条目的文本块扫描所有模式
- 记录匹配命中位置 + 格式推测（`%Y-%m-%d` / `%Y年%m月%d日` / `%Y/%m/%d` 等）
- 选择 Top 3 时间字段（按命中频率）

**步骤 3 — 条目排序与过滤**
- 提取条目 `{title, link, publish_time}`
- 尝试将 `publish_time` 解析为 `datetime`；解析失败则用 `None` 标记
- 排序：`key=(-is_valid_time, -parsed_time, -original_index)`
  - 有效时间优先，按时间倒序；无时间的保留原顺序
- **latest 模式**：取排序后第 1 条（若未解析到任何时间则回退 top_n）
- **top_n 模式**：取前 N 条
- **all 模式**：返回全部

**步骤 4 — 置信度评估与降级**
- `confidence = 0.5 * has_time_field + 0.3 * item_count_norm + 0.2 * link_density_ok`
- 阈值：`<0.3 → degrade`
- 降级时返回 `degrade_reason`，前端渲染"💡 建议：请手动填写 `item_selector` 与 `time_selector`"提示块

### 5.2 时间字段自动格式化

识别出时间后，同时输出 `_time_format_hint`（最接近的 strftime 格式字符串），直接注入 Step#2 `time_format` 默认值。

### 5.3 前端交互降级（识别失败时）

- 画布顶部展示黄色警示条："⚠️ 未能自动识别到列表/时间字段，已切换到手动填写模式"
- 提供 3 个输入框：`列表容器选择器` / `标题选择器` / `时间选择器`
- 提供"尝试重新识别"按钮（调用 smart-detect API）

---

## 6. 步骤流转、数据传递、测试验证的完整流程

### 6.1 状态对象（StepsPackage）

前端 `window.__crawlSteps` 与后端请求共用同一 JSON schema：

```json
{
  "version": 1,
  "plan_name": "示例政府公告采集",
  "target_domain": "example.gov.cn",
  "spider_type": "generic",
  "steps": [
    {
      "step_id": "step_1",
      "step_type": "page_access",
      "step_order": 1,
      "title": "访问列表页",
      "config": { "url": "https://example.gov.cn/list", "use_render": true }
    },
    { "step_id": "step_2", "step_type": "list_detect", "step_order": 2, ... }
  ],
  "schedule_config": { "enabled": true, "cron": "0 0 2 * * ?" },
  "increment_config": { "dedup_mode": "url", "crawl_scope": "latest" }
}
```

### 6.2 步骤间数据传递

**规则**：步骤 `#N` 的 `upstream` = 步骤 `#N-1` 的 `test_result.output`（若存在）；若 `#N-1` 未测试，则使用用户手动填写值（URL/选择器等）。

```
Step#1 page_access
    └─ output: { html, url, title }
         ↓ upstream
Step#2 list_detect
    └─ output: { items: [{title, link, publish_time}], total_detected }
         ↓ upstream
Step#3 detail_jump
    └─ output: { detail_items: [...] }
         ↓ upstream
Step#4 attachment_parse
    └─ output: { attachments: [...] }
         ↓ upstream
Step#5 field_mapping  → output: mapped_items
         ↓ upstream
Step#6 result_preview → 前端渲染表格
```

### 6.3 单步测试 API（/crawl/steps/step-test）

**请求**：
```json
{
  "step_id": "step_2",
  "step_type": "list_detect",
  "config": { "item_selector": "ul.news-list > li", ... },
  "page_html": "…（可选，若 step#1 已测试则此处可自动传入）…",
  "upstream_data": { "url": "https://…", "items": [...] }
}
```

**响应**：`{ code, msg, data: StepTestResult }`

**服务端实现**（`business/custom_spider/step_service.py` 中的 `StepTester`）：
- `page_access` → 调用 `core.spider_core.page_renderer.RenderedPage.fetch()`（复用 T25）
- `list_detect` → 调用 `SmartDetector.detect_all()` + T25 `field_extractor`
- `detail_jump` → 组装临时 DetailRule → 调用 `rule_engine.RuleCrawlEngine._fetch_detail()`
- `attachment_parse` → 调用 `core.spider_core.attachment_parser`
- `field_mapping` → 在业务层做 dict 更新映射（纯 Python，无底层）
- `result_preview` → 由前端渲染，后端仅做脱敏包装

### 6.4 全链路测试 API（/crawl/steps/full-test）

**请求**：整个 `StepsPackage`
**响应**：按步骤顺序返回 `StepTestResult[]` + 最终 `mapped_items[]`

**实现**：`StepTester.run_all(package)`，上一步 output 注入下一步 upstream_data

### 6.5 草稿持久化（Redis）

- Key: `crawl_steps_draft:{session_id}|{plan_id}`，expire=24h
- API: `/crawl/steps/draft-save` / `/crawl/steps/draft-load` / `/crawl/steps/draft-clear`
- 前端：每 30 秒 + 切换步骤时自动调用 `draft-save`

---

## 7. 历史方案兼容迁移方案

新增类 `CompatConverter`（在 `business/custom_spider/step_service.py`）

### 7.1 legacy rule_config → StepsPackage（编辑器打开旧方案）

输入（T25 CrawlRuleSet 结构）：
```json
{
  "name": "old_plan",
  "list_rule": { "url_template": "...", "item_selector": "...", "link_selector": "a" },
  "detail_rule": { "fields": [...], "use_render": false },
  "attachment_rules": [...],
  "field_mapping": { "title": "title" },
  "pagination": { ... },
  "max_items": 100
}
```

**转换规则**：
```python
steps = []
# Step#1 page_access
steps.append(StepConfig(
    step_id="step_1", step_type="page_access", step_order=1,
    title="访问列表页",
    config={"url": rule.list_rule.url_template,
            "use_render": rule.list_rule.use_render}
))
# Step#2 list_detect
steps.append(StepConfig(
    step_id="step_2", step_type="list_detect", step_order=2,
    title="识别列表",
    config={"item_selector": rule.list_rule.item_selector,
            "link_selector": rule.list_rule.link_selector,
            "time_selector": rule.list_rule.fields[*time_field*].expression
                             if found else "",
            "crawl_scope": "all",
            "pagination": rule.pagination or {}}
))
# Step#3 detail_jump（仅当 rule.detail_rule.fields 非空）
if rule.detail_rule.fields:
    steps.append(StepConfig(
        step_id="step_3", step_type="detail_jump", step_order=3,
        title="详情页字段提取",
        config={"detail_fields": [f.model_dump() for f in rule.detail_rule.fields],
                "use_render": rule.detail_rule.use_render}
    ))
# Step#4 attachment_parse（仅当 rule.attachment_rules 非空）
if rule.attachment_rules:
    steps.append(StepConfig(
        step_id="step_4", step_type="attachment_parse", step_order=4,
        title="附件解析",
        config=rule.attachment_rules[0].model_dump()
    ))
# Step#5 field_mapping
steps.append(StepConfig(
    step_id="step_5", step_type="field_mapping", step_order=5,
    title="字段映射", config={"map": rule.field_mapping or {}}
))
# Step#6 result_preview
steps.append(StepConfig(
    step_id="step_6", step_type="result_preview", step_order=6,
    title="结果预览", config={"sample_size": 20, "compare_raw": True}
))

package = StepsPackage(plan_name=rule.name, steps=steps, migrated_from_legacy=True)
```

**关键原则**：旧方案打开后，用户编辑后保存，`rule_config` 仍为 T25 CrawlRuleSet（由 StepAssembler 反向组装），对 T26 存储层 100% 兼容。

### 7.2 StepsPackage → rule_config（保存时的组装）

新增 `StepAssembler.build_rule_config(package) -> dict`，实现 §6 反向：
- Step#1 `page_access.url` → `list_rule.url_template`
- Step#2 `list_detect.*` → `list_rule.item_selector / link_selector / pagination`
- Step#2 `crawl_scope=latest` → 注入 `increment_config.take_latest_by_time = true`
- Step#3 `detail_jump.detail_fields` → `detail_rule.fields`
- Step#4 `attachment_parse.*` → `attachment_rules[0]`
- Step#5 `field_mapping.map` → `field_mapping`

保存路径：前端调用老的 `/api/admin/crawl/plans/{id}/update` 或 `/create`，但先调 `/crawl/steps/assemble` 获取组装后的 `rule_config`，并将 `package` 作为 `rule_config._steps_package` 扩展字段一起保存。

### 7.3 导入/导出格式升级

- 导出时在原有 JSON 追加 `"_steps_package": {...}` 字段
- 导入时若检测到 `_steps_package` 则直接使用；否则走 §7.1 自动转换

---

## 8. 分步执行开发流程

### Phase A：数据层 + 服务层（2 个文件）

**A1. `business/custom_spider/step_models.py`**（新建）
- 定义 `StepConfig` / `StepTestResult` / `StepsPackage` dataclass
- 定义 `STEP_TYPES` / `CRAWL_SCOPE_MODES` 常量
- 提供 `step_config_from_dict` / `package_from_dict` 工具函数

**A2. `business/custom_spider/step_pydantic_models.py`**（新建）
- `StepTestRequest` / `StepTestResponse` / `PackageSaveRequest`
- `SmartDetectRequest` / `SmartDetectResponse`
- 所有模型 `extra="ignore"`

**A3. `business/custom_spider/smart_detector.py`**（新建）
- 实现 `SmartDetector.detect_all(html, target_url=None) -> dict`
- 实现 `_detect_containers(soup) -> List[dict]`
- 实现 `_detect_time_fields(soup) -> List[dict]`
- 实现 `_apply_scope(items, mode, top_n) -> List[dict]`
- 实现 `_parse_time_iso(raw_text) -> str | None`（多格式）

**A4. `business/custom_spider/step_service.py`**（新建，核心）
- `StepAssembler.build_rule_config(package) -> dict`（组装为 CrawlRuleSet dict）
- `StepAssembler.build_package_from_legacy(rule_config) -> StepsPackage`
- `StepTester.test_step(step_type, config, page_html, upstream_data) -> StepTestResult`
- `StepTester.run_all(package) -> List[StepTestResult]`
- `DraftService.save(session_id, plan_id, package_json) -> bool`（Redis）
- `DraftService.load(session_id, plan_id) -> StepsPackage | None`

### Phase B：API 层（1 个文件，追加 8 个路由）

**B1. `web_admin/api/crawl_config.py`**（修改，在文件尾追加）
- `POST /crawl/steps/preview-render`：渲染 URL 返回 HTML 预览（脱敏）
- `POST /crawl/steps/smart-detect`：对输入 HTML 做智能识别，返回候选容器 + 时间字段 + 预览条目
- `POST /crawl/steps/step-test`：测试单个步骤
- `POST /crawl/steps/full-test`：全链路测试
- `POST /crawl/steps/assemble`：StepsPackage → rule_config dict
- `POST /crawl/steps/compat-convert`：旧 rule_config → StepsPackage
- `POST /crawl/steps/draft-save` + `POST /crawl/steps/draft-load` + `POST /crawl/steps/draft-clear`
- `POST /crawl/steps/template-apply`：`{template_id: "gov_notice_list"}` 返回预置 StepsPackage

**B2. 模板表（business/custom_spider/step_service.py 内常量）**
```python
STEP_TEMPLATES = {
    "gov_notice_list": StepsPackage(
        steps=[...预设步骤...]
    ),
    "enterprise_news": StepsPackage(...),
    "simple_list_only": StepsPackage(
        steps=[StepConfig(step_type="page_access", ...),
               StepConfig(step_type="list_detect", ...),
               StepConfig(step_type="field_mapping", ...),
               StepConfig(step_type="result_preview", ...)]
    ),
}
```

### Phase C：前端层（3 个文件）

**C1. `web_admin/templates/partials/crawl_step_editor.html`**（新建）
- 按 §3 实现 topbar + canvas + sidebar 三栏 HTML 结构
- 6 个 `<section class="step-panel" data-step-type="…">` 配置面板
- 在右侧步骤栏内：新增步骤按钮 + 步骤卡片（含拖拽属性 `draggable="true"`）

**C2. `web_admin/static/js/crawl_step_editor.js`**（新建）
- `window.__crawlSteps` 状态初始化（编辑模式时调 `draft-load` 或 `compat-convert`）
- `switchStep(stepId)` 步骤切换 + 自动草稿
- `renderStepCards()` / `renderStepPanel(step)` 渲染
- 拖拽排序（HTML5 dragstart/dragover/drop）
- `handleTestCurrentStep()` / `handleTestFull()` / `handleSavePlan()`
- `handleSmartDetect()` 调用 API 后将候选自动回填

**C3. `web_admin/static/css/admin.css`**（修改，文件尾追加）
- 新增 `.crawl-step-topbar` / `.crawl-step-body` / `.crawl-step-canvas` / `.crawl-step-sidebar` 布局样式
- 新增 `.step-card` / `.step-card.active` / `.status-dot` / `.order-badge`
- 新增 `.smart-candidates` / `.crawl-scope` 结果区样式
- 新增 `.step-panel` 面板样式 + 表单 fieldset 风格

### Phase D：入口路由 + 兼容路由（1 个文件）

**D1. `web_admin/pages.py`**（修改）
- 新增路由 `/admin/crawl/steps-editor?plan_id=...` 渲染 `crawl_step_editor.html`
- 保留原有 `/admin/crawl/editor` 路由（兼容历史 URL），做 307 跳转到新编辑器或直接复用同一模板

### Phase E：测试

**E1. `tests/test_t31_step_editor.py`**（新建）
- `test_step_models_serialization`：StepsPackage ↔ JSON 往返
- `test_compat_legacy_to_package`：旧 rule_config → 6 步 package
- `test_compat_roundtrip`：legacy → package → rule_config，关键字段原值保留
- `test_smart_detector_html1` + `test_smart_detector_html2`：2 份 mock HTML
- `test_scope_latest`：mock 含时间字段条目，断言取最新
- `test_step_tester_page_access` / `test_step_tester_list` / `test_step_tester_mapping`
- `test_assembler_produces_valid_ruleset`：用 `CrawlRuleSet.model_validate()` 断言合法
- `test_draft_service_roundtrip`：Redis 内存版

---

## 9. 风险与防护

| 风险 | 影响 | 应对 |
|---|---|---|
| StepAssembler 产生非法 CrawlRuleSet | 保存后执行失败 | 组装后在服务端用 `CrawlRuleSet.model_validate()` 二次校验，失败返回结构化错误，前端高亮问题步骤 |
| 旧方案字段缺失导致 compat-convert 出错 | 编辑器打开失败 | Converter 做字段缺省容错；缺 time_selector 时留空字符串 + 前端提示"请手动填写" |
| smart_detector 正则 CPU 耗时 | 大 HTML 页面 | 截断输入到 200KB；正则只扫描文本节点而非整 HTML |
| Redis 不可用导致草稿失效 | 体验降级 | `DraftService` 捕获异常后退化为内存缓存 + console 告警；不阻塞保存主流程 |
| 敏感信息未脱敏展示 | 合规风险 | 所有 `test_result.output` 由 `core/compliance/pii_mask.py` 统一脱敏（手机号/邮箱/身份证/微信号） |

---

## 10. 文件变更清单

### 新增文件
```
business/custom_spider/step_models.py            # 步骤数据结构
business/custom_spider/step_pydantic_models.py   # API Pydantic 模型
business/custom_spider/smart_detector.py         # 列表+时间智能识别
business/custom_spider/step_service.py           # StepAssembler / StepTester / DraftService / CompatConverter / STEP_TEMPLATES

web_admin/templates/partials/crawl_step_editor.html
web_admin/static/js/crawl_step_editor.js

tests/test_t31_step_editor.py
```

### 修改文件
```
web_admin/api/crawl_config.py                    # 追加 8 个 /crawl/steps/* API
web_admin/pages.py                               # 注册 /admin/crawl/steps-editor 路由
web_admin/static/css/admin.css                   # 追加三栏布局 + 步骤卡片样式
```

### 不修改文件（严格约束）
```
core/spider_core/ *   （只读复用）
README.md / DEVELOP_RULES.md / docs/TASK_LIST.md
```

---

## 11. 验收标准（Acceptance Criteria）

1. ✅ 访问 `/admin/crawl/steps-editor` 能展示 topbar + canvas + sidebar 三栏布局
2. ✅ 输入 URL → 点击"加载预览" → Step#1 测试结果展示成功
3. ✅ Step#2 调用 smart-detect → 自动回填 `item_selector` 与 `time_selector`
4. ✅ 选择 `crawl_scope=latest` → 组装后 `increment_config.take_latest_by_time=true`
5. ✅ 步骤卡片可拖拽排序，顺序改变后 `step_order` 正确更新
6. ✅ 保存后 PlanService 生成新版本；回滚旧版本时 compat-convert 自动生效
7. ✅ 用既有 T25 `CrawlRuleSet.model_validate(assembled)` 不抛异常
8. ✅ 测试套件 `pytest tests/test_t31_step_editor.py -q` 全绿
9. ✅ `tests/test_t26_custom_spider.py` 仍全部通过（不破坏旧功能）
10. ✅ 所有预览/测试结果不包含明文手机号/邮箱（由 `pii_mask.py` 验证）
