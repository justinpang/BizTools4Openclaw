"""adapter/schema_adapter — 入参出参标准化 + T06 隐私脱敏。"""

from __future__ import annotations

from typing import Any

from infra.logger_setup import get_logger
from configs.settings import settings

logger = get_logger("openclaw.schema")

_mask = None


def _get_mask():
    """懒加载脱敏器，避免启动时依赖 core 初始化。"""
    global _mask
    if _mask is not None:
        return _mask
    try:
        from core.compliance.pii_mask import PIIMask
        _mask = PIIMask()
    except Exception as exc:
        logger.info(f"T06 PIIMask 不可用，使用兜底脱敏: {exc}")
        _mask = _FallbackMask()
    return _mask


class _FallbackMask:
    """当 core.compliance 不可用时的兜底脱敏器。"""

    @staticmethod
    def auto_mask(data: Any, *, deep: bool = True) -> Any:
        if data is None:
            return None
        if isinstance(data, str):
            if "@" in data or any(ch.isdigit() and len(data) >= 7 for ch in data):
                return "***"
            if len(data) > 8:
                return data[:2] + "***" + data[-2:]
            return data
        if isinstance(data, (list, tuple)):
            return [_FallbackMask.auto_mask(x, deep=deep) for x in data]
        if isinstance(data, dict):
            return {k: _FallbackMask.auto_mask(v, deep=deep) for k, v in data.items()}
        return data


def mask_output(data: Any) -> Any:
    """对响应数据做隐私脱敏（递归）。"""
    if not settings.adapter.ADAPTER_AUTO_MASK_PII:
        return data
    try:
        m = _get_mask()
        return m.auto_mask(data, deep=True)
    except Exception as exc:
        logger.info(f"脱敏异常，兜底处理: {exc}")
        return _FallbackMask.auto_mask(data, deep=True)


def normalize_request_params(params: Any, *, tool_name: str) -> dict[str, Any]:
    """将 OpenClaw 送来的请求参数标准化为 dict。"""
    if params is None:
        return {}
    if isinstance(params, dict):
        return params
    # Pydantic / dataclass
    if hasattr(params, "model_dump"):
        try:
            return dict(params.model_dump())
        except Exception:
            pass
    if hasattr(params, "__dict__"):
        try:
            return {k: v for k, v in params.__dict__.items() if not k.startswith("_")}
        except Exception:
            pass
    # 最后兜底：转 str
    return {"raw": str(params)}


def format_task_result(task_meta: Any, raw_result: Any = None,
                       error: str | None = None) -> dict[str, Any]:
    """把 TaskMeta 转为标准 dict（会被 mask_output 递归脱敏）。"""
    def _safe_val(attr):
        try:
            return getattr(task_meta, attr, None)
        except Exception:
            return None

    status = str(_safe_val("status") or "UNKNOWN")
    if hasattr(task_meta, "status") and hasattr(task_meta.status, "value"):
        status = str(task_meta.status.value)
    tool_name = str(getattr(task_meta, "name", "") or "")
    return {
        "task_id": str(_safe_val("task_id") or ""),
        "tool_name": tool_name,
        "status": status,
        "created_at": int(float(_safe_val("created_at") or 0)) if _safe_val("created_at") else None,
        "started_at": int(float(_safe_val("started_at") or 0)) if _safe_val("started_at") else None,
        "finished_at": int(float(_safe_val("finished_at") or 0)) if _safe_val("finished_at") else None,
        "result_masked": raw_result,
        "error": error,
        "retries": int(_safe_val("retries") or 0),
    }


__all__ = [
    "mask_output",
    "normalize_request_params",
    "format_task_result",
]
