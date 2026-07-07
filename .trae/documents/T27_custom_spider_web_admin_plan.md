# T27 可视化采集配置中心开发计划

**目标**: 在 web_admin 中新增「采集配置中心」模块，提供方案管理、可视化字段点选、预览测试、任务监控的完整交互能力。

**约束边界**:
- 禁止修改：README.md、DEVELOP_RULES.md、docs/TASK_LIST.md
- 禁止修改：business/custom_spider、core/spider_core 核心逻辑
- 仅允许：新增 web_admin 页面路由、API 接口、JS 脚本（可能修改 menu.py 注册菜单、api/__init__.py 注册 router、pages.py 注册页面）
- 所有采集/解析/方案操作 100% 调用 T25/T26 底层接口

---

## 一、页面菜单结构与路由清单

### 1.1 菜单结构（新增到 menu.py 的 MENU_GROUPS）

在「采集管理」分组中新增 3 个菜单项（与「爬虫任务」并列）：

```
group_key: "collection", title: "采集管理"
  ├── 现有：spider (爬虫任务) / 7 个子渠道
  │
  ├── ✨ 新增：crawl_plans     (采集方案管理)       href: /admin/crawl/plans
  ├── ✨ 新增：crawl_editor    (可视化配置编辑器)    href: /admin/crawl/editor
  ├── ✨ 新增：crawl_monitor   (采集任务监控)       href: /admin/crawl/monitor
  └── ✨ 新增：crawl_fields    (字段模板库)         href: /admin/crawl/fields
```

每个菜单项 roles = {"super_admin", "ops"}

### 1.2 页面路由清单（新增到 pages.py）

| 路由 | 对应页面 | 说明 |
|------|---------|------|
| `GET /admin/crawl/plans` | 方案管理列表页 | 展示所有方案，支持筛选/操作 |
| `GET /admin/crawl/editor` | 可视化配置编辑器（5步向导） | 新建 / 编辑方案核心页面，?plan_id=xxx 区分 |
| `GET /admin/crawl/monitor` | 采集任务监控页 | 运行状态 / 执行日志 / 采集结果 / 告警 |
| `GET /admin/crawl/fields` | 字段模板库管理页 | 预设字段 + 自定义字段 CRUD |

### 1.3 API 路由清单（新增 web_admin/api/crawl_config.py）

所有接口前缀：`/crawl/*`，响应格式统一 `{code, msg, data}`

| 方法 | 路由 | 功能 | 底层调用 |
|------|------|------|---------|
| GET | `/crawl/plans` | 方案列表（支持 status/keyword 筛选） | PlanService.list_plans() |
| POST | `/crawl/plans` | 新建方案（仅保存基础信息 + 规则） | PlanService.create_plan() |
| PUT | `/crawl/plans/{plan_id}` | 更新方案 | PlanService.update_plan() |
| POST | `/crawl/plans/{plan_id}/clone` | 克隆方案 | PlanService.clone_plan() |
| DELETE | `/crawl/plans/{plan_id}` | 删除方案（软删除） | PlanService.delete_plan() |
| POST | `/crawl/plans/{plan_id}/enable` | 启用调度 | PlanService.enable_schedule() |
| POST | `/crawl/plans/{plan_id}/disable` | 停用调度 | PlanService.disable_schedule() |
| POST | `/crawl/plans/{plan_id}/run` | 立即执行一次 | PlanService.run_plan_now() |
| POST | `/crawl/plans/{plan_id}/test` | 测试运行（单 URL 快速验证） | PlanService.test_plan() |
| GET | `/crawl/plans/{plan_id}/export` | 导出方案配置（JSON） | PlanService.export_plan() |
| POST | `/crawl/plans/import` | 导入方案配置 | PlanService.import_plan() |
| GET | `/crawl/plans/{plan_id}/detail` | 获取方案详情 | PlanService.get_plan() |
| **===== 页面渲染 & 预览 =====** | | | |
| POST | `/crawl/preview/render` | URL 页面预渲染（返回 HTML 快照 + 可交互元素清单） | T25 SmartPageRenderer.render() |
| POST | `/crawl/preview/analyze` | 智能分析页面元素（返回列表块候选、标题、附件等） | T25 PageAnalyzer.analyze() |
| POST | `/crawl/preview/selector` | 鼠标点击 → 生成 CSS 选择器 + 校验提取结果 | 前端点击位置 + T25 提取器验证 |
| POST | `/crawl/preview/attachment` | 附件解析预览（PDF/图片） | T25 AttachmentParser |
| **===== 任务监控 =====** | | | |
| GET | `/crawl/runs` | 运行记录列表 | PlanService.list_runs() |
| GET | `/crawl/runs/{run_id}` | 运行记录详情 | PlanService.get_run_detail() |
| GET | `/crawl/plans/{plan_id}/stats` | 方案统计（累计采集量、成功率、告警） | PlanService.get_plan_stats() |
| **===== 字段模板库 =====** | | | |
| GET | `/crawl/fields/templates` | 获取三类预设字段模板 | 读取 T25 预设模板 |
| GET | `/crawl/fields/custom` | 获取自定义字段库 | DB 查询 |
| POST | `/crawl/fields/custom` | 新增自定义字段 | DB Insert |
| PUT | `/crawl/fields/custom/{field_id}` | 更新自定义字段 | DB Update |
| DELETE | `/crawl/fields/custom/{field_id}` | 删除自定义字段 | DB Delete |

