"""business/customer_send/channels/email_channel — SMTP 邮件发送。"""

from __future__ import annotations

import smtplib
import json
import base64
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.mime.base import MIMEBase
from email import encoders
from typing import Any

from infra.logger_setup import get_logger
from configs.settings import settings

logger = get_logger("customer_send.email")


class EmailChannel:
    """邮件发送适配器；仅发送，不处理限流/账号池。

    使用方式：
        ch = EmailChannel()
        ok, code, msg = ch.send(account=Account, recipient="x@y.com",
                                 content="<html>...</html>",
                                 extra={"subject": "标题", "attachments": [...]})
    """

    name = "email"

    def build_recipient(self, target: Any) -> str:
        email = getattr(target, "contact_email", None) or ""
        return email.strip()

    def build_content(self, target: Any, rendered_template: str) -> str:
        return rendered_template or ""

    def _resolve_smtp(self, account_token: str) -> dict:
        """解析 account.token；若为 'smtp_fallback' 或 JSON 失败，则走全局配置。"""
        token = (account_token or "").strip()

        # 全局回退
        fallback = {
            "host": settings.customer_send.CUSTOMER_SEND_SMTP_HOST,
            "port": int(settings.customer_send.CUSTOMER_SEND_SMTP_PORT),
            "user": settings.customer_send.CUSTOMER_SEND_SMTP_USER,
            "password": settings.customer_send.CUSTOMER_SEND_SMTP_PASSWORD,
            "use_ssl": bool(settings.customer_send.CUSTOMER_SEND_SMTP_USE_SSL),
            "from_addr": settings.customer_send.CUSTOMER_SEND_SMTP_FROM,
        }
        if not token or token == "smtp_fallback":
            return fallback
        # token 可能是 JSON
        if token.startswith("{"):
            try:
                parsed = json.loads(token)
                merged = dict(fallback)
                for k in ("host", "port", "user", "password", "use_ssl", "from_addr"):
                    if k in parsed and parsed[k] not in (None, ""):
                        merged[k] = parsed[k] if k != "port" else int(parsed[k])
                return merged
            except Exception:
                return fallback
        # "user:password@host:port" 形式
        if "@" in token and ":" in token:
            try:
                left, host_part = token.rsplit("@", 1)
                user, pwd = left.split(":", 1)
                host = host_part
                port = 465
                if ":" in host:
                    host, port_str = host.rsplit(":", 1)
                    port = int(port_str)
                merged = dict(fallback)
                merged["host"] = host
                merged["port"] = int(port)
                merged["user"] = user
                merged["password"] = pwd
                return merged
            except Exception:
                return fallback
        return fallback

    def send(
        self,
        account: Any,
        recipient: str,
        content: str,
        extra: dict[str, Any] | None = None,
    ) -> tuple[bool, int | None, str]:
        extra = extra or {}

        # 测试注入：如果提供了 __mock_sender__，直接返回其结果
        if callable(extra.get("__mock_sender__")):
            try:
                return extra["__mock_sender__"](account, recipient, content, extra)
            except Exception as exc:
                return False, None, f"mock_sender_error: {exc}"

        if extra.get("__dry_run__"):
            return True, 200, "dry_run_ok"

        if not recipient or "@" not in recipient:
            return False, 400, f"invalid_recipient: {recipient[:40]}"

        smtp_cfg = self._resolve_smtp(getattr(account, "token", "") or "")
        if not smtp_cfg.get("host"):
            return False, None, "smtp_host_not_configured"

        subject = str(extra.get("subject") or (
            "[{}] 商机推荐".format(settings.customer_send.CUSTOMER_SEND_VERSION)
        ))
        from_addr = str(smtp_cfg.get("from_addr") or smtp_cfg.get("user") or "no-reply@openclaw.local")

        try:
            msg = MIMEMultipart("alternative")
            msg["Subject"] = subject
            msg["From"] = from_addr
            msg["To"] = recipient

            # HTML 正文
            is_html = bool(("<html" in (content or "").lower()) or ("<div" in (content or "").lower()))
            body_type = "html" if is_html else "plain"
            msg.attach(MIMEText(content or "", body_type, "utf-8"))

            # 附件（可选）
            for item in extra.get("attachments", []) or []:
                try:
                    filename = str(item.get("filename", "attachment"))
                    content_b64 = str(item.get("content_b64", ""))
                    if not content_b64:
                        continue
                    part = MIMEBase("application", "octet-stream")
                    part.set_payload(base64.b64decode(content_b64))
                    encoders.encode_base64(part)
                    part.add_header("Content-Disposition", f'attachment; filename="{filename}"')
                    msg.attach(part)
                except Exception:
                    continue

            if smtp_cfg.get("use_ssl"):
                server = smtplib.SMTP_SSL(smtp_cfg["host"], int(smtp_cfg["port"]), timeout=20)
            else:
                server = smtplib.SMTP(smtp_cfg["host"], int(smtp_cfg["port"]), timeout=20)
                server.starttls()

            if smtp_cfg.get("user") and smtp_cfg.get("password"):
                server.login(str(smtp_cfg["user"]), str(smtp_cfg["password"]))
            server.sendmail(from_addr, [recipient], msg.as_string())
            server.quit()
            return True, 200, "ok"
        except smtplib.SMTPRecipientsRefused:
            return False, 550, "bounced: recipient_refused"
        except smtplib.SMTPAuthenticationError:
            return False, 535, "auth_failed"
        except Exception as exc:
            return False, None, f"{type(exc).__name__}: {str(exc)[:200]}"


__all__ = ["EmailChannel"]
