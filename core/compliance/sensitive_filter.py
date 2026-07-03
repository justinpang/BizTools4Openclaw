from __future__ import annotations

import json
import os
import threading
from collections import deque
from dataclasses import dataclass, field
from typing import Iterable

from infra.logger_setup import get_logger

logger = get_logger("compliance.sensitive_filter")


# =====================
# 风险等级常量
# =====================
RISK_LOW = "low"
RISK_MEDIUM = "medium"
RISK_HIGH = "high"

_RISK_LEVEL = {RISK_LOW: 0, RISK_MEDIUM: 1, RISK_HIGH: 2}


# =====================
# 数据类
# =====================

@dataclass
class SensitiveHit:
    """单个敏感词命中。"""
    word: str              # 词库中规范化的词
    fragment: str          # 在原文中的片段（保留原始大小写）
    start: int             # 原文中起始索引
    end: int               # 原文中结束索引
    category: str          # advertising / violation / political / custom
    risk: str              # low / medium / high


@dataclass
class FilterResult:
    """过滤结果。"""
    text: str
    hits: list[SensitiveHit] = field(default_factory=list)
    cleaned_text: str = ""
    risk: str = RISK_LOW
    is_blocked: bool = False

    def to_dict(self) -> dict:
        return {
            "text": self.text,
            "hits": [
                {
                    "word": h.word,
                    "fragment": h.fragment,
                    "start": h.start,
                    "end": h.end,
                    "category": h.category,
                    "risk": h.risk,
                }
                for h in self.hits
            ],
            "cleaned_text": self.cleaned_text,
            "risk": self.risk,
            "is_blocked": self.is_blocked,
        }


# =====================
# 内置词库（示意通用词，非真实敏感样例）
# =====================

# 每条 (word, category, risk)
_BUILTIN_BADWORDS: list[tuple[str, str, str]] = [
    # --- 广告类 (medium) ---
    ("加微信", "advertising", RISK_MEDIUM),
    ("加QQ", "advertising", RISK_MEDIUM),
    ("加v", "advertising", RISK_MEDIUM),
    ("加粉", "advertising", RISK_MEDIUM),
    ("代开发", "advertising", RISK_MEDIUM),
    ("代写论文", "advertising", RISK_MEDIUM),
    ("代写", "advertising", RISK_MEDIUM),
    ("刷钻", "advertising", RISK_MEDIUM),
    ("流量充值", "advertising", RISK_MEDIUM),
    ("兼职日结", "advertising", RISK_MEDIUM),
    ("v信", "advertising", RISK_MEDIUM),

    # --- 违规类 (high) ---
    ("博彩", "violation", RISK_HIGH),
    ("线上赌场", "violation", RISK_HIGH),
    ("澳门赌场", "violation", RISK_HIGH),
    ("枪支", "violation", RISK_HIGH),
    ("毒品", "violation", RISK_HIGH),
    ("色情", "violation", RISK_HIGH),
    ("黄色小说", "violation", RISK_HIGH),
    ("代孕", "violation", RISK_HIGH),
    ("洗钱", "violation", RISK_HIGH),
    ("假币", "violation", RISK_HIGH),
    ("办证", "violation", RISK_HIGH),
    ("黑产", "violation", RISK_HIGH),

    # --- 涉敏政治类 (high) ---
    ("反政府", "political", RISK_HIGH),
    ("颠覆国家", "political", RISK_HIGH),
    ("台独", "political", RISK_HIGH),
    ("港独", "political", RISK_HIGH),
    ("藏独", "political", RISK_HIGH),
    ("疆独", "political", RISK_HIGH),
]


# =====================
# AC 自动机节点
# =====================

class _Node:
    __slots__ = ("next", "fail", "outputs")

    def __init__(self) -> None:
        self.next: dict[str, int] = {}
        self.fail: int = 0
        self.outputs: list[tuple[str, str, str]] = []  # (word, category, risk)


