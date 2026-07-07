# 定制化采集配置手册

> 适用版本：BizTools4Openclaw v1.0.0+（T25/T26/T27 集成）
> 适用角色：super_admin / ops
> 文档日期：2026-07-08

---

## 一、快速开始

### 1.1 能力概览

定制采集（Custom Crawl）能力覆盖三个主要阶段：

```
  可视化配置      规则执行      数据消费
 ────────────   ───────────   ───────────
  页面点选字段   自动列表抓取  入库原始数据
  列表/详情分页  内容字段提取  T10 清洗流水线
  附件 PDF 解析  PDF/OCR 解析  商机自动生成
  字段映射规则   增量去重      分配销售跟进
  启停定时调度   异常告警       ← 运营看板
```

### 1.2 权限矩阵

| 角色 | 方案管理 | 可视化配置 | 手动执行 | 查看结果 |
|---|---|---|---|---|
| super_admin | ✅ 完全控制 | ✅ | ✅ | ✅ |
| ops | ✅ 编辑/启停 | ✅ | ✅ | ✅ |
| sales | ❌ | ❌ | ❌ | ✅ 仅本渠道 |
| viewer | ❌ | ❌ | ❌ | ✅ 只读 |

**操作说明**：后台登录 → 顶部菜单「📂 采集方案管理」进入首页。

---

## 二、采集方案管理

### 2.1 新建方案

1. 进入「采集方案管理」页面
2. 点击右上角「+ 新建方案」
3. 填写基础信息：

| 字段 | 必填 | 说明 |
|---|---|---|
| 方案名称 | ✅ | 简短描述，如「工信部APP违规通报采集」 |
| 目标网址 | ✅ | 列表页 URL（需可公开访问） |
| 采集类型 | ✅ | 公告/新闻/公示/政务通知 |
| 数据来源 | ✅ | 用于数据看板过滤 |
| 执行周期 | ✅ | 手动 / 每小时 / 每天 / 每周 / 自定义 Cron |
| 分页深度 | ✅ | 翻页最大页数，默认 5 |
| 启用状态 | - | 新建时默认启用 |

### 2.2 字段配置

**预设字段模板**（系统内置，不可删除）：

| 模板名称 | 包含字段 | 适用场景 |
|---|---|---|
| 政务通告 | 标题 / 发布日期 / 发布机构 / 正文 / 附件链接 | 政府公告、政策通知 |
| 企业公示 | 企业名称 / 统一社会信用代码 / 公示日期 / 事由 / 处理结果 | 企业注册、变更公告 |
| 违规通报 | 主体名称 / 违规类型 / 违规内容 / 处理措施 / 公告日期 | 行政处罚、监管通报 |

**自定义字段**操作：
1. 在「字段模板库」页面点击「+ 新增字段」
2. 配置字段名、数据类型（text/date/number/url）、清洗规则
3. 保存后即可在任意方案的字段映射中选用

### 2.3 方案克隆/导入导出

- **克隆**：在方案列表点击「克隆」，生成包含相同规则的新方案
- **导出**：单方案导出 JSON 文件，包含完整规则配置
- **导入**：上传 JSON 文件，自动创建新方案（需验证规则兼容性）
- **批量操作**：支持多选方案同时启用/禁用/删除

---

## 三、可视化配置编辑器

### 3.1 五步流程

```
  Step 1          Step 2          Step 3           Step 4         Step 5
┌─────────┐   ┌─────────┐   ┌───────────┐   ┌──────────┐   ┌──────────┐
│ 目标URL │ → │ 列表字段 │ → │ 详情字段  │ → │ 附件解析 │ → │ 保存验证 │
│ 预览渲染 │   │ 点选配置 │   │ 自动解析  │   │ PDF/OCR  │   │ 测试采集 │
└─────────┘   └─────────┘   └───────────┘   └──────────┘   └──────────┘
```

### 3.2 Step 1: URL 与页面预览

1. 在编辑器顶部输入目标列表页 URL
2. 点击「预览页面」，调用 T25 引擎渲染
3. 预览区显示完整 HTML 页面（脚本已自动消毒）
4. 页面加载成功后进入下一步

**常见问题**：

| 现象 | 原因 | 解决 |
|---|---|---|
| 预览空白 | 页面需 JS 渲染但 JS 被禁用 | 在引擎规则中启用 JS 渲染 |
| 预览 403 | 目标站点反爬拦截 | 检查目标 robots.txt，合规性校验提示 |
| 预览超时（>30s） | 目标站点响应慢 | 调整引擎超时配置，或减少并发 |

### 3.3 Step 2: 列表字段点选

