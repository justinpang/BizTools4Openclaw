# T20 · 采集任务前置合规审核工作流开发计划

> 基于 T18 权限体系 + T19 采集任务模块开发。纯管理后台层扩展，不修改底层爬虫业务代码。

---

## 一、合规审核流程流转图

```
                        ┌────────────────────────────────────────────────────┐
                        │                   TASK SUBMISSION                   │
                        │  (运营岗 / super_admin 创建采集任务)                   │
                        │  · 填写：任务名称、采集参数                            │
                        │  · 必填：勾选合规协议 + 填写数据用途 + 选择留存周期      │
                        │  · 自动校验：禁止输入违规站点 / 隐私采集配置            │
                        └────────────────────────────┬───────────────────────────┘
                                                     │
                                                     ▼
                             ┌────────────────────────────────────────┐
                             │  AUTO-JUDGE: 渠道审批规则判定           │
                             │  · 高风险渠道: short_video/xhs/b2b      │
                             │    → 状态 = PENDING_APPROVAL            │
                             │  · 低风险渠道: generic_web/bidding/... │
                             │    (若配置为免审) → 状态 = READY         │
                             │    (若配置为需审) → 状态 = PENDING_APPROVAL │
                             └────────────┬──────────────────────────┬──┘
                                          │                          │
                  ┌───────────────────────┘                          └─────────┐
                  ▼                                                                  ▼
      ┌───────────────────────┐                                      ┌───────────────────────┐
      │   PENDING_APPROVAL    │                                      │         READY         │
      │   待审核（不可启动）    │                                      │   可启动 / 可编辑      │
      │   提交者可见：审核中    │                                      │   可被调度器触发        │
      └────────┬──────────────┘                                      └──────────┬────────────┘
               │                                                                   │
               ▼                                                                   ▼
    ┌───────────────────────────┐                                      ┌────────────────────────┐
    │  合规审核工作台 (compliance)│                                      │   审批通过 → 可手动启动  │
    │  · 查看待审批列表           │                                      │   · 站内消息 + 告警通知   │
    │  · 通过 APPROVE            │                                      │   · 操作留痕              │
    │  · 驳回 REJECT（填写原因）  │                                      └────────────┬───────────┘
    └────┬──────────────┬────────┘                                                    │
         │              │                                                                 │
   ┌─────▼──┐      ┌──▼──────────────────────┐                                       │
   │APPROVE │      │   REJECT (with reason)    │                                       │
   │  (status: READY) │                      │                                       │
   │  notify submitter │                      │                                       │
   └────┬──┘      ┌──┬──────────────────────┘                                       │
         │          │                                                               │
         ▼          ▼                                                               │
     ┌─────────┐  ┌───────────────────────────┐                                 │
     │ READY   │  │  REJECTED (含驳回原因)      │                                 │
     │ (可启动) │  │  · 提交者可修改重试          │                                 │
     │         │  │  · 合规岗可查看历史           │                                 │
     └────┬────┘  └──────────┬──────────────────┘                                 │
          │                  │                                                      │
          ▼                  ▼                                                      │
     ┌──────────────┐   ┌──────────────────────┐                                 │
     │ RUN / SCHEDULED│   │ 修改后重新提交         │                                 │
     │ (复用 T19 API)│   │ (回到 AUTO-JUDGE)      │                                 │
     └──────────────┘   └──────────────────────┘                                 │
                                                                                   │
                                                                                   ▼
                                                                           ┌────────────────────┐
                                                                           │   完整操作审计链    │
                                                                           │  (web_admin.middleware)│
                                                                           │  · 提交、审核、修改 │
                                                                           │  · 所有操作留痕    │
                                                                           │  · 不可删除、不可篡改│
                                                                           └────────────────────┘
```

---

## 二、任务表单合规字段 & 协议内容设计

### 2.1 现有任务提交字段（扩展前）

参考 `web_admin/api/spider_task.py` 中 `create_spider_task`：

| 字段 | 类型 | 说明 |
|---|---|---|
| `task_name` | string | 任务名称 |
| `channel` | enum | 渠道（7 类） |
| `spider_name` | string | 爬虫名称 |
| `speed_level` | int | 速度档位 |
| `max_items` | int | 采集上限 |
| `schedule_mode` | enum | 定时模式 |
| `cron` | string | Cron 表达式 |
| `time_range` | string | 时间范围 |
| `keywords` | string[] | 关键词列表 |
| `region` | string | 地域筛选 |
| 其他 10+ 字段 | ... | 各渠道专属参数 |