class _AhoCorasick:
    """手写 Aho-Corasick 自动机。"""

    def __init__(self) -> None:
        self._nodes: list[_Node] = [_Node()]  # 节点 0 为根

    # ------- 构建 -------
    def add_word(self, word: str, category: str, risk: str) -> None:
        if not word:
            return
        node_idx = 0
        for ch in word:
            nxt = self._nodes[node_idx].next
            if ch not in nxt:
                self._nodes.append(_Node())
                nxt[ch] = len(self._nodes) - 1
            node_idx = nxt[ch]
        self._nodes[node_idx].outputs.append((word, category, risk))

    def build(self) -> None:
        """BFS 建立 fail 指针。"""
        q: deque[int] = deque()
        root = self._nodes[0]
        # 根的直接子节点 fail=0，入队
        for ch, child_idx in root.next.items():
            self._nodes[child_idx].fail = 0
            q.append(child_idx)
        while q:
            cur = q.popleft()
            cur_node = self._nodes[cur]
            for ch, child_idx in cur_node.next.items():
                # 找 fail 指针
                f = cur_node.fail
                while f != 0 and ch not in self._nodes[f].next:
                    f = self._nodes[f].fail
                self._nodes[child_idx].fail = (
                    self._nodes[f].next[ch] if ch in self._nodes[f].next and self._nodes[f].next[ch] != child_idx else 0
                )
                # 合并 outputs（fail链上）
                fail_node = self._nodes[self._nodes[child_idx].fail]
                if fail_node.outputs:
                    cur_child = self._nodes[child_idx]
                    # 去重
                    seen: set[tuple[str, str, str]] = set(cur_child.outputs)
                    for out in fail_node.outputs:
                        if out not in seen:
                            cur_child.outputs.append(out)
                q.append(child_idx)

    # ------- 扫描 -------
    def scan(self, text: str) -> list[tuple[str, str, str, int, int]]:
        """扫描文本，返回 [(word, category, risk, start, end), ...]。"""
        results: list[tuple[str, str, str, int, int]] = []
        node_idx = 0
        for i, ch in enumerate(text):
            # 失配跳转
            while node_idx != 0 and ch not in self._nodes[node_idx].next:
                node_idx = self._nodes[node_idx].fail
            if ch in self._nodes[node_idx].next:
                node_idx = self._nodes[node_idx].next[ch]
            else:
                node_idx = 0  # 根节点也没匹配
            # outputs
            for word, category, risk in self._nodes[node_idx].outputs:
                wlen = len(word)
                start = i - wlen + 1
                results.append((word, category, risk, start, i + 1))
        return results


# =====================
# SensitiveFilter 类
# =====================

