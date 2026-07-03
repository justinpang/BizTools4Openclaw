"""business/sales_task/registry — 公开单例入口。"""

from __future__ import annotations

from business.sales_task.models import (
    Opportunity,
    OpportunityStatus,
    SalesTaskJobResult,
)
from business.sales_task.pipeline import SalesTaskPipeline

_pipeline = SalesTaskPipeline()


def run_batch(
    opportunities: list[Opportunity],
    salespersons: list,
    *,
    task_id: str | None = None,
    dry_run: bool = False,
    enable_funnel: bool = True,
    custom_cycles: dict[str, int] | None = None,
) -> dict:
    """综合执行：自动分配 + 多级提醒 + 漏斗统计。"""
    return _pipeline.run_batch(
        opportunities, salespersons,
        task_id=task_id, dry_run=dry_run,
        enable_funnel=enable_funnel,
        custom_cycles=custom_cycles,
    )


def assign(
    opportunities: list[Opportunity],
    salespersons: list,
    *,
    task_id: str | None = None,
    dry_run: bool = False,
) -> SalesTaskJobResult:
    """仅执行自动分配。"""
    return _pipeline.run_assignment(
        opportunities, salespersons, task_id=task_id, dry_run=dry_run
    )


def remind(
    opportunities: list[Opportunity],
    salespersons: list,
    *,
    task_id: str | None = None,
    custom_cycles: dict[str, int] | None = None,
    dry_run: bool = False,
) -> SalesTaskJobResult:
    """仅执行多级提醒扫描。"""
    return _pipeline.run_reminder(
        opportunities, salespersons,
        task_id=task_id, custom_cycles=custom_cycles, dry_run=dry_run,
    )


def get_funnel_stats(
    tenant_id: str,
    *,
    period_days: int | None = None,
    **hints,
) -> tuple[SalesTaskJobResult, object]:
    """仅获取漏斗统计。"""
    return _pipeline.run_funnel(tenant_id, period_days=period_days, **hints)


def transition(
    opportunity: Opportunity,
    target_status: str,
    operator_sales_id: str,
    detail: str | None = None,
) -> tuple[bool, str | None]:
    """状态流转。"""
    ok, log, reason = _pipeline.status.transition(
        opportunity, target_status, operator_sales_id, detail
    )
    if log is not None:
        _pipeline.storage.append_operation_log(log)
        _pipeline.storage.upsert_opportunity(opportunity)
    return ok, reason


def add_tag(
    opportunity: Opportunity,
    tag: str,
    operator_sales_id: str,
) -> bool:
    """新增商机标签。"""
    log = _pipeline.status.add_tag(opportunity, tag, operator_sales_id)
    if log is not None:
        _pipeline.storage.append_operation_log(log)
        _pipeline.storage.upsert_opportunity(opportunity)
        return True
    return False


def remove_tag(
    opportunity: Opportunity,
    tag: str,
    operator_sales_id: str,
) -> bool:
    """删除商机标签。"""
    log = _pipeline.status.remove_tag(opportunity, tag, operator_sales_id)
    if log is not None:
        _pipeline.storage.append_operation_log(log)
        _pipeline.storage.upsert_opportunity(opportunity)
        return True
    return False


def record_follow_up(
    opportunity: Opportunity,
    sales_id: str,
    channel: str,
    content: str,
    next_follow_at: str | None = None,
) -> bool:
    """写入跟进记录。"""
    follow, log = _pipeline.status.record_follow_up(
        opportunity, sales_id, channel, content, next_follow_at
    )
    _pipeline.storage.upsert_follow_up(follow)
    _pipeline.storage.append_operation_log(log)
    _pipeline.storage.upsert_opportunity(opportunity)
    return True


def async_run(
    opportunities: list[Opportunity],
    salespersons: list,
    *,
    task_id: str | None = None,
) -> str:
    """投递到异步队列（若队列不可用则同步执行）。"""
    payload = {
        "tenant_id": opportunities[0].tenant_id if opportunities else "",
        "opportunity_count": len(opportunities),
        "sales_count": len(salespersons),
        "task_id": task_id or f"async_{hash(str(opportunities))}",
    }
    try:
        from infra.task_queue import task_queue as tq
        if tq is not None and hasattr(tq, "enqueue"):
            tq.enqueue("sales_task:run_batch", payload)
            return payload["task_id"]
    except Exception:
        pass
    # 回退：同步执行
    run_batch(opportunities, salespersons, task_id=payload["task_id"], dry_run=False)
    return payload["task_id"]


__all__ = [
    "run_batch",
    "async_run",
    "assign",
    "remind",
    "get_funnel_stats",
    "transition",
    "add_tag",
    "remove_tag",
    "record_follow_up",
]
