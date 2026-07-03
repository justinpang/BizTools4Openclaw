from __future__ import annotations

from core.spider_core import CrawlResponse
from configs.settings import settings
from business.multi_spider.base import BaseSpider
from business.multi_spider.models import RawItem, SpiderTaskParams
from business.multi_spider.pipeline import extract_basic_html, extract_items, extract_published_at


# =====================
# 企查查 企业新增
# =====================


class QccNewCompanySpider(BaseSpider):
    name = "qcc_new_company"

    def _generate_from_seeds(self, params: SpiderTaskParams) -> list[str]:
        s_cfg = settings.spider
        if not s_cfg.SPIDER_CHANNEL_ENTERPRISE_ENABLED:
            return []
        template = s_cfg.SPIDER_QCC_SEARCH_TEMPLATE or ""
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
                        {"seed": b["seed"], "platform": "qcc", "type": "new_company"},
                    ),
                    source_url=resp.final_url or resp.url or "",
                    title=b["title"] or (b["content"] or "")[:80],
                    author=b["author"],
                    published_at=b["published_at"],
                    content=b["content"],
                    tags=["qcc", "company", "new"],
                    extra={"platform": "qcc", "kind": b["kind"]},
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
                        tags=["qcc", "company", "new", "page"],
                    )
                )
        return items


# =====================
# 企查查 变更事件
# =====================


class QccChangeEventSpider(BaseSpider):
    name = "qcc_change_event"

    def _generate_from_seeds(self, params: SpiderTaskParams) -> list[str]:
        return QccNewCompanySpider()._generate_from_seeds(params)

    def parse(self, resp: CrawlResponse, params: SpiderTaskParams) -> list[RawItem]:
        blocks = extract_items(resp.text or "", max_items=params.max_items_per_url or 100)
        items: list[RawItem] = []
        for b in blocks:
            if not b["content"] and not b["title"]:
                continue
            items.append(
                RawItem(
                    source_id=self._build_source_id(
                        resp.final_url or resp.url,
                        {"seed": b["seed"], "platform": "qcc", "type": "change"},
                    ),
                    source_url=resp.final_url or resp.url or "",
                    title=b["title"] or (b["content"] or "")[:60],
                    author=b["author"],
                    published_at=b["published_at"],
                    content=b["content"],
                    tags=["qcc", "change"],
                    extra={"platform": "qcc", "kind": b["kind"]},
                )
            )
        return items


# =====================
# 天眼查 招聘
# =====================


class TycJobSpider(BaseSpider):
    name = "tyc_job"

    def _generate_from_seeds(self, params: SpiderTaskParams) -> list[str]:
        s_cfg = settings.spider
        if not s_cfg.SPIDER_CHANNEL_ENTERPRISE_ENABLED:
            return []
        template = s_cfg.SPIDER_TYC_SEARCH_TEMPLATE or ""
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
                        {"seed": b["seed"], "platform": "tyc", "type": "job"},
                    ),
                    source_url=resp.final_url or resp.url or "",
                    title=b["title"] or (b["content"] or "")[:80],
                    author=b["author"],
                    published_at=b["published_at"],
                    content=b["content"],
                    tags=["tyc", "job"],
                    extra={"platform": "tyc", "kind": b["kind"]},
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
                        tags=["tyc", "job", "page"],
                    )
                )
        return items


__all__ = ["QccNewCompanySpider", "QccChangeEventSpider", "TycJobSpider"]
