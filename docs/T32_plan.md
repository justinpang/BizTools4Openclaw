# T32 开发计划：重构可视化采集配置编辑器（内嵌交互式浏览器 + 操作录制 + 智能指令 + 零代码）

基于 T01~T31 全量代码，在 `web_admin` 现有采集配置功能基础上做交互重构，**100%复用 T25 底层页面渲染、附件解析、规则执行能力**，不改动 core 层核心逻辑与三份核心文档。

**禁止修改**：
- `README.md`、`DEVELOP_RULES.md`、`docs/TASK_LIST.md`
- `core/spider_core/*`（底层解析引擎）

**允许修改/新增**：
- `web_admin/templates/partials/crawl_step_editor.html`（三栏布局 + 浏览器面板）
- `web_admin/static/js/crawl_step_editor.js`（交互/录制/智能指令）
- `web_admin/static/css/admin.css`（样式增补）
- `web_admin/pages.py`（路由注册，仅追加）
- `web_admin/api/crawl_config.py`（新 API，仅追加）
- `business/custom_spider/step_models.py`（扩展 step_type/参数，不删除已有）
- `business/custom_spider/step_service.py`（扩展 assembler/compat/tester）
- `business/custom_spider/command_library.py`（**新增**：智能指令库）
- `business/custom_spider/step_pydantic_models.py`（已有，按需扩展）

---

## 0. 现状与问题分析

| 能力 | T31 现状 | T32 目标 |
|---|---|---|
| 页面预览 | 通过 `/crawl/preview/render` 获取 HTML 后在 `<iframe>` 渲染 | 真实浏览器交互，可点击、输入、滚动，实时同步 DOM 到步骤生成器 |
| 步骤配置 | 手动填写选择器 + 智能识别辅助 | **操作录制**：浏览时点击即生成步骤；支持元素拾取模式与指令插入模式 |
| 步骤类型 | 6 种固定类型（page_access / list_detect / detail_jump / attachment_parse / field_mapping / result_preview） | 扩展为**可插拔**：在 6 种基础类型上新增 **智能指令型步骤**（list_latest / extract_table / pagination_loop 等） |
| 测试能力 | 单步测试 + 全链路测试 | 单步 + 全链路 + **增量测试**（仅测试新添加的步骤） |
| 方案管理 | 保存/读取/导入导出 | **版本管理** + 历史回退 + 导入导出 |
| 布局 | 顶部操作栏 + 左侧画布（展示静态面板）+ 右侧步骤列表 | 顶部操作栏 + **左侧浏览器**（真实交互）+ 右侧上下栏（上：步骤列表+状态；下：当前步骤详情） |

---

## 1. 三栏布局详细交互设计与组件拆分

### 1.1 整体布局框架

```
┌───────────────────────────────────────────────────────────────────┐
│ 顶部操作栏 crawl-step-topbar (固定高度 56px)                        │
│ [方案名] [URL地址栏] [← → ↻] [模式切换:浏览/拾取/指令] [测试] [保存]│
├──────────┬────────────────────────────────────────────────────────┤
│          │ 右栏上半：步骤列表 .steps-list                          │
│ 左栏：   │  ┌───┐┌───┐┌───┐┌───┐   步骤卡片（编号+状态+拖拽）     │
│ 浏览器   │  │ 1 ││ 2 ││ 3 ││+  │   可折叠 / 可拖拽调整顺序        │
│ iframe   │  └───┘└───┘└───┘└───┘                                 │
│ 画布区   │ ───────────────────────────────────────                 │
│          │ 右栏下半：当前步骤详情 .step-detail-panel               │
│          │  - 标题 + step_type + 编辑/删除按钮                    │
│          │  - 参数表单（随 step_type 动态渲染）                    │
│          │  - 单步测试按钮、测试结果展示                           │
│          │  - 预览区（该步骤提取到的字段）                         │
│ .        │                                                        │
└──────────┴────────────────────────────────────────────────────────┘
```

### 1.2 组件拆分

