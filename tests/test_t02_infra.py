from __future__ import annotations

import asyncio
import json
import os
import sys
from unittest.mock import MagicMock, patch

import pytest

# 让 tests 目录可直接 import 同层包
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)


# ---------- 1. configs/settings ----------
def test_settings_defaults_load():
    from configs.settings import settings

    assert settings.project.PROJECT_NAME == "openclaw-business-tools"
    assert str(settings.log.LOG_LEVEL).upper() in {
        "DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL",
    }


# ---------- 2. infra/response ----------
def test_api_response_fields():
    from infra.response import ApiResponse

    resp = ApiResponse[dict](code=0, msg="ok", data={"id": 1})
    payload = resp.model_dump()
    assert set(payload.keys()) == {"code", "msg", "data", "timestamp"}
    assert payload["code"] == 0
    assert payload["data"] == {"id": 1}
    assert isinstance(payload["timestamp"], int)
    json.dumps(payload)


def test_ok_fail_factories():
    from infra.response import fail, ok

    success = ok({"x": 1})
    assert success.code == 0 and success.data == {"x": 1}
    body, status = fail(10000, "boom", data={"k": "v"})
    assert body.code == 10000
    assert body.msg == "boom"
    assert body.data == {"k": "v"}
    assert status == 400


# ---------- 3. infra/exceptions ----------
def test_biz_exception_basic():
    from infra.exceptions import BizException, ErrorCode

    exc = BizException(
        "参数缺失", code=ErrorCode.BIZ_PARAM_ERROR, http_status=400
    )
    assert str(exc) == "参数缺失"
    assert exc.code == ErrorCode.BIZ_PARAM_ERROR
    assert exc.http_status == 400


def test_from_exception_with_biz_exception():
    from infra.exceptions import BizException, ErrorCode
    from infra.response import from_exception

    exc = BizException("任务失败", code=ErrorCode.TASK_FAILURE, http_status=500)
    body, status = from_exception(exc)
    assert body.code == ErrorCode.TASK_FAILURE
    assert status == 500


# ---------- 4. infra/logger_setup ----------
def test_setup_logger_and_get_logger():
    from infra.logger_setup import get_logger, setup_logger

    setup_logger(force=True)
    lg = get_logger("test_module")
    assert lg is not None
    lg.info("hello from infra/logger_setup")


# ---------- 5. infra/alerting (mocked network) ----------
def test_alert_service_is_singleton():
    from infra.alerting import AlertService, alert_service

    another = AlertService()
    assert another is alert_service


def test_alert_service_disabled_via_settings(monkeypatch):
    """即使 alert 被关闭，send_sync 应静默不抛错。"""
    from infra import alerting as alerting_mod
    from infra.alerting import AlertType, alert_service

    monkeypatch.setattr(
        alerting_mod.settings.alert, "ALERT_ENABLED", False
    )
    alert_service.send_sync(AlertType.TASK_FAILURE, "title", "content")


def test_dingtalk_sign_uses_correct_components(monkeypatch):
    """签名：secret 下，生成包含 timestamp + sign 参数的 URL。"""
    import time as _time_mod

    from infra import alerting as alerting_mod

    monkeypatch.setattr(
        alerting_mod.settings.alert, "DINGTALK_WEBHOOK_URL",
        "https://oapi.dingtalk.com/robot/send?access_token=x",
    )
    monkeypatch.setattr(
        alerting_mod.settings.alert, "DINGTALK_SECRET", "some-secret"
    )

    captured = {}
    fixed_ts = 1700000000

    class _FakeAsyncClient:
        def __init__(self, *a, **kw):
            self._captured = captured

        async def post(self, url, json=None):
            captured["url"] = url
            captured["payload"] = json
            resp = MagicMock()
            resp.json.return_value = {"errcode": 0}
            return resp

        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            pass

    class FakeHttpx:
        AsyncClient = _FakeAsyncClient

    # 用 patch.object 在 sys.modules 注入的 httpx 无法拦截内部 local import，
    # 故直接替换 alerting_mod 所在的 sys.modules["httpx"] 也可以，
    # 但最稳的做法是 patch `sys.modules["httpx"]`。
    import sys as _sys
    original_httpx = _sys.modules.get("httpx")
    _sys.modules["httpx"] = FakeHttpx()  # type: ignore
    try:
        with patch.object(alerting_mod, "time", MagicMock(return_value=fixed_ts)):
            ok = asyncio.run(alerting_mod._send_dingtalk_async("t", "c"))
    finally:
        if original_httpx is not None:
            _sys.modules["httpx"] = original_httpx
        else:
            _sys.modules.pop("httpx", None)

    assert ok is True
    assert captured["url"].startswith("https://oapi.dingtalk.com")
    assert "timestamp=" in captured["url"]
    assert "sign=" in captured["url"]
    assert captured["payload"] is not None


def test_split_recipients_handles_empty_and_commas():
    from infra.alerting import _split_recipients

    assert _split_recipients("") == []
    assert _split_recipients("a@b.com, c@d.com") == ["a@b.com", "c@d.com"]


# ---------- 6. FastAPI 全局 handler ----------
def test_register_exception_handlers_does_not_raise():
    try:
        from fastapi import FastAPI  # noqa: F401
    except Exception:
        pytest.skip("fastapi 未安装")

    from infra.exception_handler import register_exception_handlers

    app = FastAPI()
    register_exception_handlers(app)
    assert len(app.exception_handlers) >= 3


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
