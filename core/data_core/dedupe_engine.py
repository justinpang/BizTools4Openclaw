from __future__ import annotations

import json
import os
import re
from collections import defaultdict
from dataclasses import dataclass, field
from hashlib import md5
from typing import Any

from infra.logger_setup import get_logger

logger = get_logger("data_core.dedupe")


# ============================================================
# 停用词
# ============================================================

_DEFAULT_STOPWORDS: set[str] = {
    "的", "了", "和", "是", "在", "有", "个", "也", "就", "都", "而", "及",
    "与", "或", "中", "为", "对", "我", "你", "他", "她", "它", "这", "那",
    "着", "过", "被", "把", "让", "给", "到", "说", "做", "吗", "呢", "啊",
    "吧", "的话", "一些", "什么", "怎么", "如何", "哪里", "这个", "那个",
    "这些", "那些", "一下", "一起", "已经", "现在", "目前", "需要", "想要",
    "想", "可以", "能", "能否", "有没有", "是不是",
    "the", "a", "an", "and", "or", "of", "to", "in", "on", "for", "is",
    "are", "was", "were", "it", "this", "that", "with", "by", "from",
}


# ============================================================
# 数据类
# ============================================================


@dataclass
class DedupMatch:
    """两线索之间的匹配结果。"""
    clue_a: str
    clue_b: str
    matched_dimensions: list[str]
    text_similarity: float | None = None


@dataclass
class DeduplicationResult:
    """去重整体结果。"""
    clusters: dict[str, list[str]] = field(default_factory=dict)  # master_clue_id → 所有成员
    matches: list[DedupMatch] = field(default_factory=list)
    total_clues: int = 0
    total_clusters: int = 0


# ============================================================
# 字段标准化工具
# ============================================================


def _normalize_phone(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, (list, tuple)):
        result: list[str] = []
        for v in value:
            result.extend(_normalize_phone(v))
        return _dedup_preserve_order(result)
    s = re.sub(r"\D", "", str(value))
    if s.startswith("86") and len(s) > 11:
        s = s[2:]
    return [s] if len(s) >= 7 else []


def _normalize_wechat(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, (list, tuple)):
        result: list[str] = []
        for v in value:
            result.extend(_normalize_wechat(v))
        return _dedup_preserve_order(result)
    v = str(value).strip().lower()
    for prefix in ("微信号:", "微信号：", "wechat:", "wechat_", "wx:", "wx_"):
        if v.startswith(prefix):
            v = v[len(prefix):]
            break
    v = re.sub(r"\s+", "", v)
    return [v] if len(v) >= 3 else []


def _normalize_user_id(platform: Any, user_id: Any) -> str | None:
    if not user_id:
        return None
    plat = str(platform or "").strip().lower()
    uid = str(user_id).strip()
    if not uid:
        return None
    return f"{plat}|{uid}"


def _dedup_preserve_order(items: list[str]) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for it in items:
        if it and it not in seen:
            seen.add(it)
            out.append(it)
    return out


# ============================================================
# 文本处理（分词 + 2-gram + simhash）
# ============================================================

_URL_RE = re.compile(r"https?://\S+")
_EMAIL_RE = re.compile(r"[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}")
_PHONE_RE = re.compile(r"(?<!\d)(1[3-9]\d{9})(?!\d)")


def _preprocess_text(text: str, stopwords: set[str]) -> str:
    """预处理：去 URL/email/手机号 → 归一化。"""
    if not text:
        return ""
    t = text.lower()
    t = _URL_RE.sub(" ", t)
    t = _EMAIL_RE.sub(" ", t)
    t = _PHONE_RE.sub(" ", t)
    return t.strip()


def _tokenize(text: str, stopwords: set[str]) -> list[str]:
    """分词：中文按字切，英文/数字按非字母数字边界切。"""
    if not text:
        return []
    tokens: list[str] = []
    # 使用正则分段：中文字符单独 / 英文/数字连续
    parts = re.findall(r"[\u4e00-\u9fff]|[A-Za-z0-9]+", text)
    for p in parts:
        if p in stopwords:
            continue
        if len(p) == 1 and p.isascii():
            # 忽略单个英文字符（如 'a'）
            continue
        tokens.append(p)
    return tokens


def _bigrams(tokens: list[str]) -> list[str]:
    if len(tokens) < 2:
        return []
    return [f"{tokens[i]}|{tokens[i+1]}" for i in range(len(tokens) - 1)]


def _jaccard(a: set[str], b: set[str]) -> float:
    if not a and not b:
        return 0.0
    inter = len(a & b)
    union = len(a | b)
    if union == 0:
        return 0.0
    return inter / union


