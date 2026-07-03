from __future__ import annotations

import time
import threading
from typing import Dict, Optional
from urllib.parse import urlparse
from urllib.robotparser import RobotFileParser

from infra.logger_setup import get_logger
from core.spider_core.exceptions import BlockedByRobotsError

logger = get_logger("spider.robots")


class RobotsChecker:
    """站点 robots.txt 解析与缓存。"""

    def __init__(
        self,
        *,
        enabled: bool = True,
        cache_ttl: float = 3600.0,
        user_agent: str = "",
    ) -> None:
        self._enabled = bool(enabled)
        self._cache_ttl = float(cache_ttl)
        self._user_agent = user_agent or "*"
        self._cache: Dict[str, Dict] = {}
        self._lock = threading.RLock()

    # ---------------- 内部 ----------------

    def _site_root(self, url: str) -> str:
        parsed = urlparse(url)
        if not parsed.scheme or not parsed.netloc:
            return url
        return f"{parsed.scheme}://{parsed.netloc}"

    def _parser_for(self, site_root: str) -> RobotFileParser:
        now = time.time()
        with self._lock:
            entry = self._cache.get(site_root)
            if entry and (now - entry["fetched_at"]) < self._cache_ttl:
                return entry["parser"]

        parser = RobotFileParser()
        robots_url = site_root.rstrip("/") + "/robots.txt"
        try:
            parser.set_url(robots_url)
            parser.read()
        except Exception as exc:
            logger.warning(f"robots.txt 读取失败 ({robots_url}: {exc}")
            # 失败时视为"允许全部"，但不缓存，下次重新拉取
            parser = _permissive_parser()
        with self._lock:
            self._cache[site_root] = {"parser": parser, "fetched_at": time.time()}
        return parser

    # ---------------- 对外 API ----------------

    def is_allowed(self, url: str, *, user_agent: Optional[str] = None) -> bool:
        if not self._enabled:
            return True
        site_root = self._site_root(url)
        parser = self._parser_for(site_root)
        return parser.can_fetch(user_agent or self._user_agent, url)

    def ensure_allowed(self, url: str, *, user_agent: Optional[str] = None) -> None:
        if self.is_allowed(url, user_agent=user_agent):
            return
        logger.info(f"blocked by robots: {url}")
        raise BlockedByRobotsError(url=url)

    def clear_cache(self, site_root: Optional[str] = None) -> None:
        with self._lock:
            if site_root is None:
                self._cache.clear()
            else:
                self._cache.pop(self._site_root(site_root), None)


def _permissive_parser() -> RobotFileParser:
    """构造一个"允许全部"的 RobotFileParser 实例。"""
    # 通过解析一个空的 robots.txt 文本。"""
    from io import StringIO
    parser = RobotFileParser()
    parser.parse(StringIO("").readlines() if False else [])  # 默认为无规则 → 允许
    parser.allow_all = True
    return parser


__all__ = ["RobotsChecker"]
