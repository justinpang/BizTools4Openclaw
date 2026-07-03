"""web_admin/api/dashboard — 数据看板数据汇总。"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException

from infra.logger_setup import get_logger
from infra.redis_client import get_redis
from web_admin.auth import require_admin

logger = get_logger("web_admin.dashboard")
router = APIRouter(tags=["admin"])


def _safe_count(key_pattern: str) -> int:
    try:
        r = get_redis()
        if r is None:
            return 0
        keys = r.keys(key_pattern) if hasattr(r, "keys") else []
        return len(keys) if isinstance(keys, list) else 0
    except Exception:
        return 0


def _list_from_redis(key: str, limit: int = 20) -> list[dict]:
    try:
        r = get_redis()
        if r is None:
            return []
        raws = r.lrange(key, 0, limit - 1) or []
        import json as _json
        out = []
        for raw in raws:
            try:
                s = raw.decode("utf-8") if isinstance(raw, bytes) else str(raw)
                out.append(_json.loads(s))
            except Exception:
                continue
        return out
    except Exception:
        return []


@router.get("/dashboard/stats")
def dashboard_stats(session: dict = Depends(require_admin)):
    try:
        # 爬虫任务数（调度器任务）
        spider_tasks = 0
        try:
            from infra.task_scheduler import TaskScheduler
            jobs = TaskScheduler().list_jobs()
            spider_tasks = len(jobs) if jobs else 0
        except Exception:
            spider_tasks = _safe_count("spider:task:*")

        # 抓取记录数
        crawled = _safe_count("spider:crawled:*") or 0

        # 商机线索数
        try:
            from business.data_clean.storage import query_leads  # type: ignore
            leads_data = query_leads(limit=1) or {}
            leads_total = int(getattr(leads_data, "total", 0) if hasattr(leads_data, "total")
                              else (leads_data.get("total") if isinstance(leads_data, dict) else 0))
        except Exception:
            leads_total = _safe_count("leads:*")

        # 触达批次 & 账号数
        try:
            from business.customer_send.registry import list_runs  # type: ignore
            runs = list_runs() or []
            send_total = len(runs) if isinstance(runs, list) else 0
        except Exception:
            send_total = _safe_count("send:run:*")

        try:
            from core.send_core.account_pool import _build_default  # type: ignore
            pool = _build_default()
            channels = pool.channels() or []
            account_total = sum(len(pool.all_accounts(c) or []) for c in channels)
        except Exception:
            account_total = _safe_count("web_admin:accounts:*")

        # 销售漏斗
        try:
            from business.sales_task.registry import get_funnel_stats  # type: ignore
            funnel = get_funnel_stats(period_days=7)
            if isinstance(funnel, dict):
                funnel_data = funnel
            elif hasattr(funnel, "model_dump"):
                funnel_data = funnel.model_dump()
            else:
                funnel_data = {"raw": str(funnel)[:200]}
        except Exception as exc:
            logger.info(f"funnel fallback: {exc}")
            funnel_data = {"status": "n/a", "detail": "无漏斗数据"}

        return {
            "code": 0,
            "msg": "ok",
            "data": {
                "spider_tasks": spider_tasks,
                "crawled_total": crawled,
                "leads_total": leads_total,
                "send_total": send_total,
                "accounts_total": account_total,
                "funnel": funnel_data,
                "recent_tasks": _list_from_redis("web_admin:recent_tasks", 8),
            },
        }
    except Exception as exc:
        logger.error(f"dashboard stats: {exc}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(exc))


__all__ = ["router"]
