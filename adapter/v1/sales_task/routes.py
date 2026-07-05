"""adapter/v1/sales_task/routes — 销售任务调度 HTTP 端点。"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Body, Query

from adapter.response import error, ok
from infra.logger_setup import get_logger

logger = get_logger("v1.sales_task")

router = APIRouter(prefix="/v1/sales-task", tags=["sales-task"])


@router.post("/run")
async def run_batch(
    opportunities: list[dict[str, Any]] = Body(default_factory=list, description="商机列表"),
    salespersons: list[dict[str, Any]] = Body(default_factory=list, description="销售员列表"),
    task_id: str | None = Body(default=None, description="任务 ID"),
    dry_run: bool = Body(default=False, description="是否仅模拟不落地"),
    enable_funnel: bool = Body(default=True, description="是否执行漏斗统计"),
):
    """综合调度：自动分配 + 多级提醒 + 漏斗统计。"""
    try:
        from business.sales_task.registry import run_batch as _run
        from business.sales_task.models import Opportunity, Salesperson

        ops = [Opportunity(**o) for o in (opportunities or [])]
        sps = [Salesperson(**s) for s in (salespersons or [])]
        result = _run(ops, sps, task_id=task_id, dry_run=dry_run, enable_funnel=enable_funnel)
        return ok({"result": result})
    except Exception as exc:
        logger.warning(f"run_batch failed: {exc}")
        return error(500, f"调度执行失败: {exc}")


@router.post("/run/async")
async def run_async(
    opportunities: list[dict[str, Any]] = Body(default_factory=list, description="商机列表"),
    salespersons: list[dict[str, Any]] = Body(default_factory=list, description="销售员列表"),
    task_id: str | None = Body(default=None, description="任务 ID"),
):
    """投递到异步队列。"""
    try:
        from business.sales_task.registry import async_run as _async
        from business.sales_task.models import Opportunity, Salesperson

        ops = [Opportunity(**o) for o in (opportunities or [])]
        sps = [Salesperson(**s) for s in (salespersons or [])]
        result_task_id = _async(ops, sps, task_id=task_id)
        return ok({"task_id": result_task_id, "status": "QUEUED"})
    except Exception as exc:
        logger.warning(f"async_run failed: {exc}")
        return error(500, f"异步投递失败: {exc}")


@router.post("/assign")
async def assign_endpoint(
    opportunities: list[dict[str, Any]] = Body(default_factory=list),
    salespersons: list[dict[str, Any]] = Body(default_factory=list),
    task_id: str | None = Body(default=None),
    dry_run: bool = Body(default=False),
):
    """仅执行自动分配。"""
    try:
        from business.sales_task.registry import assign as _assign
        from business.sales_task.models import Opportunity, Salesperson

        ops = [Opportunity(**o) for o in (opportunities or [])]
        sps = [Salesperson(**s) for s in (salespersons or [])]
        result = _assign(ops, sps, task_id=task_id, dry_run=dry_run)
        return ok({"result": result})
    except Exception as exc:
        return error(500, f"分配失败: {exc}")


@router.post("/remind")
async def remind_endpoint(
    opportunities: list[dict[str, Any]] = Body(default_factory=list),
    salespersons: list[dict[str, Any]] = Body(default_factory=list),
    task_id: str | None = Body(default=None),
    dry_run: bool = Body(default=False),
    custom_cycles: dict[str, int] | None = Body(default=None),
):
    """多级提醒扫描。"""
    try:
        from business.sales_task.registry import remind as _remind
        from business.sales_task.models import Opportunity, Salesperson

        ops = [Opportunity(**o) for o in (opportunities or [])]
        sps = [Salesperson(**s) for s in (salespersons or [])]
        result = _remind(ops, sps, task_id=task_id, dry_run=dry_run, custom_cycles=custom_cycles)
        return ok({"result": result})
    except Exception as exc:
        return error(500, f"提醒扫描失败: {exc}")


@router.get("/funnel")
async def funnel_stats(
    tenant_id: str = Query(default="", description="租户 ID"),
    period_days: int | None = Query(default=None, description="统计周期（天）"),
):
    """获取漏斗统计。"""
    try:
        from business.sales_task.registry import get_funnel_stats as _funnel
        result, stats = _funnel(tenant_id, period_days=period_days)
        return ok({"result": result, "stats": stats})
    except Exception as exc:
        return error(500, f"漏斗统计失败: {exc}")


@router.get("/runs")
async def list_runs_endpoint(
    tenant_id: str | None = Query(default=None, description="租户 ID（可选）"),
    page_no: int = Query(default=1, description="页码"),
    page_size: int = Query(default=20, description="每页数量"),
):
    """（预留）列出销售任务记录。"""
    try:
        # list_runs 在 registry 中目前未定义，返回空列表
        items: list[str] = []
        start = (page_no - 1) * page_size
        return ok({"items": items[start:start + page_size], "total": len(items)})
    except Exception as exc:
        return error(500, f"列表查询失败: {exc}")


__all__ = ["router"]
