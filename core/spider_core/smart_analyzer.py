"""core/spider_core/smart_analyzer — 页面智能识别引擎。

从 RenderedPage 的 HTML/DOM 中自动识别：
  1. 列表块（list blocks）
  2. 标题候选（titles）
  3. 发布时间候选（publish_times）
  4. 详情页链接候选（detail_links）
  5. 附件链接（attachment_links）
  6. 分页规则（pagination）

并基于识别结果输出推荐的采集规则 JSON（recommended_rules）。
"""

from __future__ import annotations

import re
import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from infra.logger_setup import get_logger
from core.spider_core.page_renderer import RenderedPage

try:
    from bs4 import BeautifulSoup, Tag
    _HAS_BS4 = True
except Exception:
    _HAS_BS4 = False

logger = get_logger("spider.smart_analyzer")


# =========================================================================
# 数据结构
# =========================================================================

@dataclass
class CandidateSelector:
    text: str
    selector: str = ""
    confidence: float = 0.0
    match_type: str = ""
    extra: Dict[str, Any] = field(default_factory=dict)


@dataclass
class ListBlock:
    selector: str
    item_count: int
    score: float
    sample_texts: List[str] = field(default_factory=list)


@dataclass
class AttachmentLink:
    url: str
    filename: str
    mime_hint: str
    text: str = ""


@dataclass
class PageAnalysis:
    page_url: str
    list_blocks: List[ListBlock] = field(default_factory=list)
    titles: List[CandidateSelector] = field(default_factory=list)
    publish_times: List[CandidateSelector] = field(default_factory=list)
    detail_links: List[CandidateSelector] = field(default_factory=list)
    attachment_links: List[AttachmentLink] = field(default_factory=list)
    pagination: Optional[Any] = None  # PaginationRule（循环 import 问题，使用时再构造）
    pagination_mode: str = "none"
    pagination_next_selector: Optional[str] = None
    pagination_page_param: Optional[str] = None
    pagination_max_pages: int = 0
    recommended_rules: Dict[str, Any] = field(default_factory=dict)
    confidence_score: float = 0.0


# =========================================================================
# 常量
# =========================================================================

_PDF_EXTS = {".pdf"}
_IMG_EXTS = {".jpg", ".jpeg", ".png", ".gif", ".bmp", ".webp", ".tif", ".tiff"}
_DOC_EXTS = {".doc", ".docx", ".xls", ".xlsx", ".ppt", ".pptx"}
_ARCHIVE_EXTS = {".zip", ".rar", ".7z"}

_DATE_PATTERNS = [
    re.compile(r"(20\d{2}|19\d{2})[-/年.]\s*(0?[1-9]|1[0-2])[-/月.]\s*(0?[1-9]|[12]\d|3[01])日?"),
    re.compile(r"(0?[1-9]|1[0-2])[-/月.]\s*(0?[1-9]|[12]\d|3[01])[日.]?"),
    re.compile(r"(20\d{2}|19\d{2})[-/年.]\s*(0?[1-9]|1[0-2])[-/月.]\s*(0?[1-9]|[12]\d|3[01])日?\s*([01]?\d|2[0-3])[:：]([0-5]\d)(:([0-5]\d))?"),
    re.compile(r"(\d+)\s*天前"),
    re.compile(r"(昨天|前天|今日|今天)"),
]

_NEXT_PAGE_TEXTS = ("下一页", "下一页 »", "next", "next page", ">", "»", "›", "next ›")
_PAGE_NUM_PARAMS = ("page", "p", "pageno", "pagenum", "start", "offset", "index", "pg")


# =========================================================================
# PageAnalyzer
# =========================================================================