| 组件 | CSS 选择器 | 功能 |
|---|---|---|
| 顶部操作栏 | `.crawl-step-topbar` | 方案名称、URL、前进/后退/刷新、模式切换、测试、保存 |
| 左侧浏览器画布 | `.crawl-step-browser` | `<iframe sandbox>` 或 `<div>` 渲染实际页面内容 |
| 元素高亮层 | `.crawl-step-highlight` | 与 iframe 同层级，鼠标悬浮在元素上显示高亮框 + selector tooltip |
| 右侧上栏 - 步骤列表 | `.steps-list` | 卡片式步骤展示，支持拖拽排序、状态颜色、禁用/启用/删除 |
| 右侧下栏 - 步骤详情 | `.step-detail-panel` | 当前步骤参数表单 + 单步测试按钮 + 测试结果预览 |
| 指令弹窗 | `.command-modal` | 选中元素后弹出：选择指令 → 配置参数 → 自动生成步骤 |
| Toast 提示 | `.crawl-toast` | 操作反馈、警告、错误 |

### 1.3 关键交互流程

#### 流程 A：浏览器加载
```
用户输入 URL → 点击「📡 加载预览」
  → POST /api/admin/crawl/preview/render
  → 后端调用 SmartPageRenderer 渲染
  → 返回 html_preview + final_url + status_code
  → 前端 <iframe srcdoc=html_preview> + postMessage 监听
```

#### 流程 B：元素拾取（点击即生成字段）
```
用户点击模式切换为「🔎 拾取模式」
  → 鼠标悬浮在元素上 → 蓝色高亮边框
  → 点击目标元素
  → 弹出指令选择器：「绑定字段 title」「绑定字段 content」「提取为列表容器」...
  → 用户选择指令后自动生成 step_config → 加入 steps 列表
```

#### 流程 C：操作录制（浏览即生成步骤）
```
用户点击模式切换为「⚡ 录制模式」
  → 在 iframe 内点击链接 → 自动生成【page_access】或【detail_jump】步骤
  → 在 iframe 内点击分页按钮 → 自动生成【pagination_loop】智能指令
  → 在 iframe 内点击附件 → 自动生成【attachment_parse】步骤
  → 每次操作后步骤列表追加一条，状态从 pending → 执行 → success
```

#### 流程 D：拖拽调整步骤
```
用户在步骤列表拖拽卡片
  → 目标位置高亮
  → 释放后 steps 数组重排 + step_order 更新
  → 渲染主面板（若切换了高亮元素）
```

---

## 2. 标准化步骤类型定义、输入输出结构体、参数说明

### 2.1 扩展 step_type（在现有 6 种基础类型后追加）

在 `step_models.py` 的 `STEP_TYPES` 字典中**追加**（不修改原有 key）：

```python
STEP_TYPES = {
    # ── T31 原有 6 种 ──
    "PAGE_ACCESS":      "page_access",
    "LIST_DETECT":      "list_detect",
    "DETAIL_JUMP":      "detail_jump",
    "ATTACHMENT_PARSE": "attachment_parse",
    "FIELD_MAPPING":    "field_mapping",
    "RESULT_PREVIEW":   "result_preview",
    # ── T32 新增：智能指令型（command_*）──
    "CMD_LIST_LATEST":     "command_list_latest",    # 自动取最新 N 条
    "CMD_LIST_FILTER":     "command_list_filter",    # 按条件筛选列表
    "CMD_EXTRACT_TABLE":   "command_extract_table",  # 表格结构化提取
    "CMD_BATCH_FIELDS":    "command_batch_fields",   # 批量字段提取
    "CMD_REGEX_EXTRACT":   "command_regex_extract",  # 正则匹配提取
    "CMD_PAGINATION_LOOP": "command_pagination_loop",# 翻页循环
    "CMD_SCROLL_LOAD":     "command_scroll_load",    # 滚动加载
    "CMD_CONDITION_STOP":  "command_condition_stop", # 条件终止
}
```

> 约定：所有 `command_*` 类型在 `StepAssembler.build_rule_config` 中被聚合到 `list_rule.extra_steps` 或 `detail_rule.fields`，由底层 T25 引擎统一执行。

### 2.2 各 step_type 的 config schema

#### 基础类型（T31 既有，略）

#### 智能指令类型（T32 新增）

