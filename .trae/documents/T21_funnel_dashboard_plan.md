# T21 开发计划：全链路 6 阶段化管控看板

> 基于 T18 后台底座、T01~T12 全链路业务数据开发，仅新增数据展示页面。
> 严格遵循 DEVELOP_RULES.md：分层约束、复用底层接口、不侵入业务逻辑。

---

## 1. 代码库调研结论

### 1.1 现有页面框架
- **文件**: `web_admin/pages.py`
- **布局引擎**: `_layout_v2(title, active_key, body_html, session)` 统一渲染
- **菜单系统**: `web_admin/menu.py` — `MENU_GROUPS` 分组菜单 + `role_can_view_menu()` 权限过滤
- **权限体系**: `web_admin/auth.py` — 4 角色（super_admin/ops/sales/compliance）+ 按钮级 `btn.xxx.yyy` 权限标识

### 1.2 现有数据接口（全部可复用）
| 阶段 | 现有 API | 返回数据结构 |
|------|---------|-----------|
| 采集阶段 | `GET /api/admin/spider/tasks` + `GET /api/admin/spider/task/{job_id}/items` | 任务列表 + 采集明细（含 channel/created_at/status/raw_payload 脱敏字段）|
| 清洗结构化 | `GET /api/admin/leads` + `GET /api/admin/leads/{lead_id}` | 清洗后线索（含 status/channel/score/company/contact 脱敏字段）|
| 合规校验 | 复用 `business.data_clean.storage` 查询接口 + `core.compliance.pii_detect` 逻辑 | 是否包含敏感字段、合规报告、风险等级 |
| 商机分级 | 复用 `business.sales_task.registry` + scoring engine | 商机等级（A/B/C/D）、意向评分、标签、归属渠道 |
| 客户触达 | 复用 `business.customer_send.registry.list_runs()` + `api/sales_mgmt.py` 接口 | 触达批次、发送渠道、成功/失败数、目标客户、发送时间 |
| 销售闭环 | `GET /api/admin/sales/persons` + `assignments` + `followups` + `overdue` | 商机分配记录、跟进记录、最终状态（成交/流失/待跟进）|

### 1.3 现有漏斗统计
- `GET /api/admin/dashboard/stats` 已做基础计数（spider_tasks/crawled_total/leads_total/send_total/accounts_total/funnel）
- 需扩展为 6 阶段维度化统计（按渠道/时间/状态筛选）

### 1.4 角色与权限矩阵
| 角色 | 可读阶段 | 可看明文权限 |
|------|---------|-----------|
| super_admin | 全部 6 阶段 | 是 |
| ops | 采集/清洗/合规 | 否（需申请）|
| sales | 商机分级/客户触达/销售闭环 | 否（需申请）|
| compliance | 合规校验 | 否（需申请）|

---

## 2. 6 个阶段各自的汇总指标与明细字段清单

### 阶段 1：采集阶段 (Collection)
**页面路由**: `/admin/data_center/collection`

**汇总卡片指标**:
| 指标 | 数据来源 | 说明 |
|------|---------|------|
| 任务总数 | `spider:task:*` Redis key 计数 | 所有已创建的采集任务数 |
| 已完成任务数 | spider_task meta.status=COMPLETED | 成功执行完毕的任务 |
| 采集成功率 | completed / (completed + failed) | 百分比 |
| 待处理任务数 | status=READY/PENDING_APPROVAL/RUNNING | 当前可执行或正在执行的任务 |
| 异常任务数 | status=FAILED/TERMINATED/REJECTED | 需要关注的异常状态 |
| 采集记录总数 | `spider:crawled:*` 或 `meta.success` 累计 | 所有任务的抓取条目总和 |

