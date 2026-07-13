# -*- coding: utf-8 -*-
"""T31: 可视化采集配置编辑器单元测试。

测试覆盖:
    1. step_models.StepConfig / StepsPackage 数据结构
    2. smart_detector.SmartDetector 容器识别 / 时间字段识别 / 样本条目
    3. step_service.StepAssembler 组装 T25 CrawlRuleSet
    4. step_service.CompatConverter 旧方案 -> StepsPackage 转换
    5. step_service.StepTester 单个步骤测试 / 全链路 test_all
"""

from __future__ import annotations

import json
import sys
import unittest
from typing import Any

# 保证 biztools/../ 包可从项目根导入
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


# ---------------------------------------------------------------------------
# 1. 数据模型
# ---------------------------------------------------------------------------
class StepModelsTestCase(unittest.TestCase):
    def test_step_config_defaults(self):
        from business.custom_spider.step_models import StepConfig, STEP_TYPES
        sc = StepConfig(step_id="s_1", step_type=STEP_TYPES["PAGE_ACCESS"], step_order=1)
        self.assertEqual(sc.step_id, "s_1")
        self.assertEqual(sc.step_type, STEP_TYPES["PAGE_ACCESS"])
        self.assertEqual(sc.step_order, 1)
        self.assertEqual(sc.status, "pending")
        # title 由 StepConfig 根据 step_type 自动填充为 "① 页面访问" 之类
        self.assertTrue(bool(sc.title))
        self.assertIsInstance(sc.config, dict)
        self.assertIsInstance(sc.warnings, list)
        self.assertIsInstance(sc.errors, list)
        self.assertTrue(sc.auto_detect)

    def test_steps_package_structure(self):
        from business.custom_spider.step_models import StepsPackage, StepConfig, STEP_TYPES
        pkg = StepsPackage(plan_name="demo", spider_type="generic_web")
        # 可迭代
        self.assertEqual(pkg.plan_name, "demo")
        # 向 pkg.steps 添加 3 步
        pkg.steps.append(StepConfig("a", STEP_TYPES["PAGE_ACCESS"], 1, config={"url": "https://example.com"}))
        pkg.steps.append(StepConfig("b", STEP_TYPES["LIST_DETECT"], 2, config={}))
        pkg.steps.append(StepConfig("c", STEP_TYPES["RESULT_PREVIEW"], 3, config={}))
        # 以 dict 形式导出
        out = {
            "plan_name": pkg.plan_name,
            "spider_type": pkg.spider_type,
            "target_domain": pkg.target_domain,
            "schedule_config": pkg.schedule_config,
            "increment_config": pkg.increment_config,
            "steps": [
                {
                    "step_id": s.step_id,
                    "step_type": s.step_type,
                    "step_order": s.step_order,
                    "config": s.config,
                }
                for s in pkg.steps
            ],
        }
        self.assertEqual(len(out["steps"]), 3)
        self.assertEqual(out["steps"][0]["step_type"], STEP_TYPES["PAGE_ACCESS"])
        self.assertEqual(out["steps"][0]["config"]["url"], "https://example.com")


