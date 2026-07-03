from __future__ import annotations

from core.spider_core import CrawlResponse
from configs.settings import settings
from business.multi_spider.base import BaseSpider
from business.multi_spider.models import RawItem, SpiderTaskParams
from business.multi_spider.pipeline import extract_basic_html, extract_items, extract_published_at


# =====================
# 58 同城
# =====================


class Listing58Spider(BaseSpider):
    name = "58_listing"

    def _generate_from_seeds(self, params: SpiderTaskParams) -> list[str]:
        s_cfg = settings.spider
        if not s_cfg.SPIDER_CHANNEL_LOCAL_ENABLED:
            return []
        template = s_cfg.SPIDER_58_TEMPLATE or ""
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
                        {"seed": b["seed"], "platform": "58"},
                    ),
                    source_url=resp.final_url or resp.url or "",
                    title=b["title"] or (b["content"] or "")[:80],
                    author=b["author"],
                    published_at=b["published_at"],
                    content=b["content"],
                    tags=["58", "listing"],
                    extra={"platform": "58", "kind": b["kind"]},
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
                        tags=["58", "listing", "page"],
                    )
                )
        return items


# =====================
# 闲鱼
# =====================


class XianyuItemSpider(BaseSpider):
    name = "xianyu_item"

    def _generate_from_seeds(self, params: SpiderTaskParams) -> list[str]:
        s_cfg = settings.spider
        if not s_cfg.SPIDER_CHANNEL_LOCAL_ENABLED:
            return []
        template = s_cfg.SPIDER_XIANYU_TEMPLATE or ""
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
                        {"seed": b["seed"], "platform": "xianyu"},
                    ),
                    source_url=resp.final_url or resp.url or "",
                    title=b["title"] or (b["content"] or "")[:80],
                    author=b["author"],
                    published_at=b["published_at"],
                    content=b["content"],
                    tags=["xianyu"],
                    extra={"platform": "xianyu", "kind": b["kind"]},
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
                        tags=["xianyu", "page"],
                    )
                )
        return items


# =====================
# 本地生活供需
# =====================


class LocalNeedSpider(BaseSpider):
    name = "local_need"

    def _generate_from_seeds(self, params: SpiderTaskParams) -> list[str]:
        s_cfg = settings.spider
        if not s_cfg.SPIDER_CHANNEL_LOCAL_ENABLED:
            return []
        # 本地生活的种子没有专用模板字段，复用 FORUM_SEEDS
        urls: list[str] = list(s_cfg.split_csv(s_cfg.SPIDER_FORUM_SEEDS))
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
                        {"seed": b["seed"], "platform": "local"},
                    ),
                    source_url=resp.final_url or resp.url or "",
                    title=b["title"] or (b["content"] or "")[:80],
                    author=b["author"],
                    published_at=b["published_at"],
                    content=b["content"],
                    tags=["local", "need"],
                    extra={"platform": "local", "kind": b["kind"]},
                )
            )
        return items


__all__ = ["Listing58Spider", "XianyuItemSpider", "LocalNeedSpider"]