**明细列表字段** (分页, page_size=20):
| 字段 | 类型 | 说明 | 脱敏 |
|------|------|------|------|
| job_id | string | 任务 ID | 否 |
| task_name | string | 任务名称 | 否 |
| channel | string | 渠道类型（7 大来源之一） | 否 |
| created_by | string | 创建人 | 否 |
| created_at | datetime | 创建时间 | 否 |
| last_run_at | datetime | 最近执行时间 | 否 |
| status | enum | DRAFT/READY/RUNNING/PAUSED/COMPLETED/FAILED/TERMINATED/PENDING_APPROVAL/REJECTED | 否 |
| success | int | 成功抓取条数 | 否 |
| failed | int | 失败条数 | 否 |
| compliance_status | enum | OK/REVIEW_REQUIRED/HIGH_RISK | 否 |

---

### 阶段 2：清洗结构化 (Cleaning)
**页面路由**: `/admin/data_center/cleaning`

**汇总卡片指标**:
| 指标 | 数据来源 | 说明 |
|------|---------|------|
| 原始条目总数 | leads storage total | 所有清洗过的原始数据量 |
| 结构化完成数 | status=APPROVED | 通过审核的结构化商机 |
| 清洗成功率 | approved / total | 百分比 |
| 待审核线索数 | status=PENDING | 等待人工审核的线索 |
| 异常/丢弃数 | status=REJECTED/DUPLICATE/INVALID | 丢弃的低质量数据 |

**明细列表字段** (分页, page_size=20):
| 字段 | 类型 | 说明 | 脱敏 |
|------|------|------|------|
| lead_id | string | 线索 ID | 否 |
| title | string | 商机标题 | 否 |
| channel | string | 来源渠道 | 否 |
| source_job_id | string | 来源采集任务 ID | 否 |
| company | string | 公司名称 | 否 |
| contact | string | 联系人 | 是（姓名中间字打码）|
| phone | string | 联系电话 | 是（138****1234）|
| email | string | 邮箱 | 是（a***@***.com）|
| status | enum | PENDING/APPROVED/REJECTED | 否 |
| structured_fields | object | 结构化字段（职位/需求/预算等） | 部分脱敏 |
| created_at | datetime | 采集时间 | 否 |
| cleaned_at | datetime | 清洗时间 | 否 |

---

### 阶段 3：合规校验 (Compliance)
**页面路由**: `/admin/data_center/compliance`

**汇总卡片指标**:
| 指标 | 数据来源 | 说明 |
|------|---------|------|
| 已校验总数 | 所有 lead 已通过合规检查的条数 |
| 合规通过数 | compliance_status=OK |
| 合规通过率 | OK / 已校验总数 | 百分比 |
| 待复核数 | compliance_status=REVIEW_REQUIRED |
| 高风险拦截数 | compliance_status=HIGH_RISK |

**明细列表字段** (分页, page_size=20):
| 字段 | 类型 | 说明 | 脱敏 |
|------|------|------|------|
| lead_id | string | 线索 ID | 否 |
| title | string | 商机标题 | 否 |
| channel | string | 来源渠道 | 否 |
| pii_detected | string | 检测到的 PII 类型（phone/email/idcard/wechat 等） | 部分脱敏 |
| compliance_score | float | 合规评分（0-100） | 否 |
| risk_level | enum | LOW/MEDIUM/HIGH/CRITICAL | 否 |
| compliance_status | enum | OK/REVIEW_REQUIRED/HIGH_RISK | 否 |
| masked_fields | list | 已脱敏字段列表 | 否 |
| verified_at | datetime | 合规校验时间 | 否 |

---

### 阶段 4：商机分级 (Opportunity Grading)
**页面路由**: `/admin/data_center/grading`

**汇总卡片指标**:
| 指标 | 数据来源 | 说明 |
|------|---------|------|
| 商机总数 | 已通过合规 + 清洗的 APPROVED 线索数 |
| A 级商机数 | grade=A (高意向/明确预算/紧急需求) |
| B 级商机数 | grade=B |
| C 级商机数 | grade=C |
| D 级商机数 | grade=D (信息不足/低价值) |
| 平均意向分 | 评分引擎输出 | 0-100 分 |

