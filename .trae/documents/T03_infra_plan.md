# T03 · Redis 异步任务队列 + APScheduler 分布式定时调度 基建 Plan

> 基于 T01 项目骨架与 T02 日志/异常/告警基建，在 infra 层新增纯底层调度能力。

---

## 一、仓库研究结论

1. **目录结构**：`infra/` 已存在 6 个文件（`__init__.py`、`logger_setup.py`、`exceptions.py`、`exception_handler.py`、`alerting.py`、`response.py`）；`configs/settings.py` 已提供日志/告警/项目三类配置
2. **依赖**：`requirements.txt` 已包含 `redis>=5.0.0`、`APScheduler>=3.10.4`，无需新增依赖
3. **现有基建可复用**：`get_logger(__name__)` 统一日志、`ErrorCode` 错误码体系、`BizException` 异常类、`alert_service` 告警推送、`ApiResponse` 响应结构
4. **禁止修改**：`README.md` / `DEVELOP_RULES.md` / `TASK_LIST.md`
5. **不新增目录**：全部文件直接放在 `infra/` 下；配置字段合并进 `configs/settings.py`

---

## 二、本次新增文件完整清单

| # | 文件（完整路径） | 核心功能 |
|---|----------------|---------|
| 1 | `configs/settings.py`（修改） | 在现有 `AppSettings` 中新增 `queue: QueueSettings` 与 `scheduler: SchedulerSettings` 两个分组；追加 `.env.example` 对应 key |
| 2 | `infra/redis_client.py` | `RedisClient` 单例：连接池、自动重连、心跳、超时控制；统一 `get_client()` / `acquire()` 对外 API |
| 3 | `infra/task_queue.py` | 通用异步任务队列：`enqueue()` 入队、消费者 worker、任务序列化、唯一 ID、FIFO/LIFO 队列；状态查询 |
| 4 | `infra/task_scheduler.py` | 封装 `APScheduler`：`start()` / `add_cron()` / `add_interval()` / `add_date()` / `remove_job()` / `list_jobs()`；与 Redis 任务状态存储解耦 |
| 5 | `infra/task_states.py` | 任务状态枚举 `TaskStatus`、状态存储 hash 键规则、`TaskMeta` dataclass 与读写 API |
| 6 | `infra/task_exceptions.py` | `TaskTimeoutError` / `TaskRetryExceededError` / `TaskCancelledError` / `TaskNotFoundError` 四个 T03 专用异常 |
| 7 | `tests/test_t03_infra.py` | 单元测试：Redis client 单例、队列 enqueue+dequeue、状态读写、APScheduler add/remove、任务超时与重试（使用 `fakeredis` mock 或 pytest 自定义 fixture 拦截） |

> 不新增目录；不修改 README / DEVELOP_RULES.md / docs/TASK_LIST.md。

---

## 三、每个文件核心功能、类与方法设计说明

### 3.1 configs/settings.py（修改）

在现有 `AppSettings` 中追加两个分组字段：

```python
@dataclass  # 或 Pydantic BaseSettings 的子 Model（沿用 T02 风格）
class QueueSettings:
    QUEUE_REDIS_HOST: str = "127.0.0.1"
    QUEUE_REDIS_PORT: int = 6379
    QUEUE_REDIS_PASSWORD: str = ""
    QUEUE_REDIS_DB: int = 1
    QUEUE_NAME: str = "openclaw:queue:default"
    QUEUE_POOL_SIZE: int = 10
    QUEUE_POOL_TIMEOUT: float = 30.0          # 连接池等待超时
    QUEUE_TASK_TIMEOUT: float = 300.0         # 单个任务执行超时
    QUEUE_MAX_RETRIES: int = 3
    QUEUE_RETRY_BACKOFF: float = 2.0          # 指数退避基数（秒）
    QUEUE_WORKER_CONCURRENCY: int = 4         # 同时消费的 worker 协程数
    QUEUE_BPOP_TIMEOUT: float = 5.0           # 单次 bpop 等待时间

class SchedulerSettings:
    SCHEDULER_ENABLED: bool = True
    SCHEDULER_TIMEZONE: str = "Asia/Shanghai"
    SCHEDULER_MAX_CONCURRENT: int = 10
    SCHEDULER_MISFIRE_GRACE_TIME: int = 60     # 错过多久仍补执行
    SCHEDULER_COALESCE: bool = True
    SCHEDULER_JOBSTORES_REDIS: bool = False    # 可选：用 Redis 持久化 job
    SCHEDULER_STORE_PREFIX: str = "openclaw:scheduler"
```