### 2.2 新增合规字段（在 create_spider_task 中追加）

| 字段 | 类型 | 强制 | 说明 |
|---|---|---|---|
| `compliance.agreed` | bool | **必** | 是否已勾选合规协议 |
| `compliance.data_purpose` | string | **必** | 数据用途描述（"商机采集"、"市场调研"等下拉） |
| `compliance.retention_period` | string | **必** | 数据留存周期（"30天"、"90天"、"180天"、"1年"） |
| `compliance.privacy_commitment` | bool | **必** | 隐私采集承诺（确认不采集隐私信息） |
| `compliance.site_list_verified` | bool | **必** | 采集站点已核对，不含违规/隐私站点 |
| `compliance.submitted_at` | int | 自动 | 提交时间戳（自动写入） |
| `compliance.submitted_by` | string | 自动 | 提交者 username |

### 2.3 合规协议文本（读取配置，不硬编码）

配置在 Redis 键 `web_admin:compliance:agreement_text`，默认值：

> **数据采集合规协议**
> 1. 本任务仅用于合法的公开数据采集，不得用于获取个人隐私信息；
> 2. 采集数据仅用于本企业商机分析/市场调研/招投标决策等合法用途；
> 3. 承诺不采集联系方式、身份证号、住址等个人敏感信息；
> 4. 采集数据保留周期由任务提交者选择，到期自动清理；
> 5. 任务提交者对采集内容的合规性承担直接责任；
> 6. 高风险渠道采集需经合规岗审核通过后方可执行。

### 2.4 高风险渠道判定规则

> **注：渠道类型与风险等级映射读取配置（`web_admin:compliance:channel_rules`），后台管理员可动态调整。**

| 渠道 channel | 默认风险等级 | 默认审批要求 |
|---|---|---|
| `short_video` | HIGH | 需要审批 |
| `xhs` | HIGH | 需要审批 |
| `b2b_supply` | HIGH | 需要审批 |
| `qa_platform` | MEDIUM | 可配置（默认免审） |
| `generic_web` | LOW | 可配置（默认免审） |
| `bidding` | LOW | 可配置（默认免审） |
| `company_biz` | LOW | 可配置（默认免审） |

### 2.5 违规站点 & 隐私采集配置自动校验

**关键词黑名单**（读取 `web_admin:compliance:forbidden_keywords`）：
- 隐私类："身份证"、"手机号"、"住址"、"邮箱"、"密码"、"银行卡"
- 违规类："色情"、"赌博"、"翻墙"、"黑客"、"代写"、"代开发票"
- 爬虫反爬："反爬虫"、"robots.txt"、"禁止爬取"

**校验逻辑**：提交时在 `keywords / platform / company_keywords / site_type / url_template` 中检测，命中任一即拒绝提交。

---

## 三、审核工作台页面结构与字段

### 3.1 新增页面路由

| 路由 | 页面 | 权限 | 说明 |
|---|---|---|---|
| `/admin/compliance/review` | 审核工作台 | `btn.compliance.review` | 待审核 + 已审核任务列表 |
| `/admin/compliance/config` | 审核规则配置 | `btn.compliance.config` | 渠道审批规则 + 协议文本 + 留存周期选项 |

### 3.2 审核工作台：待审核列表（PENDING_APPROVAL）

```
[Filter Bar]  渠道下拉 ▼  提交人搜索 🔍  提交时间区间 📅  刷新按钮 ↻

[Task Table]
 ┌──────────┬────────┬──────────┬──────────┬────────────┬────────┬───────────┐
 │ 任务ID    │ 渠道   │ 任务名称 │ 提交人   │ 提交时间   │ 状态   │ 操作     │
 ├──────────┼────────┼──────────┼──────────┼────────────┼────────┼───────────┤
 │ spider_1 │ 短视频 │ 餐饮品牌│ zhangsan │ 2026-07-05 │ 待审核 │ [通过] [驳回] [查看] │
 │ spider_2 │ 小红书 │ 美妆测评│ lisi     │ 2026-07-04 │ 待审核 │ [通过] [驳回] [查看] │
 │ ...     │ ...    │ ...     │ ...     │ ...       │ ...   │ ...     │
 └──────────┴────────┴──────────┴──────────┴────────────┴────────┴───────────┘
```

