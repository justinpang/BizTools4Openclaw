"""adapter/models — Pydantic 请求/响应模型。"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field


class ToolExecuteRequest(BaseModel):
    """工具同步执行请求。"""
    params: dict[str, Any] = Field(default_factory=dict, description="工具参数，具体取决于工具名称")
    async_mode: bool = Field(default=False, description="true=入队异步返回task_id；false=同步阻塞返回结果")
    webhook_url: str | None = Field(default=None, description="异步任务完成后的回调URL")
    agent_id: str = Field(default="default-agent", description="调用方Agent标识，用于配额计数")


class TaskEnqueueRequest(BaseModel):
    """任务入队请求。"""
    tool_name: str
    params: dict[str, Any] = Field(default_factory=dict)
    webhook_url: str | None = None
    agent_id: str = "default-agent"


class ApiResponse(BaseModel):
    """统一响应。"""
    code: int = Field(default=0, description="0=成功，其余为HTTP错误码")
    msg: str = Field(default="OK")
    data: Any = Field(default=None)
    trace_id: str | None = None
    task_id: str | None = None
    timestamp: int = Field(default_factory=lambda: int(datetime.utcnow().timestamp()))


class ToolDefinition(BaseModel):
    """单个工具定义（OpenClaw Skill JSON 格式）。"""
    tool_name: str
    tool_type: str
    version: str = "1.0"
    display_name: str
    description: str
    auth_type: str = "bearer"
    http_method: str = "POST"
    endpoint: str
    callback_supported: bool = True
    async_capable: bool = False
    inputs: dict[str, Any] = Field(default_factory=dict)
    outputs: dict[str, Any] = Field(default_factory=dict)
    sample_call: dict[str, Any] | None = None


class WebhookPayload(BaseModel):
    """Webhook 回调体。"""
    task_id: str
    tool_name: str
    status: str
    result_masked: Any = None
    error: str | None = None
    trace_id: str | None = None
    agent_id: str | None = None
    timestamp: int = Field(default_factory=lambda: int(datetime.utcnow().timestamp()))


__all__ = [
    "ToolExecuteRequest",
    "TaskEnqueueRequest",
    "ApiResponse",
    "ToolDefinition",
    "WebhookPayload",
]