---

## 二、可视化配置编辑器 — 五步交互流程设计

### 2.1 页面布局总览

```
┌─────────────────────────────────────────────────────────────────────────────┐
│ 📋 步骤导航栏（5 步 + 进度条）                                                │
│ [① URL与渲染] → [② 列表配置] → [③ 详情配置] → [④ 附件映射] → [⑤ 保存调度] │
├─────────────────────────────────────────────────────────────────────────────┤
│ ← 左侧步骤配置区        │ 右侧页面预览区（iframe/div 内嵌 HTML）              │
│                          │                                                     │
│  [当前步骤表单]         │  🔍 页面可视化预览                                 │
│                          │  🖱 点击元素 → 生成选择器 + 高亮                 │
│                          │  📊 实时提取结果预览                              │
│                          │  ✏ 手动编辑选择器                                │
├─────────────────────────────────────────────────────────────────────────────┤
│ ← 上一步 / 保存草稿 / 下一步 → / 测试运行（仅在②③④⑤可用）                  │
└─────────────────────────────────────────────────────────────────────────────┘
```

### 2.2 五步详细交互

**Step ① URL 输入与页面预渲染**

```
输入框：目标网站列表页 URL（必填，含 placeholder 示例）
复选框：□ 启用 JavaScript 动态渲染（默认关，可能较慢但动态页面必需）
按钮：【预览页面】

用户点击【预览页面】：
  → POST /api/admin/crawl/preview/render
     payload: {"url": "...", "render_js": true/false}
  → 后端调用 T25:
     SmartPageRenderer.render(url, render_js=...)
  → 返回: {
      "final_url": "...",
      "html_preview": "<base64 encoded HTML>",   // 取前 200KB
      "clickable_elements": [{"selector": "...", "tag": "a/div/button", "text": "..."}],
      "elapsed_ms": 1234
    }
  → 前端把 html_preview 注入右侧预览 iframe/div
  → 为 iframe 内所有元素注册 click 拦截（用于 Step ②③）
```

**Step ② 列表页字段配置**