### 3.3 审核工作台：已审核记录（APPROVED / REJECTED）

```
[Tab: 待审批 | 已审批]

[已审批 Table]
 ┌──────────┬────────┬──────────┬──────────┬────────────┬────────┬───────────┬───────────┐
 │ 任务ID    │ 渠道   │ 任务名称 │ 提交人   │ 审核人     │ 审核时间 │ 审核结果 │ 驳回原因 │
 ├──────────┼────────┼──────────┼──────────┼────────────┼────────┼───────────┼───────────┤
 │ spider_A │ 短视频 │ 餐饮品牌│ zhangsan │ compliance01│ 2026-07-05 10:30 │ 通过 │ -     │
 │ spider_B │ 小红书 │ 美妆测评│ lisi     │ compliance01│ 2026-07-04 15:22 │ 驳回 │ 含隐私关键词"手机号" │
 │ ...     │ ...    │ ...     │ ...     │ ...       │ ...   │ ...     │ ...    │
 └──────────┴────────┴──────────┴──────────┴────────────┴────────┴───────────┴───────────┘
```

### 3.4 驳回弹窗模态

```
┌───────────────────────────────────┐
│  驳回任务 spider_B                  │
├────────────────────────────────────┤
│  请填写驳回原因（必填）：             │
│  ┌────────────────────────────────┐ │
│  │ 采集任务关键词含"手机号"隐私字段 │ │
│  │ 请修改后重新提交                 │ │
│  └────────────────────────────────┘ │
│                                    │
│  [取消]   [确认驳回]                 │
└────────────────────────────────────┘
```

### 3.5 任务详情查看（复用 /admin/spider/{job_id}，只读）

审核员点击「查看」按钮跳转到 `/admin/spider/{job_id}` 页面，
- 只读展示：任务基础配置 + 采集参数 + 合规字段
- 底部显示审核操作按钮（通过/驳回）
- 审核员无启动/暂停/删除权限（权限隔离）

---

## 四、审核规则配置项设计

### 4.1 页面布局：/admin/compliance/config

```
[Section 1] 渠道审批规则配置
  表格形式，每个渠道一行：
   ┌────────┬──────────┬──────────────┬──────────────────┐
   │ 渠道    │ 风险等级 │ 是否需要审批   │ 默认审批角色     │
   ├────────┼──────────┼──────────────┼──────────────────┤
   │ 短视频  │ HIGH ▼  │ [x] 需要审批  │ compliance ▼    │
   │ 小红书  │ HIGH ▼  │ [x] 需要审批  │ compliance ▼    │
   │ 供需B2B │ HIGH ▼  │ [x] 需要审批  │ compliance ▼    │
   │ 问答平台│ MEDIUM ▼│ [ ] 需要审批  │ -              │
   │ 通用网页│ LOW ▼   │ [ ] 需要审批  │ -              │
   │ ...    │ ...     │ ...          │ ...            │
   └────────┴──────────┴──────────────┴──────────────────┘
  [保存配置]

[Section 2] 合规协议文本
  textarea（大文本输入框）：
    "数据采集合规协议（完整文本，可编辑修改）..."
  [保存协议文本]

[Section 3] 数据留存周期选项
  多选 checkbox + 自定义输入：
    [x] 30天    [x] 90天    [x] 180天    [x] 1年    [ ] 自定义：____ 天
  [保存留存周期]

[Section 4] 违规关键词黑名单
  textarea（每行一个关键词）：
    身份证
    手机号
    住址
    邮箱
    ...
  [保存黑名单]
```

### 4.2 配置持久化（Redis 键）

| Redis Key | 类型 | 默认值 | 说明 |
|---|---|---|---|
| `web_admin:compliance:channel_rules` | hash (JSON) | 见 2.4 | 每个渠道的审批规则 |
| `web_admin:compliance:agreement_text` | string | 见 2.3 | 合规协议文本 |
| `web_admin:compliance:retention_options` | string (JSON) | `["30天","90天","180天","1年"]` | 留存周期下拉选项 |
| `web_admin:compliance:forbidden_keywords` | string (JSON) | 见 2.5 | 违规关键词列表 |
| `web_admin:compliance:review_records` | hash (JSON) | - | 审核记录（job_id -> 审核详情） |

