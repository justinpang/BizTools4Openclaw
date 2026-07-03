"""tests/test_t13_openclaw_adapter — T13 OpenClaw 网关单元测试。"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

# 确保从项目根导入
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from adapter.schema_adapter import mask_output, normalize_request_params  # noqa: E402
from adapter.tool_registry import TOOL_REGISTRY, list_tools, get_tool  # noqa: E402
from adapter.models import ApiResponse, ToolDefinition  # noqa: E402
from adapter.response import ok, error  # noqa: E402


class TestT13Models(unittest.TestCase):
    def test_api_response_ok(self):
        r = ok({"a": 1}, trace_id="t1")
        self.assertEqual(r.code, 0)
        self.assertEqual(r.msg, "OK")
        self.assertEqual(r.data, {"a": 1})
        self.assertEqual(r.trace_id, "t1")

    def test_api_response_error(self):
        r = error(500, "fail", trace_id="t2")
        self.assertEqual(r.code, 500)
        self.assertEqual(r.msg, "fail")
        self.assertEqual(r.trace_id, "t2")


class TestT13ToolRegistry(unittest.TestCase):
    def test_registry_not_empty(self):
        self.assertGreaterEqual(len(TOOL_REGISTRY), 10)
        for name, meta in TOOL_REGISTRY.items():
            self.assertIn("module", meta)
            self.assertIn("func", meta)
            self.assertIn("tool_type", meta)

    def test_list_tools_schema(self):
        defs = list_tools()
        self.assertIsInstance(defs, list)
        self.assertEqual(len(defs), len(TOOL_REGISTRY))
        for t in defs:
            self.assertIsInstance(t, ToolDefinition)
            self.assertTrue(t.endpoint.startswith("/api/v1/tools/"))
            self.assertIn("execute", t.endpoint)
            self.assertIn("properties", t.inputs)
            self.assertIn("type", t.inputs)

    def test_get_tool_unknown(self):
        self.assertIsNone(get_tool("not_exist_tool"))


class TestT13SchemaAdapter(unittest.TestCase):
    def test_mask_phone_email(self):
        raw = {
            "customer_name": "张伟",
            "phone": "13812345678",
            "email": "zhangwei@example.com",
            "score": 0.92,
        }
        masked = mask_output(raw)
        self.assertIsInstance(masked, dict)
        masked_text = str(masked)
        self.assertNotIn("13812345678", masked_text)
        self.assertNotIn("zhangwei@example.com", masked_text)
        self.assertIn("score", masked)

    def test_normalize_dict(self):
        self.assertEqual(normalize_request_params({"a": 1}, tool_name="x"), {"a": 1})

    def test_normalize_none(self):
        self.assertEqual(normalize_request_params(None, tool_name="x"), {})


class TestT13AuthSettings(unittest.TestCase):
    def test_tokens_and_ips_parsing(self):
        from configs.settings import settings
        tokens = settings.adapter.get_tokens()
        self.assertIsInstance(tokens, list)
        self.assertGreaterEqual(len(tokens), 1)
        ips = settings.adapter.get_ips()
        self.assertIsInstance(ips, list)

    def test_quota_positive(self):
        from configs.settings import settings
        self.assertGreaterEqual(int(settings.adapter.ADAPTER_DAILY_QUOTA_PER_AGENT), 0)


class TestT13FastApiApp(unittest.TestCase):
    """测试 FastAPI 应用可启动、路由可挂载。"""

    def test_app_routes(self):
        try:
            from fastapi.testclient import TestClient
        except Exception:
            self.skipTest("fastapi.testclient 不可用")
            return
        from adapter.main import app
        with TestClient(app) as client:
            # /health
            self.assertEqual(client.get("/health").status_code, 200)
            # /api/v1/info
            r = client.get("/api/v1/info")
            self.assertIn(r.status_code, (200, 401, 403))
            # /api/v1/tools 无 token 应该 401
            r = client.get("/api/v1/tools",
                           headers={"Authorization": "Bearer invalid"})
            self.assertIn(r.status_code, (401, 403))
            # /api/v1/tasks 无 token 应该 401
            r = client.get("/api/v1/tasks",
                           headers={"Authorization": "Bearer invalid"})
            self.assertIn(r.status_code, (401, 403))

    def test_health_endpoint(self):
        # 使用 TestClient
        try:
            from fastapi.testclient import TestClient
        except Exception:
            self.skipTest("fastapi.testclient 不可用")
            return
        from adapter.main import app
        with TestClient(app) as client:
            r = client.get("/health")
            self.assertEqual(r.status_code, 200)
            body = r.json()
            self.assertEqual(body.get("status"), "OK")

    def test_tools_list_auth_fail(self):
        try:
            from fastapi.testclient import TestClient
        except Exception:
            self.skipTest("fastapi.testclient 不可用")
            return
        from adapter.main import app
        with TestClient(app) as client:
            r = client.get("/api/v1/tools")  # 无 token
            self.assertIn(r.status_code, (401, 422))


def run_tests() -> int:
    loader = unittest.TestLoader()
    suite = loader.loadTestsFromModule(sys.modules[__name__])
    runner = unittest.TextTestRunner(verbosity=2)
    result = runner.run(suite)
    return 0 if result.wasSuccessful() else 1


if __name__ == "__main__":
    sys.exit(run_tests())
