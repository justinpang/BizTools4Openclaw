"""轻量自检：import 检查 + 基本 API 测试。
在没有 pytest 的本地环境使用，输出简单的 pass/fail。
"""
import os
import sys
import traceback

ROOT = os.path.dirname(os.path.abspath(__file__))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

tests = []

def run(name, fn):
    try:
        fn()
        print(f"[OK] {name}")
        tests.append(True)
    except Exception as exc:
        print(f"[FAIL] {name}\n{exc}")
        traceback.print_exc()
        tests.append(False)

def t_settings():
    from configs.settings import settings

    assert settings.project.PROJECT_NAME
    assert settings.log.LOG_LEVEL in {"DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"}

def t_response():
    from infra.response import ApiResponse, fail, ok

    r = ok({"id": 1})
    d = r.model_dump()
    assert set(d.keys()) == {"code", "msg", "data", "timestamp"}
    assert d["code"] == 0
    body, status = fail(10000, "boom")
    assert body.code == 10000 and status == 400

def t_exceptions():
    from infra.exceptions import BizException, ErrorCode

    e = BizException("x", code=ErrorCode.TASK_FAILURE, http_status=500, trigger_alert=True)
    assert str(e) == "x" and e.code == ErrorCode.TASK_FAILURE

def t_logger():
    from infra.logger_setup import get_logger, setup_logger

    setup_logger(force=True)
    lg = get_logger("t02_selfcheck")
    lg.info("logger check ok")

def t_alerting():
    from infra.alerting import AlertService, AlertType, alert_service

    assert isinstance(alert_service, AlertService)
    assert AlertService() is alert_service  # 单例
    # 未启用告警时调用 send_sync 应静默
    alert_service.send_sync(AlertType.TASK_FAILURE, "t", "c")

def t_exception_handler_register():
    try:
        from fastapi import FastAPI
    except Exception:
        print("  (fastapi 未安装，跳过)")
        return
    from infra.exception_handler import register_exception_handlers

    app = FastAPI()
    register_exception_handlers(app)
    assert len(app.exception_handlers) >= 3


if __name__ == "__main__":
    run("settings", t_settings)
    run("response", t_response)
    run("exceptions", t_exceptions)
    run("logger", t_logger)
    run("alerting", t_alerting)
    run("exception_handler_register", t_exception_handler_register)
    total = len(tests)
    passed = sum(1 for x in tests if x)
    print(f"\n==> {passed}/{total} passed")
    sys.exit(0 if passed == total else 1)