**明细列表字段** (分页, page_size=20):
| 字段 | 类型 | 说明 | 脱敏 |
|------|------|------|------|
| lead_id | string | 商机 ID | 否 |
| title | string | 商机标题 | 否 |
| channel | string | 来源渠道 | 否 |
| grade | enum | A/B/C/D | 否 |
| score | float | 综合评分 0-100 | 否 |
| budget | string | 预算区间 | 否 |
| urgency | enum | LOW/MEDIUM/HIGH | 否 |
| intent_tags | list | 意向标签（如「采购决策人」「明确需求」「近期意向」） | 否 |
| industry | string | 行业分类 | 否 |
| contact | string | 联系人 | 是 |
| phone | string | 联系电话 | 是 |
| graded_at | datetime | 分级时间 | 否 |

---

### 阶段 5：客户触达 (Outreach)
**页面路由**: `/admin/data_center/outreach`

**汇总卡片指标**:
| 指标 | 数据来源 | 说明 |
|------|---------|------|
| 触达批次总数 | customer_send.registry.list_runs().total |
| 成功触达客户数 | 批次中成功发送数累计 |
| 触达成功率 | 成功数 / 目标客户总数 | 百分比 |
| 待发送任务数 | pending 状态的触达计划 |
| 失败/重试数 | failed 状态 + 重试队列 |

**明细列表字段** (分页, page_size=20):
| 字段 | 类型 | 说明 | 脱敏 |
|------|------|------|------|
| run_id | string | 触达批次 ID | 否 |
| source_lead_id | string | 关联商机 ID | 否 |
| channel | enum | email/wechat/feishu | 否 |
| target_count | int | 目标客户数 | 否 |
| success_count | int | 成功数 | 否 |
| fail_count | int | 失败数 | 否 |
| status | enum | PENDING/RUNNING/COMPLETED/FAILED | 否 |
| sent_at | datetime | 发送时间 | 否 |
| response_status | enum | OPENED/REPLIED/NO_RESPONSE | 否（如数据可用）|

---

### 阶段 6：销售闭环 (Sales Closing)
**页面路由**: `/admin/data_center/sales`

**汇总卡片指标**:
| 指标 | 数据来源 | 说明 |
|------|---------|------|
| 跟进中商机数 | opportunity status=FOLLOWING |
| 已成交数 | status=WON |
| 成交率 | WON / (WON + LOST) | 百分比 |
| 流失数 | status=LOST |
| 逾期未跟进数 | overdue API count |

**明细列表字段** (分页, page_size=20):
| 字段 | 类型 | 说明 | 脱敏 |
|------|------|------|------|
| person_id / lead_id | string | 商机 ID | 否 |
| title | string | 商机标题 | 否 |
| company | string | 公司名称 | 否 |
| contact | string | 联系人 | 是 |
| phone | string | 电话 | 是 |
| assignee | string | 分配销售 | 否 |
| grade | enum | A/B/C/D | 否 |
| status | enum | NEW/FOLLOWING/NO_RESPONSE/WON/LOST | 否 |
| last_followup_at | datetime | 最近跟进时间 | 否 |
| next_followup_at | datetime | 下次跟进时间 | 否 |
| followup_count | int | 累计跟进次数 | 否 |
| close_value | float | 成交金额（如有） | 否 |
| closed_at | datetime | 成交/流失时间 | 否 |

---

## 3. 全链路漏斗计算逻辑与数据来源

### 3.1 漏斗层级定义
```
漏斗 6 层级转化：
┌──────────────────────────────────────┐
│ 1. 采集量 (Crawled)                  │ ← spider:crawled 累计
├──────────────────────────────────────┤
│ 2. 有效线索 (Valid Leads)            │ ← leads storage total - REJECTED
├──────────────────────────────────────┤
│ 3. 合规通过商机 (Compliant Opportunities) │ ← compliance_status=OK 且 status=APPROVED
├──────────────────────────────────────┤
│ 4. 客户触达 (Outreached)             │ ← 已发送过触达消息的 lead_id
├──────────────────────────────────────┤
│ 5. 销售跟进 (In Followup)            │ ← status in {FOLLOWING, WON, LOST}
├──────────────────────────────────────┤
│ 6. 成交 (Won)                        │ ← status=WON
└──────────────────────────────────────┘
```

