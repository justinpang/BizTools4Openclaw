from __future__ import annotations

import random
import threading
import time
from typing import Dict, Optional

from infra.logger_setup import get_logger

logger = get_logger("spider.rate_limiter")


def _extract_domain(url_or_domain: str) -> str:
    if "://" in url_or_domain:
        try:
            from urllib.parse import urlparse
            parsed = urlparse(url_or_domain)
            return parsed.netloc.lower() or url_or_domain.lower()
        except Exception:
            return url_or_domain.lower()
    return url_or_domain.lower()


class DomainRateLimiter:
    """单域名请求间隔随机 + 并发上限控制。"""

    def __init__(
        self,
        *,
        interval_min: float = 1.0,
        interval_max: float = 3.0,
        max_concurrent_per_domain: int = 5,
        global_max_concurrent: int = 20,
        overrides: Optional[Dict[str, dict]] = None,
    ) -> None:
        self._interval_min = float(interval_min)
        self._interval_max = float(interval_max)
        self._max_concurrent_per_domain = int(max_concurrent_per_domain)
        self._global_max = int(global_max_concurrent)
        self._domain_overrides: Dict[str, dict] = dict(overrides or {})

        self._domain_last_hit: Dict[str, float] = {}
        self._domain_sem: Dict[str, threading.Semaphore] = {}
        self._global_sem = threading.Semaphore(max(1, self._global_max))
        self._lock = threading.RLock()

    # ---------------- 配置覆盖 ----------------

    def override(
        self,
        domain: str,
        *,
        interval_min: Optional[float] = None,
        interval_max: Optional[float] = None,
        max_concurrent: Optional[int] = None,
    ) -> None:
        key = _extract_domain(domain)
        with self._lock:
            current = self._domain_overrides.get(key, {})
            if interval_min is not None:
                current["interval_min"] = float(interval_min)
            if interval_max is not None:
                current["interval_max"] = float(interval_max)
            if max_concurrent is not None:
                current["max_concurrent"] = int(max_concurrent)
            self._domain_overrides[key] = current
            # 若 semaphore 已存在且并发上限更新，重建
            if max_concurrent is not None and key in self._domain_sem:
                self._domain_sem[key] = threading.Semaphore(max(1, int(max_concurrent)))
            logger.info(f"域限速覆盖更新: {key} -> {current}")

    def reset(self, domain: Optional[str] = None) -> None:
        with self._lock:
            if domain is None:
                self._domain_last_hit.clear()
                self._domain_sem.clear()
            else:
                key = _extract_domain(domain)
                self._domain_last_hit.pop(key, None)
                self._domain_sem.pop(key, None)

    # ---------------- 核心 ----------------

    def _domain_config(self, domain: str) -> dict:
        with self._lock:
            override = self._domain_overrides.get(domain)
            if override:
                return {
                    "interval_min": override.get("interval_min", self._interval_min),
                    "interval_max": override.get("interval_max", self._interval_max),
                    "max_concurrent": override.get("max_concurrent", self._max_concurrent_per_domain),
                }
            return {
                "interval_min": self._interval_min,
                "interval_max": self._interval_max,
                "max_concurrent": self._max_concurrent_per_domain,
            }

    def _get_or_create_sem(self, domain: str, max_concurrent: int) -> threading.Semaphore:
        with self._lock:
            sem = self._domain_sem.get(domain)
            if sem is None:
                sem = threading.Semaphore(max(1, max_concurrent))
                self._domain_sem[domain] = sem
            return sem

    def acquire(self, url_or_domain: str) -> "_RateLimitToken":
        """获取一个限速 token，使用 with 上下文。"""
        domain = _extract_domain(url_or_domain)
        cfg = self._domain_config(domain)

        # 先 sleep（如果需要）保证最小间隔
        now = time.monotonic()
        with self._lock:
            last_hit = self._domain_last_hit.get(domain, 0.0)
        sleep_for = random.uniform(cfg["interval_min"], cfg["interval_max"])
        if last_hit > 0:
            elapsed = now - last_hit
            if elapsed < sleep_for:
                remaining = sleep_for - elapsed
                if remaining > 0:
                    time.sleep(remaining)
        # 拿 semaphore
        self._global_sem.acquire()
        sem = self._get_or_create_sem(domain, cfg["max_concurrent"])
        sem.acquire()
        return _RateLimitToken(self, domain)


class _RateLimitToken:
    def __init__(self, limiter: DomainRateLimiter, domain: str) -> None:
        self._limiter = limiter
        self._domain = domain
        self._released = False

    def __enter__(self) -> "_RateLimitToken":
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        if self._released:
            return
        self._released = True
        # 更新 last_hit
        with self._limiter._lock:
            self._limiter._domain_last_hit[self._domain] = time.monotonic()
        # 释放 semaphore（可能与获取顺序不一致，但这是安全的）
        try:
            domain_sem = self._limiter._domain_sem.get(self._domain)
            if domain_sem is not None:
                domain_sem.release()
        except Exception:
            pass
        try:
            self._limiter._global_sem.release()
        except Exception:
            pass


__all__ = ["DomainRateLimiter"]
