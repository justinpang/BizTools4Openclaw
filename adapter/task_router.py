"""adapter/task_router — 任务入队 / 状态查询 / 取消 / 列表。"""

from __future__ import annotations

import uuid
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, status

from adapter.auth import require_token, check_agent_quota, check_ip_whitelist
from adapter.middleware import TRACE_ID, TOOL_NAME
from adapter.models import ApiResponse, TaskEnqueueRequest, WebhookPayload
from adapter.response import error, ok
from adapter.schema_adapter import format_task_result, mask_output, normalize_request_params
from adapter.tool_registry import TOOL_REGISTRY, execute_tool, get_tool
from infra.logger_setup import get_logger
from configs.settings import settings

logger = get_logger("openclaw.task")

router = APIRouter(prefix="/api/v1/tasks", tags=["tasks"])


@router.post("/enqueue", response_model=ApiResponse)
async def enqueue_task(
    body: TaskEnqueueRequest,
    _=Depends(require_token),
    _ip=Depends(check_ip_whitelist),
    _q=Depends(check_agent_quota),
):
    """将任务放入 Redis 队列，立即返回 task_id。"""
    tool_name = body.tool_name.strip()
    if tool_name not in TOOL_REGISTRY:
        raise HTTPException(status_code=404, detail=f"unknown tool: {tool_name}")

    tid = "oc_" + uuid.uuid4().hex[:12]
    TOOL_NAME.set(tool_name)

    try:
        from infra.task_queue import enqueue as _enqueue
        params = normalize_request_params(body.params, tool_name=tool_name)
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
        logger.info(f"task enqueued: {tid} tool={tool_name} agent={body.agent_id}")
    except Exception as exc:
        logger.error(f"enqueue failed: {exc}", exc_info=True)
        return error(500, f"入队失败: {exc}", trace_id=TRACE_ID.get() or tid)

    return ok(
        {
            "tool_name": tool_name,
            "status": "PENDING",
            "message": "任务已入队，请通过 GET /api/v1/tasks/{task_id} 查询状态",
        },
        trace_id=TRACE_ID.get() or tid,
        task_id=tid,
    )


@router.get("/{task_id}", response_model=ApiResponse)
async def get_task_status(
    task_id: str,
    _=Depends(require_token),
    _ip=Depends(check_ip_whitelist),
    _q=Depends(check_agent_quota),
):
    """查询任务状态。"""
    try:
        from infra.task_queue import get_status
        meta = get_status(task_id, source="openclaw")
    except Exception as exc:
        logger.info(f"get_status 失败: {exc}")
        return error(500, f"状态查询失败: {exc}", trace_id=TRACE_ID.get())

    if meta is None:
        raise HTTPException(status_code=404, detail=f"task {task_id} 不存在")

    result_val = getattr(meta, "result", None) if hasattr(meta, "result") else None
    error_val = getattr(meta, "error", None) if hasattr(meta, "error") else None
    formatted = format_task_result(meta, raw_result=result_val, error=error_val)
    masked = mask_output(formatted)
    return ok(masked, trace_id=TRACE_ID.get(), task_id=task_id)


@router.delete("/{task_id}", response_model=ApiResponse)
async def cancel_task(
    task_id: str,
    _=Depends(require_token),
    _ip=Depends(check_ip_whitelist),
    _q=Depends(check_agent_quota),
):
    """取消任务。"""
    try:
        from infra.task_queue import cancel as _cancel
        ok_flag = _cancel(task_id, source="openclaw")
    except Exception as exc:
        logger.info(f"cancel 失败: {exc}")
        return error(500, f"取消失败: {exc}", trace_id=TRACE_ID.get())

    if not ok_flag:
        raise HTTPException(status_code=404, detail=f"task {task_id} 不存在")

    return ok({"task_id": task_id, "cancelled": True}, trace_id=TRACE_ID.get())


@router.get("", response_model=ApiResponse)
async def list_tasks(
    limit: int = 100,
    _=Depends(require_token),
    _ip=Depends(check_ip_whitelist),
    _q=Depends(check_agent_quota),
):
    """列出最近 N 个任务。"""
    try:
        from infra.task_queue import list_tasks as _list
        items = _list(source="openclaw", limit=limit)
    except Exception as exc:
        return error(500, f"列表查询失败: {exc}", trace_id=TRACE_ID.get())

    formatted = []
    for m in items or []:
        try:
            formatted.append(format_task_result(m))
        except Exception:
            continue
    masked = mask_output(formatted)
    return ok({"total": len(masked), "items": masked}, trace_id=TRACE_ID.get())


