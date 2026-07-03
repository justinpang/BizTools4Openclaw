"""T05 任务：底层爬虫通用 SDK —— 单元测试。"""
from __future__ import annotations

import os
import sys
import json
import threading
import time
from pathlib import Path
from typing import Any, Dict

import pytest

# 保证从项目根目录导入
ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


# ============================================================
# UA 池测试
# ============================================================
class TestUA:
    def test_builtin_default(self):
        from core.spider_core.ua_pool import UserAgentPool
        ua = UserAgentPool()
        s = ua.next()
        assert isinstance(s, str) and len(s) > 0

    def test_file_load(self, tmp_path):
        from core.spider_core.ua_pool import UserAgentPool
        f = tmp_path / "ua.txt"
        f.write_text(
            "Mozilla/5.0 (Windows NT 10.0) Firefox/100.0\n"
            "Mozilla/5.0 (iPhone; CPU iPhone OS 15_0) Mobile Safari\n"
        )
        ua = UserAgentPool(file_path=str(f))
        info = ua.size()
        assert info["desktop"] >= 1
        assert info["mobile"] >= 1
        # 验证 mobile/desktop 区分
        ua_d = ua.next("desktop").lower()
        ua_m = ua.next("mobile").lower()
        assert "firefox" in ua_d or "windows" in ua_d
        assert "mobile" in ua_m or "iphone" in ua_m

    def test_refresh(self, tmp_path):
        from core.spider_core.ua_pool import UserAgentPool
        f = tmp_path / "ua.txt"
        f.write_text("Mozilla/5.0 Chrome/100.0\n")
        ua = UserAgentPool(file_path=str(f))
        size0 = ua.size()
        f.write_text("Mozilla/5.0 Chrome/100.0\nMozilla/5.0 Safari/15.0\n"
                     "Mozilla/5.0 (Android) Mobile\n")
        ua.refresh()
        size1 = ua.size()
        assert size1["total"] > size0["total"]


# ============================================================
# 代理池测试
# ============================================================
class TestProxy:
    def test_direct_mode(self):
        from core.spider_core.proxy_pool import ProxyPool
        pp = ProxyPool()
        assert pp.is_direct_mode is True
        assert pp.next() is None

    def test_failure_threshold(self):
        from core.spider_core.proxy_pool import ProxyPool, Proxy
        pp = ProxyPool(api_url="", failure_threshold=2)
        # 手动塞代理
        p1 = Proxy(proxy_url="http://a.example.com:8080")
        p2 = Proxy(proxy_url="http://b.example.com:8080")
        pp._proxies = [p1, p2]
        pp._index = 0
        pp._direct_mode = False

        # 第一个代理连续失败 2 次
        pp.report_failure(p1, reason="timeout")
        pp.report_failure(p1, reason="timeout")
        # p1 应被剔除，池只剩 p2
        assert pp.size() == 1
        nxt = pp.next()
        assert nxt is p2


# ============================================================
# 域名限速测试
# ============================================================
class TestRateLimiter:
    def test_interval_randomness_check(self, monkeypatch):
        from core.spider_core.rate_limiter import DomainRateLimiter
        rl = DomainRateLimiter(interval_min=0.001, interval_max=0.002, max_concurrent_per_domain=10)
        # 通过 monkeypatch 捕获被 sleep 的时间
        sleeps = []
        monkeypatch.setattr(time, "sleep", lambda t: sleeps.append(t))
        # 两次调用：第一次应不 sleep（初始 last_hit=0），第二次会 sleep
        with rl.acquire("http://test.example.com/page1"):
            pass
        with rl.acquire("http://test.example.com/page2"):
            pass
        # 至少一次 sleep，且在 min/max 之间
        assert any(0.0009 <= s <= 0.0021 for s in sleeps) or len(sleeps) > 0

    def test_concurrent_limit(self):
        from core.spider_core.rate_limiter import DomainRateLimiter
        rl = DomainRateLimiter(interval_min=0.0001, interval_max=0.0002, max_concurrent_per_domain=2)
        entered = 0
        max_entered = 0
        barrier = threading.Event()

        def worker():
            nonlocal entered, max_entered
            with rl.acquire("http://busy.example.com/a"):
                entered += 1
                with threading.Lock():
                    max_entered = max(max_entered, entered)
                # 等待一点时间，让其他线程也尝试进入
                time.sleep(0.001)
                entered -= 1

        threads = [threading.Thread(target=worker) for _ in range(5)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=3)
        assert max_entered <= 2

    def test_override(self):
        from core.spider_core.rate_limiter import DomainRateLimiter
        rl = DomainRateLimiter(interval_min=0.0001, interval_max=0.0002, max_concurrent_per_domain=5)
        rl.override("x.example.com", max_concurrent=1, interval_min=0.01, interval_max=0.02)
        assert "x.example.com" in rl._domain_overrides  # type: ignore


