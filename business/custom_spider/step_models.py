"""T31: 原子步骤数据模型 + StepsPackage 状态对象。

本模块仅定义纯数据结构（dataclass + 常量），不涉及 IO/网络/数据库依赖。

使用示例
--------
>>> from business.custom_spider.step_models import (
...     StepConfig, StepsPackage, STEP_TYPES, CRAWL_SCOPE_MODES,
... )
>>> s = StepConfig(step_id="s_1", step_type=STEP_TYPES["PAGE_ACCESS"],
...                step_order=1, config={"url": "https://example.com"})
>>> pkg = StepsPackage(plan_name="示例方案", steps=[s])
>>> pkg.to_dict()
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass, field, fields, asdict
from typing import Any, Dict, List, Optional


# ============================================================================
# 步骤类型常量 — 与前端 JS 中定义保持一致
# ============================================================================
STEP_TYPES: Dict[str, str] = {
    "PAGE_ACCESS":       "page_access",        # 1. 页面访问
    "LIST_DETECT":       "list_detect",        # 2. 列表识别
    "DETAIL_JUMP":       "detail_jump",        # 3. 详情跳转
    "ATTACHMENT_PARSE":  "attachment_parse",   # 4. 附件解析
    "FIELD_MAPPING":     "field_mapping",      # 5. 字段映射
    "RESULT_PREVIEW":    "result_preview",     # 6. 结果预览
    # —— T32 新增：智能指令型步骤 ——
    "CMD_LIST_LATEST":    "command_list_latest",     # 取最新 N 条
    "CMD_LIST_FILTER":    "command_list_filter",     # 按条件筛选
    "CMD_EXTRACT_TABLE":  "command_extract_table",   # 表格结构化提取
    "CMD_BATCH_FIELDS":   "command_batch_fields",    # 批量字段提取
    "CMD_REGEX_EXTRACT":  "command_regex_extract",   # 正则匹配提取
    "CMD_PAGINATION_LOOP": "command_pagination_loop", # 翻页循环
    "CMD_SCROLL_LOAD":    "command_scroll_load",     # 滚动加载
    "CMD_CONDITION_STOP": "command_condition_stop",  # 条件终止
    "CMD_TABLE_LATEST_JUMP": "command_table_latest_jump", # 表格最新记录跳转
}

STEP_TYPE_LABELS: Dict[str, str] = {
    "page_access":       "① 页面访问",
    "list_detect":       "② 列表识别",
    "detail_jump":       "③ 详情跳转",
    "attachment_parse":  "④ 附件解析",
    "field_mapping":     "⑤ 字段映射",
    "result_preview":    "⑥ 结果预览",
    "command_list_latest":    "⑦ 🆕 最新N条",
    "command_list_filter":    "⑧ 🔍 条件筛选",
    "command_extract_table":  "⑨ 📋 表格提取",
    "command_batch_fields":   "⑩ 📦 批量字段",
    "command_regex_extract":  "⑪ 🔤 正则提取",
    "command_pagination_loop": "⑫ 🔁 翻页循环",
    "command_scroll_load":    "⑬ 🔽 滚动加载",
    "command_condition_stop": "⑭ 🛑 条件终止",
    "command_table_latest_jump": "⑮ 📋➡️ 表格最新记录跳转",
}

# ============================================================================
# 采集范围模式常量
# ============================================================================
CRAWL_SCOPE_MODES: Dict[str, str] = {
    "LATEST": "latest",  # 自动选最新条目（按发布时间倒序取第一条）
    "TOP_N":  "top_n",   # 采集前 N 条
    "ALL":    "all",     # 全量采集
}

CRAWL_SCOPE_LABELS: Dict[str, str] = {
    "latest": "自动选最新",
    "top_n":  "前 N 条",
    "all":    "全量",
}


# ============================================================================
# 单步骤配置
# ============================================================================
@dataclass
class StepConfig:
    """原子步骤的配置数据。

    说明
    ----
    * ``step_id``: 前端生成唯一标识，建议 ``s_{unix_ts}_{idx}`` 格式。
    * ``step_type``: 值必须为 :data:`STEP_TYPES` 中的 value。
    * ``step_order``: 1-based 排序号，与 steps 列表顺序一致（渲染时以列表为准，本字段仅作冗余检查）。
    * ``status``: ``pending`` | ``ok`` | ``error``，由单步测试结果更新。
    * ``title``: 用户可自定义展示名，默认等于步骤类型中文标签。
    * ``config``: 自由配置字典，各步骤有约定 schema（见 T31 设计文档 §4）。
    * ``test_result``: 最近一次单步测试结果缓存，用于前端回显。
    * ``warnings`` / ``errors``: 由后端校验/组装模块回填，前端展示为黄/红提示。
    """

    step_id: str
    step_type: str
    step_order: int
    status: str = "pending"
    title: str = ""
    config: Dict[str, Any] = field(default_factory=dict)
    auto_detect: bool = True
    validated: bool = False
    last_tested_at: Optional[str] = None
    test_result: Optional[Dict[str, Any]] = None
    warnings: List[str] = field(default_factory=list)
    errors: List[str] = field(default_factory=list)

    def __post_init__(self) -> None:
        # 若未显式指定 title，则用默认中文标签
        if not self.title:
            self.title = STEP_TYPE_LABELS.get(self.step_type, self.step_type)
        # 合法性轻量检查
        if self.step_type not in set(STEP_TYPES.values()):
            raise ValueError(f"未知 step_type={self.step_type!r}, 允许值={sorted(STEP_TYPES.values())}")
        if not isinstance(self.config, dict):
            raise TypeError("config 必须是 dict")

    # ---------------------------------------------------------------- JSON 往返
    def to_dict(self) -> Dict[str, Any]:
        """返回一个可 JSON 序列化的字典（与构造参数一致）。"""
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "StepConfig":
        """从 dict 构造，忽略未知键（向前兼容）。自动补齐缺失的 step_id/step_order。"""
        known = {f.name for f in fields(cls)}
        safe = {k: v for k, v in data.items() if k in known}
        # 自动补齐缺失的必填字段，保证前向兼容
        if not safe.get("step_id"):
            safe["step_id"] = f"s_auto_{int(time.time() * 1000)}_{id(data) % 1000}"
        if not safe.get("step_order") or int(safe.get("step_order") or 0) < 1:
            safe["step_order"] = 1
        # 确保类型正确
        if "step_order" in safe and not isinstance(safe["step_order"], int):
            try:
                safe["step_order"] = int(safe["step_order"])
            except (TypeError, ValueError):
                safe["step_order"] = 1
        return cls(**safe)


# ============================================================================
# 单步测试结果（轻量版，用于 API 响应结构化）
# ============================================================================
@dataclass
class StepTestResult:
    step_id: str
    step_type: str
    success: bool
    duration_ms: int = 0
    message: str = ""
    output: Dict[str, Any] = field(default_factory=dict)
    masked: bool = True

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "StepTestResult":
        known = {f.name for f in fields(cls)}
        safe = {k: v for k, v in data.items() if k in known}
        return cls(**safe)


# ============================================================================
# StepsPackage: 编辑器全局状态
# ============================================================================
@dataclass
class StepsPackage:
    """编辑器状态容器。

    字段语义
    --------
    * ``steps``: 按 ``step_order`` 升序排列的 :class:`StepConfig` 列表。
    * ``schedule_config``: 可选调度配置，形如 ``{"enabled":true,"cron":"0 0 2 * * ?"}``。
    * ``increment_config``: 增量/范围配置，形如 ``{"dedup_mode":"url","crawl_scope":"latest"}``。
    * ``migrated_from_legacy``: 当由旧 CrawlRuleSet 自动转换时设为 True，前端可展示提示。
    """

    version: int = 1
    plan_name: str = ""
    target_domain: str = ""
    spider_type: str = "generic"
    steps: List[StepConfig] = field(default_factory=list)
    schedule_config: Optional[Dict[str, Any]] = None
    increment_config: Optional[Dict[str, Any]] = None
    migrated_from_legacy: bool = False

    # ------------------------------------------------------------------ 工具
    def sorted_steps(self) -> List[StepConfig]:
        """返回按 step_order 升序排列的步骤副本（不改变原列表）。"""
        return sorted(self.steps, key=lambda s: s.step_order)

    def normalize(self) -> None:
        """重算 step_order 使其等于在 steps 列表中的位置 +1。"""
        for i, s in enumerate(self.steps, start=1):
            s.step_order = i

    def get_step(self, step_id: str) -> Optional[StepConfig]:
        for s in self.steps:
            if s.step_id == step_id:
                return s
        return None

    # ------------------------------------------------------------------ JSON
    def to_dict(self) -> Dict[str, Any]:
        return {
            "version": self.version,
            "plan_name": self.plan_name,
            "target_domain": self.target_domain,
            "spider_type": self.spider_type,
            "steps": [s.to_dict() for s in self.steps],
            "schedule_config": self.schedule_config,
            "increment_config": self.increment_config,
            "migrated_from_legacy": self.migrated_from_legacy,
        }

    def to_json(self, **kwargs) -> str:
        return json.dumps(self.to_dict(), ensure_ascii=False, **kwargs)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "StepsPackage":
        steps_data = data.get("steps") or []
        steps = [StepConfig.from_dict(s) for s in steps_data]
        return cls(
            version=int(data.get("version", 1) or 1),
            plan_name=str(data.get("plan_name") or ""),
            target_domain=str(data.get("target_domain") or ""),
            spider_type=str(data.get("spider_type") or "generic"),
            steps=steps,
            schedule_config=data.get("schedule_config"),
            increment_config=data.get("increment_config"),
            migrated_from_legacy=bool(data.get("migrated_from_legacy")),
        )

    @classmethod
    def from_json(cls, s: str) -> "StepsPackage":
        return cls.from_dict(json.loads(s))


# ============================================================================
# 模块级便捷：基于模板快速生成 StepsPackage
# ============================================================================
STEP_TEMPLATES: Dict[str, Dict[str, Any]] = {
    "gov_notice_list": {
        "label": "政府公告/公示列表",
        "preset": [
            {"step_type": "page_access", "title": "访问公告列表页",
             "config": {"url": "", "use_render": False, "http_method": "GET"}},
            {"step_type": "list_detect", "title": "识别公告列表",
             "config": {"item_selector": "", "link_selector": "a", "link_attribute": "href",
                        "title_selector": "", "time_selector": "", "time_format": "%Y-%m-%d",
                        "crawl_scope": "latest", "top_n_count": 10,
                        "pagination": {"mode": "next_button", "next_selector": "", "max_pages": 20}}},
            {"step_type": "detail_jump", "title": "抓取详情",
             "config": {"detail_fields": [
                 {"name": "content", "extractor": "css", "expression": ".article-body", "required": True},
                 {"name": "publish_at", "extractor": "css", "expression": ".publish-time", "date_format": "%Y-%m-%d"},
             ], "use_render": False}},
            {"step_type": "field_mapping", "title": "字段映射",
             "config": {"map": {"title": "title", "publish_time": "publish_at",
                                 "body": "content", "source_url": "_source_url"}}},
            {"step_type": "result_preview", "title": "结果预览",
             "config": {"sample_size": 20, "compare_raw": True, "mask_pii": True}},
        ],
    },
    "simple_list_only": {
        "label": "仅列表（不跳详情页）",
        "preset": [
            {"step_type": "page_access", "title": "访问列表页",
             "config": {"url": "", "use_render": True, "http_method": "GET"}},
            {"step_type": "list_detect", "title": "识别列表",
             "config": {"item_selector": "", "link_selector": "a", "link_attribute": "href",
                        "title_selector": "", "time_selector": "", "time_format": "%Y-%m-%d",
                        "crawl_scope": "top_n", "top_n_count": 50}},
            {"step_type": "field_mapping", "title": "字段映射",
             "config": {"map": {"title": "title", "link": "link", "publish_time": "publish_time"}}},
            {"step_type": "result_preview", "title": "结果预览",
             "config": {"sample_size": 20, "compare_raw": True, "mask_pii": True}},
        ],
    },
    "enterprise_news": {
        "label": "企业新闻/行业资讯",
        "preset": [
            {"step_type": "page_access", "title": "访问资讯列表",
             "config": {"url": "", "use_render": True, "http_method": "GET"}},
            {"step_type": "list_detect", "title": "识别资讯列表",
             "config": {"item_selector": "", "link_selector": "a", "link_attribute": "href",
                        "title_selector": "", "time_selector": "", "time_format": "%Y-%m-%d",
                        "crawl_scope": "all"}},
            {"step_type": "detail_jump", "title": "抓取资讯详情",
             "config": {"detail_fields": [
                 {"name": "content", "extractor": "css", "expression": ".news-content", "required": True},
                 {"name": "author", "extractor": "css", "expression": ".author"},
             ], "use_render": False}},
            {"step_type": "attachment_parse", "title": "解析附件（可选）",
             "config": {"link_selector": "a.attachment", "link_attribute": "href",
                        "parse_pdf": True, "parse_image": False, "parse_docx": False,
                        "max_attachment_size_kb": 5120}},
            {"step_type": "field_mapping", "title": "字段映射",
             "config": {"map": {"title": "title", "publish_time": "publish_at",
                                 "body": "content", "source_url": "_source_url"}}},
            {"step_type": "result_preview", "title": "结果预览",
             "config": {"sample_size": 20, "compare_raw": True, "mask_pii": True}},
        ],
    },
}


def build_package_from_template(template_id: str, *, plan_name: str = "",
                                 target_domain: str = "",
                                 spider_type: str = "generic") -> StepsPackage:
    """按 :data:`STEP_TEMPLATES` 中某条模板生成 StepsPackage。"""
    if template_id not in STEP_TEMPLATES:
        raise KeyError(f"未知模板 template_id={template_id!r}, 可选={sorted(STEP_TEMPLATES)}")
    preset = STEP_TEMPLATES[template_id]["preset"]
    steps: List[StepConfig] = []
    for i, p in enumerate(preset, start=1):
        steps.append(StepConfig(
            step_id=f"s_{template_id}_{i}",
            step_type=p["step_type"],
            step_order=i,
            title=p.get("title") or STEP_TYPE_LABELS[p["step_type"]],
            config=dict(p.get("config") or {}),
        ))
    return StepsPackage(
        version=1, plan_name=plan_name, target_domain=target_domain,
        spider_type=spider_type, steps=steps,
    )
