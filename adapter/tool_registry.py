"""adapter/tool_registry — 工具注册中心：反射式生成 OpenClaw Skill JSON。"""

from __future__ import annotations

import importlib
import inspect
from typing import Any

from adapter.models import ToolDefinition
from infra.logger_setup import get_logger

logger = get_logger("openclaw.tools")

# 注册表：tool_name -> 元数据
TOOL_REGISTRY: dict[str, dict[str, Any]] = {
    "spider_list": {
        "module": "business.multi_spider.registry",
        "func": "list_spiders",
        "tool_type": "spider",
        "display_name": "列出所有可用爬虫",
        "description": "返回当前系统所有已注册爬虫名称与能力描述",
        "async_capable": False,
        "inputs_sample": {},
        "outputs_sample": {
            "spiders": [{"name": "generic_web", "description": "通用网页爬虫"}],
        },
    },
    "spider_run": {
        "module": "business.multi_spider.registry",
        "func": "run_spider_by_name",
        "tool_type": "spider",
        "display_name": "运行指定爬虫",
        "description": "根据爬虫名称与关键词执行公域商机采集",
        "async_capable": True,
        "inputs_sample": {
            "spider_name": "generic_web",
            "keywords": ["采购", "ERP"],
            "max_pages": 20,
        },
    },
    "clean_run": {
        "module": "business.data_clean.registry",
        "func": "run_cleaning",
        "tool_type": "data_clean",
        "display_name": "数据清洗",
        "description": "对采集的商机做去重/评分/合规过滤",
        "async_capable": True,
        "inputs_sample": {
            "tenant_id": "t1",
            "source_batch_id": "batch_001",
            "items": [],
        },
    },
    "send_batch": {
        "module": "business.customer_send.registry",
        "func": "run_batch",
        "tool_type": "customer_send",
        "display_name": "同步批量商机触达",
        "description": "同步执行邮件/企微/飞书批量触达（复用T11）",
        "async_capable": False,
        "inputs_sample": {
            "task_id": "task_001",
            "targets": [{"opportunity_id": "opp_1", "customer_name": "C"}],
            "channels": ["email", "wechat"],
        },
    },
    "send_async": {
        "module": "business.customer_send.registry",
        "func": "async_run",
        "tool_type": "customer_send",
        "display_name": "异步批量商机触达",
        "description": "入队后立即返回 task_id（复用T11）",
        "async_capable": True,
        "inputs_sample": {
            "task_id": "task_002",
            "targets": [],
            "channels": ["email"],
        },
    },
    "sales_assign": {
        "module": "business.sales_task.registry",
        "func": "assign",
        "tool_type": "sales_task",
        "display_name": "商机自动分配",
        "description": "按行业/地域/权重将商机分配给销售（T12）",
        "async_capable": False,
        "inputs_sample": {
            "opportunities": [{"opportunity_id": "opp_1", "tenant_id": "t1"}],
            "salespersons": [{"sales_id": "s1", "industries": ["IT"], "weight": 1.0}],
        },
    },
    "sales_remind": {
        "module": "business.sales_task.registry",
        "func": "remind",
        "tool_type": "sales_task",
        "display_name": "多级提醒扫描",
        "description": "扫描待跟进商机，触发多级推送（T12）",
        "async_capable": False,
        "inputs_sample": {
            "opportunities": [],
            "salespersons": [],
        },
    },
    "sales_transition": {
        "module": "business.sales_task.registry",
        "func": "transition",
        "tool_type": "sales_task",
        "display_name": "商机状态流转",
        "description": "将商机从当前状态流转到目标状态",
        "async_capable": False,
        "inputs_sample": {
            "opportunity": {"opportunity_id": "opp_1", "tenant_id": "t1",
                             "status": "FOLLOWING"},
            "target_status": "CLOSED_WON",
            "operator_sales_id": "s1",
            "detail": "客户签约",
        },
    },
    "sales_add_tag": {
        "module": "business.sales_task.registry",
        "func": "add_tag",
        "tool_type": "sales_task",
        "display_name": "添加商机标签",
        "description": "给商机打标签",
        "async_capable": False,
        "inputs_sample": {
            "opportunity": {"opportunity_id": "opp_1", "tenant_id": "t1"},
            "tag": "优质客户",
            "operator_sales_id": "s1",
        },
    },
    "sales_remove_tag": {
        "module": "business.sales_task.registry",
        "func": "remove_tag",
        "tool_type": "sales_task",
        "display_name": "移除商机标签",
        "description": "从商机上移除指定标签",
        "async_capable": False,
        "inputs_sample": {
            "opportunity": {"opportunity_id": "opp_1", "tenant_id": "t1"},
            "tag": "需要跟进",
            "operator_sales_id": "s1",
        },
    },
    "sales_record_follow": {
        "module": "business.sales_task.registry",
        "func": "record_follow_up",
        "tool_type": "sales_task",
        "display_name": "写入跟进记录",
        "description": "记录销售电话/邮件/会议跟进内容",
        "async_capable": False,
        "inputs_sample": {
            "opportunity": {"opportunity_id": "opp_1", "tenant_id": "t1"},
            "sales_id": "s1",
            "channel": "phone",
            "content": "客户确认预算",
        },
    },
    "sales_funnel_stats": {
        "module": "business.sales_task.registry",
        "func": "get_funnel_stats",
        "tool_type": "sales_task",
        "display_name": "商机转化漏斗统计",
        "description": "输出采集/清洗/触达/跟进/成交各环节转化率",
        "async_capable": False,
        "inputs_sample": {
            "tenant_id": "t1",
            "period_days": 7,
        },
    },
}


