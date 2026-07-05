# T13 OpenClaw 适配网关 / 工具注册中心 — 开发计划

## 一、仓库调研结论

**已有基础设施**：
- `business/multi_spider/registry.py` — 爬虫入口：`list_spiders()`、`run_spider_by_name(name, params)`
- `business/data_clean/registry.py` — 清洗入口：`run_cleaning(params)`、`CleanTaskParams`、`CleanRunResult`
- `business/customer_send/registry.py` — 触达入口：`run_batch(params)`、`async_run(params)`、`BatchSendParams`、`BatchSendResult`
- `business/sales_task/registry.py` — 销售入口：`run_batch()` / `assign()` / `remind()` / `transition()` / `add_tag()` / `record_follow_up()` / `get_funnel_stats()`
- `infra/task_queue.py` — 队列：`enqueue(func, args, kwargs, task_id)`、`get_status(task_id)` → `TaskMeta`、`list_tasks()`、`cancel()`
- `infra/task_states.py` — `TaskMeta`（含 task_id / name / status / payload / result / error / retries / created_at / started_at / finished_at）、`TaskStatus` 枚举（PENDING / RUNNING / SUCCESS / FAILED / CANCELLED）
- `core/compliance/pii_mask.py` — T06 脱敏：`PIIMask().auto_mask(data)` 深递归脱敏
- `infra/logger_setup.py` — `get_logger(name)` 统一日志
- `infra/alerting.py` — 全局告警：`alert_service`
- `configs/settings.py` — `AppSettings` + 各模块 Settings
- `requirements.txt` — 已包含 `fastapi>=0.110.0`、`uvicorn[standard]>=0.27.0`

**当前状态**：
- `adapter/` 目录已存在，仅有空 `__init__.py`
- `examples/` 目录不存在，需新建
- 四个业务模块均有独立 registry 入口函数，可直接被工具注册中心反射调用

---

## 二、新增文件清单（13 个文件，+1 修改）

```
adapter/
├── __init__.py                # 统一导出（重写）
├── config.py                  # 网关配置：端口、Token、限流阈值、IP 白名单、Webhook URL
├── models.py                  # Pydantic 请求/响应模型
├── middleware.py              # Trace ID 中间件 + Logger 上下文注入
├── auth.py                    # Bearer Token 鉴权 + 配额限流 + IP 白名单
├── tool_registry.py           # 工具注册中心：扫描 → 输出 OpenClaw Skill JSON
├── schema_adapter.py          # 入参出参标准化转换 + T06 脱敏封装
├── task_router.py             # 任务路由：enqueue / status / cancel
├── tools_router.py            # 业务工具执行路由（直连同步执行）
├── response.py                # 标准化 API 响应
└── main.py                    # FastAPI 主入口：/health、/openapi、/api/v1/*、工具注册接口

examples/
└── openclaw_skills_demo.yaml  # 可直接复制到 OpenClaw 的 Skill 配置示例

configs/
└── settings.py (修改)          # 追加 AdapterSettings 配置类

tests/
└── test_t13_openclaw_adapter.py  # 单元测试 + 集成测试
```

**总计：13 个文件（12 新增 + 1 修改 + 1 examples 目录）**

---

## 三、OpenClaw 标准工具注册 JSON 结构

```jsonc
// GET /api/v1/tools — 返回工具列表
// GET /api/v1/tools/{tool_name} — 返回单个工具定义
{
  "tool_name": "spider_run",
  "tool_type": "spider|data_clean|customer_send|sales_task",
  "version": "1.0",
  "display_name": "商机爬虫采集",
  "description": "根据关键词抓取企业新闻、采购公告、抖音小红书等公域商机信息",
  "auth_type": "bearer",
  "http_method": "POST",
  "endpoint": "/api/v1/tools/spider_run/execute",
  "callback_supported": true,
  "inputs": {
    "type": "object",
    "properties": {
      "spider_name": {
        "type": "string",
        "description": "爬虫名称，使用 /api/v1/tools 返回的工具名",
        "examples": ["generic_web", "bid_and_gov"]
      },
      "keywords": {
        "type": "array",
        "items": {"type": "string"},
        "description": "关键词列表",
        "examples": [["采购", "服务器"]]
      },
      "max_pages": {"type": "integer", "description": "最大采集页数", "default": 20},
      "async_mode": {"type": "boolean", "description": "是否异步执行（默认 true）", "default": true},
      "webhook_url": {"type": "string", "description": "可选，任务完成后的回调 URL", "default": null}
    },
    "required": ["spider_name", "keywords"]
  },
  "outputs": {
    "type": "object",
    "properties": {
      "task_id": {"type": "string", "description": "异步任务 ID，用于状态查询"},
      "status": {"type": "string", "description": "PENDING / RUNNING / SUCCESS / FAILED"},
      "collected_count": {"type": "integer", "description": "采集数量"},
      "data": {"type": "array", "items": {"type": "object"}, "description": "同步模式时直接返回结果"},
      "error": {"type": "string", "description": "错误信息（如有）"}
    }
  },
  "sample_call": {
    "http_method": "POST",
    "url": "/api/v1/tools/spider_run/execute",
    "headers": {"Authorization": "Bearer <token>"},
    "body": {"spider_name": "generic_web", "keywords": ["采购", "ERP"]}
  }
}
```

