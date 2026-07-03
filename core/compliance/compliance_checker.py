from __future__ import annotations

import json
import os
import threading
import time
from dataclasses import dataclass, field
from typing import Any

from infra.logger_setup import get_logger

logger = get_logger("compliance.checker")


# =====================
# 结果数据类
# =====================

@dataclass
class ComplianceReport:
    passed: bool                          # 是否通过合规校验（risk != high 或 未命中）
    blocked: bool                         # 是否触发拦截（命中敏感词 block threshold 或 隐私超阈值）
    risk_level: str                      # low / medium / high
    masked_data: Any                     # 脱敏后的输出
    sensitive_hits: list[dict] = field(default_factory=list)
    privacy_hits: list[dict] = field(default_factory=list)
    logs: list[str] = field(default_factory=list)
    context: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        def _to_serializable(x: Any) -> Any:
            if isinstance(x, (dict, list, tuple, str, int, float, bool)) or x is None:
                return x
            return str(x)

        return {
            "passed": self.passed,
            "blocked": self.blocked,
            "risk_level": self.risk_level,
            "sensitive_hits": self.sensitive_hits,
            "privacy_hits": self.privacy_hits,
            "logs": self.logs,
            "context": {k: _to_serializable(v) for k, v in self.context.items()},
        }


# =====================
# 统一合规校验入口
# =====================

class ComplianceChecker:
    """统一合规校验入口。

    - check_for_storage：爬虫入库场景 —— 隐私字段剔除 + 敏感词过滤
    - check_for_outbound：消息发送场景 —— 隐私字段掩码 + 敏感词过滤
    - precheck：通用入口，mode ∈ {"storage", "outbound"}
    """

    def __init__(
        self,
        *,
        pii_mask: Any | None = None,
        sensitive_filter: Any | None = None,
        privacy_stripper: Any | None = None,
        enable_alert_on_high_risk: bool = True,
        alert_debounce_seconds: int = 600,
    ) -> None:
        self._pii_mask = pii_mask
        self._sensitive_filter = sensitive_filter
        self._privacy_stripper = privacy_stripper
        self._enable_alert = bool(enable_alert_on_high_risk)
        self._alert_debounce = int(alert_debounce_seconds)
        self._last_alert_ts: dict[str, float] = {}
        self._lock = threading.RLock()

    # ---------- 场景 API ----------

    def check_for_storage(self, data: Any, *, context: dict | None = None) -> ComplianceReport:
        return self._check_impl(data, mode="storage", context=context or {})

    def check_for_outbound(self, data: Any, *, context: dict | None = None) -> ComplianceReport:
        return self._check_impl(data, mode="outbound", context=context or {})

    def precheck(self, data: Any, *, context: dict | None = None, mode: str = "storage") -> ComplianceReport:
        if mode not in {"storage", "outbound"}:
            raise ValueError(f"mode 必须是 'storage' 或 'outbound'，得到: {mode}")
        return self._check_impl(data, mode=mode, context=context or {})

    # ---------- 内部实现 ----------

    def _check_impl(self, data: Any, *, mode: str, context: dict) -> ComplianceReport:
        logs: list[str] = []

        # Step A: 敏感词检测（对字符串化后的顶层数据做检测）
        sensitive_hits: list[dict] = []
        sf = self._sensitive_filter
        if sf is not None and hasattr(sf, "detect"):
            try:
                text_for_detect = _to_flat_text(data)
                hits = sf.detect(text_for_detect)
                sensitive_hits = [
                    {
                        "word": h.word,
                        "fragment": h.fragment,
                        "category": h.category,
                        "risk": h.risk,
                        "start": h.start,
                        "end": h.end,
                    }
                    for h in hits
                ]
                if sensitive_hits:
                    logs.append(f"命中敏感词 {len(sensitive_hits)} 条")
            except Exception as exc:
                logger.warning(f"敏感词检测异常: {exc}")

        # Step B: 隐私字段检测 / 处理
        privacy_hits: list[dict] = []
        pm = self._pii_mask
        ps = self._privacy_stripper

        # 先自动检测（字符串级别的隐私）
        if pm is not None and hasattr(pm, "detect_pii"):
            try:
                flat = _to_flat_text(data)
                for h in pm.detect_pii(flat):
                    privacy_hits.append(h)
            except Exception as exc:
                logger.warning(f"隐私字段检测异常: {exc}")

        # 再扫描 dict key 级别的隐私
        if ps is not None and hasattr(ps, "scan_report"):
            try:
                scan_rep = ps.scan_report(data)
                for key in scan_rep.get("stripped_keys", []):
                    privacy_hits.append({"type": "dict_key", "key": key})
            except Exception as exc:
                logger.warning(f"隐私字段扫描异常: {exc}")

        # Step C: 输出数据（storage 剔除字段；outbound 只掩码不删除）
        masked_data: Any = data
        try:
            if mode == "storage":
                if ps is not None and hasattr(ps, "strip"):
                    # storage 场景：对隐私字段直接剔除；对字符串值做浅掩码
                    masked_data = ps.strip(masked_data, mode="strip")
                # 字符串值做敏感词掩码
                if sf is not None and hasattr(sf, "filter_text"):
                    masked_data = _apply_filter_text(masked_data, sf)
            else:
                # outbound 场景：保留结构但掩码敏感字段
                if pm is not None and hasattr(pm, "auto_mask"):
                    masked_data = pm.auto_mask(masked_data)
                if sf is not None and hasattr(sf, "filter_text"):
                    masked_data = _apply_filter_text(masked_data, sf)
        except Exception as exc:
            logger.warning(f"掩码处理异常: {exc}")

        # Step D: 计算风险等级 & 是否拦截
        risk_level = _calc_risk_level(sensitive_hits, privacy_hits)
        blocked = risk_level == "high" or len(sensitive_hits) >= 3 or len(privacy_hits) >= 5

        # Step E: 日志 + 告警
        with self._lock:
            pass

        if risk_level == "high":
            logger.warning(
                f"合规校验高风险命中: 敏感词={len(sensitive_hits)}, 隐私={len(privacy_hits)}"
                f" (context={context.get('source', 'unknown')})"
            )
        elif sensitive_hits or privacy_hits:
            logger.info(
                f"合规校验命中: 敏感词={len(sensitive_hits)}, 隐私={len(privacy_hits)}"
                f" risk={risk_level} (context={context.get('source', 'unknown')})"
            )

        # 告警联动
        if self._enable_alert and risk_level == "high":
            self._maybe_alert(context, sensitive_hits, privacy_hits)

        passed = risk_level == "low"

        return ComplianceReport(
            passed=passed,
            blocked=blocked,
            risk_level=risk_level,
            masked_data=masked_data,
            sensitive_hits=sensitive_hits,
            privacy_hits=privacy_hits,
            logs=logs,
            context=context,
        )

    def _maybe_alert(self, context: dict, sensitive_hits: list[dict], privacy_hits: list[dict]) -> None:
        now = time.time()
        source = str(context.get("source", "unknown"))
        key = f"high_risk_{source}"
        with self._lock:
            last = self._last_alert_ts.get(key, 0.0)
            if now - last < self._alert_debounce:
                return
            self._last_alert_ts[key] = now

        try:
            from infra.alerting import alert_service
            summary = f"[COMPLIANCE-HIGH-RISK] source={source}; 敏感词命中={len(sensitive_hits)}; 隐私命中={len(privacy_hits)}"
            alert_service.service_exception_sync(
                service_name="compliance-checker",
                message=summary,
                extra={
                    "context": context,
                    "sensitive_hits": sensitive_hits[:5],
                    "privacy_hits": privacy_hits[:5],
                },
            )
        except Exception as exc:
            logger.warning(f"告警推送失败: {exc}")