```
左侧表单：
  ├── 列表块选择器（手动输入 或 👉 在预览区点击列表容器）
  ├── 列表项选择器（点击列表中任一条目，自动推断 li/article/xxx 选择器）
  ├── 字段配置（每个字段一行，点击预览区元素自动填充）：
  │   ├── 字段名（下拉：标题 / 发布时间 / 详情链接 / 附件链接 / 自定义）
  │   ├── 选择器（自动填充，可手动编辑）
  │   ├── 提取方式（CSS / XPath / 正则）
  │   └── 清洗规则（去空白 / 去换行 / 日期格式化 / 数字提取）
  │
  ├── 分页规则：
  │   ├── 模式（下一页按钮 / URL 页码参数 / 页码按钮）
  │   ├── 选择器 / 参数名
  │   └── 最大翻页数（默认 20）
  │
  └── [实时预览提取结果] 按钮 → 显示当前配置下提取的前 10 条

右侧预览区交互：
  ├── 用户点击页面中的标题 → 前端自动生成 CSS selector
  ├── 前端调用 POST /crawl/preview/selector
  ├── 后端用选择器在同页面 HTML 上校验提取结果（最多 5 条样本）
  ├── 返回: {"selector": "...", "samples": [...], "match_count": 12}
  ├── 前端在右侧下方显示实时提取结果表格 + 匹配数量高亮
```

**Step ③ 详情页字段配置**

```
进入步骤：
  Step ② 必须配置了「详情链接」字段 → 否则提示并禁止进入

左侧表单：
  ├── [已预填] 详情链接字段（来自 Step ②）
  ├── 字段配置（同行 Step ②，支持字段模板下拉）：
  │   ├── 字段名（下拉：标题 / 发布时间 / 正文 / 作者 / 来源 / 附件 / 自定义）
  │   ├── 选择器（点击预览区自动填充）
  │   ├── 提取方式 + 清洗规则
  │   └── 必填（勾选则采集失败时标记错误）
  │
  └── 附件解析开关（进入 Step ④ 的条件）

右侧预览区：
  ├── 自动加载第一条详情（从 Step ② 提取的首个链接）
  ├── 点击元素 → 选择器生成 → 校验提取结果
  └── 检测到的附件链接以特殊高亮显示（蓝色边框 + 📎 图标）
```

**Step ④ 附件内容字段映射**

```
进入条件：Step ③ 开启了「附件解析」开关

左侧表单：
  ├── 附件类型选择（多选：PDF / 图片 / Word / Excel）
  ├── 字段映射：
  │   ├── 目标字段名（来自前面步骤配置的结构化字段）
  │   ├── 映射规则（下拉：全文 / 指定段落 / 指定表格行列 / 正则提取）
  │   └── 样例文本（用于测试）
  │
  └── PDF 解析配置（仅在启用 PDF 时显示）：
      └── 表格识别（开启/关闭）
      └── 图片 OCR（开启/关闭）
      └── 只取前 N 页（默认全部）

右侧预览区：
  ├── 自动下载第一个附件样例（来自 Step ③ 检测到的附件链接）
  ├── 调用 POST /crawl/preview/attachment
  ├── 显示 PDF 文本 / 表格 / OCR 结果
  └── 点击文本/表格单元格 → 自动生成正则规则
```

**Step ⑤ 保存与调度配置**

```
左侧表单（最终确认）：
  ├── 方案基础信息：
  │   ├── 方案名称（必填）
  │   ├── 站点域名（自动从 URL 提取，可编辑）
  │   ├── 采集类型（下拉：政务通告 / 企业公示 / 违规通报 / 通用）
  │   └── 描述
  │
  ├── 调度配置：
  │   ├── 调度开关（是否启用自动执行）
  │   ├── 执行周期（下拉：每日 / 每周 / Cron 表达式自定义）
  │   └── [Cron 表达式输入框]（当选择自定义时显示）
  │
  ├── 增量 & 去重：
  │   ├── 去重方式（URL / 唯一字段）
  │   └── 仅采集最近 N 天数据（可选）
  │
  └── Cookie / Header（可选，加密存储）：
      └── [输入框] 粘贴浏览器 Cookie（用于需登录站点）

底部操作栏：
  ├── [测试运行] 按钮（快速验证，采集前 5 条）
  ├── [保存为草稿] 按钮（status = draft）
  └── [保存并启用] 按钮（status = active + 注册调度）

高危操作二次确认：
  保存并启用 → 弹出确认框：「确认启用调度？将按照配置周期自动执行采集」
  删除方案 → 弹出确认框：「确认删除此方案？所有运行记录将被保留」
```

