# T05 任务计划：开发底层爬虫核心通用 SDK

> 定位：`core/spider_core/` —— 全平台统一爬虫能力底座。业务采集逻辑（平台专属爬虫）统一放在 `business/multi_spider/`，本计划不涉及。

---

## 一、Repo 调研结论（执行前快照）

1. **目录结构**：`core/spider_core/` 已存在（仅包含 `__init__.py`），可直接扩展；`business/multi_spider/` 已存在，留给业务使用。
2. **基础设施**：
   - [infra/logger_setup.py](file:///c:/projects/BizTools4Openclaw/infra/logger_setup.py) —— `get_logger(name)` 获取 loguru logger。
   - [infra/alerting.py](file:///c:/projects/BizTools4Openclaw/infra/alerting.py) —— `AlertService`，含 `service_exception_sync()` 及 `crawler_risk_sync()` 通路。
   - [infra/redis_client.py](file:///c:/projects/BizTools4Openclaw/infra/redis_client.py) —— `RedisClient` 单例，提供 `.client` 访问。
   - [configs/settings.py](file:///c:/projects/BizTools4Openclaw/configs/settings.py) —— `settings.queue` / `settings.project` / `settings.log` / `settings.alert` / `settings.scheduler` / `settings.db`。
3. **依赖**：`requirements.txt` 已包含 `playwright`、`redis`。需确认是否需要 `httpx`（或直接用标准 `requests`）。本计划约定：Python 原生 `urllib.request` + `requests` 做基础请求；playwright 仅在显式传入 `render=True` 时启用，且在缺失时抛出友好错误提示，不影响 HTTP 模式。
4. **代码规范**：遵循 DEVELOP_RULES.md（中文注释、`from __future__ import annotations`、模块级 logger、错误码匹配 T02）。
5. **本计划不新增目录**，仅在 `core/spider_core/` 与测试目录下新增文件。

---

## 二、新增文件清单（8 + 1）

| # | 文件 | 说明 |
|---|------|------|
| 1 | `core/spider_core/__init__.py` | 导出包级符号（`SpiderSDK`, `CrawlResponse`, `proxy_pool`, `ua_pool`, `rate_limiter`, `robots_checker`, `checkpoint_manager`, `risk_controller`, `exceptions`） |
| 2 | `core/spider_core/exceptions.py` | 爬虫异常族（继承 `BizException`）：`SpiderError`, `ProxyUnavailableError`, `BlockedByRobotsError`, `RateLimitExceededError`, `CrawlerRiskDetectedError`, `CheckpointNotFoundError`, `UAFileNotFoundError` |
| 3 | `core/spider_core/ua_pool.py` | `UserAgentPool`：UA 池加载/随机抽取/移动端-PC 切换 |
| 4 | `core/spider_core/proxy_pool.py` | `ProxyPool`：代理拉取 / 有效性校验 / 失效剔除 / 轮询选择 |
| 5 | `core/spider_core/rate_limiter.py` | `DomainRateLimiter`：单域名请求间隔随机 + 分域名并发上限 |
| 6 | `core/spider_core/robots_checker.py` | `RobotsChecker`：站点 robots 解析 / 缓存 / 拦截禁止路径 |
| 7 | `core/spider_core/checkpoint_manager.py` | `CheckpointManager`：抓取进度 Redis 持久化 / 断点恢复 |
| 8 | `core/spider_core/risk_controller.py` | `RiskController`：封禁/验证码模式识别 + 自动降级（降并发、拉长间隔、切代理）+ 触发告警 |
| 9 | `core/spider_core/sdk.py` | `CrawlResponse` / `SpiderSDK` 主入口：HTTP & Playwright 双模式、串联 UA/代理/限流/robots/checkpoint/风控 |
| 10 | `tests/test_t05_infra.py` | 全量单元测试（覆盖 UA、代理、限流、robots、checkpoint、风控、HTTP 模式双链路） |

**无文件修改**：计划中不修改 README.md、DEVELOP_RULES.md、docs/TASK_LIST.md、以及 infra/ / configs/ 已有文件。（若后续发现 settings 需要新增分组，可在开发阶段按“新增字段不破坏已有字段”的方式扩展，由用户审核。）

---

## 三、每个工具类核心方法设计

### 3.1 [core/spider_core/exceptions.py] — 异常族

```python
class SpiderError(BizException):           # code = SPIDER_ERROR (由 T02 ErrorCode 扩展或单独数值)
    """爬虫通用异常基类。"""

class ProxyUnavailableError(SpiderError):  # 代理批量失效
class BlockedByRobotsError(SpiderError):   # robots.txt 禁止该路径
class RateLimitExceededError(SpiderError): # 达到并发 / 间隔上限
class CrawlerRiskDetectedError(SpiderError):# 检测到风控 / 验证码 / 封禁
class CheckpointNotFoundError(SpiderError):# 断点恢复时无 checkpoint
class UAFileNotFoundError(SpiderError):    # UA 池文件不存在
```

> 在 `infra/exceptions.py` 中新增 `SPIDER_ERROR` 与 `SPIDER_RISK` 两个错误码；本文件的 `BizException` 直接复用。

---

### 3.2 [core/spider_core/ua_pool.py] — `UserAgentPool`

**构造参数**（全部由 `.env` 配置，禁止硬编码）：

| env 键 | 说明 | 默认值 |
|--------|------|--------|
| `UA_POOL_FILE_PATH` | UA 列表文本文件路径（一行一条），支持 `#` 注释、空行 | 空：启用内置精简 UA 列表 |
| `UA_POOL_DEFAULT_MODE` | `mobile` / `desktop` / `random` | `random` |

**方法**：

- `__init__(self, file_path: str = "", default_mode: str = "random")`
  - 加载：若文件存在则读取；否则使用内置精简 UA 列表（3 desktop + 3 mobile）。
  - 按 UA 文本中是否包含 "Android|iPhone|Mobile" 自动归类到 mobile/desktop 池。
- `next(self, mode: str | None = None) -> str`
  - 从对应池中随机返回一个 UA。
  - `mode=None` 走 `self.default_mode`；若该池为空，回退到全部 UA。
- `refresh(self) -> None`：重新从文件加载（运行期可热更新）。
- `size(self) -> dict[str, int]`：`{"total": N, "mobile": M, "desktop": K}`。
- `_load_from_file(self, file_path)`：内部方法。
- `_load_builtin(self)`：内置 6 条常见 UA。

**内部数据**：

```python
self._desktop: list[str]   # ["Mozilla/5.0 (Windows NT 10.0; Win64; x64) ..."]
self._mobile: list[str]    # ["Mozilla/5.0 (iPhone; CPU iPhone OS 15_0 like ..."]
self._lock: threading.Lock # 支持多线程环境刷新/读取
```

**日志与告警**：UA 池文件不存在时 `logger.warning`；UA 池为空但被调用时告警一次（`alert_service.service_exception_sync`，5 分钟去抖）。

---

### 3.3 [core/spider_core/proxy_pool.py] — `ProxyPool`

**构造参数**（来自 `.env`）：

| env 键 | 说明 | 默认值 |
|--------|------|--------|
| `PROXY_POOL_API_URL` | 代理供应商 JSON 拉取接口；空字符串表示**禁用代理**，直连 | `""` |
| `PROXY_POOL_EXTRACT_INTERVAL_SECS` | 定时重新拉取代理的间隔（秒） | `600` |
| `PROXY_POOL_VALIDATE_TIMEOUT` | 代理有效性校验超时 | `5.0` |
| `PROXY_POOL_FAILURES_BEFORE_REMOVE` | 失败多少次后剔除 | `3` |
| `PROXY_POOL_REFRESH_ON_START` | 启动时是否立刻拉取 | `True` |

**假设代理 API 返回格式**（若用户供应商不同，可在该方法内通过 env 自定义解析器名称，默认支持两种主流格式）：

```text
# 格式 A（JSON）：{"data": [{"host": "1.2.3.4", "port": 8080, "protocol": "http"}]}
# 格式 B（纯文本）：每行 "http://1.2.3.4:8080"
```

本 SDK 统一内部结构为 `Proxy`：

```python
@dataclass
class Proxy:
    proxy_url: str                 # "http://1.2.3.4:8080" 或 "https://..."
    protocol: Literal["http", "https", "socks5"] = "http"
    added_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc).replace(tzinfo=None))
    failure_count: int = 0
    last_used_at: datetime | None = None
    last_failure_reason: str = ""

    def as_requests(self) -> dict[str, str]:
        # 返回 {"http": proxy_url, "https": proxy_url} 用于 requests/httpx
        ...
```

**方法**：

- `__init__(self, api_url: str = "", ...)`
  - 若 `api_url` 为空：标记为 "直连模式"，`next()` 返回 `None`。
- `refresh(self) -> int`
  - 拉取代理，解析成 `list[Proxy]`；返回新注册数量。
  - 失败：logger.error + 告警（5 分钟去抖），不抛出。
- `validate(self, proxy: Proxy, *, test_url: str = "https://www.baidu.com") -> bool`
  - 走一次轻量 HEAD 请求，校验代理可达性与正确性；超时即视为无效。
- `next(self) -> Proxy | None`
  - 轮询 + 可用代理过滤；失败则回退下一个；若全部失效，返回 `None`（调用方自行决定走直连还是抛出 `ProxyUnavailableError`）。
- `report_failure(self, proxy: Proxy, reason: str = "") -> None`
  - 记录失败；当 `failure_count >= PROXY_POOL_FAILURES_BEFORE_REMOVE` 时剔除；若代理池尺寸跌至 0 且 `api_url` 非空，触发告警。
- `report_success(self, proxy: Proxy) -> None`
  - 归零失败计数，更新 last_used_at。
- `size(self) -> int`
- `health(self) -> dict[str, Any]`：`{"size": N, "last_refresh": ts, "api_url": "..."}`

**日志与告警**：每次拉取失败 / 代理池空（已启用代理时）触发 `crawler_risk_sync`。

---

### 3.4 [core/spider_core/rate_limiter.py] — `DomainRateLimiter`

**构造参数**（来自 `.env`）：

| env 键 | 说明 | 默认值 |
|--------|------|--------|
| `RATE_LIMIT_INTERVAL_MIN_SECS` | 每个域名两次请求之间的最小随机间隔 | `1.0` |
| `RATE_LIMIT_INTERVAL_MAX_SECS` | 最大随机间隔 | `3.0` |
| `RATE_LIMIT_MAX_CONCURRENT_PER_DOMAIN` | 单域名并发上限（线程/协程维度） | `5` |
| `RATE_LIMIT_GLOBAL_MAX_CONCURRENT` | SDK 全局限并发上限 | `20` |
| `RATE_LIMIT_DOMAIN_OVERRIDES_JSON` | 可选：`{"domain.com": {"interval_min": 2.0, "interval_max": 5.0, "max_concurrent": 3}}` | `""` |

**内部数据**：

```python
self._domain_last_hit: dict[str, datetime]  # 记录每个域名上一次请求时间
self._domain_semaphore: dict[str, threading.Semaphore] | dict[str, asyncio.Semaphore]
self._global_semaphore: threading.Semaphore
self._lock: threading.Lock                    # 动态新增域名字典
```

**方法**：

- `acquire(self, url_or_domain: str) -> _RateLimitToken`
  - 解析域名：`urlparse(url_or_domain).netloc or url_or_domain`。
  - 先拿全局 semaphore；再拿域名 semaphore。
  - 计算该域名本次的随机休眠时间 `rand(min, max) - (now - last_hit)`；若 > 0 则 `time.sleep(...)`。
  - 返回一个可作 `with` 上下文的 token：退出时释放两个 semaphore + 更新 `last_hit`。
  - 线程/协程安全（`threading.Lock` 适合同步，异步场景以 `asyncio.Lock` 再实现一个版本 —— 但本 SDK 默认同步阻塞式，业务侧可自行包进协程）。
- `override(self, domain: str, *, interval_min: float, interval_max: float, max_concurrent: int) -> None`
  - 动态覆盖该域名的策略（用于运行期风控降级）。
- `reset(self, domain: str | None = None) -> None`
  - 清除域名/全部缓存的记录。

**日志与告警**：单次等待超过 `max_interval * 3` 时 `logger.warning`，但不触发告警（过于频繁）。

---

### 3.5 [core/spider_core/robots_checker.py] — `RobotsChecker`

**构造参数**：

| env 键 | 说明 | 默认值 |
|--------|------|--------|
| `ROBOTS_ENABLED` | 是否启用 robots 校验 | `True` |
| `ROBOTS_CACHE_TTL_SECS` | robots 文本缓存 TTL | `3600` |
| `ROBOTS_USER_AGENT` | 声明 UA；空即使用 UA 池中的 next UA | `""` |

**实现思路**：手写轻量解析（不引入额外 `urllib.robotparser` 以外依赖）。

- `_load_robots(self, scheme_netloc: str) -> RobotFileParser`
  - 请求 `{scheme}://{netloc}/robots.txt`；失败时视为 "允许全部" 并 `logger.warning`。
  - 缓存到字典：`{scheme_netloc: (ts, parser)}`。
- `is_allowed(self, url: str, *, user_agent: str = "*") -> bool`
  - 解析 URL；若 `ROBOTS_ENABLED=False` 返回 True。
  - 超过缓存 TTL 则重新拉。
- `ensure_allowed(self, url: str, *, user_agent: str = "*") -> None`
  - 若 `is_allowed()` 为 False，则抛出 `BlockedByRobotsError`，并触发 `crawler_risk_sync` 一次（5 分钟去抖）。

**日志**：每次 robots 拉取失败 warning；被禁止路径记录 `logger.info("blocked by robots: ...")`。

---

### 3.6 [core/spider_core/checkpoint_manager.py] — `CheckpointManager`

**构造参数**（来自 `.env`）：

| env 键 | 说明 | 默认值 |
|--------|------|--------|
| `CHECKPOINT_PREFIX` | Redis key 前缀 | `openclaw:checkpoint` |
| `CHECKPOINT_TTL_SECS` | checkpoint 自动过期 | `7 * 24 * 3600` |

**Redis 数据结构**（见第五节详述）：

```text
openclaw:checkpoint:{task_id}  -> HASH
  - job_id: str
  - platform: str
  - source_country: str
  - current_url: str
  - last_succeeded_url: str
  - total_items: int
  - processed_items: int
  - failed_items: int
  - status: "running" | "paused" | "failed" | "done"
  - payload_json: str            # 业务自定义扩展字段（JSON）
  - created_at: str              # ISO datetime
  - updated_at: str              # ISO datetime
  - last_error: str              # 最近错误
openclaw:checkpoint:visited:{task_id} -> SET
  - {url_or_identifier}          # 已处理 URL/ID 集合，用于去重
openclaw:checkpoint:pending:{task_id} -> LIST
  - {url_or_identifier}          # 待处理队列（业务可选）
openclaw:checkpoint:index        -> SET
  - {task_id}                    # 全部活跃任务，便于管理端查询 / 清理
```

**方法**：

- `save(self, task_id: str, *, current_url: str, processed_items: int, failed_items: int, status: str = "running", payload: dict[str, Any] | None = None) -> None`
  - 更新 HASH + `updated_at`；刷新 TTL。
- `load(self, task_id: str) -> dict[str, Any] | None`
  - 从 HASH 还原 dict；不存在返回 `None`。
- `mark_done(self, task_id: str) -> None`：`status=done` + 更新时间。
- `mark_failed(self, task_id: str, error: str) -> None`：`status=failed` + `last_error`。
- `mark_visited(self, task_id: str, *ids: str) -> int`：批量 sadd，返回新加入数量。
- `is_visited(self, task_id: str, id: str) -> bool`。
- `pending_push(self, task_id: str, *ids: str) -> int`：rpush。
- `pending_pop(self, task_id: str, *, count: int = 1) -> list[str]`：lpop（返回空列表代表无）。
- `delete(self, task_id: str) -> None`：清理 4 个 key；从 index 移除。
- `list_active(self, *, count: int = 100) -> list[str]`：smembers（小体量）。

**日志与告警**：save/load 异常仅 `logger.exception` + 告警一次（5 分钟去抖）。不抛给业务，确保在 Redis 故障时仍可用（降级为内存 checkpoint）。

---

### 3.7 [core/spider_core/risk_controller.py] — `RiskController`

**风控识别目标**：在抓取过程中，对 "封禁 / 验证码 / 重定向至登录页 / 高频 403/503" 进行自动识别，并根据严重级别执行对应降级动作与告警。

**构造参数**（来自 `.env`）：

| env 键 | 说明 | 默认值 |
|--------|------|--------|
| `RISK_ENABLED` | 是否启用风控降级 | `True` |
| `RISK_BAN_PATTERNS_JSON` | 封禁关键字 JSON 数组：`["页面不存在", "请完成验证", "系统繁忙", "Access Denied", "Your IP has been banned"]` | 内置 8 条中英文兜底 |
| `RISK_CAPTCHA_PATTERNS_JSON` | 验证码关键字：`["captcha", "验证码", "人机验证", "geetest", "hCaptcha", "reCAPTCHA"]` | 内置 8 条 |
| `RISK_LOGIN_REDIRECT_KEYWORDS_JSON` | 登录重定向关键字：`["/login", "/signin", "登录", "Sign in"]` | 内置 4 条 |
| `RISK_CONSECUTIVE_BAN_TRIGGER` | 连续 N 次风控后立刻告警并切换代理 | `3` |
| `RISK_BACKOFF_INTERVAL_MIN_SECS` | 封禁触发后最低随机间隔 | `10.0` |
| `RISK_BACKOFF_INTERVAL_MAX_SECS` | 最高随机间隔 | `30.0` |
| `RISK_ALERT_DEBOUNCE_SECS` | 同类告警去抖（秒） | `600` |

**方法**：

- `detect(self, response: CrawlResponse) -> RiskLevel`
  - 扫描 `response.status_code`：403/429/503 → 高风险；401/404/500 → 中度。
  - 扫描 `response.text` 中的 `ban patterns` / `captcha patterns`；命中任一条 → 高风险。
  - 扫描 `response.final_url` 是否命中 "login/signin" 重定向 → 中度。
  - 扫描 `response.headers` 中是否含 `cf-ray` / `server: cloudflare` 等典型 CDN 标记 → 中度。
  - 返回 `RiskLevel("none" | "low" | "medium" | "high")`（枚举字符串）。
- `handle(self, url: str, level: RiskLevel, *, response: CrawlResponse | None = None) -> RiskAction`
  - 维护内部 `domain -> counters`：`consecutive_high_risk`、`total_high_risk`、`last_backoff_at`。
  - **high**：
    - 立刻触发 `alert_service.crawler_risk_sync()`（5 分钟去抖 + 按域名去重）。
    - 对该域名调用 `rate_limiter.override(domain, interval_min=RISK_BACKOFF_INTERVAL_MIN_SECS, interval_max=RISK_BACKOFF_INTERVAL_MAX_SECS, max_concurrent=1)`。
    - 调用 `proxy_pool.next()` 切换新代理；并将旧代理 `report_failure()`。
    - 返回 `RiskAction("switch_proxy_and_backoff")`。
  - **medium**：
    - 间隔加倍（在 `rate_limiter` 上覆盖 domain 的 `interval_min/max`，不改变 `max_concurrent`）。
    - `logger.warning("medium risk detected: %s", url)`。
    - 返回 `RiskAction("backoff")`。
  - **low/none**：
    - 重置该域名的 `consecutive_high_risk` 计数。
    - 返回 `RiskAction("none")`。
- `get_domain_status(self, domain: str) -> dict[str, Any]`：对外暴露计数与最近 backoff 时间，供管理端查询。
- `reset(self, domain: str | None = None) -> None`：清零。

**内部计数结构**（进程内内存字典）：

```python
self._counters: dict[str, DomainRiskCounter]
# DomainRiskCounter: consecutive_high_risk: int; total_high_risk: int; last_backoff_at: datetime; last_alert_at: datetime
```

---

### 3.8 [core/spider_core/sdk.py] — `SpiderSDK` 主入口

**目标**：对外提供统一的 `get()` / `render()` 双模式，串联 UA/代理/限流/robots/checkpoint/风控。

**输出数据结构**：

```python
@dataclass
class CrawlResponse:
    url: str                           # 请求的原始 URL
    final_url: str                     # 最终 URL（可能与 url 不同，3xx 跳转）
    status_code: int                   # HTTP 状态码；对 Playwright 也模拟（200 正常 / 404 找不到页面等）
    content: bytes                     # 原始响应字节（HTML / JSON / text）；不含业务解析
    text: str                          # content 按响应 encoding 解码的文本
    encoding: str
    headers: dict[str, str]
    elapsed_secs: float               # 本次请求耗时
    used_ua: str                       # 实际使用的 UA
    used_proxy: str | None             # 实际使用的代理（如启用）；直连则 None
    mode: Literal["http", "playwright"]
    risk_level: str                    # 风控检测结果
    error: str | None                  # 异常信息（若有）；SDK 不会自动抛出，交由调用方判断

    @property
    def ok(self) -> bool:
        return 200 <= self.status_code < 400 and self.error is None
```

**构造参数**（全部由 `.env` + 依赖注入组件组成）：

```python
class SpiderSDK:
    def __init__(
        self,
        *,
        ua_pool: UserAgentPool | None = None,
        proxy_pool: ProxyPool | None = None,
        rate_limiter: DomainRateLimiter | None = None,
        robots_checker: RobotsChecker | None = None,
        checkpoint_manager: CheckpointManager | None = None,
        risk_controller: RiskController | None = None,
        default_timeout: float = 15.0,
        default_headers: dict[str, str] | None = None,
    )
```

**方法**：

- `get(self, url: str, *, params: dict[str, Any] | None = None, headers: dict[str, str] | None = None, timeout: float | None = None, render: bool = False, render_js: bool = False, render_wait_until: str = "domcontentloaded", render_timeout: float = 30.0, task_id: str | None = None, robot_check: bool = True, risk_check: bool = True, payload: dict[str, Any] | None = None) -> CrawlResponse`
  - **步骤**：
    1. **robots**：`robots_checker.ensure_allowed(url)`；禁用则跳过。
    2. **限流**：`with rate_limiter.acquire(url)`；自动随机 sleep + 并发控制。
    3. **UA / 代理**：`ua_pool.next()` + `proxy_pool.next()`；若 `proxy_pool` 未启用则直连。
    4. **请求**：
       - `render=False`（默认）：`requests.request("GET", url, ..., proxies=proxy.as_requests(), timeout=timeout)`。
       - `render=True`：调用内置 `_playwright_get(...)`，若 playwright 未安装则回退到 HTTP 模式并 `logger.warning`。
    5. **结果处理**：构造 `CrawlResponse`；若异常（超时、DNS 失败、连接失败等）则把异常写进 `response.error`、`status_code=0`，并调用 `proxy_pool.report_failure(...)`。
    6. **风控**：若 `risk_check=True`，`risk_level = risk_controller.detect(response)`，`risk_controller.handle(url, risk_level, response=response)` 自动执行降级动作。
    7. **断点**：若 `task_id` 非空，调用 `checkpoint_manager.save(task_id, current_url=url, payload=payload, ...)` 更新进度。
  - **日志**：每次请求记录 `logger.info("spider.get: url=... status=... elapsed=...")`；异常记录 `logger.exception`。
  - **不做数据清洗**：仅返回原始 HTML/文本。业务爬虫需要自己在 `business/multi_spider/*` 中写解析/抽取。

- `batch_get(self, urls: list[str], *, task_id: str | None = None, render: bool = False, risk_check: bool = True) -> list[CrawlResponse]`
  - 按顺序串行执行；并行由业务侧使用 `concurrent.futures.ThreadPoolExecutor` 自行实现（不内置，避免与全局并发控制叠加冲突）。

- `checkpoint_restore(self, task_id: str) -> dict[str, Any] | None`：转发到 `CheckpointManager.load()`。

- `resume_from_checkpoint(self, task_id: str, *, urls_producer: Callable[[dict[str, Any]], list[str]], process_one: Callable[[CrawlResponse, dict[str, Any]], None]) -> dict[str, int]`
  - **用法**：业务提供 `urls_producer(state)`——从 checkpoint 恢复出待爬 URL；提供 `process_one(response, state)`——处理单次响应。SDK 内部负责循环、断点保存、异常与风控。
  - 返回 `{"processed": N, "failed": K, "total": T}`。

**Playwright 模式实现思路**：

- 用 `playwright.sync_api`（`sync_playwright()` 上下文管理器，内部惰性启动）。
- 浏览器由参数 `SPIDER_BROWSER_HEADLESS=True`（env）控制是否 headless。
- 模拟真实 UA：取 `ua_pool.next(mode="desktop" or "mobile")` 自动设置。
- 支持可选的 `render_wait_until`：`"load"` / `"domcontentloaded"` / `"networkidle"`。
- 返回：页面 HTML（`page.content()`）+ 最终 URL + 200。
- **注意**：为避免阻塞 Playwright 安装失败，SDK 在 `render=True` 但 `playwright` 未安装时，抛出 `SpiderError`（附带 "请执行 pip install playwright && playwright install chromium" 的友好提示）。**HTTP 模式**始终可用，不依赖 Playwright。

---

## 四、代理池、UA 池数据存储结构

### 4.1 UA 池

**磁盘文件**（可选）：

- 一行一个浏览器 UA 字符串；空行与 `#` 开头的行忽略。
- 示例：
  ```text
  # desktop
  Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36
  Mozilla/5.0 (Macintosh; Intel Mac OS X 14_2) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.2 Safari/605.1.15
  # mobile
  Mozilla/5.0 (iPhone; CPU iPhone OS 17_2 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.2 Mobile/15E148 Safari/604.1
  ```

**运行时内存结构**（进程内）：

```python
self._all: list[str]
self._mobile: list[str]
self._desktop: list[str]
self._lock: threading.Lock
self._last_file_mtime: float | None
```

**持久化**：不写 Redis。UA 池为本地文件+内存；刷新时重新读取。

---

### 4.2 代理池

**外部 API 拉取**：如 3.3 所述；本地内存结构：

```python
self._proxies: list[Proxy]          # 有序列表，next() 用 round-robin
self._index: int                    # round-robin 游标
self._lock: threading.RLock         # 支持在请求中 report_failure 并发修改
self._last_refresh_at: datetime
self._health: dict[str, Any]        # 最近一次拉取结果摘要
```

**持久化**：不写 Redis；进程重启后通过 `refresh()` 重新拉取。

---

## 五、断点续爬 Redis 存储字段设计

已在 3.6 节展示 key 结构；此处补充字段说明与业务交互流程。

**Key 规则**：`{CHECKPOINT_PREFIX}:{task_id}`；task_id 由业务侧生成（推荐 UUID，"acme_opportunity_" + UUID）。

**交互流程**：

```text
业务（business/multi_spider/*）：
  1) 构造 SpiderSDK 或直接使用全局单例 `spider_sdk`。
  2) `state = sdk.checkpoint_restore(task_id)`。
     - 若 state 非空 → 从 `state["last_succeeded_url"]` 恢复位置；从 pending queue 取出下一条。
     - 若 state 为空 → 从头开始，并在首次 `save()` 时创建 checkpoint。
  3) 循环：
       url = next_url_from_producer(state)
       if sdk.checkpoint_manager.is_visited(task_id, url): continue
       resp = sdk.get(url, task_id=task_id, payload={"phase": ...})
       if resp.ok:
           sdk.checkpoint_manager.mark_visited(task_id, url)
           sdk.checkpoint_manager.save(task_id, current_url=url, processed_items=..., payload=...)
       else:
           sdk.checkpoint_manager.save(task_id, current_url=url, failed_items=..., status="running")
  4) 正常结束 → sdk.checkpoint_manager.mark_done(task_id)
      异常结束 → sdk.checkpoint_manager.mark_failed(task_id, str(exc))
      主动放弃 → sdk.checkpoint_manager.delete(task_id)
```

**TTL 设计**：所有 HASH / SET / LIST key 均绑 `EXPIRE CHECKPOINT_TTL_SECS`，防止长期残留。

---

## 六、风控识别与降级执行逻辑（详细）

### 6.1 识别点

| 级别 | 来源 | 触发条件 |
|------|------|---------|
| high | status_code | `403 / 429 / 503` |
| high | 响应文本 | 命中 ban 关键词任意一条（忽略大小写） |
| high | 响应文本 | 命中 captcha 关键词任意一条 + 页面内容长度 < 2048 字节 |
| medium | final_url | 重定向到 "/login"、"/signin"、含 "登录" 等 |
| medium | headers | 出现 `cf-ray`、`x-bot-detected`、`server: cloudflare` 等典型 CDN |
| medium | status_code | `401 / 404 / 500 / 502 / 504` |
| low | 其它 | 页面大小异常下降（相比同站点历史均值 < 50%）；可在后续版本扩展 |
| none | 默认 | 无命中 |

> **注**：关键词支持业务侧通过 `RISK_BAN_PATTERNS_JSON` 等 env 覆盖，默认内置英文+中文兜底。

### 6.2 降级动作

| 级别 | 动作 |
|------|------|
| high | 1) 切换新代理；旧代理 `report_failure()`；2) 该域名的 `interval_min/max` 提升到 `RISK_BACKOFF_INTERVAL_MIN/MAX_SECS`；3) 并发上限临时降至 1；4) `crawler_risk_sync` 告警；5) `consecutive_high_risk++`，超过 `RISK_CONSECUTIVE_BAN_TRIGGER` 后主动 sleep 30s。 |
| medium | 1) 仅拉长 interval（`min*2`，封顶 `RISK_BACKOFF_INTERVAL_MAX_SECS`）；2) `logger.warning`；3) 不告警。 |
| low/none | 1) 清零该域名 consecutive_high_risk；2) 逐步收敛 interval 到正常值。 |