```python
# command_list_latest
config = {
    "item_selector": ".news-item",        # 列表容器
    "link_selector": "a",                 # 链接元素
    "link_attribute": "href",
    "title_selector": ".title",
    "time_selector": ".publish-time",
    "time_format": "%Y-%m-%d",
    "top_n": 20,                           # 取最新 N 条
    "auto_detect_time": True,             # 自动识别时间字段
}

# command_list_filter
config = {
    "item_selector": ".news-item",
    "filters": [
        {"field": "title", "op": "contains", "value": "招标公告"},
        {"field": "publish_time", "op": "after_date", "value": "2024-01-01"},
    ],
    "logic": "and",
}

# command_extract_table
config = {
    "table_selector": "table.data-table",
    "header_row_index": 0,
    "has_header": True,
    "use_first_row_as_header": False,
    "column_aliases": ["title", "publish_time", "category"],
}

# command_batch_fields
config = {
    "fields": [
        {"name": "title", "selector": "h1", "extractor": "css", "required": True},
        {"name": "content", "selector": ".body", "extractor": "css"},
        {"name": "publish_time", "selector": ".ptime", "date_format": "%Y-%m-%d"},
        {"name": "source", "selector": ".source > a", "attr": "text"},
    ],
}

# command_regex_extract
config = {
    "source_field": "content",
    "patterns": [
        {"name": "phone", "regex": r"1[3-9]\d{9}", "group": 0},
        {"name": "email", "regex": r"[\w\.-]+@[\w\.-]+\.\w+", "group": 0},
    ],
}

# command_pagination_loop
config = {
    "mode": "next_button",                 # next_button | numbered | infinite_scroll
    "next_selector": "a.next-page",
    "max_pages": 20,
    "max_items": 500,
    "stop_when_no_items": True,
}

# command_scroll_load
config = {
    "scroll_times": 30,                     # 最大滚动次数
    "delay_ms": 800,                        # 每次等待
    "scroll_selector": "window",            # 或特定 div
    "stop_when_no_new_items": True,
}

# command_condition_stop
config = {
    "condition_mode": "item_seen",          # item_seen | item_date_before | item_field_match
    "seen_item_link": "https://example.com/news/123",  # 当命中已知条目时终止
    "item_date_before": "2024-01-01",
    "item_field_match": {"field": "title", "op": "contains", "value": "（停止标志）"},
    "max_pages": 100,
}
```

### 2.3 输入输出约定（运行时）

| 步骤类型 | 输入 upstream_data | 输出 output |
|---|---|---|
| page_access | — | `{html, title, final_url, status_code}` |
| list_detect | page_access 的 html | `{items:[{link,title,publish_time}], item_count, suggestion}` |
| detail_jump | list_detect 的 items | `{items:[{title,content,publish_time,source_url}], mask_pii:true}` |
| attachment_parse | detail_jump 的 items | `{items:[..., attachments:[{filename,size,type,content}]]}` |
| field_mapping | 上游结构化数据 | `{mapped_items:[{title,body,publish_time,source_url}]}` |
| command_* | 同上 | 与上游一致（对列表/详情数据做扩展） |
| result_preview | 任意 | `{sample:[前 20 条], total_count}` |

---

## 3. 操作录制的事件监听逻辑、步骤自动生成规则

### 3.1 核心机制：iframe 双向通信

```
┌────────────── 前端页面 ──────────────┐
│                                       │
│  topbar URL输入 + 模式切换            │
│  ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─    │
│  │ .crawl-step-browser (iframe)  │   │
│  │ ┌───────────────────────────┐ │   │
│  │ │   被预览页面            │ │   │
│  │ │   所有 a.click / input │ │   │
│  │ │   事件通过 override     │ │   │
│  │ │   注入到 parent         │ │   │
│  │ └──────┬──────────────────┘ │   │
│  │        │ postMessage         │   │
│  │        ▼                    │   │
│  │  .crawl-step-highlight       │   │
│  │    高亮层 + 选择器分析      │   │
│  │                              │   │
│  └──────────────────────────────┘   │
│                                       │
└────────────┬──────────────────────────┘
             │ 录制事件 → 生成 step_config → 加入 steps 数组
             ▼
        .steps-list + .step-detail-panel
```

### 3.2 iframe 脚本注入（在 `<iframe srcdoc>` 中追加）

```javascript
// 在每个 HTML 中注入 <script> 片段（T32 前端在渲染前处理）
(function override(){
    document.addEventListener('click', function(e){
        var el = e.target;
        // 向上追溯到最近的可交互元素（a/button/input[type=submit]）
        var action = el.closest && el.closest('a,button,input[type="submit"]');
        if (action && parent !== window) {
            parent.postMessage({
                type: 'crawl_record_click',
                target: {
                    tag: action.tagName,
                    href: action.href || '',
                    text: (action.innerText || '').trim(),
                    selector: cssPath(action),  // 生成唯一 CSS 选择器
                    is_attachment: /\.(pdf|doc|docx|xls|xlsx|zip|rar)/i.test(action.href || ''),
                    is_pagination: /(下一页|下一页|next|page=\d+)/i.test(action.innerText || action.href),
                }
            }, '*');
            // 阻止默认跳转（录制时不真跳转）
            e.preventDefault();
        }
    });
    document.addEventListener('mouseover', function(e){
        parent.postMessage({type:'crawl_record_hover', target:{selector: cssPath(e.target), text:(e.target.innerText||'').slice(0,80)}},'*');
    });
})();
```

