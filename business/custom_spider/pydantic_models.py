"""business/custom_spider/pydantic_models — Pydantic DTO。

用于 PlanService 输入输出参数与结果包装。
"""

from __future__ import annotations

from typing import Any, List, Optional, Dict

from pydantic import BaseModel, Field, ConfigDict


# ============================================================
# 输入 DTO
# ============================================================
class PlanCreate(BaseModel):
    """创建方案请求。"""

    plan_name: str = Field(..., min_length=2, max_length=128)
    plan_code: Optional[str] = Field(default=None, max_length=64)
    target_domain: str = Field(..., min_length=2, max_length=256)
    spider_type: str = Field(default="generic", max_length=32)
    description: Optional[str] = Field(default=None, max_length=1000)
    rule_config: Dict[str, Any] = Field(..., description="T25 CrawlRuleSet 规则配置 dict")
    schedule_config: Optional[Dict[str, Any]] = Field(default=None)
    increment_config: Optional[Dict[str, Any]] = Field(default=None)
    cookie_raw: Optional[str] = Field(default=None, max_length=1500, description="明文 cookie，写入时自动加密")
    operator: str = Field(default="system", max_length=128)

    model_config = ConfigDict(extra="ignore")


class PlanUpdate(BaseModel):
    """更新方案请求。"""

    plan_name: Optional[str] = Field(default=None, min_length=2, max_length=128)
    status: Optional[str] = Field(default=None, max_length=16)
    rule_config: Optional[Dict[str, Any]] = Field(default=None)
    schedule_config: Optional[Dict[str, Any]] = Field(default=None)
    increment_config: Optional[Dict[str, Any]] = Field(default=None)
    cookie_raw: Optional[str] = Field(default=None, max_length=1500)
    change_note: Optional[str] = Field(default=None, max_length=512)
    operator: str = Field(default="system", max_length=128)

    model_config = ConfigDict(extra="ignore")


class PlanTest(BaseModel):
    """测试运行请求。"""

    test_url: Optional[str] = Field(default=None, max_length=1024)
    max_items: int = Field(default=5, ge=1, le=500)
    operator: str = Field(default="system", max_length=128)

    model_config = ConfigDict(extra="ignore")


class PlanRunResult(BaseModel):
    """执行结果。"""

    plan_id: int
    run_id: int
    status: str
    items_total: int
    items_success: int
    items_failed: int
    field_match_rate: Optional[float] = None
    duration_ms: Optional[int] = None
    alerts: List[Dict[str, Any]] = Field(default_factory=list)
    items: List[Dict[str, Any]] = Field(default_factory=list, description="提取到的样本条目（前N条）")
    error: Optional[str] = None

    model_config = ConfigDict(extra="ignore")


class PlanListQuery(BaseModel):
    """列表查询过滤条件。"""

    status: Optional[str] = None
    spider_type: Optional[str] = None
    target_domain: Optional[str] = None
    keyword: Optional[str] = None
    page: int = 1
    page_size: int = 20


__all__ = [
    "PlanCreate",
    "PlanUpdate",
    "PlanTest",
    "PlanRunResult",
    "PlanListQuery",
]