# ---------------------------------------------------------------------------
# 2. 智能识别
# ---------------------------------------------------------------------------
class SmartDetectorTestCase(unittest.TestCase):
    SAMPLE_HTML = """<html><head><title>新闻列表</title></head><body>
    <div class="news-list">
      <div class="item"><h3><a href="/news/1.html">第一条新闻</a></h3><span class="date">2025-01-12</span></div>
      <div class="item"><h3><a href="/news/2.html">第二条新闻</a></h3><span class="date">2025-01-11</span></div>
      <div class="item"><h3><a href="/news/3.html">第三条新闻</a></h3><span class="date">2024-12-30</span></div>
    </div>
    <div class="footer"><p>非列表</p></div>
    </body></html>"""

    def setUp(self):
        from business.custom_spider.smart_detector import SmartDetector
        self.detector = SmartDetector()

    def test_detect_all_basic(self):
        result = self.detector.detect_all(self.SAMPLE_HTML, target_url="https://example.com")
        self.assertTrue(result.get("success"))
        # containers: 至少 1 个
        self.assertIn("containers", result)
        self.assertGreaterEqual(len(result["containers"]), 1)
        self.assertIn("time_fields", result)
        self.assertIn("items", result)
        self.assertIn("item_count_total", result)
        self.assertIn("confidence", result)
        self.assertIn("crawl_scope_suggestion", result)

    def test_detect_container_has_selector_and_confidence(self):
        result = self.detector.detect_all(self.SAMPLE_HTML)
        top = result["containers"][0]
        self.assertIn("selector", top)
        self.assertIn("confidence", top)
        # 样本选择器会包含 'news-list' 或 'item' 类特征
        self.assertTrue("news-list" in top["selector"] or "item" in top["selector"])
        self.assertGreaterEqual(top["confidence"], 0.1)

    def test_time_field_recognize(self):
        result = self.detector.detect_all(self.SAMPLE_HTML)
        # 至少命中 date 字段
        tfs = result["time_fields"]
        self.assertGreaterEqual(len(tfs), 1)
        self.assertTrue(any("date" in tf.get("selector", "") or "time" in tf.get("selector", "") for tf in tfs))

    def test_items_sorted_by_time_desc(self):
        result = self.detector.detect_all(self.SAMPLE_HTML)
        items = result["items"]
        # sample_items 顺序应为 2025-01-12, 2025-01-11, 2024-12-30
        self.assertGreaterEqual(len(items), 3)
        self.assertIn("2025-01-12", items[0].get("publish_time_iso", ""))
        self.assertIn("2025-01-11", items[1].get("publish_time_iso", ""))

    def test_empty_html_graceful(self):
        result = self.detector.detect_all("<html><body></body></html>")
        self.assertTrue(result.get("success"))
        self.assertIn("degrade_reason", result)
        # 空内容 不抛异常

    def test_target_domain_parsed(self):
        result = self.detector.detect_all(self.SAMPLE_HTML, target_url="https://example.com/news/index.html")
        self.assertEqual(result.get("target_url"), "https://example.com/news/index.html")


