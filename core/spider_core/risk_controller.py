from __future__ import annotations

import json
import threading
import time
from dataclasses import dataclass
from typing import Any, Dict, List, Optional

from infra.logger_setup import get_logger

logger = get_logger("spider.risk")

# 级别定义
RISK_LEVEL_NONE = "none"
RISK_LEVEL_LOW = "low"
RISK_LEVEL_MEDIUM = "medium"
RISK_LEVEL_HIGH = "high"

# 动作定义
RISK_ACTION_NONE = "none"
RISK_ACTION_BACKOFF = "backoff"
RISK_ACTION_SWITCH_AND_BACKOFF = "switch_and_backoff"

# 默认封禁关键词
DEFAULT_BAN_PATTERNS: List[str] = [
    "页面不存在",
    "请完成验证",
    "系统繁忙",
    "Access Denied",
    "Your IP has been banned",
    "blocked",
    "forbidden",
]

DEFAULT_CAPTCHA_PATTERNS: List[str] = [
    "captcha",
    "验证码",
    "人机验证",
    "geetest",
    "hCaptcha",
    "reCAPTCHA",
]

DEFAULT_LOGIN_PATTERNS: List[str] = [
    "/login",
    "/signin",
    "登录",
    "Sign in",
]

HIGH_STATUS_CODES = {403, 429, 503}
MEDIUM_STATUS_CODES = {401, 404, 500, 502, 504}


@dataclass
class _DomainCounter:
    consecutive_high: int = 0
    total_high: int = 0
    last_backoff_at: float = 0.0
    last_alert_at: float = 0.0


