"""core/spider_core/dedup_store — 增量去重存储。

策略：
  - 如果可连接 Redis（默认 redis://localhost:6379），则用 Redis SET + EXPIRE
  - 否则降级为线程安全的 Python dict 内存存储

使用方式：
    store = DedupStore()
    if not store.check_and_mark(task_id="news", key="https://example.com/article/123"):
        # 新内容，处理...
"""

from __future__ import annotations

import hashlib
import threading
import time
from typing import Dict, Optional, Set

from infra.logger_setup import get_logger
from core.spider_core.config import enhanced_config

logger = get_logger("spider.dedup")


class DedupStore:
    """增量去重存储（Redis 优先，否则内存）。"""

    def __init__(self, *, ttl_days: Optional[int] = None) -> None:
        cfg = enhanced_config()
        self._ttl_seconds = int((ttl_days or cfg.dedup_ttl_days or 7) * 24 * 3600)
        self._lock = threading.Lock()
        self._memory: Dict[str, Set[str]] = {}
        self._redis = None

        # 尝试 Redis（复用现有 infra.redis_client）
        try:
            from infra.redis_client import get_redis
            r = get_redis()
            # 做一次真实的 smoke test（尝试 sadd + sismember）
            _test_key = "__dedup_test__"
            _test_val = "test"
            try:
                added = r.sadd(_test_key, _test_val)
                if added is not None and int(added) >= 0:
                    # 清理
                    try:
                        r.delete(_test_key)
                    except Exception:
                        pass
                    self._redis = r
                    logger.info("DedupStore: 使用 Redis 存储")
                    return
            except Exception:
                pass
        except Exception:
            pass
        logger.info("DedupStore: 使用内存存储（Redis 不可用）")

    # ---------- 内部 key 构造 ----------

    def _redis_key(self, task_id: str) -> str:
        return f"spider:dedup:{task_id}"

    def _hash_key(self, key: str) -> str:
        if not key:
            return ""
        if len(key) <= 64 and all(c.isalnum() or c in "-_:/." for c in key):
            return key
        return hashlib.sha256(key.encode("utf-8")).hexdigest()

    # ---------- public ----------

    def check(self, task_id: str, key: str) -> bool:
        """True = 已存在（重复）。"""
        if not key:
            return False
        h = self._hash_key(key)
        rk = self._redis_key(task_id)
        if self._redis is not None:
            try:
                return bool(self._redis.sismember(rk, h))
            except Exception as exc:
                logger.warning(f"DedupStore redis sismember 失败: {exc}")
        with self._lock:
            return h in self._memory.setdefault(task_id, set())

    def mark(self, task_id: str, key: str) -> None:
        if not key:
            return
        h = self._hash_key(key)
        rk = self._redis_key(task_id)
        if self._redis is not None:
            try:
                self._redis.sadd(rk, h)
                self._redis.expire(rk, self._ttl_seconds)
                return
            except Exception as exc:
                logger.warning(f"DedupStore redis sadd 失败: {exc}")
        with self._lock:
            self._memory.setdefault(task_id, set()).add(h)

    def check_and_mark(self, task_id: str, key: str) -> bool:
        """原子性 check + mark。返回 True 表示已存在（重复）。"""
        if not key:
            return False
        h = self._hash_key(key)
        rk = self._redis_key(task_id)
        if self._redis is not None:
            try:
                added = self._redis.sadd(rk, h)
                self._redis.expire(rk, self._ttl_seconds)
                return int(added) == 0  # 0 表示已存在
            except Exception as exc:
                logger.warning(f"DedupStore redis check_and_mark 失败: {exc}")
        with self._lock:
            s = self._memory.setdefault(task_id, set())
            existed = h in s
            s.add(h)
            return existed

    def clear(self, task_id: str) -> int:
        rk = self._redis_key(task_id)
        count = 0
        if self._redis is not None:
            try:
                count = int(self._redis.scard(rk) or 0)
                self._redis.delete(rk)
                return count
            except Exception as exc:
                logger.warning(f"DedupStore redis clear 失败: {exc}")
        with self._lock:
            if task_id in self._memory:
                count = len(self._memory[task_id])
                del self._memory[task_id]
        return count

    def count(self, task_id: str) -> int:
        rk = self._redis_key(task_id)
        if self._redis is not None:
            try:
                return int(self._redis.scard(rk) or 0)
            except Exception:
                pass
        with self._lock:
            return len(self._memory.get(task_id, set()))


# 便捷函数
_default_store: Optional[DedupStore] = None


def get_dedup_store() -> DedupStore:
    global _default_store
    if _default_store is None:
        _default_store = DedupStore()
    return _default_store


__all__ = ["DedupStore", "get_dedup_store"]