# ---------------------------------------------------------------------------
# 3. StepAssembler + CompatConverter
# ---------------------------------------------------------------------------
class StepServiceTestCase(unittest.TestCase):
    def _build_package(self) -> dict:
        """构造 StepsPackage 字典，用于 assemble / compat 测试。"""
        from business.custom_spider.step_models import STEP_TYPES
        return {
            "version": 1,
            "plan_name": "demo-plan",
            "target_domain": "",
            "spider_type": "generic_web",
            "steps": [
                {"step_id": "p1", "step_type": STEP_TYPES["PAGE_ACCESS"], "step_order": 1,
                 "title": "页面访问", "config": {"url": "https://example.com", "use_render": True,
                                                  "render_wait_ms": 1000}},
                {"step_id": "l1", "step_type": STEP_TYPES["LIST_DETECT"], "step_order": 2,
                 "title": "列表识别",
                 "config": {"item_selector": ".news-item",
                            "link_selector": "a", "link_attribute": "href",
                            "title_selector": "h3", "time_selector": ".date",
                            "time_format": "%Y-%m-%d",
                            "crawl_scope": "latest",
                            "pagination": {"mode": "next_button",
                                           "next_selector": ".next",
                                           "max_pages": 5}}},
                {"step_id": "d1", "step_type": STEP_TYPES["DETAIL_JUMP"], "step_order": 3,
                 "title": "详情跳转",
                 "config": {"detail_fields": [
                     {"name": "title", "extractor": "css", "expression": "h1", "required": True},
                     {"name": "content", "extractor": "css", "expression": ".body"},
                     {"name": "publish_time", "extractor": "css",
                      "expression": ".ptime", "date_format": "%Y-%m-%d"},
                 ], "use_render": False, "render_wait_ms": 0}},
                {"step_id": "r1", "step_type": STEP_TYPES["RESULT_PREVIEW"], "step_order": 4,
                 "title": "结果预览",
                 "config": {"sample_size": 10, "compare_raw": False, "mask_pii": True}},
            ],
            "schedule_config": {"enabled": True, "cron": "0 0 3 * * ?"},
            "increment_config": {"mode": "new_entries", "top_n_count": 50},
        }

    def test_step_assembler_returns_ruleset_dict(self):
        from business.custom_spider.step_service import StepAssembler
        from business.custom_spider.step_models import StepsPackage
        pkg_dict = self._build_package()
        pkg = StepsPackage.from_dict(pkg_dict)
        rule = StepAssembler.build_rule_config(pkg)
        self.assertIsInstance(rule, dict)
        self.assertIn("list_rule", rule)
        self.assertIn("detail_rule", rule)
        # url_template 应回填自 page_access
        self.assertEqual(rule["list_rule"]["url_template"], "https://example.com")
        # item_selector 正确传递
        self.assertEqual(rule["list_rule"]["item_selector"], ".news-item")
        # pagination 含 max_pages
        self.assertEqual(rule["list_rule"]["pagination"]["max_pages"], 5)
        # detail fields 至少有 1 条
        self.assertGreaterEqual(len(rule["detail_rule"]["fields"]), 1)
        # increment_config 正确构建
        self.assertIn("increment_config", rule)

    def test_compat_converter_roundtrip(self):
        from business.custom_spider.step_service import StepAssembler, CompatConverter
        from business.custom_spider.step_models import StepsPackage
        pkg = StepsPackage.from_dict(self._build_package())
        # 先构建一个 T25 CrawlRuleSet dict，然后转换为 StepsPackage
        rule = StepAssembler.build_rule_config(pkg)
        self.assertIn("list_rule", rule)
        pkg2 = CompatConverter.convert(rule, plan_name="converted-plan",
                                       target_domain="example.com",
                                       spider_type="generic_web")
        # CompatConverter 返回 StepsPackage 实例
        self.assertIsInstance(pkg2, StepsPackage)
        self.assertGreaterEqual(len(pkg2.steps), 4)
        self.assertTrue(getattr(pkg2, "migrated_from_legacy", False))
        # roundtrip: 再组装回 rule
        rule2 = StepAssembler.build_rule_config(pkg2)
        self.assertEqual(rule2["list_rule"]["url_template"], rule["list_rule"]["url_template"])

    def test_step_tester_test_all_runs(self):
        from business.custom_spider.step_service import StepTester
        from business.custom_spider.step_models import StepsPackage
        pkg = StepsPackage.from_dict(self._build_package())
        result = StepTester.run_all(pkg)
        self.assertIsInstance(result, dict)
        self.assertIn("steps", result)
        self.assertIn("duration_ms", result)
        # 每步都有 step_id + success + duration_ms
        for s in result["steps"]:
            self.assertIn("step_id", s)
            self.assertIn("success", s)
            self.assertIn("duration_ms", s)


# ---------------------------------------------------------------------------
# 4. API 路由注册存在性（轻量，仅验证路由存在）
# ---------------------------------------------------------------------------
class ApiRouteExistenceTestCase(unittest.TestCase):
    def test_crawl_config_router_has_smart_detect_and_step_apis(self):
        import inspect
        from web_admin.api import crawl_config as crawl_mod
        # 读取模块内的函数，确认至少存在 smart_detect / step_test / full_test / assemble
        src = inspect.getsource(crawl_mod)
        for name in ["smart_detect", "step_test", "full_test", "assemble",
                     "template_apply", "compat_convert"]:
            self.assertIn(name, src, f"expected API '{name}' to exist in web_admin.api.crawl_config")

    def test_pages_registers_editor_route(self):
        import inspect
        from web_admin import pages as pages_mod
        src = inspect.getsource(pages_mod)
        self.assertIn("crawl/steps-editor", src, "steps-editor 路由应注册在 pages.py 中")


if __name__ == "__main__":
    unittest.main(verbosity=2)