---

## 三、字段点选与选择器生成 — 前端实现逻辑

### 3.1 前端 Click-to-Selector 核心算法

```javascript
// 1. 监听预览 iframe 内的点击事件
// 2. 根据点击元素生成唯一 CSS selector
// 3. 校验选择器在页面中的匹配数量
// 4. 高亮所有匹配元素

function buildCssSelector(element) {
  // 向上遍历 DOM 直到找到有 id 或 class 的稳定锚点
  // 优先使用 id (#xxx) > 具有唯一 class 的 div > 标签名 + :nth-child
  // 算法：element → parent → parent... 直到 document.body
  // 每级：优先 tag#id, 其次 tag.class[attr=value], 最后 tag:nth-child(n)
  
  const parts = [];
  let el = element;
  while (el && el.nodeType === 1 && el.tagName !== 'BODY' && parts.length < 8) {
    let part = el.tagName.toLowerCase();
    // 有 id 则用 id（停止向上）
    if (el.id) {
      parts.unshift(part + '#' + CSS.escape(el.id));
      break;
    }
    // 有唯一 class 则用 class
    if (el.className && typeof el.className === 'string'
        && el.className.trim() && !el.className.includes(' ')) {
      const matches = el.parentElement.querySelectorAll(part + '.' + el.className);
      if (matches.length === 1) {
        parts.unshift(part + '.' + el.className);
        el = el.parentElement;
        continue;
      }
    }
    // 使用 nth-child
    const siblings = el.parentElement ? el.parentElement.children : [el];
    let idx = 1;
    for (let i = 0; i < siblings.length; i++) {
      if (siblings[i] === el) { idx = i + 1; break; }
    }
    parts.unshift(part + ':nth-child(' + idx + ')');
    el = el.parentElement;
  }
  return parts.join(' > ');
}

function highlightBySelector(selector, container) {
  // 给所有匹配元素加蓝色虚线边框 + 背景高亮
  // 3 秒后自动清除
  const matches = container.querySelectorAll(selector);
  matches.forEach(m => {
    m.style.outline = '2px dashed #2196f3';
    m.style.backgroundColor = 'rgba(33, 150, 243, 0.1)';
    setTimeout(() => {
      m.style.outline = '';
      m.style.backgroundColor = '';
    }, 3000);
  });
  return matches.length;
}
```

### 3.2 选择器简化与泛化（提高命中率）

```
原始点击选择器可能太具体：
  div.page-main > article:nth-child(3) > h3 > a.title-link

需要泛化：保留有语义的部分，去掉 nth-child 等位置依赖：
  article h3 a.title-link      ← 更通用

泛化策略：
  1. 保留 id 选择器
  2. 保留包含 title/name/date/time/article/entry/class: 等语义关键词的 class
  3. 如果 class 是随机字符串（如 hash），降级为 nth-child
  4. 把过长的 selector 压缩到 4-5 级
  5. 匹配多个元素时，自动替换位置为 :nth-of-type(n)
  6. 提供手动编辑选择器 + 「测试匹配」按钮
```

### 3.3 点击区域与字段类型自动推断

```
根据点击元素的特征自动推断字段类型：
  - element.tagName === 'A' → 可能是「详情链接」或「附件链接」
  - element.href 包含 .pdf/.docx/.xlsx/.jpg/.png → 「附件链接」
  - element 内文本匹配日期正则 → 「发布时间」
  - element.tagName 在 H1/H2/H3/H4/H5/H6 内 → 「标题」
  - element 有 img 子元素 → 「图片」
  - 元素内文本较长（> 50 字） → 「正文」
  - 元素位于列表项内（Step ② 配置的 item_selector 子元素）→ 字段为列表页字段
  - 元素不在列表项内 → 字段为详情页字段
```

---

## 四、预览、测试、保存全链路接口设计

### 4.1 预览流程时序图

