from __future__ import annotations

from typing import TYPE_CHECKING

from infra.logger_setup import get_logger

logger = get_logger("multi_spider.registry")

if TYPE_CHECKING:
    from business.multi_spider.base import BaseSpider
    from business.multi_spider.models import SpiderTaskParams, SpiderTaskResult


# =====================
# 注册表
# =====================


def _lazy_registry() -> dict[str, type[BaseSpider]]:
    """延迟导入避免循环依赖。"""
    from business.multi_spider.sources.generic_web import (
        GenericWebArticleSpider,
        GenericCommentSpider,
    )
    from business.multi_spider.sources.douyin_xhs import (
        DouyinWorkSpider,
        DouyinCommentSpider,
        XhsNoteSpider,
        XhsCommentSpider,
    )
    from business.multi_spider.sources.zhihu_baiduqa import (
        ZhihuQuestionSpider,
        ZhihuAnswerSpider,
        BaiduQASpider,
    )
    from business.multi_spider.sources.local_classifieds import (
        Listing58Spider,
        XianyuItemSpider,
        LocalNeedSpider,
    )
    from business.multi_spider.sources.bid_and_gov import (
        BidNoticeSpider,
        GovProcurementSpider,
        PublicResourceSpider,
    )
    from business.multi_spider.sources.enterprise_news import (
        QccNewCompanySpider,
        QccChangeEventSpider,
        TycJobSpider,
    )

    return {
        # 通用
        "generic_article": GenericWebArticleSpider,
        "generic_comment": GenericCommentSpider,
        # 抖音/小红书
        "douyin_work": DouyinWorkSpider,
        "douyin_comment": DouyinCommentSpider,
        "xhs_note": XhsNoteSpider,
        "xhs_comment": XhsCommentSpider,
        # 知乎/百度
        "zhihu_question": ZhihuQuestionSpider,
        "zhihu_answer": ZhihuAnswerSpider,
        "baidu_qa": BaiduQASpider,
        # 58/闲鱼/本地生活
        "58_listing": Listing58Spider,
        "xianyu_item": XianyuItemSpider,
        "local_need": LocalNeedSpider,
        # 招投标/政府采购/公共资源
        "bid_notice": BidNoticeSpider,
        "gov_procurement": GovProcurementSpider,
        "public_resource": PublicResourceSpider,
        # 企查查/天眼查
        "qcc_new_company": QccNewCompanySpider,
        "qcc_change_event": QccChangeEventSpider,
        "tyc_job": TycJobSpider,
    }


# 缓存的注册表（仅在首次使用时构建）
_REGISTRY: dict[str, type[BaseSpider]] | None = None


def _get_registry() -> dict[str, type[BaseSpider]]:
    global _REGISTRY
    if _REGISTRY is None:
        _REGISTRY = _lazy_registry()
    return _REGISTRY


def list_spiders() -> list[str]:
    """返回所有已注册的 spider_name。"""
    return sorted(_get_registry().keys())


def get_spider_class(spider_name: str) -> type[BaseSpider] | None:
    """获取 spider 类；若未注册返回 None。"""
    return _get_registry().get(spider_name)


def run_spider_by_name(
    spider_name: str,
    params: dict | SpiderTaskParams,
) -> SpiderTaskResult:
    """按名字启动爬虫任务；spider_name 未注册时抛 ValueError。"""
    from business.multi_spider.models import SpiderTaskParams

    cls = get_spider_class(spider_name)
    if cls is None:
        raise ValueError(
            f"未注册的 spider_name: {spider_name!r}，可选: {list_spiders()}"
        )
    if isinstance(params, dict):
        params_obj = SpiderTaskParams(**params)
    else:
        params_obj = params
    instance = cls()
    logger.info(f"启动爬虫 {spider_name}（task_id={params_obj.task_id}，urls={len(params_obj.urls or [])}）")
    return instance.run(params_obj)


__all__ = [
    "list_spiders",
    "get_spider_class",
    "run_spider_by_name",
]
