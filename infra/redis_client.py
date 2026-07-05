from __future__ import annotations

import threading
import time
from typing import Any, Optional

try:
    from redis import Redis as _RedisClient
    from redis.connection import ConnectionPool
    from redis.exceptions import ConnectionError as RedisConnError
    from redis.exceptions import TimeoutError as RedisTimeoutError
except Exception:  # pragma: no cover - 延迟报错，让导入不直接崩
    _RedisClient = None  # type: ignore
    ConnectionPool = None  # type: ignore
    RedisConnError = Exception  # type: ignore
    RedisTimeoutError = Exception  # type: ignore

from infra.logger_setup import get_logger

logger = get_logger("redis_client")


# =============== Redis 不可用时的内存回退 stub ===============
class InMemoryRedisStub:
    """当 Redis 不可用时的进程内内存替代方案。

    只实现了项目中实际用到的 Redis API 子集：
        - get(key)
        - set(key, value, ex=None)
        - delete(*keys)
        - ping()
        - exists(key)
        - incr(key)
        - hset(name, key, value)
        - hget(name, key)
        - lpush(name, *values)
        - rpop(name)
        - brpop(name, timeout=0)

    注意：
        - 这是一个简易 stub，不保证进程间共享/持久化
        - ex 过期时间用守护线程惰性清理（近似实现）
        - 仅用于"一键跑起来"的测试部署场景
    """

    def __init__(self) -> None:
        self._data: dict[str, Any] = {}
        self._expire_at: dict[str, float] = {}
        self._lock = threading.Lock()
        self._started_cleanup = False

    # ------ internal ------
    def _is_expired(self, key: str, now: float) -> bool:
        exp = self._expire_at.get(key)
        return exp is not None and exp <= now

    def _gc_if_needed(self) -> None:
        # 只在首次调用时启动一个轻量守护线程做过期清理
        if self._started_cleanup:
            return
        with self._lock:
            if self._started_cleanup:
                return
            self._started_cleanup = True

        def _loop() -> None:
            while True:
                time.sleep(5.0)
                try:
                    now = time.time()
                    with self._lock:
                        expired_keys = [
                            k for k, t in list(self._expire_at.items()) if t <= now
                        ]
                        for k in expired_keys:
                            self._data.pop(k, None)
                            self._expire_at.pop(k, None)
                except Exception:
                    pass

        t = threading.Thread(target=_loop, daemon=True, name="redis-stub-gc")
        t.start()

    # ------ public API ------
    def ping(self) -> bool:
        return True

    def get(self, key: str) -> Optional[bytes]:
        now = time.time()
        with self._lock:
            if self._is_expired(key, now):
                self._data.pop(key, None)
                self._expire_at.pop(key, None)
                return None
            value = self._data.get(key)
        if value is None:
            return None
        # 始终返回 bytes（与真实 redis-py 一致）
        if isinstance(value, bytes):
            return value
        return str(value).encode("utf-8")

    def set(self, key: str, value: Any, ex: Optional[int] = None, *args, **kwargs) -> Any:  # noqa: D417
        with self._lock:
            self._data[key] = value if isinstance(value, bytes) else str(value).encode("utf-8")
            if ex is not None:
                self._expire_at[key] = time.time() + float(ex)
            else:
                self._expire_at.pop(key, None)
        self._gc_if_needed()
        return True

    def delete(self, *keys: str) -> int:
        count = 0
        with self._lock:
            for k in keys:
                if k in self._data:
                    self._data.pop(k, None)
                    self._expire_at.pop(k, None)
                    count += 1
        return count

    def exists(self, key: str) -> int:
        with self._lock:
            if self._is_expired(key, time.time()):
                self._data.pop(key, None)
                self._expire_at.pop(key, None)
                return 0
            return 1 if key in self._data else 0

    def incr(self, key: str) -> int:
        with self._lock:
            cur = self._data.get(key)
            n = int(cur or 0) + 1
            self._data[key] = str(n).encode("utf-8")
            return n

    def hset(self, name: str, mapping: Any = None, *args, **kwargs) -> int:
        with self._lock:
            bucket = self._data.setdefault(name, {})
            added = 0
            if isinstance(mapping, dict):
                for k, v in mapping.items():
                    bucket[k] = v
                    added += 1
            return added

    def hget(self, name: str, key: str) -> Optional[bytes]:
        with self._lock:
            bucket = self._data.get(name)
            if not isinstance(bucket, dict):
                return None
            v = bucket.get(key)
        if v is None:
            return None
        return v if isinstance(v, bytes) else str(v).encode("utf-8")

    def lpush(self, name: str, *values: Any) -> int:
        with self._lock:
            lst = self._data.setdefault(name, [])
            if not isinstance(lst, list):
                lst = []
                self._data[name] = lst
            for v in values:
                b = v if isinstance(v, bytes) else str(v).encode("utf-8")
                lst.insert(0, b)
            return len(lst)

    def rpop(self, name: str) -> Optional[bytes]:
        with self._lock:
            lst = self._data.get(name)
            if not isinstance(lst, list) or not lst:
                return None
            return lst.pop()

    def brpop(self, name: str, timeout: float = 0.0) -> Optional[tuple[bytes, bytes]]:
        """简化版 brpop；timeout <= 0 时退化为轮询，直到有元素或超时。"""
        deadline = time.time() + (float(timeout) if timeout and timeout > 0 else 1.0)
        while time.time() < deadline:
            with self._lock:
                lst = self._data.get(name)
                if isinstance(lst, list) and lst:
                    return (name.encode("utf-8") if isinstance(name, str) else name, lst.pop())
            time.sleep(0.1)
        return None

    # ------ 兼容用 ------
    def __getattr__(self, item):  # pragma: no cover
        # 任何未实现的方法返回可调用 stub，避免上游崩
        def _noop(*args, **kwargs):
            return None
        return _noop

    def close(self) -> None:
        with self._lock:
            self._data.clear()
            self._expire_at.clear()


