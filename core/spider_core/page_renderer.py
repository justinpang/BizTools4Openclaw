"""core/spider_core/page_renderer — 页面智能渲染器。

复用 spider_core.sdk.SpiderSDK 的 get(render=...) 能力拉取 HTML，
再对 HTML 进行统一 DOM 解析，产出 links/images/forms/interactive_elements
等结构化元数据，供 smart_analyzer 进一步识别。

解析层默认使用 beautifulsoup4（如缺失则降级为标准库 html.parser），
对渲染层默认不启用 JS（由上层规则控制 use_render 开关）。
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Dict, List, Optional

from infra.logger_setup import get_logger

try:  # BeautifulSoup 是首选解析器
    from bs4 import BeautifulSoup
    _HAS_BS4 = True
except Exception:  # pragma: no cover
    _HAS_BS4 = False


logger = get_logger("spider.page_renderer")


# =========================================================================
# 数据结构
# =========================================================================

@dataclass
class Link:
    text: str = ""
    href: str = ""
    attrs: Dict[str, str] = field(default_factory=dict)


@dataclass
class Image:
    src: str = ""
    alt: str = ""
    attrs: Dict[str, str] = field(default_factory=dict)


@dataclass
class Form:
    action: str = ""
    method: str = "get"
    fields: List[Dict[str, str]] = field(default_factory=list)


@dataclass
class InteractiveElement:
    tag: str = ""
    text: str = ""
    attrs: Dict[str, str] = field(default_factory=dict)


@dataclass
class RenderedPage:
    url: str = ""
    final_url: str = ""
    html: str = ""
    title: str = ""
    links: List[Link] = field(default_factory=list)
    images: List[Image] = field(default_factory=list)
    forms: List[Form] = field(default_factory=list)
    interactive_elements: List[InteractiveElement] = field(default_factory=list)
    meta_tags: Dict[str, str] = field(default_factory=dict)
    status_code: int = 0
    elapsed_ms: int = 0
    error: Optional[str] = None

    # —— helpers ——

    def all_text(self) -> str:
        if self.html:
            try:
                if _HAS_BS4:
                    return BeautifulSoup(self.html, "html.parser").get_text(" ", strip=True)
            except Exception:
                pass
        return ""


# =========================================================================
# 解析函数
# =========================================================================

def _parse_html(html: str, page: RenderedPage) -> None:
    if not html:
        return
    try:
        if _HAS_BS4:
            soup = BeautifulSoup(html, "html.parser")
        else:
            from html.parser import HTMLParser  # 标准库兜底

            class _MinimalParser(HTMLParser):
                def __init__(self) -> None:
                    super().__init__()
                    self._title: List[str] = []
                    self._links: List[Link] = []
                    self._images: List[Image] = []
                    self._in_title = False
                    self._meta: Dict[str, str] = {}

                def handle_starttag(self, tag: str, attrs_list) -> None:  # type: ignore[override]
                    attrs = {str(k): str(v) for k, v in (attrs_list or [])}
                    if tag == "title":
                        self._in_title = True
                    elif tag == "a":
                        self._links.append(Link(text="", href=attrs.get("href", ""), attrs=attrs))
                    elif tag == "img":
                        self._images.append(Image(src=attrs.get("src", ""), alt=attrs.get("alt", ""), attrs=attrs))
                    elif tag == "meta":
                        name = attrs.get("name") or attrs.get("property") or ""
                        content = attrs.get("content", "")
                        if name:
                            self._meta[name] = content

                def handle_data(self, data: str) -> None:  # type: ignore[override]
                    if self._in_title and data:
                        self._title.append(data)

                def handle_endtag(self, tag: str) -> None:  # type: ignore[override]
                    if tag == "title":
                        self._in_title = False

            parser = _MinimalParser()
            parser.feed(html)
            page.title = "".join(parser._title).strip()
            page.links = parser._links
            page.images = parser._images
            page.meta_tags = parser._meta
            return

        # BeautifulSoup 路径
        title_el = soup.find("title")
        page.title = title_el.get_text(strip=True) if title_el else ""

        # <meta> tags
        for meta in soup.find_all("meta"):
            name = meta.get("name") or meta.get("property") or ""
            content = meta.get("content", "")
            if name:
                page.meta_tags[name] = content

        # <a> 链接
        for a in soup.find_all("a"):
            attrs = {str(k): str(v) for k, v in a.attrs.items()}
            page.links.append(Link(
                text=a.get_text(" ", strip=True),
                href=attrs.get("href", ""),
                attrs=attrs,
            ))

        # <iframe>/<embed>/<object> —— 嵌入式文档（PDF/Word/图片预览）
        for el in soup.find_all(["iframe", "embed", "object"]):
            el_name = el.name or ""
            attrs = {str(k): str(v) for k, v in el.attrs.items()}
            src = (attrs.get("src") or attrs.get("data") or "").strip()
            if not src:
                continue
            # 尝试识别 PDF.js 查看器并抽取真实 PDF 路径
            real_pdf = ""
            if "pdfjs" in src.lower() or "viewer" in src.lower():
                from urllib.parse import urlparse, parse_qs
                try:
                    parsed = urlparse(src)
                    qs = parse_qs(parsed.query)
                    for key in ("file", "src", "url"):
                        if key in qs and qs[key]:
                            real_pdf = qs[key][0]
                            break
                except Exception:
                    pass
            display_src = real_pdf or src
            # 识别文件类型给出可读文本
            ext = display_src.split("?")[0].split(".")[-1].lower() if "." in display_src else ""
            file_type = ext.upper() if ext in ("pdf", "doc", "docx", "xls", "xlsx", "ppt", "pptx", "zip", "rar", "txt") else (el_name.upper() + " 嵌入文档")
            page.links.append(Link(
                text=f"【{file_type}】附件 / 嵌入式文档 {('-' + display_src[-60:] if display_src else '')}",
                href=display_src,
                attrs=attrs,
            ))

        # <img> 图片
        for img in soup.find_all("img"):
            attrs = {str(k): str(v) for k, v in img.attrs.items()}
            page.images.append(Image(
                src=attrs.get("src", ""),
                alt=attrs.get("alt", ""),
                attrs=attrs,
            ))

        # <form> 表单
        for form in soup.find_all("form"):
            fields: List[Dict[str, str]] = []
            for inp in form.find_all(["input", "textarea", "select"]):
                fields.append({
                    "tag": inp.name or "",
                    "name": inp.get("name", ""),
                    "type": inp.get("type", ""),
                    "value": inp.get("value", ""),
                })
            page.forms.append(Form(
                action=form.get("action", ""),
                method=(form.get("method") or "get").lower(),
                fields=fields,
            ))

        # 交互元素：按钮/下拉 等
        for el in soup.find_all(["button", "select", "input"]):
            page.interactive_elements.append(InteractiveElement(
                tag=el.name or "",
                text=el.get_text(" ", strip=True),
                attrs={str(k): str(v) for k, v in el.attrs.items()},
            ))

    except Exception as exc:
        logger.warning(f"DOM 解析失败: {exc}")


# =========================================================================
# 主类
# =========================================================================

class SmartPageRenderer:
    """页面智能渲染 + DOM 解析。"""

    def __init__(self, sdk=None) -> None:
        if sdk is None:
            from core.spider_core.sdk import SpiderSDK
            sdk = SpiderSDK()
        self._sdk = sdk

    # ---------- public ----------

    def render(
        self,
        url: str,
        *,
        render: bool = False,
        render_js: bool = False,
        timeout: float = 45.0,
        wait_until: str = "networkidle",
        robot_check: bool = True,
        risk_check: bool = True,
        task_id: Optional[str] = None,
    ) -> RenderedPage:
        start = time.monotonic()
        page = RenderedPage(url=url)
        try:
            resp = self._sdk.get(
                url,
                render=render,
                render_js=render_js,
                render_wait_until=wait_until,
                render_timeout=timeout,
                timeout=timeout,
                robot_check=robot_check,
                risk_check=risk_check,
                task_id=task_id,
            )
            page.status_code = resp.status_code
            page.final_url = resp.final_url or url
            if resp.error:
                page.error = resp.error
            page.html = resp.text or ""
            _parse_html(page.html, page)
        except Exception as exc:
            page.error = str(exc)
            logger.warning(f"render 失败 {url}: {exc}")
        page.elapsed_ms = int((time.monotonic() - start) * 1000)
        return page

    def render_batch(self, urls: List[str], *, render_js: bool = False,
                     task_id: Optional[str] = None) -> List[RenderedPage]:
        out: List[RenderedPage] = []
        for u in urls:
            out.append(self.render(u, render_js=render_js, task_id=task_id))
        return out


# 模块级单例（延迟初始化，避免 import 时触发重依赖）
_default_renderer: Optional[SmartPageRenderer] = None


def get_renderer() -> SmartPageRenderer:
    global _default_renderer
    if _default_renderer is None:
        _default_renderer = SmartPageRenderer()
    return _default_renderer


def render_page(url: str, *, wait_ms: int = 8000, timeout: float = 45.0,
                 render_js: bool = True) -> Dict[str, Any]:
    """渲染单个 URL 页面并返回 dict（html / title / status_code / final_url）。

    专供 web_admin 可视化编辑器调用。默认启用 JS 渲染，以便支持
    由 JavaScript 动态生成的列表/表格等内容。
    """
    page = get_renderer().render(
        url,
        render=True,
        render_js=render_js,
        timeout=timeout,
        wait_until="networkidle",
        robot_check=False,
        risk_check=False,
    )
    return {
        "html": page.html or "",
        "title": page.title or "",
        "status_code": page.status_code or 0,
        "final_url": page.final_url or url,
        "links": [{"text": getattr(link, "text", ""),
                   "href": getattr(link, "href", "")}
                  for link in page.links[:200]],
        "error": page.error or "",
        "elapsed_ms": page.elapsed_ms,
    }


__all__ = [
    "Link",
    "Image",
    "Form",
    "InteractiveElement",
    "RenderedPage",
    "SmartPageRenderer",
    "get_renderer",
    "render_page",
]
