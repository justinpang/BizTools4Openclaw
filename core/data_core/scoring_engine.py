from __future__ import annotations

import json
import math
import os
from dataclasses import dataclass, field
from typing import Any

from infra.logger_setup import get_logger

logger = get_logger("data_core.scoring")


# ============================================================
# 分级常量
# ============================================================

GRADE_HIGH = "HIGH_INTENT"
GRADE_NORMAL = "NORMAL"
GRADE_LOW = "LOW_INTENT"
GRADE_JUNK = "JUNK"


# ============================================================
# 数据类
# ============================================================


@dataclass
class ScoreResult:
    """单条线索的打分结果。"""
    score: float
    breakdown: dict[str, float]
    grade: str

    def to_dict(self) -> dict:
        return {"score": round(self.score, 2), "grade": self.grade, "breakdown": self.breakdown}


# ============================================================
# ScoringEngine 主类
# ============================================================


class ScoringEngine:
    """6 维度打分 + 分级。"""

    _WEIGHT_KEYS = (
        "SCORE_WEIGHT_TIMELINESS",
        "SCORE_WEIGHT_INDUSTRY",
        "SCORE_WEIGHT_INTENSITY",
        "SCORE_WEIGHT_CHANNEL",
        "SCORE_WEIGHT_QUALIFICATION",
        "SCORE_WEIGHT_COMPLETENESS",
    )

    def __init__(
        self,
        *,
        weights: dict[str, float] | None = None,
        timeliness_lambda: float | None = None,
        high_industries: list[str] | None = None,
        intensity_keywords: dict[str, list[str]] | None = None,
        channel_weights: dict[str, float] | None = None,
        high_quality: list[str] | None = None,
        grade_thresholds: dict[str, float] | None = None,
    ) -> None:
        # 权重
        default_weights = {
            "timeliness": _env_float("SCORE_WEIGHT_TIMELINESS", 0.20),
            "industry": _env_float("SCORE_WEIGHT_INDUSTRY", 0.15),
            "intensity": _env_float("SCORE_WEIGHT_INTENSITY", 0.25),
            "channel": _env_float("SCORE_WEIGHT_CHANNEL", 0.15),
            "qualification": _env_float("SCORE_WEIGHT_QUALIFICATION", 0.15),
            "completeness": _env_float("SCORE_WEIGHT_COMPLETENESS", 0.10),
        }
        if weights:
            for k, v in weights.items():
                default_weights[k] = float(v)
        self._weights = default_weights

        # 时效性
        self._timeliness_lambda = (
            float(timeliness_lambda) if timeliness_lambda is not None else _env_float(
                "SCORE_TIMELINESS_LAMBDA", 0.05
            )
        )

        # 高价值行业
        self._high_industries: set[str]
        if high_industries is not None:
            self._high_industries = {str(x).strip().lower() for x in high_industries if x}
        else:
            self._high_industries = set(_env_list_string("SCORE_HIGH_INDUSTRIES_JSON"))

        # 需求强度关键词
        if intensity_keywords is not None:
            self._intensity_keywords = {
                str(k): [str(x).strip().lower() for x in v if x]
                for k, v in intensity_keywords.items()
            }
        else:
            self._intensity_keywords = _env_dict_string_list("SCORE_INTENSITY_KEYWORDS_JSON", {
                "strong": ["急需", "立即", "加急", "紧急", "采购", "订购", "马上", "高价"],
                "medium": ["需要", "求购", "希望", "寻找", "了解", "咨询", "想找"],
                "weak": ["了解一下", "看看", "问问", "咨询下"],
            })

        # 渠道权重
        if channel_weights is not None:
            self._channel_weights = {str(k).strip().lower(): float(v) for k, v in channel_weights.items()}
        else:
            self._channel_weights = _env_dict_float("SCORE_CHANNEL_WEIGHTS_JSON", {
                "b2b": 0.9, "social": 0.7, "forum": 0.6, "other": 0.4,
            })

        # 高资质关键字
        if high_quality is not None:
            self._high_quality = [str(x).strip() for x in high_quality if x]
        else:
            self._high_quality = list(_env_list_string("SCORE_HIGH_QUALITY_JSON"))

        # 分级阈值
        default_thresholds = {
            "high": _env_float("GRADE_HIGH_THRESHOLD", 70.0),
            "normal": _env_float("GRADE_NORMAL_THRESHOLD", 40.0),
            "low": _env_float("GRADE_LOW_THRESHOLD", 20.0),
        }
        if grade_thresholds:
            for k, v in grade_thresholds.items():
                default_thresholds[k] = float(v)
        self._thresholds = default_thresholds

    # ---------------- 打分主 API ----------------

    def score_one(self, clue: dict[str, Any]) -> ScoreResult:
        """对单条线索打分。"""
        if not isinstance(clue, dict):
            return ScoreResult(score=0.0, breakdown={}, grade=GRADE_JUNK)

        breakdown: dict[str, float] = {
            "timeliness": self._score_timeliness(clue),
            "industry": self._score_industry(clue),
            "intensity": self._score_intensity(clue),
            "channel": self._score_channel(clue),
            "qualification": self._score_qualification(clue),
            "completeness": self._score_completeness(clue),
        }

        score = 0.0
        for dim, weight in self._weights.items():
            score += (breakdown.get(dim, 0.0)) * weight * 100
        score = max(0.0, min(100.0, score))

        grade = self.grade_from_score(score)
        return ScoreResult(score=score, breakdown={k: round(v, 3) for k, v in breakdown.items()}, grade=grade)

    def score_batch(self, clues: list[dict[str, Any]]) -> list[ScoreResult]:
        return [self.score_one(c) for c in clues]

    def grade_from_score(self, score: float) -> str:
        if score >= self._thresholds["high"]:
            return GRADE_HIGH
        if score >= self._thresholds["normal"]:
            return GRADE_NORMAL
        if score >= self._thresholds["low"]:
            return GRADE_LOW
        return GRADE_JUNK

    def grade_batch(self, scores: list[float | ScoreResult]) -> list[str]:
        return [
            self.grade_from_score(s.score if isinstance(s, ScoreResult) else float(s))
            for s in scores
        ]

    # ---------------- 6 维度单项 ----------------

    def _score_timeliness(self, clue: dict[str, Any]) -> float:
        """exp(-λ × days)。"""
        value = clue.get("capture_time") or clue.get("created_at")
        if value is None:
            return 0.3
        days = _parse_days_old(value)
        if days is None:
            return 0.3
        # 0 天 → 1.0；100 天 → e^-5 ≈ 0.007
        return math.exp(-self._timeliness_lambda * max(0.0, days))

    def _score_industry(self, clue: dict[str, Any]) -> float:
        industry = str(clue.get("industry") or "").strip().lower()
        if not industry:
            return 0.3
        if self._high_industries and industry in self._high_industries:
            return 1.0
        # 关键字包含匹配
        for hi in self._high_industries:
            if hi and (hi in industry or industry in hi):
                return 0.85
        return 0.5  # 普通行业

    def _score_intensity(self, clue: dict[str, Any]) -> float:
        text = str(clue.get("requirement_text") or clue.get("requirement") or "").strip().lower()
        if not text:
            return 0.0

        strong = self._intensity_keywords.get("strong") or []
        medium = self._intensity_keywords.get("medium") or []
        weak = self._intensity_keywords.get("weak") or []

        # 关键词命中计分
        k_score = 0.0
        hit_strong = sum(1 for kw in strong if kw and kw in text)
        hit_medium = sum(1 for kw in medium if kw and kw in text)
        hit_weak = sum(1 for kw in weak if kw and kw in text)
        k_score = min(1.0, hit_strong * 0.15 + hit_medium * 0.08 + hit_weak * 0.03)

        # 长度分
        length = len(text)
        if length >= 80:
            len_score = 1.0
        elif length >= 50:
            len_score = 0.8
        elif length >= 20:
            len_score = 0.6
        elif length >= 10:
            len_score = 0.4
        else:
            len_score = 0.1

        # 加权：关键词更重要
        combined = 0.7 * k_score + 0.3 * len_score
        return max(0.0, min(1.0, combined))

    def _score_channel(self, clue: dict[str, Any]) -> float:
        platform = str(clue.get("source_platform") or clue.get("platform") or "").strip().lower()
        if not platform:
            return 0.3
        if platform in self._channel_weights:
            return self._channel_weights[platform]
        # 包含式匹配
        for key, val in self._channel_weights.items():
            if key in platform or platform in key:
                return val
        return self._channel_weights.get("other", 0.4)

    def _score_qualification(self, clue: dict[str, Any]) -> float:
        company = str(clue.get("company_name") or clue.get("company") or "").strip()
        if not company:
            return 0.2
        score = 0.0
        # 长度：越长越正规（合理上限）
        length = len(company)
        if length >= 8:
            score += 0.4
        elif length >= 5:
            score += 0.3
        else:
            score += 0.1
        # 正规后缀
        for suffix in ("有限公司", "股份公司", "集团", "公司", "INC", "LTD", "LLC"):
            if suffix.lower() in company.lower():
                score += 0.3
                break
        # 高资质列表
        for hq in self._high_quality:
            if hq and hq.lower() in company.lower():
                score += 0.3
                break
        return max(0.0, min(1.0, score))

    def _score_completeness(self, clue: dict[str, Any]) -> float:
        filled = 0
        for field in ("company_name", "company"):
            if clue.get(field):
                filled += 1
                break
        has_phone = bool(clue.get("contact_phone") or clue.get("phone"))
        has_wechat = bool(clue.get("contact_wechat") or clue.get("wechat"))
        has_industry = bool(clue.get("industry"))
        has_requirement = bool(clue.get("requirement_text") or clue.get("requirement"))
        total_checks = [bool(clue.get("company_name") or clue.get("company")), has_phone, has_wechat, has_industry, has_requirement]
        filled = sum(1 for x in total_checks if x)
        ratio = filled / len(total_checks)
        if ratio >= 0.8:
            return 1.0
        if ratio >= 0.6:
            return 0.7
        if ratio >= 0.4:
            return 0.4
        return 0.15

    # ---------------- 访问配置（便于调试） ----------------

    def get_config(self) -> dict[str, Any]:
        return {
            "weights": self._weights,
            "timeliness_lambda": self._timeliness_lambda,
            "high_industries": sorted(self._high_industries),
            "intensity_keywords": self._intensity_keywords,
            "channel_weights": self._channel_weights,
            "high_quality": self._high_quality,
            "thresholds": self._thresholds,
        }


