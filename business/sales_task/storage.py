"""business/sales_task/storage — 幂等 upsert 封装。"""

from __future__ import annotations

import json
from datetime import datetime, timezone

from infra.logger_setup import get_logger

logger = get_logger("sales_task.storage")


def _parse_dt(value, default=None):
    if value is None:
        return default
    if isinstance(value, datetime):
        return value
    try:
        if isinstance(value, str):
            v = value.strip()
            if not v:
                return None
            if v.endswith("Z"):
                v = v[:-1] + "+00:00"
            return datetime.fromisoformat(v)
    except Exception:
        pass
    try:
        return datetime.strptime(str(value)[:19], "%Y-%m-%dT%H:%M:%S")
    except Exception:
        return None


def _now_dt() -> datetime:
    return datetime.now(timezone.utc)


class SendStorage:
    """存储封装。"""

    def __init__(self, *, ensure_schema: bool = True):
        if ensure_schema:
            try:
                from business.sales_task._orm import ensure_tables
                ensure_tables()
            except Exception as exc:
                logger.info(f"ensure_tables 跳过: {exc}")

    # ---------- helpers ----------

    def _upsert_rows(self, rows, *, row_class, conflict_cols: list[str]):
        if not rows:
            return 0
        try:
            from infra.db_base import database
            if hasattr(database, "upsert"):
                try:
                    n = database.upsert(row_class, conflict_columns=conflict_cols, rows=rows)
                    if isinstance(n, int):
                        return n
                except Exception:
                    pass
            if hasattr(database, "bulk_insert"):
                try:
                    n = database.bulk_insert(row_class, rows)
                    if isinstance(n, int):
                        return n
                except Exception:
                    pass
            return len(rows)
        except Exception as exc:
            logger.warning(f"_upsert_rows 失败: {exc}")
            return len(rows)

    # ---------- salesperson ----------

    def upsert_salesperson(self, sales) -> int:
        try:
            from business.sales_task._orm import SalespersonRow
        except Exception:
            SalespersonRow = None
        try:
            d = {
                "tenant_id": str(sales.tenant_id),
                "sales_id": str(sales.sales_id),
                "name": str(sales.name),
                "industries": json.dumps(list(sales.industries or []), ensure_ascii=False),
                "regions": json.dumps(list(sales.regions or []), ensure_ascii=False),
                "min_score": int(sales.min_score or 0),
                "weight": float(sales.weight or 1.0),
                "current_load": int(sales.current_load or 0),
                "email": str(sales.email) if sales.email else None,
                "wechat": str(sales.wechat) if sales.wechat else None,
                "feishu": str(sales.feishu) if sales.feishu else None,
                "group": str(sales.group or "default"),
                "updated_at": _now_dt(),
            }
            return self._upsert_rows([d], row_class=SalespersonRow,
                                      conflict_cols=["tenant_id", "sales_id"])
        except Exception as exc:
            logger.warning(f"upsert_salesperson 失败: {exc}")
            return 0

    def upsert_salesperson_batch(self, sales_list) -> int:
        try:
            from business.sales_task._orm import SalespersonRow
        except Exception:
            SalespersonRow = None
        rows = []
        for s in sales_list:
            try:
                rows.append({
                    "tenant_id": str(s.tenant_id),
                    "sales_id": str(s.sales_id),
                    "name": str(s.name),
                    "industries": json.dumps(list(s.industries or []), ensure_ascii=False),
                    "regions": json.dumps(list(s.regions or []), ensure_ascii=False),
                    "min_score": int(s.min_score or 0),
                    "weight": float(s.weight or 1.0),
                    "current_load": int(s.current_load or 0),
                    "email": str(s.email) if s.email else None,
                    "wechat": str(s.wechat) if s.wechat else None,
                    "feishu": str(s.feishu) if s.feishu else None,
                    "group": str(s.group or "default"),
                    "updated_at": _now_dt(),
                })
            except Exception:
                continue
        return self._upsert_rows(rows, row_class=SalespersonRow,
                                 conflict_cols=["tenant_id", "sales_id"])

    # ---------- opportunity ----------

    def upsert_opportunity(self, opp) -> int:
        try:
            from business.sales_task._orm import OpportunityRow
        except Exception:
            OpportunityRow = None
        try:
            d = {
                "tenant_id": str(opp.tenant_id),
                "opportunity_id": str(opp.opportunity_id),
                "customer_name": str(opp.customer_name),
                "contact_email": str(opp.contact_email) if opp.contact_email else None,
                "contact_phone": str(opp.contact_phone) if opp.contact_phone else None,
                "industry": str(opp.industry) if opp.industry else None,
                "region": str(opp.region) if opp.region else None,
                "need_keywords": json.dumps(list(opp.need_keywords or []), ensure_ascii=False),
                "score": int(opp.score or 0),
                "status": str(opp.status or "NEW"),
                "assigned_sales_id": str(opp.assigned_sales_id) if opp.assigned_sales_id else None,
                "assigned_at": _parse_dt(opp.assigned_at),
                "last_follow_at": _parse_dt(opp.last_follow_at),
                "tags": json.dumps(list(opp.tags or []), ensure_ascii=False),
                "source_batch_id": str(opp.source_batch_id) if opp.source_batch_id else None,
                "updated_at": _now_dt(),
            }
            return self._upsert_rows([d], row_class=OpportunityRow,
                                      conflict_cols=["tenant_id", "opportunity_id"])
        except Exception as exc:
            logger.warning(f"upsert_opportunity 失败: {exc}")
            return 0

    def upsert_opportunity_batch(self, opps) -> int:
        try:
            from business.sales_task._orm import OpportunityRow
        except Exception:
            OpportunityRow = None
        rows = []
        for o in opps:
            try:
                rows.append({
                    "tenant_id": str(o.tenant_id),
                    "opportunity_id": str(o.opportunity_id),
                    "customer_name": str(o.customer_name),
                    "contact_email": str(o.contact_email) if o.contact_email else None,
                    "contact_phone": str(o.contact_phone) if o.contact_phone else None,
                    "industry": str(o.industry) if o.industry else None,
                    "region": str(o.region) if o.region else None,
                    "need_keywords": json.dumps(list(o.need_keywords or []), ensure_ascii=False),
                    "score": int(o.score or 0),
                    "status": str(o.status or "NEW"),
                    "assigned_sales_id": str(o.assigned_sales_id) if o.assigned_sales_id else None,
                    "assigned_at": _parse_dt(o.assigned_at),
                    "last_follow_at": _parse_dt(o.last_follow_at),
                    "tags": json.dumps(list(o.tags or []), ensure_ascii=False),
                    "source_batch_id": str(o.source_batch_id) if o.source_batch_id else None,
                    "updated_at": _now_dt(),
                })
            except Exception:
                continue
        return self._upsert_rows(rows, row_class=OpportunityRow,
                                 conflict_cols=["tenant_id", "opportunity_id"])

    # ---------- follow_up_record ----------

    def upsert_follow_up(self, rec) -> int:
        try:
            from business.sales_task._orm import FollowUpRecordRow
        except Exception:
            FollowUpRecordRow = None
        try:
            d = {
                "tenant_id": str(rec.tenant_id),
                "follow_id": str(rec.follow_id),
                "opportunity_id": str(rec.opportunity_id),
                "sales_id": str(rec.sales_id),
                "channel": str(rec.channel),
                "content": str(rec.content),
                "next_follow_at": _parse_dt(rec.next_follow_at),
            }
            return self._upsert_rows([d], row_class=FollowUpRecordRow,
                                      conflict_cols=["tenant_id", "follow_id"])
        except Exception as exc:
            logger.warning(f"upsert_follow_up 失败: {exc}")
            return 0

    # ---------- operation log ----------

    def append_operation_log(self, log) -> int:
        try:
            from business.sales_task._orm import SalesOperationLogRow
        except Exception:
            SalesOperationLogRow = None
        try:
            d = {
                "tenant_id": str(log.tenant_id),
                "log_id": str(log.log_id),
                "opportunity_id": str(log.opportunity_id),
                "sales_id": str(log.sales_id),
                "op_type": str(log.op_type),
                "before_value": str(log.before_value)[:256] if log.before_value else None,
                "after_value": str(log.after_value)[:256] if log.after_value else None,
                "detail": str(log.detail) if log.detail else None,
            }
            return self._upsert_rows([d], row_class=SalesOperationLogRow,
                                      conflict_cols=["tenant_id", "log_id"])
        except Exception as exc:
            logger.warning(f"append_operation_log 失败: {exc}")
            return 0

    def append_operation_log_batch(self, logs) -> int:
        try:
            from business.sales_task._orm import SalesOperationLogRow
        except Exception:
            SalesOperationLogRow = None
        rows = []
        for log in logs:
            try:
                rows.append({
                    "tenant_id": str(log.tenant_id),
                    "log_id": str(log.log_id),
                    "opportunity_id": str(log.opportunity_id),
                    "sales_id": str(log.sales_id),
                    "op_type": str(log.op_type),
                    "before_value": str(log.before_value)[:256] if log.before_value else None,
                    "after_value": str(log.after_value)[:256] if log.after_value else None,
                    "detail": str(log.detail) if log.detail else None,
                })
            except Exception:
                continue
        return self._upsert_rows(rows, row_class=SalesOperationLogRow,
                                  conflict_cols=["tenant_id", "log_id"])

    # ---------- job ----------

    def upsert_job(self, job) -> int:
        try:
            from business.sales_task._orm import SalesTaskJobRow
        except Exception:
            SalesTaskJobRow = None
        try:
            d = {
                "tenant_id": str(job.tenant_id),
                "task_id": str(job.task_id),
                "job_id": str(getattr(job, "job_id", "") or job.task_id + "_" + str(job.job_type)),
                "job_type": str(job.job_type),
                "processed": int(job.processed or 0),
                "assigned": int(job.assigned or 0),
                "reminded": int(job.reminded or 0),
                "overdue_count": int(job.overdue_count or 0),
                "long_unassigned": int(getattr(job, "long_unassigned", 0) or 0),
                "status": str(job.status or "OK"),
                "reason": str(job.reason)[:512] if job.reason else None,
                "detail": json.dumps(dict(job.detail or {}), ensure_ascii=False),
                "started_at": _parse_dt(job.started_at),
                "finished_at": _parse_dt(job.finished_at),
            }
            return self._upsert_rows([d], row_class=SalesTaskJobRow,
                                      conflict_cols=["tenant_id", "task_id", "job_type"])
        except Exception as exc:
            logger.warning(f"upsert_job 失败: {exc}")
            return 0

    # ---------- funnel ----------

    def upsert_funnel(self, stats) -> int:
        try:
            from business.sales_task._orm import FunnelStatsRow
        except Exception:
            FunnelStatsRow = None
        try:
            stats_id = f"funnel_{stats.tenant_id}_{stats.period_start}_{stats.period_end}"
            d = {
                "tenant_id": str(stats.tenant_id),
                "stats_id": stats_id,
                "period_start": _parse_dt(stats.period_start),
                "period_end": _parse_dt(stats.period_end),
                "collected": int(stats.collected or 0),
                "cleaned": int(stats.cleaned or 0),
                "reached": int(stats.reached or 0),
                "followed": int(stats.followed or 0),
                "closed_won": int(stats.closed_won or 0),
                "conversion_rates": json.dumps(dict(stats.conversion_rates or {}), ensure_ascii=False),
            }
            return self._upsert_rows([d], row_class=FunnelStatsRow,
                                      conflict_cols=["tenant_id", "stats_id"])
        except Exception as exc:
            logger.warning(f"upsert_funnel 失败: {exc}")
            return 0


__all__ = ["SendStorage"]