**操作方式**：
1. 在预览页面中，鼠标点击要采集的元素
2. 系统自动生成 CSS 选择器并显示提取结果
3. 在下拉框中将选择器映射到字段（标题 / 发布时间 / 详情链接等）

**配置分页规则**：
1. 点击分页导航中的「下一页」按钮
2. 系统识别翻页模式（页码参数 / URL 模板）
3. 设置最大翻页数（建议 5-20，根据实际情况）

### 3.4 Step 3: 详情页字段

1. 从列表页点击任意详情链接
2. 详情页自动加载预览
3. 同样方式点选配置详情页字段
4. 预览验证：点击「测试提取」查看单条记录效果

### 3.5 Step 4: 附件解析

当详情页中检测到附件链接（PDF/图片）时：

1. 系统自动高亮所有可解析附件
2. 开启「附件解析」开关
3. 配置附件字段映射：
   - PDF：自动提取标题/正文/表格内容
   - 图片：启用 OCR 识别文字（需环境配置，见附录 A）
4. 上传样例文件验证解析效果

### 3.6 Step 5: 保存与验证

1. 点击「保存方案」
2. 系统自动执行一次**测试采集**（最多抓取 3 条样例）
3. 显示测试结果：字段命中、提取质量、耗时
4. 若失败率过高，返回优化规则
5. 确认无误后方案可正式启用

---

## 四、规则优化技巧

### 4.1 选择器优化原则

1. **优先使用 ID/Class**：`#article-title` > `.news-list .item > a`
2. **避免绝对层级**：不要用 `body > div:nth-child(3) > ...`
3. **使用属性选择器**：如 `[data-field="title"]`
4. **可配置项优先**：对站点不稳定的选择器抽象为可编辑参数

**坏示例**（易失效）：
```css
body > div.main > section:nth-child(2) > div > a:nth-child(5)
```

**好示例**（稳定）：
```css
.news-list .item a[href*="/detail/"]
```

### 4.2 文本清洗规则

| 问题 | 配置项 | 效果 |
|---|---|---|
| 多余空白 | trim + collapse_whitespace | `"\n 标题\n"` → `"标题"` |
| HTML 残留 | strip_html_tags | 自动移除标签 |
| 日期格式混乱 | normalize_date | `"2026/07/08"` → `"2026-07-08"` |
| 数字提取 | extract_number | `"罚款 5000 元"` → `"5000"` |
| 敏感信息 | mask_sensitive | 自动脱敏手机号/邮箱/身份证 |

### 4.3 提升匹配准确率

- **字段不为空率**：核心字段（标题/日期）应 >95%
- **翻页中止条件**：遇到空页或重复内容时自动停止
- **规则版本管理**：每次修改保存新版本，可一键回滚
- **告警阈值**：设置字段命中率 <70% 时自动告警

---

## 五、采集策略与增量去重

### 5.1 定时调度配置

| 周期 | 表达式示例 | 适用场景 |
|---|---|---|
| 每小时 | `0 * * * *` | 高频更新的动态新闻 |
| 每天 9:00 | `0 9 * * *` | 政务公告、日报类 |
| 每周一 10:00 | `0 10 * * 1` | 周报、周度公示 |
| 自定义 | `30 2,14 * * 1-5` | 工作日 2:30 + 14:30 |

### 5.2 增量去重机制

- **基于 URL**：相同 URL 不重复抓取（默认）
- **基于字段哈希**：指定字段值相同判定为重复
- **基于日期范围**：指定日期前的历史数据跳过
- **Redis 存储**：去重状态持久化，重启不丢失
- **TTL**：默认 30 天自动清理过期记录

### 5.3 执行监控

在「采集任务监控」页面查看：

- 最近执行记录：时间/状态/耗时/抓取数量
- 趋势图表：最近 7 天抓取量趋势
- 告警列表：规则失效/匹配率低/连接失败
- 任务详情：点击查看执行日志、失败原因

---

## 六、合规与安全

### 6.1 robots.txt 校验

- **默认强制启用**：所有方案在采集前校验目标站点 robots.txt
- 若 `Disallow` 包含目标路径，采集任务自动跳过并记录日志
- 如需调整，在方案设置中配置（super_admin 可覆盖，操作留痕）

### 6.2 敏感信息脱敏

系统自动处理以下敏感内容：
- **手机号**：`138****5678`（大陆手机号正则）
- **邮箱**：`u***@example.com`（保留首字母和域名）
- **身份证号**：`110101********1234`（隐藏出生日期部分）

### 6.3 操作审计

- 所有方案的创建/编辑/删除/启停自动记录操作日志
- 日志包含：操作人/角色/时间/IP/变更前后快照
- 日志保留期限：180 天（可配置）
- 高危操作（删除/启用覆盖 robots）需二次确认