### 3.2 漏斗计算公式
每一层 = 满足该层条件的唯一 lead_id 数量

- **转化率 (i→i+1)** = Level[i+1] / Level[i] × 100%
- **总体转化率** = Level[6] / Level[1] × 100%
- **漏损率 (i)** = 1 - Level[i+1] / Level[i]

### 3.3 维度筛选
| 筛选维度 | 字段 | 可选值 |
|---------|------|--------|
| 时间范围 | created_at / sent_at / graded_at | 今日/近 7 天/近 30 天/自定义 |
| 渠道类型 | channel | 7 大来源 + all |
| 商机等级 | grade | A/B/C/D + all |
| 合规状态 | compliance_status | OK/REVIEW/HIGH_RISK + all |

### 3.4 API 设计：漏斗查询
`GET /api/admin/data_center/funnel?time_range=7d&channel=all&grade=all&compliance=all`

**返回结构**:
```json
{
  "code": 0,
  "data": {
    "stages": [
      {"stage_key": "collection",     "stage_title": "采集量",     "count": 1234, "ratio": 100.0},
      {"stage_key": "valid_leads",    "stage_title": "有效线索",   "count":  980, "ratio":  79.4},
      {"stage_key": "compliant",      "stage_title": "合规商机",   "count":  867, "ratio":  88.5},
      {"stage_key": "outreached",     "stage_title": "客户触达",   "count":  512, "ratio":  59.0},
      {"stage_key": "in_followup",    "stage_title": "销售跟进",   "count":  234, "ratio":  45.7},
      {"stage_key": "won",            "stage_title": "成交",       "count":   47, "ratio":  20.1}
    ],
    "total_conversion": 3.81,
    "channel_breakdown": [{"channel": "short_video", "stages": [...]}, ...],
    "grade_breakdown": [{"grade": "A", "stages": [...]}, ...]
  }
}
```

---

## 4. 商机详情时间线节点与内容设计

**页面路由**: `/admin/data_center/opportunity/{lead_id}`

### 4.1 顶部卡片：商机概览
| 字段 | 类型 | 说明 | 脱敏 |
|------|------|------|------|
| lead_id | string | 商机 ID | 否 |
| title | string | 商机标题 | 否 |
| company | string | 公司名称 | 否 |
| contact | string | 联系人 | 是 |
| phone | string | 电话 | 是 |
| email | string | 邮箱 | 是 |
| grade | enum | A/B/C/D | 否 |
| status | enum | NEW/FOLLOWING/WON/LOST | 否 |
| channel | string | 来源渠道 | 否 |
| compliance_status | enum | OK/REVIEW/HIGH_RISK | 否 |
| total_score | float | 综合评分 | 否 |

### 4.2 时间线节点（按时间倒序）
每个节点包含：`time` + `node_type` + `actor` + `details`

1. **采集节点** (COLLECTED)
   - 内容：从哪个任务采集、采集时间、渠道、原始 URL（脱敏）
   - 数据来源：spider_task meta + items

2. **清洗节点** (CLEANED)
   - 内容：提取了哪些结构化字段、丢弃了哪些噪声数据
   - 数据来源：data_clean.storage

3. **合规校验节点** (COMPLIANCE_CHECKED)
   - 内容：检测到哪些 PII、是否通过、评分、处理方式（脱敏/保留/拒绝）
   - 数据来源：core.compliance.pii_detect + compliance_rules

4. **分级节点** (GRADED)
   - 内容：打分结果、分级理由、关键标签
   - 数据来源：sales_task.scoring engine

5. **分配节点** (ASSIGNED)
   - 内容：分配给哪位销售、分配时间、分配理由（如 A 级自动分配金牌销售）
   - 数据来源：sales_mgmt assignments API

6. **跟进节点** (FOLLOWUP)
   - 内容：跟进时间、跟进方式（电话/微信/邮件/面访）、跟进内容、客户反馈、下次跟进安排
   - 数据来源：sales_mgmt followups API