### 4.3 单条审核记录结构

```jsonc
{
  "job_id": "spider_A",
  "task_name": "餐饮品牌商机采集",
  "channel": "short_video",
  "submitted_by": "zhangsan",
  "submitted_at": 1783239483,
  "reviewed_by": "compliance01",
  "reviewed_at": 1783239600,
  "decision": "APPROVED",            // APPROVED | REJECTED
  "reject_reason": null,              // REJECTED 时填写
  "compliance_fields": {              // 保存审核时的合规字段快照
    "agreed": true,
    "data_purpose": "商机采集",
    "retention_period": "90天",
    "privacy_commitment": true,
    "site_list_verified": true
  },
  "task_snapshot": {                  // 任务参数快照（防篡改）
    "keywords": ["餐饮", "品牌"],
    "max_items": 500,
    "speed_level": 3
  }
}
```

---

## 五、任务状态扩展与联动逻辑

### 5.1 扩展 T19 任务状态

在 `VALID_STATUSES` 中新增 2 个状态：

```
PENDING_APPROVAL  待审核（高风险渠道提交后，不可启动）
REJECTED          已驳回（含驳回原因，提交者可修改重提）

完整状态集合：
{ DRAFT, PENDING_APPROVAL, REJECTED, READY, RUNNING, PAUSED,
  COMPLETED, FAILED, TERMINATED }
```

### 5.2 状态流转规则（新增）

```
SUBMIT → [自动判定]
           ├─ 免审渠道 → READY（可直接启动）
           └─ 需审渠道 → PENDING_APPROVAL（等待合规审核）

PENDING_APPROVAL
  ├─ APPROVE → READY（发送消息给提交者）
  └─ REJECT  → REJECTED（写入驳回原因 + 消息）

REJECTED
  └─ 提交者修改后重新提交 → [再次自动判定]（回到 PENDING_APPROVAL / READY）

READY / RUNNING / PAUSED / COMPLETED / FAILED / TERMINATED
  → 保持 T19 原有流转逻辑不变
```

### 5.3 通知机制：站内消息 + 告警通知

**通知类型**：
- **任务提交通知**（给合规岗）："您有 1 个新任务待审核"
- **审核结果通知**（给提交者）："您的任务 spider_A 已通过审核" / "任务 spider_B 被驳回：原因..."

**通知存储**（简单 Redis 列表实现，无需数据库）：

| Redis Key | 类型 | 说明 |
|---|---|---|
| `web_admin:notification:{username}` | list | 每个用户的通知列表 |
| `web_admin:notification:all` | list | 全局通知汇总 |

**单条通知结构**：
```jsonc
{
  "id": "notif_abc123",
  "type": "COMPLIANCE_APPROVE",   // SUBMIT_FOR_REVIEW | APPROVE | REJECT
  "title": "任务 spider_A 审核通过",
  "content": "您提交的任务已通过合规审核，可启动执行。",
  "link": "/admin/spider/spider_A",
  "from": "compliance01",
  "to": "zhangsan",
  "created_at": 1783239600,
  "read": false
}
```

**告警通知**：复用 `infra/alerting.py` 的 `alert_service`，发送到企业微信/飞书 webhook（如有配置）。

---

## 六、分步开发执行流程

### Phase 1 · 权限矩阵 & 菜单注册（风险：LOW）

**目标**：在现有 T18 权限体系中追加合规审核相关权限与菜单项

**修改文件**：

**文件 1: `web_admin/auth.py`**
- 在 `ROLE_PERMISSIONS` 中为 `super_admin` 和 `compliance` 角色新增权限：
  - `btn.compliance.review`：访问审核工作台
  - `btn.compliance.approve`：审批通过
  - `btn.compliance.reject`：审批驳回（填写原因）
  - `btn.compliance.view_history`：查看历史审核记录
  - `btn.compliance.config`：配置审核规则（**仅 super_admin**）
  - `btn.compliance.notification`：接收通知（**所有可登录用户**）

