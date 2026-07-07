"""core.spider_core — 增强版爬虫 SDK 与规则化采集引擎。

公共导出结构：
  - SpiderSDK / CrawlResponse：底层请求（HTTP + Playwright）
  - RenderedPage / SmartPageRenderer：页面智能渲染器
  - PageAnalysis / PageAnalyzer：页面智能识别（列表/标题/时间/附件/分页）
  - FieldRule / ListRule / DetailRule / AttachmentRule / CrawlRuleSet / PaginationRule：规则数据结构
  - FieldExtractor / ExtractedValue：字段提取（CSS/XPath/Regex/Text + cleaners）
  - PdfParser / PdfResult / ParsedTable：PDF 文本+表格解析
  - ImageParser / ImageResult：图片 OCR 解析
  - AttachmentParser / AttachmentResult：附件统一解析入口
  - DedupStore：增量去重（Redis / 内存）
  - AlertManager / Alert：告警管理
  - RuleCrawlEngine / EngineResult：规则化采集执行器
  - EnhancedConfig / enhanced_config：增强能力开关配置
"""

from __future__ import annotations

from core.spider_core.sdk import SpiderSDK, CrawlResponse
from core.spider_core.page_renderer import (
    RenderedPage,
    SmartPageRenderer,
    get_renderer,
)
from core.spider_core.smart_analyzer import (
    PageAnalysis,
    PageAnalyzer,
    analyze_page,
    analyze_html,
)
from core.spider_core.rule_models import (
    FieldRule,
    ListRule,
    DetailRule,
    AttachmentRule,
    CrawlRuleSet,
    PaginationRule,
)
from core.spider_core.field_extractor import (
    ExtractedValue,
    FieldExtractor,
    extract_fields,
    apply_cleaners,
)
from core.spider_core.pdf_parser import (
    PdfParser,
    PdfResult,
    ParsedTable,
)
from core.spider_core.image_parser import ImageParser, ImageResult
from core.spider_core.attachment_parser import (
    AttachmentParser,
    AttachmentResult,
    get_attachment_parser,
)
from core.spider_core.dedup_store import DedupStore, get_dedup_store
from core.spider_core.alert_manager import Alert, AlertManager, get_alert_manager
from core.spider_core.rule_engine import EngineResult, RuleCrawlEngine, run_rule
from core.spider_core.config import EnhancedConfig, enhanced_config, reload_config
from core.spider_core.exceptions import (
    SpiderError,
    ProxyUnavailableError,
    BlockedByRobotsError,
    RateLimitExceededError,
    CrawlerRiskDetectedError,
    CheckpointNotFoundError,
    UAFileNotFoundError,
)

__all__ = [
    "SpiderSDK",
    "CrawlResponse",
    "RenderedPage",
    "SmartPageRenderer",
    "get_renderer",
    "PageAnalysis",
    "PageAnalyzer",
    "analyze_page",
    "analyze_html",
    "FieldRule",
    "ListRule",
    "DetailRule",
    "AttachmentRule",
    "CrawlRuleSet",
    "PaginationRule",
    "ExtractedValue",
    "FieldExtractor",
    "extract_fields",
    "apply_cleaners",
    "PdfParser",
    "PdfResult",
    "ParsedTable",
    "ImageParser",
    "ImageResult",
    "AttachmentParser",
    "AttachmentResult",
    "get_attachment_parser",
    "DedupStore",
    "get_dedup_store",
    "Alert",
    "AlertManager",
    "get_alert_manager",
    "EngineResult",
    "RuleCrawlEngine",
    "run_rule",
    "EnhancedConfig",
    "enhanced_config",
    "reload_config",
    "SpiderError",
    "ProxyUnavailableError",
    "BlockedByRobotsError",
    "RateLimitExceededError",
    "CrawlerRiskDetectedError",
    "CheckpointNotFoundError",
    "UAFileNotFoundError",
]