### 3.3 父页面监听 + 规则匹配

```javascript
// 父窗口：根据录制事件类型判断自动生成哪种 step
window.addEventListener('message', function(ev){
    if (!ev.data || ev.data.type !== 'crawl_record_click') return;
    var t = ev.data.target;
    if (mode !== 'record') return;

    // 规则优先级：
    if (t.is_attachment) {
        appendStep('attachment_parse', {link_selector: t.selector});
        flash('已加入【附件解析】步骤', 'info');
    }
    else if (t.is_pagination) {
        appendStep('command_pagination_loop', {next_selector: t.selector});
        flash('已加入【翻页循环】步骤', 'info');
    }
    else if (t.tag === 'A' && t.href) {
        // 列表内链接 → 自动推断为 detail_jump
        var inList = t.selector.match(/(li|tr|\.item|\.news|article)/i);
        if (inList && !isDetailPage()) {
            appendStep('detail_jump', {detail_fields: [...] });
        } else {
            appendStep('page_access', {url: t.href, use_render: true});
        }
    }
});
```

### 3.4 CSS 选择器生成（前端工具函数）

```javascript
function cssPath(el) {
    if (!(el instanceof Element)) return '';
    if (el.id) return '#' + el.id;
    // 优先使用 class（如果稳定且唯一）
    var cls = Array.from(el.classList).find(function(c){
        return document.querySelectorAll('.' + CSS.escape(c)).length <= 3;
    });
    if (cls) return '.' + cls;
    // 回退到 nth-child 路径
    var parts = [];
    var cur = el;
    while (cur && cur.nodeType === 1) {
        var idx = Array.from(cur.parentNode.children).indexOf(cur) + 1;
        parts.unshift(cur.tagName.toLowerCase() + ':nth-child(' + idx + ')');
        cur = cur.parentNode;
        if (parts.length > 6) break;
    }
    return parts.join(' > ');
}
```

---

## 4. 智能指令集的实现逻辑、参数配置、适配场景

### 4.1 架构：指令即可插拔的 step_type

```
              ┌──────────────────────────────────────────────┐
              │  command_library.py （T32 新增文件）          │
              │                                               │
              │  class Command:                               │
              │    - name: str                                │
              │    - label: str                               │
              │    - description: str                         │
              │    - params_schema: Dict[str, Field]          │
              │    - match_trigger(html, click_selector) -> float  // 自动识别置信度
              │    - to_step_config(selector, context) -> dict       // 生成 step.config
              │    - run(html, config) -> Dict[str, Any]             // 测试时运行
              │                                               │
              │  注册的 8 种指令（见 §2.1 command_*）         │
              └──────────────────────────────────────────────┘
                                 │
                                 ▼ 被前端 /api/admin/crawl/steps/commands 路由查询
```

### 4.2 指令库定义

| 指令 name | UI label | 适用场景 |
|---|---|---|
| `command_list_latest` | 🆕 最新 N 条 | 新闻/公告/招标列表，取最新 N 条 |
| `command_list_filter` | 🔍 条件筛选 | 标题含关键字、日期范围等过滤 |
| `command_extract_table` | 📋 表格提取 | HTML `<table>` 结构化到 rows |
| `command_batch_fields` | 📦 批量字段 | 详情页多字段提取，等同原 detail_jump 的扩展版 |
| `command_regex_extract` | 🔤 正则提取 | 从文本提取 phone/email/id 等 |
| `command_pagination_loop` | 🔁 翻页循环 | 有「下一页」按钮的列表 |
| `command_scroll_load` | 🔽 滚动加载 | 无限滚动列表、微博动态等 |
| `command_condition_stop` | 🛑 条件终止 | 抓取到已知条目/日期阈值/字段匹配时停止 |

### 4.3 前端指令插入弹窗

在 `拾取模式`下点击元素后弹出的选择器结构：