```
用户                web_admin API          T25 Engine
 │                      │                    │
 │──输入 URL, 点击预览─▶│                    │
 │                      │──POST render──────▶│
 │                      │  {url, render_js}  │
 │                      │  ← HTML + elements─│
 │◀──渲染预览 + 可点击─ │                    │
 │                      │                    │
 │──点击标题元素───────▶│                    │
 │ (selector生成逻辑)  │──POST selector─────▶│
 │                      │  {url, selector}   │
 │                      │  ← 匹配样本数据────│
 │◀──显示提取结果表格─ │                    │
 │                      │                    │
 │──完成字段配置, 测试▶│                    │
 │                      │──POST test────────▶│
 │                      │  {完整配置}        │
 │                      │  ← 采集5条结果─────│
 │◀──显示测试结果 ─────│                    │
 │                      │                    │
 │──保存方案──────────▶│                    │
 │                      │──写入 DB + 调度────▶│
 │◀──方案创建成功 ─────│                    │
```

### 4.2 统一响应格式

所有 API 统一响应格式（参考现有 spider_task.py）：

```json
{
  "code": 0,           // 0=成功，非0=错误
  "msg": "操作成功",     // 成功信息 / 错误信息
  "data": { ... }       // 响应数据（JSON 对象）
}
```

**核心接口详细设计**:

#### 接口 1: `POST /crawl/preview/render` — 页面预渲染
```
Request:
{
  "url": "https://example.com/news",
  "render_js": false
}

Response:
{
  "code": 0,
  "msg": "ok",
  "data": {
    "final_url": "https://example.com/news",
    "html_preview": "<html>...<base64>",   // 前 200KB HTML，剥离 <script>
    "clickable_elements": [
      {"selector": "a.title-link", "tag": "a", "text": "新闻标题"},
      {"selector": "li.item:nth-child(1)", "tag": "li", "text": "..."},
      ...
    ],
    "elapsed_ms": 1842,
    "error": null
  }
}
```

#### 接口 2: `POST /crawl/preview/selector` — 选择器校验
```
Request:
{
  "page_html": "<html>...</html>",   // 可选；若省略则用 url 重新请求
  "url": "https://example.com/news",
  "selector": "li.item h3 a.title-link",
  "extractor": "css" | "xpath" | "regex",
  "sample_limit": 5
}

Response:
{
  "code": 0,
  "msg": "ok",
  "data": {
    "selector": "li.item h3 a.title-link",
    "match_count": 20,
    "samples": ["新闻标题1", "新闻标题2", "新闻标题3", "新闻标题4", "新闻标题5"],
    "suggest_simplify": "li.item a.title-link"  // 简化版 selector 建议
  }
}
```

#### 接口 3: `POST /crawl/plans/{plan_id}/test` — 测试运行
```
Request:
{
  "test_url": "https://example.com/news?page=1",   // 可选
  "max_items": 5
}

Response:
{
  "code": 0,
  "msg": "ok",
  "data": {
    "status": "completed",
    "items_total": 5,
    "items_success": 4,
    "field_match_rate": 0.95,
    "elapsed_ms": 8423,
    "items": [
      {"title": "...", "publish_time": "...", "detail_url": "...", ...},
      ...
    ],
    "alerts": [
      {"level": "warning", "message": "字段 publish_time 缺失 1 条"},
      ...
    ]
  }
}
```

---

## 五、新增文件清单

### 5.1 页面层（web_admin/）

| 文件 | 预估行数 | 职责 |
|------|---------|------|
| `web_admin/pages.py` (修改) | +200行 | 新增 4 个页面路由函数（plans/editor/monitor/fields） |

### 5.2 API 层（web_admin/api/）

| 文件 | 预估行数 | 职责 |
|------|---------|------|
| `web_admin/api/crawl_config.py` (新增) | 600 | 方案 CRUD / 预览渲染 / 选择器校验 / 运行监控 / 字段模板库 |
| `web_admin/api/__init__.py` (修改) | +5行 | 注册 crawl_config_router |

### 5.3 前端脚本（web_admin/static/js/）

