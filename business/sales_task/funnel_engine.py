"""business/sales_task/funnel_engine — 商机转化漏斗统计。"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from infra.logger_setup import get_logger
from configs.settings import settings
from business.sales_task.models import FunnelStats, _now_iso

logger = get_logger("sales_task.funnel")


def _safe_div(a: int, b: int) -> float:
    if b <= 0:
        return 0.0
    return round(float(a) / float(b), 4)


class FunnelEngine:
    """转化漏斗统计引擎（采集 → 清洗 → 触达 → 跟进 → 成交）。"""

    def __init__(self, storage=None):
        self.storage = storage
        self.period_days = int(settings.sales_task.SALES_TASK_FUNNEL_PERIOD_DAYS or 7)

    def _period_range(self, *, days: int | None = None,
                       custom_start: str | None = None,
                       custom_end: str | None = None):
        if custom_start and custom_end:
            try:
                s = datetime.fromisoformat(custom_start.replace("Z", "+00:00"))
                e = datetime.fromisoformat(custom_end.replace("Z", "+00:00"))
                if s.tzinfo is None:
                    s = s.replace(tzinfo=timezone.utc)
                if e.tzinfo is None:
                    e = e.replace(tzinfo=timezone.utc)
                return s, e
            except Exception as exc:
                logger.info(f"自定义周期解析失败，回退到默认 {days or self.period_days} 天: {exc}")

        d = days or self.period_days
        now = datetime.now(timezone.utc)
        start = now - timedelta(days=d)
        return start, now

    # ---------- 从各模块取数 ----------

    def _get_collected(self, tenant_id: str, start: datetime, end: datetime) -> int:
        """采集量：从 data_clean 或原始爬虫取。"""
        try:
            from infra.db_base import database
            if hasattr(database, "session_scope"):
                try:
                    with database.session_scope() as session:
                        q = session.execute(
                            "SELECT COUNT(*) FROM cleaned_opportunity "
                            "WHERE tenant_id = ? AND created_at >= ? AND created_at <= ?",
                            (tenant_id, start.isoformat(), end.isoformat()),
                        )
                        row = q.fetchone() if hasattr(q, "fetchone") else None
                        if row is not None:
                            return int(row[0] or 0)
                except Exception:
                    pass
            if hasattr(database, "raw_query"):
                try:
                    r = database.raw_query(
                        "SELECT COUNT(*) FROM cleaned_opportunity "
                        "WHERE tenant_id = ? AND created_at >= ? AND created_at <= ?",
                        (tenant_id, start.isoformat(), end.isoformat()),
                    )
                    if r and hasattr(r, "__iter__"):
                        row = list(r)[0] if len(list(r)) > 0 else None
                        if row is not None:
                            return int(row[0] or 0)
                except Exception:
                    pass
        except Exception:
            pass
        return 0

    def _get_cleaned(self, tenant_id: str, start: datetime, end: datetime) -> int:
        """有效清洗线索（score >= 30 的）。"""
        try:
            from infra.db_base import database
            if hasattr(database, "session_scope"):
                try:
                    with database.session_scope() as session:
                        q = session.execute(
                            "SELECT COUNT(*) FROM cleaned_opportunity "
                            "WHERE tenant_id = ? AND created_at >= ? AND created_at <= ? AND (score IS NULL OR score >= 30)",
                            (tenant_id, start.isoformat(), end.isoformat()),
                        )
                        row = q.fetchone() if hasattr(q, "fetchone") else None
                        if row is not None:
                            return int(row[0] or 0)
                except Exception:
                    pass
        except Exception:
            pass
        return 0

    def _get_reached(self, tenant_id: str, start: datetime, end: datetime) -> int:
        """已触达客户数。"""
        try:
            from infra.db_base import database
            if hasattr(database, "session_scope"):
                try:
                    with database.session_scope() as session:
                        q = session.execute(
                            "SELECT COUNT(DISTINCT opportunity_id) FROM customer_send_behavior "
                            "WHERE tenant_id = ? AND event IN ('sent','opened','clicked') "
                            "AND created_at >= ? AND created_at <= ?",
                            (tenant_id, start.isoformat(), end.isoformat()),
                        )
                        row = q.fetchone() if hasattr(q, "fetchone") else None
                        if row is not None:
                            return int(row[0] or 0)
                except Exception:
                    pass
        except Exception:
            pass
        return 0

    def _get_followed(self, tenant_id: str, start: datetime, end: datetime) -> int:
        """销售跟进数（有 follow_up_record 的商机数）。"""
        try:
            from infra.db_base import database
            if hasattr(database, "session_scope"):
                try:
                    with database.session_scope() as session:
                        q = session.execute(
                            "SELECT COUNT(DISTINCT opportunity_id) FROM follow_up_record "
                            "WHERE tenant_id = ? AND created_at >= ? AND created_at <= ?",
                            (tenant_id, start.isoformat(), end.isoformat()),
                        )
                        row = q.fetchone() if hasattr(q, "fetchone") else None
                        if row is not None:
                            return int(row[0] or 0)
                except Exception:
                    pass
        except Exception:
            pass
        return 0

    def _get_closed_won(self, tenant_id: str, start: datetime, end: datetime) -> int:
        """成交数。"""
        try:
            from infra.db_base import database
            if hasattr(database, "session_scope"):
                try:
                    with database.session_scope() as session:
                        q = session.execute(
                            "SELECT COUNT(*) FROM opportunity "
                            "WHERE tenant_id = ? AND status = 'CLOSED_WON' "
                            "AND updated_at >= ? AND updated_at <= ?",
                            (tenant_id, start.isoformat(), end.isoformat()),
                        )
                        row = q.fetchone() if hasattr(q, "fetchone") else None
                        if row is not None:
                            return int(row[0] or 0)
                except Exception:
                    pass
        except Exception:
            pass
        return 0

    # ---------- 主入口 ----------

    def compute_funnel(
        self,
        tenant_id: str,
        *,
        period_days: int | None = None,
        period_start: str | None = None,
        period_end: str | None = None,
        opportunity_count_hint: int | None = None,
        cleaned_hint: int | None = None,
        reached_hint: int | None = None,
        followed_hint: int | None = None,
        closed_won_hint: int | None = None,
    ) -> FunnelStats:
        """计算转化漏斗。

        当数据库不可用时，使用 hint 值作为回退。
        """
        start, end = self._period_range(days=period_days, custom_start=period_start, custom_end=period_end)

        collected = self._get_collected(tenant_id, start, end)
        if collected == 0 and opportunity_count_hint:
            collected = int(opportunity_count_hint)

        cleaned = self._get_cleaned(tenant_id, start, end)
        if cleaned == 0 and cleaned_hint:
            cleaned = int(cleaned_hint)

        reached = self._get_reached(tenant_id, start, end)
        if reached == 0 and reached_hint:
            reached = int(reached_hint)

        followed = self._get_followed(tenant_id, start, end)
        if followed == 0 and followed_hint:
            followed = int(followed_hint)

        closed_won = self._get_closed_won(tenant_id, start, end)
        if closed_won == 0 and closed_won_hint:
            closed_won = int(closed_won_hint)

        rates = {
            "cleaned_rate": _safe_div(cleaned, collected),
            "reached_rate": _safe_div(reached, cleaned),
            "followed_rate": _safe_div(followed, reached),
            "won_rate": _safe_div(closed_won, followed),
            "end_to_end": _safe_div(closed_won, collected),
        }

        stats = FunnelStats(
            tenant_id=tenant_id,
            period_start=start.strftime("%Y-%m-%dT%H:%M:%SZ"),
            period_end=end.strftime("%Y-%m-%dT%H:%M:%SZ"),
            collected=collected,
            cleaned=cleaned,
            reached=reached,
            followed=followed,
            closed_won=closed_won,
            conversion_rates=rates,
        )

        logger.info(
            f"funnel[{tenant_id}] collected={collected} cleaned={cleaned} "
            f"reached={reached} followed={followed} closed_won={closed_won} "
            f"e2e={rates['end_to_end']:.2%}"
        )
        return stats


__all__ = ["FunnelEngine"]