---

## 七、与现有自动化流水线的兼容性

定制采集方案的数据完全复用 T10 清洗流水线：

```
┌──────────────────┐    ┌──────────────────┐    ┌──────────────────┐
│ T27 可视化配置    │ →  │ T26 方案 + 调度  │ →  │ 原始爬虫数据表  │
│ (人工定义规则)    │    │ (规则执行/日志)  │    │ (source=custom)  │
└──────────────────┘    └──────────────────┘    └────────┬─────────┘
                                                          ↓
                                                   ┌──────────────────┐
                                                   │ T10 清洗流水线   │
                                                   │ (字段标准化)     │
                                                   └────────┬─────────┘
                                                          ↓
                                                   ┌──────────────────┐
                                                   │ 商机数据管理     │
                                                   │ (分配/跟进)       │
                                                   └──────────────────┘
```

**与 T18/T19 自动化爬虫的区别**：

| 维度 | 自动化爬虫 | 定制采集 |
|---|---|---|
| 规则来源 | 代码内置，开发维护 | 运营可视化配置 |
| 适用场景 | 已接入合作渠道 | 长尾/临时/特殊站点 |
| 变更速度 | 依赖开发排期 | 即时生效 |
| 稳定性 | 高（代码覆盖测试） | 依赖人工规则质量 |

---

## 八、常见问题 FAQ

### Q1：页面预览显示正常，但采集不到数据？

**可能原因**：
- 目标站点返回了不同内容（UA/IP 不同）
- 页面动态加载但未启用 JS 渲染
- 选择器过于脆弱（依赖不稳定的 class 名）

**排查步骤**：
1. 检查采集日志中的页面 HTML 是否与预期一致
2. 开启「JS 渲染」重试
3. 简化选择器，使用更稳定的属性

### Q2：采集到了数据，但字段都是空的？

检查字段映射：详情页字段选择器是否与实际页面匹配。
站点改版后 HTML 结构可能变化，需重新点选配置。

### Q3：PDF 附件解析失败？

1. 确认目标 PDF 可公开下载（非登录保护）
2. 检查 PDF 文件是否为扫描件：若是需启用 OCR（见附录 A）
3. 确认文件大小 < 20MB，过大文件可能超时

### Q4：OCR 识别准确率低？

- 确保图片分辨率 >= 300 DPI
- 对中文内容，确保已安装中文语言包（`chi_sim`）
- 倾斜/模糊图片会降低识别率

### Q5：Redis 不可达会影响采集吗？

不会。系统设计了降级方案：
- Redis 正常 → 使用 Redis 去重 + 持久化
- Redis 不可达 → 自动降级为进程内内存去重
- 重启后去重状态丢失，但不影响新数据采集

### Q6：如何回滚到之前的规则版本？

1. 进入「方案详情」→「版本历史」
2. 找到要回滚的版本，点击「回滚到此版本」
3. 系统自动保存当前规则为新版本，再应用所选版本
4. 操作全程记录，可追溯

### Q7：采集耗时过长怎么办？

优化建议：
- 减小分页深度（如从 20 → 10）
- 配置并发数（默认 2，可提高到 5）
- 调整调度时间至目标站点低峰期
- 如目标站点反爬严重，考虑降低频率/使用代理（需合规）

---

## 附录 A：OCR 环境配置

**注意**：以下为可选配置，影响 PDF 图片扫描件的识别能力。

### A.1 Tesseract 安装

```bash
# Ubuntu/Debian
apt-get install tesseract-ocr tesseract-ocr-chi-sim

# macOS
brew install tesseract tesseract-lang

# Windows 下载安装包
# https://github.com/UB-Mannheim/tesseract/wiki
```

### A.2 Poppler 安装（PDF 处理依赖）

```bash
# Ubuntu/Debian
apt-get install poppler-utils

# macOS
brew install poppler

# Windows 下载解压后添加到 PATH
# https://github.com/oschwartz10612/poppler-windows/releases
```

### A.3 环境变量配置

在 `.env` 或 Docker Compose 配置中：

```dotenv
# OCR 开关（true/false）
CRAWL_OCR_ENABLED=true

# Tesseract 可执行文件路径（Windows 需明确指定）
CRAWL_OCR_TESSERACT_PATH=/usr/bin/tesseract

# PDF 转图片临时目录
CRAWL_PDF_TEMP_DIR=/tmp/crawl_pdf

# OCR 语言（简体中文+英文）
CRAWL_OCR_LANGUAGES=chi_sim+eng
```

---

## 附录 B：API 接口速查

### 方案管理

