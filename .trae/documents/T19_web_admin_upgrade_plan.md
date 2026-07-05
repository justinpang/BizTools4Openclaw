# T19 · 全渠道差异化采集任务管理模块开发计划

> 基于 T18 后台底座 + T09 爬虫业务能力开发。纯框架/页面层，不修改底层爬虫业务代码。

---

## 一、7 大渠道表单字段清单

> 通用参数（所有渠道共享：`task_name`（任务名）、`speed_level`（速度档位：1-5）、`max_items`（采集上限）、`schedule_mode`（定时开关：off/daily/hourly）、`cron_expression`（Cron 表达式）、`time_range`（时间范围）

### 1. 通用网页/论坛（channel_key = `generic_web`）
- 渠道参数：
  - `site_type`：站点类型（网页门户/论坛/BBS）
  - `keywords`：关键词列表
  - `max_depth`：抓取深度（1-5）
  - `extract_rules`：抽取规则(JSON)
  - `url_template`：URL 模板

### 2. 短视频（channel_key = `short_video`）
- `platform`：平台（抖音/快手/视频号/TikTok）
- `keywords`：关键词列表
- `region`：地域过滤
- `min_likes`：最小点赞数
- `min_comments`：最小评论数

### 3. 小红书（channel_key = `xhs`）
- `platform`：平台（固定 xhs）
- `keywords`：关键词列表
- `post_type`：内容类型（笔记/视频/全部）
- `region`：城市筛选
- `min_likes`：最小点赞数

### 4. 问答平台（channel_key = `qa_platform`）
- `platform`：平台（知乎/百度知道/悟空问答）
- `keywords`：关键词列表
- `min_answers`：最小回答数
- `min_views`：最小浏览数
- `filter_rule`：过滤规则(JSON)

### 5. 供需 B2B（channel_key = `b2b_supply`）
- `platform`：平台（阿里巴巴/慧聪/中国供应商）
- `keywords`：关键词列表
- `region`：地域过滤
- `industry`：行业过滤
- `filter_price`：价格筛选(JSON)

### 6. 招投标（channel_key = `bidding`）
- `platform`：平台（政府采购/公共资源交易/企业采购）
- `keywords`：关键词列表
- `region`：地域过滤
- `bid_type`：招标类型（招标公告/中标公告/变更公告）
- `publish_days`：发布天数(0-30)

### 7. 企业工商（channel_key = `company_biz`）
- `platform`：平台（企查查/天眼查/爱企查/工商公示)
- `company_keywords`：公司名关键词
- `region`：地域过滤
- `industry`：行业过滤
- `registered_capital_min`：注册资本下限(万元)
- `establishment_years`：成立年限(0+)

---

## 二、任务状态枚举与流转规则

| 状态 code | 中文标签 | 说明 |
|---|---|---|
| `DRAFT` | 待审核 | 刚创建尚未启动 |
| `READY` | 待启动 | 已审核，可启动 |
| `RUNNING` | 运行中 | 正在执行 |
| `PAUSED` | 已暂停 | 用户点击暂停 |
| `COMPLETED` | 已完成 | 执行完毕 |
| `FAILED` | 已失败 | 执行失败（可重试） |
| `TERMINATED` | 已终止 | 手动终止（不可恢复） |

### 流转规则

```
DRAFT ── (审核通过) ──> READY
READY ── (启动) ──> RUNNING
RUNNING ── (暂停) ──> PAUSED
PAUSED ── (继续) ──> RUNNING
RUNNING ── (执行完毕) ──> COMPLETED
RUNNING ── (出错/风控) ──> FAILED
RUNNING ── (终止) ──> TERMINATED
READY / FAILED ── (删除) ──> (删除

补充：FAILED 可"重试"从上次中断位置继续（断点续爬）
```

### 操作按钮（按当前状态显示）
- **DRAFT**：[编辑] [启动] [删除]
- **READY**：[启动] [编辑] [删除]
- **RUNNING**：[暂停] [终止] [查看日志]
- **PAUSED**：[继续] [终止] [删除]
- **COMPLETED**：[查看明细] [删除]
- **FAILED**：[重试（断点续爬）] [删除]
- **TERMINATED**：[删除]

---

## 三、页面布局设计

### 3.1 采集任务总览页（/admin/spider）
布局：筛选区（渠道/状态/时间） → 任务列表 → 新建任务入口（7 大渠道）

**字段列表**：
- 任务 ID、渠道类型（图标化）、任务名称、运行状态、采集总数、失败数、创建时间、操作
- 操作按钮

**操作列** 按钮（按状态/权限过滤，缺省隐藏）

### 3.2 任务详情与实时监控页（/admin/spider/{job_id}）
布局：顶部面包屑 + 任务基础配置（只读）
- **配置**：配置项（只读）
- **采集进度条**：成功 / 失败 / 风控拦截数量统计
- **原始数据采集明细列表**：分页展示，含用户信息/联系方式脱敏
- **任务运行日志区**：日志列表，实时刷新按钮，支持按关键字过滤

---

## 四、底层接口对接映射

