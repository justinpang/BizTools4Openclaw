from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from infra.logger_setup import get_logger
from core.spider_core.ua_pool import UserAgentPool
from core.spider_core.proxy_pool import ProxyPool, Proxy
from core.spider_core.rate_limiter import DomainRateLimiter
from core.spider_core.robots_checker import RobotsChecker
from core.spider_core.checkpoint_manager import CheckpointManager
from core.spider_core.risk_controller import RiskController

# requests / playwright：模块级引用，便于测试时 monkeypatch 替换
try:
    import requests as _requests_lib  # noqa: F401
except Exception:  # pragma: no cover - 缺失依赖时降级报错
    _requests_lib = None

try:
    from playwright.sync_api import sync_playwright as _playwright_sync  # type: ignore
except Exception:  # pragma: no cover
    _playwright_sync = None

try:
    from playwright.async_api import async_playwright as _playwright_async  # type: ignore
except Exception:  # pragma: no cover
    _playwright_async = None

logger = get_logger("spider.sdk")


@dataclass
class CrawlResponse:
    url: str = ""
    final_url: str = ""
    status_code: int = 0
    content: bytes = field(default_factory=bytes)
    text: str = ""
    encoding: str = "utf-8"
    headers: Dict[str, str] = field(default_factory=dict)
    elapsed_secs: float = 0.0
    used_ua: str = ""
    used_proxy: Optional[str] = None
    mode: str = "http"
    risk_level: str = "none"
    error: Optional[str] = None

    @property
    def ok(self) -> bool:
        return self.error is None and 200 <= self.status_code < 400


