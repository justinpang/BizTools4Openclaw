from __future__ import annotations

import asyncio
import base64
import hashlib
import hmac
import smtplib
import time
import urllib.parse
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from enum import Enum
from typing import Any

from infra.logger_setup import get_logger
from configs.settings import settings

logger = get_logger(__name__)


class AlertType(str, Enum):
    """三类告警场景。"""

    TASK_FAILURE = "task_failure"
    SERVICE_EXCEPTION = "service_exception"
    CRAWLER_RISK = "crawler_risk"


class ChannelName(str, Enum):
    DINGTALK = "dingtalk"
    EMAIL = "email"


# ---------- 钉钉通道 ----------

def _dingtalk_sign(secret: str) -> tuple[str, str]:
    """按钉钉官方签名算法生成 sign。

    返回 (timestamp, sign)
    """
    timestamp = str(round(time.time() * 1000))
    string_to_sign = f"{timestamp}\n{secret}"
    hmac_code = hmac.new(
        secret.encode("utf-8"),
        string_to_sign.encode("utf-8"),
        digestmod=hashlib.sha256,
    ).digest()
    sign = urllib.parse.quote_plus(base64.b64encode(hmac_code))
    return timestamp, sign


def _build_dingtalk_payload(title: str, content: str) -> dict[str, Any]:
    return {
        "msgtype": "markdown",
        "markdown": {
            "title": title[:32],
            "text": f"## {title}\n\n{content}",
        },
    }


async def _send_dingtalk_async(title: str, content: str) -> bool:
    webhook = settings.alert.DINGTALK_WEBHOOK_URL
    if not webhook:
        return False

    url = webhook
    secret = settings.alert.DINGTALK_SECRET
    if secret:
        try:
            ts, sign = _dingtalk_sign(secret)
            sep = "&" if "?" in url else "?"
            url = f"{url}{sep}timestamp={ts}&sign={sign}"
        except Exception as exc:  # pragma: no cover - 告警失败不应打断主流程
            logger.error(f"[alert] dingtalk sign failed: {exc}")
            return False

    # 延迟导入 httpx，避免在不需要告警时强制依赖
    try:
        import httpx  # type: ignore
    except Exception as exc:  # pragma: no cover
        logger.error(f"[alert] httpx is not available: {exc}")
        return False

    payload = _build_dingtalk_payload(title, content)
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            resp = await client.post(url, json=payload)
            resp_json = resp.json()
            if resp_json.get("errcode") == 0:
                logger.info(f"[alert] dingtalk sent: {title}")
                return True
            logger.warning(f"[alert] dingtalk failed: {resp_json}")
            return False
    except Exception as exc:
        logger.error(f"[alert] dingtalk exception: {exc}")
        return False


# ---------- 邮件通道 ----------

def _split_recipients(raw: str) -> list[str]:
    if not raw:
        return []
    return [r.strip() for r in raw.split(",") if r.strip()]


def _send_email_sync(title: str, content: str) -> bool:
    s = settings.alert
    if not (s.SMTP_HOST and s.SMTP_USER and s.SMTP_PASSWORD and s.SMTP_FROM):
        return False
    recipients = _split_recipients(s.SMTP_TO)
    if not recipients:
        return False

    msg = MIMEMultipart("alternative")
    msg["Subject"] = title
    msg["From"] = s.SMTP_FROM
    msg["To"] = ", ".join(recipients)

    plain = MIMEText(content, "plain", "utf-8")
    html_body = f"<html><body><h3>{title}</h3><pre>{content}</pre></body></html>"
    html = MIMEText(html_body, "html", "utf-8")
    msg.attach(plain)
    msg.attach(html)

    try:
        if s.SMTP_USE_SSL:
            with smtplib.SMTP_SSL(s.SMTP_HOST, int(s.SMTP_PORT), timeout=10) as server:
                server.login(s.SMTP_USER, s.SMTP_PASSWORD)
                server.sendmail(s.SMTP_FROM, recipients, msg.as_string())
        else:
            with smtplib.SMTP(s.SMTP_HOST, int(s.SMTP_PORT), timeout=10) as server:
                server.starttls()
                server.login(s.SMTP_USER, s.SMTP_PASSWORD)
                server.sendmail(s.SMTP_FROM, recipients, msg.as_string())
        logger.info(f"[alert] email sent: {title} -> {recipients}")
        return True
    except Exception as exc:
        logger.error(f"[alert] email exception: {exc}")
        return False


# ---------- 主服务 ----------

