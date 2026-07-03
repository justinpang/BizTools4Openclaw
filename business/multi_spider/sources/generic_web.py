from __future__ import annotations

from typing import TYPE_CHECKING

from core.spider_core import CrawlResponse
from configs.settings import settings
from business.multi_spider.base import BaseSpider
from business.multi_spider.models import RawItem, SpiderTaskParams
from business.multi_spider.pipeline import extract_basic_html, extract_items, extract_published_at

if TYPE_CHECKING:
    pass


# =====================
# 通用网页/论坛文章
# =====================


class GenericWebArticleSpider(BaseSpider):
    """通用网页/论坛文章抓取。

    从 SPIDER_GENERIC_WEB_SEEDS / SPIDER_FORUM_SEEDS 读种子，
    或通过 params.keywords + params.urls 动态传入。
    """

    name = "generic_article"

    def _generate_from_seeds(self, params: SpiderTaskParams) -> list[str]:
        s_cfg = settings.spider
        if not s_cfg.SPIDER_CHANNEL_GENERIC_ENABLED:
            return []
        seeds: list[str] = []
        seeds.extend(s_cfg.split_csv(s_cfg.SPIDER_GENERIC_WEB_SEEDS))
        seeds.extend(s_cfg.split_csv(s_cfg.SPIDER_FORUM_SEEDS))
        if params.keywords:
            # 若外部传入关键词，作为附加种子（不作真实拼接 URL，
            # 具体平台模板在各渠道 spider 中实现）
            pass
        return seeds[: params.max_pages or len(seeds)]

    def parse(self, resp: CrawlResponse, params: SpiderTaskParams) -> list[RawItem]:
        info = extract_basic_html(resp.text or "")
        if not info["title"] and not info["text_body"]:
            return []
        # 整页作为一条文章
        item = RawItem(
            source_id="",  # 由基类通过 hash(url, title) 自动生成
            source_url=resp.final_url or resp.url or "",
            title=info["title"] or (info["text_body"] or "")[:60],
            author=info["author"],
            published_at=extract_published_at(resp.text or ""),
            content=info["text_body"],
            tags=["generic_article"],
            extra={"status_code": resp.status_code},
        )
        return [item]


# =====================
# 通用帖子/评论（抓取页面中可能的评论块）
# =====================


class GenericCommentSpider(BaseSpider):
    """通用帖子/评论抓取。"""

    name = "generic_comment"

    def _generate_from_seeds(self, params: SpiderTaskParams) -> list[str]:
        s_cfg = settings.spider
        if not s_cfg.SPIDER_CHANNEL_GENERIC_ENABLED:
            return []
        seeds: list[str] = []
        seeds.extend(s_cfg.split_csv(s_cfg.SPIDER_FORUM_SEEDS))
        seeds.extend(s_cfg.split_csv(s_cfg.SPIDER_GENERIC_WEB_SEEDS))
        return seeds[: params.max_pages or len(seeds)]

    def parse(self, resp: CrawlResponse, params: SpiderTaskParams) -> list[RawItem]:
        blocks = extract_items(resp.text or "", max_items=params.max_items_per_url or 100)
        items: list[RawItem] = []
        for b in blocks:
            content = b["content"]
            if not content and not b["title"]:
                continue
            items.append(
                RawItem(
                    source_id=self._build_source_id(resp.final_url or resp.url, {"seed": b["seed"]}),
                    source_url=resp.final_url or resp.url or "",
                    title=b["title"] or content[:80],
                    author=b["author"],
                    published_at=b["published_at"],
                    content=content,
                    tags=["generic_comment", b["kind"]],
                    extra={"kind": b["kind"]},
                )
            )
        return items


__all__ = ["GenericWebArticleSpider", "GenericCommentSpider"]