- 在 `role_can_view_menu()` 中新增菜单可见性：
  - `compliance_review`：`{super_admin, compliance}`
  - `compliance_config`：`{super_admin}`

**文件 2: `web_admin/menu.py`**
- 在 `MENU_GROUPS` 中新增分组（插入在 "采集管理" 之后、"商机管理" 之前）：
  ```
  group_key: "compliance"
  title: "合规审核"
  items:
    - key: "compliance_review"  审核工作台  /admin/compliance/review   {super_admin, compliance}
    - key: "compliance_config"  审核规则配置 /admin/compliance/config  {super_admin}
  ```

**验证方式**：
- super_admin 登录可见「合规审核」分组的全部 2 个菜单项
- compliance 角色仅见「审核工作台」
- ops/sales 角色不可见该分组
- 无权限者访问 `/admin/compliance/*` 路由应返回 403

---

### Phase 2 · 配置项管理 API（风险：LOW）

**目标**：实现审核规则、协议文本、留存周期、违规关键词的 CRUD API

**修改文件**：

**文件 3: `web_admin/api/compliance.py`（新建文件）**

新建合规 API 模块，提供配置管理与审核记录管理：

| 路由 | 方法 | 说明 | 权限 |
|---|---|---|---|
| `/api/admin/compliance/config` | GET | 获取全部审核配置（channel_rules + agreement_text + retention_options + forbidden_keywords） | `btn.compliance.config` |
| `/api/admin/compliance/config/channel_rules` | POST | 更新渠道审批规则 | `btn.compliance.config` |
| `/api/admin/compliance/config/agreement_text` | POST | 更新合规协议文本 | `btn.compliance.config` |
| `/api/admin/compliance/config/retention_options` | POST | 更新留存周期选项 | `btn.compliance.config` |
| `/api/admin/compliance/config/forbidden_keywords` | POST | 更新违规关键词 | `btn.compliance.config` |
| `/api/admin/compliance/tasks/pending` | GET | 获取待审核任务列表 | `btn.compliance.review` |
| `/api/admin/compliance/tasks/history` | GET | 获取已审核历史记录 | `btn.compliance.view_history` |
| `/api/admin/compliance/task/{job_id}/approve` | POST | 审核通过（写入记录 + 变更状态为 READY + 通知提交者） | `btn.compliance.approve` |
| `/api/admin/compliance/task/{job_id}/reject` | POST | 审核驳回（写入原因 + 变更状态为 REJECTED + 通知提交者） | `btn.compliance.reject` |
| `/api/admin/compliance/agreement_text` | GET | 获取合规协议文本（供任务创建页面显示） | 公开（登录即可） |
| `/api/admin/compliance/channel_rules` | GET | 获取渠道审批规则（供任务创建页面判定） | 公开（登录即可） |
| `/api/admin/compliance/validate_keywords` | POST | 校验关键词是否含违规词（返回 {ok: bool, hits: string[]}） | 公开（登录即可） |

**实现要点**：
- Redis 键设计见「第四章 4.2」
- 所有写操作自动写入 middleware 审计日志
- 审核记录包含完整任务参数快照，防止篡改回溯
- 首次访问时自动写入默认配置（若 Redis 键不存在）

**文件 4: `web_admin/api/__init__.py` / adapter/main.py 路由注册**

在 adapter 路由注册处追加 compliance router。

---

### Phase 3 · 任务提交合规校验（风险：MEDIUM）

**目标**：修改 `create_spider_task`，在任务创建前执行合规前置校验

**修改文件**：

**文件 5: `web_admin/api/spider_task.py`**

- 在 `VALID_STATUSES` 中新增 2 个状态：`PENDING_APPROVAL`, `REJECTED`
- `create_spider_task()` 逻辑改造：

  1. **参数解析**：新增合规字段参数（`compliance_agreed`, `compliance_data_purpose`, `compliance_retention_period`, `compliance_privacy_commitment`, `compliance_site_list_verified`）
  2. **协议勾选校验**：`compliance_agreed` 必须为 true，否则 HTTP 400
  3. **用途与留存周期校验**：必须在允许列表内，否则 400
  4. **隐私承诺校验**：`compliance_privacy_commitment` + `compliance_site_list_verified` 必须为 true
  5. **违规关键词检测**：调用 `/api/admin/compliance/validate_keywords` 内部逻辑检测 keywords/platform/company_keywords/site_type/url_template，命中则 400 并返回命中词列表
  6. **渠道规则判定**：读取 channel_rules，若为「需审渠道」→ 任务状态 = `PENDING_APPROVAL`；否则 = `READY`
  7. **合规字段持久化**：将所有合规字段写入任务 payload 的 `compliance` 子对象中
  8. **通知**：若进入 `PENDING_APPROVAL`，则向所有 compliance 角色发送站内通知

