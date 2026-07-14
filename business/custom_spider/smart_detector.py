"""T31: 列表智能识别 & 自动选最新。

职责
----
* 输入一段 HTML 或 DOM，自动给出：
    1. Top N 候选 ``item_selector``（容器识别 + 打分）
    2. Top N 候选 ``time_selector``（时间字段识别 + 格式推测）
    3. 按 publish_time 倒序排列的条目列表
    4. 根据采集范围模式 ``latest | top_n | all`` 筛选
* 识别失败时返回 ``degrade_reason``，供前端降级为手动填写。

不修改/调用 core.spider_core 底层解析逻辑，纯 Python + BeautifulSoup。
对缺失依赖（bs4）做容错处理：不崩溃，返回明确错误提示。
"""

from __future__ import annotations

import re
import time
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple

try:
    from bs4 import BeautifulSoup, Tag
    _HAS_BS4 = True
except Exception:  # pragma: no cover - 依赖缺失时容错
    BeautifulSoup = None  # type: ignore
    Tag = None            # type: ignore
    _HAS_BS4 = False


# ============================================================================
# 时间字段正则
# ============================================================================
# 匹配顺序：最具体模式优先，避免部分匹配误判
_TIME_PATTERNS: List[Tuple[re.Pattern, str]] = [
    # 2024-01-02 / 2024/01/02 / 2024.01.02 / 2024年1月2日
    (re.compile(r"(\d{4})[-/年\.](\d{1,2})[-/月\.](\d{1,2})"), "%Y-%m-%d"),
    # 2024-01-02 10:20 / 2024年1月2日 10:20
    (re.compile(r"(\d{4})[-/年\.](\d{1,2})[-/月\.](\d{1,2})\s*(\d{1,2})[:时](\d{1,2})"), "%Y-%m-%d %H:%M"),
    # 01-02-2024 / 1.2.24
    (re.compile(r"(\d{1,2})[-/\.](\d{1,2})[-/\.](\d{2,4})"), "%d-%m-%Y"),
    # 20240102
    (re.compile(r"(?<!\d)(20\d{6})(?!\d)"), "%Y%m%d"),
]

_TIME_KEYWORD_PATTERN = re.compile(
    r"(发布时间|发布日期|时间|日期|更新时间|Updated|Published|Date)[^<\n]{0,30}([^<\n]{8,40})",
    re.IGNORECASE,
)


# ============================================================================
# 内部数据结构
# ============================================================================
@dataclass
class _ContainerScore:
    selector: str
    item_count: int
    avg_text_len: float
    link_density: float
    score: float


@dataclass
class _TimeField:
    selector: str
    sample_values: List[str]
    format_hint: str
    hit_count: int


@dataclass
class _ListItem:
    title: str
    link: str
    raw_time: str
    parsed_time: Optional[datetime]
    original_index: int


