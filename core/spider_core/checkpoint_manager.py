from __future__ import annotations

import json
import threading
import time
from typing import Any, Dict, List, Optional

from infra.logger_setup import get_logger

logger = get_logger("spider.checkpoint")


class CheckpointManager:
    """抓取进度 Redis 持久化 / 断点恢复。"""

    def __init__(
        self,
        *,
        prefix: str = "openclaw:checkpoint",
        ttl_seconds: int = 7 * 24 * 3600,
        redis_client: Any = None,
    ) -> None:
        self._prefix = prefix
        self._ttl = int(ttl_seconds)
        self._lock = threading.RLock()
        self._redis_client = redis_client  # 允许外部注入（用于测试）
        # 内存回退缓存（Redis 不可用时用）
        self._memory_store: Dict[str, Dict[str, Any]] = {}
        self._memory_visited: Dict[str, set] = {}
        self._memory_pending: Dict[str, List[str]] = {}

    # ---------------- Redis ----------------

    # Redis 客户端状态：
    #   None → 懒加载（从 infra.redis_client.get_redis() 获取）
    #   False → 显式禁用（纯内存模式；用于测试/离线环境）
    #   其他值 → 使用该 redis 客户端实例（如 fakeredis、redis.Redis）

    def _get_redis(self) -> Optional[Any]:
        """获取 Redis 实例；不可用或显式禁用时返回 None（回退内存模式）。"""
        if self._redis_client is False:
            return None
        if self._redis_client is not None:
            return self._redis_client
        try:
            from infra.redis_client import get_redis
            client = get_redis()
            if client is not None:
                self._redis_client = client
            return client
        except Exception as exc:
            logger.warning(f"checkpoint 无法连接 Redis: {exc}，回退内存模式")
            self._redis_client = False  # 失败后永久禁用，避免反复尝试
            return None

    def _redis_safe(self, method: str, *args, **kwargs) -> Any:
        """安全调用一个 Redis 方法，失败时记录日志但不抛异常。"""
        client = self._get_redis()
        if client is None:
            return None
        try:
            fn = getattr(client, method)
            return fn(*args, **kwargs)
        except Exception as exc:
            logger.warning(f"checkpoint Redis {method} 失败: {exc}，回退内存模式")
            return None

    # ---------------- Hash ----------------

    def save(
        self,
        task_id: str,
        *,
        current_url: str = "",
        processed_items: int = 0,
        failed_items: int = 0,
        status: str = "running",
        payload: Optional[Dict[str, Any]] = None,
    ) -> None:
        key = f"{self._prefix}:{task_id}"
        now = time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime())
        data = {
            "task_id": task_id,
            "current_url": current_url,
            "processed_items": str(int(processed_items)),
            "failed_items": str(int(failed_items)),
            "status": status,
            "payload_json": json.dumps(payload or {}, ensure_ascii=False),
            "updated_at": now,
        }
        with self._lock:
            if "created_at" not in (self._memory_store.get(task_id) or {}):
                self._memory_store.setdefault(task_id, {})["created_at"] = now
            self._memory_store[task_id].update(data)

        result = self._redis_safe("hset", key, mapping=data)
        if result is not None:
            self._redis_safe("expire", key, self._ttl)
            # 维护活跃任务索引
            self._redis_safe("sadd", f"{self._prefix}:index", task_id)

    def load(self, task_id: str) -> Optional[Dict[str, Any]]:
        key = f"{self._prefix}:{task_id}"
        # 先查 Redis
        raw: Optional[Dict[str, Any]] = None
        data = self._redis_safe("hgetall", key)
        if data:
            decoded: Dict[str, str] = {}
            for k, v in data.items():
                if isinstance(k, bytes):
                    k = k.decode("utf-8")
                if isinstance(v, bytes):
                    v = v.decode("utf-8")
                decoded[k] = v
            raw = decoded
        # 回退内存
        if raw is None:
            with self._lock:
                stored = self._memory_store.get(task_id)
                if stored:
                    raw = dict(stored)
        if raw is None:
            return None
        # 统一格式解析
        payload_raw = raw.pop("payload_json", "{}")
        try:
            payload = json.loads(payload_raw) if payload_raw else {}
        except Exception:
            payload = {}
        for num_key in ("processed_items", "failed_items"):
            if num_key in raw:
                try:
                    raw[num_key] = int(raw[num_key])
                except Exception:
                    raw[num_key] = 0
        raw["payload"] = payload
        return raw

    def mark_done(self, task_id: str) -> None:
        self.save(task_id, status="done")

    def mark_failed(self, task_id: str, error: str = "") -> None:
        data = {"error": error}
        self.save(task_id, status="failed", payload=data)

    # ---------------- Set (visited) ----------------

    def mark_visited(self, task_id: str, *ids: str) -> int:
        if not ids:
            return 0
        key = f"{self._prefix}:visited:{task_id}"
        # 内存同步
        with self._lock:
            s = self._memory_visited.setdefault(task_id, set())
            before = len(s)
            s.update(ids)
            in_memory = len(s) - before

        redis_count = 0
        result = self._redis_safe("sadd", key, *ids)
        if result is not None:
            redis_count = int(result)
            self._redis_safe("expire", key, self._ttl)
        # 取两者中更可信的（redis 优先）
        return redis_count if result is not None else in_memory

    def is_visited(self, task_id: str, id: str) -> bool:
        key = f"{self._prefix}:visited:{task_id}"
        result = self._redis_safe("sismember", key, id)
        if result is not None:
            return bool(result)
        with self._lock:
            return id in self._memory_visited.setdefault(task_id, set())

    def visited_count(self, task_id: str) -> int:
        key = f"{self._prefix}:visited:{task_id}"
        result = self._redis_safe("scard", key)
        if result is not None:
            return int(result)
        with self._lock:
            return len(self._memory_visited.get(task_id, set()))

    # ---------------- List (pending) ----------------

    def pending_push(self, task_id: str, *ids: str) -> int:
        if not ids:
            return 0
        key = f"{self._prefix}:pending:{task_id}"
        with self._lock:
            lst = self._memory_pending.setdefault(task_id, [])
            lst.extend(ids)
            in_memory = len(ids)

        result = self._redis_safe("rpush", key, *ids)
        if result is not None:
            self._redis_safe("expire", key, self._ttl)
            return int(result) - (int(self._redis_safe("llen", key)) - in_memory)  # 近似
        return in_memory

    def pending_pop(self, task_id: str, *, count: int = 1) -> List[str]:
        key = f"{self._prefix}:pending:{task_id}"
        # redis: lpop 多个
        result = None
        try:
            client = self._get_redis()
            if client is not None:
                # 兼容性：redis-py 3.x/4.x lpop(count) 可能不同
                if count == 1:
                    val = client.lpop(key)
                    if isinstance(val, bytes):
                        val = val.decode("utf-8")
                    result = [val] if val else []
                else:
                    # lpop 多值
                    try:
                        vals = client.lpop(key, count)
                        result = [v.decode("utf-8") if isinstance(v, bytes) else v for v in (vals or [])]
                    except Exception:
                        # 回退多次 lpop
                        vals = []
                        for _ in range(count):
                            v = client.lpop(key)
                            if not v:
                                break
                            if isinstance(v, bytes):
                                v = v.decode("utf-8")
                            vals.append(v)
                        result = vals
        except Exception:
            result = None

        if result is not None:
            # 同步内存
            with self._lock:
                lst = self._memory_pending.get(task_id, [])
                for _ in result:
                    if lst:
                        lst.pop(0)
            return result
        # 回退内存
        with self._lock:
            lst = self._memory_pending.setdefault(task_id, [])
            popped = lst[:count]
            self._memory_pending[task_id] = lst[count:]
            return popped

    def pending_count(self, task_id: str) -> int:
        key = f"{self._prefix}:pending:{task_id}"
        result = self._redis_safe("llen", key)
        if result is not None:
            return int(result)
        with self._lock:
            return len(self._memory_pending.get(task_id, []))

    # ---------------- 清理 / 查询 ----------------

    def delete(self, task_id: str) -> None:
        with self._lock:
            self._memory_store.pop(task_id, None)
            self._memory_visited.pop(task_id, None)
            self._memory_pending.pop(task_id, None)
        keys = [
            f"{self._prefix}:{task_id}",
            f"{self._prefix}:visited:{task_id}",
            f"{self._prefix}:pending:{task_id}",
        ]
        for key in keys:
            self._redis_safe("delete", key)
        self._redis_safe("srem", f"{self._prefix}:index", task_id)

    def list_active(self, *, count: int = 100) -> List[str]:
        key = f"{self._prefix}:index"
        result = self._redis_safe("smembers", key)
        if result:
            items = []
            for v in result:
                if isinstance(v, bytes):
                    v = v.decode("utf-8")
                items.append(v)
            return items[:count]
        with self._lock:
            return list(self._memory_store.keys())[:count]


__all__ = ["CheckpointManager"]