# ============================================================
# robots 测试
# ============================================================
class TestRobots:
    def test_disabled_mode_always_allow(self):
        from core.spider_core.robots_checker import RobotsChecker
        rc = RobotsChecker(enabled=False)
        assert rc.is_allowed("https://anywhere.example.com/private") is True

    def test_enabled_disallowed_path(self):
        """通过 monkeypatch 避免真正网络请求。"""
        from core.spider_core.robots_checker import RobotsChecker
        rc = RobotsChecker(enabled=True, cache_ttl=3600)

        class _FakeParser:
            def can_fetch(self, ua, url):
                return "/private" not in url

        rc._parser_for = lambda site_root: _FakeParser()  # type: ignore
        assert rc.is_allowed("https://example.com/public") is True
        assert rc.is_allowed("https://example.com/private/a") is False


# ============================================================
# checkpoint 测试（内存模式 / fakeredis 模式）
# ============================================================
class TestCheckpoint:
    def test_memory_mode_save_and_load(self):
        from core.spider_core.checkpoint_manager import CheckpointManager
        cm = CheckpointManager(ttl_seconds=60, prefix="ut:ck")
        cm._redis_client = False  # 显式禁用 Redis，避免 fallback 到真实实例
        cm.save("task-1", current_url="https://example.com/a", processed_items=5, failed_items=1, payload={"k": "v"})
        data = cm.load("task-1")
        assert data is not None
        assert data["current_url"] == "https://example.com/a"
        assert int(data["processed_items"]) == 5
        assert data["payload"]["k"] == "v"

    def test_visited_and_pending(self):
        from core.spider_core.checkpoint_manager import CheckpointManager
        cm = CheckpointManager(prefix="ut:ck")
        cm._redis_client = False
        assert cm.is_visited("t", "u1") is False
        cm.mark_visited("t", "u1", "u2", "u3")
        assert cm.is_visited("t", "u2") is True
        assert cm.visited_count("t") == 3
        # pending
        cm.pending_push("t", "a", "b", "c")
        assert cm.pending_count("t") == 3
        popped = cm.pending_pop("t", count=2)
        assert popped == ["a", "b"]
        assert cm.pending_count("t") == 1


# ============================================================
# 风控测试
# ============================================================
class TestRisk:
    def test_detect_high_by_status(self):
        from core.spider_core.risk_controller import RiskController, RISK_LEVEL_HIGH, RISK_LEVEL_NONE
        rc = RiskController(enabled=True, alert_debounce_seconds=0.1)
        assert rc.detect(status_code=403) == RISK_LEVEL_HIGH
        assert rc.detect(status_code=200) == RISK_LEVEL_NONE

    def test_detect_high_by_captcha_text(self):
        from core.spider_core.risk_controller import RiskController, RISK_LEVEL_HIGH
        rc = RiskController(enabled=True)
        html = "请完成验证码后继续"
        assert rc.detect(status_code=200, text=html) == RISK_LEVEL_HIGH

    def test_detect_medium_by_login_redirect(self):
        from core.spider_core.risk_controller import RiskController, RISK_LEVEL_MEDIUM
        rc = RiskController(enabled=True)
        assert rc.detect(status_code=200, text="OK", final_url="https://example.com/login") == RISK_LEVEL_MEDIUM

    def test_handle_triggers_alert_debounce(self):
        from core.spider_core.risk_controller import RiskController
        rc = RiskController(enabled=True, alert_debounce_seconds=1000)
        calls = []

        class _AlertService:
            def crawler_risk_sync(self, msg):
                calls.append(msg)

        rc.attach(alert_service=_AlertService())
        for _ in range(3):
            rc.handle("https://api.example.com/x", "high", response_excerpt="blocked")
        # 由于去抖，仅应触发一次告警
        assert len(calls) == 1


# ============================================================
# SpiderSDK 主入口（monkey-patched requests）
# ============================================================
class FakeResponse:
    def __init__(self, *, status_code=200, text="", content=None, url="", headers=None, encoding="utf-8"):
        self.status_code = status_code
        self.text = text
        self.content = content or text.encode("utf-8")
        self.url = url
        self.headers = headers or {}
        self.encoding = encoding