- 新增辅助函数：
  - `_validate_compliance_fields(channel, payload) -> (ok: bool, reason: str)`
  - `_needs_approval(channel) -> bool`（读取 channel_rules 配置）
  - `_notify_compliance_reviewers(job_id, task_name, submitter)`（发送通知）

- `list_spider_tasks()` 扩展：
  - 新增状态筛选支持（含 PENDING_APPROVAL / REJECTED）
  - ops 角色查看自身提交的 PENDING_APPROVAL 任务时显示「待审核」标签

- `run_spider_now()` / `resume_spider_task()` 增加保护：
  - 若任务状态为 PENDING_APPROVAL 或 REJECTED，禁止启动，返回 HTTP 400

**验证方式**：
- 创建高风险渠道（短视频/小红书/B2B）任务 → 状态为 PENDING_APPROVAL，不可启动
- 创建低风险渠道（招投标/企业工商）任务 → 状态为 READY，可正常启动
- 提交含「手机号」关键词的任务 → 返回 400，提交被拦截
- 未勾选协议 → 返回 400

---

### Phase 4 · 审核工作台页面（风险：MEDIUM）

**目标**：实现合规审核的前端页面与交互

**修改文件**：

**文件 6: `web_admin/pages.py`**

新增 2 个路由页面函数：
- `compliance_review_page()` → `/admin/compliance/review`
  - 顶部 Tab 切换：「待审核」「已审批」
  - 待审核列表区（含渠道/状态筛选）
  - 已审核记录区（含审核结果/驳回原因列）
  - 任务详情查看链接（跳转到 `/admin/spider/{job_id}`）
  - 通过 / 驳回操作按钮（权限隔离）

- `compliance_config_page()` → `/admin/compliance/config`
  - 渠道审批规则配置表格
  - 合规协议文本编辑区
  - 留存周期选项编辑区
  - 违规关键词黑名单编辑区
  - 每分区独立「保存」按钮

在 `_page_title()` 中追加页面标题映射。

**文件 7: `web_admin/static/js/admin.js`**

新增前端交互函数：
- `admin.loadCompliancePending()`：加载待审核列表
- `admin.loadComplianceHistory()`：加载已审核历史
- `admin.approveTask(jobId)`：审核通过（POST API）
- `admin.rejectTask(jobId)`：弹出驳回原因输入框 → 提交（POST API）
- `admin.loadComplianceConfig()`：加载审核配置
- `admin.saveChannelRules()`：保存渠道规则配置
- `admin.saveAgreementText()`：保存协议文本
- `admin.saveRetentionOptions()`：保存留存周期
- `admin.saveForbiddenKeywords()`：保存违规关键词
- `admin.loadNotifications()`：加载通知列表
- `admin.markNotificationRead(id)`：标记通知已读
- `admin.renderTaskFormWithCompliance()`：任务创建页中追加合规字段展示
- `admin.validateTaskKeywords()`：提交前关键词实时校验

在现有的 `spider_page` / 任务创建表单中：
- 任务创建表单底部追加「合规字段」区块
- 显示「合规协议」文本（从 API 读取）+ 勾选框
- 数据用途下拉、留存周期下拉、隐私承诺勾选
- 提交按钮 disabled 直到全部合规字段完成

**文件 8: `web_admin/static/css/admin.css`**

追加样式：
- `.compliance-tables`：审核表格样式
- `.compliance-form-block`：合规字段区块（灰色背景、边框）
- `.compliance-agreement-text`：协议文本显示（固定高度 + scroll）
- `.reject-modal`：驳回弹窗样式
- `.status-pending-approval` / `.status-rejected`：状态标签样式
- `.notification-badge`：顶部通知小红点样式

