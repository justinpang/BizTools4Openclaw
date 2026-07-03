"""business/customer_send/storage — 批量 upsert 到结构化表。"""

from __future__ import annotations

import json
from datetime import datetime

from infra.logger_setup import get_logger
from configs.settings import settings

logger = get_logger("customer_send.storage")


def _parse_dt(value, default=None):
    if value is None:
        return default
    if isinstance(value, datetime):
        return value
    if isinstance(value, (int, float)):
        try:
            return datetime.fromtimestamp(float(value))
        except Exception:
            return None
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


class SendStorage:
    """持久化 BatchSendResult 与 SendBehaviorLog 写入数据库。"""

    def __init__(self, *, ensure_schema: bool = True):
        if ensure_schema:
            try:
                from business.customer_send._orm import ensure_tables
                ensure_tables()
            except Exception as exc:
                logger.info(f"ensure_tables 跳过: {exc}")

    # ----------- helpers -----------

    def _upsert_rows(self, rows, *, row_class):
        if not rows:
            return 0
        try:
            from infra.db_base import database  # type: ignore
            tn = getattr(row_class, "__tablename__", "")
            if "behavior" in str(tn).lower() or "behavior" in str(rows[0]).lower():
                conflict_cols = ["tenant_id", "behavior_id"]
            else:
                conflict_cols = ["tenant_id", "task_id"]
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
                    return len(rows)
            return len(rows)
        except Exception as exc:
            logger.warning(f"_upsert_rows 失败: {exc}")
            return len(rows)

    # ----------- jobs -----------

    def upsert_job(self, result):
        try:
            from business.customer_send._orm import CustomerSendJobRow
        except Exception:
            CustomerSendJobRow = None
        try:
            started = _parse_dt(getattr(result, "started_at", None))
            finished = _parse_dt(getattr(result, "finished_at", None))
            row = {
                "tenant_id": str(getattr(result, "tenant_id", "") or ""),
                "task_id": str(getattr(result, "task_id", "")),
                "channels": json.dumps(list(getattr(result, "channels", []) or []), ensure_ascii=False),
                "total": int(getattr(result, "total", 0) or 0),
                "success": int(getattr(result, "success", 0) or 0),
                "failed": int(getattr(result, "failed", 0) or 0),
                "blocked": int(getattr(result, "blocked", 0) or 0),
                "rate_limited": int(getattr(result, "rate_limited", 0) or 0),
                "status": str(getattr(result, "status", "PENDING") or "PENDING"),
                "caller": str(getattr(result, "caller", "") or "") or None,
                "started_at": started,
                "finished_at": finished,
            }
            return self._upsert_rows([row], row_class=CustomerSendJobRow)
        except Exception as exc:
            logger.warning(f"upsert_job 失败: {exc}")
            return 0

    # ----------- behaviors -----------

    def record_behaviors(self, behaviors):
        try:
            from business.customer_send._orm import CustomerSendBehaviorRow
        except Exception:
            CustomerSendBehaviorRow = None
        rows = []
        for b in behaviors:
            try:
                rows.append({
                    "behavior_id": str(getattr(b, "behavior_id", "")),
                    "tenant_id": str(getattr(b, "tenant_id", "")),
                    "opportunity_id": str(getattr(b, "opportunity_id", "")),
                    "channel": str(getattr(b, "channel", "")),
                    "event": str(getattr(b, "event", "")),
                    "recipient_masked": str(getattr(b, "recipient_masked", "") or "")[:256] or None,
                    "h5_page_id": str(getattr(b, "h5_page_id", "") or "") or None,
                    "http_path": str(getattr(b, "http_path", "") or "") or None,
                    "payload_snapshot": json.dumps(dict(getattr(b, "payload_snapshot", {}) or {}), ensure_ascii=False),
                    "remote_ip_masked": str(getattr(b, "remote_ip_masked", "") or "")[:64] or None,
                    "user_agent_hash": str(getattr(b, "user_agent_hash", "") or "")[:64] or None,
                    "created_at": _parse_dt(getattr(b, "created_at", None)),
                })
            except Exception as exc:
                logger.warning(f"behavior 行构建失败: {exc}")
                continue
        if not rows:
            return 0
        return self._upsert_rows(rows, row_class=CustomerSendBehaviorRow)


__all__ = ["SendStorage"]