# ============================================================================
# SmartDetector
# ============================================================================
class SmartDetector:
    """列表 + 时间字段智能识别。"""

    def __init__(self) -> None:
        self.last_html: Optional[str] = None
        self.last_soup: Optional[Any] = None

    # ------------------------------------------------------------ 公共 API
    def detect_all(self, html: str, target_url: Optional[str] = None) -> Dict[str, Any]:
        """对一段 HTML 做完整分析，返回约定格式的 dict。"""
        self.last_html = html or ""

        if not _HAS_BS4:
            return {
                "success": False,
                "containers": [],
                "time_fields": [],
                "items": [],
                "item_count_total": 0,
                "confidence": 0.0,
                "crawl_scope_suggestion": "top_n",
                "degrade_reason": "missing_dependency: BeautifulSoup 未安装，请先 pip install beautifulsoup4",
                "target_url": target_url,
            }

        if not html or not html.strip():
            return {
                "success": False,
                "containers": [],
                "time_fields": [],
                "items": [],
                "item_count_total": 0,
                "confidence": 0.0,
                "crawl_scope_suggestion": "top_n",
                "degrade_reason": "empty_html: 输入为空，无法识别",
                "target_url": target_url,
            }

        soup = BeautifulSoup(self.last_html, "html.parser")
        self.last_soup = soup

        # 阶段 1: 容器识别
        containers = self._detect_containers(soup)
        best_container = containers[0] if containers else None

        # 阶段 2: 时间字段识别
        item_nodes: List[Any] = []
        if best_container is not None:
            item_nodes = self._find_item_nodes(soup, best_container.selector)
        time_fields = self._detect_time_fields(item_nodes) if item_nodes else self._detect_time_fields_text(soup)

        # 阶段 3: 条目抽取 & 排序
        items = self._extract_items(item_nodes, time_fields[0] if time_fields else None)
        sorted_items = sorted(
            items,
            key=lambda it: (it.parsed_time is None, it.parsed_time or datetime.min, -it.original_index),
            reverse=True,
        )

        # 阶段 4: 置信度评估
        confidence = self._calc_confidence(containers, time_fields, items)

        # 阶段 5: 建议的采集范围
        if confidence >= 0.7 and time_fields and any(it.parsed_time for it in sorted_items):
            scope_suggestion = "latest"
        elif items:
            scope_suggestion = "top_n"
        else:
            scope_suggestion = "all"

        # 降级判定
        degrade_reason: Optional[str] = None
        if not containers:
            degrade_reason = "no_container: 未能识别出任何候选列表容器"
        elif not items:
            degrade_reason = "no_items: 候选容器内未发现可解析的条目"
        elif confidence < 0.3:
            degrade_reason = f"low_confidence: 识别置信度仅 {confidence:.2f}, 建议人工复核选择器"

        # 组装输出（对中文/数字做 JSON 安全的字符串化）
        containers_out = [
            {
                "selector": cs.selector,
                "item_count": cs.item_count,
                "confidence": round(cs.score, 3),
                "sample_titles": [],  # 留给前端在 items 中展示
            }
            for cs in containers[:3]
        ]
        time_fields_out = [
            {
                "selector": tf.selector,
                "format_hint": tf.format_hint,
                "sample_values": tf.sample_values[:3],
                "confidence": round(min(tf.hit_count / max(1, len(items or [0])), 1.0), 3),
            }
            for tf in time_fields[:3]
        ]
        items_out = [
            {
                "title": it.title,
                "link": it.link,
                "publish_time_iso": (
                    it.parsed_time.strftime("%Y-%m-%d %H:%M:%S") if it.parsed_time else ""
                ),
                "_raw_time": it.raw_time,
            }
            for it in sorted_items[:200]
        ]

        return {
            "success": True,
            "containers": containers_out,
            "time_fields": time_fields_out,
            "items": items_out,
            "item_count_total": len(items),
            "confidence": round(confidence, 3),
            "crawl_scope_suggestion": scope_suggestion,
            "degrade_reason": degrade_reason,
            "target_url": target_url,
        }

    # ------------------------------------------------------------ 阶段 1: 容器识别
    def _detect_containers(self, soup: Any) -> List[_ContainerScore]:
        """在 DOM 中寻找若干候选列表容器。

        多策略探测：
        - 策略 A：直接子节点为多个 <a>/<li>/<div>
        - 策略 B：直接子节点含链接的 div/ul/ol
        """
        candidates: List[_ContainerScore] = []

        # ---- 策略 A：查找多子节点的容器
        tags_to_try = ["ul", "ol", "table", "div", "section", "article"]
        for tag_name in tags_to_try:
            for el in soup.find_all(tag_name):
                children = [c for c in el.children if isinstance(c, Tag)]
                if len(children) < 2:
                    continue

                item_count = len(children)

                # 平均文本长度
                total_text = 0
                for c in children:
                    text = (c.get_text(" ", strip=True) or "").strip()
                    total_text += len(text)
                avg_text_len = total_text / max(1, item_count)

                # 链接密度
                link_count = sum(1 for c in children if c.find("a"))
                link_density = link_count / max(1, item_count)

                # 加权评分
                score = (
                    min(item_count, 50) / 50.0 * 0.35
                    + min(avg_text_len, 200) / 200.0 * 0.35
                    + link_density * 0.30
                )

                # 用标签 + class 构造选择器
                cls = el.get("class")
                cls_sel = "." + ".".join(cls) if cls else ""
                selector = f"{tag_name}{cls_sel}"

                candidates.append(_ContainerScore(
                    selector=selector,
                    item_count=item_count,
                    avg_text_len=avg_text_len,
                    link_density=link_density,
                    score=score,
                ))

        # ---- 策略 B：从 <a> 标签反向探测其所属父容器
        try:
            for a_tag in soup.find_all("a"):
                parent = a_tag.parent
                if parent is None:
                    continue
                p_tag = parent.name
                if p_tag is None:
                    continue
                if str(p_tag).lower() in ["ul", "ol", "table", "div", "li"]:
                    continue
                p_children = [c for c in parent.children if isinstance(c, Tag)]
                if len(p_children) < 2:
                    continue
                p_parent_text = parent.get_text(" ", strip=True) or ""
                p_parent_link_count = sum(1 for c in p_children if c.find("a"))
                p_parent_link_density = p_parent_link_count / max(1, len(p_children))
                p_parent_avg_text = len(p_parent_text) / max(1, len(p_children))
                p_parent_score = (
                    min(len(p_children), 50) / 50.0 * 0.35
                    + min(p_parent_avg_text, 200) / 200.0 * 0.35
                    + p_parent_link_density * 0.30
                )
                p_parent_cls = parent.get("class")
                p_parent_cls_sel = "." + ".".join(p_parent_cls) if p_parent_cls else ""
                p_parent_selector = f"{p_tag}{p_parent_cls_sel}"
                candidates.append(_ContainerScore(
                    selector=p_parent_selector,
                    item_count=len(p_children),
                    avg_text_len=p_parent_avg_text,
                    link_density=p_parent_link_density,
                    score=p_parent_score,
                ))
        except Exception:
            pass

        # 去重（相同 selector 的多次结果合并）
        dedup: Dict[str, _ContainerScore] = {}
        for c in candidates:
            if c.selector not in dedup or dedup[c.selector].score < c.score:
                dedup[c.selector] = c

        return sorted(dedup.values(), key=lambda c: c.score, reverse=True)[:5]

    # ------------------------------------------------------------ 工具：按选择器找条目子节点
    def _find_item_nodes(self, soup: Any, selector: str) -> List[Any]:
        """给定形如 ``ul.item-list`` 的选择器，返回容器下的直接子条目节点。

        改进：
        - 对多个匹配的容器都取其直接子节点
        - 对像 div > div.wrap > div.item 这样的嵌套结构也能拿到条目
        """
        if not selector or not soup:
            return []
        try:
            containers = soup.select(selector)
        except Exception:
            containers = []
        if not containers:
            return []

        all_children: List[Any] = []
        for container in containers:
            if not container:
                continue
            # 直接子节点
            children = [c for c in container.children if isinstance(c, Tag)]
            if children:
                all_children.extend(children)
                continue
            # 回退：找容器内的 li/a/div/article 等条目
            for tag_name in ["li", "a", "article", "div", "tr", "span"]:
                more = container.find_all(tag_name, recursive=False)
                if more:
                    all_children.extend([c for c in more if isinstance(c, Tag)])
                    break
            # 再回退：下一层递归查找
            if not all_children:
                for c in container.children:
                    if isinstance(c, Tag):
                        sub_children = [sc for sc in c.children if isinstance(sc, Tag)]
                        all_children.extend(sub_children)
        return all_children

    # ------------------------------------------------------------ 阶段 2: 时间字段识别（在条目内）
    def _detect_time_fields(self, item_nodes: List[Any]) -> List[_TimeField]:
        """对条目内的文本做模式匹配，找到最常见的时间字段。"""
        hits_by_pattern_index: Dict[int, List[str]] = {i: [] for i in range(len(_TIME_PATTERNS))}
        # 为每个条目记录可能的"时间所在元素"：记录元素路径 + 值
        field_hit_count: Dict[str, List[str]] = {}

        for item in item_nodes:
            text_blocks: List[Tuple[str, Optional[Tag]]] = []  # (text, tag_ref)
            # 直接文本
            direct = (item.get_text(" ", strip=True) or "").strip()
            if direct:
                text_blocks.append((direct, item))
            # 子节点文本
            for child in item.find_all(recursive=True):
                t = (child.get_text(strip=True) or "").strip()
                if 6 <= len(t) <= 50:
                    text_blocks.append((t, child))

            for text, _tag in text_blocks:
                for pat_idx, (pat, fmt) in enumerate(_TIME_PATTERNS):
                    m = pat.search(text)
                    if m:
                        hits_by_pattern_index[pat_idx].append(text.strip())
                        # 构造简易选择器：tag.class + nth-child 级别不做，用 content 文本提示
                        sel = f"{(_tag.name if _tag else 'span')}[contains-time]"
                        lst = field_hit_count.setdefault(sel, [])
                        lst.append(text.strip())
                        break

        # 用最命中次数最多的格式作为 format_hint
        fmt_rank = sorted(hits_by_pattern_index.items(), key=lambda kv: -len(kv[1]))
        best_fmt = _TIME_PATTERNS[fmt_rank[0][0]][1] if fmt_rank and fmt_rank[0][1] else "%Y-%m-%d"

        fields: List[_TimeField] = []
        for sel, vals in sorted(field_hit_count.items(), key=lambda kv: -len(kv[1]))[:5]:
            fields.append(_TimeField(
                selector=sel,
                sample_values=list(dict.fromkeys(vals))[:5],
                format_hint=best_fmt,
                hit_count=len(vals),
            ))
        return fields

    # ------------------------------------------------------------ 阶段 2b: 降级时间字段识别（整文本关键字）
    def _detect_time_fields_text(self, soup: Any) -> List[_TimeField]:
        """未识别到条目容器时，在全文搜索"发布时间: 2024-01-02"这样的关键词短语。"""
        full_text = (soup.get_text("\n", strip=True) or "") if soup else ""
        values: List[str] = []
        for m in _TIME_KEYWORD_PATTERN.finditer(full_text):
            candidate = (m.group(2) or "").strip(" :：\t\r\n")
            # 再次用时间模式确认
            for pat, fmt in _TIME_PATTERNS:
                if pat.search(candidate):
                    values.append(candidate[:64])
                    break
            if len(values) >= 5:
                break
        if values:
            return [_TimeField(selector="span.time-keyword", sample_values=values,
                                format_hint="%Y-%m-%d", hit_count=len(values))]
        return []

    # ------------------------------------------------------------ 阶段 3: 条目抽取与排序
    def _extract_items(self, item_nodes: List[Any], time_field: Optional[_TimeField]) -> List[_ListItem]:
        items: List[_ListItem] = []
        for idx, node in enumerate(item_nodes):
            if not isinstance(node, Tag):
                continue

            title = ""
            link = ""

            # 如果 node 本身就是 <a>，直接取它的文本和 href
            if node.name == "a":
                title = (node.get_text(" ", strip=True) or "").strip()
                link = (node.get("href") or "").strip()
            else:
                # 否则尝试找第一个 <a>
                a = node.find("a")
                if a is not None and hasattr(a, "get_text"):
                    title = (a.get_text(" ", strip=True) or "").strip()
                    link = (a.get("href") or "").strip()
                # 如果 <a> 没有有效文本，使用整个节点的文本作为标题
                if not title:
                    title = (node.get_text(" ", strip=True) or "").strip()[:120]

            # 过滤掉完全空白的记录
            if not title and not link:
                continue

            # 时间：优先在节点内搜索时间模式
            raw_time = ""
            parsed_time: Optional[datetime] = None
            node_text = node.get_text(" ", strip=True) or ""
            for pat, fmt in _TIME_PATTERNS:
                m = pat.search(node_text)
                if m:
                    raw_time = m.group(0).strip()
                    try:
                        parsed_time = datetime.strptime(self._normalize_to_fmt(raw_time, fmt), fmt)
                    except Exception:
                        parsed_time = None
                    break

            items.append(_ListItem(
                title=title, link=link, raw_time=raw_time,
                parsed_time=parsed_time, original_index=idx,
            ))
        return items

    @staticmethod
    def _normalize_to_fmt(raw: str, fmt: str) -> str:
        """把诸如 '2024年1月2日' 按目标 format 规整为 '2024-01-02'。"""
        # 仅保留数字与分隔符（-/.），其它字符替换为对应分隔
        digits = re.findall(r"\d+", raw)
        if len(digits) < 3:
            return raw

        if fmt == "%Y-%m-%d":
            return f"{int(digits[0]):04d}-{int(digits[1]):02d}-{int(digits[2]):02d}"
        if fmt == "%Y-%m-%d %H:%M":
            h = digits[3] if len(digits) >= 4 else "00"
            mm = digits[4] if len(digits) >= 5 else "00"
            return f"{int(digits[0]):04d}-{int(digits[1]):02d}-{int(digits[2]):02d} {int(h):02d}:{int(mm):02d}"
        if fmt == "%d-%m-%Y":
            # 01-02-2024 / 1.2.24 这类；将最后一个 digits 视为年
            day, month, year = digits[0], digits[1], digits[2]
            if len(year) == 2:
                year = "20" + year
            return f"{int(day):02d}-{int(month):02d}-{int(year):04d}"
        if fmt == "%Y%m%d":
            try:
                return f"{int(raw):08d}"
            except Exception:
                return raw
        return raw

    # ------------------------------------------------------------ 阶段 4: 置信度计算
    @staticmethod
    def _calc_confidence(containers: List[_ContainerScore],
                          time_fields: List[_TimeField],
                          items: List[_ListItem]) -> float:
        if not containers:
            return 0.0
        container_score = containers[0].score
        time_factor = 0.4 if time_fields else 0.0
        item_factor = 0.3 if items else 0.0
        parsed_ratio = sum(1 for it in items if it.parsed_time) / max(1, len(items)) if items else 0.0
        return min(1.0, 0.3 * container_score + time_factor + item_factor + 0.3 * parsed_ratio)

    # ------------------------------------------------------------ 按采集范围过滤条目
    @staticmethod
    def apply_scope(items: List[Dict[str, Any]], scope: str, top_n: int) -> List[Dict[str, Any]]:
        """对 ``detect_all`` 输出的 items 按 ``latest | top_n | all`` 筛选。"""
        scope = (scope or "").strip().lower()
        if scope == "latest":
            # 取 publish_time_iso 最大的一条；若所有条目都没有解析时间，则退化到 top_n=1
            with_time = [it for it in items if it.get("publish_time_iso")]
            if with_time:
                return [sorted(with_time, key=lambda x: x["publish_time_iso"], reverse=True)[0]]
            return items[:1]
        if scope == "top_n":
            n = max(1, int(top_n or 10))
            return items[:n]
        # all / 未知
        return list(items)


# ============================================================================
# 模块级便捷函数
# ============================================================================
def detect_html(html: str, target_url: Optional[str] = None, *,
                 item_limit: int = 10, scope: str = "latest", top_n: int = 10) -> Dict[str, Any]:
    """便捷函数：创建 SmartDetector 并执行 detect_all + apply_scope。"""
    detector = SmartDetector()
    result = detector.detect_all(html, target_url=target_url)
    if result.get("success") and scope != "all":
        result["items"] = detector.apply_scope(result.get("items", []), scope, top_n)[:item_limit]
    return result
