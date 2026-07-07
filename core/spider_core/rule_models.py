"""core/spider_core/rule_models — 标准化采集规则数据结构。

本文件仅定义数据结构，不含任何站点专属规则。所有规则由上层业务传入。

典型用法：

    from core.spider_core.rule_models import (
        CrawlRuleSet, ListRule, DetailRule, FieldRule,
        PaginationRule, TEMPLATES,
    )

    # 1) 直接构造
    rule = CrawlRuleSet(
        name="gov_test",
        list_rule=ListRule(
            url_template="https://example.gov.cn/list?page={page}",
            item_selector="ul.news-list > li",
            link_selector="a",
            max_pages=2,
            use_render=False,
        ),
        detail_rule=DetailRule(
            use_render=False,
            fields=TEMPLATES["gov_notice"],
        ),
        max_items=50,
        compliance_check=True,
    )

    # 2) 从 JSON/字典加载
    data = {...}
    rule = CrawlRuleSet.model_validate(data)
"""

from __future__ import annotations

from typing import Dict, List, Literal, Optional

from pydantic import BaseModel, Field


# =========================================================================
# 分页规则
# =========================================================================

class PaginationRule(BaseModel):
    """翻页规则。"""
    mode: Literal["next_button", "page_param", "infinite_scroll"] = "page_param"
    next_selector: Optional[str] = None  # CSS 选择器（mode=next_button 时使用）
    page_param_name: Optional[str] = None  # URL 参数名（mode=page_param 时使用）
    max_pages: int = 20
    sample_urls: List[str] = []


# =========================================================================
# 字段提取规则
# =========================================================================

class FieldRule(BaseModel):
    """单字段提取规则。"""
    name: str
    extractor: Literal["css", "xpath", "regex", "text"] = "css"
    expression: str
    attribute: Optional[str] = None  # CSS 模式下，取哪个属性（None=innerText）
    regex_group: int = 0  # 正则模式下，取哪个分组（0=完整匹配）
    required: bool = False
    default_value: Optional[str] = None
    cleaners: List[str] = []
    date_format: Optional[str] = None


# =========================================================================
# 列表/详情/附件规则
# =========================================================================

class ListRule(BaseModel):
    """列表页规则。"""
    url_template: str
    item_selector: str
    link_selector: str
    link_attribute: str = "href"
    pagination: Optional[PaginationRule] = None
    max_pages: int = 20
    use_render: bool = False


class DetailRule(BaseModel):
    """详情页规则。"""
    url_template: Optional[str] = None
    fields: List[FieldRule]
    use_render: bool = False


class AttachmentRule(BaseModel):
    """附件解析规则。"""
    link_selector: str
    link_attribute: str = "href"
    parse_pdf: bool = True
    parse_image: bool = True
    parse_docx: bool = True
    download_limit_mb: float = 50.0
    max_attachments_per_page: int = 10


# =========================================================================
# 规则集（引擎入口结构）
# =========================================================================

class CrawlRuleSet(BaseModel):
    """完整采集规则集。"""
    name: str = "default_rule"
    task_id: str = ""
    list_rule: ListRule
    detail_rule: Optional[DetailRule] = None
    attachment_rule: Optional[AttachmentRule] = None
    field_mapping: Dict[str, str] = Field(default_factory=dict)
    dedup_mode: Literal["url", "field", "none"] = "url"
    dedup_fields: List[str] = Field(default_factory=list)
    retry_count: int = 3
    retry_backoff_sec: float = 2.0
    match_rate_threshold: float = 0.5
    failure_rate_threshold: float = 0.3
    max_items: int = 1000
    compliance_check: bool = True


# =========================================================================
# 三类场景预设字段模板（非站点专属，仅字段组合参考）
# =========================================================================

TEMPLATES: Dict[str, List[FieldRule]] = {
    "gov_notice": [
        FieldRule(
            name="title",
            extractor="css",
            expression="h1, .article-title, .title",
            required=True,
            cleaners=["strip_whitespace", "normalize_space"],
        ),
        FieldRule(
            name="publish_time",
            extractor="css",
            expression=".time, .date, [class*='time'], [class*='date'], time",
            cleaners=["strip_whitespace"],
            date_format="%Y-%m-%d",
        ),
        FieldRule(
            name="source",
            extractor="css",
            expression=".source, [class*='source'], [class*='from']",
        ),
        FieldRule(
            name="content",
            extractor="css",
            expression=".content, article, [class*='article'], [class*='content']",
            cleaners=["strip_whitespace", "remove_extra_newlines", "remove_html_tags"],
        ),
        FieldRule(
            name="doc_number",
            extractor="css",
            expression="[class*='doc-number'], [class*='docno'], [class*='number']",
        ),
    ],

    "corp_announcement": [
        FieldRule(
            name="title",
            extractor="css",
            expression="h1, .title, .article-title",
            required=True,
            cleaners=["strip_whitespace", "normalize_space"],
        ),
        FieldRule(
            name="company_name",
            extractor="css",
            expression="[class*='company'], [class*='corp'], [class*='enterprise']",
        ),
        FieldRule(
            name="publish_time",
            extractor="css",
            expression="[class*='time'], [class*='date'], time",
            date_format="%Y-%m-%d",
        ),
        FieldRule(
            name="content",
            extractor="css",
            expression=".content, .body, article, [class*='content']",
            cleaners=["strip_whitespace", "remove_extra_newlines", "remove_html_tags"],
        ),
        FieldRule(
            name="announcement_type",
            extractor="css",
            expression="[class*='type'], [class*='category'], [class*='tag']",
        ),
    ],

    "violation_report": [
        FieldRule(
            name="title",
            extractor="css",
            expression="h1, .title, .article-title",
            required=True,
            cleaners=["strip_whitespace", "normalize_space"],
        ),
        FieldRule(
            name="violator",
            extractor="css",
            expression="[class*='violat'], [class*='subject'], [class*='party']",
        ),
        FieldRule(
            name="violation_content",
            extractor="css",
            expression="[class*='content'], [class*='fact'], [class*='violation']",
            cleaners=["strip_whitespace", "remove_extra_newlines", "remove_html_tags"],
        ),
        FieldRule(
            name="punishment",
            extractor="css",
            expression="[class*='punish'], [class*='penalty'], [class*='result']",
        ),
        FieldRule(
            name="publish_time",
            extractor="css",
            expression="[class*='time'], [class*='date'], time",
            date_format="%Y-%m-%d",
        ),
    ],
}


__all__ = [
    "PaginationRule",
    "FieldRule",
    "ListRule",
    "DetailRule",
    "AttachmentRule",
    "CrawlRuleSet",
    "TEMPLATES",
]