**注册工具列表（预计 12 个工具）**：

| tool_name | 所属模块 | 功能 |
|---|---|---|
| `spider_list` | multi_spider | 列出所有可用爬虫 |
| `spider_run` | multi_spider | 运行指定爬虫采集 |
| `clean_run` | data_clean | 执行数据清洗 |
| `send_batch` | customer_send | 批量商机触达（邮件/企微/飞书） |
| `send_async` | customer_send | 异步商机触达 |
| `sales_assign` | sales_task | 商机自动分配 |
| `sales_remind` | sales_task | 多级提醒扫描 |
| `sales_transition` | sales_task | 商机状态流转 |
| `sales_add_tag` | sales_task | 商机添加标签 |
| `sales_record_follow` | sales_task | 写入跟进记录 |
| `sales_funnel_stats` | sales_task | 漏斗统计查询 |
| `task_status` | (通用) | 任务状态查询 |

---

## 四、网关鉴权 / 限流中间件实现方案

### 4.1 鉴权流程

```
Request
  ├─► TraceMiddleware: 生成/读取 trace_id（X-Trace-Id）
  │                     注入 logger 上下文
  │
  ├─► AuthMiddleware (Depends):
  │       ├─► 读取 Authorization: Bearer <token>
  │       ├─► 与 settings.adapter.API_TOKENS 列表匹配
  │       └─► 不匹配 → 401 Unauthorized
  │
  ├─► IpWhitelistMiddleware (Depends):
  │       ├─► 读取 client_ip (X-Forwarded-For 优先)
  │       ├─► 检查是否在 settings.adapter.IP_WHITELIST 或
  │       │               WHITELIST 为空（允许全部）
  │       └─► 不在白名单 → 403 Forbidden
  │
  └─► RateLimitMiddleware (Depends):
          ├─► agent_id 由请求头 X-Agent-Id 确定
          ├─► Redis key: openclaw:quota:<agent_id>:<date>
          ├─► 若计数 >= settings.adapter.DAILY_QUOTA_PER_AGENT
          │      → 429 Too Many Requests + 触发告警
          └─► 否则计数 +1，设置 TTL 24h
```

### 4.2 配置（在 `configs/settings.py` 追加）

```python
class AdapterSettings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="", extra="ignore")

    # 网关基本信息
    ADAPTER_HOST: str = "0.0.0.0"
    ADAPTER_PORT: int = 8000
    ADAPTER_BASE_URL: str = "http://localhost:8000"
    ADAPTER_VERSION: str = "T13-v1.0"

    # Bearer Token 列表（支持多个 Agent 共享，逗号分隔）
    ADAPTER_API_TOKENS: str = "test-token-12345"

    # 单 Agent 每日调用上限（0 表示不限制）
    ADAPTER_DAILY_QUOTA_PER_AGENT: int = 1000

    # IP 白名单（空字符串表示不启用）
    ADAPTER_IP_WHITELIST: str = ""

    # Webhook 回调默认 URL
    ADAPTER_DEFAULT_WEBHOOK_URL: str = ""
    ADAPTER_WEBHOOK_TIMEOUT: float = 10.0

    # T06 隐私脱敏
    ADAPTER_AUTO_MASK_PII: bool = True

    # 日志
    ADAPTER_LOG_LEVEL: str = "INFO"

    def get_tokens(self) -> list[str]:
        return [t.strip() for t in str(self.ADAPTER_API_TOKENS).split(",") if t.strip()]

    def get_ips(self) -> list[str]:
        return [ip.strip() for ip in str(self.ADAPTER_IP_WHITELIST).split(",") if ip.strip()]
```

