"""全局 pytest 配置与环境变量注入。

注意：必须在模块 **顶层** (非 fixture 内) 设置 os.environ，
因为 settings / core.compliance / infra.db_base 等模块在
首次 import 时就会读取环境变量，而 fixture 的执行在这之后。
"""
import os

# 早于任何业务模块的 import，为测试会话设定稳定的默认值。
os.environ.setdefault("DB_ENCRYPTION_KEY", "test-32-chars-encryption-key--01")
os.environ.setdefault("DB_ARCHIVE_DAYS", "90")
os.environ.setdefault("DB_ARCHIVE_HOT_THRESHOLD", "1000")

# 让 log 等级降低，避免测试输出过于杂乱。
os.environ.setdefault("LOG_LEVEL", "WARNING")
