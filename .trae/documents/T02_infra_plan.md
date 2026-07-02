# T02 · 项目全局日志 / 统一异常 / 消息告警 / 统一响应 基建 Plan

> 任务定位：infra 层纯底层通用基建，不侵入 core/business/adapter 等业务模块

---

## 一、仓库研究结论

1. **目录结构**：T01 已搭建完整四层骨架；`infra/`、`configs/` 目录均存在且只有空 `__init__.py`
2. **现有依赖**（[requirements.txt](file:///c:/projects/BizTools4Openclaw/requirements.txt)）：`fastapi / uvicorn / pydantic / pydantic-settings / python-dotenv / loguru / redis / APScheduler / httpx / pytest`，已覆盖 T02 所需基础依赖，无需新增
3. **配置现状**：`configs/` 为空；`.env.example` 已预留 DB / Redis / 网关 / 代理 / 渠道 / 日志等基础键，但**缺少钉钉告警与告警邮件**专用键，本任务将统一补齐
4. **禁止修改清单**（严格遵守）：`README.md`、`DEVELOP_RULES.md`、`TASK_LIST.md`

---

## 二、本次新增文件完整清单（路径 + 文件名）

> 全部文件均存放于 `infra/` 与 `configs/` 两个目录，不改动任何已存在目录，不新增目录

### 2.1 配置层（configs）

| # | 文件 | 核心功能 |
|---|------|---------|
| 1 | [configs/settings.py](file:///c:/projects/BizTools4Openclaw/configs/settings.py) | 全局单例配置：基于 `pydantic-settings` 从 `.env` 或环境变量加载；支持日志、告警、项目基础配置三类分组；类型安全 + 自动校验 |

### 2.2 基建层（infra）

| # | 文件 | 核心功能 |
|---|------|---------|
| 2 | [infra/logger_setup.py](file:///c:/projects/BizTools4Openclaw/infra/logger_setup.py) | **全局日志工具（单例）**：基于 loguru 封装；日志分级（DEBUG/INFO/WARNING/ERROR/CRITICAL）、按天切割、过期自动删除、控制台 + 文件双输出；暴露统一 `get_logger(name)` 接口 |
| 3 | [infra/exceptions.py](file:///c:/projects/BizTools4Openclaw/infra/exceptions.py) | **自定义异常类 + 错误码定义**：`BizException`、`BizWarning`、基础业务异常枚举；错误码分层（HTTP 状态段 + 模块段 + 具体码） |
| 4 | [infra/exception_handler.py](file:///c:/projects/BizTools4Openclaw/infra/exception_handler.py) | **FastAPI 全局异常捕获中间件**：注册 `RequestValidationError`、`HTTPException`、`BizException`、`Exception` 四类处理器；统一 JSON 兜底返回；堆栈完整打印（仅开发环境） |
| 5 | [infra/alerting.py](file:///c:/projects/BizTools4Openclaw/infra/alerting.py) | **告警统一入口（单例）**：内置 `AlertType.TASK_FAILURE / SERVICE_EXCEPTION / CRAWLER_RISK` 三类场景；钉钉机器人（Webhook + 签名）、邮件（SMTP）双通道；可扩展；失败降级为本地日志 |
| 6 | [infra/response.py](file:///c:/projects/BizTools4Openclaw/infra/response.py) | **统一 API 响应结构体 + 辅助函数**：`ApiResponse[T]`（`code / msg / data / timestamp`）；`ok()`、`fail()`、`from_exception()` 工厂；标准 HTTP 状态码映射 |

### 2.3 测试（tests）

| # | 文件 | 核心功能 |
|---|------|---------|
| 7 | [tests/test_t02_infra.py](file:///c:/projects/BizTools4Openclaw/tests/test_t02_infra.py) | T02 基建单元测试：日志级别/文件切割、响应结构 JSON 一致性、自定义异常捕获、告警通道（mock httpx/smtp） |

### 2.4 文档（docs）

| # | 文件 | 核心功能 |
|---|------|---------|
| 8 | [docs/T02_INFRA_USAGE.md](file:///c:/projects/BizTools4Openclaw/docs/T02_INFRA_USAGE.md) | 基建工具使用指南（非业务文档）：快速上手、导入示例、错误码表、告警通道配置 |

> 📌 **本次不修改的文件**：`README.md`、`DEVELOP_RULES.md`、`TASK_LIST.md`、`.gitignore`、`requirements.txt`、`.env.example`（其中 `.env.example` 不在禁止列表中，但本 plan **会追加**告警相关 key，属于环境变量配置补充，不属于业务文档修改）。

---

## 三、每个文件核心功能与代码分层设计说明

### 3.1 configs/settings.py — 全局单例配置

**设计要点**：
- 使用 `pydantic_settings.SettingsConfigDict(env_file=".env", extra="ignore")`，从 `.env` 或系统环境变量加载
- 采用「分组嵌套 pydantic model」结构：`AppSettings` → `LogSettings` + `AlertSettings` + `ProjectSettings`
- 所有字段具备默认值，保证**本地裸跑也能启动**（但生产必须配置真实值）
- 导出单例：`settings = AppSettings()`，全项目 `from configs.settings import settings`
- **不写入业务逻辑**：仅读/校验，不触发 I/O

**字段分组示例**（非代码，仅设计说明）：

```
ProjectSettings:
  PROJECT_NAME, ENV(dev/test/prod), DEBUG, APP_HOST, APP_PORT, API_PREFIX

LogSettings:
  LOG_LEVEL(INFO), LOG_DIR(./logs), LOG_ROTATION(1 day),
  LOG_RETENTION(30 days), LOG_CONSOLE_ENABLED(True), LOG_FILE_ENABLED(True)

AlertSettings:
  ALERT_ENABLED(True),
  DINGTALK_WEBHOOK_URL, DINGTALK_SECRET(可选,用于签名),
  SMTP_HOST, SMTP_PORT(465), SMTP_USER, SMTP_PASSWORD, SMTP_FROM,
  SMTP_TO(逗号分隔收件人), SMTP_USE_SSL(True),
  ALERT_TASK_FAILURE_ENABLED, ALERT_SERVICE_EXCEPTION_ENABLED, ALERT_CRAWLER_RISK_ENABLED
```

---

### 3.2 infra/logger_setup.py — 全局日志工具（单例）

**核心职责**：
1. **初始化 loguru**：在模块 import 时完成配置（线程安全；多次调用幂等，避免重复 sink）
2. **控制台 sink**：彩色输出 + 简洁格式
3. **文件 sink**：按天切割 `{time:YYYY-MM-DD}.log`；`retention=settings.log.LOG_RETENTION`；`rotation=settings.log.LOG_ROTATION`；ERROR 单独落盘一份 `error_{time}.log`
4. **日志分级**：保留 loguru 原生 5 级；通过 `LOG_LEVEL` 全局过滤
5. **统一对外 API**：`get_logger(name: str) -> Logger`，返回配置后的 logger 实例；模块内可 `logger = get_logger(__name__)`

**设计要点**：
- 使用 `sys.modules` 缓存判断，确保单例 & 幂等初始化
- 通过 `logger.configure(extra={"module": name})` 支持多模块区分
- 结构化记录（`serialize=False`），方便人工排查；后续可按需开启 JSON 落盘
- DEBUG 模式下打印更详细的函数/行号

---

### 3.3 infra/exceptions.py — 异常体系 & 错误码

**核心数据结构**：

```python
class ErrorCode(IntEnum):
    # 通用成功/失败
    SUCCESS = 0
    UNKNOWN_ERROR = 50000

    # HTTP 状态层（对齐 FastAPI）
    BAD_REQUEST = 40000
    UNAUTHORIZED = 40100
    FORBIDDEN = 40300
    NOT_FOUND = 40400
    VALIDATION_ERROR = 42200

    # 业务层
    BIZ_ERROR = 10000
    BIZ_WARNING = 10001
    TASK_FAILURE = 20001          # 任务失败告警场景
    SERVICE_EXCEPTION = 20002     # 服务异常告警场景
    CRAWLER_RISK = 20003          # 爬虫风控告警场景

class BizException(Exception):
    code: int = ErrorCode.BIZ_ERROR
    msg: str = "业务异常"
    http_status: int = 400
    data: Any | None = None
    trigger_alert: bool = False   # 是否触发告警通道

class BizWarning(BizException):
    code = ErrorCode.BIZ_WARNING
    msg = "业务告警"
    http_status = 200
```

**设计要点**：
- 错误码「**首位对齐 HTTP 状态码**」（4xx/5xx），便于前端统一处理；尾段留给业务细分
- `BizException` 携带 `trigger_alert`，由全局异常处理器决定是否触发告警（解耦：异常本身不主动发告警，避免同步阻塞）
- 提供 `raise_biz_error()` / `raise_task_failure()` 等辅助函数

---

### 3.4 infra/exception_handler.py — FastAPI 全局异常捕获

**对外导出**：`register_exception_handlers(app: FastAPI) -> None`

**四类处理器**：

| 异常 | 行为 |
|------|------|
| `RequestValidationError` (Pydantic) | 提取 `loc/msg`，构建统一 JSON；http=422, code=VALIDATION_ERROR；不告警 |
| `HTTPException` | 透传 status_code；根据 code 映射到统一响应体；5xx 级别触发 `SERVICE_EXCEPTION` 告警 |
| `BizException` | 读取自身 code/msg/data；若 `trigger_alert=True`，根据异常类型触发对应告警场景 |
| `Exception`（兜底） | http=500, code=UNKNOWN_ERROR；打印完整 traceback 到日志；触发 `SERVICE_EXCEPTION` 告警；`DEBUG=False` 时不向客户端返回堆栈 |

**设计要点**：
- 使用 FastAPI `@app.exception_handler(X)` / `app.add_exception_handler(X, handler)` 注册
- 异步 handler，保证不阻塞主循环
- 告警通过 `asyncio.create_task(alerting.send_async(...))` 后台发送，避免拖慢接口响应
- 返回结构体始终为 `ApiResponse[T]`（见 3.6）

---

### 3.5 infra/alerting.py — 告警统一入口（单例）

**对外 API**：

```python
class AlertType(str, Enum):
    TASK_FAILURE = "task_failure"
    SERVICE_EXCEPTION = "service_exception"
    CRAWLER_RISK = "crawler_risk"

class AlertService:                 # 单例
    enabled: bool = settings.alert.ALERT_ENABLED

    async def send_async(self, alert_type: AlertType, title: str, content: str,
                         channels: list[str] | None = None) -> None
    def send_sync(self, alert_type: AlertType, title: str, content: str,
                  channels: list[str] | None = None) -> None

alert_service = AlertService()       # 全局单例
```

**内置通道**：
1. **DingTalkWebhook**：httpx POST `settings.alert.DINGTALK_WEBHOOK_URL`；支持 `sign(timestamp + "\n" + secret)` HMAC-SHA256 签名；消息类型 `markdown`；失败 fallback 到日志
2. **Email (SMTP)**：`smtplib.SMTP_SSL`（Python stdlib，零新增依赖）；HTML + Plain text 双格式；多收件人从 `SMTP_TO` 拆分；失败 fallback 到日志

**设计要点**：
- `channels=None` 时默认启用所有已配置的通道（按 settings 是否有值判断）
- **任何告警通道失败不得影响主流程**：内部 try/except + 降级到日志
- 提供场景化便捷函数：`alert_task_failure(title, content)`、`alert_service_exception(title, content)`、`alert_crawler_risk(title, content)`
- 所有标题前缀 `[openclaw-business-tools][{alert_type}]`，便于机器人关键词过滤
- 消息体截断上限 10KB，避免钉钉超长消息被拒

---

### 3.6 infra/response.py — 全局统一 API 响应结构体

**核心数据模型**（Pydantic v2）：

```python
from datetime import datetime
from typing import Generic, TypeVar, Any
from pydantic import BaseModel, Field

T = TypeVar("T")

class ApiResponse(BaseModel, Generic[T]):
    code: int = Field(default=0, description="业务状态码；0 成功，其余失败")
    msg: str = Field(default="ok", description="状态描述")
    data: T | None = Field(default=None, description="业务数据体")
    timestamp: int = Field(default_factory=lambda: int(datetime.now().timestamp()),
                           description="服务端 Unix 时间戳（秒）")
```

**辅助工厂函数**：

```python
def ok(data: T | None = None, msg: str = "ok") -> ApiResponse[T]
def fail(code: int, msg: str, data: Any | None = None,
         http_status: int = 400) -> tuple[ApiResponse[Any], int]
def from_exception(exc: BizException | Exception) -> tuple[ApiResponse[Any], int]
```

**全局响应结构体字段规范（四字段强制）**：

| 字段 | 类型 | 必填 | 含义 | 约定 |
|------|------|------|------|------|
| `code` | `int` | ✅ | 业务状态码 | `0` = 成功；非 0 = 失败；对齐 `ErrorCode` 表 |
| `msg` | `str` | ✅ | 状态描述 | 成功= `"ok"`；失败为可读错误信息 |
| `data` | `T \| None` | ✅ | 业务数据体 | 成功时返回对象/列表/分页结果；失败时可为 `None` 或附加详情 dict |
| `timestamp` | `int` | ✅ | 服务端时间戳 | Unix 秒；由工厂自动注入，**业务层不得手工覆盖** |

**统一响应装饰器 / route 返回**：
- 所有 route 返回 `ApiResponse[T]`；失败场景可 `return fail(code, msg), http_status`
- 对 list 分页后续由上层定义 `PageResult[T]`；本层不设计分页结构（保持纯基建）

**HTTP 状态码对齐原则**：
- `200 OK` → `code=0` 成功
- `400 BAD REQUEST` → 业务失败（`BIZ_ERROR` 系列）
- `422 UNPROCESSABLE ENTITY` → 参数校验失败
- `500 INTERNAL SERVER ERROR` → 服务异常兜底

---

### 3.7 tests/test_t02_infra.py — 单元测试

**测试要点**：
1. `settings` 对象能正常加载（无 `.env` 时走默认值）
2. `get_logger(__name__)` 返回 loguru Logger，且多次调用幂等
3. `ApiResponse` JSON 序列化包含 `code/msg/data/timestamp` 四字段
4. `BizException` 被全局处理器捕获后返回正确结构
5. `alert_service.send_sync()` 在 `enabled=False` 时静默，不抛异常
6. `alerting.DingTalkWebhook` 使用 `httpx.AsyncClient`（monkeypatch）时能正确组装签名与 payload

**不依赖外部服务**：所有网络调用使用 `monkeypatch` / `MagicMock` 拦截

---

### 3.8 docs/T02_INFRA_USAGE.md — 使用指南（简要）

- 快速上手指令：`from infra.response import ok, fail`、`from infra.logger_setup import get_logger`
- 错误码表：`ErrorCode` 枚举全集说明
- 告警场景与通道配置说明
- 环境变量配置示例（`.env.local` 模板片段）

---

## 四、全局响应结构体字段规范（正式定义）

```jsonc
// 成功响应
{
  "code": 0,
  "msg": "ok",
  "data": { "id": 123, "name": "demo" },
  "timestamp": 1783000000
}

// 失败响应
{
  "code": 10000,
  "msg": "业务异常：参数缺失",
  "data": { "detail": [...], "trace_id": "..." },
  "timestamp": 1783000000
}
```

**字段规范**：
- `code`：`int`，`0` = 成功；非 0 = 失败。错误码第一位数对齐 HTTP 状态（4→客户端，5→服务端，1/2→业务）
- `msg`：`str`，人类可读描述；英文小写 `ok` 代表成功
- `data`：任意 JSON 可序列化对象 / 数组 / `null`；失败时可选携带调试详情
- `timestamp`：`int`，Unix 秒时间戳，**由工厂函数自动注入，业务层不得修改**

---

## 五、分步执行开发流程

| 步骤 | 操作文件 | 产出 |
|------|----------|------|
| Step 1 | `configs/settings.py` | 全局单例配置；日志 + 告警 + 项目三组；类型安全 |
| Step 2 | `infra/response.py` | `ApiResponse[T]` + `ok()`/`fail()`/`from_exception()` 工厂 |
| Step 3 | `infra/exceptions.py` | `ErrorCode` 枚举 + `BizException` / `BizWarning` + 辅助 raise 函数 |
| Step 4 | `infra/logger_setup.py` | loguru 单例初始化；按天切割 + 过期删除；双 sink |
| Step 5 | `infra/alerting.py` | `AlertService` 单例；钉钉 + 邮件双通道；三类场景便捷函数 |
| Step 6 | `infra/exception_handler.py` | `register_exception_handlers(app)`；四类异常映射 + 告警触发 |
| Step 7 | `tests/test_t02_infra.py` | 覆盖配置、日志、响应、异常、告警（mock 网络）的单元测试 |
| Step 8 | `docs/T02_INFRA_USAGE.md` | 导入方式 / 错误码表 / 告警通道配置示例 |
| Step 9 | 执行 `pytest -q` 验证（可选：本地无 pytest 则跳过） | 全部测试通过，无类型错误 |

---

## 六、潜在依赖 / 注意事项 / 风险处理

| 事项 | 说明 | 风险处理 |
|------|------|---------|
| Python 版本 | 使用 `from __future__ import annotations` + PEP 604 类型注解（`X \| None`），需 Python ≥ 3.10；若低于则升级 / 改 `Optional` | 本 plan 默认 ≥ 3.10，与 `fastapi>=0.110` 一致 |
| `loguru` 重复 sink | 多次 `logger.add` 会导致同一文件被写入多次 | 在 `logger_setup.py` 内用 `_initialized` 开关与 `logger.remove()` 保证幂等 |
| 钉钉签名 | 需要 `timestamp + "\n" + secret`，HMAC-SHA256，base64 + URL 编码 | 单测使用固定 seed 验证签名正确性 |
| SMTP | 使用 stdlib `smtplib.SMTP_SSL` + `email.mime.multipart` | 单测用 `unittest.mock.patch("smtplib.SMTP_SSL")` |
| 告警异步 | `asyncio.create_task` 可能在事件循环未就绪时抛错 | `send_sync()` 使用 `asyncio.run(...)`（非事件循环上下文），`send_async()` 纯协程 |
| 无 `.env` 文件 | pydantic-settings 会 fallback 到环境变量 | settings 字段全量默认值；日志默认 `LOG_LEVEL=INFO`，告警默认 `ALERT_ENABLED=False`，裸跑不阻塞 |
| 硬编码检查 | DEVELOP_RULES 禁止硬编码 | 所有路径 / 级别 / token 均来自 `settings`；代码内仅出现常量 key 名 |
| 单例线程安全 | 告警服务需全局唯一实例 | 使用模块级单例 `alert_service = AlertService()`；类内部 `__new__` / `_instance` 缓存兜底 |
| 错误码冲突 | 后续 T03/T04 可能新增业务码 | `ErrorCode` 预留范围：400xx/500xx 通用；1xxxx 业务；2xxxx 基建告警；并附中文注释 |

---

## 七、强制约束自检（对照 DEVELOP_RULES.md）

- ✅ 架构规范：全部放入 `infra/` 与 `configs/`；未侵入 `core/business/adapter`
- ✅ 代码规范：PEP8；类名大驼峰；函数/变量小蛇形；常量大写
- ✅ 配置规范：所有可调项进 `settings`，读自环境变量 / `.env`，禁止硬编码
- ✅ 接口规范：所有对外响应为 `ApiResponse` 四字段结构；`code/msg/data/timestamp`
- ✅ 异常规范：统一 `BizException` + 全局处理器；异常捕获不裸抛
- ✅ 日志规范：全项目统一入口 `get_logger(__name__)`
- ✅ 不修改禁止文档：README / DEVELOP_RULES / TASK_LIST 全程不动