在 AppSettings 追加：`adapter: "AdapterSettings" = Field(default_factory=lambda: AdapterSettings())`

---

## 五、HTTP 接口规范

### 5.1 统一响应格式

```jsonc
// POST /api/v1/* / GET /api/v1/* 均使用此格式
{
  "code": 0,              // 0=成功，其余为错误码（401/403/404/422/429/500）
  "msg": "OK",            // 消息
  "data": {...},          // 业务数据（被脱敏）
  "trace_id": "oc_abc123",// 全链路追踪 ID
  "task_id": "task_xxx",  // 如有，异步任务 ID
  "timestamp": 1234567890
}
```

### 5.2 核心接口清单

| 方法 | 路径 | 功能 | 鉴权 |
|---|---|---|---|
| GET | `/health` | 健康检查 | 否 |
| GET | `/` | 网关信息（版本号、支持工具列表数） | 否 |
| GET | `/api/v1/tools` | 获取全部工具描述 JSON（供 OpenClaw 注册） | 是 |
| GET | `/api/v1/tools/{tool_name}` | 获取单个工具描述 | 是 |
| POST | `/api/v1/tools/{tool_name}/execute` | 执行工具（同步模式，快速返回结果） | 是 |
| POST | `/api/v1/tasks/enqueue` | 异步任务下发，入 Redis 队列 | 是 |
| GET | `/api/v1/tasks/{task_id}` | 任务状态查询（轮询用） | 是 |
| POST | `/api/v1/tasks/{task_id}/webhook` | 手动触发 webhook（调试用） | 是 |
| DELETE | `/api/v1/tasks/{task_id}` | 取消任务 | 是 |
| GET | `/api/v1/tasks` | 近期任务列表（默认最近 100） | 是 |

### 5.3 详细入参出参

**POST /api/v1/tools/{tool_name}/execute**

Request Body:
```jsonc
{
  "spider_name": "generic_web",
  "keywords": ["采购", "ERP"],
  "max_pages": 20,
  "async_mode": false,
  "webhook_url": null,
  "agent_id": "openclaw-demo"
}
```

Response (async_mode=true):
```jsonc
{
  "code": 0,
  "msg": "任务已入队",
  "data": {
    "tool_name": "spider_run",
    "status": "PENDING",
    "estimated_completion_at": 1234567890
  },
  "trace_id": "oc_abc123",
  "task_id": "oc_8f1a9b0c7e",
  "timestamp": 1234567890
}
```

Response (async_mode=false):
```jsonc
{
  "code": 0,
  "msg": "执行完成",
  "data": {
    "collected_count": 50,
    "cleaned_count": 45,
    "items": [
      {"title": "XXX采购公告", "source": "gov", "industry_masked": "***"}
    ]
  },
  "trace_id": "oc_abc123",
  "task_id": "oc_8f1a9b0c7e",
  "timestamp": 1234567890
}
```

**POST /api/v1/tasks/enqueue**

Request Body:
```jsonc
{
  "tool_name": "spider_run",
  "params": {"spider_name": "generic_web", "keywords": ["采购"]},
  "webhook_url": "https://openclaw.example.com/webhook",
  "agent_id": "openclaw-demo"
}
```

**GET /api/v1/tasks/{task_id}**

Response:
```jsonc
{
  "code": 0,
  "msg": "OK",
  "data": {
    "task_id": "oc_xxx",
    "tool_name": "spider_run",
    "status": "RUNNING",
    "created_at": 1234567890,
    "started_at": 1234567891,
    "finished_at": null,
    "result_masked": null, // 完成时有值
    "error": null          // 失败时有值
  },
  "trace_id": "oc_abc123"
}
```

**Webhook 回调格式**：
```jsonc
// POST {webhook_url}（由网关在任务完成时自动触发）
{
  "task_id": "oc_xxx",
  "tool_name": "spider_run",
  "status": "SUCCESS",
  "result_masked": {...},    // 脱敏后的返回数据
  "error": null,
  "trace_id": "oc_abc123",
  "agent_id": "openclaw-demo",
  "timestamp": 1234567890
}
```

---

## 六、全链路 Trace 日志埋点规则

