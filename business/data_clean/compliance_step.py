from __future__ import annotations

import uuid
from typing import TYPE_CHECKING

from infra.logger_setup import get_logger
from core.compliance import compliance_checker, pii_mask, privacy_stripper, sensitive_filter
from configs.settings import settings

from business.data_clean.models import AnomalyRecord, EntityExtract, RawRecord

if TYPE_CHECKING:
    pass

logger = get_logger("data_clean.compliance")


# =====================
# 合规步骤
# =====================


class ComplianceStep:
    """隐私脱敏 / 敏感词 / 合规报告，高违规分流到异常池。"""

    def __init__(self) -> None:
        cfg = settings.cleaning
        self.high_violation_risk = str(cfg.CLEAN_HIGH_VIOLATION_RISK or "high").lower()
        self.high_violation_hits = int(cfg.CLEAN_HIGH_VIOLATION_HITS or 3)

    def _mask_text(self, text: str) -> str:
        try:
            return pii_mask.auto_mask(text or "") or text or ""
        except Exception as exc:
            logger.warning(f"pii_mask.auto_mask 失败: {exc}")
            return text or ""

    def _filter_text(self, text: str) -> object:
        try:
            return sensitive_filter.filter_text(text or "")
        except Exception as exc:
            logger.warning(f"sensitive_filter.filter_text 失败: {exc}")

            class _Empty:
                risk = "low"
                hits: list[object] = []
                is_blocked = False
            return _Empty()

    def _compliance_report_dict(self, rec: RawRecord, entities: EntityExtract) -> dict:
        try:
            report = compliance_checker.check_for_storage({
                "title": (rec.raw_payload or {}).get("title", "") or "",
                "content": rec.raw_text or "",
                "author": (rec.raw_payload or {}).get("author", "") or "",
                "entities": entities.model_dump(mode="json") if entities else {},
                "spider_name": rec.spider_name,
                "source_url": rec.source_url,
            })
            if hasattr(report, "to_dict"):
                return report.to_dict()
            if hasattr(report, "model_dump"):
                return report.model_dump(mode="json")  # type: ignore[attr-defined]
            return {}
        except Exception as exc:
            logger.warning(f"compliance_checker 失败: {exc}")
            return {"error": str(exc)}

    def _strip_payload(self, payload: dict) -> dict:
        try:
            stripped = privacy_stripper.strip(payload)
            if isinstance(stripped, dict):
                return stripped
        except Exception as exc:
            logger.warning(f"privacy_stripper.strip 失败: {exc}")
        return payload

    def process(
        self,
        rec: RawRecord,
        entities: EntityExtract,
    ) -> tuple[EntityExtract, AnomalyRecord | None, str, dict]:
        """处理一条记录，返回 (entities, 可能的异常, 脱敏文本, 合规报告 dict).

        entities 中的 phone/wechat/company 等可能包含敏感信息，本步骤对它们进行脱敏。
        """
        # 1) 脱敏正文/标题
        masked_text = self._mask_text(rec.raw_text or "")
        title_in_payload = (rec.raw_payload or {}).get("title", "") or ""
        masked_title = self._mask_text(title_in_payload)

        # 2) 敏感词命中检查（以脱敏文本为主，可能保留原始敏感词）
        filter_result = self._filter_text(masked_text)
        risk = getattr(filter_result, "risk", "low") or "low"
        hits = list(getattr(filter_result, "hits", []) or [])
        is_blocked = bool(getattr(filter_result, "is_blocked", False))

        # 3) 合规报告
        report_dict = self._compliance_report_dict(rec, entities)

        # 4) payload 隐私字段剔除
        if rec.raw_payload:
            rec.raw_payload = self._strip_payload(rec.raw_payload)

        # 5) 脱敏 entities 中的电话/微信
        entities.phone_numbers = [self._mask_text(p) for p in entities.phone_numbers]
        entities.wechat_ids = [self._mask_text(w) for w in entities.wechat_ids]

        # 6) 触发 high_violation？
        hit_count = len(hits)
        is_high_violation = (
            str(risk).lower() == self.high_violation_risk
            or is_blocked
            or hit_count >= self.high_violation_hits
        )

        anomaly: AnomalyRecord | None = None
        if is_high_violation:
            hit_words = []
            for h in hits:
                # SensitiveHit 可能是对象或字符串
                word = getattr(h, "word", None)
                if word:
                    hit_words.append(str(word))
                elif isinstance(h, str):
                    hit_words.append(h)
                else:
                    try:
                        hit_words.append(h.get("word", "") or "")  # type: ignore[union-attr]
                    except Exception:
                        pass
            reason = f"risk={risk}, hits={hit_count}, words={hit_words[:5]}"
            anomaly = AnomalyRecord(
                anomaly_id=f"a_hv_{uuid.uuid4().hex[:10]}",
                tenant_id=rec.tenant_id,
                source_record_id=rec.id,
                type="high_violation",
                severity="error",
                reason=reason,
                raw_snippet=masked_text[:200],
                pipeline_version=str(settings.cleaning.CLEAN_PIPELINE_VERSION),
                needs_review=True,
                spider_name=rec.spider_name,
                source_url=rec.source_url,
            )

        # 返回：(entities, anomaly, 脱敏文本, 合规报告)
        return entities, anomaly, masked_text, report_dict


__all__ = ["ComplianceStep"]