class SensitiveFilter:
    """敏感词过滤引擎。

    - 使用内置词库 + 可选外部词库文件（每行一个或 JSON 数组）
    - AC 自动机 O(n) 扫描
    - 支持大小写不敏感、中文多词同时命中
    """

    def __init__(
        self,
        *,
        mask_char: str = "*",
        mask_length: int = 3,
        block_threshold: str = RISK_MEDIUM,
        custom_words_file: str | None = None,
        words: Iterable[tuple[str, str, str]] | None = None,
    ) -> None:
        self._mask_char = mask_char or "*"
        self._mask_len = int(mask_length) if mask_length and mask_length > 0 else 3
        self._block_threshold = block_threshold if block_threshold in _RISK_LEVEL else RISK_MEDIUM
        self._ac_cased = _AhoCorasick()   # 中文 / 大小写敏感原始扫描
        self._ac_nocase = _AhoCorasick()  # 大小写不敏感扫描
        self._word_meta: dict[str, tuple[str, str]] = {}  # word(casefold) → (category, risk)
        self._lock = threading.RLock()

        # 装载内置词库
        for word, category, risk in _BUILTIN_BADWORDS:
            self._register(word, category, risk)

        # 运行时注入
        if words:
            for item in words:
                if len(item) >= 3:
                    self._register(str(item[0]), str(item[1]), str(item[2]))

        # 装载外部文件
        if custom_words_file:
            try:
                self.load_file(custom_words_file)
            except Exception as exc:
                logger.warning(f"装载外部词库文件失败: {exc}")

        # 根据已注册的 word_meta 构建两份 AC 自动机（大小写敏感与不敏感）
        # 注：对中文而言 casefold 与原字相同，两份自动机行为一致；
        #     对英文/数字/符号，ac_nocase 使用 casefold 后的文本做扫描
        with self._lock:
            self._ac_cased = _rebuild_ac(self._word_meta, case_sensitive=True)
            self._ac_nocase = _rebuild_ac(self._word_meta, case_sensitive=False)

    # -------- 词库管理 --------

    def add_word(self, word: str, *, category: str = "custom", risk: str = RISK_LOW) -> None:
        self._register(word, category, risk)
        with self._lock:
            self._ac_cased = _rebuild_ac(self._word_meta, case_sensitive=True)
            self._ac_nocase = _rebuild_ac(self._word_meta, case_sensitive=False)

    def add_words(self, items: Iterable[tuple[str, str, str]]) -> None:
        count = 0
        for item in items:
            if len(item) >= 3:
                self._register(str(item[0]), str(item[1]), str(item[2]))
                count += 1
        if count > 0:
            with self._lock:
                self._ac_cased = _rebuild_ac(self._word_meta, case_sensitive=True)
                self._ac_nocase = _rebuild_ac(self._word_meta, case_sensitive=False)

    def load_file(self, path: str) -> None:
        """文件格式：
        - 一行一个词：word[,category][,risk]
        - 或以 JSON 数组格式：[{"word": "...", "category": "...", "risk": "..."}]
        - `#` 开头为注释
        """
        if not path or not os.path.exists(path):
            logger.warning(f"词库文件不存在: {path}")
            return
        count = 0
        with open(path, "r", encoding="utf-8") as f:
            content = f.read().strip()
        if content.startswith("["):
            # 尝试 JSON 数组
            try:
                items = json.loads(content)
                if isinstance(items, list):
                    for item in items:
                        if isinstance(item, dict):
                            w = str(item.get("word", "") or item.get("text", ""))
                            c = str(item.get("category", "custom"))
                            r = str(item.get("risk", RISK_LOW))
                        elif isinstance(item, (list, tuple)) and len(item) >= 1:
                            w = str(item[0])
                            c = str(item[1]) if len(item) >= 2 else "custom"
                            r = str(item[2]) if len(item) >= 3 else RISK_LOW
                        else:
                            continue
                        if w:
                            self._register(w, c, r)
                            count += 1
            except json.JSONDecodeError:
                # 回退为纯文本
                for line in content.splitlines():
                    line = line.strip()
                    if not line or line.startswith("#"):
                        continue
                    parts = [p.strip() for p in line.split(",")]
                    w = parts[0]
                    c = parts[1] if len(parts) >= 2 else "custom"
                    r = parts[2] if len(parts) >= 3 else RISK_LOW
                    self._register(w, c, r)
                    count += 1
        else:
            for line in content.splitlines():
                line = line.strip()
                if not line or line.startswith("#"):
                    continue
                parts = [p.strip() for p in line.split(",")]
                w = parts[0]
                c = parts[1] if len(parts) >= 2 else "custom"
                r = parts[2] if len(parts) >= 3 else RISK_LOW
                self._register(w, c, r)
                count += 1
        if count > 0:
            with self._lock:
                self._ac_cased = _rebuild_ac(self._word_meta, case_sensitive=True)
                self._ac_nocase = _rebuild_ac(self._word_meta, case_sensitive=False)
            logger.info(f"装载 {count} 个自定义敏感词（{path}）")

    # -------- 核心检测 / 清洗 --------

    def detect(self, text: str) -> list[SensitiveHit]:
        if not text:
            return []
        # 大小写不敏感扫描（英文）；同时保留原文片段
        with self._lock:
            raw_results = self._ac_nocase.scan(text.casefold())
        hits: list[SensitiveHit] = []
        for word_cf, category, risk, start, end in raw_results:
            fragment = text[start:end]
            hits.append(SensitiveHit(
                word=word_cf,
                fragment=fragment,
                start=start,
                end=end,
                category=category,
                risk=risk,
            ))
        hits.sort(key=lambda h: (h.start, -h.end))
        return _dedupe_overlaps(hits)

    def filter_text(self, text: str) -> FilterResult:
        if not text:
            return FilterResult(text="", hits=[], cleaned_text="", risk=RISK_LOW, is_blocked=False)
        hits = self.detect(text)
        # 按 start 排序后，用 mask 替换命中区间
        cleaned = _apply_mask(text, hits, self._mask_char * max(1, self._mask_len))
        top_risk = _top_risk([h.risk for h in hits])
        is_blocked = _RISK_LEVEL.get(top_risk, 0) >= _RISK_LEVEL.get(self._block_threshold, 1)
        return FilterResult(
            text=text,
            hits=hits,
            cleaned_text=cleaned,
            risk=top_risk,
            is_blocked=is_blocked,
        )

    def highlight(self, text: str, *, open_tag: str = "<mark>", close_tag: str = "</mark>") -> str:
        if not text:
            return ""
        hits = self.detect(text)
        if not hits:
            return text
        parts: list[str] = []
        last = 0
        for h in hits:
            if h.start >= last:
                parts.append(text[last:h.start])
                parts.append(open_tag + h.fragment + close_tag)
                last = h.end
        parts.append(text[last:])
        return "".join(parts)

    def is_blocked(self, text: str) -> bool:
        if not text:
            return False
        result = self.filter_text(text)
        return result.is_blocked

    # -------- 内部辅助 --------

    def _register(self, word: str, category: str, risk: str) -> None:
        if not word:
            return
        cf = word.casefold()
        # 保存规范化的元信息；若重复则保留最高 risk
        if cf in self._word_meta:
            existing_cat, existing_risk = self._word_meta[cf]
            if _RISK_LEVEL.get(risk, 0) > _RISK_LEVEL.get(existing_risk, 0):
                self._word_meta[cf] = (category or existing_cat, risk)
        else:
            self._word_meta[cf] = (category or "custom", risk or RISK_LOW)