```
每个 HTTP 请求：
  1. 生成唯一 trace_id：oc_ + uuid.hex[:12]（或读取 X-Trace-Id）
  2. 写入：
     ├─► Response header: X-Trace-Id
     ├─► Logger 上下文：get_logger().bind(trace_id=xxx, agent_id=xxx, tool=xxx)
     └─► 异步任务 meta：task.meta.trace_id = xxx

日志字段统一：
  - trace_id（全链路唯一）
  - agent_id（从 X-Agent-Id 读取）
  - tool_name（被调用工具）
  - task_id（如有异步任务）
  - client_ip
  - path / method
  - latency_ms
  - status_code

示例日志：
[2026-07-03 21:09:50] INFO  openclaw.gateway | trace_id=oc_a1b2c3 agent_id=openclaw-demo tool=spider_run task_id=oc_8f1a9b0c7e client_ip=10.0.0.1 path=/api/v1/tools/spider_run/execute method=POST status=200 latency_ms=1234
```

---

## 七、工具注册中心映射（反射式）

**设计原则**：每个 registry 模块的 `run_*` / `async_run` / `list_*` 函数由 `tool_registry.py` 通过 `inspect.signature` 分析函数签名，自动生成 OpenClaw Skill JSON 的 inputs/outputs。

```python
# 注册表（在 adapter/tool_registry.py 中）
TOOL_REGISTRY = {
    # 爬虫
    "spider_list": {
        "module": "business.multi_spider.registry",
        "func": "list_spiders",
        "tool_type": "spider",
        "display_name": "列出所有可用爬虫",
        "description": "返回当前系统所有已注册爬虫名称和能力描述",
        "async_capable": False,
    },
    "spider_run": {
        "module": "business.multi_spider.registry",
        "func": "run_spider_by_name",
        "tool_type": "spider",
        "display_name": "运行指定爬虫",
        "description": "根据爬虫名称与关键词执行公域商机采集",
        "async_capable": True,
    },
    # 清洗
    "clean_run": {
        "module": "business.data_clean.registry",
        "func": "run_cleaning",
        "tool_type": "data_clean",
        "display_name": "数据清洗",
        "description": "对采集的商机进行去重、评分、合规过滤",
        "async_capable": True,
    },
    # 触达
    "send_batch": {
        "module": "business.customer_send.registry",
        "func": "run_batch",
        "tool_type": "customer_send",
        "display_name": "批量商机触达",
        "description": "同步执行邮件/企微/飞书批量触达（T11 复用）",
        "async_capable": False,
    },
    "send_async": {
        "module": "business.customer_send.registry",
        "func": "async_run",
        "tool_type": "customer_send",
        "display_name": "异步批量触达",
        "description": "入队后立即返回 task_id（T11 复用）",
        "async_capable": True,
    },
    # 销售
    "sales_assign": {
        "module": "business.sales_task.registry",
        "func": "assign",
        "tool_type": "sales_task",
        "display_name": "商机自动分配",
        "description": "按行业/地域/权重将商机分配给销售",
        "async_capable": True,
    },
    "sales_remind": {
        "module": "business.sales_task.registry",
        "func": "remind",
        "tool_type": "sales_task",
        "display_name": "多级提醒扫描",
        "description": "扫描待跟进商机，触发多级推送（T12 复用）",
        "async_capable": True,
    },
    "sales_transition": {
        "module": "business.sales_task.registry",
        "func": "transition",
        "tool_type": "sales_task",
        "display_name": "商机状态流转",
        "description": "将商机从当前状态流转到目标状态（如 FOLLOWING -> CLOSED_WON）",
        "async_capable": False,
    },
    "sales_add_tag": {
        "module": "business.sales_task.registry",
        "func": "add_tag",
        "tool_type": "sales_task",
        "display_name": "添加商机标签",
        "description": "给商机打标签",
        "async_capable": False,
    },
    "sales_remove_tag": {
        "module": "business.sales_task.registry",
        "func": "remove_tag",
        "tool_type": "sales_task",
        "display_name": "移除商机标签",
        "description": "",
        "async_capable": False,
    },
    "sales_record_follow": {
        "module": "business.sales_task.registry",
        "func": "record_follow_up",
        "tool_type": "sales_task",
        "display_name": "写入跟进记录",
        "description": "记录销售电话/邮件/会议跟进内容",
        "async_capable": False,
    },
    "sales_funnel_stats": {
        "module": "business.sales_task.registry",
        "func": "get_funnel_stats",
        "tool_type": "sales_task",
        "display_name": "商机转化漏斗统计",
        "description": "输出采集/清洗/触达/跟进/成交各环节转化率",
        "async_capable": False,
    },
}
```

---

## 八、分步执行开发流程

