"""core/spider_core/alert_manager — 告警管理器。

作用：
  - 记录采集过程中的各类告警（parse 失败、匹配率低、失败率高、OCR 失败等）
  - 计算统计指标并输出到日志（logger.warning / error）
  - 对高优先级告警触发 SpiderError(trigger_alert=True)

使用方式：
    am = AlertManager()
    am.record(task_id="news", level="error", category="parse", message="字段 'title' 未命中")
    alerts = am.flush(task_id="news")
"""

from __future__ import annotations

import threading
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from infra.logger_setup import get_logger

logger = get_logger("spider.alert")


@dataclass
class Alert:
    task_id: str
    level: str  # "warning" | "error" | "critical"
    category: str  # "parse" | "match_rate" | "failure_rate" | "attachment" | "ocr" | "compliance"
    message: str
    details: Dict[str, Any] = field(default_factory=dict)
    timestamp: float = 0.0


class AlertManager:
    """告警管理器。"""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._alerts: Dict[str, List[Alert]] = {}

    # ---------- public ----------

    def record(
        self,
        *,
        task_id: str,
        level: str = "warning",
        category: str = "parse",
        message: str,
        details: Optional[Dict[str, Any]] = None,
    ) -> Alert:
        import time as _time
        alert = Alert(
            task_id=task_id,
            level=level,
            category=category,
            message=message,
            details=details or {},
            timestamp=_time.time(),
        )
        with self._lock:
            self._alerts.setdefault(task_id, []).append(alert)
        # 同步写到日志（便于实时观察）
        log_fn = logger.error if level in ("error", "critical") else logger.warning
        log_fn(f"[{alert.level.upper()}] [{category}] task={task_id} — {message}")

        # critical 级别直接触发全局告警通道
        if level == "critical":
            try:
                from core.spider_core.exceptions import SpiderError as _SE
            except Exception:
                try:
                    from infra.exceptions import BizException as _BE  # type: ignore
                except Exception:
                    _BE = None
                _SE = _BE  # type: ignore
            if _SE:
                try:
                    raise _SE(message, code=500, trigger_alert=True, data=details or {})
                except Exception:
                    # 仅记录，不中断
                    pass
        return alert

    def check_thresholds(
        self,
        *,
        task_id: str,
        field_match_rate: Optional[float] = None,
        failure_rate: Optional[float] = None,
        match_rate_threshold: float = 0.5,
        failure_rate_threshold: float = 0.3,
    ) -> List[Alert]:
        out: List[Alert] = []
        if field_match_rate is not None and field_match_rate < match_rate_threshold:
            out.append(self.record(
                task_id=task_id,
                level="warning",
                category="match_rate",
                message=f"字段匹配率 {field_match_rate:.2%} 低于阈值 {match_rate_threshold:.0%}",
                details={"field_match_rate": field_match_rate, "threshold": match_rate_threshold},
            ))
        if failure_rate is not None and failure_rate > failure_rate_threshold:
            out.append(self.record(
                task_id=task_id,
                level="error",
                category="failure_rate",
                message=f"页面失败率 {failure_rate:.2%} 超过阈值 {failure_rate_threshold:.0%}",
                details={"failure_rate": failure_rate, "threshold": failure_rate_threshold},
            ))
        return out

    def flush(self, task_id: str) -> List[Alert]:
        with self._lock:
            out = list(self._alerts.get(task_id, []))
            self._alerts[task_id] = []
            return out

    def count(self, task_id: str) -> int:
        with self._lock:
            return len(self._alerts.get(task_id, []))


# 模块级单例
_default_manager: Optional[AlertManager] = None


def get_alert_manager() -> AlertManager:
    global _default_manager
    if _default_manager is None:
        _default_manager = AlertManager()
    return _default_manager


__all__ = ["Alert", "AlertManager", "get_alert_manager"]
