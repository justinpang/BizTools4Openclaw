"""adapter — OpenClaw 适配网关。
模块懒加载：避免测试时因缺少 FastAPI 依赖而失败。
"""

from adapter.tool_registry import TOOL_REGISTRY, list_tools, get_tool, execute_tool

__all__ = [
    "TOOL_REGISTRY",
    "list_tools",
    "get_tool",
    "execute_tool",
]
