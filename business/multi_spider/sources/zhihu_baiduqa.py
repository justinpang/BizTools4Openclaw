from __future__ import annotations

from core.spider_core import CrawlResponse
from configs.settings import settings
from business.multi_spider.base import BaseSpider
from business.multi_spider.models import RawItem, SpiderTaskParams
from business.multi_spider.pipeline import extract_basic_html, extract_items, extract_published_at


# =====================
# 知乎问题
# =====================


class ZhihuQuestionSpider(BaseSpider):
    name = "zhihu_question"

    def _generate_from_seeds(self, params: SpiderTaskParams) -> list[str]:
        s_cfg = settings.spider
        if not s_cfg.SPIDER_CHANNEL_ZHIHU_BAIDU_ENABLED:
            return []
        template = s_cfg.SPIDER_ZHIHU_SEARCH_TEMPLATE or ""
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
                        {"seed": b["seed"], "platform": "zhihu", "type": "question"},
                    ),
                    source_url=resp.final_url or resp.url or "",
                    title=b["title"] or (b["content"] or "")[:80],
                    author=b["author"],
                    published_at=b["published_at"],
                    content=b["content"],
                    tags=["zhihu", "question"],
                    extra={"platform": "zhihu", "kind": b["kind"]},
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
                        tags=["zhihu", "question", "page"],
                    )
                )
        return items


# =====================
# 知乎回答
# =====================


class ZhihuAnswerSpider(BaseSpider):
    name = "zhihu_answer"

    def _generate_from_seeds(self, params: SpiderTaskParams) -> list[str]:
        return ZhihuQuestionSpider()._generate_from_seeds(params)

    def parse(self, resp: CrawlResponse, params: SpiderTaskParams) -> list[RawItem]:
        blocks = extract_items(resp.text or "", max_items=params.max_items_per_url or 100)
        items: list[RawItem] = []
        for b in blocks:
            if not b["content"]:
                continue
            items.append(
                RawItem(
                    source_id=self._build_source_id(
                        resp.final_url or resp.url,
                        {"seed": b["seed"], "platform": "zhihu", "type": "answer"},
                    ),
                    source_url=resp.final_url or resp.url or "",
                    title=b["title"] or (b["content"] or "")[:60],
                    author=b["author"],
                    published_at=b["published_at"],
                    content=b["content"],
                    tags=["zhihu", "answer"],
                    extra={"platform": "zhihu", "kind": b["kind"]},
                )
            )
        return items


# =====================
# 百度知道
# =====================


class BaiduQASpider(BaseSpider):
    name = "baidu_qa"

    def _generate_from_seeds(self, params: SpiderTaskParams) -> list[str]:
        s_cfg = settings.spider
        if not s_cfg.SPIDER_CHANNEL_ZHIHU_BAIDU_ENABLED:
            return []
        template = s_cfg.SPIDER_BAIDU_QA_TEMPLATE or ""
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
                        {"seed": b["seed"], "platform": "baidu_qa"},
                    ),
                    source_url=resp.final_url or resp.url or "",
                    title=b["title"] or (b["content"] or "")[:80],
                    author=b["author"],
                    published_at=b["published_at"],
                    content=b["content"],
                    tags=["baidu", "qa"],
                    extra={"platform": "baidu_qa", "kind": b["kind"]},
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
                        tags=["baidu", "qa", "page"],
                    )
                )
        return items


__all__ = ["ZhihuQuestionSpider", "ZhihuAnswerSpider", "BaiduQASpider"]