# ---- 公共接口 ----

def list_tools() -> list[ToolDefinition]:
    """返回所有已注册工具的 OpenClaw Skill JSON。"""
    return [get_tool(name) for name in TOOL_REGISTRY]


def get_tool(tool_name: str) -> ToolDefinition | None:
    """返回单个工具定义，若无则返回 None。"""
    meta = TOOL_REGISTRY.get(tool_name)
    if meta is None:
        return None
    return ToolDefinition(
        tool_name=tool_name,
        tool_type=meta["tool_type"],
        version="1.0",
        display_name=meta["display_name"],
        description=meta["description"],
        auth_type="bearer",
        http_method="POST",
        endpoint=f"/api/v1/tools/{tool_name}/execute",
        callback_supported=meta.get("async_capable", False),
        async_capable=meta.get("async_capable", False),
        inputs=_build_inputs_schema(meta),
        outputs=_build_outputs_schema(meta),
        sample_call={
            "http_method": "POST",
            "url": f"/api/v1/tools/{tool_name}/execute",
            "headers": {"Authorization": "Bearer <token>", "X-Agent-Id": "openclaw-demo"},
            "body": meta.get("inputs_sample", {}),
        },
    )


def get_callable(tool_name: str):
    """获取工具对应的可调用函数，失败返回 None。"""
    meta = TOOL_REGISTRY.get(tool_name)
    if meta is None:
        return None
    try:
        mod = importlib.import_module(meta["module"])
        fn = getattr(mod, meta["func"], None)
        return fn
    except Exception as exc:
        logger.info(f"import {meta['module']} 失败: {exc}")
        return None


def execute_tool(tool_name: str, params: dict[str, Any]) -> Any:
    """调用工具，返回原始结果（未脱敏）。"""
    meta = TOOL_REGISTRY.get(tool_name)
    if meta is None:
        raise ValueError(f"unknown tool: {tool_name}")
    fn = get_callable(tool_name)
    if fn is None:
        raise RuntimeError(f"tool {tool_name} 无法加载 callable")

    logger.info(f"execute: {tool_name} params_keys={list(params.keys())}")
    try:
        sig = inspect.signature(fn)
        # 过滤掉不在签名中的键，避免 TypeError
        valid_keys = set(sig.parameters.keys())
        filtered = {k: v for k, v in params.items() if k in valid_keys}
        return fn(**filtered)
    except TypeError as exc:
        # 若签名过滤后仍然不匹配，尝试直接调用
        logger.info(f"签名匹配失败，回退原始调用: {exc}")
        return fn(params)


# ---- 内部辅助 ----

def _build_inputs_schema(meta: dict[str, Any]) -> dict[str, Any]:
    sample = meta.get("inputs_sample") or {}
    return {
        "type": "object",
        "properties": _describe_value(sample),
        "required": list(sample.keys())[:3],
    }


def _build_outputs_schema(meta: dict[str, Any]) -> dict[str, Any]:
    sample = meta.get("outputs_sample")
    if sample:
        return {"type": "object", "properties": _describe_value(sample)}
    return {
        "type": "object",
        "properties": {
            "task_id": {"type": "string", "description": "异步任务ID"},
            "status": {"type": "string"},
            "result_masked": {"type": "object", "description": "脱敏后的执行结果"},
            "error": {"type": "string"},
        },
    }


def _describe_value(val: Any) -> dict[str, Any]:
    """基于 sample 值生成简易 JSON Schema。"""
    if val is None:
        return {"type": "null"}
    if isinstance(val, bool):
        return {"type": "boolean"}
    if isinstance(val, int):
        return {"type": "integer"}
    if isinstance(val, float):
        return {"type": "number"}
    if isinstance(val, str):
        return {"type": "string"}
    if isinstance(val, list):
        item_schema = _describe_value(val[0]) if val else {}
        return {"type": "array", "items": item_schema}
    if isinstance(val, dict):
        return {
            "type": "object",
            "properties": {k: _describe_value(v) for k, v in val.items()},
        }
    return {"type": "string"}


__all__ = [
    "TOOL_REGISTRY",
    "list_tools",
    "get_tool",
    "get_callable",
    "execute_tool",
]
