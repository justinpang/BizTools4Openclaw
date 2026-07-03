from __future__ import annotations

import re
from html.parser import HTMLParser
from typing import Any

from infra.logger_setup import get_logger

logger = get_logger("multi_spider.pipeline")


# =====================
# 轻量级 HTML 提取器（不依赖第三方库）
# =====================


class _TextExtractor(HTMLParser):
    """提取页面文本 + title + 若干元字段。"""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self._in_title = False
        self.title = ""
        self._in_author: set[str] = set()
        self.author = ""
        self._in_body = False
        self._fragments: list[str] = []
        self._skip_tag = {"script", "style", "noscript", "nav", "aside"}
        self._current_skip: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        tag = tag.lower()
        attrs_dict = {k.lower(): (v or "") for k, v in attrs}
        if tag in self._skip_tag:
            self._current_skip.append(tag)
            return
        if tag == "title":
            self._in_title = True
        if tag == "body" or tag == "article":
            self._in_body = True
        # class="author" / id="author" / itemprop="author" / class="comment-item" 等自动采集
        cls = attrs_dict.get("class", "")
        mid = attrs_dict.get("id", "")
        itemprop = attrs_dict.get("itemprop", "")
        if "author" in cls + " " + mid + " " + itemprop:
            self._in_author.add(tag)

    def handle_endtag(self, tag: str) -> None:
        tag = tag.lower()
        if tag in self._skip_tag and self._current_skip and self._current_skip[-1] == tag:
            self._current_skip.pop()
        if tag == "title":
            self._in_title = False
        if tag in self._in_author:
            self._in_author.discard(tag)

    def handle_data(self, data: str) -> None:
        if self._current_skip:
            return
        data = (data or "").strip()
        if not data:
            return
        if self._in_title:
            self.title = data
        if self._in_author:
            self.author = (self.author + " " + data).strip()
        if self._in_body or not self.title:
            self._fragments.append(data)

    def text(self) -> str:
        return "\n".join(self._fragments)


def extract_basic_html(html: str) -> dict[str, Any]:
    """从 HTML 中提取 {title, author, text_body}。失败时返回空字段。"""
    if not html:
        return {"title": "", "author": "", "text_body": ""}
    try:
        parser = _TextExtractor()
        parser.feed(html)
        return {
            "title": parser.title.strip(),
            "author": parser.author.strip(),
            "text_body": parser.text().strip(),
        }
    except Exception as exc:
        logger.warning(f"HTML 解析异常: {exc}")
        # 回退：用简单正则抓 <title>
        m = re.search(r"<title[^>]*>([^<]+)</title>", html, flags=re.IGNORECASE)
        title = m.group(1).strip() if m else ""
        # 去所有标签得到 text_body
        text_body = re.sub(r"<[^>]+>", " ", html or "")
        text_body = re.sub(r"\s+", " ", text_body).strip()
        return {"title": title, "author": "", "text_body": text_body}


# 预编译正则：提取帖子/评论时间（多种格式）
_PUBLISHED_AT_RE = [
    re.compile(r"(\d{4}-\d{1,2}-\d{1,2}[ T]\d{1,2}:\d{2}(?::\d{2})?)"),
    re.compile(r"(\d{4}年\d{1,2}月\d{1,2}日)"),
    re.compile(r"(\d{1,2}-\d{1,2}\s+\d{1,2}:\d{2})"),
    re.compile(r"(\d+\s*(?:秒|分钟|小时|天|月|年)前)"),
]


def extract_published_at(text: str) -> str | None:
    if not text:
        return None
    for pat in _PUBLISHED_AT_RE:
        m = pat.search(text)
        if m:
            return m.group(1)
    return None


# 提取评论/帖子条目块（常见：<article>、<li>、class=comment-item 等）
_ITEM_HINT_RE = [
    (re.compile(r'<article[^>]*>(.*?)</article>', flags=re.IGNORECASE | re.DOTALL), "article"),
    (re.compile(r'<li[^>]*class="[^"]*comment[^"]*"[^>]*>(.*?)</li>', flags=re.IGNORECASE | re.DOTALL), "li.comment"),
    (re.compile(r'<div[^>]*class="[^"]*comment-item[^"]*"[^>]*>(.*?)</div>', flags=re.IGNORECASE | re.DOTALL), "div.comment-item"),
    (re.compile(r'<div[^>]*class="[^"]*post[^"]*"[^>]*>(.*?)</div>', flags=re.IGNORECASE | re.DOTALL), "div.post"),
]


def extract_items(html: str, max_items: int = 100) -> list[dict[str, Any]]:
    """从页面 HTML 中提取候选条目（仅做粗略分块，不依赖精确结构）。"""
    items: list[dict[str, Any]] = []
    if not html:
        return items
    for pat, kind in _ITEM_HINT_RE:
        for m in pat.finditer(html):
            block_html = m.group(1)
            info = extract_basic_html(block_html)
            if not info["title"] and not info["text_body"]:
                continue
            # 用块内摘要做 source_id 种子
            seed = (info["title"] or info["text_body"])[:120]
            items.append(
                {
                    "kind": kind,
                    "title": info["title"],
                    "author": info["author"],
                    "content": info["text_body"],
                    "published_at": extract_published_at(block_html),
                    "seed": seed,
                }
            )
            if len(items) >= max_items:
                return items
        if items:
            return items
    return items


__all__ = ["extract_basic_html", "extract_published_at", "extract_items"]
