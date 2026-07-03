from __future__ import annotations

import os
import threading
import time
from dataclasses import dataclass, field
from typing import Any

from infra.logger_setup import get_logger

logger = get_logger("data_core.pipeline")


# ============================================================
# 数据类（标准输出结构）
# ============================================================


@dataclass
class ScoredOpportunity:
    """商机条目（脱敏后输出）。"""
    clue_id: str
    master_source: str
    merged_sources: list[str]
    company_name: str | None
    contact_phones: list[str]
    contact_wechats: list[str]
    requirement_text: str
    industry: str | None
    platforms: list[str]
    score: float
    grade: str
    score_breakdown: dict[str, float]
    is_blocked: bool
    block_reason: str | None
    first_capture_at: str | None
    latest_activity_at: str | None
    duplicate_of: str | None
    raw_ids: list[int]

    def to_dict(self) -> dict[str, Any]:
        return {
            "clue_id": self.clue_id,
            "master_source": self.master_source,
            "merged_sources": self.merged_sources,
            "company_name": self.company_name,
            "contact_phones": self.contact_phones,
            "contact_wechats": self.contact_wechats,
            "requirement_text": self.requirement_text,
            "industry": self.industry,
            "platforms": self.platforms,
            "score": round(self.score, 2),
            "grade": self.grade,
            "score_breakdown": self.score_breakdown,
            "is_blocked": self.is_blocked,
            "block_reason": self.block_reason,
            "first_capture_at": self.first_capture_at,
            "latest_activity_at": self.latest_activity_at,
            "duplicate_of": self.duplicate_of,
            "raw_ids": self.raw_ids,
        }


@dataclass
class PipelineResult:
    total_input: int = 0
    blocked_by_blacklist: int = 0
    duplicates_removed: int = 0
    final_opportunities: int = 0
    grade_distribution: dict[str, int] = field(default_factory=dict)
    score_histogram: list[tuple[str, int]] = field(default_factory=list)
    items: list[ScoredOpportunity] = field(default_factory=list)
    logs: list[str] = field(default_factory=list)
    alerts: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "total_input": self.total_input,
            "blocked_by_blacklist": self.blocked_by_blacklist,
            "duplicates_removed": self.duplicates_removed,
            "final_opportunities": self.final_opportunities,
            "grade_distribution": self.grade_distribution,
            "score_histogram": [list(x) for x in self.score_histogram],
            "items": [i.to_dict() for i in self.items],
            "logs": self.logs,
            "alerts": self.alerts,
        }


# ============================================================
# OpportunityPipeline 主类
# ============================================================