7. **触达节点** (OUTREACH_SENT)
   - 内容：发送时间、渠道、消息模板、发送状态（成功/失败/已读/已回复）
   - 数据来源：customer_send registry

8. **状态变更节点** (STATUS_CHANGED)
   - 内容：从旧状态到新状态、变更人、变更原因
   - 数据来源：sales_task status_engine + audit_log

9. **成交/流失节点** (WON / LOST)
   - 内容：成交金额/流失原因、时间
   - 数据来源：sales_mgmt persons API + opportunity registry

### 4.3 需求原文与标签区
- 原始需求描述（脱敏）
- 自动打标结果（行业/职位/意向/预算/紧急度）
- 相关标签云

### 4.4 数据来源与关联 ID
- source_job_id: 关联采集任务（可跳转详情页）
- outreach_run_ids: 关联触达批次列表
- audit_log_entries: 关联操作日志

---

## 5. 首页数据看板布局与指标定义

**页面路由**: `/admin/data_center/dashboard`（扩展现有 `/admin/dashboard`）

### 5.1 顶部核心指标卡（4 张）
| 指标 | 公式/来源 | 展示 |
|------|----------|-------|
| 今日新增商机 | 今日 status=APPROVED 的 leads | 大数字 + 今日趋势箭头 |
| 总商机数 | leads total | 大数字 |
| A 级商机数 | grade=A count | 大数字 + 占比 % |
| 待跟进数 | status=NEW/FOLLOWING 且 last_followup > 24h | 大数字 + 红色警告 |
| 成交数 | status=WON count | 大数字 + 成交金额汇总（如有） |

### 5.2 全局漏斗图
- 展示「3. 全链路漏斗」的 6 层转化
- 每层显示数量与百分比
- 支持点击某层跳转到对应阶段明细页

### 5.3 渠道占比饼图
- 各渠道（7 大来源）的商机数量占比
- 数据来源：leads storage 按 channel group by

### 5.4 等级占比饼图
- A/B/C/D 各等级的商机数量占比
- 数据来源：leads storage 按 grade group by

### 5.5 最近 7 天趋势折线图
- 横轴：日期
- 纵轴：每日新增商机数 / 每日成交数（双折线）
- 数据来源：leads storage 按日期 group by + sales closing 按日期 group by

### 5.6 快速入口卡片
- 6 个阶段的快速跳转按钮（带阶段图标 + 当前阶段数据数量）

---

## 6. 分步开发执行流程

### 阶段 A：菜单项与权限扩展（先改 `menu.py` + `auth.py`）
1. `menu.py`: 扩展 `data_center` 分组，新增 8 个菜单项
   - `data_center_dashboard`（全链路看板）/admin/data_center/dashboard
   - `data_center_collection`（采集阶段）/admin/data_center/collection
   - `data_center_cleaning`（清洗结构化）/admin/data_center/cleaning
   - `data_center_compliance`（合规校验）/admin/data_center/compliance
   - `data_center_grading`（商机分级）/admin/data_center/grading
   - `data_center_outreach`（客户触达）/admin/data_center/outreach
   - `data_center_sales`（销售闭环）/admin/data_center/sales
   - `data_center_opportunity`（商机追踪，动态路由）/admin/data_center/opportunity/{lead_id}
   - 每个菜单项配置 `roles`（按 1.4 权限矩阵）
2. `auth.py`: 新增按钮级权限（只读查看 + 申请明文）
   - `btn.data_center.view`（所有角色的基础访问）
   - `btn.data_center.view_raw`（仅 super_admin，控制明文查看按钮显示）

### 阶段 B：后端 API 层（`web_admin/api/data_center.py` 新建文件）
1. **漏斗 API**: `GET /data_center/funnel`
   - 参数：`time_range`（7d/30d/custom）、`channel`、`grade`、`compliance`
   - 逻辑：按维度从各底层模块统计后组装成 3.4 的返回结构
   - 复用：dashboard.py 的计数逻辑 + lead_mgmt.py 的 query_leads
