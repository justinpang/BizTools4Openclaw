"""adapter/tools_router — 工具列表 / 工具详情 / 同步执行 / 异步执行。"""

from __future__ import annotations

import json
import uuid

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Request, status

from adapter.auth import check_agent_quota, check_ip_whitelist, require_token
from adapter.middleware import TRACE_ID, TOOL_NAME
from adapter.models import ApiResponse, ToolExecuteRequest, ToolDefinition
from adapter.response import error, ok
from adapter.schema_adapter import mask_output, normalize_request_params
from adapter.task_router import sync_tool_worker
from adapter.tool_registry import TOOL_REGISTRY, execute_tool, get_tool, list_tools
from infra.logger_setup import get_logger

logger = get_logger("openclaw.tools")

router = APIRouter(prefix="/api/v1/tools", tags=["tools"])


@router.get("", response_model=ApiResponse)
async def tools_list(
    _=Depends(require_token),
    _ip=Depends(check_ip_whitelist),
    _q=Depends(check_agent_quota),
):
    """返回所有已注册工具的 OpenClaw Skill JSON。"""
    defs: list[dict] = [t.model_dump() for t in list_tools()]
    return ok({"tools": defs, "count": len(defs)}, trace_id=TRACE_ID.get())


@router.get("/{tool_name}", response_model=ApiResponse)
async def tool_detail(
    tool_name: str,
    _=Depends(require_token),
    _ip=Depends(check_ip_whitelist),
    _q=Depends(check_agent_quota),
):
    """返回单个工具定义。"""
    td = get_tool(tool_name)
    if td is None:
        raise HTTPException(status_code=404, detail=f"unknown tool: {tool_name}")
    return ok(td.model_dump(), trace_id=TRACE_ID.get())


@router.post("/{tool_name}/execute", response_model=ApiResponse)
async def tool_execute(
    tool_name: str,
    body: ToolExecuteRequest,
    background: BackgroundTasks,
    _=Depends(require_token),
    _ip=Depends(check_ip_whitelist),
    _q=Depends(check_agent_quota),
):
    """执行工具：async_mode=true 入队返回task_id；false 同步阻塞返回结果。"""
    if tool_name not in TOOL_REGISTRY:
        raise HTTPException(status_code=404, detail=f"unknown tool: {tool_name}")

    TOOL_NAME.set(tool_name)
    params = normalize_request_params(body.params, tool_name=tool_name)

    if body.async_mode:
        tid = "oc_" + uuid.uuid4().hex[:12]
        try:
            from infra.task_queue import enqueue as _enqueue
            _enqueue(
                "adapter.tool_execute",
                kwargs={
                    "tool_name": tool_name,
                    "params": params,
                    "trace_id": TRACE_ID.get() or tid,
                    "agent_id": body.agent_id,
                    "webhook_url": body.webhook_url,
                },
                task_id=tid,
                source="openclaw",
            )
        except Exception as exc:
            logger.error(f"enqueue failed: {exc}", exc_info=True)
            return error(500, f"入队失败: {exc}", trace_id=TRACE_ID.get() or tid)

        return ok(
            {
                "tool_name": tool_name,
                "status": "PENDING",
                "message": "异步任务已入队，通过 GET /api/v1/tasks/{task_id} 查询状态",
            },
            trace_id=TRACE_ID.get() or tid,
            task_id=tid,
        )

    # 同步执行
    try:
        raw_result = execute_tool(tool_name, params)
        masked = mask_output(raw_result)
        return ok(masked, trace_id=TRACE_ID.get())
    except Exception as exc:
        logger.error(f"tool {tool_name} failed: {exc}", exc_info=True)
        return error(500, f"工具执行失败: {exc}", trace_id=TRACE_ID.get())


__all__ = ["router", "tools_list", "tool_detail", "tool_execute"]