class OpportunityPipeline:
    """组合各模块：黑名单过滤 → 去重 → 合并 → 打分 → 分级 → 脱敏输出。"""

    def __init__(
        self,
        *,
        blacklist_filter: Any | None = None,
        dedupe_engine: Any | None = None,
        merge_engine: Any | None = None,
        scoring_engine: Any | None = None,
        pii_mask: Any | None = None,
        compliance_checker: Any | None = None,
        alert_debounce_seconds: int | None = None,
        blacklist_alert_batch_size: int | None = None,
        enable_compliance_check: bool | None = None,
    ) -> None:
        # 默认：从模块级单例引入
        from core.data_core.blacklist_filter import blacklist_filter as _bl
        from core.data_core.dedupe_engine import dedupe_engine as _de
        from core.data_core.merge_engine import merge_engine as _me
        from core.data_core.scoring_engine import scoring_engine as _se
        from core.compliance.pii_mask import pii_mask as _pm

        self._blacklist = blacklist_filter or _bl
        self._dedupe = dedupe_engine or _de
        self._merge = merge_engine or _me
        self._scoring = scoring_engine or _se
        self._pii_mask = pii_mask or _pm
        self._compliance = compliance_checker

        def _env_int(name: str, default: int) -> int:
            raw = os.environ.get(name)
            if raw is None or raw == "":
                return default
            try:
                return int(raw)
            except ValueError:
                return default

        def _env_bool(name: str, default: bool) -> bool:
            raw = os.environ.get(name)
            if raw is None:
                return default
            return str(raw).strip().lower() not in ("0", "false", "no", "off", "")

        self._alert_debounce = alert_debounce_seconds if alert_debounce_seconds is not None else _env_int(
            "COMPLIANCE_ALERT_DEBOUNCE_SECS", 600
        )
        self._blacklist_alert_batch_size = (
            blacklist_alert_batch_size if blacklist_alert_batch_size is not None
            else _env_int("BLACKLIST_ALERT_BATCH_SIZE", 10)
        )
        self._enable_compliance_check = (
            enable_compliance_check if enable_compliance_check is not None
            else _env_bool("PIPELINE_ENABLE_COMPLIANCE_CHECK", True)
        )
        self._last_alert_ts: dict[str, float] = {}
        self._lock = threading.RLock()

    # ---------------- 公共 API ----------------

    def process_batch(self, clues: list[dict[str, Any]]) -> PipelineResult:
        result = PipelineResult(total_input=len(clues or []))
        if not clues:
            return result

        # Step 1: 合规预检（可选）—— 在处理前先对明文做检查，用于告警决策
        if self._enable_compliance_check and self._compliance is not None:
            for c in clues:
                try:
                    r = self._compliance.check_for_storage(c, context={"source": "pipeline"})
                except Exception as exc:
                    logger.warning(f"compliance_checker 异常: {exc}")

        # Step 2: 黑名单过滤
        filter_results = []
        surviving_clues: list[dict[str, Any]] = []
        try:
            filter_results = self._blacklist.filter_batch(clues)
        except Exception as exc:
            logger.warning(f"blacklist_filter 异常: {exc}")
            filter_results = []

        blocked = 0
        for c, fr in zip(clues, filter_results):
            if fr and fr.is_blocked:
                blocked += 1
                continue
            surviving_clues.append(c)
        result.blocked_by_blacklist = blocked

        # Step 3: 去重
        dedup_result = None
        try:
            dedup_result = self._dedupe.deduplicate(surviving_clues)
        except Exception as exc:
            logger.warning(f"dedupe_engine 异常: {exc}")

        if dedup_result is None:
            # 退化：每个线索独立为一元素簇
            clusters = {}
            for idx, c in enumerate(surviving_clues):
                cid = str(c.get("clue_id") or c.get("id") or f"auto_{idx}")
                clusters[cid] = [cid]
        else:
            clusters = dedup_result.clusters

        # Step 4: 合并
        try:
            merge_result = self._merge.merge_clusters(surviving_clues, clusters)
        except Exception as exc:
            logger.warning(f"merge_engine 异常: {exc}")
            # 退化：将 surviving_clues 视为单元素簇
            merge_result = _build_trivial_merge_result(surviving_clues)

        # 记录"被移除的冗余线索数" = 输入数 - 主线索数
        result.duplicates_removed = merge_result.total_input - merge_result.total_merged

        # Step 5: 打分 + 分级
        items: list[ScoredOpportunity] = []
        grade_dist: dict[str, int] = {
            "HIGH_INTENT": 0, "NORMAL": 0, "LOW_INTENT": 0, "JUNK": 0,
        }
        # 先对主线索打分
        for merged in merge_result.merged:
            # 将 MergedClue 转 dict 形式供给 scoring
            pseudo_clue = {
                "clue_id": merged.clue_id,
                "company_name": merged.company_name,
                "source_platform": merged.master_source,
                "platform": merged.master_source,
                "contact_phone": merged.contact_phones,
                "contact_wechat": merged.contact_wechats,
                "requirement_text": merged.requirement_text,
                "industry": merged.industry,
                "capture_time": merged.latest_activity_at or merged.first_capture_at,
                "platforms": merged.platforms,
            }
            try:
                sr = self._scoring.score_one(pseudo_clue)
            except Exception as exc:
                logger.warning(f"scoring 异常: {exc}")
                from core.data_core.scoring_engine import GRADE_JUNK
                sr = type("SR", (), {"score": 0.0, "grade": GRADE_JUNK, "breakdown": {}})()

            # Step 6: 输出脱敏 —— 对 phone/wechat/email 等做脱敏
            masked_company = self._mask_value("company", merged.company_name)
            masked_phones = [self._mask_value("phone", p) for p in merged.contact_phones]
            masked_wechats = [self._mask_value("wechat", w) for w in merged.contact_wechats]
            masked_requirement = self._mask_value("requirement", merged.requirement_text)

            grade = sr.grade if hasattr(sr, "grade") else "JUNK"
            grade_dist[grade] = grade_dist.get(grade, 0) + 1
            items.append(ScoredOpportunity(
                clue_id=merged.clue_id,
                master_source=str(merged.master_source or ""),
                merged_sources=list(merged.merged_sources or []),
                company_name=masked_company,
                contact_phones=masked_phones,
                contact_wechats=masked_wechats,
                requirement_text=masked_requirement,
                industry=merged.industry,
                platforms=list(merged.platforms or []),
                score=float(getattr(sr, "score", 0.0)),
                grade=grade,
                score_breakdown=dict(getattr(sr, "breakdown", {}) or {}),
                is_blocked=False,
                block_reason=None,
                first_capture_at=merged.first_capture_at,
                latest_activity_at=merged.latest_activity_at,
                duplicate_of=None,
                raw_ids=list(merged.raw_ids or []),
            ))

        # 将 duplicate 线索（非主线索）也输出为 JUNK 并标注 duplicate_of
        for dup in merge_result.duplicates:
            pseudo_clue = {
                "clue_id": dup.clue_id,
                "company_name": dup.company_name,
                "source_platform": dup.master_source,
                "contact_phone": dup.contact_phones,
                "contact_wechat": dup.contact_wechats,
                "requirement_text": dup.requirement_text,
                "industry": dup.industry,
                "capture_time": dup.latest_activity_at or dup.first_capture_at,
            }
            try:
                sr = self._scoring.score_one(pseudo_clue)
            except Exception:
                from core.data_core.scoring_engine import GRADE_JUNK
                sr = type("SR", (), {"score": 0.0, "grade": GRADE_JUNK, "breakdown": {}})()

            items.append(ScoredOpportunity(
                clue_id=dup.clue_id,
                master_source=str(dup.master_source or ""),
                merged_sources=list(dup.merged_sources or []),
                company_name=self._mask_value("company", dup.company_name),
                contact_phones=[self._mask_value("phone", p) for p in dup.contact_phones],
                contact_wechats=[self._mask_value("wechat", w) for w in dup.contact_wechats],
                requirement_text=self._mask_value("requirement", dup.requirement_text),
                industry=dup.industry,
                platforms=list(dup.platforms or []),
                score=float(getattr(sr, "score", 0.0)),
                grade=getattr(sr, "grade", "JUNK"),
                score_breakdown=dict(getattr(sr, "breakdown", {}) or {}),
                is_blocked=False,
                block_reason=None,
                first_capture_at=dup.first_capture_at,
                latest_activity_at=dup.latest_activity_at,
                duplicate_of=dup.duplicate_of,
                raw_ids=list(dup.raw_ids or []),
            ))

        # 计算直方图
        bins = [0] * 10
        for item in items:
            idx = min(9, int(item.score // 10))
            bins[idx] += 1
        score_hist: list[tuple[str, int]] = []
        for i, v in enumerate(bins):
            score_hist.append((f"{i*10}-{(i+1)*10}", v))

        result.grade_distribution = grade_dist
        result.score_histogram = score_hist
        result.items = items
        result.final_opportunities = len(items)

        # 日志：摘要信息
        summary_msg = (
            f"pipeline summary: total_input={result.total_input}, "
            f"blocked={result.blocked_by_blacklist}, duplicates_removed={result.duplicates_removed}, "
            f"final={result.final_opportunities}, grades={grade_dist}"
        )
        logger.info(summary_msg)
        result.logs.append(summary_msg)

        # 批量黑名单命中告警
        if result.blocked_by_blacklist >= self._blacklist_alert_batch_size:
            alert_msg = (
                f"[PIPELINE-BLACKLIST] 单次批次命中黑名单 {result.blocked_by_blacklist} 条，"
                f"阈值={self._blacklist_alert_batch_size}"
            )
            self._emit_alert("blacklist_batch", alert_msg)
            result.alerts.append(alert_msg)

        return result

    # ---------------- 内部辅助 ----------------

    def _mask_value(self, field_type: str, value: Any) -> Any:
        """统一调用 PIIMask 对值做脱敏。"""
        if value is None:
            return None
        try:
            mask = self._pii_mask
            if field_type == "phone":
                if isinstance(value, str):
                    return mask.mask_phone(value)
                return value
            if field_type == "wechat":
                if isinstance(value, str):
                    return mask.mask_wechat(value)
                return value
            if field_type == "company":
                if isinstance(value, str):
                    return value  # 企业名称保留原样（可能含个人信息时已由前置脱敏处理）
                return value
            if field_type == "requirement":
                if isinstance(value, str):
                    # 内容级脱敏（手机号/微信号出现在文本中）
                    return mask._mask_string(value) if hasattr(mask, "_mask_string") else value
                return value
            if isinstance(value, str):
                return mask._mask_string(value) if hasattr(mask, "_mask_string") else value
            return value
        except Exception as exc:
            logger.warning(f"mask_value 异常 ({field_type}): {exc}")
            return value

    def _emit_alert(self, key: str, message: str) -> None:
        now = time.time()
        with self._lock:
            last = self._last_alert_ts.get(key, 0.0)
            if now - last < self._alert_debounce:
                return
            self._last_alert_ts[key] = now
        try:
            from infra.alerting import alert_service
            alert_service.service_exception_sync(
                service_name="data_core_pipeline",
                message=message,
                extra={"alert_key": key, "alert_debounce_seconds": self._alert_debounce},
            )
        except Exception as exc:
            logger.warning(f"告警推送失败: {exc}")


# ============================================================
# 辅助：退化式 merge 结果构造
# ============================================================


def _build_trivial_merge_result(clues: list[dict[str, Any]]) -> Any:
    from core.data_core.merge_engine import MergeResult, MergedClue
    mr = MergeResult(total_input=len(clues))
    for idx, c in enumerate(clues):
        cid = str(c.get("clue_id") or c.get("id") or f"auto_{idx}")
        mc = MergedClue(
            clue_id=cid,
            master_source=str(c.get("source_platform") or c.get("platform") or "unknown"),
            merged_sources=[str(c.get("source_platform") or c.get("source_id") or cid)],
            company_name=c.get("company_name") or c.get("company"),
            contact_phones=[str(p) for p in (c.get("contact_phone") or c.get("phone") or [])] if not isinstance(c.get("contact_phone", "") or c.get("phone", ""), str) and hasattr(c.get("contact_phone") or c.get("phone"), "__iter__") else [str(c.get("contact_phone") or c.get("phone") or "")] if c.get("contact_phone") or c.get("phone") else [],
            contact_wechats=[str(w) for w in (c.get("contact_wechat") or c.get("wechat") or [])] if not isinstance(c.get("contact_wechat", "") or c.get("wechat", ""), str) and hasattr(c.get("contact_wechat") or c.get("wechat"), "__iter__") else [str(c.get("contact_wechat") or c.get("wechat") or "")] if c.get("contact_wechat") or c.get("wechat") else [],
            requirement_text=str(c.get("requirement_text") or c.get("requirement") or ""),
            industry=c.get("industry"),
            platforms=[str(c.get("source_platform") or c.get("platform") or "")] if c.get("source_platform") or c.get("platform") else [],
            first_capture_at=str(c.get("capture_time") or c.get("created_at") or ""),
            latest_activity_at=str(c.get("capture_time") or c.get("created_at") or ""),
            raw_ids=[],
            user_ids=[],
            _source_members=[c],
        )
        mr.merged.append(mc)
    mr.total_merged = len(mr.merged)
    return mr


# ============================================================
# 模块级单例
# ============================================================


def _build_default_pipeline() -> OpportunityPipeline:
    return OpportunityPipeline()


opportunity_pipeline: OpportunityPipeline
try:
    opportunity_pipeline = _build_default_pipeline()
except Exception as exc:
    logger.warning(f"默认 OpportunityPipeline 初始化失败: {exc}")
    opportunity_pipeline = OpportunityPipeline()


__all__ = ["ScoredOpportunity", "PipelineResult", "OpportunityPipeline", "opportunity_pipeline"]