2. **各阶段明细列表 API**（6 个端点）
   - `GET /data_center/stage/{stage_key}`
   - stage_key ∈ {collection/cleaning/compliance/grading/outreach/sales}
   - 参数：`page/page_size/status/channel/keyword/time_range`
   - 逻辑：按阶段从对应的底层接口读取数据，脱敏后返回
3. **单商机全链路详情 API**
   - `GET /data_center/opportunity/{lead_id}`
   - 逻辑：从各底层接口（spider_task.items/leads/detail/compliance_report/sales_assignments/followups/outreach_runs）聚合数据，按时间倒序生成时间线
   - 所有敏感字段自动脱敏
4. **渠道/等级分布 API**
   - `GET /data_center/distribution?dim=channel|grade`
   - 返回饼图数据
5. **近期趋势 API**
   - `GET /data_center/trend?days=7&metric=leads|wins`
   - 返回折线图数据

### 阶段 C：页面路由层（`web_admin/pages.py` 扩展）
每个阶段页面遵循统一模板：

1. **全链路看板页**: `data_center_dashboard_page()` → `/admin/data_center/dashboard`
   - 5.1~5.6 布局 + `_layout_v2("数据中心-全链路看板", "data_center_dashboard", body_html, session)`
2. **采集阶段页**: `data_center_collection_page()`
3. **清洗结构化页**: `data_center_cleaning_page()`
4. **合规校验页**: `data_center_compliance_page()`
5. **商机分级页**: `data_center_grading_page()`
6. **客户触达页**: `data_center_outreach_page()`
7. **销售闭环页**: `data_center_sales_page()`
8. **商机追踪详情页**: `data_center_opportunity_page(lead_id)` → `/admin/data_center/opportunity/{lead_id}`

**页面 HTML 模板统一模式**：
```
[顶部标题 + 面包屑]
[筛选栏：时间范围 | 渠道 | 状态 | 搜索关键字]
[汇总指标卡：5 张卡片]
[阶段明细列表：表格 + 分页]
[列表项：点击 lead_id 跳转到商机追踪页 / 点击 job_id 跳转到 spider_detail]
```

### 阶段 D：前端交互脚本（`admin.js` 扩展）
1. `loadFunnelChart()` — 调 API 渲染漏斗（使用纯 HTML/CSS 条形图，不引入第三方库）
2. `loadPieChart()` — 渠道/等级分布饼图
3. `loadTrendChart()` — 趋势折线图
4. `loadStageList(stage_key)` — 加载某阶段明细列表
5. `loadOpportunityTimeline(lead_id)` — 加载时间线
6. `applyDataFilters()` — 统一筛选参数处理
7. 图表全部用纯 CSS/HTML 实现（无外部依赖）：
   - 漏斗：堆叠条形，每层高度 = count / max_count
   - 饼图：CSS conic-gradient 或 SVG
   - 折线图：SVG path

### 阶段 E：样式扩展（`admin.css` 底部追加）
1. `.funnel-stage` — 漏斗每层样式
2. `.metric-card` — 指标卡片样式
3. `.timeline-node` — 时间线节点样式
4. `.pie-chart`, `.line-chart` — 图表 CSS
5. `.data-table` 扩展支持可点击行跳转

### 阶段 F：API 路由注册（`web_admin/main.py`）
1. `from web_admin.api.data_center import router as data_center_router`
2. `api_router.include_router(data_center_router)`

### 阶段 G：测试验证
1. 运行 `python -m pytest tests/ -v` 确保全量通过
2. 手动验证：
   - 4 种角色登录后可见的菜单是否符合权限矩阵
   - 6 阶段页面能否正常加载数据（无数据时展示空态）
   - 敏感字段是否脱敏（只有 super_admin 能看到「申请明文」按钮）
   - 商机追踪页能否正确聚合时间线数据
   - 筛选功能（渠道/时间/状态）是否生效

### 阶段 H：提交
- `git add web_admin/`
- `git commit -m "feat(T21): 搭建全链路6阶段化管控看板..."`
- `git push origin main`