**通知中心（简单）**：
- 顶部导航栏右侧添加通知图标 + 未读数量小红点
- 点击展开通知列表（下拉样式，显示最新 10 条）
- 通知点击跳转到对应链接并标记为已读

---

### Phase 5 · 任务详情页扩展与权限隔离（风险：LOW）

**目标**：在现有任务详情页中追加合规字段展示，审核操作按钮，保证权限隔离

**修改文件**：

**文件 9: `web_admin/pages.py` — `spider_detail_page()`**

- 在任务基础配置区块中追加「合规字段」显示（只读）：
  - 合规协议：已勾选 / 未勾选
  - 数据用途：xxx
  - 留存周期：xxx 天
  - 隐私承诺：已勾选 / 未勾选
  - 采集站点核对：已核对 / 未核对
  - 当前审核状态：待审核 / 已通过 / 已驳回（含驳回原因）

- 审核操作按钮（仅 compliance 角色显示，且任务为 PENDING_APPROVAL 时）：
  - 「通过审核」按钮
  - 「驳回任务」按钮

**文件 10: `web_admin/api/spider_task.py` — `get_task_detail()`**

- 返回中追加 `compliance` 子对象供前端渲染

**验证方式**：
- super_admin / compliance 角色访问详情页 → 可见合规字段
- ops 角色访问详情页 → 可见合规字段（只读），但不可见审核操作按钮
- PENDING_APPROVAL 状态的任务 → compliance 角色可见通过/驳回按钮

---

### Phase 6 · 通知中心页面（风险：LOW）

**目标**：提供通知列表查看页面 + 通知 API

**修改文件**：

**文件 11: `web_admin/pages.py`**

新增页面：
- `notifications_page()` → `/admin/notifications`
  - 通知列表表格：标题、类型、时间、状态、链接
  - 全部标记已读按钮
  - 清空按钮（仅 super_admin）

在 menu.py 中追加到「系统设置」分组：
- key: `notifications`，title: "消息中心"，href: `/admin/notifications`，roles: `{super_admin, ops, sales, compliance}`

**文件 12: `web_admin/api/notifications.py`（新建文件）**

API：
- `GET /api/admin/notifications`：获取当前用户通知列表（分页）
- `POST /api/admin/notifications/{id}/read`：标记已读
- `POST /api/admin/notifications/read_all`：全部标记已读
- `POST /api/admin/notifications/clear`：清空通知（super_admin）
- `POST /api/admin/notifications/send`（内部）：发送通知

---

### Phase 7 · 自测与验证（风险：N/A）

**测试用例清单**：

1. **权限矩阵测试**：
   - [ ] super_admin 登录 → 可见审核工作台 + 规则配置
   - [ ] compliance 角色登录 → 仅见审核工作台
   - [ ] ops/sales 角色 → 不可见审核分组
   - [ ] 无权限访问 `/admin/compliance/config` → 返回 403

2. **任务提交合规校验**：
   - [ ] 未勾选合规协议 → 提交被拒（400）
   - [ ] 未填写数据用途 → 提交被拒
   - [ ] 关键词含"手机号" → 提交被拒并提示命中词
   - [ ] 高风险渠道提交 → 状态 PENDING_APPROVAL，无法启动
   - [ ] 低风险渠道（免审）提交 → 状态 READY，可启动

3. **审核流程**：
   - [ ] compliance 角色查看待审核列表 → 可看到高风险任务
   - [ ] 点击「通过」→ 任务状态变为 READY，通知发送给提交者
   - [ ] 点击「驳回」→ 弹出原因输入框，任务状态 REJECTED，通知发送
   - [ ] 审核历史记录 → 可查询到所有已审核任务

4. **状态流转保护**：
   - [ ] PENDING_APPROVAL 任务 → 禁止启动
   - [ ] REJECTED 任务 → 禁止启动，可修改后重提
   - [ ] READY 任务 → 可正常启动（与 T19 一致）

5. **配置管理**：
   - [ ] 修改某渠道为「需审」→ 该渠道新增任务自动进入 PENDING_APPROVAL
   - [ ] 修改协议文本 → 创建任务页面显示新文本
   - [ ] 新增违规关键词 → 提交含该关键词的任务被拦截

6. **操作留痕**：
   - [ ] 所有审核操作（通过/驳回）可在 audit_log 中查询
   - [ ] 审核记录快照包含完整任务参数，不可修改

