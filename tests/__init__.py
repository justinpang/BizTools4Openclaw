"""tests 包的入口：在所有测试模块被 import 之前预先抑制来自第三方库的弃用警告。

这是 conftest.py 中 warning 抑制的早期双保险。原因：
  - pytest 在导入 conftest.py 之后才会调用我们的 fixtures；
  - 但某些测试模块（如 test_t13_openclaw_adapter.py、test_t14_web_admin.py）
    在第一行就执行了 `from fastapi.testclient import TestClient`，
    它内部会 `from starlette.testclient import TestClient`，在 import 时
    就触发 `StarletteDeprecationWarning`；
  - 该 warning 发生在包的导入阶段，早于 conftest.py 的 fixtures 执行，
    因此我们需要在 tests 包被 import 时立即注册 filter。
"""

import warnings

# 抑制来自 starlette / fastapi 的 httpx 弃用警告（上游库问题，不在本仓库修复范围）
warnings.filterwarnings(
    "ignore",
    message="Using `httpx` with `starlette.testclient` is deprecated",
)
warnings.filterwarnings(
    "ignore",
    category=DeprecationWarning,
    message=".*pytest-asyncio.*",
)
