"""T31: 步骤编排 API 的 Pydantic 请求/响应模型。

与 :mod:`business.custom_spider.step_models` 中数据类一致，
用于 FastAPI 路由函数的类型注解与输入校验。

所有模型 ``extra="ignore"``，确保向前兼容：服务端新增字段时，
老客户端请求不会报错。
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field, ConfigDict, field_validator


# ============================================================================
# 通用响应
# ============================================================================
class ApiResponse(BaseModel):
    code: int = Field(default=0, description="0=成功，其它为错误码")
    msg: str = Field(default="ok", description="人类可读的提示消息")
    data: Optional[Dict[str, Any]] = Field(default=None)

    model_config = ConfigDict(extra="ignore")


# ============================================================================
# StepTest: 单步测试
# ============================================================================
class StepTestRequest(BaseModel):
    step_id: str = Field(..., min_length=1, max_length=128)
    step_type: str = Field(..., min_length=1, max_length=32)
    config: Dict[str, Any] = Field(default_factory=dict, description="步骤配置 dict；具体字段随 step_type 变化")
    page_html: Optional[str] = Field(default=None, description="可选：上游渲染得到的 HTML，用于脱离网络做测试")
    upstream_data: Optional[Dict[str, Any]] = Field(default=None, description="可选：上一步输出")

    model_config = ConfigDict(extra="ignore")

    @field_validator("step_type")
    @classmethod
    def _check_step_type(cls, v: str) -> str:
        allowed = {"page_access", "list_detect", "detail_jump",
                   "attachment_parse", "field_mapping", "result_preview"}
        if v not in allowed:
            raise ValueError(f"step_type 必须是 {sorted(allowed)} 之一")
        return v


class StepTestItemInfo(BaseModel):
    """list_detect 输出的条目样例。"""
    title: str = ""
    link: str = ""
    publish_time: str = ""
    _raw_time: Optional[str] = None

    model_config = ConfigDict(extra="allow")


# ============================================================================
# SmartDetect: 智能识别候选容器 + 时间字段
# ============================================================================
class SmartDetectRequest(BaseModel):
    page_html: Optional[str] = Field(default=None, description="待分析的 HTML 片段；若未提供，必须同时提供 url 让服务端渲染")
    url: Optional[str] = Field(default=None, description="可选：当未提供 page_html 时，服务端会先抓取该 URL")
    use_render: bool = Field(default=False, description="是否用 headless 浏览器渲染")
    max_candidates: int = Field(default=3, ge=1, le=10, description="返回容器候选数上限")
    detect_time_fields: bool = True
    detect_items: bool = True
    item_limit: int = Field(default=10, ge=1, le=200)

    model_config = ConfigDict(extra="ignore")


class SmartDetectContainer(BaseModel):
    selector: str = ""
    item_count: int = 0
    confidence: float = 0.0
    sample_titles: List[str] = Field(default_factory=list)

    model_config = ConfigDict(extra="allow")


class SmartDetectTimeField(BaseModel):
    selector: str = ""
    format_hint: str = ""
    sample_values: List[str] = Field(default_factory=list)
    confidence: float = 0.0

    model_config = ConfigDict(extra="allow")


class SmartDetectItem(BaseModel):
    title: str = ""
    link: str = ""
    publish_time_iso: str = ""
    _raw_time: Optional[str] = None

    model_config = ConfigDict(extra="allow")


class SmartDetectResponse(BaseModel):
    success: bool = True
    containers: List[SmartDetectContainer] = Field(default_factory=list)
    time_fields: List[SmartDetectTimeField] = Field(default_factory=list)
    items: List[SmartDetectItem] = Field(default_factory=list)
    item_count_total: int = 0
    confidence: float = 0.0
    crawl_scope_suggestion: str = "latest"  # latest | top_n | all
    degrade_reason: Optional[str] = Field(default=None, description="置信度不足时返回的降级原因")
    target_url: Optional[str] = None

    model_config = ConfigDict(extra="allow")


# ============================================================================
# FullTest: 全链路测试
# ============================================================================
class FullTestRequest(BaseModel):
    package: Dict[str, Any] = Field(..., description="StepsPackage 的 JSON 字典")

    model_config = ConfigDict(extra="ignore")


# ============================================================================
# Assemble: StepsPackage -> CrawlRuleSet dict
# ============================================================================
class AssembleRequest(BaseModel):
    package: Dict[str, Any] = Field(..., description="StepsPackage 的 JSON 字典")
    validate_ruleset: bool = Field(default=True, description="是否用 CrawlRuleSet model 做二次校验")

    model_config = ConfigDict(extra="ignore")


# ============================================================================
# CompatConvert: CrawlRuleSet dict -> StepsPackage
# ============================================================================
class CompatConvertRequest(BaseModel):
    rule_config: Dict[str, Any] = Field(..., description="旧版 CrawlRuleSet 的 JSON 字典")
    plan_name: str = ""
    target_domain: str = ""
    spider_type: str = "generic"

    model_config = ConfigDict(extra="ignore")


# ============================================================================
# Draft: 草稿保存/加载
# ============================================================================
class DraftSaveRequest(BaseModel):
    session_id: Optional[str] = Field(default=None, max_length=128)
    plan_id: Optional[str] = Field(default=None, max_length=128)
    package: Dict[str, Any] = Field(...)

    model_config = ConfigDict(extra="ignore")


class DraftLoadRequest(BaseModel):
    session_id: Optional[str] = Field(default=None, max_length=128)
    plan_id: Optional[str] = Field(default=None, max_length=128)

    model_config = ConfigDict(extra="ignore")


class TemplateApplyRequest(BaseModel):
    template_id: str = Field(..., min_length=1, max_length=64)
    plan_name: str = ""
    target_domain: str = ""
    spider_type: str = "generic"

    model_config = ConfigDict(extra="ignore")


# ============================================================================
# 页面预览（脱敏后的 HTML + title）
# ============================================================================
class PagePreviewRequest(BaseModel):
    url: str = Field(..., min_length=1, max_length=2048)
    use_render: bool = False
    render_wait_ms: int = Field(default=1500, ge=0, le=30000)

    model_config = ConfigDict(extra="ignore")


class PagePreviewResponse(BaseModel):
    success: bool = True
    url: str = ""
    title: str = ""
    html_preview: str = ""
    status_code: int = 0
    masked: bool = True
    error: Optional[str] = None

    model_config = ConfigDict(extra="allow")