class SpiderSDK:
    """统一爬虫 SDK 入口。"""

    def __init__(
        self,
        *,
        ua_pool: Optional[UserAgentPool] = None,
        proxy_pool: Optional[ProxyPool] = None,
        rate_limiter: Optional[DomainRateLimiter] = None,
        robots_checker: Optional[RobotsChecker] = None,
        checkpoint_manager: Optional[CheckpointManager] = None,
        risk_controller: Optional[RiskController] = None,
        default_timeout: float = 15.0,
        default_headers: Optional[Dict[str, str]] = None,
    ) -> None:
        self._ua = ua_pool or UserAgentPool()
        self._proxy = proxy_pool or ProxyPool()
        self._limiter = rate_limiter or DomainRateLimiter()
        self._robots = robots_checker or RobotsChecker()
        self._checkpoint = checkpoint_manager or CheckpointManager()
        self._risk = risk_controller or RiskController()
        self._timeout = float(default_timeout)
        self._default_headers = dict(default_headers or {})

        # 让风控能反向调用我们的依赖
        self._risk.attach(
            rate_limiter=self._limiter,
            proxy_pool=self._proxy,
        )

    # ---------------- 属性 ----------------

    @property
    def checkpoint_manager(self) -> CheckpointManager:
        return self._checkpoint

    @property
    def risk_controller(self) -> RiskController:
        return self._risk

    @property
    def ua_pool(self) -> UserAgentPool:
        return self._ua

    @property
    def proxy_pool(self) -> ProxyPool:
        return self._proxy

    # ---------------- 核心 GET ----------------

    def get(
        self,
        url: str,
        *,
        params: Optional[Dict[str, Any]] = None,
        headers: Optional[Dict[str, str]] = None,
        timeout: Optional[float] = None,
        render: bool = False,
        render_js: bool = True,
        render_wait_until: str = "networkidle",
        render_timeout: float = 45.0,
        task_id: Optional[str] = None,
        robot_check: bool = True,
        risk_check: bool = True,
        payload: Optional[Dict[str, Any]] = None,
    ) -> CrawlResponse:
        start = time.monotonic()
        resp = CrawlResponse(url=url, final_url=url)

        # 1. robots
        if robot_check:
            try:
                self._robots.ensure_allowed(url)
            except Exception as exc:
                resp.error = f"robots blocked: {exc}"
                resp.risk_level = "medium"
                logger.info(f"robots 拒绝: {url}")
                return resp

        # 2. 限流（在 semaphore 内执行请求）
        try:
            with self._limiter.acquire(url):
                # 3. UA / 代理
                ua = self._ua.next()
                proxy = self._proxy.next()
                resp.used_ua = ua
                resp.used_proxy = proxy.proxy_url if proxy else None

                # 4. 组装最终请求头
                final_headers = {
                    **self._default_headers,
                    **(headers or {}),
                    "User-Agent": ua,
                }

                # 5. 执行请求
                if render:
                    self._render_page(
                        url,
                        resp=resp,
                        headers=final_headers,
                        timeout=render_timeout,
                        wait_until=render_wait_until,
                    )
                else:
                    self._http_get(
                        url,
                        params=params,
                        headers=final_headers,
                        proxy=proxy,
                        timeout=timeout or self._timeout,
                        resp=resp,
                    )
        except Exception as exc:
            resp.error = f"request_error: {exc}"
            logger.warning(f"请求异常 {url}: {exc}")

        resp.elapsed_secs = round(time.monotonic() - start, 4)

        # 6. 风控
        if risk_check and resp.status_code > 0:
            try:
                level = self._risk.detect(
                    status_code=resp.status_code,
                    text=resp.text,
                    final_url=resp.final_url,
                    headers=resp.headers,
                )
                resp.risk_level = level
                if level != "none":
                    self._risk.handle(url, level, response_excerpt=resp.text[:200])
            except Exception as exc:
                logger.warning(f"风控处理出错: {exc}")

        # 7. checkpoint（若提供 task_id）
        if task_id:
            try:
                self._checkpoint.save(
                    task_id,
                    current_url=resp.final_url or url,
                    processed_items=1 if resp.ok else 0,
                    failed_items=0 if resp.ok else 1,
                    status="running",
                    payload=payload,
                )
            except Exception as exc:
                logger.warning(f"checkpoint save 失败: {exc}")

        logger.info(
            f"spider.get: url={url} status={resp.status_code} risk={resp.risk_level} "
            f"elapsed={resp.elapsed_secs}s"
        )
        return resp

    # ---------------- HTTP 实现 ----------------

    def _http_get(
        self,
        url: str,
        *,
        params: Optional[Dict[str, Any]],
        headers: Dict[str, str],
        proxy: Optional[Proxy],
        timeout: float,
        resp: CrawlResponse,
    ) -> None:
        # 通过模块级变量引用，便于测试时 monkeypatch 替换
        requests_lib = _requests_lib

        # 优先使用 requests 库，失败时回退到标准库 urllib.request
        if requests_lib is not None:
            try:
                proxies = proxy.as_requests() if proxy else None
                r = requests_lib.get(
                    url,
                    params=params,
                    headers=headers,
                    proxies=proxies,
                    timeout=timeout,
                    allow_redirects=True,
                )
                resp.status_code = int(r.status_code)
                resp.final_url = r.url
                resp.content = r.content
                resp.encoding = r.encoding or "utf-8"
                resp.text = r.text
                resp.headers = {str(k): str(v) for k, v in (r.headers or {}).items()}
                resp.mode = "http"
                if proxy:
                    self._proxy.report_success(proxy)
                return
            except Exception as exc:
                logger.warning(f"requests 请求失败，尝试 urllib 回退 {url}: {exc}")
                # 继续到 urllib fallback

        # Fallback: 使用 Python 标准库 urllib.request
        try:
            import urllib.request
            import urllib.parse
            import urllib.error

            # 构造带 params 的 URL
            final_url = url
            if params:
                sep = "&" if "?" in final_url else "?"
                final_url = final_url + sep + urllib.parse.urlencode(params)

            req = urllib.request.Request(final_url, headers=headers or {})
            proxy_url = proxy.as_requests() if proxy else None
            if proxy_url and isinstance(proxy_url, dict):
                proxy_handler = urllib.request.ProxyHandler(proxy_url)
                opener = urllib.request.build_opener(proxy_handler)
            else:
                opener = urllib.request.build_opener()

            r = opener.open(req, timeout=timeout)
            resp.status_code = int(r.getcode())
            resp.final_url = r.geturl()
            resp.content = r.read()
            resp.headers = {str(k): str(v) for k, v in (r.headers or {}).items()}

            # 处理编码：优先使用响应头，其次尝试自动检测
            content_type = r.headers.get("Content-Type", "") if hasattr(r, "headers") else ""
            charset = "utf-8"
            if "charset=" in content_type.lower():
                charset = content_type.lower().split("charset=")[1].split(";")[0].strip()
            try:
                resp.text = resp.content.decode(charset, errors="replace")
            except (LookupError, UnicodeDecodeError):
                # 失败时尝试其他常见编码
                for enc in ("utf-8", "gbk", "gb2312", "latin-1"):
                    try:
                        resp.text = resp.content.decode(enc, errors="replace")
                        resp.encoding = enc
                        break
                    except Exception:
                        continue
                else:
                    resp.text = resp.content.decode("utf-8", errors="replace")
                    resp.encoding = "utf-8"
            resp.encoding = charset
            resp.mode = "urllib"
            if proxy:
                self._proxy.report_success(proxy)
        except urllib.error.HTTPError as http_err:
            resp.status_code = http_err.code
            resp.error = f"HTTP {http_err.code}: {http_err.reason}"
            try:
                resp.content = http_err.read()
                resp.text = resp.content.decode("utf-8", errors="replace")
            except Exception:
                pass
            logger.warning(f"urllib HTTP 错误 {url}: {http_err}")
        except Exception as exc:
            resp.status_code = 0
            resp.error = str(exc)
            if proxy:
                self._proxy.report_failure(proxy, reason=str(exc))
            logger.warning(f"http 请求失败 {url}: {exc}")

    # ---------------- Playwright 实现 ----------------

    def _render_page(
        self,
        url: str,
        *,
        resp: CrawlResponse,
        headers: Dict[str, str],
        timeout: float,
        wait_until: str,
    ) -> None:
        """JS 渲染入口：自动检测 asyncio 事件循环，在线程中隔离执行"""
        if _playwright_sync is None:
            raise ImportError(
                "需要安装 playwright: pip install playwright && playwright install chromium"
            )

        # 检测是否在 asyncio 事件循环中（FastAPI 会触发这种情况）
        try:
            import asyncio
            running_loop = asyncio.get_running_loop()
        except RuntimeError:
            running_loop = None

        if running_loop is not None:
            # 在事件循环中：使用线程池隔离，避免 "Playwright Sync API inside asyncio loop" 错误
            import concurrent.futures
            with concurrent.futures.ThreadPoolExecutor(max_workers=1) as executor:
                future = executor.submit(
                    self._render_page_sync_impl,
                    url, resp, headers, timeout, wait_until,
                )
                try:
                    future.result(timeout=timeout + 10)
                except concurrent.futures.TimeoutError:
                    resp.status_code = 0
                    resp.error = f"playwright 渲染超时（{timeout}s）"
                    logger.warning(f"playwright 渲染超时 {url}")
        else:
            # 不在事件循环中：直接调用同步 API
            self._render_page_sync_impl(url, resp, headers, timeout, wait_until)

    def _render_page_sync_impl(
        self,
        url: str,
        resp: CrawlResponse,
        headers: Dict[str, str],
        timeout: float,
        wait_until: str,
    ) -> None:
        """Playwright 实际执行逻辑（必须在无事件循环的线程中运行）

        为确保能完整捕获动态内容，采用以下策略：
        1. networkidle 等待网络活动停止
        2. 多次滚动触发懒加载  
        3. 等待 DOM 稳定（两次 content 不再变化）

        注意：每次调用都在本地重新 import sync_playwright，
        避免模块级的 `_playwright_sync` 被 FastAPI 主事件循环污染
        （可能导致 'PlaywrightContextManager' object has no attribute '_playwright'）。
        """
        try:
            # 在本地作用域内重新导入 playwright（不使用模块级引用）
            from playwright.sync_api import sync_playwright  # type: ignore

            with sync_playwright() as p:
                browser = p.chromium.launch(headless=True)
                try:
                    context = browser.new_context(user_agent=headers.get("User-Agent"))
                    page = context.new_page()
                    page_resp = page.goto(url, wait_until=wait_until, timeout=int(timeout * 1000))
                    resp.status_code = 200
                    if page_resp is not None:
                        try:
                            resp.status_code = int(page_resp.status)
                        except Exception:
                            pass

                    # —— 增强内容收集：多次滚动+等待页面稳定 ——
                    import time as _time
                    try:
                        for scroll_round in range(3):
                            page.evaluate(
                                "() => { window.scrollTo(0, document.body.scrollHeight); }"
                            )
                            page.wait_for_timeout(1500)
                            page.evaluate("() => { window.scrollTo(0, 0); }")
                            page.wait_for_timeout(800)

                        page.wait_for_timeout(1500)
                    except Exception:
                        pass  # 滚动失败不影响主流程

                    resp.final_url = page.url
                    resp.text = page.content()
                    resp.content = resp.text.encode("utf-8", errors="ignore")
                    resp.mode = "playwright"
                finally:
                    browser.close()
        except Exception as exc:
            resp.status_code = 0
            resp.error = f"playwright_error: {exc}"
            logger.warning(f"playwright 渲染失败 {url}: {exc}")

    # ---------------- 批处理 / 恢复 ----------------

    def checkpoint_restore(self, task_id: str) -> Optional[Dict[str, Any]]:
        return self._checkpoint.load(task_id)

    def batch_get(self, urls: List[str], *, task_id: Optional[str] = None, render: bool = False) -> List[CrawlResponse]:
        results: List[CrawlResponse] = []
        for url in urls:
            results.append(self.get(url, render=render, task_id=task_id))
        return results


# 模块级单例（便于业务直接 `from core.spider_core import spider_sdk`）
spider_sdk = SpiderSDK()

__all__ = ["SpiderSDK", "CrawlResponse", "spider_sdk"]
