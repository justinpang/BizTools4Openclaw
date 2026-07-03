from __future__ import annotations

import os
import random
import threading
import time
from dataclasses import dataclass, field
from typing import Any

from infra.logger_setup import get_logger

logger = get_logger("send_core.account_pool")


# ============================================================
# 数据类
# ============================================================


@dataclass
class Account:
    """单一渠道账号。"""

    channel: str  # wechat / feishu / email
    account_id: str
    token: str
    daily_quota: int
    weight: float = 1.0
    enabled: bool = True

    # 运行态（由 ban_detector / pipeline 写入；不从 .env 解析）
    banned: bool = False
    banned_reason: str | None = None
    banned_ts: float | None = None
    cooldown_until: float = 0.0
    last_used_ts: float = 0.0

    def is_available(self, now: float | None = None) -> bool:
        n = now if now is not None else time.time()
        return self.enabled and not self.banned and n >= self.cooldown_until

    def mark_banned(self, reason: str, cooldown_seconds: float = 3600.0) -> None:
        self.banned = True
        self.banned_reason = reason
        self.banned_ts = time.time()
        self.cooldown_until = time.time() + cooldown_seconds

    def unban(self) -> None:
        self.banned = False
        self.banned_reason = None
        self.banned_ts = None
        self.cooldown_until = 0.0


# ============================================================
# 辅助：解析 .env 配置
# ============================================================


def _parse_accounts_env(channel: str, env_key: str, default_quota: int) -> list[Account]:
    """解析形如 'id:token:quota,id2:token2:quota2' 的字符串。"""
    raw = os.environ.get(env_key)
    if not raw:
        return []
    accounts: list[Account] = []
    for part in raw.split(","):
        part = part.strip()
        if not part:
            continue
        tokens = part.split(":")
        if len(tokens) < 2:
            logger.warning(f"账号格式错误（{env_key}）：{part}")
            continue
        acc_id = tokens[0].strip()
        token = ":".join(tokens[1:-1]) if len(tokens) > 2 else tokens[1]
        if len(tokens) >= 3 and tokens[-1].isdigit():
            quota = int(tokens[-1])
            token = ":".join(tokens[1:-1])
        else:
            quota = default_quota
            token = ":".join(tokens[1:])
        if not acc_id:
            continue
        weight = float(quota) / max(default_quota, 1)
        accounts.append(Account(channel=channel, account_id=acc_id, token=token, daily_quota=quota, weight=weight))
    return accounts


# ============================================================
# AccountPool 主类
# ============================================================


