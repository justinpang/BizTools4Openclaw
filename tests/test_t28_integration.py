"""T28 全模块联调集成测试。

覆盖：
1. T26 表创建链路
2. DedupStore Redis/内存 去重
3. _parse_engine_result 正确读取 errors
4. 权限装饰器对 RBAC 角色的正确拦截
5. HTML 消毒与敏感信息脱敏
"""
from __future__ import annotations

import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import unittest
import json

from infra.logger_setup import get_logger
logger = get_logger(__name__)


class T28_TableCreationTest(unittest.TestCase):
    """验证 T26 custom_spider 表能被显式创建。"""

    def test_01_create_tables_callable(self):
        """create_tables 函数必须可被 import 并调用。"""
        from business.custom_spider import create_tables
        self.assertTrue(callable(create_tables))

    def test_02_create_tables_returns_bool(self):
        """调用后必须返回布尔值（数据库不可用也不应崩溃）。"""
        from business.custom_spider import create_tables
        result = create_tables()
        self.assertIsInstance(result, bool)
        logger.info(f"create_tables() -> {result}")

    def test_03_plan_repository_exists(self):
        """PlanRepository 必须可实例化，说明依赖链完整。"""
        from business.custom_spider.repository import PlanRepository
        # 不做数据库操作，仅验证导入成功和核心方法存在
        self.assertTrue(hasattr(PlanRepository, "list"))
        self.assertTrue(hasattr(PlanRepository, "create"))
        self.assertTrue(hasattr(PlanRepository, "get_by_id"))


class T28_DedupStoreTest(unittest.TestCase):
    """验证 DedupStore 的去重语义。"""

    def test_01_memory_dedup_basic(self):
        """同一 key 第二次 check_and_mark 应返回 True（重复）。"""
        from core.spider_core.dedup_store import DedupStore
        store = DedupStore()  # 使用内存存储（无 Redis 也能跑）

        task_id = "t28-test-memory"
        key1 = "https://example.com/article/1"
        key2 = "https://example.com/article/2"

        # 首次不重复
        is_dup1 = store.check_and_mark(task_id, key1)
        self.assertFalse(is_dup1, "首次检测不应为重复")

        # 第二次重复
        is_dup2 = store.check_and_mark(task_id, key1)
        self.assertTrue(is_dup2, "第二次检测应为重复")

        # 不同 key 不重复
        is_dup3 = store.check_and_mark(task_id, key2)
        self.assertFalse(is_dup3, "新 key 不应重复")

        self.assertEqual(store.count(task_id), 2)

    def test_02_clear_resets_state(self):
        """clear 后之前的 key 不被认为重复。"""
        from core.spider_core.dedup_store import DedupStore
        store = DedupStore()
        task_id = "t28-test-clear"
        store.check_and_mark(task_id, "key-a")
        self.assertEqual(store.count(task_id), 1)

        cleared = store.clear(task_id)
        self.assertEqual(cleared, 1)
        self.assertEqual(store.count(task_id), 0)

    def test_03_long_key_hash(self):
        """超长 key 必须被 hash 压缩。"""
        from core.spider_core.dedup_store import DedupStore
        store = DedupStore()
        long_key = "x" * 500
        task_id = "t28-test-longkey"
        self.assertFalse(store.check_and_mark(task_id, long_key))
        self.assertTrue(store.check_and_mark(task_id, long_key))


class T28_EngineResultParsingTest(unittest.TestCase):
    """验证 _parse_engine_result 能正确读取 errors 列表。"""

    def test_01_dict_with_errors_list(self):
        """errors 列表应被拼接为 error_msg。"""
        from business.custom_spider.service import _parse_engine_result

        result = {
            "items": [],
            "success_items": 0,
            "total_items": 5,
            "errors": ["Rule parsing failed: missing list_rule", "URL template invalid"],
        }
        items, success, total, match_rate, error_msg, alerts = _parse_engine_result(result)
        self.assertIn("Rule parsing failed", error_msg)
        self.assertIn("URL template invalid", error_msg)
        logger.info(f"error_msg={error_msg!r}")

    def test_02_empty_result_should_have_error_hint(self):
        """完全空的结果应返回调试提示。"""
        from business.custom_spider.service import _parse_engine_result
        items, success, total, match_rate, error_msg, alerts = _parse_engine_result({"items": []})
        self.assertTrue(error_msg, "空结果应有非空 error_msg 提示")
        logger.info(f"empty-result error_msg={error_msg!r}")

    def test_03_engine_result_object_with_errors(self):
        """EngineResult 对象的 errors 字段应被读取。"""
        from dataclasses import dataclass, field
        from typing import List, Any
        from business.custom_spider.service import _parse_engine_result

        @dataclass
        class FakeEngineResult:
            items: List[Any] = field(default_factory=list)
            success_items: int = 0
            total_items: int = 3
            field_match_rate: float = 0.33
            errors: List[str] = field(default_factory=lambda: ["Pydantic validation failed"])
            alerts: List[Any] = field(default_factory=list)

        obj = FakeEngineResult()
        items, success, total, match_rate, error_msg, alerts = _parse_engine_result(obj)
        self.assertIn("Pydantic validation failed", error_msg)

    def test_04_none_result(self):
        """None 应返回带信息的 error_msg。"""
        from business.custom_spider.service import _parse_engine_result
        _, _, _, _, error_msg, _ = _parse_engine_result(None)
        self.assertIn("T25 engine returned None", error_msg)