在 `.env.example` 中同步追加以上 key（README 等禁止文件不动）。

---

### 3.2 infra/redis_client.py — Redis 单例连接池

**类 `RedisClient`（单例）**：

| 方法 | 说明 |
|------|------|
| `__new__ / _instance` | 单例保证 |
| `_build_pool() -> ConnectionPool` | 用 `redis.ConnectionPool` 创建统一连接池；读取 settings 中的 host/port/password/db/pool_size |
| `acquire() -> Redis` | 返回一个 `redis.Redis(pool=...)` 句柄；惰性初始化；每次调用都是同一 pool 上的轻量句柄 |
| `ping(fail_silently: bool = True) -> bool` | 心跳；失败记录告警日志 |
| `close()` | 关闭连接池（进程退出时调用，可选） |

**异常处理**：
- 连接失败时内部重连（`backoff` 指数退避最多 `QUEUE_POOL_TIMEOUT` 秒，或最多 N 次）
- 严重失败触发 `alert_service.service_exception_async("redis unreachable", ...)`

**模块级导出**：

```python
redis_client: RedisClient = RedisClient()

def get_redis() -> Redis:
    return redis_client.acquire()
```

---

### 3.3 infra/task_states.py — 任务状态存储

**类 `TaskStatus(str, Enum)`**：
```
PENDING   = "pending"    # 待执行
RUNNING   = "running"    # 执行中
SUCCESS   = "success"    # 执行成功
FAILED    = "failed"     # 执行失败
CANCELLED = "cancelled"  # 已取消
```

**类 `TaskMeta`（pydantic BaseModel / dataclass）**：
```python
task_id: str
name: str
payload: dict             # JSON 可序列化参数
status: TaskStatus
retries: int = 0
max_retries: int = settings.queue.QUEUE_MAX_RETRIES
created_at: float
started_at: float | None = None
finished_at: float | None = None
error: str | None = None
traceback: str | None = None
source: str = "queue"     # "queue" | "scheduler"
```

**Redis 存储结构**（由 queue 与 scheduler 共用读写）：

| Key | 类型 | 内容 | TTL |
|-----|------|------|-----|
| `openclaw:task:meta:<task_id>` | HASH | `name / status / retries / created_at / started_at / finished_at / error / traceback` | 7 天（任务归档周期，可配） |
| `openclaw:task:index:<source>` | ZSET | `task_id -> created_at(ts)`，用于按时间范围查询 | 同 TTL |

**对外 API**：

```python
def create_meta(meta: TaskMeta) -> None
def update_meta(task_id: str, **fields: Any) -> None
def get_meta(task_id: str) -> TaskMeta | None
def list_meta(source: str, since: float | None = None, limit: int = 100) -> list[TaskMeta]
def cancel_task(task_id: str) -> bool
```

---

### 3.4 infra/task_queue.py — 通用异步任务队列

**对外数据模型**（入队参数）：

```python
TaskFn = Callable[..., Awaitable[Any]]     # 任务执行函数必须是 async

async def enqueue(
    func: TaskFn | str,                     # 支持传函数对象，或 "module.path:func_name" 字符串（便于 worker 跨进程解析）
    *args: Any,
    kwargs: dict[str, Any] | None = None,
    task_name: str | None = None,
    max_retries: int | None = None,
    timeout: float | None = None,
) -> str:
    """入队一个任务，返回 task_id（UUID4）。"""

async def get_status(task_id: str) -> TaskMeta | None
async def cancel(task_id: str) -> bool
async def list_tasks(since: float | None = None, limit: int = 100) -> list[TaskMeta]
```