class RedisClient:
    """Redis 连接池单例。

    行为：
      - 默认仍走真实 Redis（按 QUEUE_REDIS_HOST 等配置）
      - 连接失败时会自动退化为进程内 InMemoryRedisStub（仅限测试/部署场景）
      - 提供 acquire/ping/close 基础 API
    """

    _instance: "RedisClient | None" = None
    _instance_lock = threading.Lock()

    def __new__(cls, *args: Any, **kwargs: Any) -> "RedisClient":
        if cls._instance is None:
            with cls._instance_lock:
                if cls._instance is None:
                    cls._instance = super().__new__(cls)
                    cls._instance._initialized = False
        return cls._instance

    def __init__(self, *, override_pool: Any = None, override_client: Any = None) -> None:
        # 单例只初始化一次
        if getattr(self, "_initialized", False):
            # 但允许测试注入 mock
            if override_pool is not None:
                self._pool = override_pool
                self._client = None
            if override_client is not None:
                self._client = override_client
            return
        self._initialized = True
        self._lock = threading.Lock()
        self._pool: Any = None
        self._client: Any = None
        self._fallback: bool = False  # 是否已经降级到内存 stub

    # ---------- private ----------

    def _ensure_connected(self) -> None:
        # 若已经退化为 stub，直接返回（懒加载后不重建）
        if self._fallback and self._client is not None:
            return

        if self._client is not None and not self._fallback:
            try:
                self._client.ping()
                return
            except Exception:
                logger.warning("redis ping failed, reconnecting")
                self._client = None
        with self._lock:
            if self._fallback and self._client is not None:
                return
            if self._client is not None and not self._fallback:
                try:
                    self._client.ping()
                    return
                except Exception:
                    self._client = None
            try:
                self._connect_with_backoff()
            except Exception as exc:
                logger.warning(f"redis 不可达，回退到进程内内存 stub: {exc}")
                self._client = InMemoryRedisStub()
                self._fallback = True

    def _connect_with_backoff(self) -> None:
        from configs.settings import settings

        if _RedisClient is None or ConnectionPool is None:
            # 没装 redis 包，直接抛给外层 → 会走 stub
            raise RuntimeError("redis 依赖未安装")

        host = settings.queue.QUEUE_REDIS_HOST
        port = int(settings.queue.QUEUE_REDIS_PORT)
        password = settings.queue.QUEUE_REDIS_PASSWORD or None
        db = int(settings.queue.QUEUE_REDIS_DB)
        max_conn = int(settings.queue.QUEUE_POOL_SIZE or 10)
        socket_timeout = float(settings.queue.QUEUE_POOL_TIMEOUT or 5.0)

        total_wait = 0.0
        attempt = 0
        backoff = 0.2
        # 最多尝试 5 秒（避免启动时长时间挂起）
        deadline = min(float(settings.queue.QUEUE_POOL_TIMEOUT or 5.0), 5.0)
        last_error: Exception | None = None
        while total_wait < deadline:
            try:
                self._pool = ConnectionPool(
                    host=host,
                    port=port,
                    password=password,
                    db=db,
                    max_connections=max_conn,
                    socket_timeout=socket_timeout,
                    socket_connect_timeout=socket_timeout,
                )
                self._client = _RedisClient(connection_pool=self._pool)
                self._client.ping()
                logger.info(f"redis connected: {host}:{port}/{db}")
                return
            except (RedisConnError, RedisTimeoutError, Exception) as exc:
                last_error = exc
                attempt += 1
                sleep_for = min(backoff * (2 ** (attempt - 1)), 1.0)
                logger.warning(
                    f"redis connect attempt {attempt} failed: {exc}, sleep {sleep_for:.2f}s"
                )
                time.sleep(sleep_for)
                total_wait += sleep_for
                try:
                    if self._pool is not None:
                        self._pool.disconnect()
                except Exception:
                    pass
                self._pool = None
                self._client = None
        raise RuntimeError(f"redis connect failed after {attempt} attempts: {last_error}")

    # ---------- public ----------

    def acquire(self) -> Any:
        """获取一个可用的 Redis 句柄（或内存 stub）。"""
        self._ensure_connected()
        return self._client

    def ping(self, *, fail_silently: bool = True) -> bool:
        try:
            client = self.acquire()
            return bool(client.ping())
        except Exception as exc:
            logger.warning(f"redis ping error: {exc}")
            if fail_silently:
                return False
            raise

    def close(self) -> None:
        try:
            if self._pool is not None:
                self._pool.disconnect()
        except Exception as exc:
            logger.warning(f"redis disconnect error: {exc}")
        self._client = None
        self._pool = None
        self._fallback = False


# 模块级单例，业务直接 `from infra.redis_client import redis_client, get_redis` 使用
redis_client = RedisClient()


def get_redis() -> Any:
    """获取一个可立即使用的 Redis 句柄（或内存 stub）。"""
    return redis_client.acquire()


__all__ = ["RedisClient", "redis_client", "get_redis", "InMemoryRedisStub"]
