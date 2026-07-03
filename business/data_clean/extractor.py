from __future__ import annotations

import re
from collections import Counter
from typing import TYPE_CHECKING

from infra.logger_setup import get_logger
from configs.settings import settings

from business.data_clean.models import AnomalyRecord, EntityExtract, RawRecord

if TYPE_CHECKING:
    pass

logger = get_logger("data_clean.extractor")


# =====================
# 预编译正则
# =====================

# 手机号 (大陆 + 852)
_PHONE_RE = re.compile(r"(?<!\d)(1[3-9]\d{9}|\+?86[- ]?1[3-9]\d{9}|\+?852[- ]?\d{8})(?!\d)")
# 座机：(010) 1234 5678 / 021-1234-5678
_LANDLINE_RE = re.compile(r"(?<!\d)\(?0\d{2,3}\)?[-\s]?\d{3,4}[-\s]?\d{3,4}(?!\d)")

# 微信：wechat/vx/wx + 字母数字下划线，或典型微信号 (字母开头，6-20 位)
_WECHAT_KEYWORD_RE = re.compile(r"(?:微信|wx|vx|weixin|wechat)\s*[:：]?\s*([A-Za-z0-9_\-]{5,30})", re.IGNORECASE)
_WECHAT_PURE_RE = re.compile(r"(?<![A-Za-z0-9])[A-Za-z][A-Za-z0-9_\-]{4,19}(?![A-Za-z0-9])")

# 公司名："XXX 科技有限公司"、"广州 XXX 股份有限公司"
_COMPANY_TOKENS = "公司|有限公司|股份有限公司|集团|工作室|厂|中心|部|科技|信息|数据|贸易|实业"
_COMPANY_RE = re.compile(
    rf"([\u4e00-\u9fa5A-Za-z0-9&·\-]{{2,30}}(?:{_COMPANY_TOKENS}))",
    flags=re.IGNORECASE,
)

# 预算 / 金额：
#   "预算 5 万元"、"预算：5000~10000 元"、"人民币 10 万"、"投资 100 万"
_AMOUNT_UNIT = r"(元|块|圆|万|万元|十万|百万|千万|亿|亿元)"
_BUDGET_RE = re.compile(
    rf"(?:预算|金额|投资|投入|报价|费用|价格)[:：]?\s*(\d[\d,]*\.?\d*)\s*{_AMOUNT_UNIT}?"
    rf"(?:\s*[~\-至到]\s*(\d[\d,]*\.?\d*)\s*{_AMOUNT_UNIT}?)?",
    flags=re.IGNORECASE,
)
_SIMPLE_AMOUNT_RE = re.compile(
    rf"(\d[\d,]*\.?\d*)\s*{_AMOUNT_UNIT}",
    flags=re.IGNORECASE,
)

# 数字去逗号
def _norm_num(s: str) -> float:
    try:
        return float(s.replace(",", ""))
    except ValueError:
        return 0.0


_UNIT_MULTIPLIER = {
    "万": 10_000,
    "万元": 10_000,
    "十万": 100_000,
    "百万": 1_000_000,
    "千万": 10_000_000,
    "亿": 100_000_000,
    "亿元": 100_000_000,
}


# =====================
# 实体抽取器
# =====================


