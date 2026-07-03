from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field


# =====================
# 入参
# =====================


class SpiderTaskParams(BaseModel):
    """爬虫任务参数。"""

    spider_name: str
    task_id: str = Field(default_factory=lambda: uuid.uuid4().hex)
    urls: list[str] | None = None
    keywords: list[str] | None = None
    max_pages: int = 20
    max_items_per_url: int = 100
    render_js: bool = False
    use_proxy: bool = True
    tenant_id: str = "default"
    country: str = "CN"
    dry_run: bool = False
    extra: dict[str, Any] = Field(default_factory=dict)


# =====================
# 出参
# =====================


class SpiderTaskResult(BaseModel):
    """爬虫任务结果。"""

    task_id: str
    spider_name: str
    status: Literal["ok", "partial", "failed"] = "ok"
    total_attempted: int = 0
    total_persisted: int = 0
    total_failed: int = 0
    total_blocked_by_compliance: int = 0
    risk_detected: int = 0
    rate_limited: int = 0
    first_error: str | None = None
    started_at: datetime = Field(default_factory=lambda: datetime.utcnow())
    finished_at: datetime | None = None
    duration_ms: int | None = None
    source_ids: list[str] = Field(default_factory=list, exclude=True)


# =====================
# 单条解析结果
# =====================


@dataclass
class RawItem:
    """单个解析产出的原始条目。"""

    source_id: str
    source_url: str
    author: str = ""
    published_at: str | None = None
    title: str = ""
    content: str = ""
    tags: list[str] = field(default_factory=list)
    extra: dict[str, Any] = field(default_factory=dict)


__all__ = ["SpiderTaskParams", "SpiderTaskResult", "RawItem"]
