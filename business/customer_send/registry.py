"""business/customer_send/registry — 公开的单例入口。"""

from __future__ import annotations

from business.customer_send.models import BatchSendParams, BatchSendResult
from business.customer_send.pipeline import CustomerSendPipeline

_pipeline = CustomerSendPipeline()

TASK_HANDLER_NAME = "customer_send:run_batch"


def run_batch(params: BatchSendParams | dict) -> BatchSendResult:
    """同步执行一批商机触达。"""
    return _pipeline.run(params)


def async_run(params: BatchSendParams | dict) -> str:
    """将任务投递到异步队列；返回 task_id。"""
    task_id = getattr(params, "task_id", None) if not isinstance(params, dict) else params.get("task_id")
    payload = params.model_dump() if not isinstance(params, dict) else dict(params)
    if not task_id:
        import hashlib
        task_id = "async_" + hashlib.md5(repr(sorted(payload.items())).encode()).hexdigest()[:12]
    try:
        from infra.task_queue import task_queue as tq
        if tq is not None and hasattr(tq, "enqueue"):
            tq.enqueue(TASK_HANDLER_NAME, payload)
    except Exception:
        # 若队列不可用，fallback：直接同步执行（不影响使用）
        run_batch(params)
    return str(task_id)


def list_runs(tenant_id: str | None = None) -> list[str]:
    """预留 — 返回已知的 task_id。目前不做持久化查询。"""
    return []


def _queue_handler(payload_dict: dict) -> dict:
    """队列 worker 回调 — 将 payload 变成 BatchSendResult 的 dict 形式。"""
    result = run_batch(payload_dict)
    return result.model_dump() if hasattr(result, "model_dump") else dict(
        task_id=getattr(result, "task_id", ""),
        status=getattr(result, "status", ""),
        total=getattr(result, "total", 0),
        success=getattr(result, "success", 0),
        failed=getattr(result, "failed", 0),
        blocked=getattr(result, "blocked", 0),
        rate_limited=getattr(result, "rate_limited", 0),
    )


__all__ = [
    "run_batch",
    "async_run",
    "list_runs",
    "TASK_HANDLER_NAME",
    "_queue_handler",
]