---

## 七、变更文件总览

| # | 文件 | 操作 | 说明 |
|---|---|---|---|
| 1 | `web_admin/auth.py` | 修改 | 扩展权限矩阵 + 菜单可见性 |
| 2 | `web_admin/menu.py` | 修改 | 新增「合规审核」分组（2 项） + 消息中心 |
| 3 | `web_admin/api/compliance.py` | **新增** | 审核配置 + 审批操作 + 校验 API |
| 4 | `adapter/main.py` 或 `web_admin` 路由注册处 | 修改 | 注册 compliance router |
| 5 | `web_admin/api/spider_task.py` | 修改 | 扩展任务状态 + 合规字段前置校验 |
| 6 | `web_admin/pages.py` | 修改 | 新增审核工作台/配置页/通知中心页面 |
| 7 | `web_admin/static/js/admin.js` | 修改 | 新增前端交互 + 任务创建页合规字段 |
| 8 | `web_admin/static/css/admin.css` | 修改 | 新增合规页面组件样式 |
| 9 | `web_admin/api/notifications.py` | **新增** | 通知中心 API |

**共 9 个文件（7 修改 + 2 新增），零底层业务代码修改。**

---

## 八、风险与约束

### 8.1 核心约束

1. **不修改底层爬虫逻辑**：所有审核仅在任务调度前进行拦截，不影响已实现的爬虫 SDK
2. **不引入数据库依赖**：配置与审核记录全部存储于 Redis（与 T19 一致），保持轻量
3. **审核记录不可删除/不可修改**：所有审核记录 append-only，通过 Redis hash 的一次性写入实现
4. **严格权限隔离**：
   - 合规岗：仅能审核、查看审核记录，不能启动/暂停/删除爬虫任务
   - 运营岗：仅能创建、启停自己的任务，不能修改审核规则
   - super_admin：拥有全部权限

### 8.2 潜在风险与应对

| 风险 | 影响 | 应对方案 |
|---|---|---|
| Redis 不可用导致配置读取失败 | 审核功能不可用，所有任务默认需审批 | 在 `_needs_approval()` 中添加降级逻辑：Redis 读取失败时默认全部需审批（安全默认） |
| 合规字段变更导致历史任务状态不一致 | 历史审核记录与新字段不匹配 | 审核记录包含当时字段快照（`task_snapshot`），与当前配置隔离 |
| 违规关键词匹配过于严格，误拦截合法任务 | 运营体验下降 | 提供「命中词」反馈 + 配置页可动态调整关键词列表 |
| 通知发送失败导致用户无法感知 | 用户不知道任务状态变化 | 通知为尽力发送，任务详情页始终显示最新状态作为事实来源 |
| 新状态 `PENDING_APPROVAL` 与 T19 调度器交互问题 | 待审核任务被错误调度 | 在 `run_spider_now()` 中显式检查状态，调度器层面通过 `READY` 限制启动 |

### 8.3 向后兼容

- 已存在的 T19 任务（状态为 READY/RUNNING/...）不受影响，正常运行
- 旧任务 payload 中无 `compliance` 字段 → 前端处理为「合规信息未记录」
- 新创建的任务强制带合规字段，老任务重新编辑时需补充合规字段

---

## 九、开发顺序与依赖

```
Phase 1 (auth + menu)       独立无依赖           预估工作量：小
     │
     ▼
Phase 2 (compliance API)    依赖 Phase 1（权限） 预估工作量：中
     │
     ▼
Phase 3 (task 合规校验)     依赖 Phase 2 API     预估工作量：中
     │
     ▼
Phase 4 (审核工作台页面)    依赖 Phase 2+3       预估工作量：中-大
     │
     ▼
Phase 5 (详情页扩展)        依赖 Phase 2+3       预估工作量：小
     │
     ▼
Phase 6 (通知中心)          依赖 Phase 1 menu    预估工作量：中
     │
     ▼
Phase 7 (自测与验证)        依赖 1-6            预估工作量：中
```

**建议**：开发时先完成 Phase 1-3（核心审核流程），再补充 Phase 4-5（页面），最后 Phase 6（通知）。每 Phase 完成后独立验证通过后再进入下一 Phase。
