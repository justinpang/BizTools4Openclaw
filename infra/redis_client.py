from __future__ import annotations

import threading
import time
from typing import Any

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


class RedisClient:
    """Redis 连接池单例。

    - 惰性初始化连接池
    - 自动重连（指数退避，最多 QUEUE_POOL_TIMEOUT 秒）
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

    # ---------- private ----------

    def _ensure_connected(self) -> None:
        if self._client is not None:
            try:
                self._client.ping()
                return
            except Exception:
                logger.warning("redis ping failed, reconnecting")
                self._client = None
        with self._lock:
            if self._client is not None:
                try:
                    self._client.ping()
                    return
                except Exception:
                    self._client = None
            self._connect_with_backoff()

    def _connect_with_backoff(self) -> None:
        from configs.settings import settings
        from infra.task_exceptions import RedisUnreachableError

        if _RedisClient is None or ConnectionPool is None:
            raise RedisUnreachableError("redis 依赖未安装，请 pip install redis")

        host = settings.queue.QUEUE_REDIS_HOST
        port = int(settings.queue.QUEUE_REDIS_PORT)
        password = settings.queue.QUEUE_REDIS_PASSWORD or None
        db = int(settings.queue.QUEUE_REDIS_DB)
        max_conn = int(settings.queue.QUEUE_POOL_SIZE or 10)
        socket_timeout = float(settings.queue.QUEUE_POOL_TIMEOUT or 30.0)

        total_wait = 0.0
        attempt = 0
        backoff = 0.2
        deadline = float(settings.queue.QUEUE_POOL_TIMEOUT or 30.0)
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
            except (RedisConnError, RedisTimeoutError) as exc:
                last_error = exc
                attempt += 1
                sleep_for = min(backoff * (2 ** (attempt - 1)), 2.0)
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
        raise RedisUnreachableError(
            f"redis connect failed after {attempt} attempts: {last_error}"
        )

    # ---------- public ----------

    def acquire(self) -> Any:
        """获取一个可用的 Redis 句柄（同一连接池上的轻量对象）。"""
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


# 模块级单例，业务直接 `from infra.redis_client import redis_client, get_redis` 使用
redis_client = RedisClient()


def get_redis() -> Any:
    """获取一个可立即使用的 Redis 句柄。"""
    return redis_client.acquire()


__all__ = ["RedisClient", "redis_client", "get_redis"]
