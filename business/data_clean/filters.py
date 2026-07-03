from __future__ import annotations

import re
from typing import TYPE_CHECKING

from infra.logger_setup import get_logger
from configs.settings import settings

from business.data_clean.models import AnomalyRecord, RawRecord

if TYPE_CHECKING:
    pass

logger = get_logger("data_clean.filters")


# =====================
# 工具：URL 提取
# =====================

_URL_RE = re.compile(r"https?://[^\s'\"<>]+", re.IGNORECASE)


def _extract_domains(text: str) -> list[str]:
    urls = _URL_RE.findall(text or "")
    results = []
    for u in urls:
        try:
            from urllib.parse import urlparse

            host = urlparse(u).hostname or ""
            if host:
                results.append(host.lower())
        except Exception:
            continue
    return results


# =====================
# 脏数据过滤
# =====================


class DirtyFilter:
    """判断一条原始记录是否为脏数据（空内容/灌水/失效链接/黑名单域名）。"""

    def __init__(self) -> None:
        self.min_text_len = int(settings.cleaning.CLEAN_MIN_TEXT_LEN or 30)
        self.blacklist_domains = set(
            d.lower() for d in settings.cleaning.split_csv(settings.cleaning.CLEAN_BLACKLIST_DOMAINS)
        )
        # 广告灌水正则（若未配置则使用默认规则）
        patterns_str = settings.cleaning.CLEAN_AD_JUNK_PATTERNS
        if patterns_str:
            patterns = [p.strip() for p in patterns_str.split(",") if p.strip()]
        else:
            # 默认：超长重复单字、纯链接、Emoji 堆
            patterns = [
                r"^(https?://[^\s]+(\s|,|，)?)+$",                       # 纯链接
                r"^([\U00010000-\U0010FFFF\W_]){5,}$",                   # 纯表情/符号
                r"^(.+?)\1{5,}$",                                         # 重复单字 ≥ 6 次
                r"^(加微信|vx|wechat|联系电话|qq群).{0,20}$",           # 典型引流标题
            ]
        self._patterns = [re.compile(p, re.IGNORECASE) for p in patterns]

    # ---- 单项检查（返回 (rejected, reason)） ----

    def check_empty(self, rec: RawRecord) -> tuple[bool, str]:
        text = (rec.raw_text or "").strip()
        if len(text) < self.min_text_len:
            return True, f"text_length<{self.min_text_len}"
        return False, ""

    def check_junk(self, rec: RawRecord) -> tuple[bool, str]:
        text = (rec.raw_text or "").strip()
        title = (rec.raw_payload.get("title") if rec.raw_payload else "") or ""
        for sample in (text, title):
            if not sample:
                continue
            for pat in self._patterns:
                if pat.search(sample):
                    return True, f"junk_pattern:{pat.pattern[:40]}"
        return False, ""

    def check_blacklist(self, rec: RawRecord) -> tuple[bool, str]:
        if not self.blacklist_domains:
            return False, ""
        # 检查 source_url 的域名
        url = rec.source_url or ""
        domains = []
        if url:
            try:
                from urllib.parse import urlparse

                host = urlparse(url).hostname or ""
                if host:
                    domains.append(host.lower())
            except Exception:
                pass
        # 也检查正文里的外链
        domains.extend(_extract_domains(rec.raw_text or ""))
        for d in domains:
            for bad in self.blacklist_domains:
                if d == bad or d.endswith("." + bad):
                    return True, f"blacklist_domain:{bad}"
        return False, ""

    def check_fetch_error(self, rec: RawRecord) -> tuple[bool, str]:
        if rec.fetch_status and rec.fetch_status not in (0, 3):
            return True, f"fetch_status={rec.fetch_status}"
        if rec.fetch_error:
            return True, f"fetch_error"
        return False, ""

    # ---- 组合检查 ----

    def apply(self, rec: RawRecord) -> tuple[bool, AnomalyRecord | None]:
        """返回 (passed?, anomaly)。passed=True 表示记录可以继续走后续流水线。"""
        # 先检查抓取错误和失效链接
        rejected, reason = self.check_fetch_error(rec)
        if rejected:
            return False, self._make_anomaly(rec, "dirty", "warn", reason)

        # 空内容
        rejected, reason = self.check_empty(rec)
        if rejected:
            return False, self._make_anomaly(rec, "dirty", "info", reason)

        # 灌水
        rejected, reason = self.check_junk(rec)
        if rejected:
            return False, self._make_anomaly(rec, "dirty", "warn", reason)

        # 黑名单域名
        rejected, reason = self.check_blacklist(rec)
        if rejected:
            return False, self._make_anomaly(rec, "dirty", "error", reason)

        return True, None

    def apply_batch(self, records: list[RawRecord]) -> tuple[list[RawRecord], list[AnomalyRecord]]:
        passed: list[RawRecord] = []
        anomalies: list[AnomalyRecord] = []
        for r in records:
            ok, anom = self.apply(r)
            if ok:
                passed.append(r)
            else:
                anomalies.append(anom)  # type: ignore[arg-type]
        return passed, anomalies

    @staticmethod
    def _make_anomaly(rec: RawRecord, typ: str, severity: str, reason: str) -> AnomalyRecord:
        import uuid

        return AnomalyRecord(
            anomaly_id=f"a_{uuid.uuid4().hex[:10]}",
            tenant_id=rec.tenant_id,
            source_record_id=rec.id,
            type=typ,
            severity=severity,
            reason=reason,
            raw_snippet=(rec.raw_text or "")[:200],
            pipeline_version=str(settings.cleaning.CLEAN_PIPELINE_VERSION),
            needs_review=True,
            spider_name=rec.spider_name,
            source_url=rec.source_url,
        )


__all__ = ["DirtyFilter"]
