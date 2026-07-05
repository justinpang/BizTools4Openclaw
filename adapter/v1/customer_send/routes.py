"""adapter/v1/customer_send/routes — 客户触达服务 HTTP 端点。"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Body, Query

from adapter.response import error, ok
from infra.logger_setup import get_logger

logger = get_logger("v1.customer_send")

router = APIRouter(prefix="/v1/customer-send", tags=["customer-send"])


@router.post("/run")
async def run_batch(
    params: dict[str, Any] = Body(default_factory=dict, description="触达任务参数"),
):
    """同步执行一批客户触达。"""
    try:
        from business.customer_send.registry import run_batch as _run
        result = _run(params)
        return ok({"result": getattr(result, "model_dump", lambda: result)()})
    except Exception as exc:
        logger.warning(f"run_batch failed: {exc}")
        return error(500, f"触达执行失败: {exc}")


@router.post("/run/async")
async def run_async(
    params: dict[str, Any] = Body(default_factory=dict, description="触达任务参数"),
):
    """投递到异步队列，返回 task_id。"""
    try:
        from business.customer_send.registry import async_run as _async
        task_id = _async(params)
        return ok({"task_id": task_id, "status": "QUEUED"})
    except Exception as exc:
        logger.warning(f"async_run failed: {exc}")
        return error(500, f"异步投递失败: {exc}")


@router.get("/runs")
async def list_runs(
    tenant_id: str | None = Query(default=None, description="租户 ID（可选）"),
    page_no: int = Query(default=1, description="页码"),
    page_size: int = Query(default=20, description="每页数量"),
):
    """列出触达任务记录（预留）。"""
    try:
        from business.customer_send.registry import list_runs as _list
        items = _list(tenant_id)
        start = (page_no - 1) * page_size
        return ok({"items": items[start:start + page_size], "total": len(items)})
    except Exception as exc:
        return error(500, f"列表查询失败: {exc}")


__all__ = ["router"]