class PageAnalyzer:
    """页面智能识别引擎。"""

    def analyze(self, page: RenderedPage) -> PageAnalysis:
        analysis = PageAnalysis(page_url=page.final_url or page.url)
        if not page.html:
            return analysis
        if not _HAS_BS4:
            logger.warning("BeautifulSoup4 未安装，页面识别将降级（仅链接级分析）")
            return _fallback_analyze(page, analysis)

        soup = BeautifulSoup(page.html, "html.parser")

        analysis.titles = list(self._detect_titles(soup, page))
        analysis.publish_times = list(self._detect_publish_times(soup, page))
        analysis.list_blocks = list(self._detect_list_blocks(soup))
        analysis.detail_links = list(self._detect_detail_links(soup, analysis.list_blocks))
        analysis.attachment_links = list(self._detect_attachment_links(page))
        pagination_info = self._detect_pagination(page)
        analysis.pagination_mode = pagination_info["mode"]
        analysis.pagination_next_selector = pagination_info["next_selector"]
        analysis.pagination_page_param = pagination_info["page_param"]
        analysis.pagination_max_pages = pagination_info["max_pages"]
        analysis.recommended_rules = _build_recommended_rules(analysis)

        # 总置信度 = 有识别结果的维度占比
        hit_dims = sum(1 for xs in [
            analysis.list_blocks, analysis.titles, analysis.publish_times,
            analysis.detail_links, analysis.attachment_links,
        ] if xs)
        analysis.confidence_score = round(hit_dims / 5, 3)
        return analysis

    # ------- 1) 列表块 -------

    def _detect_list_blocks(self, soup) -> List[ListBlock]:  # type: ignore[no-untyped-def]
        blocks: List[ListBlock] = []
        candidate_tags = ["ul", "ol", "div", "tbody", "section"]
        for tag in candidate_tags:
            for container in soup.find_all(tag):
                children = [c for c in container.children if isinstance(c, Tag)]
                if len(children) < 3:
                    continue
                # 结构相似度：子标签名是否一致或接近
                tag_names = [c.name for c in children if c.name]
                from collections import Counter
                if not tag_names:
                    continue
                common = Counter(tag_names).most_common(1)[0]
                tag_ratio = common[1] / len(tag_names)
                # 子元素中含 <a> 的比例
                link_children = sum(1 for c in children if c.find("a"))
                link_ratio = link_children / max(1, len(children))
                # 文本长度方差：列表项的文本长度通常相近
                texts = [c.get_text(" ", strip=True) for c in children]
                lengths = [len(t) for t in texts if t]
                if len(lengths) < 3:
                    continue
                avg = sum(lengths) / len(lengths)
                variance = sum((l - avg) ** 2 for l in lengths) / len(lengths)
                text_score = 1.0 / (1.0 + (variance / max(1.0, avg ** 2)))
                # 综合打分
                score = tag_ratio * 0.4 + link_ratio * 0.3 + text_score * 0.3
                if score < 0.35:
                    continue
                selector = _build_css_selector(container)
                blocks.append(ListBlock(
                    selector=selector,
                    item_count=len(children),
                    score=round(score, 3),
                    sample_texts=texts[:3],
                ))
        blocks.sort(key=lambda b: b.score, reverse=True)
        # 去重：去掉相互包含的块
        unique_blocks: List[ListBlock] = []
        for b in blocks:
            if not any(b.selector and u.selector and
                       b.selector != u.selector and
                       b.selector.startswith(u.selector) for u in unique_blocks):
                unique_blocks.append(b)
            if len(unique_blocks) >= 5:
                break
        return unique_blocks

    # ------- 2) 标题识别 -------

    def _detect_titles(self, soup, page: RenderedPage) -> List[CandidateSelector]:  # type: ignore[no-untyped-def]
        out: List[CandidateSelector] = []
        seen_texts: set = set()

        # h1~h6
        for level in range(1, 5):
            for el in soup.find_all(f"h{level}"):
                text = el.get_text(" ", strip=True)
                if not text or len(text) < 4 or len(text) > 300:
                    continue
                if text in seen_texts:
                    continue
                seen_texts.add(text)
                out.append(CandidateSelector(
                    text=text,
                    selector=_build_css_selector(el),
                    confidence=round(1.0 - level * 0.1, 2),
                    match_type=f"h{level}",
                ))

        # article / header / .title 块
        for sel in ["article header", "header h1", ".title", ".article-title", ".news-title"]:
            for el in soup.select(sel):
                text = el.get_text(" ", strip=True)
                if not text or text in seen_texts:
                    continue
                seen_texts.add(text)
                out.append(CandidateSelector(
                    text=text,
                    selector=sel,
                    confidence=0.55,
                    match_type="semantic",
                ))

        # <title>
        if page.title:
            out.append(CandidateSelector(
                text=page.title,
                selector="title",
                confidence=0.3,
                match_type="page_title",
            ))

        return out[:10]

    # ------- 3) 发布时间识别 -------

    def _detect_publish_times(self, soup, page: RenderedPage) -> List[CandidateSelector]:  # type: ignore[no-untyped-def]
        out: List[CandidateSelector] = []
        seen: set = set()

        # <time> 标签
        for el in soup.find_all("time"):
            text = (el.get_text(" ", strip=True) or el.get("datetime") or "").strip()
            if text and text not in seen and _looks_like_date(text):
                seen.add(text)
                out.append(CandidateSelector(
                    text=text,
                    selector=_build_css_selector(el),
                    confidence=0.9,
                    match_type="time_tag",
                ))

        # meta article:published_time
        meta_val = page.meta_tags.get("article:published_time") or page.meta_tags.get("pubDate")
        if meta_val:
            out.append(CandidateSelector(
                text=meta_val,
                selector="meta",
                confidence=0.85,
                match_type="meta_tag",
            ))

        # 文本正则扫描：取包含时间模式的最小块
        for el in soup.find_all(True):
            text = el.get_text(" ", strip=True)
            if not text or len(text) > 80:
                continue
            if not _looks_like_date(text):
                continue
            if text in seen:
                continue
            seen.add(text)
            out.append(CandidateSelector(
                text=text,
                selector=_build_css_selector(el),
                confidence=0.5,
                match_type="regex_text",
            ))
            if len(out) >= 8:
                break

        return out

    # ------- 4) 详情页链接 -------

    def _detect_detail_links(self, soup, list_blocks: List[ListBlock]) -> List[CandidateSelector]:  # type: ignore[no-untyped-def]
        out: List[CandidateSelector] = []
        seen: set = set()
        for block in list_blocks[:3]:
            try:
                items = soup.select(block.selector)
            except Exception:
                continue
            for item in items:
                a = item.find("a") if isinstance(item, Tag) else None
                if not a:
                    continue
                href = a.get("href") or ""
                text = a.get_text(" ", strip=True) or ""
                if not href or href in ("#", "javascript:void(0)"):
                    continue
                if href in seen:
                    continue
                seen.add(href)
                out.append(CandidateSelector(
                    text=text[:80],
                    selector="a",
                    confidence=round(block.score * 0.9, 3),
                    match_type="list_item_link",
                    extra={"href": href},
                ))
                if len(out) >= 20:
                    break
        return out

    # ------- 5) 附件链接识别 -------

    def _detect_attachment_links(self, page: RenderedPage) -> List[AttachmentLink]:
        out: List[AttachmentLink] = []
        seen_urls: set = set()
        links_src = page.links[:]
        # 回退：如果 page.links 未填充，尝试用 BeautifulSoup 从 HTML 解析
        if not links_src and _HAS_BS4 and page.html:
            try:
                from bs4 import BeautifulSoup
                soup = BeautifulSoup(page.html, "html.parser")
                for a in soup.find_all("a"):
                    links_src.append(type("Link", (), {"text": a.get_text(" ", strip=True), "href": a.get("href", "")})())
            except Exception:
                pass
        for link in links_src:
            href = getattr(link, "href", "") or ""
            text = getattr(link, "text", "") or ""
            if not href or href in ("#", "javascript:void(0)"):
                continue
            url_lower = href.lower()
            ext = ""
            for exts in (_PDF_EXTS, _IMG_EXTS, _DOC_EXTS, _ARCHIVE_EXTS):
                for e in exts:
                    if url_lower.endswith(e):
                        ext = e
                        break
                if ext:
                    break
            if not ext:
                continue
            if href in seen_urls:
                continue
            seen_urls.add(href)
            mime = "application/pdf" if ext in _PDF_EXTS else \
                   ("image" if ext in _IMG_EXTS else "application/octet-stream")
            filename = href.rsplit("/", 1)[-1].split("?", 1)[0]
            out.append(AttachmentLink(url=href, filename=filename, mime_hint=mime, text=text))
            if len(out) >= 30:
                break
        return out

    # ------- 6) 分页规则识别 -------

    def _detect_pagination(self, page: RenderedPage) -> Dict[str, Any]:
        info: Dict[str, Any] = {"mode": "none", "next_selector": None, "page_param": None, "max_pages": 0}

        if not _HAS_BS4:
            return info
        soup = BeautifulSoup(page.html, "html.parser")

        # A) next_button 模式
        for a in soup.find_all("a"):
            text = (a.get_text(" ", strip=True) or "").strip().lower()
            if not text:
                continue
            if text in _NEXT_PAGE_TEXTS or any(t in text for t in ["下一页", "next page", "next"]):
                info["mode"] = "next_button"
                info["next_selector"] = _build_css_selector(a)
                break

        # B) page_param 模式：从所有链接的 URL 参数中找页码相关的
        page_numbers: Dict[str, set] = {}
        for a in soup.find_all("a"):
            href = a.get("href") or ""
            if not href or "?" not in href:
                continue
            qs = href.split("?", 1)[1]
            for kv in qs.split("&"):
                if "=" not in kv:
                    continue
                k, v = kv.split("=", 1)
                k_lower = k.lower()
                if k_lower not in _PAGE_NUM_PARAMS:
                    continue
                try:
                    page_num = int(v)
                    page_numbers.setdefault(k, set()).add(page_num)
                except ValueError:
                    continue

        for param, values in page_numbers.items():
            if len(values) >= 2:
                info["mode"] = info["mode"] if info["mode"] != "none" else "page_param"
                info["page_param"] = param
                info["max_pages"] = max(info["max_pages"], max(values))
                break

        # 如果分页链接有文本页码（"1","2","3"...）
        if info["mode"] == "none":
            numeric_pages = []
            for a in soup.find_all("a"):
                text = a.get_text(" ", strip=True).strip()
                if text.isdigit() and int(text) <= 500:
                    numeric_pages.append(int(text))
            if len(numeric_pages) >= 2:
                info["mode"] = "page_param"
                info["max_pages"] = max(numeric_pages)
                # 尝试猜测页码参数名
                for a in soup.find_all("a"):
                    href = a.get("href") or ""
                    if "?" in href:
                        qs = href.split("?", 1)[1]
                        for kv in qs.split("&"):
                            if "=" in kv:
                                k, v = kv.split("=", 1)
                                if v.isdigit() and int(v) in numeric_pages:
                                    info["page_param"] = k
                                    break
                    if info["page_param"]:
                        break

        return info


