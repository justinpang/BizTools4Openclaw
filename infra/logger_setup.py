from __future__ import annotations

import os
import sys
from pathlib import Path
from typing import Any

from loguru import logger

from configs.settings import settings

# 模块级状态：确保初始化幂等
_INITIALIZED: bool = False


def _build_log_format(debug: bool) -> str:
    """构建日志格式字符串，debug 模式下更详细。"""
    base = (
        "<green>{time:YYYY-MM-DD HH:mm:ss.SSS}</green> | "
        "<level>{level:<8}</level> | "
        "<cyan>{extra[module]}</cyan> | "
        "<level>{message}</level>"
    )
    if debug:
        base += " | <yellow>{file}:{function}:{line}</yellow>"
    return base


def setup_logger(*, force: bool = False) -> None:
    """初始化 loguru。多次调用幂等。

    - 控制台 sink：彩色，按级别过滤
    - 主文件 sink：按天切割；过期自动删除
    - 错误文件 sink：ERROR 级别单独落盘
    """
    global _INITIALIZED
    if _INITIALIZED and not force:
        return

    # 清空 loguru 默认 sink（避免重复输出）
    logger.remove()

    log_level = str(settings.log.LOG_LEVEL).upper()
    debug = bool(settings.project.DEBUG)
    fmt = _build_log_format(debug)

    # ---- 控制台 ----
    if settings.log.LOG_CONSOLE_ENABLED:
        logger.add(
            sys.stderr,
            level=log_level,
            colorize=True,
            format=fmt,
            enqueue=True,
            backtrace=debug,
            diagnose=False,
        )

    # ---- 文件 ----
    if settings.log.LOG_FILE_ENABLED:
        log_dir = Path(settings.log.LOG_DIR)
        try:
            log_dir.mkdir(parents=True, exist_ok=True)
        except OSError:
            # 目录不可写时，降级到控制台
            pass
        else:
            main_path = str(log_dir / "{time:YYYY-MM-DD}.log")
            error_path = str(log_dir / "error_{time:YYYY-MM-DD}.log")

            logger.add(
                main_path,
                level=log_level,
                rotation=settings.log.LOG_ROTATION,
                retention=settings.log.LOG_RETENTION,
                encoding="utf-8",
                format=fmt,
                enqueue=True,
                backtrace=debug,
                diagnose=False,
            )

            logger.add(
                error_path,
                level="ERROR",
                rotation=settings.log.LOG_ROTATION,
                retention=settings.log.LOG_RETENTION,
                encoding="utf-8",
                format=fmt,
                enqueue=True,
                backtrace=debug,
                diagnose=False,
            )

    # 为 logger 注入默认 extra 字段
    logger.configure(extra={"module": "app"})

    _INITIALIZED = True


def get_logger(module_name: str | None = None, **extra: Any) -> Any:
    """获取配置后的 logger 实例。

    Args:
        module_name: 模块名，通常传入 `__name__`
        extra: 额外字段，会合并到 loguru extra
    """
    setup_logger()

    ctx_extra: dict[str, Any] = {"module": module_name or "app"}
    ctx_extra.update(extra)
    return logger.bind(**ctx_extra)


# 静默忽略，避免 lint 告警
_ = os.sep

__all__ = ["setup_logger", "get_logger", "logger"]