class RiskController:
    """风控识别 + 降级动作。"""

    def __init__(
        self,
        *,
        enabled: bool = True,
        ban_patterns: Optional[List[str]] = None,
        captcha_patterns: Optional[List[str]] = None,
        login_redirect_patterns: Optional[List[str]] = None,
        consecutive_ban_trigger: int = 3,
        backoff_interval_min: float = 10.0,
        backoff_interval_max: float = 30.0,
        alert_debounce_seconds: float = 600.0,
    ) -> None:
        self._enabled = bool(enabled)
        self._ban_patterns = [p for p in (ban_patterns or DEFAULT_BAN_PATTERNS) if p]
        self._captcha_patterns = [p for p in (captcha_patterns or DEFAULT_CAPTCHA_PATTERNS) if p]
        self._login_patterns = [p for p in (login_redirect_patterns or DEFAULT_LOGIN_PATTERNS) if p]
        self._consecutive_trigger = int(consecutive_ban_trigger)
        self._backoff_min = float(backoff_interval_min)
        self._backoff_max = float(backoff_interval_max)
        self._alert_debounce = float(alert_debounce_seconds)

        self._counters: Dict[str, _DomainCounter] = {}
        self._lock = threading.RLock()

        # 外部依赖（可注入）
        self._rate_limiter_ref: Any = None  # 在 SDK 中赋值
        self._proxy_pool_ref: Any = None
        self._alert_service_ref: Any = None

    # ---------------- 注入 ----------------

    def attach(self, *, rate_limiter: Any = None, proxy_pool: Any = None, alert_service: Any = None) -> None:
        if rate_limiter is not None:
            self._rate_limiter_ref = rate_limiter
        if proxy_pool is not None:
            self._proxy_pool_ref = proxy_pool
        if alert_service is not None:
            self._alert_service_ref = alert_service

    # ---------------- 识别 ----------------

    def detect(self, *, status_code: int = 0, text: str = "", final_url: str = "", headers: Optional[Dict] = None) -> str:
        """返回 risk level 字符串。"""
        if not self._enabled:
            return RISK_LEVEL_NONE

        # 状态码
        if status_code in HIGH_STATUS_CODES:
            return RISK_LEVEL_HIGH
        if status_code in MEDIUM_STATUS_CODES:
            return RISK_LEVEL_MEDIUM

        # 文本关键词
        if text:
            text_low = text.lower()
            for pat in self._ban_patterns:
                if pat and pat.lower() in text_low:
                    return RISK_LEVEL_HIGH
            # 验证码 + 页面较短 → 高风险
            for pat in self._captcha_patterns:
                if pat and pat.lower() in text_low and len(text) < 4096:
                    return RISK_LEVEL_HIGH

        # 登录跳转
        if final_url:
            for pat in self._login_patterns:
                if pat and (pat in final_url):
                    return RISK_LEVEL_MEDIUM

        # Cloudflare 等典型 CDN header
        if headers:
            header_text = " ".join(str(h) for h in headers.keys()) + " " + " ".join(str(v) for v in headers.values())
            for marker in ("cf-ray", "cloudflare", "x-bot-detected", "set-cookie=cf_"):
                if marker.lower() in header_text.lower():
                    return RISK_LEVEL_MEDIUM

        return RISK_LEVEL_NONE

    # ---------------- 降级 ----------------

    def handle(self, url: str, level: str, *, response_excerpt: str = "") -> str:
        """执行降级动作，返回动作类型。"""
        if not self._enabled or level == RISK_LEVEL_NONE:
            return RISK_ACTION_NONE

        from urllib.parse import urlparse
        parsed = urlparse(url)
        domain = parsed.netloc.lower() or url.lower()
        with self._lock:
            counter = self._counters.setdefault(domain, _DomainCounter())

        if level == RISK_LEVEL_HIGH:
            with self._lock:
                counter.consecutive_high += 1
                counter.total_high += 1
                counter.last_backoff_at = time.time()
                trigger_extra_sleep = counter.consecutive_high >= self._consecutive_trigger

            # 1. 延长间隔 + 降并发上限
            if self._rate_limiter_ref is not None:
                try:
                    self._rate_limiter_ref.override(
                        domain,
                        interval_min=self._backoff_min,
                        interval_max=self._backoff_max,
                        max_concurrent=1,
                    )
                except Exception as exc:
                    logger.warning(f"rate_limiter override 失败: {exc}")
            # 2. 切换代理（将旧代理标记失败）
            if self._proxy_pool_ref is not None:
                try:
                    current = getattr(self._proxy_pool_ref, "_last_used", None)
                    if current is not None:
                        self._proxy_pool_ref.report_failure(current, reason="high_risk")
                    # 拉取下一个
                    self._proxy_pool_ref.next()
                except Exception as exc:
                    logger.warning(f"proxy_pool 切换失败: {exc}")
            # 3. 告警（去抖）
            self._try_alert(domain, counter, response_excerpt)
            # 4. 连续高风险 → 额外 sleep
            if trigger_extra_sleep:
                time.sleep(self._backoff_max)
                with self._lock:
                    counter.consecutive_high = 0  # 重置
            return RISK_ACTION_SWITCH_AND_BACKOFF

        if level == RISK_LEVEL_MEDIUM:
            if self._rate_limiter_ref is not None:
                try:
                    self._rate_limiter_ref.override(
                        domain,
                        interval_min=max(self._backoff_min / 2.0, 1.0),
                        interval_max=self._backoff_max / 2.0,
                    )
                except Exception as exc:
                    logger.warning(f"rate_limiter override 失败: {exc}")
            logger.warning(f"medium risk for {domain}: {response_excerpt[:120]}")
            return RISK_ACTION_BACKOFF

        # low/none
        with self._lock:
            counter.consecutive_high = 0
        return RISK_ACTION_NONE

    def _try_alert(self, domain: str, counter: _DomainCounter, excerpt: str) -> None:
        now = time.time()
        should_alert = (now - counter.last_alert_at) >= self._alert_debounce
        if not should_alert:
            return
        with self._lock:
            # double-check
            if (now - counter.last_alert_at) < self._alert_debounce:
                return
            counter.last_alert_at = now
        alert = self._alert_service_ref
        if alert is None:
            # 尝试延迟加载 alert service
            try:
                from infra.alerting import alert_service as _as
                alert = _as
            except Exception:
                alert = None
        if alert is not None:
            try:
                msg = f"[SPIDER] 风控高风险: domain={domain}, total_high={counter.total_high}, excerpt={excerpt[:200]}"
                # 兼容不同 alerting 接口
                if hasattr(alert, "crawler_risk_sync"):
                    alert.crawler_risk_sync(msg)
                elif hasattr(alert, "send_alert_sync"):
                    alert.send_alert_sync(msg)
                else:
                    logger.warning(f"alert_service 无可用方法: {dir(alert)}")
                    logger.warning(msg)
            except Exception as exc:
                logger.warning(f"风控告警发送失败: {exc}")
        else:
            logger.warning(f"[SPIDER-RISK (no alert_service)] domain={domain}, total_high={counter.total_high}")

    # ---------------- 查询 / 重置 ----------------

    def get_domain_status(self, domain: str) -> Dict[str, Any]:
        with self._lock:
            c = self._counters.get(domain) or _DomainCounter()
            return {
                "consecutive_high_risk": c.consecutive_high,
                "total_high_risk": c.total_high,
                "last_backoff_at": c.last_backoff_at,
                "last_alert_at": c.last_alert_at,
            }

    def reset(self, domain: Optional[str] = None) -> None:
        with self._lock:
            if domain is None:
                self._counters.clear()
            else:
                self._counters.pop(domain, None)


__all__ = [
    "RiskController",
    "RISK_LEVEL_NONE",
    "RISK_LEVEL_LOW",
    "RISK_LEVEL_MEDIUM",
    "RISK_LEVEL_HIGH",
    "RISK_ACTION_NONE",
    "RISK_ACTION_BACKOFF",
    "RISK_ACTION_SWITCH_AND_BACKOFF",
]
