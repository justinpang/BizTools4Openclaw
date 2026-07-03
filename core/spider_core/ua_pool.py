from __future__ import annotations

import os
import random
import threading
from typing import Optional

from infra.logger_setup import get_logger

logger = get_logger("spider.ua_pool")

# 内置兜底 UA（3 desktop + 3 mobile）
_BUILTIN_DESKTOP_UAS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 14_2) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.2 Safari/605.1.15",
    "Mozilla/5.0 (X11; Linux x86_64; rv:121.0) Gecko/20100101 Firefox/121.0",
]

_BUILTIN_MOBILE_UAS = [
    "Mozilla/5.0 (iPhone; CPU iPhone OS 17_2 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.2 Mobile/15E148 Safari/604.1",
    "Mozilla/5.0 (Linux; Android 13; Pixel 7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Mobile Safari/537.36",
    "Mozilla/5.0 (iPhone; CPU iPhone OS 16_6 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/16.6 Mobile/15E148 Safari/604.1",
]

_MOBILE_HINTS = ("android", "iphone", "ipad", "mobile", "mobile safari", "silk/")


class UserAgentPool:
    """UA 池：支持从文件加载 + 内置兜底；mobile/desktop/random 三种模式。"""

    def __init__(
        self,
        *,
        file_path: str = "",
        default_mode: str = "random",
    ) -> None:
        self._file_path = file_path
        self._default_mode = default_mode.lower() if default_mode else "random"
        if self._default_mode not in ("mobile", "desktop", "random"):
            self._default_mode = "random"
        self._desktop: list[str] = []
        self._mobile: list[str] = []
        self._lock = threading.RLock()
        self._last_file_mtime: Optional[float] = None
        self._load_initial()

    # ---------------- 加载 ----------------

    def _load_initial(self) -> None:
        if self._file_path and os.path.isfile(self._file_path):
            try:
                self._load_from_file(self._file_path)
                self._last_file_mtime = os.path.getmtime(self._file_path)
                logger.info(f"UA 池已从文件加载: {self._file_path} "
                            f"(desktop={len(self._desktop)}, mobile={len(self._mobile)})")
                return
            except Exception as exc:
                logger.warning(f"UA 文件加载失败: {exc}，回退内置 UA")
        # 回退内置
        self._load_builtin()

    def _load_from_file(self, path: str) -> None:
        desktop: list[str] = []
        mobile: list[str] = []
        with open(path, "r", encoding="utf-8") as f:
            for raw in f:
                line = raw.strip()
                if not line or line.startswith("#"):
                    continue
                if any(hint in line.lower() for hint in _MOBILE_HINTS):
                    mobile.append(line)
                else:
                    desktop.append(line)
        if not desktop and not mobile:
            raise ValueError(f"UA 文件中未发现有效 UA: {path}")
        with self._lock:
            self._desktop = desktop
            self._mobile = mobile

    def _load_builtin(self) -> None:
        with self._lock:
            self._desktop = list(_BUILTIN_DESKTOP_UAS)
            self._mobile = list(_BUILTIN_MOBILE_UAS)
        logger.info("UA 池使用内置兜底 UA")

    def refresh(self) -> None:
        """重新从文件加载（如果文件被更新）。"""
        try:
            if self._file_path and os.path.isfile(self._file_path):
                mtime = os.path.getmtime(self._file_path)
                if self._last_file_mtime is None or mtime > self._last_file_mtime:
                    self._load_from_file(self._file_path)
                    self._last_file_mtime = mtime
                    logger.info(f"UA 池已刷新: {self._file_path}")
                    return
            # 文件消失或不可读 → 回退内置
            if not self._desktop and not self._mobile:
                self._load_builtin()
        except Exception as exc:
            logger.warning(f"UA 池刷新失败: {exc}")
            if not self._desktop and not self._mobile:
                self._load_builtin()

    # ---------------- 查询 ----------------

    def next(self, mode: Optional[str] = None) -> str:
        """随机返回一个 UA。"""
        effective_mode = (mode or self._default_mode).lower()
        with self._lock:
            desktop = self._desktop
            mobile = self._mobile
        if effective_mode == "desktop":
            pool = desktop if desktop else mobile + desktop
        elif effective_mode == "mobile":
            pool = mobile if mobile else desktop + mobile
        else:  # random
            pool = desktop + mobile
        if not pool:
            logger.warning("UA 池为空，返回默认 UA")
            return _BUILTIN_DESKTOP_UAS[0]
        return random.choice(pool)

    def size(self) -> dict:
        with self._lock:
            return {
                "total": len(self._desktop) + len(self._mobile),
                "desktop": len(self._desktop),
                "mobile": len(self._mobile),
            }

    # ---------------- 属性 ----------------

    @property
    def default_mode(self) -> str:
        return self._default_mode

    @property
    def file_path(self) -> str:
        return self._file_path


__all__ = ["UserAgentPool"]
