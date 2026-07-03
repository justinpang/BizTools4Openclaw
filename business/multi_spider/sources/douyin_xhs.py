from __future__ import annotations

from core.spider_core import CrawlResponse
from configs.settings import settings
from business.multi_spider.base import BaseSpider
from business.multi_spider.models import RawItem, SpiderTaskParams
from business.multi_spider.pipeline import extract_basic_html, extract_items, extract_published_at


# =====================
# 抖音作品
# =====================


class DouyinWorkSpider(BaseSpider):
    name = "douyin_work"

    def _generate_from_seeds(self, params: SpiderTaskParams) -> list[str]:
        s_cfg = settings.spider
        if not s_cfg.SPIDER_CHANNEL_DOUYIN_XHS_ENABLED:
            return []
        template = s_cfg.SPIDER_DOUYIN_SEARCH_TEMPLATE or ""
        urls: list[str] = []
        if template and "{keyword}" in template and params.keywords:
            for kw in params.keywords:
                urls.append(template.replace("{keyword}", kw))
        # 也允许直接通过 params.urls 传入（在 build_url_list 统一处理）
        return urls[: params.max_pages or len(urls)]

    def parse(self, resp: CrawlResponse, params: SpiderTaskParams) -> list[RawItem]:
        blocks = extract_items(resp.text or "", max_items=params.max_items_per_url or 100)
        items: list[RawItem] = []
        for b in blocks:
            if not b["title"] and not b["content"]:
                continue
            items.append(
                RawItem(
                    source_id=self._build_source_id(resp.final_url or resp.url, {"seed": b["seed"], "platform": "douyin"}),
                    source_url=resp.final_url or resp.url or "",
                    title=b["title"] or (b["content"] or "")[:80],
                    author=b["author"],
                    published_at=b["published_at"],
                    content=b["content"],
                    tags=["douyin", "work"],
                    extra={"platform": "douyin", "kind": b["kind"]},
                )
            )
        # 页面级回退：整个页面作为一条作品
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
                        tags=["douyin", "work", "page"],
                    )
                )
        return items


# =====================
# 抖音评论
# =====================


class DouyinCommentSpider(BaseSpider):
    name = "douyin_comment"

    def _generate_from_seeds(self, params: SpiderTaskParams) -> list[str]:
        return DouyinWorkSpider()._generate_from_seeds(params)

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
                        {"seed": b["seed"], "platform": "douyin", "type": "comment"},
                    ),
                    source_url=resp.final_url or resp.url or "",
                    title=b["title"] or (b["content"] or "")[:60],
                    author=b["author"],
                    published_at=b["published_at"],
                    content=b["content"],
                    tags=["douyin", "comment"],
                    extra={"platform": "douyin", "kind": b["kind"]},
                )
            )
        return items


# =====================
# 小红书笔记
# =====================


class XhsNoteSpider(BaseSpider):
    name = "xhs_note"

    def _generate_from_seeds(self, params: SpiderTaskParams) -> list[str]:
        s_cfg = settings.spider
        if not s_cfg.SPIDER_CHANNEL_DOUYIN_XHS_ENABLED:
            return []
        template = s_cfg.SPIDER_XHS_SEARCH_TEMPLATE or ""
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
                    source_id=self._build_source_id(resp.final_url or resp.url, {"seed": b["seed"], "platform": "xhs"}),
                    source_url=resp.final_url or resp.url or "",
                    title=b["title"] or (b["content"] or "")[:80],
                    author=b["author"],
                    published_at=b["published_at"],
                    content=b["content"],
                    tags=["xhs", "note"],
                    extra={"platform": "xhs", "kind": b["kind"]},
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
                        tags=["xhs", "note", "page"],
                    )
                )
        return items


# =====================
# 小红书评论
# =====================


class XhsCommentSpider(BaseSpider):
    name = "xhs_comment"

    def _generate_from_seeds(self, params: SpiderTaskParams) -> list[str]:
        return XhsNoteSpider()._generate_from_seeds(params)

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
                        {"seed": b["seed"], "platform": "xhs", "type": "comment"},
                    ),
                    source_url=resp.final_url or resp.url or "",
                    title=b["title"] or (b["content"] or "")[:60],
                    author=b["author"],
                    published_at=b["published_at"],
                    content=b["content"],
                    tags=["xhs", "comment"],
                    extra={"platform": "xhs", "kind": b["kind"]},
                )
            )
        return items


__all__ = ["DouyinWorkSpider", "DouyinCommentSpider", "XhsNoteSpider", "XhsCommentSpider"]