```
┌─ 选择指令（已选中元素: <code>li:nth-child(3) > a.title</code>） ─┐
│                                                                       │
│  ┌──────────────┐ ┌──────────────┐ ┌──────────────┐                │
│  │ 🆕 最新N条    │ │ 🔍 条件筛选    │ │ 📋 表格提取    │                │
│  │ 作为列表容器   │ │  筛选列表项   │ │   结构化表格   │                │
│  └──────────────┘ └──────────────┘ └──────────────┘                │
│  ┌──────────────┐ ┌──────────────┐ ┌──────────────┐                │
│  │ 📦 批量字段   │ │ 🔤 正则提取   │ │ 🔁 翻页循环   │                │
│  │   详情页字段   │ │ 从文本抽取    │ │   下一页按钮   │                │
│  └──────────────┘ └──────────────┘ └──────────────┘                │
│  ┌──────────────┐ ┌──────────────┐                                  │
│  │ 🔽 滚动加载   │ │ 🛑 条件终止   │                                  │
│  │    无限滚动   │ │  终止规则配置   │                                  │
│  └──────────────┘ └──────────────┘                                  │
│                                                                       │
│    [取消]   [下一步 → 参数配置 → 生成步骤]                            │
└────────────────────────────────────────────────────────────────────────┘
```

---

## 5. 字段映射规则、方案版本管理、历史兼容方案

### 5.1 字段映射（零代码）

保留 `field_mapping` 步骤类型，增强：

```python
# T32 扩展：支持 alias + transform + 清洗
config = {
    "map": {
        "title": "title",
        "publish_time": "publish_time",
        "body": "content",
        "source_url": "_source_url",
    },
    "transforms": [
        {"field": "publish_time", "op": "date_format", "target": "%Y-%m-%d"},
        {"field": "body", "op": "strip_html"},
        {"field": "title", "op": "truncate", "params": {"length": 200}},
    ],
}
```

前端配置面板以「点击即绑定」交互：

- 左侧展示 **已拾取元素**列表（点击元素时入此列表）
- 右侧展示 **标准字段模板**（title / publish_time / body / source_url / attachments）
- 中间拖拽连线或点击「绑定」按钮完成映射

### 5.2 方案版本管理

新增 API 与服务：

```
POST   /api/admin/crawl/plans/{plan_id}/versions        保存当前配置为历史版本
GET    /api/admin/crawl/plans/{plan_id}/versions        列出版本列表
GET    /api/admin/crawl/plans/{plan_id}/versions/{vid}  读取版本内容
POST   /api/admin/crawl/plans/{plan_id}/versions/{vid}/rollback  回退到指定版本
POST   /api/admin/crawl/plans/{plan_id}/versions/{vid}/restore   恢复为当前（不覆盖 current）
```

**存储**：在 `web_admin.api.crawl_config` 中新增 `plan_versions` 表（或复用 T26 已有方案表 + 单独的 versions 表存储 JSON diff）

```python
# plan_versions 表 schema
{
    "version_id":   "v_{plan_id}_{unix_ts}_{idx}",
    "plan_id":      int,
    "title":        "手动保存 / {auto_message}",
    "rule_config":  Dict[str, Any],       # 完整 rule_config 快照（JSON 存储）
    "steps_package": Optional[Dict],       # 可选：步骤化快照
    "created_at":   "2024-07-09T10:30:00Z",
    "operator":     "admin",
}
```

**自动版本**：每次调用 `update_plan_api` 成功后自动保存旧版为 version，保留最近 20 个版本，超出自动清除。

### 5.3 历史兼容（T32 强约束）

- 旧版 `CrawlRuleSet`（list_rule + detail_rule + schedule_config）与新版 StepsPackage 并存
- `CompatConverter.convert()` 已在 T31 实现，T32 扩展为可处理 14 种 step_type
- 保存时仍然通过 `StepAssembler.build_rule_config()` 组装为 T25 兼容的 rule_config，保证 T26 方案管理不受影响
- 新增的 `command_*` 步骤在 `build_rule_config` 中被**聚合到** `list_rule.extra_steps` 字段（list 结构，底层按需执行）
- 若 T25 引擎不识别 extra_steps，忽略之，不影响原有逻辑

---

## 6. 分步执行开发流程（共 9 阶段）

