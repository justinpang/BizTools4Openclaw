"""core/spider_core/pdf_parser — PDF 文本/表格提取。

依赖策略：
  - 首选 pdfplumber（文本+表格表现最佳）
  - 其次尝试 pymupdf (fitz)
  - 两者都缺失时，返回 parse_status="partial" 并告警
  - OCR 开关由 SPIDER_ENHANCED_PDF_OCR_ENABLED 控制（需安装图片解析依赖）

使用方式：
    parser = PdfParser()
    result = parser.parse(pdf_bytes)
    print(result.tables)      # List[ParsedTable]
    print(result.text[:200])  # 纯文本
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List

from infra.logger_setup import get_logger
from core.spider_core.config import enhanced_config

logger = get_logger("spider.pdf_parser")


@dataclass
class ParsedTable:
    page_index: int = 0
    row_count: int = 0
    column_count: int = 0
    headers: List[str] = field(default_factory=list)
    rows: List[List[str]] = field(default_factory=list)
    raw_markdown: str = ""
    confidence: float = 0.0


@dataclass
class ImageMeta:
    page_index: int = 0
    format: str = ""
    bytes_length: int = 0
    alt: str = ""


@dataclass
class PdfResult:
    source_url: str = ""
    filename: str = ""
    mime_type: str = "application/pdf"
    file_size_bytes: int = 0
    text: str = ""
    tables: List[ParsedTable] = field(default_factory=list)
    images: List[ImageMeta] = field(default_factory=list)
    fields: Dict[str, Any] = field(default_factory=dict)
    ocr_applied: bool = False
    parse_status: str = "ok"  # "ok" | "partial" | "failed"
    error: str = ""
    elapsed_ms: int = 0
    page_count: int = 0


class PdfParser:
    """PDF 解析器。"""

    def __init__(self) -> None:
        self._cfg = enhanced_config()

    # ---------- public ----------

    def extract_text(self, pdf_bytes: bytes, *, pages: Any = None) -> str:
        return self._do_extract(pdf_bytes, pages=pages).text

    def extract_tables(self, pdf_bytes: bytes) -> List[ParsedTable]:
        return self._do_extract(pdf_bytes).tables

    def extract_metadata(self, pdf_bytes: bytes) -> Dict[str, Any]:
        return self._do_extract(pdf_bytes).fields

    def parse(self, pdf_bytes: bytes, *, filename: str = "", source_url: str = "",
              ocr: bool = False) -> PdfResult:
        import time as _time
        start = _time.monotonic()
        result = self._do_extract(pdf_bytes, ocr=ocr)
        result.filename = filename
        result.source_url = source_url
        result.file_size_bytes = len(pdf_bytes) if pdf_bytes else 0
        result.elapsed_ms = int((_time.monotonic() - start) * 1000)
        return result

    # ---------- internal ----------

    def _do_extract(self, pdf_bytes: bytes, *, pages: Any = None, ocr: bool = False) -> PdfResult:
        result = PdfResult()
        if not pdf_bytes:
            result.parse_status = "failed"
            result.error = "empty pdf bytes"
            return result

        # —— 方案 A：pdfplumber ——
        try:
            import pdfplumber  # type: ignore
            import io as _io
            with pdfplumber.open(_io.BytesIO(pdf_bytes)) as pdf:
                page_count = len(pdf.pages)
                result.page_count = page_count
                texts: List[str] = []
                for i, page in enumerate(pdf.pages):
                    if pages is not None and i not in (pages if isinstance(pages, (list, tuple)) else [pages]):
                        continue
                    try:
                        page_text = page.extract_text() or ""
                        texts.append(page_text)
                        if not page_text.strip() and ocr and self._cfg.pdf_ocr_enabled:
                            ocr_text = self._ocr_page(page)
                            if ocr_text:
                                texts.append(ocr_text)
                                result.ocr_applied = True
                    except Exception as exc:
                        logger.warning(f"pdf 第 {i} 页提取失败: {exc}")
                        result.parse_status = "partial"
                result.text = "\n\n".join([t for t in texts if t])

                # 表格
                for i, page in enumerate(pdf.pages):
                    try:
                        tables = page.extract_tables()
                        for table in tables or []:
                            if not table:
                                continue
                            pt = ParsedTable(
                                page_index=i,
                                row_count=len(table),
                                column_count=len(table[0]) if table else 0,
                                headers=[str(c).strip() if c else "" for c in (table[0] or [])],
                                rows=[[str(c).strip() if c else "" for c in row] for row in table[1:]],
                                confidence=0.8,
                            )
                            pt.raw_markdown = _table_to_markdown(pt.headers, pt.rows)
                            result.tables.append(pt)
                    except Exception as exc:
                        logger.warning(f"pdf 第 {i} 页表格提取失败: {exc}")

                # metadata
                try:
                    result.fields = dict(pdf.metadata or {})
                except Exception:
                    pass
                if not result.tables and not result.text.strip():
                    result.parse_status = "partial"
                return result
        except ImportError:
            pass
        except Exception as exc:
            logger.warning(f"pdfplumber 解析失败: {exc}")

        # —— 方案 B：pymupdf ——
        try:
            import fitz  # type: ignore
            import io as _io
            doc = fitz.open(stream=_io.BytesIO(pdf_bytes), filetype="pdf")
            result.page_count = doc.page_count
            texts: List[str] = []
            for i, page in enumerate(doc):
                try:
                    page_text = page.get_text("text")
                    texts.append(page_text)
                except Exception as exc:
                    logger.warning(f"pymupdf 第 {i} 页提取失败: {exc}")
            result.text = "\n\n".join([t for t in texts if t])
            try:
                result.fields = dict(doc.metadata or {})
            except Exception:
                pass
            doc.close()
            if not result.text.strip():
                result.parse_status = "partial"
            return result
        except ImportError:
            pass
        except Exception as exc:
            logger.warning(f"pymupdf 解析失败: {exc}")

        # —— 两者都不可用 ——
        result.parse_status = "failed"
        result.error = "no pdf backend available (need pdfplumber or pymupdf)"
        logger.warning(result.error)
        return result

    def _ocr_page(self, page) -> str:  # type: ignore[no-untyped-def]
        """对扫描版页执行 OCR（可选路径）。"""
        try:
            img_bytes = page.to_image().original.convert("RGB")  # type: ignore
            import io as _io
            buf = _io.BytesIO()
            img_bytes.save(buf, format="PNG")
            from core.spider_core.image_parser import ImageParser
            return ImageParser().extract_text(buf.getvalue())
        except Exception as exc:
            logger.debug(f"pdf ocr 失败: {exc}")
            return ""


def _table_to_markdown(headers: List[str], rows: List[List[str]]) -> str:
    if not rows and not headers:
        return ""
    lines: List[str] = []
    lines.append("| " + " | ".join(headers or [f"col{i}" for i in range(len(rows[0]) if rows else 1)]) + " |")
    cols = len(rows[0]) if rows else len(headers or [])
    lines.append("| " + " | ".join(["---"] * cols) + " |")
    for row in rows:
        lines.append("| " + " | ".join(row) + " |")
    return "\n".join(lines)


__all__ = ["ParsedTable", "ImageMeta", "PdfResult", "PdfParser"]
