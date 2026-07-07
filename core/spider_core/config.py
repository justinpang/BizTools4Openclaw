"""core/spider_core/config — 增强能力开关与阈值配置。

所有配置通过 os.environ 读取，默认保守关闭，避免未安装依赖时产生 ImportError。
推荐在项目 .env 中按以下格式声明（不强制写入 .env.example，业务层按需配置）：

    SPIDER_ENHANCED_ENABLED=true
    SPIDER_ENHANCED_USE_RENDER=false
    SPIDER_ENHANCED_PDF_OCR_ENABLED=false
    SPIDER_ENHANCED_OCR_ENABLED=false
    SPIDER_ENHANCED_OCR_LANG=chi_sim+eng
    SPIDER_ENHANCED_OCR_BACKEND=tesseract
    SPIDER_ENHANCED_TESSERACT_PATH=
    SPIDER_ENHANCED_ATTACHMENT_MAX_MB=50
    SPIDER_ENHANCED_DEDUP_TTL_DAYS=7
    SPIDER_ENHANCED_MATCH_RATE_THRESHOLD=0.5
    SPIDER_ENHANCED_FAILURE_RATE_THRESHOLD=0.3
    SPIDER_ENHANCED_COMPLIANCE_CHECK=true
    SPIDER_ENHANCED_PII_MASK=true
"""

from __future__ import annotations

import os
from dataclasses import dataclass


def _env_bool(name: str, default: bool) -> bool:
    raw = os.environ.get(name, "").strip().lower()
    if raw in ("true", "1", "yes", "on"):
        return True
    if raw in ("false", "0", "no", "off", ""):
        return default if raw == "" else False
    return default


def _env_float(name: str, default: float) -> float:
    try:
        return float(os.environ.get(name, default))
    except (TypeError, ValueError):
        return default


def _env_int(name: str, default: int) -> int:
    try:
        return int(os.environ.get(name, default))
    except (TypeError, ValueError):
        return default


def _env_str(name: str, default: str) -> str:
    val = os.environ.get(name)
    if val is None or val == "":
        return default
    return val.strip()


@dataclass
class EnhancedConfig:
    """增强能力配置单例。所有字段均可读，修改需通过环境变量。"""

    enabled: bool
    use_render: bool
    pdf_ocr_enabled: bool
    ocr_enabled: bool
    ocr_lang: str
    ocr_backend: str
    tesseract_path: str
    attachment_max_mb: float
    dedup_ttl_days: int
    match_rate_threshold: float
    failure_rate_threshold: float
    compliance_check: bool
    pii_mask: bool

    @classmethod
    def from_env(cls) -> "EnhancedConfig":
        return cls(
            enabled=_env_bool("SPIDER_ENHANCED_ENABLED", False),
            use_render=_env_bool("SPIDER_ENHANCED_USE_RENDER", False),
            pdf_ocr_enabled=_env_bool("SPIDER_ENHANCED_PDF_OCR_ENABLED", False),
            ocr_enabled=_env_bool("SPIDER_ENHANCED_OCR_ENABLED", False),
            ocr_lang=_env_str("SPIDER_ENHANCED_OCR_LANG", "chi_sim+eng"),
            ocr_backend=_env_str("SPIDER_ENHANCED_OCR_BACKEND", "tesseract"),
            tesseract_path=_env_str("SPIDER_ENHANCED_TESSERACT_PATH", ""),
            attachment_max_mb=_env_float("SPIDER_ENHANCED_ATTACHMENT_MAX_MB", 50.0),
            dedup_ttl_days=_env_int("SPIDER_ENHANCED_DEDUP_TTL_DAYS", 7),
            match_rate_threshold=_env_float("SPIDER_ENHANCED_MATCH_RATE_THRESHOLD", 0.5),
            failure_rate_threshold=_env_float("SPIDER_ENHANCED_FAILURE_RATE_THRESHOLD", 0.3),
            compliance_check=_env_bool("SPIDER_ENHANCED_COMPLIANCE_CHECK", True),
            pii_mask=_env_bool("SPIDER_ENHANCED_PII_MASK", True),
        )


_config: EnhancedConfig | None = None


def enhanced_config() -> EnhancedConfig:
    """获取配置单例。"""
    global _config
    if _config is None:
        _config = EnhancedConfig.from_env()
    return _config


def reload_config() -> EnhancedConfig:
    """强制重读环境变量（主要用于测试场景）。"""
    global _config
    _config = EnhancedConfig.from_env()
    return _config


__all__ = ["EnhancedConfig", "enhanced_config", "reload_config"]
