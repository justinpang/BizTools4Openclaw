from __future__ import annotations

import os
import threading
import time
from dataclasses import dataclass, field
from typing import Any

from infra.logger_setup import get_logger

logger = get_logger("send_core.ban_detector")


_DEFAULT_BAN_KEYWORDS = (
    "账号被限制", "账号被封", "消息拒收", "请勿频繁发送", "内容违规",
    "rate limit", "rate_limit", "rate limited", "banned", "forbidden", "429",
)


@dataclass
class BanCheckResult:
    is_ban: bool = False
    matched_keywords: list[str] = field(default_factory=list)
    reason: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {"is_ban": self.is_ban, "matched_keywords": self.matched_keywords, "reason": self.reason}


class BanDetector:
    """渠道封禁检测。

    规则：
    1. response_text 命中任一风控关键词 → 视为封禁
    2. status_code in ('BANNED','FORBIDDEN','RATE_LIMIT', 403, 429) → 视为封禁
    3. 同一账号连续 N 次 NETWORK_ERROR → 视为隐性封禁（默认 3 次）
    """

    def __init__(
        self,
        *,
        keywords: list[str] | None = None,
        consecutive_fail: int | None = None,
        account_pool: Any = None,
    ) -> None:
        self._keywords = list(keywords) if keywords else list(_DEFAULT_BAN_KEYWORDS)
        self._consecutive_fail = int(
            consecutive_fail if consecutive_fail is not None else os.environ.get("SEND_BAN_CONSECUTIVE_FAIL", "3")
        )
        self._account_pool = account_pool
        self._lock = threading.RLock()
        self._consecutive: dict[str, int] = {}

    # ---------------- 注入账号池（否则 ban 只写到内存） ----------------

    def set_account_pool(self, pool: Any) -> None:
        self._account_pool = pool

    # ---------------- 检测 ----------------

    def detect_from_response(
        self,
        *,
        status_code: str | int | None = None,
        response_text: str | None = None,
        channel: str | None = None,
        account_id: str | None = None,
    ) -> BanCheckResult:
        """基于单次响应判断是否封禁。"""
        matched: list[str] = []
        if response_text:
            text_l = str(response_text).lower()
            for kw in self._keywords:
                if kw.lower() in text_l:
                    matched.append(kw)
        # 状态码判断
        if status_code is not None:
            sc = str(status_code).upper()
            if sc in ("BANNED", "FORBIDDEN", "RATE_LIMIT"):
                matched.append(f"status_code={sc}")
            try:
                n = int(sc)
                if n in (403, 429):
                    matched.append(f"status_code={n}")
            except ValueError:
                pass
        result = BanCheckResult(is_ban=bool(matched), matched_keywords=matched)
        if result.is_ban:
            result.reason = f"matched={matched[:5]}"
            if account_id and self._account_pool and hasattr(self._account_pool, "mark_banned"):
                self._account_pool.mark_banned(channel or "unknown", account_id, reason=result.reason)
            logger.warning(f"[ban_detector] 检测到封禁：account={account_id} reason={result.reason}")
        return result

    # ---------------- 连续失败计数 ----------------

    def record_network_failure(self, account_id: str) -> bool:
        """记录一次网络失败。达到连续阈值返回 True，视为隐性封禁。"""
        with self._lock:
            n = self._consecutive.get(account_id, 0) + 1
            self._consecutive[account_id] = n
            if n >= self._consecutive_fail:
                if self._account_pool and hasattr(self._account_pool, "mark_banned"):
                    self._account_pool.mark_banned(
                        "unknown", account_id, reason=f"consecutive_network_fail={n}"
                    )
                logger.warning(f"[ban_detector] 连续 {n} 次失败，账号 {account_id} 标记封禁")
                return True
        return False

    def record_success(self, account_id: str) -> None:
        with self._lock:
            self._consecutive.pop(account_id, None)

    # ---------------- 便捷：全渠道健康检查 ----------------

    def has_any_available(self, channel: str) -> bool:
        if self._account_pool is None:
            return True
        if hasattr(self._account_pool, "available_count"):
            return self._account_pool.available_count(channel) > 0
        return True


# ============================================================
# 模块级单例
# ============================================================


def _build_default() -> BanDetector:
    return BanDetector()


ban_detector: BanDetector
try:
    ban_detector = _build_default()
except Exception as exc:
    logger.warning(f"BanDetector 默认实例初始化失败：{exc}")
    ban_detector = BanDetector()


__all__ = ["BanCheckResult", "BanDetector", "ban_detector"]
