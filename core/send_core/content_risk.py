from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import Any

from infra.logger_setup import get_logger

logger = get_logger("send_core.content_risk")


# ============================================================
# 数据类
# ============================================================


@dataclass
class RiskCheckResult:
    """风控检查结果。"""

    is_blocked: bool = False
    reasons: list[str] = field(default_factory=list)
    matches: list[str] = field(default_factory=list)
    masked_content: str = ""
    masked_recipient: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "is_blocked": self.is_blocked,
            "reasons": self.reasons,
            "matches": self.matches,
            "masked_content": self.masked_content,
            "masked_recipient": self.masked_recipient,
        }


# ============================================================
# ContentRisk 主类
# ============================================================


_MINIMUM_KEYWORDS = ["赌博", "色情", "枪支", "博彩", "返利", "兼职刷单"]


class ContentRisk:
    """内容风控校验器。

    步骤：
    1. 对接收人信息做 PII 脱敏（避免日志/告警泄露明文隐私）
    2. 校验正文是否命中 T06 SensitiveFilter 黑名单
    3. 校验正文是否命中自定义词库（SENDRISK_EXTRA_BANNED_WORDS_FILE）
    4. 可选调用 T06 ComplianceChecker.check_for_outbound
    """

    def __init__(
        self,
        *,
        pii_mask: Any = None,
        sensitive_filter: Any = None,
        compliance_checker: Any = None,
        extra_banned_file: str | None = None,
    ) -> None:
        # 惰性加载，避免 import 循环
        self._pii = pii_mask
        self._sf = sensitive_filter
        self._cc = compliance_checker
        self._extra_banned_file = extra_banned_file or os.environ.get("SENDRISK_EXTRA_BANNED_WORDS_FILE")
        self._extra_keywords: list[str] = []
        if self._extra_banned_file:
            self._load_extra_keywords()

    def _load_extra_keywords(self) -> None:
        try:
            if self._extra_banned_file and os.path.exists(self._extra_banned_file):
                with open(self._extra_banned_file, "r", encoding="utf-8") as f:
                    for line in f:
                        kw = line.strip()
                        if kw and not kw.startswith("#"):
                            self._extra_keywords.append(kw)
                logger.info(f"加载自定义黑名单词 {len(self._extra_keywords)} 条")
        except Exception as exc:
            logger.warning(f"加载自定义词库失败：{exc}")

    # ---------------- 工具 ----------------

    def _get_pii(self) -> Any:
        if self._pii is None:
            try:
                from core.compliance.pii_mask import pii_mask as p
                self._pii = p
            except Exception as exc:
                logger.warning(f"PIIMask 加载失败：{exc}")
        return self._pii

    def _get_sf(self) -> Any:
        if self._sf is None:
            try:
                from core.compliance.sensitive_filter import sensitive_filter as s
                self._sf = s
            except Exception as exc:
                logger.warning(f"SensitiveFilter 加载失败：{exc}")
        return self._sf

    def _get_cc(self) -> Any:
        if self._cc is None:
            try:
                from core.compliance.compliance_checker import compliance_checker as c
                self._cc = c
            except Exception as exc:
                logger.warning(f"ComplianceChecker 加载失败：{exc}")
        return self._cc

    # ---------------- 主 API ----------------

    def mask_recipient(self, recipient: Any) -> str:
        """接收人信息脱敏，用于日志与告警。"""
        text = str(recipient or "")
        pii = self._get_pii()
        if pii is not None and hasattr(pii, "auto_mask"):
            try:
                masked = pii.auto_mask(text)
                if isinstance(masked, dict):
                    return str(masked.get("masked", masked))
                return str(masked)
            except Exception as exc:
                logger.warning(f"PIIMask.auto_mask 失败：{exc}")
        # 兜底：保留少量首字母
        return text[:4] + "***" if len(text) > 4 else "***"

    def check_content(self, content: str, recipient: Any = None) -> RiskCheckResult:
        """完整风控检查。"""
        result = RiskCheckResult()
        content = content or ""
        # 1. 接收人脱敏（仅用于输出）
        result.masked_recipient = self.mask_recipient(recipient)

        # 2. 正文脱敏（输出端）
        pii = self._get_pii()
        try:
            if pii is not None and hasattr(pii, "auto_mask"):
                masked_c = pii.auto_mask(content)
                if isinstance(masked_c, dict):
                    result.masked_content = str(masked_c.get("masked", masked_c))
                else:
                    result.masked_content = str(masked_c)
            else:
                result.masked_content = content
        except Exception as exc:
            logger.warning(f"正文脱敏失败：{exc}")
            result.masked_content = content

        # 3. 敏感词过滤（T06 SensitiveFilter）
        sf = self._get_sf()
        if sf is not None and hasattr(sf, "is_blocked"):
            try:
                if bool(sf.is_blocked(content)):
                    result.is_blocked = True
                    result.reasons.append("sensitive_filter:blocked")
                    report = getattr(sf, "check", None)
                    if callable(report):
                        rep = report(content)
                        if isinstance(rep, dict) and rep.get("hits"):
                            for h in rep["hits"]:
                                result.matches.append(str(h))
            except Exception as exc:
                logger.warning(f"SensitiveFilter 异常：{exc}")
        # 最低保障：本地关键字兜底（避免合规工具加载失败时完全放行）
        if not result.is_blocked:
            lowered = content.lower()
            for kw in _MINIMUM_KEYWORDS:
                if kw.lower() in lowered:
                    result.is_blocked = True
                    result.reasons.append("minimum_keyword:" + kw)
                    result.matches.append(kw)
                    break

        # 4. 自定义词库
        if not result.is_blocked:
            for kw in self._extra_keywords:
                if kw and kw.lower() in (content or "").lower():
                    result.is_blocked = True
                    result.reasons.append("custom_keyword:" + kw)
                    result.matches.append(kw)
                    break

        # 5. T06 ComplianceChecker（可选）
        if not result.is_blocked:
            cc = self._get_cc()
            if cc is not None and hasattr(cc, "check_for_outbound"):
                try:
                    rep = cc.check_for_outbound(content, context={"layer": "send_core"})
                    blocked = False
                    if isinstance(rep, dict):
                        blocked = bool(rep.get("blocked"))
                        if rep.get("hits"):
                            result.matches.extend([str(h) for h in rep["hits"]][:5])
                    elif hasattr(rep, "blocked"):
                        blocked = bool(getattr(rep, "blocked"))
                    if blocked:
                        result.is_blocked = True
                        result.reasons.append("compliance_checker:blocked")
                except Exception as exc:
                    logger.warning(f"ComplianceChecker 异常：{exc}")

        if result.is_blocked:
            logger.info(f"[content_risk] BLOCKED reasons={result.reasons} matches={result.matches[:5]}")
        return result

    def is_blocked(self, content: str, recipient: Any = None) -> bool:
        """简化 API：只返回是否拦截。"""
        return self.check_content(content, recipient).is_blocked


# ============================================================
# 模块级单例
# ============================================================


def _build_default() -> ContentRisk:
    return ContentRisk()


content_risk: ContentRisk
try:
    content_risk = _build_default()
except Exception as exc:
    logger.warning(f"ContentRisk 默认实例初始化失败：{exc}")
    content_risk = ContentRisk()


__all__ = ["RiskCheckResult", "ContentRisk", "content_risk"]