| 文件 | 预估行数 | 职责 |
|------|---------|------|
| `web_admin/static/js/crawl_editor.js` (新增) | 800 | 5步编辑器主逻辑：步骤切换 / 选择器生成 / 字段配置 / 测试预览 / 保存 |
| `web_admin/static/js/crawl_plans.js` (新增) | 300 | 方案管理列表页：筛选 / 操作 / 导入导出 |
| `web_admin/static/js/crawl_monitor.js` (新增) | 300 | 任务监控页：运行状态 / 日志 / 结果查看 / 告警显示 |
| `web_admin/static/js/crawl_fields.js` (新增) | 200 | 字段模板库管理 |
| `web_admin/static/js/admin.js` (修改) | +50行 | 新增 crawl_xxx 页面的初始加载逻辑（根据 active_key） |

### 5.4 样式（web_admin/static/css/）

| 文件 | 预估行数 | 职责 |
|------|---------|------|
| `web_admin/static/css/admin.css` (修改) | +150行 | 编辑器两列布局 / 步骤导航 / 元素高亮 / 预览区样式 |

### 5.5 菜单配置（web_admin/）

| 文件 | 预估行数 | 职责 |
|------|---------|------|
| `web_admin/menu.py` (修改) | +30行 | 在「采集管理」分组中新增 4 个菜单项 |

### 5.6 总计

- **新增文件**: 5 个 (crawl_config.py + 4 个 JS 文件)
- **修改文件**: 4 个 (pages.py / api/__init__.py / admin.js / admin.css / menu.py)
- **新增代码**: ~2600 行
- **无侵入修改**: 所有修改为 append-only（在现有文件末尾追加）

---

## 六、分步执行开发流程

### Phase 1: 基础骨架（页面路由 + 菜单注册）
1. 修改 `menu.py`：在「采集管理」分组追加 4 个菜单项
2. 修改 `pages.py`：追加 4 个页面路由（空壳页面，仅显示标题 + "开发中"）
3. 修改 `api/__init__.py`：预注册 `crawl_config_router` 占位
4. 冒烟测试：访问 `/admin/crawl/plans` → 确认菜单显示 + 页面可访问

### Phase 2: 方案管理列表页
1. 新增 `crawl_config.py`：实现方案 CRUD + 启停 + 克隆 + 导入导出 API
2. 新增 `crawl_plans.js`：列表页渲染 + 筛选 + 操作按钮绑定
3. 修改 `pages.py`：完善方案管理页 HTML 结构（表格 + 筛选栏 + 操作按钮）
4. 测试：浏览器访问页面 → 创建/编辑/删除方案 → API 响应正确

### Phase 3: 可视化配置编辑器（核心）
1. 修改 `pages.py`：实现 editor 页 HTML 结构（5步导航 + 左右两列布局）
2. 新增 `crawl_editor.js`：实现步骤导航切换 / 状态管理 / 表单数据聚合
3. 实现 Step ① URL 预渲染：对接 `POST /crawl/preview/render`
4. 实现 Click-to-Selector：前端算法 + 高亮 + 选择器校验
5. 实现 Step ② 列表页字段配置 + Step ③ 详情页字段配置
6. 实现 Step ④ 附件配置（若有） + Step ⑤ 保存与调度
7. 测试：模拟 URL → 完整 5 步流程 → 成功保存方案

### Phase 4: 任务监控页
1. 修改 `pages.py`：实现 monitor 页 HTML 结构
2. 新增 `crawl_monitor.js`：运行记录列表 / 详情查看 / 采集结果表格
3. 实现告警高亮：字段匹配率 < 80% 黄色；< 50% 红色；有采集失败红色闪烁
4. 测试：执行一个方案 → 监控页显示运行记录 + 结果

### Phase 5: 字段模板库页
1. 修改 `pages.py`：实现 fields 页 HTML 结构
2. 新增 `crawl_fields.js`：预设字段展示 / 自定义字段 CRUD
3. 修改 `crawl_config.py`：实现字段模板库 API（本地 JSON 或轻量 DB）
4. 测试：新增/编辑/删除自定义字段 → 在编辑器中可选用