### 6.3 告警去抖策略

- 每个域名独立记录 `last_alert_at`。
- `RiskController` 内部使用 `threading.Lock`；不同域名互不阻塞。
- 默认 10 分钟内同一域名仅告警一次；但仍会执行降级动作。

---

## 七、开发执行步骤（8 步）

### Step 0（准备阶段）—— 确认 Python 环境与依赖

- 确认已安装：`requests`、`playwright`、`redis`、`pytest`、`loguru`、`pydantic`。
- 若缺少：`python -m pip install requests playwright redis pydantic loguru`。
- 为 Playwright：**首次执行时若未安装 chromium**，不阻塞 HTTP 模式；仅在调用 `render=True` 时友好提示。
- 在 `.env.example` 中补充以下 env 模板键（**仅模板，不含真实值**）：

```dotenv
# -------------------- Spider Core --------------------
# UA 池
UA_POOL_FILE_PATH=
UA_POOL_DEFAULT_MODE=random          # mobile / desktop / random

# 代理池
PROXY_POOL_API_URL=
PROXY_POOL_EXTRACT_INTERVAL_SECS=600
PROXY_POOL_VALIDATE_TIMEOUT=5.0
PROXY_POOL_FAILURES_BEFORE_REMOVE=3
PROXY_POOL_REFRESH_ON_START=True

# 限流
RATE_LIMIT_INTERVAL_MIN_SECS=1.0
RATE_LIMIT_INTERVAL_MAX_SECS=3.0
RATE_LIMIT_MAX_CONCURRENT_PER_DOMAIN=5
RATE_LIMIT_GLOBAL_MAX_CONCURRENT=20
RATE_LIMIT_DOMAIN_OVERRIDES_JSON=

# robots 合规
ROBOTS_ENABLED=True
ROBOTS_CACHE_TTL_SECS=3600
ROBOTS_USER_AGENT=

# checkpoint
CHECKPOINT_PREFIX=openclaw:checkpoint
CHECKPOINT_TTL_SECS=604800           # 7 days

# 风控
RISK_ENABLED=True
RISK_BAN_PATTERNS_JSON='["页面不存在","请完成验证","系统繁忙","Access Denied","Your IP has been banned"]'
RISK_CAPTCHA_PATTERNS_JSON='["captcha","验证码","人机验证","geetest","hCaptcha","reCAPTCHA"]'
RISK_LOGIN_REDIRECT_KEYWORDS_JSON='["/login","/signin","登录","Sign in"]'
RISK_CONSECUTIVE_BAN_TRIGGER=3
RISK_BACKOFF_INTERVAL_MIN_SECS=10.0
RISK_BACKOFF_INTERVAL_MAX_SECS=30.0
RISK_ALERT_DEBOUNCE_SECS=600

# Playwright
SPIDER_BROWSER_HEADLESS=True
SPIDER_DEFAULT_TIMEOUT=15.0
```

