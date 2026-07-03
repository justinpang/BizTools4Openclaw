"""tests/test_t14_web_admin.py — T14 Web 管理后台单元测试。"""

from __future__ import annotations

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

os.environ.setdefault("WEB_ADMIN_PASSWORD_PLAIN", "unittest-admin")

import unittest


class TestT14WebAdminSettings(unittest.TestCase):

    def test_web_admin_settings_present(self):
        from configs.settings import settings
        self.assertTrue(settings.web_admin.WEB_ADMIN_ENABLED)
        self.assertTrue(str(settings.web_admin.WEB_ADMIN_PATH_PREFIX).startswith("/admin"))


class TestT14Auth(unittest.TestCase):

    def test_session_lifecycle(self):
        from web_admin.auth import create_session, _get_session_raw, delete_session
        token = create_session("unittest-admin", client_ip="127.0.0.1")
        self.assertTrue(isinstance(token, str) and len(token) > 4)
        s = _get_session_raw(token)
        self.assertIsNotNone(s)
        delete_session(token)

    def test_depends_reject_no_session(self):
        from fastapi.testclient import TestClient
        from adapter.main import app
        with TestClient(app) as client:
            r = client.get("/api/admin/dashboard/stats")
            # 没登录返回 401
            self.assertIn(r.status_code, (401, 403))


class TestT14Pages(unittest.TestCase):

    def test_login_page(self):
        from fastapi.testclient import TestClient
        from adapter.main import app
        with TestClient(app) as client:
            r = client.get("/admin/login")
            self.assertEqual(r.status_code, 200)
            self.assertIn("登录", r.text)

    def test_dashboard_page(self):
        from fastapi.testclient import TestClient
        from adapter.main import app
        with TestClient(app) as client:
            # 未登录 → 重定向
            r = client.get("/admin/dashboard", follow_redirects=False)
            self.assertIn(r.status_code, (302, 401))


class TestT14APIs(unittest.TestCase):

    def test_list_spider_tasks_unauthed(self):
        from fastapi.testclient import TestClient
        from adapter.main import app
        with TestClient(app) as client:
            r = client.get("/api/admin/spider/tasks")
            self.assertIn(r.status_code, (401, 403))

    def test_list_channels_unauthed(self):
        from fastapi.testclient import TestClient
        from adapter.main import app
        with TestClient(app) as client:
            r = client.get("/api/admin/channels")
            self.assertIn(r.status_code, (401, 403))

    def test_list_sales_unauthed(self):
        from fastapi.testclient import TestClient
        from adapter.main import app
        with TestClient(app) as client:
            r = client.get("/api/admin/sales/persons")
            self.assertIn(r.status_code, (401, 403))

    def test_mask_phone(self):
        # 脱敏工具不依赖底层服务
        from web_admin.api.lead_mgmt import _mask_value
        self.assertIn("****", _mask_value("13800000000"))
        self.assertIn("@", _mask_value("alice@example.com"))


class TestT14Middleware(unittest.TestCase):

    def test_middleware_build(self):
        from web_admin.middleware import build_audit_middleware, load_audit_logs
        def session_getter(request): return {"username": "test"}
        mw = build_audit_middleware(session_getter)
        self.assertTrue(callable(mw))
        self.assertIsInstance(load_audit_logs(limit=3), list)


class TestT14Menu(unittest.TestCase):

    def test_menu_structure(self):
        from web_admin.menu import MENU
        keys = [m["key"] for m in MENU]
        for expected in ["dashboard", "spider", "leads", "channels", "sales", "audit_log"]:
            self.assertIn(expected, keys)


def run_tests() -> int:
    loader = unittest.TestLoader()
    suite = loader.loadTestsFromModule(sys.modules[__name__])
    runner = unittest.TextTestRunner(verbosity=2)
    result = runner.run(suite)
    return 0 if result.wasSuccessful() else 1


if __name__ == "__main__":
    sys.exit(run_tests())