---

## 7. 变更文件清单

| 文件 | 变更类型 | 说明 |
|------|---------|------|
| `web_admin/menu.py` | 修改 | 扩展 data_center 分组，新增 8 个菜单项 |
| `web_admin/auth.py` | 修改 | 新增 `btn.data_center.view` / `btn.data_center.view_raw` 权限 |
| `web_admin/api/data_center.py` | **新建** | 6 阶段明细 + 漏斗 + 分布 + 趋势 + 商机追踪 API（约 10 个端点）|
| `web_admin/api/__init__.py` | 修改 | 导出 `data_center_router` |
| `web_admin/pages.py` | 修改 | 新增 8 个页面路由函数，扩展 `_page_title` |
| `web_admin/main.py` | 修改 | 注册 `data_center_router` |
| `web_admin/static/js/admin.js` | 修改 | 追加图表渲染函数与阶段列表加载函数 |
| `web_admin/static/css/admin.css` | 修改 | 追加漏斗/卡片/时间线/图表 CSS 样式 |

**新增文件**: 1 个（data_center.py）
**修改文件**: 7 个
**底层业务代码**: 0 个修改（仅读取，不写入）

---

## 8. 依赖与注意事项

### 8.1 依赖说明
- 复用 `business.data_clean.storage.query_leads/get_lead`（清洗存储）
- 复用 `business.sales_task.registry` + 评分引擎
- 复用 `business.customer_send.registry.list_runs()`
- 复用 `infra.redis_client.get_redis()`（计数缓存读取）
- 复用 `web_admin.api.dashboard._safe_count()` 模式
- 复用 `web_admin.api.lead_mgmt._mask_lead()` 脱敏逻辑（扩展到所有阶段）

### 8.2 风险处理
| 风险 | 触发条件 | 处理策略 |
|------|---------|---------|
| 底层模块 import 失败 | 业务 SDK 未接入/路径变更 | try/except 降级，返回空数据 + 前端空态提示 |
| Redis key 不存在 | 新系统尚无数据 | 返回 0 + 空态，不报错 |
| 大数据量分页 | leads > 10,000 | 使用底层 `query_leads(page=page, page_size=page_size)` 原生分页，禁止全量读取 |
| 脱敏规则不全 | 新字段名不在敏感列表 | 扩展 `_mask_lead()` 的敏感字段列表（在 API 层，不改底层）|
| 角色权限越界 | 低角色访问高阶段数据 | 菜单层 `role_can_view_menu()` 过滤 + API 层 `require_admin()` + permission check 二次校验 |

### 8.3 空态设计
每个阶段页面无数据时显示：
- 汇总卡片：0 / — / 0%
- 列表：`[暂无数据]` 提示 + 引导文案「可能原因：采集任务未执行 / 数据尚未清洗 / 过滤条件过严」
- 漏斗：灰色空漏斗占位图 + 说明

### 8.4 明文申请机制
- 默认所有敏感字段脱敏显示
- super_admin 角色可见「查看原文」按钮（`btn.data_center.view_raw` 控制）
- 点击按钮 → 调后端 API 返回未脱敏版本 → 本次会话中显示明文
- 审计日志记录所有查看明文操作（谁、何时、查看了哪个商机）

---

## 9. 实施顺序摘要

```
Step 1: 菜单 & 权限 (menu.py + auth.py)
Step 2: 数据中心 API (新建 data_center.py)
Step 3: 路由注册 (main.py + api/__init__.py)
Step 4: 页面路由 (pages.py 扩展 8 个页面)
Step 5: 前端 JS 图表渲染 (admin.js 追加)
Step 6: CSS 样式 (admin.css 追加)
Step 7: 测试验证 (pytest + 手动验证)
Step 8: 提交推送
```

**估算新增代码量**：约 800-1200 行（主要在 data_center.py + pages.py 页面 HTML）
**修改现有代码量**：约 50-100 行（主要在 menu.py + auth.py + main.py）
**底层业务代码修改量**：0 行
