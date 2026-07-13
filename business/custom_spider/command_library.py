"""T32: 智能指令库（可插拔 step_type = command_*）。

本模块实现 8 种智能指令，每条指令提供：

* ``params_schema``: 参数结构描述（供前端动态生成表单）。
* ``match_trigger(html, selector)``: 给定一段 HTML 与一个 CSS 选择器，
  返回该指令对该元素的推荐置信度（0~1），用于「拾取模式」时的指令推荐排序。
* ``to_step_config(selector, context)``: 给定被选择元素信息，生成一条
  step_config（供前端直接追加到 steps）。
* ``run(html, config, upstream)``: 纯本地数据变换，不做网络抓取，用于
  单步测试与增量测试。使用 bs4 + re 实现。
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from bs4 import BeautifulSoup


# ============================================================================
# 指令元数据结构
# ============================================================================
@dataclass
class FieldDef:
    """表单字段定义。"""

    name: str
    label: str
    field_type: str = "text"         # text | number | bool | textarea | select | regex
    default: Any = None
    required: bool = False
    options: List[str] = field(default_factory=list)
    hint: str = ""


@dataclass
class CommandMeta:
    """指令元数据，供前端动态渲染。"""

    name: str
    label: str
    description: str = ""
    category: str = "list"            # list | data | flow
    params_schema: List[FieldDef] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "label": self.label,
            "description": self.description,
            "category": self.category,
            "params_schema": [f.__dict__ for f in self.params_schema],
        }


# ============================================================================
# 指令基类
# ============================================================================
class Command:
    """指令基类。每条指令仅关注自身的元数据定义与数据变换。"""

    name: str = ""
    label: str = ""
    description: str = ""
    category: str = "list"

    params_schema: List[FieldDef] = []

    @classmethod
    def meta(cls) -> CommandMeta:
        return CommandMeta(
            name=cls.name, label=cls.label, description=cls.description,
            category=cls.category, params_schema=list(cls.params_schema),
        )

    @classmethod
    def match_trigger(cls, html: str, selector: str) -> float:
        """对一段 html 与一个选择器返回推荐置信度 0~1。

        默认实现仅基于 selector 的文本特征做简单启发。各子类应覆盖。
        """
        return 0.1

    @classmethod
    def to_step_config(cls, selector: str, context: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """生成一条 step_config（会填入到 StepConfig.config）。

        默认：仅把 selector 写入 ``item_selector`` / ``table_selector`` 等常规字段。
        子类可覆盖以加入更多默认值。
        """
        return {}

    @classmethod
    def run(cls, html: str, config: Dict[str, Any],
            upstream: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """在一段 html（或上游结构化数据）上执行本指令，返回 JSON 可序列化结果。"""
        return {"success": True}


# ============================================================================
# 指令 1：command_list_latest  — 取最新 N 条
# ============================================================================
class CommandListLatest(Command):
    name = "command_list_latest"
    label = "🆕 取最新 N 条"
    description = "在列表容器中，按发布时间字段排序并取最新 N 条；配合自动识别时间字段。"
    category = "list"

    params_schema = [
        FieldDef("item_selector", "列表项选择器", "text", "", True, hint="如 li / .news-item"),
        FieldDef("link_selector", "链接元素", "text", "a"),
        FieldDef("link_attribute", "链接属性", "text", "href"),
        FieldDef("title_selector", "标题字段", "text", ""),
        FieldDef("time_selector", "发布时间字段（可自动识别）", "text", ""),
        FieldDef("time_format", "时间格式", "text", "%Y-%m-%d"),
        FieldDef("top_n_count", "取前 N 条", "number", 20, True),
        FieldDef("auto_detect_time", "自动识别时间字段", "bool", True),
        FieldDef("crawl_scope", "采集范围", "select", "top_n", False,
                 ["top_n", "latest", "all"]),
    ]

    @classmethod
    def match_trigger(cls, html: str, selector: str) -> float:
        # 若选择器匹配多个 <li>/.item，则较适合
        try:
            soup = BeautifulSoup(html or "", "html.parser")
            items = soup.select(selector) if selector else []
            # 同时检查是否包含明显的日期文本（如 2024-xx-xx / xxxx年xx月xx日）
            date_like = bool(re.search(r"\d{4}[-/.年]\s*\d{1,2}[-/.月]\s*\d{1,2}", html or ""))
            base = min(len(items) / 10.0, 1.0)
            return min(base + (0.3 if date_like else 0.0), 1.0)
        except Exception:
            return 0.2

    @classmethod
    def to_step_config(cls, selector: str, context: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        return {
            "item_selector": selector or "",
            "link_selector": "a",
            "link_attribute": "href",
            "title_selector": "",
            "time_selector": "",
            "time_format": "%Y-%m-%d",
            "top_n_count": 20,
            "auto_detect_time": True,
            "crawl_scope": "top_n",
        }

    @classmethod
    def run(cls, html: str, config: Dict[str, Any],
            upstream: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        soup = BeautifulSoup(html or "", "html.parser")
        item_sel = config.get("item_selector") or ""
        items = soup.select(item_sel) if item_sel else []
        top_n = int(config.get("top_n_count") or 20)
        # 按列表原始顺序取前 N
        items = items[:top_n]
        result_items = []
        for idx, it in enumerate(items):
            link_el = it.select_one(config.get("link_selector") or "a")
            title_el = it.select_one(config.get("title_selector") or "a") if not config.get("title_selector") else it.select_one(config["title_selector"])
            time_el = it.select_one(config.get("time_selector") or "") if config.get("time_selector") else None
            title_txt = (title_el.get_text(strip=True) if title_el else "")
            result_items.append({
                "index": idx + 1,
                "title": title_txt,
                "link": (link_el and link_el.get("href", "") or ""),
                "publish_time": (time_el.get_text(strip=True) if time_el else ""),
            })
        return {
            "success": True,
            "total_items": len(items),
            "items": result_items[:top_n],
        }


# ============================================================================
# 指令 2：command_list_filter — 按条件筛选列表
# ============================================================================
class CommandListFilter(Command):
    name = "command_list_filter"
    label = "🔍 条件筛选"
    description = "按字段 contains / equals / after_date 等规则过滤列表项。"
    category = "list"

    params_schema = [
        FieldDef("item_selector", "列表项选择器", "text", "", True),
        FieldDef("field", "字段", "text", "title", True,
                 ["title", "publish_time", "link"]),
        FieldDef("op", "比较操作符", "select", "contains", True,
                 ["contains", "equals", "not_contains", "after_date", "before_date", "regex"]),
        FieldDef("value", "比较值", "text", "招标公告", True),
    ]

    @classmethod
    def run(cls, html: str, config: Dict[str, Any],
            upstream: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        items: List[Dict[str, Any]] = []
        if upstream and "items" in upstream:
            items = list(upstream["items"])
        elif html:
            # 允许不提供 upstream 时也能从 HTML 解析
            soup = BeautifulSoup(html, "html.parser")
            items = [{"title": it.get_text(strip=True)[:80]} for it in soup.select(config.get("item_selector") or "")]
        field = config.get("field") or "title"
        op = config.get("op") or "contains"
        value = str(config.get("value") or "")
        filtered = []
        for it in items:
            v = str(it.get(field) or "")
            if op == "contains" and value in v: filtered.append(it)
            elif op == "equals" and v == value: filtered.append(it)
            elif op == "not_contains" and value not in v: filtered.append(it)
            elif op == "after_date" and v >= value: filtered.append(it)
            elif op == "before_date" and v and v <= value: filtered.append(it)
            elif op == "regex" and value and re.search(value, v): filtered.append(it)
        return {"success": True, "original_count": len(items), "filtered_count": len(filtered), "items": filtered}


# ============================================================================
# 指令 3：command_extract_table — 表格结构化提取
# ============================================================================
class CommandExtractTable(Command):
    name = "command_extract_table"
    label = "📋 表格提取"
    description = "把 HTML <table> 结构化到 rows，第一行作为表头或使用给定别名。"
    category = "data"

    params_schema = [
        FieldDef("table_selector", "表格选择器", "text", "table", True),
        FieldDef("header_row_index", "表头行索引（0 为第一行）", "number", 0),
        FieldDef("has_header", "是否使用表格首行作为表头", "bool", True),
        FieldDef("use_first_row_as_header", "使用第一行数据作为表头（无 th 时）", "bool", False),
        FieldDef("column_aliases", "列别名（逗号分隔）", "text", ""),
    ]

    @classmethod
    def match_trigger(cls, html: str, selector: str) -> float:
        return 0.9 if (selector or "").lower().startswith("table") else 0.3

    @classmethod
    def to_step_config(cls, selector: str, context: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        return {"table_selector": selector or "table", "has_header": True, "header_row_index": 0,
                "use_first_row_as_header": False, "column_aliases": ""}

    @classmethod
    def run(cls, html: str, config: Dict[str, Any],
            upstream: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        soup = BeautifulSoup(html or "", "html.parser")
        table = soup.select_one(config.get("table_selector") or "table")
        if table is None:
            return {"success": False, "error": "未找到 table"}
        rows = []
        for tr in table.find_all("tr"):
            cells = [td.get_text(" ", strip=True) for td in tr.find_all(["th", "td"])]
            rows.append(cells)
        if not rows:
            return {"success": False, "error": "表格为空"}
        headers = rows[0] if config.get("has_header") else [f"col{i+1}" for i in range(len(rows[0]))]
        if config.get("column_aliases"):
            aliases = [a.strip() for a in str(config["column_aliases"]).split(",") if a.strip()]
            if aliases and len(aliases) == len(headers):
                headers = aliases
        start_idx = 1 if config.get("has_header") else 0
        records = [dict(zip(headers, row)) for row in rows[start_idx:]]
        return {"success": True, "headers": headers, "row_count": len(records), "records": records[:50]}


# ============================================================================
# 指令 4：command_batch_fields — 批量字段提取
# ============================================================================
class CommandBatchFields(Command):
    name = "command_batch_fields"
    label = "📦 批量字段"
    description = "在详情页上按 CSS 选择器提取多个字段（title/content/publish_time 等）。"
    category = "data"

    params_schema = [
        FieldDef("fields", "字段列表（JSON 数组）", "textarea",
                 '[{"name":"title","selector":"h1","required":true}]', True,
                 hint='JSON 数组格式，每项含 name/selector/extractor(可选)'),
    ]

    @classmethod
    def to_step_config(cls, selector: str, context: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        import json
        default = [
            {"name": "title", "selector": selector or "h1", "required": True},
            {"name": "content", "selector": ".content", "required": False},
            {"name": "publish_time", "selector": ".time", "date_format": "%Y-%m-%d"},
        ]
        return {"fields": json.dumps(default, ensure_ascii=False)}

    @classmethod
    def run(cls, html: str, config: Dict[str, Any],
            upstream: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        import json
        soup = BeautifulSoup(html or "", "html.parser")
        try:
            fields = json.loads(config.get("fields") or "[]")
        except Exception as exc:
            return {"success": False, "error": f"fields JSON 解析失败: {exc}"}
        result: Dict[str, Any] = {}
        for fdef in fields:
            sel = fdef.get("selector") or ""
            el = soup.select_one(sel) if sel else None
            txt = el.get_text(" ", strip=True) if el else ""
            result[fdef.get("name") or "field"] = txt
        return {"success": True, "fields": result}


# ============================================================================
# 指令 5：command_regex_extract — 正则匹配提取
# ============================================================================
class CommandRegexExtract(Command):
    name = "command_regex_extract"
    label = "🔤 正则提取"
    description = "从一段文本按正则规则抽取手机/邮箱/身份证等字段。"
    category = "data"

    params_schema = [
        FieldDef("source_field", "源字段名（从 upstream 读取）", "text", "content"),
        FieldDef("patterns", "模式（JSON 数组）", "textarea",
                 '[{"name":"phone","regex":"1[3-9]\\\\d{9}"}]', True),
    ]

    @classmethod
    def run(cls, html: str, config: Dict[str, Any],
            upstream: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        import json
        source = ""
        if upstream and config.get("source_field") and config["source_field"] in upstream:
            source = str(upstream[config["source_field"]])
        elif html:
            source = html
        try:
            patterns = json.loads(config.get("patterns") or "[]")
        except Exception as exc:
            return {"success": False, "error": f"patterns JSON 解析失败: {exc}"}
        matches: Dict[str, List[str]] = {}
        for p in patterns:
            name = p.get("name") or "regex"
            try:
                matches[name] = re.findall(p.get("regex") or "", source or "")
            except re.error as exc:
                matches[name] = [f"RE_ERROR: {exc}"]
        return {"success": True, "matches": matches}


# ============================================================================
# 指令 6：command_pagination_loop — 翻页循环
# ============================================================================
class CommandPaginationLoop(Command):
    name = "command_pagination_loop"
    label = "🔁 翻页循环"
    description = "通过 next 按钮或 page=N 参数循环翻页，直到达到最大页数或无更多数据。"
    category = "flow"

    params_schema = [
        FieldDef("mode", "翻页模式", "select", "next_button", True,
                 ["next_button", "numbered", "infinite_scroll"]),
        FieldDef("next_selector", "下一页按钮选择器", "text", "a.next-page"),
        FieldDef("max_pages", "最大页数", "number", 20, True),
        FieldDef("stop_when_no_items", "列表为空时停止", "bool", True),
    ]

    @classmethod
    def to_step_config(cls, selector: str, context: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        return {"mode": "next_button", "next_selector": selector or "a.next-page",
                "max_pages": 20, "stop_when_no_items": True}

    @classmethod
    def run(cls, html: str, config: Dict[str, Any],
            upstream: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        # 仅做元数据验证：返回将要执行的循环参数
        return {
            "success": True,
            "mode": config.get("mode", "next_button"),
            "next_selector": config.get("next_selector", "a.next-page"),
            "max_pages": int(config.get("max_pages") or 20),
            "stop_when_no_items": bool(config.get("stop_when_no_items", True)),
            "note": "本指令用于配置抓取范围；真正的翻页由底层引擎按规则集执行。",
        }


# ============================================================================
# 指令 7：command_scroll_load — 滚动加载
# ============================================================================
class CommandScrollLoad(Command):
    name = "command_scroll_load"
    label = "🔽 滚动加载"
    description = "无限滚动页面（动态 JS 加载），按最大次数执行 scrollTop。"
    category = "flow"

    params_schema = [
        FieldDef("scroll_times", "最大滚动次数", "number", 30, True),
        FieldDef("delay_ms", "每次滚动后等待（毫秒）", "number", 800),
        FieldDef("scroll_selector", "滚动目标选择器", "text", "window", False, ["window", "body", "自定义"]),
        FieldDef("stop_when_no_new_items", "没有新内容时停止", "bool", True),
    ]

    @classmethod
    def run(cls, html: str, config: Dict[str, Any],
            upstream: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        return {
            "success": True,
            "scroll_times": int(config.get("scroll_times") or 30),
            "delay_ms": int(config.get("delay_ms") or 800),
            "scroll_selector": config.get("scroll_selector") or "window",
            "stop_when_no_new_items": bool(config.get("stop_when_no_new_items", True)),
            "note": "实际滚动由底层渲染引擎执行，此处仅返回配置。",
        }


# ============================================================================
# 指令 8：command_condition_stop — 条件终止
# ============================================================================
class CommandConditionStop(Command):
    name = "command_condition_stop"
    label = "🛑 条件终止"
    description = "当命中已知条目/日期阈值/字段匹配时，停止翻页循环，适用于增量采集场景。"
    category = "flow"

    params_schema = [
        FieldDef("condition_mode", "条件模式", "select", "item_seen", True,
                 ["item_seen", "item_date_before", "item_field_match"]),
        FieldDef("seen_item_link", "已知条目标记链接", "text", ""),
        FieldDef("item_date_before", "截止日期（YYYY-MM-DD）", "text", "2024-01-01"),
        FieldDef("item_field_match", "字段匹配（JSON）", "textarea",
                 '{"field":"title","op":"contains","value":"停止"}'),
        FieldDef("max_pages", "最大页数上限（兜底）", "number", 100),
    ]

    @classmethod
    def run(cls, html: str, config: Dict[str, Any],
            upstream: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        return {
            "success": True,
            "condition_mode": config.get("condition_mode", "item_seen"),
            "stop_rule": {
                k: config.get(k) for k in ("seen_item_link", "item_date_before", "item_field_match")
            },
            "max_pages": int(config.get("max_pages") or 100),
            "note": "真正的终止判断由底层引擎在翻页循环中执行。",
        }


# ============================================================================
# 指令 9：command_table_latest_jump — 表格最新记录 + 详情跳转
# ============================================================================
class CommandTableLatestJump(Command):
    """从表格中识别最新记录，并生成可用于 detail_jump 的 items 列表。

    典型工作流：page_access → command_table_latest_jump → detail_jump → field_mapping
    """
    name = "command_table_latest_jump"
    label = "📋➡️ 表格最新记录跳转"
    description = "从 HTML 表格中按时间字段识别最新记录，自动提取链接列生成 items，供后续详情跳转使用。"
    category = "list"

    params_schema = [
        FieldDef("table_selector", "表格选择器", "text", "table", True,
                 hint='如 table / .notice-table / #data-table'),
        FieldDef("top_n_count", "取前 N 条记录", "number", 10, True),
        FieldDef("auto_detect_columns", "自动识别列（链接/时间/标题）", "bool", True),
        FieldDef("link_column_name", "链接列的表头名称（留空=自动识别）", "text", ""),
        FieldDef("time_column_name", "时间列的表头名称（留空=自动识别）", "text", ""),
        FieldDef("title_column_name", "标题列的表头名称（留空=自动识别）", "text", ""),
        FieldDef("sort_mode", "排序模式", "select", "desc", False,
                 ["desc", "asc", "none"],
                 hint='desc=最新在前, asc=最旧在前, none=保持原顺序'),
    ]

    @classmethod
    def match_trigger(cls, html: str, selector: str) -> float:
        sel = (selector or "").lower()
        soup = BeautifulSoup(html or "", "html.parser")
        tables = soup.select(selector) if selector else soup.find_all("table")
        if tables:
            return 0.85
        if "table" in sel or "tbody" in sel or sel.startswith("tr"):
            return 0.7
        return 0.2

    @classmethod
    def to_step_config(cls, selector: str, context: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        return {
            "table_selector": selector or "table",
            "top_n_count": 10,
            "auto_detect_columns": True,
            "link_column_name": "",
            "time_column_name": "",
            "title_column_name": "",
            "sort_mode": "desc",
        }

    @classmethod
    def _detect_time_column(cls, headers: List[str], rows: List[List[str]]) -> Optional[int]:
        """自动识别哪一列是时间字段。"""
        # 先根据表头关键词识别
        time_keywords = ["时间", "日期", "发布", "创建", "更新", "登记", "date", "time", "publish", "release"]
        for i, h in enumerate(headers):
            hl = h.lower()
            if any(kw in hl for kw in time_keywords):
                return i
        # 再根据内容格式识别（是否包含日期格式）
        date_pattern = re.compile(r"\d{4}[-/.年]\s*\d{1,2}[-/.月]\s*\d{1,2}|(\d{1,2}[-/.]){2}\d{2,4}")
        col_scores = [0] * len(headers)
        for row in rows[:10]:
            for i, cell in enumerate(row):
                if i < len(headers) and date_pattern.search(cell or ""):
                    col_scores[i] += 1
        if col_scores and max(col_scores) > 0:
            return col_scores.index(max(col_scores))
        return None

    @classmethod
    def _detect_link_column(cls, rows_html: List[List]) -> Optional[int]:
        """从行的 HTML 元素中识别哪一列包含 <a> 链接。"""
        if not rows_html:
            return None
        col_scores = [0] * (max((len(r) for r in rows_html), default=0))
        for row in rows_html[:10]:
            for i, cell in enumerate(row):
                if i < len(col_scores):
                    if cell.find("a") is not None:
                        col_scores[i] += 2
                    text = cell.get_text(" ", strip=True)
                    if "http" in text.lower() or "链接" in text:
                        col_scores[i] += 1
        if col_scores and max(col_scores) > 0:
            return col_scores.index(max(col_scores))
        return None

    @classmethod
    def _detect_title_column(cls, headers: List[str], rows: List[List[str]]) -> Optional[int]:
        """自动识别哪一列是标题列。"""
        title_keywords = ["标题", "名称", "主题", "事项", "公告", "通知", "title", "name", "subject"]
        for i, h in enumerate(headers):
            hl = h.lower()
            if any(kw in hl for kw in title_keywords):
                return i
        # 选择文本最长且最丰富的列（排除时间/链接列）
        time_col = cls._detect_time_column(headers, rows)
        best_col = None
        best_score = 0
        for i in range(len(headers)):
            if time_col is not None and i == time_col:
                continue
            avg_len = 0
            for row in rows[:10]:
                if i < len(row):
                    avg_len += len(row[i])
            avg_len = avg_len / min(10, max(1, len(rows)))
            if avg_len > best_score:
                best_score = avg_len
                best_col = i
        return best_col

    @classmethod
    def _parse_date(cls, text: str) -> Optional[float]:
        """尝试把文本解析为日期的时间戳用于排序。"""
        if not text:
            return None
        m = re.search(r"(\d{4})[-/.年]\s*(\d{1,2})[-/.月]\s*(\d{1,2})", text)
        if m:
            try:
                from datetime import datetime
                return datetime(int(m.group(1)), int(m.group(2)), int(m.group(3))).timestamp()
            except Exception:
                return None
        # 尝试 MM/DD 格式
        m2 = re.search(r"(\d{1,2})[-/.]\s*(\d{1,2})", text)
        if m2:
            try:
                from datetime import datetime
                return datetime(2000, int(m2.group(1)), int(m2.group(2))).timestamp()
            except Exception:
                return None
        return None

    @classmethod
    def run(cls, html: str, config: Dict[str, Any],
            upstream: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        soup = BeautifulSoup(html or "", "html.parser")
        table_sel = config.get("table_selector") or "table"
        table = soup.select_one(table_sel)

        if table is None:
            return {"success": False, "error": f"未找到表格: {table_sel}"}

        # 解析表格的 HTML 行（保留结构以便检测链接）
        all_trs = table.find_all("tr")
        if len(all_trs) == 0:
            return {"success": False, "error": "表格为空"}

        # 解析表头（第一行作为 header）
        has_header = True
        header_cells_html = all_trs[0].find_all(["th", "td"])
        headers = [c.get_text(" ", strip=True) for c in header_cells_html]

        # 解析数据行
        data_rows_html = []
        data_rows_text = []
        for tr in all_trs[1:]:
            cells_html = tr.find_all(["th", "td"])
            cells_text = [c.get_text(" ", strip=True) for c in cells_html]
            data_rows_html.append(cells_html)
            data_rows_text.append(cells_text)

        if not data_rows_text:
            return {"success": False, "error": "表格无数据行"}

        # 识别列
        auto_detect = config.get("auto_detect_columns", True)
        time_col = None
        link_col = None
        title_col = None

        if auto_detect:
            time_col = cls._detect_time_column(headers, data_rows_text)
            link_col = cls._detect_link_column(data_rows_html)
            title_col = cls._detect_title_column(headers, data_rows_text)
        else:
            # 手动指定
            t_name = (config.get("time_column_name") or "").strip()
            l_name = (config.get("link_column_name") or "").strip()
            title_name = (config.get("title_column_name") or "").strip()
            for i, h in enumerate(headers):
                if t_name and t_name in h:
                    time_col = i
                if l_name and l_name in h:
                    link_col = i
                if title_name and title_name in h:
                    title_col = i

        # 检测信息
        detect_info = {
            "headers": headers,
            "time_column": headers[time_col] if time_col is not None else None,
            "link_column": headers[link_col] if link_col is not None else None,
            "title_column": headers[title_col] if title_col is not None else None,
        }

        # 生成 items
        items = []
        for row_idx, (row_html, row_text) in enumerate(zip(data_rows_html, data_rows_text)):
            item = {
                "row_index": row_idx,
                "title": (row_text[title_col] if title_col is not None and title_col < len(row_text)
                          else (row_text[0] if row_text else "")),
                "publish_time": (row_text[time_col] if time_col is not None and time_col < len(row_text) else ""),
                "link": "",
                "row_data": dict(zip(headers, row_text)),
            }
            # 从 link_column 中提取链接
            if link_col is not None and link_col < len(row_html):
                link_cell = row_html[link_col]
                a_tag = link_cell.find("a")
                if a_tag and a_tag.get("href"):
                    item["link"] = a_tag.get("href")
                elif a_tag and a_tag.get_text(strip=True) and "http" in a_tag.get_text(strip=True).lower():
                    item["link"] = a_tag.get_text(strip=True)
                else:
                    # 尝试从单元格文本提取链接
                    cell_text = link_cell.get_text(" ", strip=True)
                    url_match = re.search(r"(https?://[^\s]+)", cell_text)
                    if url_match:
                        item["link"] = url_match.group(1)

            # 如果 link_column 未找到但有 link 列，尝试找第一个有链接的单元格
            if not item["link"]:
                for cell in row_html:
                    a_tag = cell.find("a")
                    if a_tag and a_tag.get("href"):
                        item["link"] = a_tag.get("href")
                        break

            items.append(item)

        # 排序（按时间字段）
        sort_mode = (config.get("sort_mode") or "desc").lower()
        if sort_mode in ("desc", "asc") and time_col is not None:
            def _sort_key(it):
                ts = cls._parse_date(it.get("publish_time", ""))
                return (0 if ts else 1, -(ts or 0) if sort_mode == "desc" else (ts or 0))
            items.sort(key=_sort_key)

        # 取前 N 条
        top_n = int(config.get("top_n_count") or 10)
        items = items[:top_n]

        return {
            "success": True,
            "detect_info": detect_info,
            "row_count": len(items),
            "items": items,
            "has_links": sum(1 for it in items if it.get("link")) > 0,
        }


# ============================================================================
# 注册表
# ============================================================================
COMMAND_REGISTRY: Dict[str, Command] = {
    "command_list_latest": CommandListLatest(),
    "command_list_filter": CommandListFilter(),
    "command_extract_table": CommandExtractTable(),
    "command_batch_fields": CommandBatchFields(),
    "command_regex_extract": CommandRegexExtract(),
    "command_pagination_loop": CommandPaginationLoop(),
    "command_scroll_load": CommandScrollLoad(),
    "command_condition_stop": CommandConditionStop(),
    "command_table_latest_jump": CommandTableLatestJump(),
}


def get_command(name: str) -> Optional[Command]:
    return COMMAND_REGISTRY.get(name)


def list_command_metas() -> List[Dict[str, Any]]:
    """返回所有指令的元数据（前端用于渲染指令选择弹窗）。"""
    return [c.meta().to_dict() for c in COMMAND_REGISTRY.values()]


def run_command(name: str, html: str, config: Dict[str, Any],
                upstream: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    cmd = get_command(name)
    if cmd is None:
        return {"success": False, "error": f"未知指令 name={name!r}"}
    try:
        return cmd.run(html, config, upstream)
    except Exception as exc:
        return {"success": False, "error": f"指令执行异常: {exc}"}