**Redis 队列结构**：

| Key | 类型 | 内容 |
|-----|------|------|
| `openclaw:queue:ready` | LIST | 待执行任务 `task_id`；FIFO 用 `LPUSH + BRPOP` |
| `openclaw:queue:payload:<task_id>` | STRING | JSON 字符串：`{"func":"module.path:name","args":[],"kwargs":{},"max_retries":3,"timeout":300}` |
| `openclaw:task:meta:<task_id>` | HASH | 由 `task_states.py` 统一管理 |

**Worker 消费循环**（在独立 Python 进程中由用户启动）：

```python
async def run_worker(concurrency: int | None = None) -> None:
    """协程 worker，每个 task 独立 asyncio task。"""
```

**执行流程**：
1. `BRPOP openclaw:queue:ready <BPOP_TIMEOUT>` → 拿到 `task_id`
2. 读取 payload + meta，将 meta.status 改为 `RUNNING`
3. `asyncio.wait_for(coro, timeout=task.timeout)` 执行；超时触发 `TaskTimeoutError`
4. 成功 → meta 改为 `SUCCESS`，写日志 `get_logger("task_queue").info`
5. 失败：
   - 若 `retries < max_retries` → meta 计数+1，重新入队（加 `queue` key 到 ready），延迟 `BACKOFF ** retries` 秒
   - 否则 → `FAILED`，推送告警 `alert_service.task_failure_async(...)`
6. 任何异常 → 写入 meta.traceback；落盘日志由 `get_logger` 统一处理

**取消语义**：`cancel_task()` 将 meta 改为 `CANCELLED`，worker 在下一次 BRPOP 前检查该字段；若已开始执行则用 `asyncio.Event` 支持协作取消（可选）。

---

### 3.5 infra/task_scheduler.py — 分布式 APScheduler

**类 `TaskScheduler`（单例）**：

| 方法 | 说明 |
|------|------|
| `start()` | 惰性初始化 `BlockingScheduler` / `AsyncIOScheduler`（推荐 AsyncIOScheduler，便于和 FastAPI 事件循环共存）；从 settings 读取 timezone/max_concurrent/misfire_grace_time/coalesce |
| `stop()` | 优雅关闭 |
| `add_cron(job_id, func, *, cron_kwargs)` | 新增 cron 任务，返回 job_id |
| `add_interval(job_id, func, seconds/minutes/...)` | 新增间隔任务 |
| `add_date(job_id, func, run_date)` | 一次性定时任务 |
| `remove_job(job_id)` | 删除任务 |
| `get_job(job_id)` | 查询 Job |
| `list_jobs()` | 列出所有 Job（包含 next_run_time） |

**任务函数的签名统一**：`func(*args, **kwargs) -> Awaitable[Any]`；scheduler 内部通过 `asyncio.run_coroutine_threadsafe` 或直接 await（视调度器模式而定）。

**异常与告警接入**：
- 对每个注册 job 使用装饰器 `@_scheduler_job_wrapper`：
  1. `TaskMeta.source="scheduler"`，创建/更新 meta → `RUNNING`
  2. try/except 捕获；失败重试走 `QUEUE_MAX_RETRIES`（或独立 SCHEDULER_* 开关）
  3. 最终失败触发 `alert_service.task_failure_async(...)`
  4. 写 `get_logger("task_scheduler")` 日志

**Redis JobStore 可选**：
- 若 `SCHEDULER_JOBSTORES_REDIS=True`，调用 `scheduler.add_jobstore("redis", **redis_kwargs)` 使 job 定义持久化到 Redis，重启后保留；否则默认内存存储
- 默认关闭，保持最小依赖

---

### 3.6 infra/task_exceptions.py — 专用异常

```python
class TaskTimeoutError(BizException):   code = ErrorCode.TASK_TIMEOUT;   http_status = 504
class TaskRetryExceededError(BizException):  code = ErrorCode.TASK_RETRY_EXCEEDED; http_status = 500
class TaskCancelledError(BizException): code = ErrorCode.TASK_CANCELLED; http_status = 409
class TaskNotFoundError(BizException):  code = ErrorCode.TASK_NOT_FOUND; http_status = 404
class RedisUnreachableError(BizException): code = ErrorCode.REDIS_UNREACHABLE; http_status = 503
```

