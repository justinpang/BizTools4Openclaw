"""business/sales_task/reminder_engine — 多级提醒引擎。"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from infra.logger_setup import get_logger
from configs.settings import settings
from business.sales_task.models import (
    Opportunity,
    ReminderLevel,
    SalesOperationLog,
    _make_id,
    _now_iso,
)

logger = get_logger("sales_task.reminder")


def _parse_to_dt(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        v = value.strip()
        if v.endswith("Z"):
            v = v[:-1] + "+00:00"
        return datetime.fromisoformat(v)
    except Exception:
        return None


class ReminderEngine:
    """多级定时提醒：NOTIFY / FIRST / SECOND / OVERDUE。"""

    def __init__(self, storage=None):
        self.storage = storage
        s = settings.sales_task
        self.cycles: dict[str, int] = {
            ReminderLevel.NOTIFY.value: int(s.SALES_TASK_REMIND_CYCLE_DAYS_NOTIFY),
            ReminderLevel.FIRST.value: int(s.SALES_TASK_REMIND_CYCLE_DAYS_FIRST),
            ReminderLevel.SECOND.value: int(s.SALES_TASK_REMIND_CYCLE_DAYS_SECOND),
            ReminderLevel.OVERDUE.value: int(s.SALES_TASK_REMIND_CYCLE_DAYS_OVERDUE),
        }
        self.overdue_alert_threshold = int(s.SALES_TASK_OVERDUE_ALERT_THRESHOLD)

    # ---------- 周期判断 ----------

    def apply_custom_cycles(self, custom: dict[str, int] | None) -> None:
        if not custom:
            return
        for k, v in custom.items():
            if k in self.cycles:
                self.cycles[k] = int(v)

    def compute_reminder_level(
        self,
        opportunity: Opportunity,
        *,
        now: datetime | None = None,
        already_fired: set[str] | None = None,
    ) -> str | None:
        """计算商机当前应触发的提醒级别。"""
        now = now or datetime.now(timezone.utc)
        already = already_fired or set()

        status = opportunity.status
        if status in ("CLOSED_WON", "LOST", "NEW"):
            return None

        base_dt = _parse_to_dt(opportunity.assigned_at)
        if base_dt is None:
            return None

        # 让 base_dt 带时区信息
        if base_dt.tzinfo is None:
            base_dt = base_dt.replace(tzinfo=timezone.utc)

        days_since_assign = (now - base_dt).days

        # OVERDUE: 超过阈值且仍在跟进状态
        if days_since_assign >= self.cycles[ReminderLevel.OVERDUE.value]:
            if ReminderLevel.OVERDUE.value not in already:
                return ReminderLevel.OVERDUE.value

        if days_since_assign >= self.cycles[ReminderLevel.SECOND.value]:
            if ReminderLevel.SECOND.value not in already:
                return ReminderLevel.SECOND.value

        if days_since_assign >= self.cycles[ReminderLevel.FIRST.value]:
            if ReminderLevel.FIRST.value not in already:
                return ReminderLevel.FIRST.value

        # NOTIFY 由分配引擎同步触发，不在这里重复
        return None

    # ---------- 批量扫描 ----------

    def scan_and_remind(
        self,
        opportunities: list[Opportunity],
        *,
        already_fired_map: dict[str, set[str]] | None = None,
        dry_run: bool = False,
    ) -> dict:
        """扫描并触发提醒。

        返回: {
            reminded: int,
            overdue_count: int,
            details: list[(opportunity_id, sales_id, level, days)],
            operation_logs: list[SalesOperationLog],
        }
        """
        result = {
            "reminded": 0,
            "overdue_count": 0,
            "details": [],
            "operation_logs": [],
        }

        if not opportunities:
            return result

        now = datetime.now(timezone.utc)

        for opp in opportunities:
            if opp.status in ("NEW", "CLOSED_WON", "LOST"):
                continue
            if not opp.assigned_sales_id:
                continue

            fired = (already_fired_map or {}).get(opp.opportunity_id, set())
            level = self.compute_reminder_level(opp, now=now, already_fired=fired)
            if level is None:
                continue

            base_dt = _parse_to_dt(opp.assigned_at)
            days = 0
            if base_dt is not None:
                if base_dt.tzinfo is None:
                    base_dt = base_dt.replace(tzinfo=timezone.utc)
                days = (now - base_dt).days

            result["reminded"] += 1
            if level == ReminderLevel.OVERDUE.value:
                result["overdue_count"] += 1

            result["details"].append((opp.opportunity_id, opp.assigned_sales_id, level, days))
            result["operation_logs"].append(
                SalesOperationLog(
                    log_id=_make_id("op", opp.tenant_id, opp.opportunity_id, f"REMIND_{level}"),
                    tenant_id=opp.tenant_id,
                    opportunity_id=opp.opportunity_id,
                    sales_id=opp.assigned_sales_id or "",
                    op_type=f"REMIND_{level}",
                    before_value=opp.status,
                    after_value=opp.status,
                    detail=f"自分配起 {days} 天未推进，触发 {level} 提醒",
                )
            )

        if result["overdue_count"] >= self.overdue_alert_threshold:
            try:
                from infra.alerting import alert_service
                if hasattr(alert_service, "service_exception_sync"):
                    alert_service.service_exception_sync(
                        service_name="sales_task",
                        message=(
                            f"[sales_task:overdue_alert] 大量商机逾期 "
                            f"overdue={result['overdue_count']} threshold={self.overdue_alert_threshold}"
                        ),
                    )
            except Exception as exc:
                logger.info(f"告警推送跳过: {exc}")

        return result


__all__ = ["ReminderEngine"]