> **说明**：上面的 `.env.example` 属于"模板文档"的扩展，符合 T01 以来的扩展方式。若用户明确禁止修改该文件，此步可跳过，由业务在其 `.env` 中自行配置。

### Step 1 — 写入异常族 `core/spider_core/exceptions.py`

- 新建异常类，全部继承 `BizException`；新增错误码：`SPIDER_ERROR`、`SPIDER_RISK`（在 `infra/exceptions.py:ErrorCode` 中增补两个枚举条目）。
- 覆盖上述 6 类异常。

### Step 2 — UA 池 `core/spider_core/ua_pool.py`

- 读取 env 构造参数。
- 内置 3 desktop + 3 mobile 兜底 UA。
- 提供 `next(mode=...) / refresh() / size()`。
- 写针对单元测试：① 文件模式加载；② 内置兜底模式；③ mobile/desktop 分类；④ refresh。

### Step 3 — 代理池 `core/spider_core/proxy_pool.py`

- 拉取、解析、校验、轮询、失败剔除。
- 直连模式（api_url 为空）直接返回 None。
- 提供 `validate() / next() / report_failure() / report_success() / refresh() / size()`。
- 单元测试：① 直连模式；② 使用本地 `httpbin.org`（或测试内 `unittest.mock`）模拟代理 API；③ 失败剔除；④ 空池告警。