# =========================================================================
# 辅助函数
# =========================================================================

def _looks_like_date(text: str) -> bool:
    for p in _DATE_PATTERNS:
        if p.search(text):
            return True
    return False


def _build_css_selector(el) -> str:  # type: ignore[no-untyped-def]
    """为一个 BeautifulSoup 元素构造简易 CSS 选择器（非唯一，但够用）。"""
    if not _HAS_BS4 or not hasattr(el, "name"):
        return ""
    parts: List[str] = []
    cur = el
    depth = 0
    while cur is not None and depth < 4:
        name = getattr(cur, "name", None)
        if not name:
            break
        part = name
        cls = cur.get("class")
        if cls:
            # 只取第一个类名（避免过度匹配）
            cls_str = cls[0] if isinstance(cls, list) else str(cls)
            if cls_str and len(cls_str) < 40 and " " not in cls_str:
                part += "." + cls_str
        else:
            id_attr = cur.get("id")
            if id_attr and len(id_attr) < 40:
                part += "#" + str(id_attr)
        parts.append(part)
        cur = cur.parent
        depth += 1
    if not parts:
        return ""
    return " > ".join(reversed(parts))


def _fallback_analyze(page: RenderedPage, analysis: PageAnalysis) -> PageAnalysis:
    """无 BeautifulSoup 时的降级分析：只处理链接列表。"""
    for link in page.links:
        href = link.href or ""
        if not href or href in ("#", "javascript:void(0)"):
            continue
        analysis.detail_links.append(CandidateSelector(
            text=(link.text or "")[:80],
            selector="a",
            confidence=0.3,
            match_type="fallback_link",
            extra={"href": href},
        ))
    # 附件链接
    for link in page.links:
        href = (link.href or "").lower()
        if any(href.endswith(e) for e in _PDF_EXTS | _IMG_EXTS | _DOC_EXTS):
            analysis.attachment_links.append(AttachmentLink(
                url=link.href or "",
                filename=(link.href or "").rsplit("/", 1)[-1],
                mime_hint="unknown",
                text=link.text or "",
            ))
    return analysis