> 新的 `ErrorCode` 枚举值：`TASK_TIMEOUT / TASK_RETRY_EXCEEDED / TASK_CANCELLED / TASK_NOT_FOUND / REDIS_UNREACHABLE`，追加到 `infra/exceptions.py` 中。

---

### 3.7 tests/test_t03_infra.py — 单元测试

使用 `pytest + pytest-asyncio`；网络层用 `fakeredis` mock Redis，避免真实依赖：

| 测试用例 | 目的 |
|---------|------|
| `test_redis_client_singleton` | 多次调用返回同一单例；`acquire()` 可读写 |
| `test_enqueue_and_run_worker` | 入队一个简单协程；worker 消费并把状态置为 SUCCESS |
| `test_task_failure_and_retry` | 模拟任务抛错；验证重试次数达到上限后变为 FAILED 并触发告警（`alert_service` 被 mock） |
| `test_task_timeout` | 任务执行超过 `timeout` → `TaskTimeoutError` |
| `test_task_cancel` | 入队后取消 → worker 读到 CANCELLED 直接丢弃 |
| `test_task_state_query` | `list_tasks` / `get_meta` 返回正确字段 |
| `test_scheduler_add_remove_and_run` | 用 AsyncIOScheduler + short interval job，触发一次后移除 |
| `test_scheduler_cron_expression` | 解析 cron `* * * * *` 与中文时区下 next_run_time 合理 |
| `test_max_retries_from_env` | 覆盖 settings，验证重试次数上限会被尊重 |

**隔离策略**：每个测试用 `monkeypatch` 覆盖队列 key 前缀（`QUEUE_NAME` / `SCHEDULER_STORE_PREFIX`），避免用例间污染；测试结束清理 key。

---

## 四、Redis 队列数据存储结构、定时任务存储规则

### 4.1 异步任务队列

**键命名空间**：`openclaw:queue:*`（可通过 `configs.settings.queue.QUEUE_NAME` 替换前缀，实现多项目/多环境隔离）

| Key 格式 | 类型 | 说明 |
|----------|------|------|
| `<prefix>:ready` | LIST | LPUSH 入队，BRPOP 出队 |
| `<prefix>:payload:<task_id>` | STRING | JSON：`{func, args, kwargs, max_retries, timeout}` |
| `<prefix>:task:meta:<task_id>` | HASH | 元数据（状态/重试数/时间戳/错误） |
| `<prefix>:task:index:<source>` | ZSET | `task_id -> created_at`，用于范围查询 |

**TTL**：任务完成后写入 meta 与 index 的 TTL 为 `7 * 24 * 3600` 秒（可配），之后自动过期，避免无限增长。

### 4.2 定时任务

| Key 格式 | 类型 | 说明 |
|----------|------|------|
| `<store_prefix>:meta:<task_id>` | HASH | 同 4.1，`source="scheduler"` |
| `<store_prefix>:index` | ZSET | `task_id -> next_run_ts`（可选，便于展示 dashboard） |
| `<store_prefix>:jobstore:*` | 由 `RedisJobStore` 内部管理 | 仅在开启 `SCHEDULER_JOBSTORES_REDIS` 时存在 |

**存储规则**：
- `job_id` 由调用方传入（建议形如 `biz:<module>:<name>`），在本模块内做唯一性检查；冲突返回 `BizException(code=TASK_CONFLICT)`
- `func` 支持传字符串 `"module.path:func_name"`，由 wrapper 动态 import，利于跨进程调度；若传函数对象（同进程内使用），直接引用

---

## 五、分步执行开发流程

