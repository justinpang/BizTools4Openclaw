"""core/spider_core/attachment_parser — 附件统一解析入口。

职责：
  1. 从 HTML 中按 CSS 选择器（或给定链接列表）提取附件 URL
  2. 下载附件内容（复用 SpiderSDK.get）
  3. 根据后缀 / MIME 自动分发到 PdfParser / ImageParser
  4. 汇总输出 AttachmentResult 列表

可配置项（来自 AttachmentRule 或 config）：
  - download_limit_mb：单文件最大 MB（超过跳过并告警）
  - max_attachments_per_page：每页最多解析数
"""

from __future__ import annotations

import os
import time
from dataclasses import dataclass, field
from typing import Any, List, Optional

from infra.logger_setup import get_logger
from core.spider_core.config import enhanced_config
from core.spider_core.page_renderer import RenderedPage

try:
    from bs4 import BeautifulSoup
    _HAS_BS4 = True
except Exception:
    _HAS_BS4 = False

logger = get_logger("spider.attachment")


@dataclass
class AttachmentResult:
    source_url: str = ""
    filename: str = ""
    mime_type: str = ""
    file_size_bytes: int = 0
    text: str = ""
    tables: List[Any] = field(default_factory=list)
    images: List[Any] = field(default_factory=list)
    fields: dict = field(default_factory=dict)
    ocr_applied: bool = False
    parse_status: str = "ok"
    error: str = ""
    elapsed_ms: int = 0