# =====================
# 辅助函数
# =====================

def _to_flat_text(data: Any) -> str:
    """把任意结构 flatten 成字符串（便于扫描敏感词）。"""
    if data is None:
        return ""
    if isinstance(data, str):
        return data
    if isinstance(data, (int, float, bool)):
        return str(data)
    if isinstance(data, (list, tuple)):
        return " ".join(_to_flat_text(item) for item in data)
    if isinstance(data, dict):
        return " ".join(f"{k}={_to_flat_text(v)}" for k, v in data.items())
    try:
        return str(data)
    except Exception:
        return ""


def _apply_filter_text(data: Any, sf: Any) -> Any:
    """对字符串字段做敏感词 filter_text 处理，保留结构。"""
    if data is None:
        return None
    if isinstance(data, bool):
        return data
    if isinstance(data, (int, float)):
        return data
    if isinstance(data, str):
        try:
            result = sf.filter_text(data)
            return result.cleaned_text if result.cleaned_text else data
        except Exception:
            return data
    if isinstance(data, dict):
        return {k: _apply_filter_text(v, sf) for k, v in data.items()}
    if isinstance(data, list):
        return [_apply_filter_text(item, sf) for item in data]
    if isinstance(data, tuple):
        return tuple(_apply_filter_text(item, sf) for item in data)
    return data


def _calc_risk_level(sensitive_hits: list[dict], privacy_hits: list[dict]) -> str:
    """按最高风险计算。"""
    risk_scores: list[int] = [0]
    for h in sensitive_hits:
        r = h.get("risk", "low")
        if r == "high":
            risk_scores.append(3)
        elif r == "medium":
            risk_scores.append(2)
        else:
            risk_scores.append(1)
    # 隐私字段命中 ≥ 5 → medium
    if len(privacy_hits) >= 5:
        risk_scores.append(2)
    elif len(privacy_hits) >= 1:
        risk_scores.append(1)
    top = max(risk_scores)
    if top >= 3:
        return "high"
    if top >= 2:
        return "medium"
    return "low"


# =====================
# 模块级单例
# =====================

def _build_default_checker() -> ComplianceChecker:
    from core.compliance.pii_mask import pii_mask
    from core.compliance.sensitive_filter import sensitive_filter
    from core.compliance.privacy_stripper import privacy_stripper

    alert_str = (os.environ.get("COMPLIANCE_ALERT_HIGH_RISK", "true") or "true").strip().lower()
    enable_alert = alert_str not in {"false", "0", "no", "off"}
    try:
        debounce = int(os.environ.get("COMPLIANCE_ALERT_DEBOUNCE_SECS", "600"))
    except ValueError:
        debounce = 600

    return ComplianceChecker(
        pii_mask=pii_mask,
        sensitive_filter=sensitive_filter,
        privacy_stripper=privacy_stripper,
        enable_alert_on_high_risk=enable_alert,
        alert_debounce_seconds=debounce,
    )


compliance_checker: ComplianceChecker | None = None
try:
    compliance_checker = _build_default_checker()
except Exception as exc:
    logger.warning(f"默认 ComplianceChecker 初始化失败: {exc}")
    compliance_checker = ComplianceChecker()


__all__ = ["ComplianceReport", "ComplianceChecker", "compliance_checker"]