def _build_recommended_rules(analysis: PageAnalysis) -> Dict[str, Any]:
    """基于识别结果构造推荐规则 JSON（仅参考，不强制）。"""
    first_list = analysis.list_blocks[0] if analysis.list_blocks else None
    first_title = analysis.titles[0] if analysis.titles else None
    first_time = analysis.publish_times[0] if analysis.publish_times else None

    list_rule: Dict[str, Any] = {
        "url_template": "{page_url}",
        "item_selector": first_list.selector if first_list else "ul > li",
        "link_selector": "a",
        "link_attribute": "href",
        "max_pages": max(1, analysis.pagination_max_pages) if analysis.pagination_max_pages else 5,
        "use_render": False,
    }
    pagination_rule: Dict[str, Any] = {
        "mode": analysis.pagination_mode,
        "next_selector": analysis.pagination_next_selector,
        "page_param_name": analysis.pagination_page_param,
        "max_pages": analysis.pagination_max_pages,
    }
    list_rule["pagination"] = pagination_rule if analysis.pagination_mode != "none" else None

    detail_fields: List[Dict[str, Any]] = []
    if first_title:
        detail_fields.append({
            "name": "title",
            "extractor": "css",
            "expression": first_title.selector or "h1",
            "required": True,
            "cleaners": ["strip_whitespace", "normalize_space"],
        })
    if first_time:
        detail_fields.append({
            "name": "publish_time",
            "extractor": "css",
            "expression": first_time.selector or "[class*='time']",
            "cleaners": ["strip_whitespace"],
            "date_format": "%Y-%m-%d",
        })
    detail_fields.append({
        "name": "content",
        "extractor": "css",
        "expression": "article, .content, [class*='article']",
        "cleaners": ["strip_whitespace", "remove_extra_newlines", "remove_html_tags"],
    })

    return {
        "rule_name": "auto_generated",
        "list_rule": list_rule,
        "detail_fields": detail_fields,
        "attachment_count": len(analysis.attachment_links),
        "confidence": analysis.confidence_score,
    }


# =========================================================================
# 便捷入口
# =========================================================================

def analyze_page(page: RenderedPage) -> PageAnalysis:
    return PageAnalyzer().analyze(page)


def analyze_html(html: str, url: str = "") -> PageAnalysis:
    from core.spider_core.page_renderer import _parse_html
    page = RenderedPage(url=url, final_url=url, html=html)
    _parse_html(html, page)  # 预解析填充 links/images/forms
    return analyze_page(page)


__all__ = [
    "CandidateSelector",
    "ListBlock",
    "AttachmentLink",
    "PageAnalysis",
    "PageAnalyzer",
    "analyze_page",
    "analyze_html",
]