| 方法 | 路径 | 说明 |
|---|---|---|
| GET | `/admin/api/crawl/plans` | 方案列表 |
| POST | `/admin/api/crawl/plans` | 新建方案 |
| PUT | `/admin/api/crawl/plans/{id}` | 更新方案 |
| DELETE | `/admin/api/crawl/plans/{id}` | 删除方案 |
| POST | `/admin/api/crawl/plans/{id}/clone` | 克隆方案 |
| POST | `/admin/api/crawl/plans/{id}/enable` | 启用定时 |
| POST | `/admin/api/crawl/plans/{id}/disable` | 禁用定时 |
| POST | `/admin/api/crawl/plans/{id}/run` | 立即执行 |
| POST | `/admin/api/crawl/plans/{id}/test` | 测试运行（3 条） |
| GET | `/admin/api/crawl/plans/{id}/export` | 导出 JSON |
| POST | `/admin/api/crawl/plans/import` | 导入 JSON |

### 预览与解析

| 方法 | 路径 | 说明 |
|---|---|---|
| POST | `/admin/api/crawl/preview/render` | 渲染页面 HTML |
| POST | `/admin/api/crawl/preview/selector` | 验证 CSS 选择器 |
| POST | `/admin/api/crawl/preview/attachment` | 解析附件样例 |

### 监控与字段

| 方法 | 路径 | 说明 |
|---|---|---|
| GET | `/admin/api/crawl/runs` | 执行记录列表 |
| GET | `/admin/api/crawl/runs/{id}` | 执行详情 |
| GET | `/admin/api/crawl/fields/templates` | 预设字段模板 |
| GET | `/admin/api/crawl/fields/custom` | 自定义字段列表 |
| POST | `/admin/api/crawl/fields/custom` | 新增自定义字段 |
| PUT | `/admin/api/crawl/fields/custom/{id}` | 更新自定义字段 |
| DELETE | `/admin/api/crawl/fields/custom/{id}` | 删除自定义字段 |

---

## 附录 C：典型配置示例

### C.1 政务公告采集

```json
{
  "name": "XX市政务公告采集",
  "list_url": "https://www.example.gov.cn/news/",
  "pagination": {
    "type": "page_param",
    "param_name": "page",
    "max_pages": 5
  },
  "fields": {
    "title": {
      "selector": ".news-list .item h3 a",
      "clean_rules": ["trim", "collapse_whitespace"]
    },
    "publish_date": {
      "selector": ".news-list .item .date",
      "clean_rules": ["normalize_date"]
    },
    "detail_url": {
      "selector": ".news-list .item h3 a",
      "attribute": "href"
    }
  },
  "detail_fields": {
    "content": {
      "selector": "#article-content"
    },
    "source": {
      "selector": ".article-source"
    }
  },
  "schedule": "0 9 * * *",
  "dedup_mode": "url"
}
```

### C.2 企业公示采集

```json
{
  "name": "企业异常名录公示",
  "list_url": "https://example.gsxt.gov.cn/abnormal/",
  "fields": {
    "company_name": { "selector": ".company" },
    "credit_code": { "selector": ".credit-code" },
    "reason": { "selector": ".reason" },
    "publish_date": { "selector": ".pub-date", "clean_rules": ["normalize_date"] }
  },
  "schedule": "0 10 * * 1",
  "dedup_mode": "field",
  "dedup_fields": ["company_name", "credit_code"]
}
```

### C.3 含 PDF 附件的违规通报

```json
{
  "name": "行政处罚决定书",
  "list_url": "https://example.gov.cn/punish/",
  "attachments": {
    "enabled": true,
    "pdf": {
      "extract_text": true,
      "extract_tables": true,
      "ocr_enabled": true
    }
  },
  "schedule": "0 14 * * *",
  "dedup_mode": "url"
}
```

---

## 附录 D：故障排查清单

| 现象 | 检查项 | 预期状态 |
|---|---|---|
| ✅ 方案保存失败 | `/var/log/app.log` 中搜索 `custom_spider` | 应有明确错误提示 |
| ✅ 采集不到数据 | 任务监控 → 查看执行日志 | 检查是否 robots 拒绝 |
| ✅ 字段都是空 | 查看选择器，与页面 HTML 比对 | 选择器应命中 |
| ✅ 定时任务不执行 | 检查 enable 状态 + scheduler 日志 | 下次执行时间应显示 |
| ✅ Redis 报错 | `redis-cli ping` 或 Docker 容器状态 | 返回 PONG |
| ✅ 权限不足 | 检查账号角色，ops 应有 edit 权限 | 操作不受限 |

---

## 更新日志

| 版本 | 日期 | 更新内容 |
|---|---|---|
| 1.0.0 | 2026-07-08 | 首版发布，覆盖 T25/T26/T27 全量功能操作指引 |
