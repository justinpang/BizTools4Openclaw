"""business/customer_send/template_engine — {{变量}} 模板替换 + PIIMask 自动脱敏。"""

from __future__ import annotations

import os
import re
from typing import Any

from infra.logger_setup import get_logger
from configs.settings import settings

try:
    from core.compliance import pii_mask as _pii_mask  # type: ignore
    _HAS_PII = hasattr(_pii_mask, "auto_mask")
except Exception:
    _pii_mask = None
    _HAS_PII = False

logger = get_logger("customer_send.template_engine")


# 变量模式：{{var_name}} 支持下划线/短横线命名
_VAR_RE = re.compile(r"\{\{\s*([a-zA-Z0-9_-]+)\s*\}\}")

# 模板名到文件名映射
_TEMPLATE_FILES: dict[tuple[str, str], str] = {
    ("email", "default"): "email_default.html",
    ("wechat", "default"): "wechat_card.json",
    ("feishu", "default"): "feishu_card.json",
}


def _pii(text: str) -> str:
    """优先走 core.compliance.pii_mask.auto_mask；失败返回掩码后字符串。"""
    if not text:
        return ""
    if _HAS_PII and _pii_mask is not None:
        try:
            result = _pii_mask.auto_mask(text)
            if isinstance(result, dict):
                return str(result.get("masked", result.get("value", text[:3] + "***")))
            return str(result)
        except Exception:
            pass
    # 兜底：只保留首 2-4 字符
    if len(text) <= 4:
        return "***"
    return text[:4] + "***"


def build_variables(target: Any, *, h5_url: str | None = None) -> dict[str, str]:
    """从 SendTarget 构造模板变量字典；customer_name / contact_* 强制脱敏。"""

    def _safe(val: Any) -> str:
        if val is None:
            return "—"
        if isinstance(val, list):
            return ",".join(str(x) for x in val) if val else "—"
        return str(val)

    raw = {
        "customer_name": _pii(getattr(target, "customer_name", "") or ""),
        "contact_email": _pii(getattr(target, "contact_email", "") or ""),
        "contact_phone": _pii(getattr(target, "contact_phone", "") or ""),
        "contact_wechat": _pii(getattr(target, "contact_wechat", "") or ""),
        "industry": _safe(getattr(target, "contact_industry", None)),
        "region": _safe(getattr(target, "contact_region", None)),
        "need_keywords_csv": _safe(getattr(target, "need_keywords", None)),
        "opportunity_id": _safe(getattr(target, "opportunity_id", "")),
        "opportunity_title": _safe(getattr(target, "opportunity_title", "")),
        "opportunity_score": _safe(getattr(target, "opportunity_score", 0)),
        "tenant_id": _safe(getattr(target, "tenant_id", "")),
        "h5_url": h5_url or "",
        "send_date": _today(),
    }
    return raw


def _today() -> str:
    try:
        from datetime import datetime, timezone
        return datetime.now(timezone.utc).strftime("%Y-%m-%d")
    except Exception:
        return ""


def render_from_string(template_str: str, variables: dict[str, str]) -> str:
    """字符串内的 {{key}} 替换；未知 key 渲染为 '—'。"""
    if not template_str:
        return ""

    def _sub(match: re.Match[str]) -> str:
        key = match.group(1)
        val = variables.get(key)
        if val is None or val == "":
            return "—"
        return str(val)

    return _VAR_RE.sub(_sub, template_str)


def render(
    channel: str,
    template_name: str,
    variables: dict[str, str],
) -> str:
    """从文件加载指定模板并渲染。若文件不存在则返回纯文本模板。"""
    filename = _TEMPLATE_FILES.get((channel.lower(), template_name.lower()))
    if not filename:
        # fallback：使用通用纯文本模板
        fallback = (
            "【{{opportunity_title}}】\n"
            "客户：{{customer_name}}｜行业：{{industry}}｜地区：{{region}}\n"
            "意向得分：{{opportunity_score}}｜需求：{{need_keywords_csv}}\n"
            "详情：{{h5_url}}\n"
            "商机 ID：{{opportunity_id}}｜{{send_date}}"
        )
        return render_from_string(fallback, variables)

    tpl_path = os.path.join(settings.customer_send.CUSTOMER_SEND_TEMPLATE_DIR, filename)
    try:
        with open(tpl_path, "r", encoding="utf-8") as f:
            tpl = f.read()
    except FileNotFoundError:
        logger.warning(f"模板文件不存在: {tpl_path}")
        return render_from_string(
            "【{{opportunity_title}}】客户：{{customer_name}}｜{{h5_url}}", variables
        )
    except Exception as exc:
        logger.warning(f"模板读取失败: {tpl_path} ({exc})")
        return render_from_string("【{{opportunity_title}}】{{customer_name}}", variables)
    return render_from_string(tpl, variables)


__all__ = [
    "render",
    "render_from_string",
    "build_variables",
]
