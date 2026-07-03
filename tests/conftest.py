"""全局 pytest 配置与环境变量注入。

注意：必须在模块 **顶层** (非 fixture 内) 设置 os.environ，
因为 settings / core.compliance / infra.db_base 等模块在
首次 import 时就会读取环境变量，而 fixture 的执行在这之后。

本 conftest 同时负责：
  - 注册 sqlite3 的显式 datetime 适配器，避免 Python 3.12+ 的弃用警告。
  - 在测试会话结束时释放 infra.db_base 的 SQLAlchemy engine，避免未关闭连接警告。
  - 维护一个"测试创建的 sqlite3 内存连接注册表"，并在每个测试函数结束后关闭它们。
  - 抑制来自第三方库（starlette / httpx / pytest-asyncio）的上游弃用警告。
"""
# 必须放在模块最开头：先于任何第三方模块的 import 之前抑制上游弃用警告。
import warnings as _warnings
_warnings.filterwarnings(
    "ignore",
    message="Using `httpx` with `starlette.testclient` is deprecated",
)
_warnings.filterwarnings(
    "ignore",
    category=DeprecationWarning,
    message=".*pytest-asyncio.*",
)

import os
import threading

import pytest

# -------- 环境变量：在 import infra/core/business 之前注入 --------
os.environ.setdefault("DB_ENCRYPTION_KEY", "test-32-chars-encryption-key--01")
os.environ.setdefault("DB_ARCHIVE_DAYS", "90")
os.environ.setdefault("DB_ARCHIVE_HOT_THRESHOLD", "1000")
os.environ.setdefault("LOG_LEVEL", "WARNING")

# -------- sqlite3 datetime adapter：Python 3.12 起默认 adapter 被弃用 --------
def _register_sqlite3_datetime_adapters() -> None:
    """显式注册 sqlite3 的 datetime / date 适配器，避开默认 adapter 的 deprecation 警告。"""
    try:
        import sqlite3
        from datetime import datetime, date

        def _adapt_datetime(value: datetime) -> bytes:
            return value.isoformat(timespec="seconds").encode("ascii")

        def _adapt_date(value: date) -> bytes:
            return value.isoformat().encode("ascii")

        try:
            sqlite3.register_adapter(datetime, _adapt_datetime)
            sqlite3.register_adapter(date, _adapt_date)
        except Exception:
            pass
    except Exception:
        pass


_register_sqlite3_datetime_adapters()

# -------- 测试中创建的 sqlite3 内存连接注册表 + autouse teardown --------
_test_sqlite_conn_lock = threading.Lock()
_test_sqlite_conns: list[object] = []


def _register_test_sqlite_conn(conn) -> None:
    """在测试函数内创建的 sqlite3.Connection，注册后会在测试结束时自动关闭。"""
    try:
        with _test_sqlite_conn_lock:
            _test_sqlite_conns.append(conn)
    except Exception:
        pass


def pytest_configure(config):
    """pytest 启动时的统一钩子。目前仅用于确保注册器已被 import。"""
    # 无操作；保留该函数以便未来扩展。
    _ = config


@pytest.fixture(autouse=True)
def _auto_close_test_sqlite_conns():
    """每个测试函数结束后关闭本测试注册过的 sqlite3 内存连接，避免 unclosed database。"""
    yield
    with _test_sqlite_conn_lock:
        pending = list(_test_sqlite_conns)
        _test_sqlite_conns.clear()
    for c in pending:
        try:
            c.close()
        except Exception:
            pass


# -------- pytest 会话级 teardown：释放 DB engine --------
def pytest_sessionfinish(session, exitstatus):
    """在整个 pytest 会话结束后释放 DB engine，避免未关闭连接的 ResourceWarning。"""
    try:
        from infra.db_base import database
        if hasattr(database, "dispose"):
            database.dispose()
    except Exception:
        pass
    # 兜底：关闭所有未关闭的 sqlite3 连接
    with _test_sqlite_conn_lock:
        pending = list(_test_sqlite_conns)
        _test_sqlite_conns.clear()
    for c in pending:
        try:
            c.close()
        except Exception:
            pass