# =====================
# 模块级辅助函数
# =====================

def _rebuild_ac(word_meta: dict[str, tuple[str, str]], *, case_sensitive: bool) -> _AhoCorasick:
    ac = _AhoCorasick()
    for cf_word, (category, risk) in word_meta.items():
        w = cf_word if case_sensitive else cf_word
        ac.add_word(w, category, risk)
    ac.build()
    return ac


def _top_risk(risks: list[str]) -> str:
    level = -1
    top = RISK_LOW
    for r in risks:
        lv = _RISK_LEVEL.get(r, 0)
        if lv > level:
            level = lv
            top = r
    return top


def _dedupe_overlaps(hits: list[SensitiveHit]) -> list[SensitiveHit]:
    """去除 start 相同或完全包含的重复命中。"""
    if not hits:
        return hits
    kept: list[SensitiveHit] = []
    for h in hits:
        # 与最后一条比较：若重叠就取更长的那个
        if kept and h.start < kept[-1].end:
            prev = kept[-1]
            if h.end - h.start > prev.end - prev.start:
                kept[-1] = h
            continue
        kept.append(h)
    return kept


def _apply_mask(text: str, hits: list[SensitiveHit], mask_repl: str) -> str:
    if not hits:
        return text
    parts: list[str] = []
    last = 0
    for h in hits:
        if h.start >= last:
            parts.append(text[last:h.start])
            parts.append(mask_repl)
            last = h.end
    parts.append(text[last:])
    return "".join(parts)


# =====================
# 模块级单例（从 .env 加载）
# =====================

def _build_default_filter() -> SensitiveFilter:
    mask_char = os.environ.get("SENSITIVE_MASK_CHAR", "*")
    try:
        mask_len = int(os.environ.get("SENSITIVE_MASK_LEN", "3"))
    except ValueError:
        mask_len = 3
    block_threshold = os.environ.get("SENSITIVE_BLOCK_THRESHOLD", RISK_MEDIUM)
    custom_file = os.environ.get("SENSITIVE_WORDS_FILE") or None
    return SensitiveFilter(
        mask_char=mask_char,
        mask_length=mask_len,
        block_threshold=block_threshold,
        custom_words_file=custom_file,
    )


sensitive_filter: SensitiveFilter | None = None
try:
    sensitive_filter = _build_default_filter()
except Exception as exc:
    logger.warning(f"默认 SensitiveFilter 初始化失败: {exc}")
    sensitive_filter = SensitiveFilter()


__all__ = [
    "RISK_LOW", "RISK_MEDIUM", "RISK_HIGH",
    "SensitiveHit", "FilterResult",
    "SensitiveFilter", "sensitive_filter",
]
