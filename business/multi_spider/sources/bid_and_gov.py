from __future__ import annotations

from core.spider_core import CrawlResponse
from configs.settings import settings
from business.multi_spider.base import BaseSpider
from business.multi_spider.models import RawItem, SpiderTaskParams
from business.multi_spider.pipeline import extract_basic_html, extract_items, extract_published_at


# =====================
# 招投标公告
# =====================


class BidNoticeSpider(BaseSpider):
    name = "bid_notice"

    def _generate_from_seeds(self, params: SpiderTaskParams) -> list[str]:
        s_cfg = settings.spider
        if not s_cfg.SPIDER_CHANNEL_BID_GOV_ENABLED:
            return []
        template = s_cfg.SPIDER_BID_SEARCH_TEMPLATE or ""
        urls: list[str] = []
        if template and "{keyword}" in template and params.keywords:
            for kw in params.keywords:
                urls.append(template.replace("{keyword}", kw))
        return urls[: params.max_pages or len(urls)]

    def parse(self, resp: CrawlResponse, params: SpiderTaskParams) -> list[RawItem]:
        blocks = extract_items(resp.text or "", max_items=params.max_items_per_url or 100)
        items: list[RawItem] = []
        for b in blocks:
            if not b["title"] and not b["content"]:
                continue
            items.append(
                RawItem(
                    source_id=self._build_source_id(
                        resp.final_url or resp.url,
                        {"seed": b["seed"], "platform": "bid"},
                    ),
                    source_url=resp.final_url or resp.url or "",
                    title=b["title"] or (b["content"] or "")[:80],
                    author=b["author"],
                    published_at=b["published_at"],
                    content=b["content"],
                    tags=["bid", "notice"],
                    extra={"platform": "bid", "kind": b["kind"]},
                )
            )
        if not items:
            info = extract_basic_html(resp.text or "")
            if info["title"] or info["text_body"]:
                items.append(
                    RawItem(
                        source_id="",
                        source_url=resp.final_url or resp.url or "",
                        title=info["title"] or (info["text_body"] or "")[:80],
                        author=info["author"],
                        published_at=extract_published_at(resp.text or ""),
                        content=info["text_body"],
                        tags=["bid", "notice", "page"],
                    )
                )
        return items


# =====================
# 政府采购
# =====================


class GovProcurementSpider(BaseSpider):
    name = "gov_procurement"

    def _generate_from_seeds(self, params: SpiderTaskParams) -> list[str]:
        s_cfg = settings.spider
        if not s_cfg.SPIDER_CHANNEL_BID_GOV_ENABLED:
            return []
        template = s_cfg.SPIDER_GOV_SEARCH_TEMPLATE or ""
        urls: list[str] = []
        if template and "{keyword}" in template and params.keywords:
            for kw in params.keywords:
                urls.append(template.replace("{keyword}", kw))
        return urls[: params.max_pages or len(urls)]

    def parse(self, resp: CrawlResponse, params: SpiderTaskParams) -> list[RawItem]:
        blocks = extract_items(resp.text or "", max_items=params.max_items_per_url or 100)
        items: list[RawItem] = []
        for b in blocks:
            if not b["title"] and not b["content"]:
                continue
            items.append(
                RawItem(
                    source_id=self._build_source_id(
                        resp.final_url or resp.url,
                        {"seed": b["seed"], "platform": "gov"},
                    ),
                    source_url=resp.final_url or resp.url or "",
                    title=b["title"] or (b["content"] or "")[:80],
                    author=b["author"],
                    published_at=b["published_at"],
                    content=b["content"],
                    tags=["gov", "procurement"],
                    extra={"platform": "gov", "kind": b["kind"]},
                )
            )
        if not items:
            info = extract_basic_html(resp.text or "")
            if info["title"] or info["text_body"]:
                items.append(
                    RawItem(
                        source_id="",
                        source_url=resp.final_url or resp.url or "",
                        title=info["title"] or (info["text_body"] or "")[:80],
                        author=info["author"],
                        published_at=extract_published_at(resp.text or ""),
                        content=info["text_body"],
                        tags=["gov", "procurement", "page"],
                    )
                )
        return items


# =====================
# 公共资源交易
# =====================


class PublicResourceSpider(BaseSpider):
    name = "public_resource"

    def _generate_from_seeds(self, params: SpiderTaskParams) -> list[str]:
        s_cfg = settings.spider
        if not s_cfg.SPIDER_CHANNEL_BID_GOV_ENABLED:
            return []
        template = s_cfg.SPIDER_PUBLIC_RESOURCE_TEMPLATE or ""
        urls: list[str] = []
        if template and "{keyword}" in template and params.keywords:
            for kw in params.keywords:
                urls.append(template.replace("{keyword}", kw))
        return urls[: params.max_pages or len(urls)]

    def parse(self, resp: CrawlResponse, params: SpiderTaskParams) -> list[RawItem]:
        blocks = extract_items(resp.text or "", max_items=params.max_items_per_url or 100)
        items: list[RawItem] = []
        for b in blocks:
            if not b["title"] and not b["content"]:
                continue
            items.append(
                RawItem(
                    source_id=self._build_source_id(
                        resp.final_url or resp.url,
                        {"seed": b["seed"], "platform": "public_resource"},
                    ),
                    source_url=resp.final_url or resp.url or "",
                    title=b["title"] or (b["content"] or "")[:80],
                    author=b["author"],
                    published_at=b["published_at"],
                    content=b["content"],
                    tags=["public_resource"],
                    extra={"platform": "public_resource", "kind": b["kind"]},
                )
            )
        if not items:
            info = extract_basic_html(resp.text or "")
            if info["title"] or info["text_body"]:
                items.append(
                    RawItem(
                        source_id="",
                        source_url=resp.final_url or resp.url or "",
                        title=info["title"] or (info["text_body"] or "")[:80],
                        author=info["author"],
                        published_at=extract_published_at(resp.text or ""),
                        content=info["text_body"],
                        tags=["public_resource", "page"],
                    )
                )
        return items


__all__ = ["BidNoticeSpider", "GovProcurementSpider", "PublicResourceSpider"]