| 页面/操作 | 调用底层接口（T09） | 权限 |
|---|---|---|
| 任务列表 | `GET /api/admin/spider/tasks` | `btn.spider.view` |
| 创建任务 | `POST /api/admin/spider/task` | `btn.spider.create` |
| 启动任务 | `POST /api/admin/spider/task/{id}/run` | `btn.spider.run` |
| 暂停任务 | `POST /api/admin/spider/task/{id}/pause` | `btn.spider.pause` |
| 继续任务 | `POST /api/admin/spider/task/{id}/resume` | `btn.spider.resume` |
| 终止任务 | `POST /api/admin/spider/task/{id}/terminate` | `btn.spider.terminate` |
| 重试任务 | `POST /api/admin/spider/task/{id}/retry` | `btn.spider.retry` |
| 删除任务 | `DELETE /api/admin/spider/task/{id}` | `btn.spider.delete` |
| 任务详情 | `GET /api/admin/spider/task/{id}` | `btn.spider.view` |
| 采集明细 | `GET /api/admin/spider/task/{id}/items` | `btn.spider.view_items` |
| 日志 | `GET /api/admin/spider/task/{id}/logs` | `btn.spider.view` |
| 风控告警 | `GET /api/admin/spider/risks` | `btn.spider.view` |

说明：
- 所有高危操作（启动/暂停/终止/删除/重试）自动写入操作日志（`middleware.py` 已实现）。
- 所有采集数据用户信息/联系方式自动脱敏（前端 `admin.ui.autoMask` 实现）。
- 所有渠道参数、阈值配置 **不硬编码限制**，完全透传底层接口。

---

## 五、分步开发执行流程

### Phase 1：权限与菜单注册（低风险）
1. 扩展 `web_admin/auth.py` 角色权限矩阵：补充 `btn.spider.run / pause / resume / terminate / retry / view_items` 等按钮级权限（新增权限标识 7 个）
2. 扩展 `web_admin/menu.py`：调整 `MENU_GROUPS` 中的采集管理分组，补充 7 个渠道的子项（active_key 区分，href 跳转到新页面 /admin/spider）
3. 扩展 `web_admin/pages.py`：补充新页面路由（详情页 /admin/spider/{job_id}）
4. 验证 pages.py 中调整 role_can_view_menu(role, active_key) 补充新 active_key 的可见性映射

### Phase 2：页面模板与组件样式

1. 扩展 `web_admin/pages.py`：
   - 现有 spider_page 改造：新增**渠道筛选栏**（7 大渠道图标卡片式选择）
   - 新增 `spider_detail_page(job_id)`：任务详情+监控页面（只读配置区、进度条、原始数据列表、日志区）
2. 扩展 `web_admin/static/css/admin.css`：
   - 新增 `.channel-filter-row` 渠道筛选行（渠道卡片、任务状态图标标签）
   - 新增 `.task-detail-progress` 进度条样式
   - 新增 `.task-detail-config` 只读配置样式
   - 新增 `.spider-item-table` 原始数据表格样式
   - 新增 `.spider-logs` 日志区样式
3. 扩展 `web_admin/static/js/admin.js`：
   - 新增 `admin.loadSpiderDetail(job_id)`、`admin.pauseTask(job_id)` 等操作函数（前端交互）
   - 新增 `admin.runTask(job_id)` 与 retry 操作、terminate 操作

### Phase 3：API 封装（无）
1. 扩展 `web_admin/api/spider_task.py`：
   - 新增 `POST /spider/task` 中新增 7 个渠道表单字段（关键词、地域、阈值、采集数 → JSON 化存储）
   - 新增 `GET /spider/task/{id}` 详情接口
   - 新增 `POST /spider/task/{id}/terminate` 终止接口
   - 新增 `POST /spider/task/{id}/retry` 重试接口（断点续爬）
   - 新增 `GET /spider/task/{id}/items` 采集明细接口（含页码）
   - 增强 `list_spider_tasks` 过滤：支持按渠道、状态、时间筛选

### Phase 4：前端交互与权限

1. `web_admin/static/js/admin.js`：
   - `admin.createSpiderTask(event)` 改造为**动态渠道字段表单**渲染
   - 新增 `admin.loadSpiderDetail(job_id)`、`admin.terminateTask`、`admin.retryTask`
   - 采集明细列表（items 自动脱敏）、实时刷新按钮
   - 按钮级权限过滤（`applyPermission`）

### Phase 5：自测与验证

1. **页面路由与菜单可见性**：7 大渠道角色可见性是否正确
2. **按钮级权限**：无权限角色不显示按钮
3. **高危操作日志**：所有启停操作是否自动记录到操作日志
4. **脱敏**：原始数据采集字段是否正确脱敏
5. **原始数据分页**：分页加载是否正常
6. **断点续爬**：失败任务点击重试后，从上次中断位置继续
7. **任务状态流转**：状态切换是否符合规则

---

## 六、变更文件清单（严格遵循"仅修改/新增 web_admin 目录"）

| 文件 | 操作 | 说明 |
|---|---|---|
| `web_admin/auth.py` | 修改 | 扩展权限矩阵 |
| `web_admin/menu.py` | 修改 | 调整采集管理分组 |
| `web_admin/pages.py` | 修改 | 新增任务详情页面路由 |
| `web_admin/api/spider_task.py` | 修改 | 7 大渠道字段 + 新增详情/终止/重试/明细接口 |
| `web_admin/static/css/admin.css` | 修改 | 新页面组件样式 |
| `web_admin/static/js/admin.js` | 修改 | 新页面交互与 API 调用 |

共 **6 个文件**，**0 新增文件**，不涉及业务爬虫代码。