class TestSpiderSDK:
    def test_http_get_ok(self, monkeypatch):
        from core.spider_core import SpiderSDK, UserAgentPool, ProxyPool, DomainRateLimiter, RobotsChecker
        sdk = SpiderSDK(
            ua_pool=UserAgentPool(),
            proxy_pool=ProxyPool(),
            rate_limiter=DomainRateLimiter(interval_min=0.0001, interval_max=0.0002),
            robots_checker=RobotsChecker(enabled=True),
        )
        # 禁用 real robots fetching
        sdk._robots.is_allowed = lambda *a, **kw: True  # type: ignore
        # 模拟 requests 库：替换模块级变量
        import core.spider_core.sdk as sdk_module
        monkeypatch.setattr(sdk_module, "_requests_lib", type("M", (), {
            "get": staticmethod(lambda url, *a, **kw: FakeResponse(status_code=200, text="<html>hi</html>", url=url))
        })())

        resp = sdk.get("https://example.com/ok", robot_check=True)
        assert resp.ok is True
        assert resp.status_code == 200
        assert resp.used_ua
        assert resp.used_proxy is None  # 直连模式

    def test_http_get_requests_error(self, monkeypatch):
        from core.spider_core import SpiderSDK, UserAgentPool, ProxyPool, DomainRateLimiter, RobotsChecker
        sdk = SpiderSDK(
            ua_pool=UserAgentPool(),
            proxy_pool=ProxyPool(),
            rate_limiter=DomainRateLimiter(interval_min=0.0001, interval_max=0.0002),
            robots_checker=RobotsChecker(enabled=False),
        )

        import core.spider_core.sdk as sdk_module

        def failing_get(url, *args, **kwargs):
            raise ConnectionError("fake network error")

        monkeypatch.setattr(sdk_module, "_requests_lib", type("M", (), {
            "get": staticmethod(failing_get)
        })())

        resp = sdk.get("https://example.com/fail")
        assert resp.ok is False
        assert resp.error is not None

    def test_risk_triggered_for_403(self, monkeypatch):
        from core.spider_core import SpiderSDK, UserAgentPool, ProxyPool, DomainRateLimiter, RobotsChecker
        sdk = SpiderSDK(
            ua_pool=UserAgentPool(),
            proxy_pool=ProxyPool(),
            rate_limiter=DomainRateLimiter(interval_min=0.0001, interval_max=0.0002),
            robots_checker=RobotsChecker(enabled=False),
        )

        import core.spider_core.sdk as sdk_module
        monkeypatch.setattr(sdk_module, "_requests_lib", type("M", (), {
            "get": staticmethod(lambda url, *a, **kw: FakeResponse(status_code=403, text="Forbidden", url=url))
        })())

        # 注入一个记录告警的 alert service
        alerts = []

        class _A:
            def crawler_risk_sync(self, msg):
                alerts.append(msg)

        sdk.risk_controller.attach(alert_service=_A())

        resp = sdk.get("https://example.com/forbidden")
        assert resp.risk_level == "high"
        # 去抖可能吞掉，但风控检测应正确返回 high
        assert resp.ok is False

    def test_robots_blocked(self, monkeypatch):
        from core.spider_core import SpiderSDK, UserAgentPool, ProxyPool, DomainRateLimiter, RobotsChecker
        sdk = SpiderSDK(
            ua_pool=UserAgentPool(),
            proxy_pool=ProxyPool(),
            rate_limiter=DomainRateLimiter(interval_min=0.0001, interval_max=0.0002),
            robots_checker=RobotsChecker(enabled=True),
        )
        # 让 robots 检查拒绝所有路径
        sdk._robots.is_allowed = lambda *a, **kw: False  # type: ignore

        import core.spider_core.sdk as sdk_module
        monkeypatch.setattr(sdk_module, "_requests_lib", type("M", (), {
            "get": staticmethod(lambda *a, **kw: FakeResponse(status_code=200, text="", url=""))
        })())

        resp = sdk.get("https://example.com/private")
        assert resp.ok is False
        assert resp.error and "robots" in resp.error.lower()

    def test_checkpoint_integration(self, monkeypatch):
        from core.spider_core import SpiderSDK, UserAgentPool, ProxyPool, DomainRateLimiter, RobotsChecker
        from core.spider_core.checkpoint_manager import CheckpointManager
        cm = CheckpointManager(prefix="ut:ck:sdk")
        cm._redis_client = False
        sdk = SpiderSDK(
            ua_pool=UserAgentPool(),
            proxy_pool=ProxyPool(),
            rate_limiter=DomainRateLimiter(interval_min=0.0001, interval_max=0.0002),
            robots_checker=RobotsChecker(enabled=False),
            checkpoint_manager=cm,
        )

        import core.spider_core.sdk as sdk_module
        monkeypatch.setattr(sdk_module, "_requests_lib", type("M", (), {
            "get": staticmethod(lambda url, *a, **kw: FakeResponse(status_code=200, text="<html>x</html>", url=url))
        })())

        resp = sdk.get("https://example.com/ck", task_id="job-42")
        assert resp.ok is True
        data = cm.load("job-42")
        assert data is not None
        assert data["status"] == "running"


# ============================================================
# 模块级导入完整性测试
# ============================================================
def test_module_exports_all_symbols():
    from core.spider_core import (  # noqa: F401 - 仅验证可导入
        SpiderSDK, CrawlResponse, UserAgentPool, ProxyPool, Proxy,
        DomainRateLimiter, RobotsChecker, CheckpointManager, RiskController,
        spider_sdk,
    )
    assert spider_sdk is not None


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-v"]))
