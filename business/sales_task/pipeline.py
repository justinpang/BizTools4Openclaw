"""business/sales_task/pipeline — 总调度流水线。"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from infra.logger_setup import get_logger
from configs.settings import settings
from business.sales_task.assignment_engine import AssignmentEngine
from business.sales_task.funnel_engine import FunnelEngine
from business.sales_task.models import (
    FunnelStats,
    Opportunity,
    OpportunityStatus,
    ReminderParams,
    SalesTaskJobResult,
    _now_iso,
)
from business.sales_task.push_notifier import PushNotifier
from business.sales_task.reminder_engine import ReminderEngine
from business.sales_task.status_engine import StatusEngine
from business.sales_task.storage import SendStorage

logger = get_logger("sales_task.pipeline")


class SalesTaskPipeline:
    """综合调度：自动分配 + 多级提醒 + 逾期告警 + 漏斗统计。"""

    def __init__(self, storage: SendStorage | None = None):
        self.storage = storage or SendStorage(ensure_schema=True)
        self.assignment = AssignmentEngine(storage=self.storage)
        self.reminder = ReminderEngine(storage=self.storage)
        self.status = StatusEngine(storage=self.storage)
        self.funnel = FunnelEngine(storage=self.storage)
        self.push = PushNotifier()
        self.long_unassigned_threshold_days = int(
            settings.sales_task.SALES_TASK_LONG_UNASSIGNED_THRESHOLD_DAYS or 7
        )

    # ---------- 自动分配 ----------

    def run_assignment(
        self,
        opportunities: list[Opportunity],
        salespersons: list,
        *,
        task_id: str | None = None,
        dry_run: bool = False,
    ) -> SalesTaskJobResult:
        tenant_id = opportunities[0].tenant_id if opportunities else ""
        result = SalesTaskJobResult(
            task_id=task_id or f"assign_{tenant_id}_{_now_iso()}",
            tenant_id=tenant_id,
            job_type="ASSIGN",
        )
        result.processed = len([o for o in opportunities if o.status == OpportunityStatus.NEW.value])

        res = self.assignment.assign_batch(opportunities, salespersons, dry_run=dry_run)
        result.assigned = res["assigned"]
        reason_parts = []
        if res["no_match_reasons"]:
            reason_parts.append("; ".join(res["no_match_reasons"][:3]))
        if result.processed > 0 and result.assigned < result.processed:
            reason_parts.append(
                f"未分配 {result.processed - result.assigned}/{result.processed} 商机"
            )
        result.reason = "; ".join(reason_parts) or None

        if dry_run:
            result.status = "OK"
            result.finished_at = _now_iso()
            result.detail = {
                "assignments": res["assignments"][:50],
                "dry_run": True,
            }
            return result

        # 落库：商机更新 + 操作日志
        if not dry_run:
            self.storage.upsert_opportunity_batch(opportunities)
            self.storage.append_operation_log_batch(res["operation_logs"])
            # 批量推送 NOTIFY 提醒
            self._push_assign_notifications(opportunities, salespersons,
                                            assignments=res["assignments"])

        # 长期未分配扫描
        result.long_unassigned = self._scan_long_unassigned(opportunities)

        result.status = "OK"
        result.finished_at = _now_iso()
        result.detail = {
            "unassigned_reasons": res["no_match_reasons"][:10],
            "assignments_count": len(res["assignments"]),
            "long_unassigned_count": result.long_unassigned,
        }
        self.storage.upsert_job(result)
        return result

    def _push_assign_notifications(
        self,
        opportunities: list[Opportunity],
        salespersons: list,
        *,
        assignments: list[tuple],
    ) -> int:
        pushed = 0
        sales_map = {s.sales_id: s for s in salespersons}
        opp_map = {o.opportunity_id: o for o in opportunities}
        for opp_id, sales_id, _score in assignments:
            sp = sales_map.get(sales_id)
            opp = opp_map.get(opp_id)
            if sp is None or opp is None:
                continue
            try:
                self.push.push_to_sales(sp, "NOTIFY", opp, 0)
                pushed += 1
            except Exception as exc:
                logger.info(f"推送 NOTIFY 失败: {exc}")
        return pushed

    def _scan_long_unassigned(self, opportunities: list[Opportunity]) -> int:
        """扫描超过阈值但仍未分配的商机，触发告警。"""
        now = datetime.now(timezone.utc)
        count = 0
        for opp in opportunities:
            if opp.status != OpportunityStatus.NEW.value:
                continue
            try:
                created = datetime.fromisoformat(str(opp.created_at).replace("Z", "+00:00"))
                if created.tzinfo is None:
                    created = created.replace(tzinfo=timezone.utc)
                if (now - created).days >= self.long_unassigned_threshold_days:
                    count += 1
            except Exception:
                continue
        if count > 0:
            try:
                from infra.alerting import alert_service
                if hasattr(alert_service, "service_exception_sync"):
                    alert_service.service_exception_sync(
                        service_name="sales_task",
                        message=(
                            f"[sales_task:long_unassigned] {count} 个商机超过 "
                            f"{self.long_unassigned_threshold_days} 天未分配"
                        ),
                    )
            except Exception:
                pass
        return count

    # ---------- 多级提醒 ----------

    def run_reminder(
        self,
        opportunities: list[Opportunity],
        salespersons: list,
        *,
        task_id: str | None = None,
        custom_cycles: dict[str, int] | None = None,
        dry_run: bool = False,
        already_fired_map: dict[str, set[str]] | None = None,
    ) -> SalesTaskJobResult:
        tenant_id = opportunities[0].tenant_id if opportunities else ""
        result = SalesTaskJobResult(
            task_id=task_id or f"remind_{tenant_id}_{_now_iso()}",
            tenant_id=tenant_id,
            job_type="REMIND",
        )
        self.reminder.apply_custom_cycles(custom_cycles)

        res = self.reminder.scan_and_remind(
            opportunities, already_fired_map=already_fired_map, dry_run=dry_run
        )
        result.reminded = res["reminded"]
        result.overdue_count = res["overdue_count"]
        result.processed = len([
            o for o in opportunities
            if o.status not in ("NEW", "CLOSED_WON", "LOST")
        ])

        # 推送提醒
        sales_map = {s.sales_id: s for s in salespersons}
        opp_map = {o.opportunity_id: o for o in opportunities}
        push_logs = []
        for opp_id, sales_id, level, days in res["details"]:
            sp = sales_map.get(sales_id)
            opp = opp_map.get(opp_id)
            if sp is None or opp is None:
                continue
            try:
                self.push.push_to_sales(sp, level, opp, days, dry_run=dry_run)
            except Exception as exc:
                logger.info(f"推送提醒失败: {exc}")

        if not dry_run:
            self.storage.append_operation_log_batch(res["operation_logs"])

        result.status = "OK"
        result.finished_at = _now_iso()
        result.detail = {
            "reminder_details": [(opp_id, lvl, d) for (opp_id, _s, lvl, d) in res["details"][:30]],
            "cycles": dict(self.reminder.cycles),
        }
        self.storage.upsert_job(result)
        return result

    # ---------- 漏斗统计 ----------

    def run_funnel(
        self,
        tenant_id: str,
        *,
        task_id: str | None = None,
        period_days: int | None = None,
        opportunity_count_hint: int | None = None,
        cleaned_hint: int | None = None,
        reached_hint: int | None = None,
        followed_hint: int | None = None,
        closed_won_hint: int | None = None,
    ) -> tuple[SalesTaskJobResult, FunnelStats]:
        result = SalesTaskJobResult(
            task_id=task_id or f"funnel_{tenant_id}_{_now_iso()}",
            tenant_id=tenant_id,
            job_type="FUNNEL",
        )
        stats = self.funnel.compute_funnel(
            tenant_id,
            period_days=period_days,
            opportunity_count_hint=opportunity_count_hint,
            cleaned_hint=cleaned_hint,
            reached_hint=reached_hint,
            followed_hint=followed_hint,
            closed_won_hint=closed_won_hint,
        )
        result.processed = stats.collected
        result.reminded = stats.followed
        result.assigned = stats.cleaned
        result.overdue_count = stats.closed_won
        result.status = "OK"
        result.finished_at = _now_iso()
        result.detail = stats.conversion_rates
        self.storage.upsert_funnel(stats)
        self.storage.upsert_job(result)
        return result, stats

    # ---------- 综合 run_batch ----------

    def run_batch(
        self,
        opportunities: list[Opportunity],
        salespersons: list,
        *,
        task_id: str | None = None,
        dry_run: bool = False,
        enable_funnel: bool = True,
        custom_cycles: dict[str, int] | None = None,
    ) -> dict:
        """综合执行：分配 → 提醒 → 漏斗统计。"""
        results = {}
        # 1. 自动分配
        results["assignment"] = self.run_assignment(
            opportunities, salespersons,
            task_id=task_id, dry_run=dry_run,
        )
        # 2. 多级提醒（对 ASSIGNED/FOLLOWING/COMMUNICATING 的商机）
        results["reminder"] = self.run_reminder(
            opportunities, salespersons,
            task_id=task_id, custom_cycles=custom_cycles, dry_run=dry_run,
        )
        # 3. 漏斗统计
        if enable_funnel:
            results["funnel_job"], results["funnel_stats"] = self.run_funnel(
                (opportunities[0].tenant_id if opportunities else ""),
                opportunity_count_hint=len(opportunities),
            )
        return results


__all__ = ["SalesTaskPipeline"]
