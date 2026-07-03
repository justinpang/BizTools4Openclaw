from __future__ import annotations

import os
import re
from collections import Counter
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from infra.logger_setup import get_logger

logger = get_logger("data_core.merge")


# ============================================================
# 数据类
# ============================================================


@dataclass
class MergedClue:
    """合并后的线索。"""
    clue_id: str
    master_source: str
    merged_sources: list[str] = field(default_factory=list)
    company_name: str | None = None
    contact_phones: list[str] = field(default_factory=list)
    contact_wechats: list[str] = field(default_factory=list)
    requirement_text: str = ""
    industry: str | None = None
    platforms: list[str] = field(default_factory=list)
    first_capture_at: str | None = None
    latest_activity_at: str | None = None
    raw_ids: list[int] = field(default_factory=list)
    user_ids: list[str] = field(default_factory=list)
    duplicate_of: str | None = None  # 非主线索 → 指向 master
    _source_members: list[dict] = field(default_factory=list)


@dataclass
class MergeResult:
    merged: list[MergedClue] = field(default_factory=list)  # 主线索列表
    duplicates: list[MergedClue] = field(default_factory=list)  # 冗余线索（指向主线索的 duplicate_of）
    total_input: int = 0
    total_merged: int = 0


# ============================================================
# MergeEngine 主类
# ============================================================


class MergeEngine:
    """跨平台线索合并工具。"""

    def __init__(
        self,
        *,
        max_phones: int | None = None,
        max_wechats: int | None = None,
    ) -> None:
        def _env_int(name: str, default: int) -> int:
            raw = os.environ.get(name)
            if raw is None or raw == "":
                return default
            try:
                return int(raw)
            except ValueError:
                return default

        self._max_phones = max_phones if max_phones is not None else _env_int("MERGE_MAX_PHONES", 3)
        self._max_wechats = max_wechats if max_wechats is not None else _env_int("MERGE_MAX_WECHATS", 3)

    # ---------------- 公共 API ----------------

    def merge_clusters(
        self,
        clues: list[dict[str, Any]],
        clusters: dict[str, list[str]],
    ) -> MergeResult:
        """根据去重引擎给出的簇结构合并线索。

        - `clues`: 原始线索列表，每项含 clue_id 字段
        - `clusters`: 从 DeduplicationResult.clusters 得到的 {master_id: [member_ids]}
        """
        if not clues:
            return MergeResult()

        # 构建 clue_id → clue 字典
        clue_map: dict[str, dict[str, Any]] = {}
        for idx, c in enumerate(clues):
            cid = str(c.get("clue_id") or c.get("id") or f"auto_{idx}")
            clue_map[cid] = c

        result = MergeResult(total_input=len(clues))
        merged_ids: set[str] = set()

        for master_id, member_ids in clusters.items():
            members: list[dict[str, Any]] = []
            for mid in member_ids:
                if mid in clue_map:
                    members.append(clue_map[mid])
            if not members:
                continue

            # 主线索选举
            main_idx = self._elect_master(members)
            main_clue = members[main_idx]

            # 构造主线索 MergedClue
            merged = self._build_merged(main_clue, members)
            merged.clue_id = str(main_clue.get("clue_id") or main_clue.get("id") or f"merged_{len(result.merged)}")
            merged.merged_sources = [
                str(m.get("source_platform") or m.get("source_id") or f"src_{i}")
                for i, m in enumerate(members)
            ]

            result.merged.append(merged)
            merged_ids.update(str(m.get("clue_id") or m.get("id")) for m in members)

            # 非主线索 → 作为 duplicates 记录
            for i, m in enumerate(members):
                if i == main_idx:
                    continue
                dup = self._build_merged(m, [m])
                dup.duplicate_of = merged.clue_id
                dup.clue_id = str(m.get("clue_id") or m.get("id"))
                dup.master_source = merged.master_source
                result.duplicates.append(dup)

        # 未被任何簇包含的线索 → 视为单元素簇，保留为独立主线索
        for cid, c in clue_map.items():
            if cid in merged_ids:
                continue
            merged = self._build_merged(c, [c])
            merged.clue_id = cid
            merged.merged_sources = [str(c.get("source_platform") or c.get("source_id") or cid)]
            result.merged.append(merged)

        result.total_merged = len(result.merged)
        return result

    # ---------------- 主线索选举 ----------------

    def _elect_master(self, members: list[dict[str, Any]]) -> int:
        # 规则：含 company_name 的优先 → 含 phone/wechat 数量最多 → 最近采集时间
        scored: list[tuple[int, int, float]] = []  # (priority, contact_count, -days_old)
        for idx, m in enumerate(members):
            priority = 0
            if m.get("company_name") or m.get("company"):
                priority += 10
            contact_count = (
                len(_as_list(m.get("contact_phone"))) +
                len(_as_list(m.get("phone"))) +
                len(_as_list(m.get("contact_wechat"))) +
                len(_as_list(m.get("wechat")))
            )
            priority += min(contact_count, 5)
            # 时间：越近越高分
            capture_time = m.get("capture_time") or m.get("created_at") or ""
            days_old = _parse_days_old(capture_time) or 0.0
            scored.append((idx, priority, -days_old))

        scored.sort(key=lambda t: (t[1], t[2]), reverse=True)
        return scored[0][0]

    # ---------------- 构造合并后的 MergedClue ----------------

    def _build_merged(self, main: dict[str, Any], members: list[dict[str, Any]]) -> MergedClue:
        # phone / wechat 去重合并
        phones: list[str] = []
        wechats: list[str] = []
        for m in members:
            for p in _as_list(m.get("contact_phone")) + _as_list(m.get("phone")):
                if p and str(p).strip() not in phones:
                    phones.append(str(p).strip())
            for w in _as_list(m.get("contact_wechat")) + _as_list(m.get("wechat")):
                if w and str(w).strip() not in wechats:
                    wechats.append(str(w).strip())

        # 企业名称：最长或出现频次最高的
        company_names = [str(m.get("company_name") or m.get("company") or "").strip() for m in members]
        company_names = [c for c in company_names if c]
        company_name = _pick_most_frequent_or_longest(company_names) if company_names else None

        # 行业：多数投票
        industries = [str(m.get("industry") or "").strip() for m in members if m.get("industry")]
        industry = _pick_most_frequent_or_longest(industries) if industries else None

        # 需求文本：拼接去重
        requirements = [str(m.get("requirement_text") or m.get("requirement") or "").strip() for m in members]
        requirements = [r for r in requirements if r]
        # 去重短句
        seen_reqs: set[str] = set()
        unique_reqs: list[str] = []
        for r in requirements:
            key = r[:80].lower()  # 用前 80 字符的小写版判断重复
            if key not in seen_reqs:
                seen_reqs.add(key)
                unique_reqs.append(r)
        requirement_text = " | ".join(unique_reqs) if unique_reqs else ""

        # 平台
        platforms: list[str] = []
        for m in members:
            p = str(m.get("source_platform") or m.get("platform") or "").strip()
            if p and p not in platforms:
                platforms.append(p)

        # 时间：最早与最近
        capture_times = [
            str(m.get("capture_time") or m.get("created_at") or "").strip()
            for m in members
        ]
        capture_times = [t for t in capture_times if t]

        first_capture: str | None = None
        latest_activity: str | None = None
        if capture_times:
            parsed = [(t, _parse_days_old(t)) for t in capture_times]
            # 最旧（days_old 最大）
            first_capture = max(parsed, key=lambda t: t[1] or 0.0)[0]
            # 最新（days_old 最小）
            latest_activity = min(parsed, key=lambda t: t[1] or 0.0)[0]

        # source raw_ids
        raw_ids: list[int] = []
        for m in members:
            v = m.get("raw_id") or m.get("source_raw_id")
            if isinstance(v, (int, float)) and v == int(v):
                raw_ids.append(int(v))
            elif isinstance(v, str) and v.isdigit():
                raw_ids.append(int(v))

        # user_ids
        user_ids: list[str] = []
        for m in members:
            u = str(m.get("user_id") or "").strip()
            if u and u not in user_ids:
                user_ids.append(u)

        return MergedClue(
            clue_id="",
            master_source=str(main.get("source_platform") or main.get("platform") or "unknown"),
            merged_sources=[],
            company_name=company_name,
            contact_phones=phones[: self._max_phones],
            contact_wechats=wechats[: self._max_wechats],
            requirement_text=requirement_text,
            industry=industry,
            platforms=platforms,
            first_capture_at=first_capture,
            latest_activity_at=latest_activity,
            raw_ids=raw_ids,
            user_ids=user_ids,
        )