```
Step 1. 配置类：在 configs/settings.py 追加 AdapterSettings
   └─ env_prefix=""，支持 ADAPTER_* 前缀变量

Step 2. 基础模型：新增 adapter/models.py
   └─ Pydantic BaseModel：ToolExecuteRequest / TaskEnqueueRequest /
      TaskStatusResponse / ApiResponse / WebhookPayload

Step 3. 响应封装：新增 adapter/response.py
   └─ ok(data) / error(code, msg, data) 统一函数

Step 4. Trace 中间件：新增 adapter/middleware.py
   └─ X-Trace-Id 生成/传播，logger 上下文绑定

Step 5. 鉴权与限流：新增 adapter/auth.py
   └─ get_current_token(Depends) + check_ip_whitelist +
      check_agent_quota（Redis 原子计数器）

Step 6. 工具注册中心：新增 adapter/tool_registry.py
   └─ TOOL_REGISTRY 反射函数签名生成 inputs/outputs JSON；
      get_tool(tool_name) / list_tools() / execute_tool(tool_name, params)

Step 7. 入参出参适配与脱敏：新增 adapter/schema_adapter.py
   └─ normalize_request_payload() →
      mask_output(result) →（T06 PIIMask.auto_mask）

Step 8. 任务路由：新增 adapter/task_router.py
   └─ POST /enqueue（调用 infra.task_queue.enqueue）
      GET /{task_id}（调用 infra.task_queue.get_status）
      DELETE /{task_id}（调用 infra.task_queue.cancel）
      POST /{task_id}/webhook

Step 9. 工具执行路由：新增 adapter/tools_router.py
   └─ GET /api/v1/tools（注册 JSON）
      POST /api/v1/tools/{tool_name}/execute

Step 10. FastAPI 主入口：新增 adapter/main.py
   └─ include_router(task_router)、include_router(tools_router)
      mount /health / / 根路径
      全局异常处理（HTTPException / ValidationError / 通用 Exception → 触发告警）

Step 11. 重新导出：重写 adapter/__init__.py
   └─ expose app, TOOL_REGISTRY, mask_output

Step 12. OpenClaw Skill 配置示例：新增 examples/openclaw_skills_demo.yaml
   └─ 3-4 个典型工具的 YAML 配置，可直接复制到 OpenClaw

Step 13. 单元测试：新增 tests/test_t13_openclaw_adapter.py
   └─ 覆盖鉴权(401/403)、限流(429)、工具注册 JSON、
      任务下发/状态查询/取消、脱敏、trace_id 一致性等

Step 14. 最终验证：pytest 全部通过 + uvicorn 本地启动可请求
Step 15. 提交：feat(T13) 完成 OpenClaw 适配网关
```

---

## 九、依赖与风险

**新增依赖（已在 requirements.txt 中）**：
- `fastapi>=0.110.0`
- `uvicorn[standard]>=0.27.0`
- `pydantic-settings`（已有，由 settings.py 使用）

**风险与应对**：

| 风险 | 影响 | 方案 |
|---|---|---|
| FastAPI 启动时依赖下层模块的 DB 初始化失败 | 网关无法启动 | lazy-load：仅在执行时初始化 DB/Redis，启动不阻塞 |
| Redis 不可用，限流失效 | 无法限流，但不中断业务 | auth.py 中捕获 redis.ConnectionError，降级为"无限流"，同时告警 |
| 工具内部抛出未捕获异常 | HTTP 500 | 全局异常处理器捕获 → 记录 full trace → 触发 `alert_service` → 响应体保持标准化 JSON |
| Webhook 回调失败 | 通知丢失 | 3 次指数退避重试，失败记录日志 + 告警 |
| 未脱敏数据被返回给 OpenClaw | 隐私泄露 | `schema_adapter.py` 的 `mask_output()` 在 **所有** 非错误响应前强制调用；`auto_mask(deep=True)` 递归 |
| Trace ID 传播断开 | 日志无法追溯 | middleware + task.meta 双记录，任务 worker 读取 meta.trace_id 注入上下文 |

**约束满足情况**：
- ✅ 不新增/删除/重命名目录（仅在 `adapter/` 内新增文件，新增 `examples/` 目录为配置示例，符合"配置文件可新增"）
- ✅ Token、限流阈值、Webhook URL 全部来自 `.env` 的 `ADAPTER_*` 变量
- ✅ 业务逻辑全部复用下层 `business/*` 和 `infra/*`，不重复实现采集/清洗/发送
- ✅ 所有输出通过 T06 `PIIMask.auto_mask()` 脱敏
- ✅ 鉴权失败 / 超限 / 工具异常自动记录日志并触发全局告警
