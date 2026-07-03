from __future__ import annotations

import os
import threading
import time
from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime
from hashlib import sha256
from typing import Any

from infra.logger_setup import get_logger

logger = get_logger("send_core.rate_limiter")


# ============================================================
# 数据类
# ============================================================


@dataclass
class RateCheckResult:
    allowed: bool
    rejected_reason: str | None = None
    limits_hit: list[str] = None

    def __post_init__(self) -> None:
        if self.limits_hit is None:
            self.limits_hit = []


# ============================================================
# RateLimiter 主类
# ============================================================


class RateLimiter:
    """分层限流控制器。

    四层检查：
    1. SEND_GLOBAL_DAILY_LIMIT   - 全局日发送总量
    2. SEND_ACCOUNT_DAILY_LIMIT  - 单账号日发送总量
    3. SEND_ACCOUNT_HOURLY_LIMIT - 单账号小时发送频率
    4. SEND_USER_GAP_SECONDS     - 单用户最小发送间隔（防骚扰）
    """

    def __init__(
        self,
        *,
        global_daily: int | None = None,
        account_daily: int | None = None,
        account_hourly: int | None = None,
        user_gap_seconds: int | None = None,
        key_ttl_seconds: int | None = None,
        redis_client: Any = None,
    ) -> None:
        self._global_daily = int(
            global_daily if global_daily is not None else os.environ.get("SEND_GLOBAL_DAILY_LIMIT", "5000")
        )
        self._account_daily = int(
            account_daily if account_daily is not None else os.environ.get("SEND_ACCOUNT_DAILY_LIMIT_DEFAULT", "100")
        )
        self._account_hourly = int(
            account_hourly if account_hourly is not None else os.environ.get("SEND_ACCOUNT_HOURLY_LIMIT", "30")
        )
        self._user_gap_seconds = int(
            user_gap_seconds if user_gap_seconds is not None else os.environ.get("SEND_USER_GAP_SECONDS", "300")
        )
        self._key_ttl = int(
            key_ttl_seconds if key_ttl_seconds is not None else os.environ.get("SEND_RATE_KEY_TTL_SECONDS", "259200")
        )

        self._redis = redis_client  # 允许测试注入 fake-redis
        self._lock = threading.RLock()
        # Redis 降级时的进程内回退
        self._fallback: dict[str, int] = defaultdict(int)
        self._fallback_time: dict[str, float] = {}

    # ---------------- 主 API ----------------

    def check_and_increment(
        self,
        *,
        account_id: str,
        user_id: str | None = None,
        channel: str = "unknown",
    ) -> RateCheckResult:
        """同步执行四层检查。全部通过后原子递增计数。"""
        hits: list[str] = []
        reason: str | None = None

        now = time.time()
        date_str = datetime.fromtimestamp(now).strftime("%Y%m%d")
        hour_str = datetime.fromtimestamp(now).strftime("%H")

        keys = {
            "global": f"send:quota:global:{date_str}",
            "acct_day": f"send:quota:account:{account_id}:{date_str}",
            "acct_hour": f"send:freq:hour:{account_id}:{hour_str}",
            "user_gap": f"send:user:gap:{_hash_user(user_id)}" if user_id else None,
        }

        # 预检查（不消耗额度）
        if self._redis_available():
            try:
                with self._get_redis() as r:
                    global_count = int(r.get(keys["global"]) or 0)
                    if global_count >= self._global_daily:
                        hits.append("global_daily")
                    acct_day = int(r.get(keys["acct_day"]) or 0)
                    if acct_day >= self._account_daily:
                        hits.append("account_daily")
                    acct_hour = int(r.get(keys["acct_hour"]) or 0)
                    if acct_hour >= self._account_hourly:
                        hits.append("account_hourly")
                    if keys["user_gap"]:
                        last_ts = r.get(keys["user_gap"])
                        if last_ts is not None and (now - float(last_ts)) < self._user_gap_seconds:
                            hits.append("user_gap")
            except Exception as exc:
                logger.warning(f"Redis 限流失败，降级到进程内：{exc}")
                self._fallback_check(keys, now, hits)
        else:
            self._fallback_check(keys, now, hits)

        if hits:
            reason = f"hit_limits={','.join(hits)}; channel={channel}"
            logger.info(f"[rate_limiter] 拦截发送：{reason}")
            return RateCheckResult(allowed=False, rejected_reason=reason, limits_hit=list(hits))

        # 通过：写回计数
        if self._redis_available():
            try:
                with self._get_redis() as r:
                    pipe = r.pipeline()
                    pipe.incr(keys["global"])
                    pipe.expire(keys["global"], self._key_ttl)
                    pipe.incr(keys["acct_day"])
                    pipe.expire(keys["acct_day"], self._key_ttl)
                    pipe.incr(keys["acct_hour"])
                    pipe.expire(keys["acct_hour"], self._key_ttl)
                    if keys["user_gap"]:
                        pipe.set(keys["user_gap"], now, ex=self._user_gap_seconds + 60)
                    pipe.execute()
                return RateCheckResult(allowed=True)
            except Exception as exc:
                logger.warning(f"Redis 写入失败，降级到进程内：{exc}")

        self._fallback_increment(keys, now)
        return RateCheckResult(allowed=True)

    # ---------------- 降级（进程内） ----------------

    def _fallback_check(self, keys: dict[str, str | None], now: float, hits: list[str]) -> None:
        with self._lock:
            if self._fallback[keys["global"]] >= self._global_daily:
                hits.append("global_daily")
            if self._fallback[keys["acct_day"]] >= self._account_daily:
                hits.append("account_daily")
            if self._fallback[keys["acct_hour"]] >= self._account_hourly:
                hits.append("account_hourly")
            if keys["user_gap"]:
                last = self._fallback_time.get(keys["user_gap"], 0.0)
                if last and (now - last) < self._user_gap_seconds:
                    hits.append("user_gap")

    def _fallback_increment(self, keys: dict[str, str | None], now: float) -> None:
        with self._lock:
            self._fallback[keys["global"]] += 1
            self._fallback[keys["acct_day"]] += 1
            self._fallback[keys["acct_hour"]] += 1
            if keys["user_gap"]:
                self._fallback_time[keys["user_gap"]] = now

    # ---------------- Redis 访问封装 ----------------

    def _redis_available(self) -> bool:
        try:
            if self._redis is not None:
                return True
            from infra.redis_client import redis_client as rc
            return rc.ping(fail_silently=True)
        except Exception:
            return False

    def _get_redis(self) -> Any:
        if self._redis is not None:
            class _Ctx:
                def __init__(self, r): self.r = r
                def __enter__(self): return self.r
                def __exit__(self, exc_type, exc, tb): return None
            return _Ctx(self._redis)
        from infra.redis_client import redis_client as rc
        return rc.acquire()

    # ---------------- 查询/调试 ----------------

    def get_current(self, *, account_id: str) -> dict[str, int]:
        now = time.time()
        date_str = datetime.fromtimestamp(now).strftime("%Y%m%d")
        hour_str = datetime.fromtimestamp(now).strftime("%H")
        keys = {
            "global_day": f"send:quota:global:{date_str}",
            "account_day": f"send:quota:account:{account_id}:{date_str}",
            "account_hour": f"send:freq:hour:{account_id}:{hour_str}",
        }
        result: dict[str, int] = {}
        try:
            if self._redis_available():
                with self._get_redis() as r:
                    for key_name, k in keys.items():
                        val = r.get(k)
                        result[key_name] = int(val) if val is not None else 0
            else:
                for key_name, k in keys.items():
                    result[key_name] = self._fallback.get(k, 0)
        except Exception as exc:
            logger.warning(f"get_current 失败：{exc}")
            result = {k: 0 for k in keys}
        return result


# ============================================================
# 辅助
# ============================================================


def _hash_user(user_id: str | None) -> str:
    if not user_id:
        return "none"
    return sha256(user_id.encode("utf-8")).hexdigest()[:16]


# ============================================================
# 模块级单例
# ============================================================


def _build_default() -> RateLimiter:
    return RateLimiter()


rate_limiter: RateLimiter
try:
    rate_limiter = _build_default()
except Exception as exc:
    logger.warning(f"RateLimiter 默认实例初始化失败：{exc}")
    rate_limiter = RateLimiter()


__all__ = ["RateCheckResult", "RateLimiter", "rate_limiter"]