### 阶段 1：扩展 step_models（step_type 常量 + 标签）
- 修改 `business/custom_spider/step_models.py`
- 在 `STEP_TYPES` 中追加 8 种 `command_*`
- 在 `STEP_TYPE_LABELS` 中追加对应中文标签
- 修改 `StepConfig.__post_init__` 的合法性检查，允许新 step_type

**预计改动**：1 个文件，新增约 20 行

### 阶段 2：新增 command_library 指令库
- 新增 `business/custom_spider/command_library.py`
- 实现 `class Command + Base + 8 种 subclass`
- 实现 `run()` 方法：纯 Python（bs4 / re）实现数据变换，不调用底层网络抓取
- 实现 `to_step_config()` 生成标准化参数 dict

**预计改动**：1 个文件，约 400 行

### 阶段 3：扩展 step_service（StepAssembler + StepTester + CompatConverter）
- 修改 `StepAssembler.build_rule_config`：识别 `command_*` 类型步骤，聚合到 `list_rule.extra_steps`（JSON list）
- 修改 `StepTester`：为 8 种指令类型添加 `_test_command_{name}` 方法
- 修改 `CompatConverter.convert`：在旧 rule_config → steps 过程中，若原 list_rule 存在 `pagination.max_pages > 1`，自动生成 `command_pagination_loop` 步骤
- 在 step_service 中增加 `version_service.save_version / list_versions / rollback` 方法（纯 API 级别逻辑）

**预计改动**：1 个文件，修改约 200 行

### 阶段 4：API 路由扩展
- 修改 `web_admin/api/crawl_config.py`，追加以下路由（**不修改原有路由**）：
  - `GET /crawl/steps/commands` → 返回指令库元数据（name/label/schema）
  - `POST /crawl/steps/command-test` → 单步指令测试
  - `POST /crawl/steps/{plan_id}/versions` → 保存版本
  - `GET /crawl/steps/{plan_id}/versions` → 列出版本
  - `GET /crawl/steps/{plan_id}/versions/{version_id}` → 读取版本内容
  - `POST /crawl/steps/{plan_id}/versions/{version_id}/rollback` → 回退
  - `POST /crawl/steps/full-test-incremental` → 增量测试（只测新添加步骤）

**预计改动**：1 个文件，追加约 280 行

### 阶段 5：重写 crawl_step_editor.html（三栏布局 + 浏览器面板）
- 完全重写 `web_admin/templates/partials/crawl_step_editor.html`
- 采用 **iframe + 高亮层**结构，右侧步骤面板上下拆分
- 保持原来的顶部操作栏逻辑，但按钮逻辑改为调用新 API
- 增加**指令插入弹窗**（.command-modal）
- 增加 **模式切换按钮**（浏览 / 拾取 / 录制）

**预计改动**：1 个文件，重写约 350 行

### 阶段 6：重写前端 JS（交互逻辑 + 录制 + 拖拽 + 智能指令）
- 扩展 `crawl_step_editor.js`：
  - iframe 脚本注入（元素事件拦截 → postMessage）
  - 高亮层实现（CSS 绝对定位 + JS 计算位置）
  - 模式切换逻辑（3 种模式）
  - 事件 → 步骤生成（匹配规则 §3.3）
  - 步骤拖拽排序（HTML5 drag/drop）
  - 步骤禁用/启用/重放
  - 步骤详情面板动态表单
  - 增量测试按钮
  - localStorage 草稿持久化增强（含版本号）

**预计改动**：1 个文件，从现有 ~600 行扩展到 ~1500 行

### 阶段 7：CSS 样式增补
- 在 `admin.css` 末尾追加：
  - `.crawl-step-body` 改为 `grid` 布局（左 60% + 右 40%）
  - `.crawl-step-browser / .crawl-step-highlight` 样式（iframe、遮罩层）
  - `.steps-list` 与 `.step-detail-panel` 上下栏样式（带分隔条）
  - `.command-modal` 弹窗样式
  - 响应式宽度调整（拖拽分隔条）

**预计改动**：1 个文件，追加约 180 行

### 阶段 8：pages.py 路由注册
- 在 `web_admin/pages.py` 中：
  - 确认 `/admin/crawl/steps-editor` 路由存在（T31 已加）
  - 无需新路由，但注入新的 `script src` 指向最新 JS 路径（加 `?v=t32` 缓存版本号）

**预计改动**：1 个文件，1~2 行（cache-busting）