class AttachmentParser:
    """附件统一解析入口。"""

    def __init__(self, sdk=None, pdf_parser=None, image_parser=None) -> None:
        self._cfg = enhanced_config()
        if sdk is None:
            from core.spider_core.sdk import SpiderSDK
            sdk = SpiderSDK()
        self._sdk = sdk
        self._pdf = pdf_parser
        self._img = image_parser

    # ---------- helpers ----------

    def _pdf_parser(self):
        if self._pdf is None:
            from core.spider_core.pdf_parser import PdfParser
            self._pdf = PdfParser()
        return self._pdf

    def _image_parser(self):
        if self._img is None:
            from core.spider_core.image_parser import ImageParser
            self._img = ImageParser()
        return self._img

    def _guess_mime(self, url: str) -> str:
        lower = url.lower().split("?", 1)[0]
        if lower.endswith(".pdf"):
            return "application/pdf"
        if lower.endswith((".jpg", ".jpeg", ".png", ".gif", ".bmp", ".webp", ".tif", ".tiff")):
            return "image/*"
        if lower.endswith((".doc", ".docx")):
            return "application/msword"
        if lower.endswith((".xls", ".xlsx")):
            return "application/vnd.ms-excel"
        return "application/octet-stream"

    def _is_pdf(self, mime: str, url: str) -> bool:
        return mime == "application/pdf" or url.lower().endswith(".pdf")

    def _is_image(self, mime: str, url: str) -> bool:
        return mime.startswith("image") or url.lower().endswith(
            (".jpg", ".jpeg", ".png", ".gif", ".bmp", ".webp", ".tif", ".tiff"))

    def _filename(self, url: str) -> str:
        try:
            return os.path.basename(url.split("?", 1)[0]) or url
        except Exception:
            return url

    # ---------- public ----------

    def download(self, url: str, *, base_url: Optional[str] = None, task_id: Optional[str] = None) -> bytes:
        from urllib.parse import urljoin
        # 补全相对 URL
        if url and not url.startswith(("http://", "https://")) and base_url:
            try:
                url = urljoin(base_url, url)
            except Exception:
                pass
        resp = self._sdk.get(url, timeout=60.0, task_id=task_id, robot_check=False)
        if resp.error:
            raise RuntimeError(f"附件下载失败: {resp.error}")
        # content 优先；其次 text.encode
        if resp.content:
            return resp.content if isinstance(resp.content, bytes) else str(resp.content).encode("utf-8")
        return (resp.text or "").encode("utf-8")

    def parse(
        self,
        url: str,
        *,
        base_url: Optional[str] = None,
        filename: Optional[str] = None,
        mime_type: Optional[str] = None,
        task_id: Optional[str] = None,
    ) -> AttachmentResult:
        start = time.monotonic()
        # 记录原始 URL（可能是相对 URL），但下载时会用补全后的 URL
        out = AttachmentResult(source_url=url, filename=filename or self._filename(url))
        try:
            mime = mime_type or self._guess_mime(url)
            out.mime_type = mime

            # 下载（内部处理 base_url 补全）
            raw = self.download(url, base_url=base_url, task_id=task_id)
            out.file_size_bytes = len(raw)
            # 下载完成后，source_url 替换为实际下载的 URL（如果被补全了）
            if not url.startswith(("http://", "https://")) and base_url:
                from urllib.parse import urljoin
                try:
                    out.source_url = urljoin(base_url, url)
                except Exception:
                    pass
            max_bytes = int(self._cfg.attachment_max_mb * 1024 * 1024) if self._cfg.attachment_max_mb else 50 * 1024 * 1024
            if out.file_size_bytes > max_bytes:
                out.parse_status = "partial"
                out.error = f"附件超过 {max_bytes // (1024*1024)} MB，已跳过解析"
                logger.warning(out.error)
                return out

            # 按类型分发
            if self._is_pdf(mime, url):
                pdf_result = self._pdf_parser().parse(
                    raw,
                    filename=out.filename,
                    source_url=url,
                    ocr=self._cfg.pdf_ocr_enabled,
                )
                out.text = pdf_result.text
                out.tables = pdf_result.tables
                out.images = pdf_result.images
                out.fields = pdf_result.fields
                out.ocr_applied = pdf_result.ocr_applied
                out.parse_status = pdf_result.parse_status
                out.error = pdf_result.error
            elif self._is_image(mime, url):
                img_result = self._image_parser().parse(
                    raw, filename=out.filename, source_url=url
                )
                out.text = img_result.text
                out.ocr_applied = img_result.ocr_applied
                out.parse_status = img_result.parse_status
                out.error = img_result.error
            else:
                # 其他类型：暂不解析，仅记录
                out.parse_status = "partial"
                out.error = f"未支持的附件类型: {mime}"
        except Exception as exc:
            out.parse_status = "failed"
            out.error = str(exc)
            logger.warning(f"附件解析失败 {url}: {exc}")
        out.elapsed_ms = int((time.monotonic() - start) * 1000)
        return out

    def parse_batch(
        self,
        urls: List[str],
        *,
        max_items: int = 10,
        task_id: Optional[str] = None,
    ) -> List[AttachmentResult]:
        results: List[AttachmentResult] = []
        for i, url in enumerate(urls):
            if i >= max_items:
                break
            if not url:
                continue
            results.append(self.parse(url, task_id=task_id))
        return results

    # ---------- 从 HTML / RenderedPage 提取链接 ----------

    def extract_links_from_page(
        self,
        page: RenderedPage,
        *,
        selector: str = "a",
        link_attribute: str = "href",
    ) -> List[str]:
        """从已渲染页面提取附件链接。"""
        out: List[str] = []
        if not page.html:
            return out
        if not _HAS_BS4:
            # 降级：从 page.links 中过滤有后缀的
            for link in page.links:
                href = link.href or ""
                lower = href.lower().split("?", 1)[0]
                if any(lower.endswith(ext) for ext in [".pdf", ".jpg", ".jpeg", ".png", ".doc", ".docx"]):
                    out.append(href)
            return out

        try:
            soup = BeautifulSoup(page.html, "html.parser")
            for el in soup.select(selector):
                href = el.get(link_attribute) or ""
                if not href or href in ("#", "javascript:void(0)"):
                    continue
                lower = href.lower().split("?", 1)[0]
                if any(lower.endswith(ext) for ext in [".pdf", ".jpg", ".jpeg", ".png",
                                                        ".gif", ".doc", ".docx", ".xls", ".xlsx"]):
                    out.append(href)
        except Exception as exc:
            logger.warning(f"extract_links_from_page 失败: {exc}")
        return out


# 模块级单例
_default_parser: Optional[AttachmentParser] = None


def get_attachment_parser() -> AttachmentParser:
    global _default_parser
    if _default_parser is None:
        _default_parser = AttachmentParser()
    return _default_parser


__all__ = ["AttachmentResult", "AttachmentParser", "get_attachment_parser"]
