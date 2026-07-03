from __future__ import annotations

import json
import os
import time
from datetime import datetime, timezone
from typing import Any

from infra.logger_setup import get_logger

logger = get_logger("compliance.data_lifecycle")


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _parse_timestamp(value: Any) -> datetime | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value
    if isinstance(value, (int, float)):
        # 可能是秒或毫秒级时间戳
        try:
            t = float(value)
            # 若 > 10^12，视为毫秒
            if t > 1e12:
                t = t / 1000
            return datetime.fromtimestamp(t, tz=timezone.utc)
        except (ValueError, OSError, OverflowError):
            pass
    if isinstance(value, str):
        # 支持 ISO 格式
        try:
            if value.endswith("Z"):
                value = value[:-1] + "+00:00"
            dt = datetime.fromisoformat(value)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            return dt
        except ValueError:
            pass
        # 尝试常见格式
        for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d", "%Y/%m/%d %H:%M:%S", "%Y/%m/%d"):
            try:
                return datetime.strptime(value, fmt).replace(tzinfo=timezone.utc)
            except ValueError:
                continue
    return None


class DataLifecycle:
    """数据生命周期工具。

    - mark_expired：对 dict 列表按照 created_at 字段标记过期
    - clear_privacy：批量清除结构中的隐私字段（删除 / 掩码两种模式）
    - clear_file：文件级逐行处理，避免内存压力
    - report：返回结构化报告
    """

    def __init__(
        self,
        *,
        retention_days: int = 90,
        pii_mask: Any | None = None,
        privacy_stripper: Any | None = None,
    ) -> None:
        self._retention_days = int(retention_days) if retention_days and retention_days > 0 else 90
        self._pii_mask = pii_mask
        self._privacy_stripper = privacy_stripper

    # ---------- 过期标记 ----------

    def mark_expired(
        self,
        rows: list[dict],
        *,
        created_at_field: str = "created_at",
        archived_field: str = "is_archived",
    ) -> list[dict]:
        """对 rows 列表中 created_at 早于 retention_days 的记录打 is_archived=True。"""
        if not rows:
            return []
        cutoff = _utc_now().timestamp() - self._retention_days * 86400
        result: list[dict] = []
        for row in rows:
            if not isinstance(row, dict):
                result.append(row)
                continue
            new_row = dict(row)
            ts = _parse_timestamp(new_row.get(created_at_field))
            if ts is not None:
                if ts.timestamp() < cutoff:
                    new_row[archived_field] = True
                else:
                    new_row.setdefault(archived_field, False)
            else:
                new_row.setdefault(archived_field, False)
            result.append(new_row)
        return result

    # ---------- 隐私清除 ----------

    def clear_privacy(self, data: Any, *, mode: str = "delete") -> Any:
        """批量清除结构中的隐私字段。

        mode ∈ {"delete", "mask"}。
        """
        if mode == "delete":
            ps = self._privacy_stripper
            if ps is not None and hasattr(ps, "strip"):
                return ps.strip(data, mode="strip")
            # 退化：依赖 pii_mask auto_mask
            if self._pii_mask is not None and hasattr(self._pii_mask, "auto_mask"):
                return self._pii_mask.auto_mask(data)
            return data
        if mode == "mask":
            pm = self._pii_mask
            if pm is not None and hasattr(pm, "auto_mask"):
                return pm.auto_mask(data)
            return data
        raise ValueError(f"mode 必须是 'delete' 或 'mask'，得到: {mode}")

    # ---------- 文件级清除 ----------

    def clear_file(self, file_path: str, *, output_path: str | None = None, mode: str = "mask") -> dict:
        """逐行处理文本文件，输出到 output_path（默认原文件加 .cleaned）。"""
        if not file_path or not os.path.exists(file_path):
            return {"total_lines": 0, "modified_lines": 0, "output": None, "error": f"文件不存在: {file_path}"}

        if output_path is None:
            output_path = file_path + ".cleaned"

        total = 0
        modified = 0
        try:
            with open(file_path, "r", encoding="utf-8") as fin, open(output_path, "w", encoding="utf-8") as fout:
                for line in fin:
                    total += 1
                    processed = line.rstrip("\n")
                    new_line = line
                    if self._pii_mask is not None and hasattr(self._pii_mask, "_mask_string"):
                        try:
                            masked = self._pii_mask._mask_string(processed)
                        except Exception:
                            masked = processed
                    elif self._privacy_stripper is not None and hasattr(self._privacy_stripper, "strip"):
                        try:
                            masked = str(self._privacy_stripper.strip(processed, mode=mode))
                        except Exception:
                            masked = processed
                    else:
                        masked = processed
                    if masked != processed:
                        modified += 1
                    # 处理敏感词
                    from core.compliance.sensitive_filter import sensitive_filter as _sf
                    if _sf is not None and hasattr(_sf, "filter_text"):
                        try:
                            result = _sf.filter_text(masked)
                            masked = result.cleaned_text or masked
                        except Exception:
                            pass
                    fout.write(masked + "\n")
            return {"total_lines": total, "modified_lines": modified, "output": output_path}
        except Exception as exc:
            logger.warning(f"clear_file 异常: {exc}")
            return {"total_lines": total, "modified_lines": modified, "output": output_path, "error": str(exc)}

    # ---------- 报告 ----------

    def report(self, rows: list[dict] | None = None, *, extra: dict | None = None) -> dict:
        now = _utc_now()
        data = {
            "scan_time": now.isoformat(),
            "retention_days": self._retention_days,
            "scanned_rows": len(rows) if rows is not None else 0,
        }
        if rows:
            archived = sum(1 for r in rows if isinstance(r, dict) and r.get("is_archived"))
            data["archived_rows"] = archived
        if extra:
            data["extra"] = extra
        return data


# =====================
# 模块级单例
# =====================

def _build_default_lifecycle() -> DataLifecycle:
    from core.compliance.pii_mask import pii_mask
    from core.compliance.privacy_stripper import privacy_stripper

    try:
        retention = int(os.environ.get("COMPLIANCE_RETENTION_DAYS", "90"))
    except ValueError:
        retention = 90
    return DataLifecycle(
        retention_days=retention,
        pii_mask=pii_mask,
        privacy_stripper=privacy_stripper,
    )


data_lifecycle: DataLifecycle | None = None
try:
    data_lifecycle = _build_default_lifecycle()
except Exception as exc:
    logger.warning(f"默认 DataLifecycle 初始化失败: {exc}")
    data_lifecycle = DataLifecycle()


__all__ = ["DataLifecycle", "data_lifecycle"]