def _text_similarity(a: str, b: str, *, alpha: float, stopwords: set[str]) -> float:
    """Jaccard 词汇 + 2-gram 组合。"""
    tokens_a = _tokenize(_preprocess_text(a, stopwords), stopwords)
    tokens_b = _tokenize(_preprocess_text(b, stopwords), stopwords)
    if not tokens_a or not tokens_b:
        return 0.0
    # 短文本（≤3 token）直接要求完全相等 → 避免 spurious 匹配
    if len(tokens_a) <= 3 and len(tokens_b) <= 3:
        return 1.0 if tokens_a == tokens_b else 0.0

    set_a = set(tokens_a)
    set_b = set(tokens_b)
    j_word = _jaccard(set_a, set_b)
    big_a = set(_bigrams(tokens_a))
    big_b = set(_bigrams(tokens_b))
    j_bigram = _jaccard(big_a, big_b) if big_a or big_b else 0.0
    return alpha * j_word + (1 - alpha) * j_bigram


def _simhash(text: str, stopwords: set[str]) -> int:
    """简单 64-bit simhash，用于分桶。"""
    tokens = _tokenize(_preprocess_text(text, stopwords), stopwords)
    if not tokens:
        return 0
    bits = [0] * 64
    for token in tokens:
        # md5 得到 16 bytes，取前 8 字节作 hash
        h = md5(token.encode("utf-8"), usedforsecurity=False).digest()[:8]
        v = int.from_bytes(h, "big", signed=False)
        for i in range(64):
            bit = (v >> i) & 1
            bits[i] += 1 if bit else -1
    result = 0
    for i in range(64):
        if bits[i] > 0:
            result |= 1 << i
    return result


# ============================================================
# Union-Find (Disjoint Set Union)
# ============================================================


class _UnionFind:
    def __init__(self) -> None:
        self._parent: dict[str, str] = {}

    def find(self, x: str) -> str:
        if x not in self._parent:
            self._parent[x] = x
            return x
        # 路径压缩
        root = x
        while self._parent[root] != root:
            root = self._parent[root]
        while self._parent[x] != root:
            self._parent[x], x = root, self._parent[x]
        return root

    def union(self, a: str, b: str) -> None:
        ra = self.find(a)
        rb = self.find(b)
        if ra != rb:
            # 小挂大（按字典序即可，稳定）
            if ra < rb:
                self._parent[rb] = ra
            else:
                self._parent[ra] = rb

    def clusters(self) -> dict[str, list[str]]:
        groups: dict[str, list[str]] = {}
        for key in self._parent:
            root = self.find(key)
            groups.setdefault(root, []).append(key)
        return groups


# ============================================================
# DedupeEngine
# ============================================================


