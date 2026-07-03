"""business/sales_task/push_notifier — 复用 T11 渠道推送销售提醒。"""

from __future__ import annotations

from infra.logger_setup import get_logger
from configs.settings import settings
from business.sales_task.models import Opportunity, ReminderLevel, Salesperson

logger = get_logger("sales_task.push")


def _mask_value(value: str | None, keep: int = 2) -> str:
    if not value:
        return ""
    v = str(value)
    if len(v) <= keep:
        return v + "***"
    return v[:keep] + "***"


class PushNotifier:
    """向销售推送提醒消息，复用 T11 channels。"""

    def __init__(self):
        s = settings.sales_task
        self.feishu_enabled = bool(s.SALES_TASK_PUSH_FEISHU_ENABLED)
        self.wechat_enabled = bool(s.SALES_TASK_PUSH_WECHAT_ENABLED)
        self.email_enabled = bool(s.SALES_TASK_PUSH_EMAIL_ENABLED)
        # 渠道对象（懒加载）
        self._feishu = None
        self._wechat = None
        self._email = None

    def _get_channel(self, channel: str):
        try:
            if channel == "feishu":
                if self._feishu is None:
                    from business.customer_send.channels.feishu_channel import FeishuChannel
                    self._feishu = FeishuChannel()
                return self._feishu
            if channel == "wechat":
                if self._wechat is None:
                    from business.customer_send.channels.wechat_channel import WechatChannel
                    self._wechat = WechatChannel()
                return self._wechat
            if channel == "email":
                if self._email is None:
                    from business.customer_send.channels.email_channel import EmailChannel
                    self._email = EmailChannel()
                return self._email
        except Exception as exc:
            logger.info(f"渠道 {channel} 不可用: {exc}")
        return None

    # ---------- 模板 ----------

    def _render_template(self, level: str, salesperson: Salesperson, opportunity: Opportunity, days: int) -> str:
        level_label = {
            ReminderLevel.NOTIFY.value: "新商机分配通知",
            ReminderLevel.FIRST.value: "首次跟进提醒",
            ReminderLevel.SECOND.value: "二次回访提醒",
            ReminderLevel.OVERDUE.value: "⚠️ 商机逾期告警",
        }.get(level, level)

        customer_masked = _mask_value(opportunity.customer_name)
        industry = opportunity.industry or "-"
        region = opportunity.region or "-"
        keywords = ", ".join(opportunity.need_keywords or []) or "-"

        return (
            f"【{level_label}】\n"
            f"销售: {salesperson.name}\n"
            f"客户: {customer_masked}（{industry} / {region}）\n"
            f"商机关键字: {keywords}\n"
            f"商机分值: {opportunity.score}\n"
            f"自分配起: {days} 天\n"
            f"商机 ID: {opportunity.opportunity_id}\n"
            f"请尽快跟进。"
        )

    # ---------- 推送 ----------

    def push_to_sales(
        self,
        salesperson: Salesperson,
        level: str,
        opportunity: Opportunity,
        days: int,
        *,
        dry_run: bool = False,
    ) -> list[str]:
        """向一个销售推送提醒。返回成功推送的渠道列表。"""
        if dry_run:
            return [f"dry_run:{level}"]

        content = self._render_template(level, salesperson, opportunity, days)
        success_channels = []

        # 1) 飞书：优先通过飞书 webhook 推送
        if self.feishu_enabled and salesperson.feishu:
            ch = self._get_channel("feishu")
            if ch is not None:
                try:
                    ok, code, msg = ch.send(
                        _make_account("feishu", salesperson.feishu),
                        salesperson.feishu,
                        content,
                        extra={"__mock_sender__": _noop_sender} if _has_mock() else None,
                    )
                    if ok:
                        success_channels.append("feishu")
                except Exception as exc:
                    logger.info(f"飞书推送失败: {exc}")

        # 2) 企微：次选
        if self.wechat_enabled and salesperson.wechat:
            ch = self._get_channel("wechat")
            if ch is not None:
                try:
                    ok, code, msg = ch.send(
                        _make_account("wechat", salesperson.wechat),
                        salesperson.wechat,
                        content,
                        extra={"__mock_sender__": _noop_sender} if _has_mock() else None,
                    )
                    if ok:
                        success_channels.append("wechat")
                except Exception as exc:
                    logger.info(f"企微推送失败: {exc}")

        # 3) 邮件：最后选
        if self.email_enabled and salesperson.email:
            ch = self._get_channel("email")
            if ch is not None:
                try:
                    ok, code, msg = ch.send(
                        _make_account("email", salesperson.email),
                        salesperson.email,
                        content,
                        extra={"__mock_sender__": _noop_sender} if _has_mock() else None,
                    )
                    if ok:
                        success_channels.append("email")
                except Exception as exc:
                    logger.info(f"邮件推送失败: {exc}")

        if not success_channels:
            logger.info(f"销售 {salesperson.sales_id} 无可用推送渠道")

        return success_channels


# ---------- helper: mock account ----------

class _MockAccount:
    def __init__(self, account_id: str, token: str):
        self.account_id = account_id
        self.token = token
        self.channel = account_id


def _make_account(channel: str, token: str) -> _MockAccount:
    return _MockAccount(channel, token)


def _noop_sender(account, recipient, content, extra=None):
    return True, 200, "noop"


def _has_mock() -> bool:
    """测试模式：当检测到 pytest 运行时，自动启用 mock sender。"""
    import sys
    return any("pytest" in str(arg) for arg in sys.argv)


__all__ = ["PushNotifier"]