### 阶段 9：测试与回归
- 在 `tests/test_t32_step_editor.py`（**新增文件**）中：
  - 单元测试：14 种 step_type 的 config 序列化/反序列化
  - 单元测试：8 种指令的 `run()` 基本逻辑
  - 集成测试：`StepAssembler.build_rule_config` 在包含 `command_*` 时输出合法 rule_config
  - 集成测试：`CompatConverter.convert` 对旧版 rule_config 生成合法 StepsPackage
  - 冒烟测试：`/crawl/steps/commands` / `/{plan_id}/versions` 等新 API 返回 2xx
- 人工测试：浏览器端验证三栏布局、元素高亮、录制功能、指令插入、版本保存/回退

**预计改动**：1 个新文件，约 400 行；需运行测试确保通过

### 执行依赖图

```
阶段 1 (step_models) ─┐
                      ├──► 阶段 3 (step_service) ──┐
阶段 2 (command_lib) ─┘                            │
                      ┌────────────────────────────┘
                      ▼
阶段 4 (API 路由) ──► 阶段 8 (路由注册)
                      │
                      ▼
阶段 5 (HTML) ──────► 阶段 6 (JS) ──► 阶段 7 (CSS)
                        │
                        ▼
                      阶段 9 (测试/回归)
```

> **策略**：阶段 1-4（后端模型/服务/API）与阶段 5-7（前端）**可并行开发**。阶段 8-9 最后完成。

---

## 7. 风险与应对策略

| 风险 | 可能性 | 影响 | 应对策略 |
|---|---|---|---|
| Playwright 依赖体积大，Docker 镜像构建慢 | 中 | 构建时间 | 已在 T11/T25 时期引入；复用现有 Dockerfile，不新增依赖安装步骤 |
| iframe `srcdoc` 中脚本注入被浏览器 CSP 拦截 | 高 | 录制失效 | 使用同源 `srcdoc`（无跨域）；若仍拦截，改为页面内 JS 注入后渲染 |
| 选择器生成不稳定（依赖 nth-child） | 高 | 重放时选择器命中错误 | 提供 3 种选择器策略（class优先 > id > nth-child）并允许人工编辑 |
| 旧 CrawlRuleSet 升级丢失分页配置 | 中 | 历史方案不可用 | CompatConverter 检测 `list_rule.pagination.max_pages > 1` 自动生成 pagination_loop |
| 指令步骤在 T25 引擎不可被识别导致数据丢失 | 中 | 新配置在旧引擎失效 | 所有 `command_*` 在 `build_rule_config` 中附加到 `extra_steps` 字段；引擎端忽略未识别字段不崩溃 |
| 隐私信息未脱敏显示 | 低 | 合规风险 | 复用 `step_service._mask_any()` 对所有步骤测试输出做统一脱敏，测试用的 sample_data 也同样走脱敏 |
| 用户误删关键步骤 | 低 | 步骤丢失 | 高危操作（删除/覆盖）二次确认；+ 草稿自动保存（5 秒防抖） |

---

## 8. 文件与模块改动清单

| 文件 | 动作 | 类型 | 说明 |
|---|---|---|---|
| `business/custom_spider/step_models.py` | 扩展 | 修改 | 8 种 command_* step_type |
| `business/custom_spider/command_library.py` | 新增 | 文件 | 8 种指令的 run / trigger / to_step_config |
| `business/custom_spider/step_service.py` | 扩展 | 修改 | StepAssembler/StepTester/CompatConverter 升级 + version 服务 |
| `business/custom_spider/smart_detector.py` | 不变 | - | 直接复用 |
| `web_admin/api/crawl_config.py` | 扩展 | 修改 | 7 条新路由（指令元数据 + 版本管理 + 增量测试） |
| `web_admin/templates/partials/crawl_step_editor.html` | 重写 | 修改 | 三栏布局 + 浏览器画布 + 指令弹窗 |
| `web_admin/static/js/crawl_step_editor.js` | 扩展 | 修改 | 浏览器事件监听、录制、拖拽、智能指令 |
| `web_admin/static/css/admin.css` | 扩展 | 修改 | 新三栏布局 + 高亮层 + 弹窗样式 |
| `web_admin/pages.py` | 扩展 | 修改 | 确认 `/admin/crawl/steps-editor` 路由存在 + script 版本号 |
| `tests/test_t32_step_editor.py` | 新增 | 文件 | 14 种 step_type 单元测试 + 指令运行 + API 冒烟 |