# ============================================================
# 辅助
# ============================================================


def _env_float(name: str, default: float) -> float:
    raw = os.environ.get(name)
    if raw is None or raw == "":
        return default
    try:
        return float(raw)
    except ValueError:
        return default


def _env_list_string(name: str) -> list[str]:
    raw = os.environ.get(name)
    if not raw:
        return []
    try:
        parsed = json.loads(raw)
        if isinstance(parsed, list):
            return [str(x).strip() for x in parsed if x is not None]
    except json.JSONDecodeError:
        pass
    return [x.strip() for x in raw.split(",") if x.strip()]


def _env_dict_string_list(name: str, default: dict[str, list[str]]) -> dict[str, list[str]]:
    raw = os.environ.get(name)
    if not raw:
        return default
    try:
        parsed = json.loads(raw)
        if isinstance(parsed, dict):
            return {
                str(k): [str(x).strip().lower() for x in (v if isinstance(v, list) else [str(v)]) if x]
                for k, v in parsed.items()
            }
    except json.JSONDecodeError:
        pass
    return default


def _env_dict_float(name: str, default: dict[str, float]) -> dict[str, float]:
    raw = os.environ.get(name)
    if not raw:
        return default
    try:
        parsed = json.loads(raw)
        if isinstance(parsed, dict):
            return {str(k): float(v) for k, v in parsed.items()}
    except json.JSONDecodeError:
        pass
    return default


def _parse_days_old(value: Any) -> float | None:
    from datetime import datetime as _dt
    if not value:
        return None
    try:
        if isinstance(value, (int, float)):
            ts = float(value)
            if ts > 1e12:
                ts = ts / 1000
            from time import time as _now
            return max(0.0, (_now() - ts) / 86400)
        s = str(value).strip()
        if not s:
            return None
        if s.endswith("Z"):
            s = s[:-1] + "+00:00"
        dt = _dt.fromisoformat(s)
        now = _dt.now(dt.tzinfo) if dt.tzinfo else _dt.now()
        return max(0.0, (now - dt).total_seconds() / 86400)
    except Exception:
        return None


# ============================================================
# 模块级单例
# ============================================================


def _build_default_engine() -> ScoringEngine:
    return ScoringEngine()


scoring_engine: ScoringEngine
try:
    scoring_engine = _build_default_engine()
except Exception as exc:
    logger.warning(f"默认 ScoringEngine 初始化失败: {exc}")
    scoring_engine = ScoringEngine()


__all__ = [
    "GRADE_HIGH", "GRADE_NORMAL", "GRADE_LOW", "GRADE_JUNK",
    "ScoreResult", "ScoringEngine", "scoring_engine",
]