| 步骤 | 操作 | 产出 |
|------|------|------|
| 1 | `configs/settings.py` 追加 `QueueSettings` + `SchedulerSettings`；`.env.example` 补充 Redis/队列/调度器 key；`infra/exceptions.py` 追加 `ErrorCode` 新增项 | 配置 & 错误码就绪 |
| 2 | `infra/task_exceptions.py` 定义任务专用异常；`infra/task_states.py` 定义 `TaskStatus/TaskMeta` & Redis 读写 | 状态存储就绪 |
| 3 | `infra/redis_client.py` 实现 `RedisClient` 单例 + `get_redis()`；在 worker 与 scheduler 中通过它获取连接 | Redis 连接就绪 |
| 4 | `infra/task_queue.py` 实现 `enqueue / get_status / list_tasks / cancel` + `run_worker()`；消费循环内接入 T02 日志与告警 | 队列底座就绪 |
| 5 | `infra/task_scheduler.py` 实现 `TaskScheduler` 单例；封装 `start/stop/add_cron/add_interval/add_date/remove_job/list_jobs/get_job`；job 装饰器接入 T02 告警 | 调度器就绪 |
| 6 | `tests/test_t03_infra.py` 覆盖 3.7 中的 9 条用例；`pytest -v` 本地全量通过 | 测试闭环 |
| 7 | Git 提交（`feat(T03): ...`）；保留一次压扁 commit（按用户规范） | 交付 |

---

## 六、潜在依赖 / 注意事项 / 风险处理

| 事项 | 说明 | 风险处理 |
|------|------|---------|
| Python 版本 | `FastAPI + APScheduler 3.10` 需要 Python ≥ 3.8；本项目 Python 3.14 无问题 | 无 |
| Redis 依赖 | `redis>=5.0.0` 已在 requirements.txt | 如本地缺 redis，测试用 `fakeredis`，不依赖真实实例 |
| `fakeredis` 可选测试依赖 | 不在 requirements.txt 中；可选测试依赖 | 在测试代码顶部 `try: import fakeredis except: pytest.skip(...)` 自动降级 |
| worker 跨进程 | `enqueue(func)` 的 `func` 若为字符串 `"module.path:name"`，worker 需在同代码库环境；**使用方需保证模块路径一致** | 文档说明 & 入队时 `func` 同时支持字符串与函数对象 |
| 任务超时 | `asyncio.wait_for(coro, timeout=...)` 与 `TaskTimeoutError` 配合 | wrapper 内统一处理，触发告警 |
| 取消语义 | worker 通过 meta 状态字段 `CANCELLED` 协作式取消 | 不做 `task.cancel()` 强取消（避免无法清理资源） |
| APScheduler 实例 | 推荐 `AsyncIOScheduler`，在 FastAPI `lifespan` 中 `scheduler.start() / .stop()` | 与主事件循环共存；`start()` 幂等，多次调用安全 |
| 分布式 | 默认不启用 `RedisJobStore`，但提供开关；多实例共享 job 定义时打开 | 在 docs 中补充开关说明 |
| 告警抖动 | 高失败率可能导致告警风暴 | wrapper 内做 "同一 task_id 10 分钟内只告警一次" 的内存级节流（用 `dict[task_id] -> last_ts`） |

---

## 七、强制约束自检（对照 DEVELOP_RULES.md）

- ✅ 架构规范：全部放入 `infra/`；不侵入 `core / business / adapter / web_admin`
- ✅ 代码规范：PEP8；类名大驼峰；函数/变量小蛇形；常量大写；所有公共函数附 docstring
- ✅ 配置规范：所有可调项（Redis 地址、队列名、最大并发、重试次数、TTL、BPOP_TIMEOUT ...）全部来自 `settings`，通过 `.env` 控制；代码内零硬编码
- ✅ 异常规范：统一 `BizException` 派生；T03 定义 5 个专用异常；失败自动触发 T02 告警
- ✅ 日志规范：`get_logger("redis_client" / "task_queue" / "task_scheduler" / "task_states")` 分类打日志
- ✅ 响应规范：对外暴露 `get_status / list_tasks` 等查询 API 返回值用 `ApiResponse` 包装
- ✅ 目录规范：不新增、不删除、不重命名现有目录；所有新增代码全部落盘 `infra/`
- ✅ 禁止文档修改：`README / DEVELOP_RULES / docs/TASK_LIST` 不动
