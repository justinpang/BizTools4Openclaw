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
        render_wait_until: str = "domcontentloaded",
        render_timeout: float = 30.0,
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
        requests = _requests_lib
        if requests is None:
            raise ImportError("需要安装 requests: pip install requests")

        try:
            proxies = proxy.as_requests() if proxy else None
            r = requests.get(
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
        sync_pw = _playwright_sync
        if sync_pw is None:
            raise ImportError(
                "需要安装 playwright: pip install playwright && playwright install chromium"
            )

        try:
            with sync_pw() as p:
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
