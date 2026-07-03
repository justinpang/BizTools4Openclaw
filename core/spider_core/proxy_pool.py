from __future__ import annotations

import json
import threading
import time
from dataclasses import dataclass, field
from typing import Any, List, Optional

from infra.logger_setup import get_logger

logger = get_logger("spider.proxy_pool")


@dataclass
class Proxy:
    proxy_url: str
    protocol: str = "http"
    added_at: float = field(default_factory=lambda: time.time())
    failure_count: int = 0
    last_used_at: Optional[float] = None
    last_failure_reason: str = ""

    def as_requests(self) -> dict:
        return {"http": self.proxy_url, "https": self.proxy_url}


class ProxyPool:
    """代理池：API 拉取 / 有效性校验 / 失败剔除 / 轮询。"""

    def __init__(
        self,
        *,
        api_url: str = "",
        validate_timeout: float = 5.0,
        failure_threshold: int = 3,
        refresh_on_start: bool = True,
        refresh_interval: float = 600.0,
    ) -> None:
        self._api_url = api_url
        self._validate_timeout = float(validate_timeout)
        self._failure_threshold = int(failure_threshold)
        self._refresh_interval = float(refresh_interval)

        self._proxies: List[Proxy] = []
        self._index = 0
        self._lock = threading.RLock()
        self._last_refresh_at: float = 0.0
        self._direct_mode = not bool(api_url)  # 无 API URL 时为直连模式

        if refresh_on_start and api_url:
            try:
                self.refresh()
            except Exception as exc:
                logger.warning(f"启动时代理刷新失败: {exc}")

    # ---------------- 基本信息 ----------------

    @property
    def is_direct_mode(self) -> bool:
        return self._direct_mode

    def size(self) -> int:
        with self._lock:
            return len(self._proxies)

    def health(self) -> dict:
        with self._lock:
            return {
                "size": len(self._proxies),
                "last_refresh_at": self._last_refresh_at,
                "api_url": self._api_url,
                "direct_mode": self._direct_mode,
            }

    # ---------------- 拉取 ----------------

    def refresh(self) -> int:
        """从 API 拉取最新代理；返回本次新注册数量。"""
        if not self._api_url:
            return 0
        try:
            proxies = self._fetch_from_api(self._api_url)
            with self._lock:
                self._proxies = proxies
                self._index = 0
                self._last_refresh_at = time.time()
            logger.info(f"代理池刷新: 共 {len(proxies)} 个")
            return len(proxies)
        except Exception as exc:
            logger.error(f"代理池拉取失败: {exc}")
            return 0

    def _fetch_from_api(self, url: str) -> List[Proxy]:
        """拉取并解析。支持 JSON 格式 `{"data": [{"host":..., "port":..., "protocol":...}]}` 和纯文本。"""
        # 使用标准库 urllib，避免额外依赖；urllib 异常由上层捕获
        import urllib.request
        req = urllib.request.Request(url, headers={"User-Agent": "openclaw-spider/1.0"})
        with urllib.request.urlopen(req, timeout=self._validate_timeout) as resp:
            raw = resp.read().decode("utf-8", errors="ignore").strip()

        # 尝试 JSON 解析
        try:
            payload = json.loads(raw)
            items = payload.get("data") if isinstance(payload, dict) else payload
            if isinstance(items, list):
                proxies: List[Proxy] = []
                for item in items:
                    if isinstance(item, dict):
                        host = str(item.get("host") or item.get("ip") or "").strip()
                        port = item.get("port") or item.get("p") or 0
                        protocol = str(item.get("protocol") or item.get("type") or "http").lower()
                        if host and port:
                            proxy_url = f"{protocol}://{host}:{port}"
                            proxies.append(Proxy(proxy_url=proxy_url, protocol=protocol))
                    elif isinstance(item, str) and item.strip():
                        proxies.append(Proxy(proxy_url=item.strip()))
                if proxies:
                    return proxies
        except json.JSONDecodeError:
            pass

        # 纯文本：每行一个
        proxies: List[Proxy] = []
        for line in raw.splitlines():
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            proxies.append(Proxy(proxy_url=line))
        return proxies

    # ---------------- 验证 & 获取 ----------------

    def validate(self, proxy: Proxy, *, test_url: str = "https://www.baidu.com") -> bool:
        """对单个代理做连通性验证。"""
        import urllib.request
        proxy_handler = urllib.request.ProxyHandler({"http": proxy.proxy_url, "https": proxy.proxy_url})
        opener = urllib.request.build_opener(proxy_handler)
        try:
            req = urllib.request.Request(test_url, headers={"User-Agent": "curl/8.0"})
            with opener.open(req, timeout=self._validate_timeout) as resp:
                return 200 <= int(resp.status) < 400
        except Exception:
            return False

    def next(self) -> Optional[Proxy]:
        """轮询获取下一个可用代理；直连模式或空池返回 None。"""
        if self._direct_mode:
            return None
        with self._lock:
            if not self._proxies:
                return None
            # 最多尝试一轮，避免被卡死（即便全都是失败的也返回一个）
            size = len(self._proxies)
            for _ in range(size):
                idx = self._index % size
                self._index = idx + 1
                proxy = self._proxies[idx]
                if proxy.failure_count < self._failure_threshold:
                    proxy.last_used_at = time.time()
                    return proxy
            # 若全部失败，重置计数器，返回第一个（允许 SDK 再试）
            for p in self._proxies:
                p.failure_count = 0
            self._index = 0
            first = self._proxies[0]
            first.last_used_at = time.time()
            return first

    def report_failure(self, proxy: Proxy, reason: str = "") -> None:
        """报告某个代理请求失败。"""
        if proxy is None:
            return
        with self._lock:
            proxy.failure_count += 1
            proxy.last_failure_reason = reason or ""
            if proxy.failure_count >= self._failure_threshold:
                # 剔除
                try:
                    self._proxies.remove(proxy)
                except ValueError:
                    pass
                logger.warning(f"代理已剔除 (失败 {self._failure_threshold} 次): {proxy.proxy_url}")
                if not self._proxies and not self._direct_mode:
                    logger.error("代理池为空，请求将回退直连")

    def report_success(self, proxy: Proxy) -> None:
        if proxy is None:
            return
        with self._lock:
            proxy.failure_count = 0
            proxy.last_used_at = time.time()


__all__ = ["ProxyPool", "Proxy"]