# ============================================================
# 辅助函数
# ============================================================


def _as_list(value: Any) -> list[Any]:
    if value is None:
        return []
    if isinstance(value, (list, tuple)):
        return [v for v in value if v is not None]
    return [value]


def _parse_days_old(value: Any) -> float | None:
    if not value:
        return None
    try:
        if isinstance(value, (int, float)):
            ts = float(value)
            # 可能是毫秒
            if ts > 1e12:
                ts = ts / 1000
            from time import time as _now
            return max(0.0, (_now() - ts) / 86400)
        # ISO 字符串
        s = str(value).strip()
        if not s:
            return None
        # 去掉 Z 或尾部
        if s.endswith("Z"):
            s = s[:-1] + "+00:00"
        dt = datetime.fromisoformat(s)
        now = datetime.now(dt.tzinfo) if dt.tzinfo else datetime.now()
        delta = now - dt
        return max(0.0, delta.total_seconds() / 86400)
    except Exception:
        return None


def _pick_most_frequent_or_longest(items: list[str]) -> str | None:
    if not items:
        return None
    counter = Counter(items)
    most_common = counter.most_common()
    if most_common[0][1] >= 2:  # 出现 ≥ 2 次直接选它
        return most_common[0][0]
    # 否则返回最长的
    return max(items, key=len)


# ============================================================
# 模块级单例
# ============================================================


def _build_default_engine() -> MergeEngine:
    return MergeEngine()


merge_engine: MergeEngine
try:
    merge_engine = _build_default_engine()
except Exception as exc:
    logger.warning(f"默认 MergeEngine 初始化失败: {exc}")
    merge_engine = MergeEngine()


__all__ = ["MergedClue", "MergeResult", "MergeEngine", "merge_engine"]
