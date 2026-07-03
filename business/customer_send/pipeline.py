"""business/customer_send/pipeline — 商机触达流水线主类。"""

from __future__ import annotations

import time
import hashlib
from datetime import datetime
from typing import Any

from infra.logger_setup import get_logger
from configs.settings import settings

from business.customer_send.channels.email_channel import EmailChannel
from business.customer_send.channels.feishu_channel import FeishuChannel
from business.customer_send.channels.wechat_channel import WechatChannel
from business.customer_send.channels.h5_landing import H5Landing
from business.customer_send.models import (
    BatchSendParams,
    BatchSendResult,
    H5PageSpec,
    SendBehaviorLog,
    SingleSendResult,
)
from business.customer_send.storage import SendStorage
from business.customer_send.template_engine import build_variables, render

logger = get_logger("customer_send.pipeline")


_CHANNEL_MAP: dict[str, type] = {
    "email": EmailChannel,
    "wechat": WechatChannel,
    "feishu": FeishuChannel,
}


class CustomerSendPipeline:
    """完整的商机触达流水线。

    执行步骤：
        1. 为每个 target 构造模板变量（含 PII 脱敏与 H5 短链）
        2. 对每个 channel × target 调用 SendPipeline.send()：
           - content_risk 检查（敏感词/合规拦截 → status=BLOCKED）
           - AccountPool 均衡选取账号
           - RateLimiter 限流
           - 调用 Channel.send(account, recipient, rendered_content)
           - Retry 重试策略
        3. 根据 SendPipelineResult 写入 behavior 埋点
        4. 汇总 BatchSendResult
        5. 超阈值告警
        6. 写入 customer_send_job 结构化表
    """

    def __init__(self, storage: SendStorage | None = None):
        self.storage = storage or SendStorage(ensure_schema=True)

    # --------- 辅助: pipeline 级的 sender ---------

    def _send_via_core(
        self,
        *,
        channel: str,
        recipient: str,
        content: str,
        opportunity_id: str,
        target: Any,
        task_id: str,
        extra: dict[str, Any] | None = None,
    ) -> tuple[bool, str, str | None, int, str | None]:
        """使用 core.send_core.SendPipeline 执行发送。

        返回: (success, final_status, reason_or_none, attempts, masked_recipient)
        """
        extra = dict(extra or {})
        channel_cls = _CHANNEL_MAP.get(channel.lower())
        if channel_cls is None:
            return False, "UNKNOWN_CHANNEL", f"unknown_channel:{channel}", 0, recipient[:8] + "***"

        channel_inst = channel_cls()
        task_id_within = f"{task_id}__{opportunity_id}__{channel}"

        try:
            from core.send_core.send_pipeline import SendPipeline, send_pipeline as _sp
            sp = _sp if _sp is not None else SendPipeline()
        except Exception as exc:
            logger.warning(f"core.send_core 不可用，直接调用 channel.send(): {exc}")
            # fallback：直接调用 channel 发送（不经过风控/限流/重试）
            ok, code, msg = channel_inst.send(
                account=_MockAccount(token=""), recipient=recipient, content=content, extra=extra,
            )
            return (bool(ok), "SUCCESS" if ok else "FAILED", str(msg or "")[:200], 1, "")

        # 构造 send_pipeline 参数
        sender_fn = lambda account, recipient, content, extra=None: channel_inst.send(
            account=account, recipient=recipient, content=content, extra=extra or {},
        )
        try:
            result = sp.send(
                task_id=task_id_within,
                channel=channel,
                content=content,
                recipient=recipient,
                sender_fn=sender_fn,
                user_id=opportunity_id,
                extra=extra,
            )
            return (
                bool(getattr(result, "success", False)),
                str(getattr(result, "final_status", "FAILED") or "FAILED"),
                str(getattr(result, "reason", None) or "")[:200] or None,
                int(getattr(result, "attempts", 0) or 0),
                str(getattr(result, "masked_recipient", "") or "")
            )
        except Exception as exc:
            return False, "EXCEPTION", f"{type(exc).__name__}: {exc}"[:200], 1, recipient[:8] + "***"

    # --------- 主入口 ---------

    def run(self, params: BatchSendParams | dict) -> BatchSendResult:
        if isinstance(params, dict):
            params = BatchSendParams(**params)

        started_at = datetime.utcnow()
        started_at_iso = started_at.isoformat() + "Z"

        enabled_channels = [c.lower() for c in (params.channels or [])]
        # 根据配置开关过滤
        if not settings.customer_send.CUSTOMER_SEND_EMAIL_ENABLED:
            enabled_channels = [c for c in enabled_channels if c != "email"]
        if not settings.customer_send.CUSTOMER_SEND_WECHAT_ENABLED:
            enabled_channels = [c for c in enabled_channels if c != "wechat"]
        if not settings.customer_send.CUSTOMER_SEND_FEISHU_ENABLED:
            enabled_channels = [c for c in enabled_channels if c != "feishu"]

        result = BatchSendResult(
            task_id=params.task_id,
            status="ok",
            started_at=started_at_iso,
            finished_at=started_at_iso,
        )
        behaviors: list[SendBehaviorLog] = []

        targets = params.targets or []
        total = len(targets) * max(1, len(enabled_channels))
        result.total = total

        if not targets:
            logger.info(f"[{params.task_id}] 无 targets，结束")
            result.finished_at = datetime.utcnow().isoformat() + "Z"
            self.storage.upsert_job(result)
            return result

        if not enabled_channels:
            logger.warning(f"[{params.task_id}] 所有渠道都未启用")
            result.status = "failed"
            result.finished_at = datetime.utcnow().isoformat() + "Z"
            self.storage.upsert_job(result)
            return result

        h5 = H5Landing()
        tpl_name = params.template_name or "default"
        batch_size = max(1, int(params.batch_size or settings.customer_send.CUSTOMER_SEND_BATCH_SIZE_DEFAULT))

        t0 = time.time()

        for target in targets:
            # 1) 生成 H5
            h5_url = ""
            page_id = ""
            if params.enable_h5:
                spec = H5PageSpec(
                    page_id="",  # 稍后由 h5.page_id_for 生成
                    tenant_id=target.tenant_id,
                    opportunity_id=target.opportunity_id,
                    customer_name_masked=(target.customer_name or "")[:4] + "***",
                    industry=target.contact_industry,
                    region=target.contact_region,
                    keywords=list(target.need_keywords or []),
                    title=target.opportunity_title or f"商机 {target.opportunity_id}",
                    summary=(
                        f"客户：{target.customer_name[:8] or ''}｜行业：{target.contact_industry or '-'}｜地区：{target.contact_region or '-'}"
                    ),
                )
                page_id = h5.page_id_for(spec)
                spec.page_id = page_id
                h5_url = h5.short_url(page_id)

            variables = build_variables(target, h5_url=h5_url)

            for channel in enabled_channels:
                # 2) 渲染模板
                rendered = render(channel, tpl_name, variables)
                recipient = _CHANNEL_MAP[channel]().build_recipient(target)

                # dry_run 模式：仅做模板渲染，不触发任何网络
                if params.dry_run:
                    details = SingleSendResult(
                        send_id=_send_id(params.task_id, channel, target.opportunity_id),
                        channel=channel,
                        opportunity_id=target.opportunity_id,
                        success=True, status="DRY_RUN_OK",
                        masked_recipient=variables.get("customer_name", "")[:16],
                        h5_page_url=h5_url or None, cost_ms=0, attempts=0,
                    )
                    result.details.append(details)
                    result.success += 1
                    behaviors.append(
                        SendBehaviorLog(
                            behavior_id=details.send_id,
                            tenant_id=target.tenant_id,
                            opportunity_id=target.opportunity_id,
                            channel=channel,
                            event="dry_run_sent",
                            recipient_masked=details.masked_recipient,
                            h5_page_id=page_id or None,
                        )
                    )
                    continue

                extra: dict[str, Any] = {
                    "opportunity_id": target.opportunity_id,
                    "tenant_id": target.tenant_id,
                    "h5_url": h5_url,
                    "channel": channel,
                }
                # email 渠道自动提供 subject
                if channel == "email":
                    extra["subject"] = (
                        f"[{settings.customer_send.CUSTOMER_SEND_VERSION}] "
                        f"{target.opportunity_title or '商机推荐'}"
                    )

                start_ms = int(time.time() * 1000)
                ok, status, reason, attempts, masked = self._send_via_core(
                    channel=channel,
                    recipient=recipient,
                    content=rendered,
                    opportunity_id=target.opportunity_id,
                    target=target,
                    task_id=params.task_id,
                    extra=extra,
                )
                cost_ms = max(0, int(time.time() * 1000) - start_ms)

                sid = _send_id(params.task_id, channel, target.opportunity_id)
                detail = SingleSendResult(
                    send_id=sid,
                    channel=channel,
                    opportunity_id=target.opportunity_id,
                    success=ok,
                    status=status,
                    reason=reason,
                    masked_recipient=masked or variables.get("customer_name", "")[:20],
                    attempts=attempts,
                    h5_page_url=h5_url or None,
                    cost_ms=cost_ms,
                )
                result.details.append(detail)

                if status == "CONTENT_BLOCKED":
                    result.blocked += 1
                    behaviors.append(
                        SendBehaviorLog(
                            behavior_id=f"{sid}_blocked",
                            tenant_id=target.tenant_id,
                            opportunity_id=target.opportunity_id,
                            channel=channel,
                            event="blocked",
                            recipient_masked=detail.masked_recipient,
                        )
                    )
                elif status == "RATE_LIMITED":
                    result.rate_limited += 1
                    behaviors.append(
                        SendBehaviorLog(
                            behavior_id=f"{sid}_rate",
                            tenant_id=target.tenant_id,
                            opportunity_id=target.opportunity_id,
                            channel=channel,
                            event="rate_limited",
                            recipient_masked=detail.masked_recipient,
                        )
                    )
                elif ok or status == "SUCCESS":
                    result.success += 1
                    behaviors.append(
                        SendBehaviorLog(
                            behavior_id=sid,
                            tenant_id=target.tenant_id,
                            opportunity_id=target.opportunity_id,
                            channel=channel,
                            event="sent",
                            recipient_masked=detail.masked_recipient,
                            h5_page_id=page_id or None,
                        )
                    )
                else:
                    result.failed += 1
                    behaviors.append(
                        SendBehaviorLog(
                            behavior_id=f"{sid}_failed",
                            tenant_id=target.tenant_id,
                            opportunity_id=target.opportunity_id,
                            channel=channel,
                            event="failed",
                            recipient_masked=detail.masked_recipient,
                        )
                    )

        # 整体状态判定
        if result.blocked == 0 and result.failed == 0:
            result.status = "ok"
        elif result.success == 0:
            result.status = "failed"
        else:
            result.status = "partial"

        # 告警阈值
        total_done = result.success + result.failed + result.blocked + result.rate_limited or 1
        if result.blocked / total_done > settings.customer_send.CUSTOMER_SEND_BLOCKED_ALERT_RATIO:
            self._emit_alert("blocked_ratio", result)
        if result.failed / total_done > settings.customer_send.CUSTOMER_SEND_FAILED_ALERT_RATIO:
            self._emit_alert("failed_ratio", result)

        result.finished_at = datetime.utcnow().isoformat() + "Z"

        # 持久化
        try:
            self.storage.upsert_job(result)
            self.storage.record_behaviors(behaviors)
        except Exception as exc:
            logger.warning(f"upsert 失败（不影响返回）: {exc}")

        logger.info(
            f"[{params.task_id}] 完成 ok={result.success} failed={result.failed} "
            f"blocked={result.blocked} rate_limited={result.rate_limited} "
            f"elapsed_ms={int((time.time()-t0)*1000)}"
        )
        return result

    def _emit_alert(self, alert_key: str, result: BatchSendResult) -> None:
        try:
            from infra.alerting import alert_service
            if alert_service is None:
                return
            if hasattr(alert_service, "service_exception_sync"):
                message = (
                    f"[customer_send:{alert_key}] task={result.task_id} "
                    f"status={result.status} ok={result.success} failed={result.failed} "
                    f"blocked={result.blocked} rate_limited={result.rate_limited}"
                )
                alert_service.service_exception_sync(
                    service_name="customer_send", message=message,
                    extra={"alert_key": alert_key, "task_id": result.task_id},
                )
        except Exception as exc:
            logger.warning(f"告警推送失败: {exc}")


class _MockAccount:
    """fallback 时使用的最小账号对象。"""

    def __init__(self, token: str):
        self.account_id = "fallback"
        self.token = token
        self.channel = "fallback"
        self.daily_quota = 999999


def _send_id(task_id: str, channel: str, opportunity_id: str) -> str:
    key = f"{task_id}__{channel}__{opportunity_id}"
    return f"snd_{hashlib.md5(key.encode('utf-8')).hexdigest()[:12]}"


__all__ = ["CustomerSendPipeline"]