class AccountPool:
    """渠道账号池 + 负载均衡。"""

    def __init__(
        self,
        *,
        lb_strategy: str | None = None,
        default_quota: int | None = None,
        seed: int = 42,
    ) -> None:
        self._lock = threading.RLock()
        self._rng = random.Random(seed)

        self._strategy = (lb_strategy or os.environ.get("SEND_LB_STRATEGY", "round_robin")).lower()
        if self._strategy not in ("round_robin", "weighted_random", "least_loaded"):
            logger.warning(f"未知 LB 策略 {self._strategy}，回退 round_robin")
            self._strategy = "round_robin"

        self._default_quota = default_quota if default_quota is not None else int(
            os.environ.get("SEND_ACCOUNT_DAILY_LIMIT_DEFAULT", "100")
        )

        self._channels: dict[str, list[Account]] = {}
        self._cursor: dict[str, int] = {}
        self._load_from_env()

    def _load_from_env(self) -> None:
        raw_channels = os.environ.get("SEND_CHANNELS", "wechat,feishu,email")
        for ch in [c.strip().lower() for c in raw_channels.split(",") if c.strip()]:
            self._channels[ch] = []
            key_map = {
                "wechat": "SEND_WECHAT_ACCOUNTS",
                "feishu": "SEND_FEISHU_ACCOUNTS",
                "email": "SEND_EMAIL_ACCOUNTS",
            }
            env_key = key_map.get(ch, f"SEND_{ch.upper()}_ACCOUNTS")
            accs = _parse_accounts_env(ch, env_key, self._default_quota)
            self._channels[ch] = accs
            logger.info(f"渠道 {ch} 加载了 {len(accs)} 个账号")
        # 若没有任何账号配置，创建占位账号（便于单测与默认启动）
        if not any(self._channels.values()):
            logger.warning("未配置 SEND_*_ACCOUNTS，使用空账号池；调用方需通过 register_account() 注入")

    # ---------------- 动态注册 ----------------

    def register_account(self, account: Account) -> None:
        with self._lock:
            self._channels.setdefault(account.channel, []).append(account)

    # ---------------- 查询 ----------------

    def channels(self) -> list[str]:
        return list(self._channels.keys())

    def all_accounts(self, channel: str) -> list[Account]:
        return list(self._channels.get(channel, []))

    # ---------------- 核心：选择账号 ----------------

    def pick(self, channel: str) -> Account | None:
        channel_l = channel.lower()
        with self._lock:
            pool = self._channels.get(channel_l, [])
            if not pool:
                return None
            available = [a for a in pool if a.is_available()]
            if not available:
                return None
            idx = self._next_index(channel_l, available)
            picked = available[idx]
            picked.last_used_ts = time.time()
            return picked

    def pick_with_fallback(self, preferred_channel: str) -> Account:
        """优先从 preferred_channel 取，否则轮询其它渠道；全部不可用时抛异常。"""
        acc = self.pick(preferred_channel)
        if acc is not None:
            return acc
        for ch in self._channels.keys():
            if ch == preferred_channel:
                continue
            acc = self.pick(ch)
            if acc is not None:
                return acc
        raise RuntimeError(f"send_core: 无可用账号 (preferred={preferred_channel})")

    # ---------------- 内部：各策略实现 ----------------

    def _next_index(self, channel: str, available: list[Account]) -> int:
        # 每种策略都维护自己的"cursor"，避免对第一个账号过度倾斜
        if self._strategy == "round_robin":
            self._cursor.setdefault(channel, 0)
            idx = self._cursor[channel] % len(available)
            self._cursor[channel] = (idx + 1) % len(available)
            return idx
        if self._strategy == "weighted_random":
            weights = [max(a.weight, 0.01) for a in available]
            total = sum(weights)
            r = self._rng.uniform(0, total)
            acc = 0.0
            for i, w in enumerate(weights):
                acc += w
                if r <= acc:
                    return i
            return len(available) - 1
        if self._strategy == "least_loaded":
            # 简单策略：选 last_used_ts 最早的账号
            best_i = 0
            best_ts = self._cursor.get(channel, 0.0)
            for i, a in enumerate(available):
                ts = self._cursor.get(f"{channel}:{a.account_id}", 0.0)
                if ts < best_ts or (ts == best_ts and i == 0):
                    best_i = i
                    best_ts = ts
            # 更新所选账号的"最近使用"
            self._cursor[f"{channel}:{available[best_i].account_id}"] = time.time()
            return best_i
        # 兜底
        return 0

    # ---------------- 封禁/冷却 ----------------

    def mark_banned(self, channel: str, account_id: str, reason: str, cooldown_seconds: float | None = None) -> bool:
        if cooldown_seconds is None:
            cooldown_seconds = float(os.environ.get("SEND_BAN_COOLDOWN_SECONDS", "3600"))
        with self._lock:
            for a in self._channels.get(channel, []):
                if a.account_id == account_id:
                    a.mark_banned(reason, cooldown_seconds)
                    logger.warning(f"账号 {channel}/{account_id} 已标记封禁：{reason}")
                    return True
        return False

    def unban(self, channel: str, account_id: str) -> bool:
        with self._lock:
            for a in self._channels.get(channel, []):
                if a.account_id == account_id:
                    a.unban()
                    logger.info(f"账号 {channel}/{account_id} 已解除封禁")
                    return True
        return False

    def cleanup_expired_bans(self) -> int:
        """由外部定时器调用，自动清理已过冷却期的封禁。"""
        n = 0
        now = time.time()
        with self._lock:
            for ch, pool in self._channels.items():
                for a in pool:
                    if a.banned and a.cooldown_until and now >= a.cooldown_until:
                        a.unban()
                        n += 1
        if n:
            logger.info(f"清理冷却期账号 {n} 个")
        return n

    def available_count(self, channel: str) -> int:
        with self._lock:
            return sum(1 for a in self._channels.get(channel, []) if a.is_available())


# ============================================================
# 模块级单例
# ============================================================


def _build_default() -> AccountPool:
    return AccountPool()


account_pool: AccountPool
try:
    account_pool = _build_default()
except Exception as exc:
    logger.warning(f"AccountPool 默认实例初始化失败：{exc}")
    account_pool = AccountPool()


__all__ = ["Account", "AccountPool", "account_pool"]
