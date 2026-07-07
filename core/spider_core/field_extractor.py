"""core/spider_core/field_extractor — 字段提取引擎。

支持四种提取器：
  - css:    使用 BeautifulSoup 的 CSS 选择器（取 innerText 或指定属性）
  - xpath:  使用 lxml 的 XPath（缺失时降级为 CSS）
  - regex:  对整段文本执行正则匹配，取指定分组
  - text:   返回固定表达式（支持 {field} 引用其他已提取字段）

清洗流水线 cleaners（可组合、顺序执行）：
  - "strip_whitespace"        : 两端去空白
  - "normalize_space"         : 合并连续空白为单空格
  - "remove_extra_newlines"   : 合并多个 \\n 为一个
  - "remove_html_tags"        : 正则清除 <tag> / </tag>
  - "trim_to_length:2000"     : 截断到 N 字符
  - "replace:old:new"         : 简单文本替换
  - "to_uppercase" / "to_lowercase"
  - "normalize_date:%Y-%m-%d" : 尝试用 strptime 解析，按目标格式输出
  - "remove_pii"              : 触发 PII 脱敏（若 SPIDER_ENHANCED_PII_MASK=true）

默认对所有字段执行 strip_whitespace，由调用方追加其他 cleaners。
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from infra.logger_setup import get_logger
from core.spider_core.config import enhanced_config

try:
    from bs4 import BeautifulSoup
    _HAS_BS4 = True
except Exception:
    _HAS_BS4 = False

try:
    from lxml import html as _lxml_html  # type: ignore
    _HAS_LXML = True
except Exception:
    _HAS_LXML = False

logger = get_logger("spider.field_extractor")


# =========================================================================
# 提取结果
# =========================================================================

@dataclass
class ExtractedValue:
    raw: str = ""
    cleaned: str = ""
    matched: bool = False
    match_score: float = 0.0
    rule_name: str = ""
    details: Dict[str, Any] = field(default_factory=dict)


# =========================================================================
# 清洗流水线
# =========================================================================

_HTML_TAG_RE = re.compile(r"<[^>]+>")
_PHONE_RE = re.compile(r"(?:\+?86[-\s]?)?1[3-9]\d{9}")
_EMAIL_RE = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")
_ID_CARD_RE = re.compile(r"\d{17}[\dXx]")
_BANK_CARD_RE = re.compile(r"\b\d{16,19}\b")


def apply_cleaners(value: str, cleaners: Optional[List[str]]) -> str:
    if value is None:
        return ""
    result = str(value)
    for cleaner in cleaners or []:
        c = (cleaner or "").strip()
        if not c:
            continue
        try:
            result = _apply_one_cleaner(result, c)
        except Exception as exc:
            logger.warning(f"cleaner '{c}' 失败: {exc}")
    return result.strip()


def _apply_one_cleaner(value: str, cleaner: str) -> str:
    if cleaner == "strip_whitespace":
        return value.strip()
    if cleaner == "normalize_space":
        return re.sub(r"\s+", " ", value).strip()
    if cleaner == "remove_extra_newlines":
        return re.sub(r"\n{2,}", "\n", value).strip()
    if cleaner == "remove_html_tags":
        return _HTML_TAG_RE.sub(" ", value).strip()
    if cleaner.startswith("trim_to_length:"):
        try:
            n = int(cleaner.split(":", 1)[1])
            return value[:n]
        except (IndexError, ValueError):
            return value
    if cleaner.startswith("replace:"):
        parts = cleaner.split(":", 2)
        if len(parts) == 3:
            return value.replace(parts[1], parts[2])
        return value
    if cleaner == "to_uppercase":
        return value.upper()
    if cleaner == "to_lowercase":
        return value.lower()
    if cleaner.startswith("normalize_date:"):
        fmt = cleaner.split(":", 1)[1]
        return _normalize_date(value, fmt)
    if cleaner == "remove_pii":
        cfg = enhanced_config()
        if cfg.pii_mask:
            v = _PHONE_RE.sub("[PHONE]", value)
            v = _EMAIL_RE.sub("[EMAIL]", v)
            v = _ID_CARD_RE.sub("[ID_CARD]", v)
            v = _BANK_CARD_RE.sub("[BANK_CARD]", v)
            return v
        return value
    # 未知 cleaner：忽略并告警
    logger.warning(f"未知 cleaner: {cleaner}")
    return value


def _normalize_date(value: str, target_fmt: str) -> str:
    import datetime as _dt
    candidate_patterns = [
        "%Y-%m-%d", "%Y/%m/%d", "%Y.%m.%d", "%Y年%m月%d日",
        "%Y-%m-%d %H:%M", "%Y-%m-%d %H:%M:%S",
        "%Y/%m/%d %H:%M:%S", "%Y年%m月%d日 %H:%M",
        "%m-%d", "%m月%d日",
    ]
    for fmt in candidate_patterns:
        try:
            dt = _dt.datetime.strptime(value.strip(), fmt)
            if "%Y" not in target_fmt and "%Y" not in fmt:
                dt = dt.replace(year=_dt.datetime.now().year)
            return dt.strftime(target_fmt)
        except ValueError:
            continue
    # 正则兜底：仅替换分隔符
    m = re.search(r"(20\d{2}|19\d{2})[-/年.](0?[1-9]|1[0-2])[-/月.](0?[1-9]|[12]\d|3[01])", value)
    if m:
        try:
            y, mo, d = m.group(1), m.group(2), m.group(3)
            return f"{int(y):04d}-{int(mo):02d}-{int(d):02d}"
        except Exception:
            pass
    return value


# =========================================================================
# 四种提取器实现
# =========================================================================

def _extract_css(html: str, expression: str, attribute: Optional[str]) -> str:
    if not _HAS_BS4 or not html:
        return ""
    try:
        soup = BeautifulSoup(html, "html.parser")
        el = soup.select_one(expression)
        if el is None:
            return ""
        if attribute:
            return el.get(attribute, "") or ""
        return el.get_text(" ", strip=True)
    except Exception as exc:
        logger.warning(f"CSS 选择器执行失败 '{expression}': {exc}")
        return ""


def _extract_xpath(html: str, expression: str, attribute: Optional[str]) -> str:
    if not _HAS_LXML:
        # 降级为 CSS 选择器
        return _extract_css(html, expression.replace("//", "").replace("/", " > ").replace("@", ""),
                            attribute)
    try:
        tree = _lxml_html.fromstring(html)
        result = tree.xpath(expression)
        if result is None:
            return ""
        if isinstance(result, list):
            if not result:
                return ""
            first = result[0]
            if hasattr(first, "text_content"):
                if attribute:
                    return first.get(attribute, "") or ""
                return first.text_content() or ""
            return str(first)
        return str(result)
    except Exception as exc:
        logger.warning(f"XPath 执行失败 '{expression}': {exc}")
        return ""


def _extract_regex(text: str, expression: str, regex_group: int) -> str:
    try:
        m = re.search(expression, text)
        if not m:
            return ""
        if regex_group == 0:
            return m.group(0)
        if len(m.groups()) >= regex_group:
            return m.group(regex_group) or ""
        return ""
    except Exception as exc:
        logger.warning(f"regex 执行失败 '{expression}': {exc}")
        return ""


def _extract_text(expression: str, context: Dict[str, ExtractedValue]) -> str:
    # 支持 {field_name} 占位符引用已提取字段
    try:
        out = expression
        for k, v in context.items():
            out = out.replace("{" + k + "}", v.cleaned)
        # 未识别的 {xxx} 保留原样（非占位符场景）
        return out
    except Exception:
        return expression


# =========================================================================
# 主类
# =========================================================================

class FieldExtractor:
    """字段提取引擎。"""

    def __init__(self) -> None:
        pass

    # ------- single field -------

    def extract_from_element(
        self,
        html: str,
        rule: Any,  # FieldRule (避免循环 import，按鸭子类型调用)
        *,
        context: Optional[Dict[str, ExtractedValue]] = None,
    ) -> ExtractedValue:
        name = getattr(rule, "name", "")
        extractor = getattr(rule, "extractor", "css")
        expression = getattr(rule, "expression", "")
        attribute = getattr(rule, "attribute", None)
        regex_group = int(getattr(rule, "regex_group", 0) or 0)
        required = bool(getattr(rule, "required", False))
        default_value = getattr(rule, "default_value", None)
        cleaners = list(getattr(rule, "cleaners", []) or [])

        result = ExtractedValue(rule_name=name)

        # 提取原始值
        if extractor == "css":
            raw = _extract_css(html, expression, attribute)
        elif extractor == "xpath":
            raw = _extract_xpath(html, expression, attribute)
        elif extractor == "regex":
            raw = _extract_regex(html, expression, regex_group)
        elif extractor == "text":
            raw = _extract_text(expression, context or {})
        else:
            raw = ""

        result.raw = raw

        # default_value 兜底
        if not raw and default_value is not None:
            raw = str(default_value)
            result.raw = raw

        # 清洗
        result.cleaned = apply_cleaners(raw, cleaners)

        # 命中判定
        if result.cleaned:
            result.matched = True
            result.match_score = 1.0
        elif required:
            result.matched = False
            result.match_score = 0.0
            result.details["note"] = "required field not matched"
        else:
            result.matched = False
            result.match_score = 0.0

        # date_format 兜底（如果 cleaner 没写 normalize_date）
        date_format = getattr(rule, "date_format", None)
        if result.cleaned and date_format and "normalize_date:" not in " ".join(cleaners):
            result.cleaned = _normalize_date(result.cleaned, date_format)

        return result

    # ------- 批量提取 -------

    def extract(self, html: str, rules: List[Any]) -> Dict[str, ExtractedValue]:
        out: Dict[str, ExtractedValue] = {}
        # 先跑非 text 规则，再跑 text 规则（以便 text 引用其他字段）
        ordered = sorted(rules, key=lambda r: (getattr(r, "extractor", "") == "text"))
        for rule in ordered:
            name = getattr(rule, "name", "")
            if not name:
                continue
            out[name] = self.extract_from_element(html, rule, context=out)
        return out

    # ------- 便捷：提取为 plain dict -------

    def extract_as_dict(self, html: str, rules: List[Any]) -> Dict[str, str]:
        return {k: v.cleaned for k, v in self.extract(html, rules).items()}


# 模块级单例
_default_extractor = FieldExtractor()


def extract_fields(html: str, rules: List[Any]) -> Dict[str, ExtractedValue]:
    return _default_extractor.extract(html, rules)


__all__ = [
    "ExtractedValue",
    "FieldExtractor",
    "apply_cleaners",
    "extract_fields",
]