class EntityExtractor:
    """从 RawRecord 抽取实体字段。"""

    def __init__(self) -> None:
        cfg = settings.cleaning
        self.min_text_len = int(cfg.CLEAN_MIN_TEXT_LEN)
        self.topk = int(cfg.CLEAN_KEYWORDS_TOPK or 8)

        self.company_enabled = bool(cfg.CLEAN_COMPANY_ENABLED)
        self.phone_enabled = bool(cfg.CLEAN_PHONE_ENABLED)
        self.wechat_enabled = bool(cfg.CLEAN_WECHAT_ENABLED)
        self.budget_enabled = bool(cfg.CLEAN_BUDGET_ENABLED)

        self.industry_keywords = [
            k for k in cfg.split_csv(cfg.CLEAN_INDUSTRY_KEYWORDS) if k
        ]
        self.region_keywords = [k for k in cfg.split_csv(cfg.CLEAN_REGION_KEYWORDS) if k]
        self.need_keywords = [k for k in cfg.split_csv(cfg.CLEAN_NEED_KEYWORDS) if k]

    # ---- 单项抽取 ----

    def _companies(self, text: str) -> list[str]:
        if not self.company_enabled:
            return []
        found = list(dict.fromkeys(m for m in _COMPANY_RE.findall(text or "")))
        return [f.strip() for f in found if len(f.strip()) >= 4][:10]

    def _phones(self, text: str) -> list[str]:
        if not self.phone_enabled:
            return []
        found = list(dict.fromkeys(_PHONE_RE.findall(text or "")))
        land = list(dict.fromkeys(_LANDLINE_RE.findall(text or "")))
        return [f.replace(" ", "").replace("-", "") for f in (found + land)][:10]

    def _wechats(self, text: str) -> list[str]:
        if not self.wechat_enabled:
            return []
        found: list[str] = []
        # 先抓带关键字的
        for m in _WECHAT_KEYWORD_RE.findall(text or ""):
            found.append(m)
        # 再抓疑似微信号（仅在包含 "微信" 关键字时放宽）
        if "微信" in (text or "") or "wechat" in (text or "").lower() or "wx" in (text or "").lower():
            for m in _WECHAT_PURE_RE.findall(text or ""):
                found.append(m)
        return list(dict.fromkeys(f.strip() for f in found))[:10]

    def _industry(self, text: str) -> list[str]:
        hits: list[str] = []
        for kw in self.industry_keywords:
            if kw and kw in (text or ""):
                hits.append(kw)
        return hits

    def _region(self, text: str) -> str:
        counts = Counter[str]()
        for kw in self.region_keywords:
            if kw and kw in (text or ""):
                counts[kw] += (text or "").count(kw)
        if not counts:
            return ""
        return counts.most_common(1)[0][0]

    def _keywords(self, text: str) -> list[str]:
        counts = Counter[str]()
        for kw in self.need_keywords:
            if kw:
                c = (text or "").count(kw)
                if c > 0:
                    counts[kw] += c
        return [k for k, _ in counts.most_common(self.topk)]

    def _budget(self, text: str) -> dict[str, object]:
        if not self.budget_enabled or not text:
            return {}
        # 先尝试预算正则
        m = _BUDGET_RE.search(text)
        if m:
            low = _norm_num(m.group(1))
            low_unit_match = m.group(2) if m.lastindex and m.lastindex >= 2 else None
            low_value = int(low * _UNIT_MULTIPLIER.get(low_unit_match or "", 1)) if low_unit_match else int(low)
            high_match = m.group(3) if m.lastindex and m.lastindex >= 3 else None
            high_unit_match = m.group(4) if m.lastindex and m.lastindex >= 4 else None
            if high_match:
                high_value = int(_norm_num(high_match) * _UNIT_MULTIPLIER.get(high_unit_match or "", 1))
            else:
                high_value = low_value
            return {"value": low_value, "value_high": high_value, "unit": "CNY",
                    "range": [low_value, high_value], "raw": m.group(0).strip()}
        # 再尝试简单金额
        m2 = _SIMPLE_AMOUNT_RE.search(text)
        if m2:
            num = _norm_num(m2.group(1))
            unit = m2.group(2) or ""
            value = int(num * _UNIT_MULTIPLIER.get(unit, 1)) if unit else int(num)
            return {"value": value, "unit": "CNY", "raw": m2.group(0).strip()}
        return {}

    # ---- 整体抽取 ----

    def extract(self, rec: RawRecord) -> tuple[EntityExtract, AnomalyRecord | None]:
        text = (rec.raw_text or "")
        if rec.raw_payload:
            payload_text = " ".join(
                v for k, v in rec.raw_payload.items() if isinstance(v, str)
            )
            combined_text = text + "\n" + payload_text
        else:
            combined_text = text

        extract = EntityExtract(
            company_names=self._companies(combined_text),
            phone_numbers=self._phones(combined_text),
            wechat_ids=self._wechats(combined_text),
            industry_tags=self._industry(combined_text),
            region=self._region(combined_text),
            keywords=self._keywords(combined_text),
            budget=self._budget(combined_text),
            estimated_text_length=len(text),
        )

        # 若文本太短且完全没有实体 → 视为抽取失败
        if len(text) < max(10, self.min_text_len) and not any(
            [extract.company_names, extract.phone_numbers, extract.wechat_ids,
             extract.industry_tags, extract.keywords, extract.budget]
        ):
            return extract, AnomalyRecord(
                anomaly_id=f"a_ext_{rec.id}",
                tenant_id=rec.tenant_id,
                source_record_id=rec.id,
                type="extract_fail",
                severity="info",
                reason="text_too_short_and_no_entities",
                raw_snippet=text[:200],
                pipeline_version=str(settings.cleaning.CLEAN_PIPELINE_VERSION),
                spider_name=rec.spider_name,
                source_url=rec.source_url,
            )

        return extract, None

    def extract_batch(self, records: list[RawRecord]) -> tuple[
        list[tuple[RawRecord, EntityExtract]], list[AnomalyRecord]
    ]:
        ok: list[tuple[RawRecord, EntityExtract]] = []
        anomalies: list[AnomalyRecord] = []
        for r in records:
            ent, anom = self.extract(r)
            if anom:
                anomalies.append(anom)
            else:
                ok.append((r, ent))
        return ok, anomalies


__all__ = ["EntityExtractor"]
