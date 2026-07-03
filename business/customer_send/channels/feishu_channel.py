"""business/customer_send/channels/feishu_channel — 飞书机器人/交互式卡片。"""

from __future__ import annotations

import json
from typing import Any

from infra.logger_setup import get_logger

logger = get_logger("customer_send.feishu")


class FeishuChannel:
    """飞书机器人消息适配器。"""

    name = "feishu"

    def build_recipient(self, target: Any) -> str:
        # 飞书 webhook 无 recipient 概念，这里用 opportunity_id 作为唯一标识
        return getattr(target, "opportunity_id", str(getattr(target, "id", "")))

    def build_content(self, target: Any, rendered_template: str) -> str:
        return rendered_template or ""

    def send(
        self,
        account: Any,
        recipient: str,
        content: str,
        extra: dict[str, Any] | None = None,
    ) -> tuple[bool, int | None, str]:
        extra = extra or {}

        if callable(extra.get("__mock_sender__")):
            try:
                return extra["__mock_sender__"](account, recipient, content, extra)
            except Exception as exc:
                return False, None, f"mock_sender_error: {exc}"

        if extra.get("__dry_run__"):
            return True, 200, "dry_run_ok"

        webhook_url = getattr(account, "token", "") or ""
        if not webhook_url or not webhook_url.startswith("http"):
            return False, 400, "feishu: invalid webhook url"

        try:
            payload = json.loads(content) if content.strip().startswith("{") else {
                "msg_type": "text",
                "content": {"text": content[:3000]},
            }
        except Exception:
            payload = {"msg_type": "text", "content": {"text": content[:3000]}}

        try:
            import requests
            resp = requests.post(
                webhook_url,
                data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
                headers={"Content-Type": "application/json; charset=UTF-8"},
                timeout=15,
            )
            if 200 <= resp.status_code < 300:
                try:
                    data = resp.json()
                except Exception:
                    data = {}
                if isinstance(data, dict) and data.get("code", -1) == 0:
                    return True, resp.status_code, "ok"
                return False, resp.status_code, f"feishu_api: {data.get('msg', resp.text[:200])}"
            return False, resp.status_code, f"http_{resp.status_code}"
        except Exception as exc:
            return False, None, f"{type(exc).__name__}: {str(exc)[:200]}"


__all__ = ["FeishuChannel"]
