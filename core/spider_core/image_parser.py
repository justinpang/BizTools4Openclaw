"""core/spider_core/image_parser — 图片 OCR 解析。

依赖策略：
  - 首选 pytesseract（需系统安装 tesseract 可执行 + chi_sim 语言包）
  - 其次 easyocr（纯 Python，首次需下载模型，可能较慢）
  - 两者都不可用时，返回 parse_status="partial"

开关：SPIDER_ENHANCED_OCR_ENABLED=true 才启用 OCR；关闭时仅返回空文本并告警。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import List

from infra.logger_setup import get_logger
from core.spider_core.config import enhanced_config

logger = get_logger("spider.image_parser")


@dataclass
class ImageResult:
    source_url: str = ""
    filename: str = ""
    mime_type: str = "image"
    file_size_bytes: int = 0
    text: str = ""
    tables: List[Any] = field(default_factory=list)
    ocr_applied: bool = False
    parse_status: str = "ok"
    error: str = ""
    elapsed_ms: int = 0


class ImageParser:
    """图片 OCR 解析器。"""

    def __init__(self) -> None:
        self._cfg = enhanced_config()
        self._ocr_backend = self._cfg.ocr_backend or "tesseract"

    def extract_text(self, image_bytes: bytes) -> str:
        if not self._cfg.ocr_enabled:
            return ""
        return self._do_ocr(image_bytes)

    def parse(self, image_bytes: bytes, *, filename: str = "", source_url: str = "") -> ImageResult:
        import time as _time
        start = _time.monotonic()
        result = ImageResult()
        result.filename = filename
        result.source_url = source_url
        result.file_size_bytes = len(image_bytes) if image_bytes else 0
        if self._cfg.ocr_enabled and image_bytes:
            try:
                result.text = self._do_ocr(image_bytes)
                result.ocr_applied = bool(result.text.strip())
                if not result.text.strip():
                    result.parse_status = "partial"
            except Exception as exc:
                result.error = str(exc)
                result.parse_status = "failed"
                logger.warning(f"图片 OCR 失败: {exc}")
        else:
            result.parse_status = "partial"
            if not self._cfg.ocr_enabled:
                result.error = "ocr disabled by config (SPIDER_ENHANCED_OCR_ENABLED=false)"
        result.elapsed_ms = int((_time.monotonic() - start) * 1000)
        return result

    def _do_ocr(self, image_bytes: bytes) -> str:
        lang = self._cfg.ocr_lang or "chi_sim+eng"

        # —— A) pytesseract ——
        if self._ocr_backend == "tesseract":
            try:
                import pytesseract  # type: ignore
                from PIL import Image as _PILImage  # type: ignore
                import io as _io
                if self._cfg.tesseract_path:
                    pytesseract.pytesseract.tesseract_cmd = self._cfg.tesseract_path
                img = _PILImage.open(_io.BytesIO(image_bytes))
                text = pytesseract.image_to_string(img, lang=lang.replace("+", "+"))
                return (text or "").strip()
            except ImportError:
                logger.info("pytesseract / Pillow 未安装，将尝试 easyocr")
            except Exception as exc:
                logger.warning(f"pytesseract OCR 失败: {exc}")

        # —— B) easyocr ——
        try:
            import easyocr  # type: ignore
            reader = easyocr.Reader([l for l in lang.replace("chi_sim", "ch_sim").split("+") if l], gpu=False)
            raw = reader.readtext(image_bytes, detail=0)
            return "\n".join([str(x).strip() for x in raw if x])
        except ImportError:
            logger.warning("easyocr 未安装，图片 OCR 不可用")
        except Exception as exc:
            logger.warning(f"easyocr 失败: {exc}")

        # —— C) 全部不可用 ——
        logger.warning("图片 OCR 无可用 backend（请安装 pytesseract 或 easyocr）")
        return ""


__all__ = ["ImageResult", "ImageParser"]