def _truncate(text: str, max_bytes: int) -> str:
    if text is None:
        return ""
    encoded = text.encode("utf-8")
    if len(encoded) <= max_bytes:
        return text
    # 以字节截断后再解码（避免中途截断多字节字符）
    safe = encoded[:max_bytes].decode("utf-8", "ignore")
    return f"{safe}\n... [truncated]"


def _is_alert_type_enabled(alert_type: AlertType) -> bool:
    mapping = {
        AlertType.TASK_FAILURE: settings.alert.ALERT_TASK_FAILURE_ENABLED,
        AlertType.SERVICE_EXCEPTION: settings.alert.ALERT_SERVICE_EXCEPTION_ENABLED,
        AlertType.CRAWLER_RISK: settings.alert.ALERT_CRAWLER_RISK_ENABLED,
    }
    return bool(mapping.get(alert_type, True))


class AlertService:
    """告警统一入口（模块级单例）。"""

    _instance: "AlertService | None" = None

    def __new__(cls) -> "AlertService":
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    @property
    def enabled(self) -> bool:
        return bool(settings.alert.ALERT_ENABLED)

    # ---- 通道可用性探测 ----
    def _has_dingtalk(self) -> bool:
        return bool(settings.alert.DINGTALK_WEBHOOK_URL)

    def _has_email(self) -> bool:
        s = settings.alert
        return bool(s.SMTP_HOST and s.SMTP_USER and s.SMTP_PASSWORD and s.SMTP_FROM and _split_recipients(s.SMTP_TO))

    def _resolve_channels(self, channels: list[str] | None) -> list[str]:
        if channels:
            allowed = {ChannelName.DINGTALK.value, ChannelName.EMAIL.value}
            return [c for c in channels if c in allowed]
        result: list[str] = []
        if self._has_dingtalk():
            result.append(ChannelName.DINGTALK.value)
        if self._has_email():
            result.append(ChannelName.EMAIL.value)
        return result

    # ---- 对外 API ----
    async def send_async(
        self,
        alert_type: AlertType,
        title: str,
        content: str,
        *,
        channels: list[str] | None = None,
    ) -> None:
        if not self.enabled:
            logger.debug(f"[alert] disabled, skip: {alert_type}")
            return
        if not _is_alert_type_enabled(alert_type):
            return

        prefixed_title = f"{settings.alert.ALERT_ENV_PREFIX}[{alert_type.value}] {title}"
        body = _truncate(content, int(settings.alert.ALERT_MAX_BYTES))
        resolved = self._resolve_channels(channels)
        if not resolved:
            logger.warning(f"[alert] no channel available for {alert_type}")
            return

        tasks: list[asyncio.Task[bool]] = []
        loop = asyncio.get_event_loop()
        for ch in resolved:
            if ch == ChannelName.DINGTALK.value:
                tasks.append(loop.create_task(_send_dingtalk_async(prefixed_title, body)))
            elif ch == ChannelName.EMAIL.value:
                tasks.append(loop.create_task(loop.run_in_executor(None, _send_email_sync, prefixed_title, body)))

        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)

    def send_sync(
        self,
        alert_type: AlertType,
        title: str,
        content: str,
        *,
        channels: list[str] | None = None,
    ) -> None:
        try:
            asyncio.run(self.send_async(alert_type, title, content, channels=channels))
        except Exception as exc:  # pragma: no cover - 告警失败不能影响主流程
            logger.error(f"[alert] send_sync failed: {exc}")

    # ---- 场景化便捷 API ----
    async def task_failure_async(self, title: str, content: str = "") -> None:
        await self.send_async(AlertType.TASK_FAILURE, title, content)

    async def service_exception_async(self, title: str, content: str = "") -> None:
        await self.send_async(AlertType.SERVICE_EXCEPTION, title, content)

    async def crawler_risk_async(self, title: str, content: str = "") -> None:
        await self.send_async(AlertType.CRAWLER_RISK, title, content)

    def task_failure(self, title: str, content: str = "") -> None:
        self.send_sync(AlertType.TASK_FAILURE, title, content)

    def service_exception(self, title: str, content: str = "") -> None:
        self.send_sync(AlertType.SERVICE_EXCEPTION, title, content)

    def crawler_risk(self, title: str, content: str = "") -> None:
        self.send_sync(AlertType.CRAWLER_RISK, title, content)


# 模块级单例，全局使用
alert_service = AlertService()

__all__ = [
    "AlertType",
    "ChannelName",
    "AlertService",
    "alert_service",
]