### Phase 6: 整合与回归测试
1. 修改 `admin.js`：根据 active_key 加载对应页面脚本
2. 修改 `admin.css`：补充新页面样式
3. 全流程测试：
   - 从 0 开始创建方案 → 可视化配置 → 测试运行 → 保存启用 → 监控查看
   - 方案克隆 → 编辑差异 → 保存新版本
   - 方案导入导出 → JSON 文件往返
   - 删除方案 → 二次确认弹窗正常
4. 权限测试：ops 角色可见/操作；非 ops 角色无法看到菜单

---

## 七、关键设计决策

### 7.1 页面渲染方式
- **方案**：纯 Python 字符串拼接 HTML（遵循 pages.py 既有风格），而非引入前端框架
- **理由**：与现有架构一致，零新增依赖，代码风格统一

### 7.2 预览 HTML 安全策略
- `<script>` 标签全部剥离（防止目标站点 JS 执行）
- `<iframe>` / `<frame>` 移除
- `onclick/onload` 内联事件移除
- 链接 `target="_blank"` 强制添加 `rel="noopener noreferrer"`
- 预览区域使用独立 div（非 iframe），避免 JS 注入风险

### 7.3 敏感信息处理
- Cookie 字段：不在前端展示，只在后端与数据库间加密传递
- 采集结果中的手机号/身份证/邮箱：自动脱敏显示（138****5678）

### 7.4 操作日志
- 所有修改/删除/启停操作自动记录到 `custom_spider_operation_logs` 表
- 由 T26 PlanService 层负责（web_admin 只调用接口，不直接写日志）

### 7.5 前端数据状态管理
- 方案配置数据在编辑器全程存在 `window.__crawlPlanDraft`
- 每步切换自动校验完整性（缺失字段提示）
- 离开页面 / 未保存提示："您有未保存的修改，确定离开吗？"

---

## 八、风险与处理

| 风险 | 概率 | 影响 | 处理方案 |
|------|------|------|---------|
| 目标站点页面动态 JS 内容无法预览 | 中 | 部分元素无法点击选择 | 提供「启用 JS 渲染」开关（可选 + 明确提示耗时）；失败时降级为原始 HTML |
| 选择器命中率低（泛化过度或不足） | 中 | 采集结果与预览不符 | 提供手动编辑；支持多候选建议；测试运行对比 |
| 大附件解析超时 | 低 | 页面阻塞 | 附件解析异步执行，前端显示进度条 + 超时取消 |
| cookie 明文被泄露到 logs | 低 | 安全风险 | cookie 字段前端不回显明文；后端加密存储；接口层日志过滤 |
| 权限绕过 | 极低 | 非 ops 人员操作 | 所有 API 调用 `require_admin`（role in {super_admin, ops}） |
| 浏览器兼容性（点击选择器） | 低 | 部分浏览器交互异常 | 使用原生 DOM API；降级为「手动输入选择器」模式 |

---

## 九、开发输出物验收标准

| 检查项 | 通过标准 |
|--------|---------|
| 菜单注册 | 登录后左侧导航栏显示「采集方案管理/可视化配置编辑器/采集任务监控/字段模板库」 |
| 方案管理页 | 方案列表正常加载；新建/编辑/克隆/启停/测试/删除/导入导出按钮可用 |
| 配置编辑器 | 5步流程正常流转；URL 输入 → 预览渲染 → 字段点击选择 → 保存 |
| 字段点击 | 点击预览区元素 → 自动填充选择器 + 显示匹配样本；可手动编辑 |
| 测试运行 | 点击测试 → 10 秒内返回结果（或合理超时 + 错误提示） |
| 任务监控 | 执行后运行记录可查询；结果展示为表格；告警高亮 |
| 字段模板库 | 三类预设字段展示；自定义字段 CRUD 可用 |
| 权限隔离 | 非 super_admin/ops 角色看不到菜单；访问 API 返回 403 |
| 操作日志 | 所有修改/删除/启停操作可在 operation_logs 表查到记录 |
| 合规脱敏 | 采集结果中手机号/邮箱等自动脱敏 |
