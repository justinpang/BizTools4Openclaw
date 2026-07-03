from __future__ import annotations

import os
import time
from dataclasses import dataclass
from enum import Enum
from typing import Any

from infra.logger_setup import get_logger

logger = get_logger("send_core.failure_retry")


class FailureCategory(Enum):
    NETWORK = "network"          # 网络/超时/500，可重试
    RATE_LIMITED = "rate_limited"  # 限流，可重试但间隔拉长
    BAN = "ban"                  # 账号封禁/内容违规，不重试
    CONTENT = "content"          # 内容违规，不重试
    UNKNOWN = "unknown"          # 未知，默认不重试


@dataclass
class RetryDecision:
    should_retry: bool
    delay_seconds: float
    category: FailureCategory
    reason: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "should_retry": self.should_retry,
            "delay_seconds": self.delay_seconds,
            "category": self.category.value,
            "reason": self.reason,
        }


class FailureRetryPolicy:
    """差异化失败重试策略。

    规则：
    - NETWORK       → max_network_attempts 次，指数退避 base_delay × 2^n
    - RATE_LIMITED  → max_rate_attempts 次，更长的固定间隔
    - BAN / CONTENT → 0 次，立即标记失败并告警
    - UNKNOWN       → 0 次
    """

    def __init__(
        self,
        *,
        max_network_attempts: int | None = None,
        network_base_delay: float | None = None,
        max_rate_attempts: int | None = None,
        rate_base_delay: float | None = None,
    ) -> None:
        self._max_network = int(
            max_network_attempts if max_network_attempts is not None
            else os.environ.get("SEND_NETWORK_RETRY", "3")
        )
        self._net_base = float(
            network_base_delay if network_base_delay is not None
            else os.environ.get("SEND_NETWORK_BASE_DELAY", "10")
        )
        self._max_rate = int(
            max_rate_attempts if max_rate_attempts is not None
            else os.environ.get("SEND_RATE_RETRY", "2")
        )
        self._rate_base = float(
            rate_base_delay if rate_base_delay is not None
            else os.environ.get("SEND_RATE_BASE_DELAY", "30")
        )

    # ---------------- 分类 ----------------

    def classify(
        self,
        *,
        exception: Any = None,
        status_code: str | int | None = None,
        response_text: str | None = None,
    ) -> FailureCategory:
        """根据返回或异常分类。"""
        # 内容 / 违规关键词
        if response_text:
            rt = str(response_text).lower()
            for kw in ("content rejected", "内容违规", "blocked", "invalid content", "sensitive", "违禁"):
                if kw in rt:
                    return FailureCategory.CONTENT
            for kw in ("banned", "forbidden", "rate limit", "rate_limit", "账号被限制", "消息拒收", "请勿频繁发送"):
                if kw in rt:
                    return FailureCategory.BAN
        # 显式状态码
        if status_code is not None:
            sc = str(status_code).upper()
            if sc in ("BANNED", "FORBIDDEN", "CONTENT_BLOCKED"):
                return FailureCategory.BAN
            if sc in ("RATE_LIMITED", "QUOTA_EXCEEDED", "TOO_MANY_REQUESTS"):
                return FailureCategory.RATE_LIMITED
            if sc in ("TIMEOUT", "NETWORK_ERROR", "GATEWAY_ERROR"):
                return FailureCategory.NETWORK
            # HTTP 状态码数值
            try:
                n = int(sc)
            except ValueError:
                n = -1
            if 500 <= n < 600:
                return FailureCategory.NETWORK
            if n in (429,):
                return FailureCategory.RATE_LIMITED
            if 400 <= n < 500 and n not in (404, 401, 403):
                # 4xx 中除认证外视为 BAN（含内容违规）
                return FailureCategory.BAN
        # 异常类型
        if exception is not None:
            ex_name = type(exception).__name__.lower()
            ex_msg = str(exception).lower() if str(exception) else ""
            if any(k in ex_name or k in ex_msg for k in ("timeout", "timeouterror", "connection", "network", "socket", "500")):
                return FailureCategory.NETWORK
            if any(k in ex_name or k in ex_msg for k in ("forbidden", "banned", "429", "rate")):
                return FailureCategory.BAN
        return FailureCategory.UNKNOWN

    # ---------------- 决策 ----------------

    def decide(self, category: FailureCategory, current_attempt: int) -> RetryDecision:
        if current_attempt < 0:
            current_attempt = 0
        if category == FailureCategory.NETWORK:
            if current_attempt < self._max_network:
                delay = self._net_base * (2 ** current_attempt)
                return RetryDecision(True, delay, category, reason=f"network_attempt_{current_attempt+1}/{self._max_network}")
            return RetryDecision(False, 0.0, category, reason="network_max_attempts_reached")
        if category == FailureCategory.RATE_LIMITED:
            if current_attempt < self._max_rate:
                delay = self._rate_base * (2 ** current_attempt)
                return RetryDecision(True, delay, category, reason=f"rate_limited_attempt_{current_attempt+1}/{self._max_rate}")
            return RetryDecision(False, 0.0, category, reason="rate_limited_max_attempts_reached")
        if category == FailureCategory.CONTENT:
            return RetryDecision(False, 0.0, category, reason="content_blocked_no_retry")
        if category == FailureCategory.BAN:
            return RetryDecision(False, 0.0, category, reason="account_ban_no_retry")
        return RetryDecision(False, 0.0, category, reason="unknown_no_retry")

    # ---------------- 便捷：sleep ----------------

    def sleep_for(self, decision: RetryDecision, *, max_sleep: float = 600.0) -> float:
        if not decision.should_retry or decision.delay_seconds <= 0:
            return 0.0
        delay = min(decision.delay_seconds, max_sleep)
        time.sleep(delay)
        return delay


# ============================================================
# 模块级单例
# ============================================================


def _build_default() -> FailureRetryPolicy:
    return FailureRetryPolicy()


failure_retry: FailureRetryPolicy
try:
    failure_retry = _build_default()
except Exception as exc:
    logger.warning(f"FailureRetryPolicy 默认实例初始化失败：{exc}")
    failure_retry = FailureRetryPolicy()


__all__ = ["FailureCategory", "RetryDecision", "FailureRetryPolicy", "failure_retry"]
