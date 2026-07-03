from __future__ import annotations

import threading
import time
from dataclasses import dataclass, field
from typing import Any, Callable

from infra.logger_setup import get_logger

logger = get_logger("send_core.pipeline")


# ============================================================
# 数据类
# ============================================================


@dataclass
class SendPipelineResult:
    task_id: str
    success: bool = False
    final_status: str = "UNKNOWN"
    reason: str | None = None
    attempts: int = 0
    masked_recipient: str = ""
    masked_content: str = ""
    warnings: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "task_id": self.task_id,
            "success": self.success,
            "final_status": self.final_status,
            "reason": self.reason,
            "attempts": self.attempts,
            "masked_recipient": self.masked_recipient,
            "masked_content": self.masked_content,
            "warnings": self.warnings,
        }


# ============================================================
# SendPipeline 主类
# ============================================================


class SendPipeline:
    """统一发送管线。

    流程：
    1. 内容风控（T06）- 失败 → CONTENT_BLOCKED
    2. 限流（全局日/账号日/小时/用户间隔）- 失败 → RATE_LIMITED
    3. 账号分配 - 失败 → FAILED
    4. 调用发送函数 sender_fn(account, recipient, content) - 返回 (ok, status_code, message)
    5. 根据发送结果：
        - 成功 → SUCCESS
        - 失败 → 分类（NETWORK / RATE / BAN / CONTENT）→ 按策略重试
    6. 重试超限 → FAILED 并告警
    """

    def __init__(
        self,
        *,
        account_pool: Any = None,
        rate_limiter: Any = None,
        content_risk: Any = None,
        failure_retry: Any = None,
        ban_detector: Any = None,
        task_status: Any = None,
        alert_service: Any = None,
        max_total_attempts: int = 5,
    ) -> None:
        self._account_pool = account_pool
        self._rate_limiter = rate_limiter
        self._content_risk = content_risk
        self._failure_retry = failure_retry
        self._ban_detector = ban_detector
        self._task_status = task_status
        self._alert = alert_service
        self._max_total_attempts = max_total_attempts
        self._lock = threading.RLock()

    # ---------------- 懒加载单例 ----------------

    def _get_pool(self):
        if self._account_pool is None:
            from core.send_core.account_pool import account_pool as p
            self._account_pool = p
        return self._account_pool

    def _get_rate(self):
        if self._rate_limiter is None:
            from core.send_core.rate_limiter import rate_limiter as r
            self._rate_limiter = r
        return self._rate_limiter

    def _get_risk(self):
        if self._content_risk is None:
            from core.send_core.content_risk import content_risk as c
            self._content_risk = c
        return self._content_risk

    def _get_retry(self):
        if self._failure_retry is None:
            from core.send_core.failure_retry import failure_retry as f
            self._failure_retry = f
        return self._failure_retry

    def _get_ban(self):
        if self._ban_detector is None:
            from core.send_core.ban_detector import ban_detector as b
            self._ban_detector = b
        return self._ban_detector

    def _get_status(self):
        if self._task_status is None:
            from core.send_core.task_status import task_status_store as t
            self._task_status = t
        return self._task_status

    # ---------------- 发送器入口 ----------------

    def send(
        self,
        *,
        task_id: str,
        channel: str,
        content: str,
        recipient: Any,
        sender_fn: Callable[..., tuple[bool, str | int | None, str]],
        user_id: str | None = None,
        extra: dict[str, Any] | None = None,
    ) -> SendPipelineResult:
        result = SendPipelineResult(task_id=task_id)
        risk = self._get_risk().check_content(content, recipient)
        result.masked_recipient = risk.masked_recipient
        result.masked_content = risk.masked_content
        if risk.is_blocked:
            self._get_status().mark_content_blocked(
                task_id, message=";".join(risk.reasons)[:200], channel=channel,
            )
            result.final_status = "CONTENT_BLOCKED"
            result.reason = ";".join(risk.reasons)
            self._emit_alert_if_needed("content_blocked", task_id, result)
            return result

        pool = self._get_pool()
        rate = self._get_rate()
        retry_policy = self._get_retry()
        ban = self._get_ban()
        if hasattr(ban, "set_account_pool"):
            ban.set_account_pool(pool)
        status_store = self._get_status()
        from core.send_core.failure_retry import FailureCategory as _FC

        total_attempts = 0
        last_error: str | None = None

        while total_attempts < self._max_total_attempts:
            # 选账号
            account = pool.pick(channel)
            if account is None:
                result.warnings.append("no_available_account")
                result.final_status = "FAILED"
                result.reason = "无可用账号"
                status_store.mark_failed(task_id, message="no_available_account", channel=channel)
                self._emit_alert_if_needed("no_account", task_id, result)
                return result

            # 限流
            rate_result = rate.check_and_increment(
                account_id=account.account_id,
                user_id=user_id,
                channel=channel,
            )
            if not rate_result.allowed:
                result.warnings.append("rate_limited:" + str(rate_result.limits_hit))
                decision = retry_policy.decide(_FC.RATE_LIMITED, total_attempts)
                if decision.should_retry:
                    time.sleep(min(decision.delay_seconds, 30))
                    total_attempts += 1
                    continue
                result.final_status = "RATE_LIMITED"
                result.reason = rate_result.rejected_reason
                status_store.mark_rate_limited(
                    task_id, message=rate_result.rejected_reason or "", channel=channel,
                )
                return result

            # 发送
            total_attempts += 1
            status_store.mark_sending(task_id, channel=channel, account_id=account.account_id)
            ok, status_code, message = False, None, ""
            try:
                ok, status_code, message = sender_fn(
                    account=account, recipient=recipient, content=content, extra=extra,
                )
            except Exception as exc:
                ok = False
                status_code = "EXCEPTION"
                message = f"{type(exc).__name__}: {exc}"
                logger.warning(f"[send_pipeline] sender_fn 异常：{message}")

            if ok:
                status_store.mark_success(
                    task_id, channel=channel, account_id=account.account_id,
                    message=message[:200] if message else None,
                )
                if hasattr(ban, "record_success"):
                    ban.record_success(account.account_id)
                result.success = True
                result.final_status = "SUCCESS"
                result.attempts = total_attempts
                return result

            # 失败：分类 + 决策
            last_error = message
            category = retry_policy.classify(
                exception=None, status_code=status_code, response_text=message,
            )
            # 封禁检测
            ban_check = ban.detect_from_response(
                status_code=status_code, response_text=message,
                channel=channel, account_id=account.account_id,
            )
            if ban_check.is_ban or category in (_FC.BAN, _FC.CONTENT):
                status_store.mark_banned(
                    task_id, message=message[:200] if message else "ban_detected",
                    channel=channel, account_id=account.account_id,
                )
                result.final_status = "BANNED"
                result.reason = (message or "ban_detected")[:200]
                self._emit_alert_if_needed("ban", task_id, result)
                return result

            if category == _FC.NETWORK and hasattr(ban, "record_network_failure"):
                ban.record_network_failure(account.account_id)

            decision = retry_policy.decide(category, total_attempts)
            if decision.should_retry:
                time.sleep(min(decision.delay_seconds, 120))
                continue
            break

        status_store.mark_failed(
            task_id, message=(last_error or "max_attempts_reached")[:200], channel=channel,
        )
        result.final_status = "FAILED"
        result.reason = last_error
        result.attempts = total_attempts
        self._emit_alert_if_needed("final_failed", task_id, result)
        return result

    # ---------------- 告警 ----------------

    def _emit_alert_if_needed(self, alert_key: str, task_id: str, result: SendPipelineResult) -> None:
        try:
            if self._alert is None:
                from infra.alerting import alert_service as a
                self._alert = a
            if hasattr(self._alert, "service_exception_sync"):
                message = (
                    f"[send_core:{alert_key}] task={task_id} "
                    f"status={result.final_status} recipient={result.masked_recipient} "
                    f"reason_preview={(result.reason or '')[:80]}"
                )
                self._alert.service_exception_sync(
                    service_name="send_core", message=message, extra={"alert_key": alert_key},
                )
        except Exception as exc:
            logger.warning(f"告警推送失败：{exc}")


# ============================================================
# 模块级单例
# ============================================================


def _build_default() -> SendPipeline:
    return SendPipeline()


send_pipeline: SendPipeline
try:
    send_pipeline = _build_default()
except Exception as exc:
    logger.warning(f"SendPipeline 默认实例初始化失败：{exc}")
    send_pipeline = SendPipeline()


__all__ = ["SendPipelineResult", "SendPipeline", "send_pipeline"]