@router.post("/{task_id}/webhook", response_model=ApiResponse)
async def manual_webhook(
    task_id: str,
    _=Depends(require_token),
    _ip=Depends(check_ip_whitelist),
    _q=Depends(check_agent_quota),
):
    """手动触发 webhook（调试用）。"""
    try:
        from infra.task_queue import get_status
        meta = get_status(task_id, source="openclaw")
        if meta is None:
            raise HTTPException(status_code=404, detail=f"task {task_id} 不存在")

        status_val = str(getattr(meta, "status", "UNKNOWN") or "UNKNOWN")
        if hasattr(meta, "status") and hasattr(meta.status, "value"):
            status_val = str(meta.status.value)
        result_val = getattr(meta, "result", None) if hasattr(meta, "result") else None

        url = settings.adapter.ADAPTER_DEFAULT_WEBHOOK_URL or ""
        if not url:
            return error(400, "未配置 ADAPTER_DEFAULT_WEBHOOK_URL", trace_id=TRACE_ID.get())

        payload = WebhookPayload(
            task_id=task_id,
            tool_name=str(getattr(meta, "name", "")),
            status=status_val,
            result_masked=mask_output(result_val),
            error=getattr(meta, "error", None) if hasattr(meta, "error") else None,
            trace_id=TRACE_ID.get(),
        )
        _send_webhook(url, payload.model_dump())
        return ok({"sent": True, "url": url}, trace_id=TRACE_ID.get(), task_id=task_id)
    except HTTPException:
        raise
    except Exception as exc:
        return error(500, f"webhook 发送失败: {exc}", trace_id=TRACE_ID.get())


def _send_webhook(url: str, payload: dict[str, Any]) -> None:
    import json
    import urllib.request as urllib_request
    timeout = float(settings.adapter.ADAPTER_WEBHOOK_TIMEOUT or 10)
    data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    req = urllib_request.Request(
        url,
        data=data,
        headers={"Content-Type": "application/json", "X-Trace-Id": payload.get("trace_id", "")},
        method="POST",
    )
    try:
        with urllib_request.urlopen(req, timeout=timeout) as r:
            logger.info(f"webhook sent: {url} status={r.status}")
    except Exception as exc:
        logger.warning(f"webhook failed {url}: {exc}")


# ===== 同步工具 worker（Redis 队列消费） =====

def sync_tool_worker(tool_name: str, params: dict[str, Any],
                      *, trace_id: str = "", agent_id: str = "",
                      webhook_url: str | None = None) -> Any:
    """队列 worker 回调。调用工具 → 发送 webhook。"""
    TRACE_ID.set(trace_id or "oc_" + uuid.uuid4().hex[:12])
    TOOL_NAME.set(tool_name)
    logger.info(f"worker executing: {tool_name} agent={agent_id}")

    try:
        raw_result = execute_tool(tool_name, params)
        masked = mask_output(raw_result)
        err = None
    except Exception as exc:
        logger.error(f"worker failed: {exc}", exc_info=True)
        masked = None
        err = str(exc)

    # 发送 webhook
    url = webhook_url or settings.adapter.ADAPTER_DEFAULT_WEBHOOK_URL
    if url:
        try:
            payload = WebhookPayload(
                task_id=params.get("_task_id", "") if isinstance(params, dict) else "",
                tool_name=tool_name,
                status="SUCCESS" if err is None else "FAILED",
                result_masked=masked,
                error=err,
                trace_id=TRACE_ID.get(),
                agent_id=agent_id,
            )
            _send_webhook(url, payload.model_dump())
        except Exception as exc:
            logger.warning(f"webhook 发送失败: {exc}")
    return {"tool": tool_name, "result_masked": masked, "error": err}


__all__ = ["router", "enqueue_task", "get_task_status", "cancel_task",
           "list_tasks", "manual_webhook", "sync_tool_worker"]