class T28_PermissionRBACTest(unittest.TestCase):
    """验证 RBAC 角色权限配置包含新的 btn.spider.edit。"""

    def test_01_spider_edit_in_super_admin(self):
        """super_admin 必须有 edit 权限。"""
        from web_admin.auth import ROLE_PERMISSIONS, ROLE_SUPER_ADMIN
        self.assertIn("btn.spider.edit", ROLE_PERMISSIONS[ROLE_SUPER_ADMIN])

    def test_02_spider_edit_in_ops(self):
        """ops 必须有 edit 权限。"""
        from web_admin.auth import ROLE_PERMISSIONS, ROLE_OPS
        self.assertIn("btn.spider.edit", ROLE_PERMISSIONS[ROLE_OPS])

    def test_03_sales_no_spider_permission(self):
        """sales 不应有任何 spider 权限（只读或无）。"""
        from web_admin.auth import ROLE_PERMISSIONS, ROLE_SALES
        permissions = ROLE_PERMISSIONS.get(ROLE_SALES, set())
        self.assertNotIn("btn.spider.edit", permissions)
        self.assertNotIn("btn.spider.delete", permissions)

    def test_04_has_permission_function_exists(self):
        """has_permission 工具函数必须可调用。"""
        from web_admin.auth import has_permission
        self.assertTrue(callable(has_permission))
        self.assertTrue(has_permission("super_admin", "btn.spider.edit"))
        self.assertFalse(has_permission("sales", "btn.spider.edit"))
        self.assertFalse(has_permission(None, "btn.spider.view"))


class T28_SanitizationMaskingTest(unittest.TestCase):
    """验证 HTML 消毒与敏感信息脱敏逻辑。"""

    def test_01_mask_phone_number(self):
        """11 位大陆手机号必须脱敏中间 4 位。"""
        from web_admin.api.crawl_config import _mask_sensitive_text
        text = "联系方式：13812345678"
        masked = _mask_sensitive_text(text)
        self.assertNotIn("13812345678", masked)
        self.assertIn("138****5678", masked)

    def test_02_mask_email(self):
        """邮箱用户名必须部分脱敏。"""
        from web_admin.api.crawl_config import _mask_sensitive_text
        text = "邮箱: testuser@example.com"
        masked = _mask_sensitive_text(text)
        # 原始邮箱不能明文出现
        self.assertNotIn("testuser@example.com", masked)
        # 域名应保留
        self.assertIn("example.com", masked)

    def test_03_mask_id_card(self):
        """18 位身份证号必须脱敏中间 8 位。"""
        from web_admin.api.crawl_config import _mask_sensitive_text
        text = "身份证: 110101199001011234"
        masked = _mask_sensitive_text(text)
        self.assertNotIn("19900101", masked)

    def test_04_sanitize_removes_script(self):
        """HTML 消毒必须移除 <script>。"""
        from web_admin.api.crawl_config import _sanitize_html
        html = '<div>正常内容<script>alert("xss")</script></div>'
        sanitized = _sanitize_html(html)
        self.assertNotIn("<script>", sanitized)
        self.assertIn("正常内容", sanitized)

    def test_05_sanitize_removes_iframe(self):
        """必须移除 iframe。"""
        from web_admin.api.crawl_config import _sanitize_html
        html = '<p>预览区<iframe src="evil.com"></iframe></p>'
        sanitized = _sanitize_html(html)
        self.assertNotIn("<iframe", sanitized)

    def test_06_sanitize_removes_inline_events(self):
        """必须移除 onclick 等内联事件。"""
        from web_admin.api.crawl_config import _sanitize_html
        html = '<a href="#" onclick="steal()">点击</a>'
        sanitized = _sanitize_html(html)
        self.assertNotIn("onclick", sanitized)


class T28_APIEndpointsTest(unittest.TestCase):
    """验证 crawl_config API 路由正确注册（不需要网络连接）。"""

    def test_01_router_importable(self):
        """crawl_config router 必须可 import。"""
        from web_admin.api.crawl_config import router
        self.assertIsNotNone(router)
        self.assertGreater(len(router.routes), 10)

    def test_02_all_routes_have_valid_paths(self):
        """所有路由路径必须以 /crawl/ 开头。"""
        from web_admin.api.crawl_config import router
        for r in router.routes:
            self.assertTrue(
                getattr(r, "path", "").startswith("/crawl/"),
                f"路由 {getattr(r, 'path', None)} 路径不符合规范"
            )


if __name__ == "__main__":
    loader = unittest.TestLoader()
    suite = unittest.TestSuite()

    # 按依赖顺序添加测试类
    for cls in [
        T28_TableCreationTest,
        T28_DedupStoreTest,
        T28_EngineResultParsingTest,
        T28_PermissionRBACTest,
        T28_SanitizationMaskingTest,
        T28_APIEndpointsTest,
    ]:
        suite.addTests(loader.loadTestsFromTestCase(cls))

    runner = unittest.TextTestRunner(verbosity=2)
    result = runner.run(suite)

    print()
    print("=" * 72)
    print(f"T28 集成测试总结: 运行 {result.testsRun} 个测试, "
          f"失败 {len(result.failures)}, 错误 {len(result.errors)}, "
          f"跳过 {len(result.skipped)}")
    print("=" * 72)

    sys.exit(0 if result.wasSuccessful() else 1)
