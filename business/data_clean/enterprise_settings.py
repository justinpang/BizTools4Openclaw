from __future__ import annotations

import os
from typing import Any

from infra.logger_setup import get_logger

"""business.data_clean.enterprise_settings — T29 企业信息补全：运行时配置。

所有配置均通过 .env 读取，零硬编码密钥/URL。

.env 配置项说明：

    ENRICH_ENABLED=true                 # 是否启用企业补全
    ENRICH_CHANNEL=aiqicha              # 渠道：aiqicha / qcc / tianyancha
    ENRICH_MODE=async                   # async（异步批量）/ sync（同步单条）

    # 风控/限流
    ENRICH_INTERVAL_SECONDS=5           # 两次查询间隔（秒），默认 5 秒
    ENRICH_ACCOUNT_DAILY_LIMIT=200      # 单账号日查询上限（预留，当前无账号）
    ENRICH_GLOBAL_DAILY_LIMIT=500       # 全局日查询上限（预留）
    ENRICH_CONSECUTIVE_FAILURE_THRESHOLD=5  # 连续失败阈值

    # 缓存
    ENRICH_CACHE_ENABLED=true           # 启用缓存
    ENRICH_CACHE_TTL_SECONDS=604800     # 缓存 TTL，默认 7 天

    # 字段合并策略
    ENRICH_SKIP_IF_CONTACT_EXISTS=true  # 已有联系方式则跳过（不覆盖）
    ENRICH_FILL_EMPTY_ONLY=true         # 只填充空字段

    # 最低要求：命中多少个联系字段才视为成功
    ENRICH_MIN_CONTACT_FIELDS=1         # 至少 1 个：电话/邮箱/联系人

    # PII 脱敏（用于日志/展示，入库保持原文）
    ENRICH_MASK_IN_LOG=true             # 日志中自动脱敏手机号/邮箱
"""


logger = get_logger("data_clean.enterprise_enrich")


def _env_bool(name: str, default: bool = False) -> bool:
    v = os.environ.get(name)
    if v is None:
        return default
    return str(v).strip().lower() in ("1", "true", "yes", "y", "on")


def _env_int(name: str, default: int) -> int:
    v = os.environ.get(name)
    if v is None or v == "":
        return default
    try:
        return int(v)
    except ValueError:
        return default


def _env_str(name: str, default: str = "") -> str:
    v = os.environ.get(name)
    if v is None:
        return default
    return str(v).strip()


# ============================================================
# EnterpriseEnrichSettings — 单例，模块加载时一次性读取 .env
# ============================================================


class EnterpriseEnrichSettings:
    """T29 企业信息补全节点的运行时配置。"""

    def __init__(self) -> None:
        # 总开关
        self.enabled: bool = _env_bool("ENRICH_ENABLED", True)
        self.channel: str = _env_str("ENRICH_CHANNEL", "aiqicha")
        self.mode: str = _env_str("ENRICH_MODE", "async")

        # 风控/限流
        self.interval_seconds: float = float(_env_int("ENRICH_INTERVAL_SECONDS", 5))
        self.account_daily_limit: int = _env_int("ENRICH_ACCOUNT_DAILY_LIMIT", 200)
        self.global_daily_limit: int = _env_int("ENRICH_GLOBAL_DAILY_LIMIT", 500)
        self.consecutive_failure_threshold: int = _env_int(
            "ENRICH_CONSECUTIVE_FAILURE_THRESHOLD", 5
        )

        # 缓存
        self.cache_enabled: bool = _env_bool("ENRICH_CACHE_ENABLED", True)
        self.cache_ttl_seconds: int = _env_int("ENRICH_CACHE_TTL_SECONDS", 7 * 24 * 3600)

        # 字段合并策略
        self.skip_if_contact_exists: bool = _env_bool("ENRICH_SKIP_IF_CONTACT_EXISTS", True)
        self.fill_empty_only: bool = _env_bool("ENRICH_FILL_EMPTY_ONLY", True)
        self.min_contact_fields: int = _env_int("ENRICH_MIN_CONTACT_FIELDS", 1)

        # PII 处理
        self.mask_in_log: bool = _env_bool("ENRICH_MASK_IN_LOG", True)

        # 动态校验与日志
        self._validate_and_log()

    # ---------- 辅助 ----------

    def _validate_and_log(self) -> None:
        valid_channels = {"aiqicha", "qcc", "tianyancha"}
        if self.channel not in valid_channels:
            logger.warning(
                f"[T29] 未知 ENRICH_CHANNEL='{self.channel}'，回退到 aiqicha。"
                f" 有效值: {sorted(valid_channels)}"
            )
            self.channel = "aiqicha"
        if self.mode not in ("async", "sync"):
            logger.warning(f"[T29] 未知 ENRICH_MODE='{self.mode}'，回退到 async。")
            self.mode = "async"

        logger.info(
            f"[T29] EnterpriseEnrichSettings 初始化完成: "
            f"enabled={self.enabled}, channel={self.channel}, mode={self.mode}, "
            f"interval={self.interval_seconds}s, cache={'on' if self.cache_enabled else 'off'}"
        )

    def masked_repr(self) -> dict[str, Any]:
        """用于日志/调试的安全表示（不含敏感值）。"""
        return {
            "enabled": self.enabled,
            "channel": self.channel,
            "mode": self.mode,
            "interval_seconds": self.interval_seconds,
            "cache_enabled": self.cache_enabled,
            "cache_ttl_seconds": self.cache_ttl_seconds,
            "skip_if_contact_exists": self.skip_if_contact_exists,
            "fill_empty_only": self.fill_empty_only,
            "min_contact_fields": self.min_contact_fields,
        }

    def __repr__(self) -> str:
        return f"EnterpriseEnrichSettings({self.masked_repr()})"


# 模块级单例
enrich_settings: EnterpriseEnrichSettings | None = None
try:
    enrich_settings = EnterpriseEnrichSettings()
except Exception as exc:
    logger.warning(f"[T29] enrich_settings 初始化失败: {exc}，使用默认值。")
    enrich_settings = EnterpriseEnrichSettings()


__all__ = ["EnterpriseEnrichSettings", "enrich_settings"]