### Step 4 — 域名限速 `core/spider_core/rate_limiter.py`

- 基于 semaphore 与随机 sleep。
- 动态覆盖策略（供风控使用）。
- 提供 `override() / reset() / acquire()`。
- 单元测试：① 两次请求间间隔 ≥ min_interval 确定性检查（通过 monkeypatch time.sleep 精确统计）；② 并发上限（线程数 N 但 semaphore 为 2 时，同一时间最多 2 个通过）。

### Step 5 — robots 校验 `core/spider_core/robots_checker.py`

- 使用 `urllib.robotparser.RobotFileParser`（stdlib，零依赖）。
- 轻量 TTL 缓存。
- 提供 `is_allowed() / ensure_allowed()`；后者在禁止时抛 `BlockedByRobotsError`。
- 单元测试：使用本地 flask/test server 模拟 robots；或使用 monkeypatch 直接 mock HTTP 层。

### Step 6 — Redis checkpoint `core/spider_core/checkpoint_manager.py`

- 完全复用 [infra/redis_client.py](file:///c:/projects/BizTools4Openclaw/infra/redis_client.py) 的 `RedisClient().client`（即 `redis.Redis`）。
- 单元测试：用 `fakeredis.FakeRedis` 注入 `override_client`（已存在于 `RedisClient.__init__` 的入参，天然支持测试）。
- 覆盖：save/load/mark_done/mark_failed/mark_visited/is_visited/pending_push/pending_pop/delete/list_active；并验证 TTL 刷新。

### Step 7 — 风控 `core/spider_core/risk_controller.py`

- 封装 `RiskLevel`、`RiskAction`（字符串枚举）。
- 内置兜底关键词，支持 env 以 JSON 覆盖。
- 维护 domain 维度计数 + 自动调用 `rate_limiter.override` 与 `proxy_pool.report_failure`。
- 单元测试：① detect 触发 high；② detect 触发 medium；③ handle 触发 switch_proxy_and_backoff；④ 连续 high 超过阈值触发 sleep；⑤ 告警去抖（10 分钟同域名只调用一次 `crawler_risk_sync`）。

### Step 8 — SDK 主入口 `core/spider_core/sdk.py`

- 串联 Step 2-7 组件；内部维护一个 "模块级单例"：`spider_sdk = SpiderSDK(...)`（在首次导入时构造，延迟初始化依赖，允许测试时覆盖）。
- 对外导出：`SpiderSDK` / `CrawlResponse` / `from core.spider_core import spider_sdk`。
- Playwright 模式在未安装时优雅降级。
- 单元测试：
  - HTTP 模式成功（monkeypatch 掉 `requests.get`）；
  - HTTP 模式异常（网络超时）→ 失败计数 + 告警去抖；
  - robots 拒绝 → 抛 `BlockedByRobotsError`；
  - render=True 触发 Playwright（通过 mock playwright）。

### Step 9（收尾）— 包导出 + 测试汇总

- 更新 `core/spider_core/__init__.py` 导出上述模块。
- 确认：`python -m pytest tests/ -v` 全量回归（T01-T05 无失败）。
- **注意**：本计划的 Step 0 新增 `.env.example` 行属于"模板文档"范畴，严格遵循"不重命名/不删除/不改动已有项目目录"的约束；若用户希望模板也保持不变，此步可省略。

---

## 八、与业务的接口约定（给 `business/multi_spider/` 的使用指南）

业务爬虫的推荐用法：

```python
# business/multi_spider/example_spider.py

from core.spider_core import spider_sdk

def crawl(task_id: str, start_urls: list[str]) -> dict[str, int]:
    """业务爬虫：仅负责输入输出与业务解析，不关心代理/UA/限流/风控。"""
    processed, failed = 0, 0
    for url in start_urls:
        if spider_sdk.checkpoint_manager.is_visited(task_id, url):
            continue
        resp = spider_sdk.get(url, task_id=task_id, payload={"phase": "list"})
        if not resp.ok:
            failed += 1
            spider_sdk.checkpoint_manager.save(task_id, current_url=url, processed_items=processed, failed_items=failed)
            continue
        processed += 1
        spider_sdk.checkpoint_manager.mark_visited(task_id, url)
        spider_sdk.checkpoint_manager.save(task_id, current_url=url, processed_items=processed, failed_items=failed)
        # 业务侧自行实现 HTML 解析；SDK 不参与
        # parse_items(resp.text)
    spider_sdk.checkpoint_manager.mark_done(task_id)
    return {"processed": processed, "failed": failed}
```

**依赖方向**：`business/multi_spider/` → `core/spider_core/`；**绝不反向依赖**（spider_core 不应 import business/）。

---

## 九、日志 / 告警覆盖矩阵

| 场景 | 日志级别 | 告警 |
|------|---------|------|
| 单次成功请求 | INFO | — |
| robots 禁止 | INFO | — |
| 代理拉取失败 | ERROR | `alert_service.crawler_risk_sync()`（5 分钟去抖） |
| 代理全部失效（且启用代理）| ERROR | `crawler_risk_sync()` |
| 请求网络异常（超时/连接拒绝） | ERROR | `service_exception_sync()`（5 分钟去抖） |
| 识别到封禁 / 验证码（high risk） | WARNING | `crawler_risk_sync()`（10 分钟每域名去抖） |
| checkpoint 读写失败 | ERROR | `service_exception_sync()`（5 分钟去抖） |
| UA 池文件缺失 | WARNING | `service_exception_sync()`（5 分钟去抖） |

---

## 十、测试策略（`tests/test_t05_infra.py`）

- **总测试数 ≥ 18**，覆盖：
  - UA 池（文件加载 / 内置 / mobile desktop 区分 / refresh） — 4 个；
  - 代理池（直连模式 / mock API 拉取 / 失败阈值剔除 / 空池告警） — 4 个；
  - 域名限速（随机间隔 / 并发上限 / 动态覆盖 override） — 3 个；
  - robots（allow / disallow / 缓存） — 2 个；
  - checkpoint（save-load / visited / pending queue / delete list） — 3 个；
  - 风控（detect high/medium/none / handle 自动切换代理与告警去抖） — 3 个；
  - SDK（HTTP 成功 / HTTP 异常 / robots 禁止 / render=True mock） — 4 个。
- 工具：`pytest + monkeypatch + fakeredis`（与 T03 保持一致）；不依赖真实网络。
- 断言：
  - 字符串匹配（UA 含 "Mozilla"）；
  - 时间差断言（两次 `acquire` 调用间隔 ≈ min_interval）；
  - `spider_sdk.get()` 返回 `CrawlResponse.ok=True/False`；
  - `alert_service.crawler_risk_sync()` mock 被调用次数（风控阈值触发时）。

---

## 十一、风险与边界预案

| 风险 | 后果 | 预案 |
|------|------|------|
| Playwright / browser 未安装 | `render=True` 失败 | 在 `SpiderSDK` 中捕获 `ImportError`，抛出 `SpiderError` 并附安装说明；HTTP 模式独立可用 |
| Redis 不可用 | checkpoint 读写失败 | `CheckpointManager` 内捕获异常，降级为进程内内存字典（`self._memory: dict[str, dict]`）；仍能保存/恢复，但跨进程共享失效；触发告警一次 |
| 代理 API 响应格式不符合预期 | refresh 抛异常 | `ProxyPool` 内捕获异常并保留旧代理；触发告警；同时支持 env 传入自定义 JSON 路径（`PROXY_POOL_API_RESPONSE_JSONPATH="$.data[*]"`）可扩展 |
| 业务爬虫长时间无 checkpoint 更新 | 任务可能在重启后从中间恢复失败但被遗漏 | 由 `pending_push/pop` 的 `llen > 0` 且 `updated_at` 超过 N 小时作为"失联"判定，由管理端定时巡检（后续 T 任务实现，不在本计划内） |
| 高频请求触发反爬 | 导致大量封禁 | 域名限速 + 风控自动降级双通道 |
| 并发语义在线程/协程混合场景下出现冲突 | 限速锁失效 | 默认 `threading.Semaphore`；若业务切换到 async，可在 `DomainRateLimiter` 基础上增加 `AsyncDomainRateLimiter`（不冲突于现有实现，可在后续版本增加） |

---

## 十二、可交付验收标准

1. `python -m pytest tests/` → 全部通过（含 T01-T04 回归）。
2. `python -c "from core.spider_core import spider_sdk; r = spider_sdk.get('https://example.com'); print(r.status_code, r.text[:80])"` → 在网络可达时返回 `200` 与 HTML 片段（手动验证）。
3. 可在无网络环境下跑通全部单元测试（通过 monkeypatch / fakeredis 实现隔离）。
4. 所有新增文件均位于 `core/spider_core/` 与 `tests/`，不重命名/不删除已有目录与文件。
5. 敏感密钥、代理 API 地址、并发配置全部从 `.env` 读取，代码内**无任何硬编码**。

