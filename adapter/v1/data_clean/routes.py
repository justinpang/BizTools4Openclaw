"""adapter/v1/data_clean/routes — 数据清洗服务 HTTP 端点。"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Body, Query

from adapter.response import error, ok
from infra.logger_setup import get_logger

logger = get_logger("v1.data_clean")

router = APIRouter(prefix="/v1/data-clean", tags=["data-clean"])


@router.post("/run")
async def run_cleaning(
    params: dict[str, Any] = Body(default_factory=dict, description="清洗参数，包含 raw_records"),
):
    """执行数据清洗任务。"""
    try:
        from business.data_clean.registry import run_cleaning as _run
        raw = params.pop("raw_records", None)
        result = _run(params, raw_records=raw)
        return ok({"result": result, "tenant_id": params.get("tenant_id", "")})
    except Exception as exc:
        logger.warning(f"run_cleaning failed: {exc}")
        return error(500, f"清洗执行失败: {exc}")


@router.get("/runs")
async def list_runs(
    tenant_id: str | None = Query(default=None, description="租户 ID（可选）"),
    page_no: int = Query(default=1, description="页码"),
    page_size: int = Query(default=20, description="每页数量"),
):
    """（预留）列出清洗记录。"""
    try:
        from business.data_clean.registry import list_runs as _list
        items = _list()
        start = (page_no - 1) * page_size
        return ok({"items": items[start:start + page_size], "total": len(items)})
    except Exception as exc:
        return error(500, f"列表查询失败: {exc}")


__all__ = ["router"]