class DedupeEngine:
    """多维度去重引擎。"""

    def __init__(
        self,
        *,
        text_threshold: float | None = None,
        text_alpha: float | None = None,
        enable_phone: bool | None = None,
        enable_wechat: bool | None = None,
        enable_user_id: bool | None = None,
        enable_text: bool | None = None,
        extra_stopwords: list[str] | None = None,
    ) -> None:
        def _env_bool(name: str, default: bool) -> bool:
            raw = os.environ.get(name)
            if raw is None:
                return default
            return str(raw).strip().lower() not in ("0", "false", "no", "off", "")

        def _env_float(name: str, default: float) -> float:
            raw = os.environ.get(name)
            if raw is None or raw == "":
                return default
            try:
                return float(raw)
            except ValueError:
                return default

        self._text_threshold = text_threshold if text_threshold is not None else _env_float(
            "DEDUPE_TEXT_THRESHOLD", 0.70
        )
        self._text_alpha = text_alpha if text_alpha is not None else _env_float(
            "DEDUPE_SIM_ALPHA", 0.50
        )
        self._enable_phone = enable_phone if enable_phone is not None else _env_bool("DEDUPE_PHONE_ENABLE", True)
        self._enable_wechat = enable_wechat if enable_wechat is not None else _env_bool("DEDUPE_WECHAT_ENABLE", True)
        self._enable_user_id = enable_user_id if enable_user_id is not None else _env_bool("DEDUPE_USERID_ENABLE", True)
        self._enable_text = enable_text if enable_text is not None else _env_bool("DEDUPE_TEXT_ENABLE", True)

        self._stopwords: set[str] = set(_DEFAULT_STOPWORDS)
        if extra_stopwords:
            for w in extra_stopwords:
                if w:
                    self._stopwords.add(w)

        # 加载 stopwords 自定义文件
        sw_file = os.environ.get("BLACKLIST_STOPWORDS_FILE")
        if sw_file and os.path.exists(sw_file):
            try:
                with open(sw_file, "r", encoding="utf-8") as f:
                    for line in f:
                        line = line.strip()
                        if line and not line.startswith("#"):
                            self._stopwords.add(line)
            except Exception as exc:
                logger.warning(f"加载停用词文件失败: {exc}")

    # ------------------------ 公共 API ------------------------

    def deduplicate(self, clues: list[dict[str, Any]]) -> DeduplicationResult:
        """对线索列表去重。

        步骤：
          1. 为每条线索生成 id（用 clue_id；未提供则用 index）。
          2. 按 phone/wechat/user_id/simhash 分桶。
          3. 同一分桶内做两两精细比较；任何维度匹配即合并到同一簇。
        """
        if not clues:
            return DeduplicationResult()

        # 预处理 + 生成 id
        processed: list[tuple[str, dict[str, Any]]] = []
        for idx, c in enumerate(clues):
            cid = str(c.get("clue_id") or c.get("id") or f"auto_{idx}")
            processed.append((cid, c))

        uf = _UnionFind()
        for cid, _c in processed:
            uf.find(cid)  # 确保加入

        matches: list[DedupMatch] = []

        # 哈希分桶
        buckets_phone: dict[str, list[str]] = defaultdict(list)
        buckets_wechat: dict[str, list[str]] = defaultdict(list)
        buckets_user_id: dict[str, list[str]] = defaultdict(list)
        buckets_text: dict[str, list[str]] = defaultdict(list)

        for cid, c in processed:
            if self._enable_phone:
                for p in _normalize_phone(c.get("contact_phone")) + _normalize_phone(c.get("phone")):
                    buckets_phone[p[:10]].append(cid)
            if self._enable_wechat:
                for w in _normalize_wechat(c.get("contact_wechat")) + _normalize_wechat(c.get("wechat")):
                    buckets_wechat[w].append(cid)
            if self._enable_user_id:
                key = _normalize_user_id(c.get("source_platform") or c.get("platform"), c.get("user_id"))
                if key:
                    buckets_user_id[key].append(cid)
            if self._enable_text:
                text = str(c.get("requirement_text") or c.get("requirement") or "")
                if text.strip():
                    sh = _simhash(text, self._stopwords)
                    # 取前 16-bit 作为桶 key
                    bucket_key = str(sh >> 48 & 0xFFFF) if sh else "none"
                    buckets_text[bucket_key].append(cid)

        # 比较函数
        def _fine_compare(a_cid: str, a: dict[str, Any], b_cid: str, b: dict[str, Any]) -> list[str]:
            matched: list[str] = []
            if self._enable_phone:
                a_phones = set(
                    _normalize_phone(a.get("contact_phone")) + _normalize_phone(a.get("phone"))
                )
                b_phones = set(
                    _normalize_phone(b.get("contact_phone")) + _normalize_phone(b.get("phone"))
                )
                if a_phones and b_phones and a_phones & b_phones:
                    matched.append("phone")
            if self._enable_wechat:
                a_wx = set(_normalize_wechat(a.get("contact_wechat")) + _normalize_wechat(a.get("wechat")))
                b_wx = set(_normalize_wechat(b.get("contact_wechat")) + _normalize_wechat(b.get("wechat")))
                if a_wx and b_wx and a_wx & b_wx:
                    matched.append("wechat")
            if self._enable_user_id:
                a_uid = _normalize_user_id(a.get("source_platform") or a.get("platform"), a.get("user_id"))
                b_uid = _normalize_user_id(b.get("source_platform") or b.get("platform"), b.get("user_id"))
                if a_uid and b_uid and a_uid == b_uid:
                    matched.append("user_id")
            if self._enable_text:
                a_text = str(a.get("requirement_text") or a.get("requirement") or "")
                b_text = str(b.get("requirement_text") or b.get("requirement") or "")
                if a_text and b_text:
                    sim = _text_similarity(a_text, b_text, alpha=self._text_alpha, stopwords=self._stopwords)
                    if sim >= self._text_threshold:
                        matched.append("text")
            return matched

        # 扫描每个桶
        processed_map = dict(processed)
        processed_pairs: set[tuple[str, str]] = set()

        for bucket_dict in (buckets_phone, buckets_wechat, buckets_user_id, buckets_text):
            for bucket_key, members in bucket_dict.items():
                if len(members) < 2:
                    continue
                for i in range(len(members)):
                    for j in range(i + 1, len(members)):
                        a_cid, b_cid = members[i], members[j]
                        pair_key = (a_cid, b_cid) if a_cid < b_cid else (b_cid, a_cid)
                        if pair_key in processed_pairs:
                            continue
                        processed_pairs.add(pair_key)
                        matched = _fine_compare(a_cid, processed_map[a_cid], b_cid, processed_map[b_cid])
                        if matched:
                            uf.union(a_cid, b_cid)
                            matches.append(
                                DedupMatch(
                                    clue_a=a_cid,
                                    clue_b=b_cid,
                                    matched_dimensions=matched,
                                )
                            )

        clusters = uf.clusters()
        return DeduplicationResult(
            clusters=clusters,
            matches=matches,
            total_clues=len(processed),
            total_clusters=len(clusters),
        )

    def text_similarity(self, a: str, b: str) -> float:
        """对外公开的文本相似度计算函数。"""
        return _text_similarity(a, b, alpha=self._text_alpha, stopwords=self._stopwords)


# ============================================================
# 模块级单例
# ============================================================


def _build_default_engine() -> DedupeEngine:
    return DedupeEngine()


dedupe_engine: DedupeEngine
try:
    dedupe_engine = _build_default_engine()
except Exception as exc:
    logger.warning(f"默认 DedupeEngine 初始化失败: {exc}")
    dedupe_engine = DedupeEngine()


__all__ = ["DedupMatch", "DeduplicationResult", "DedupeEngine", "dedupe_engine"]
