from __future__ import annotations

import math
import threading
import time
import traceback
from datetime import datetime, timezone
from typing import Any, Dict, Iterable, List, Optional, Tuple, Type, TypeVar

from infra.exceptions import BizException, ErrorCode
from infra.logger_setup import get_logger

logger = get_logger("db.base")

_T = TypeVar("_T")


def _utc_now() -> datetime:
    """返回当前 UTC 时间（避免 datetime.utcnow 的弃用告警）。"""
    return datetime.now(timezone.utc).replace(tzinfo=None)


# ---------------- 数据库异常 ----------------

class DBUnreachableError(BizException):
    """数据库连接不可达。"""

    def __init__(self, message: str = "数据库连接不可达", *, data: Any = None) -> None:
        super().__init__(message, code=ErrorCode.DB_ERROR, http_status=503, data=data, trigger_alert=True)


class DBQueryError(BizException):
    """查询异常。"""

    def __init__(self, message: str = "数据库查询异常", *, data: Any = None) -> None:
        super().__init__(message, code=ErrorCode.DB_ERROR, http_status=500, data=data, trigger_alert=True)


# ---------------- ORM 基础类 ----------------

try:
    from sqlalchemy import and_, func, or_, String as _SaString
    from sqlalchemy import Index, Column, Table
    from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, Session as _SaSession
except Exception as _sa_err:  # pragma: no cover - 环境缺失时暴露清晰错误
    DeclarativeBase = object  # type: ignore[assignment,misc]

    def mapped_column(*args: Any, **kwargs: Any) -> Any:  # type: ignore[misc]
        raise RuntimeError(f"SQLAlchemy 未安装: {_sa_err}")

    Mapped = Any  # type: ignore[misc,assignment]


class Base(DeclarativeBase):  # type: ignore[valid-type,misc]
    """声明式基类。"""

    pass


class BaseModel:
    """所有业务表都继承它；统一公共字段与辅助方法。"""

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    tenant_id: Mapped[str] = mapped_column(default="default", index=True)
    is_archived: Mapped[bool] = mapped_column(default=False, index=True)
    created_at: Mapped[datetime] = mapped_column(default=_utc_now)
    updated_at: Mapped[datetime] = mapped_column(default=_utc_now, onupdate=_utc_now)

    def to_dict(self) -> Dict[str, Any]:
        """将 ORM 实例转成 dict（简单字段处理，敏感字段不解密）。"""
        data: Dict[str, Any] = {}
        for col in self.__table__.columns:  # type: ignore[attr-defined]
            name = col.name
            data[name] = getattr(self, name, None)
        return data

    @classmethod
    def for_tenant(cls, query, tenant_id: str):
        """强制带上租户过滤。"""
        return query.filter(cls.tenant_id == str(tenant_id))  # type: ignore[attr-defined]

    @classmethod
    def hot_only(cls, query):
        """仅查询未归档（热数据）。"""
        return query.filter(cls.is_archived == False)  # noqa: E712

    @classmethod
    def archived_only(cls, query):
        """仅查询归档（冷数据）。"""
        return query.filter(cls.is_archived == True)  # noqa: E712


# ---------------- PaginationResult ----------------

class PaginationResult:
    def __init__(self, items: List[Any], page: int, page_size: int, total: int) -> None:
        self.items = items
        self.page = page
        self.page_size = page_size
        self.total = total
        self.total_pages = max(1, math.ceil(total / page_size)) if page_size > 0 else 1

    def to_dict(self) -> Dict[str, Any]:
        return {
            "items": [
                it.to_dict() if hasattr(it, "to_dict") else it for it in self.items
            ],
            "page": self.page,
            "page_size": self.page_size,
            "total": self.total,
            "total_pages": self.total_pages,
        }


# ---------------- Database 单例 ----------------

class Database:
    """全局数据库单例（进程级）。

    - 提供 Engine / SessionFactory / scoped_session
    - 提供分页 / 批量插入 / upsert / 批量归档等工具方法
    - 所有方法在异常时自动告警，不吞异常
    """

    _instance: Optional["Database"] = None
    _lock = threading.Lock()

    def __init__(self, *, override_engine: Any = None, override_session_factory: Any = None) -> None:
        """单例初始化。测试时可注入 engine / session factory。"""
        self._initialized = False
        self._alert_debounce_ts: Dict[str, float] = {}
        self.engine = override_engine
        self._session_factory = override_session_factory
        self.Session = None
        if override_engine is not None and override_session_factory is None:
            from sqlalchemy.orm import sessionmaker as _sessionmaker
            self._session_factory = _sessionmaker(bind=override_engine, expire_on_commit=False)
        if self._session_factory is not None:
            from sqlalchemy.orm import scoped_session as _scoped
            self.Session = _scoped(self._session_factory)
            self._initialized = True

    # 懒加载真实连接
    def ensure_connected(self) -> None:
        if self._initialized and self.engine is not None:
            return
        with self._lock:
            if self._initialized:
                return
            from sqlalchemy import create_engine
            from sqlalchemy.orm import sessionmaker, scoped_session
            from configs.settings import settings as _settings

            url = (
                f"postgresql+psycopg2://{_settings.db.DB_USER}:{_settings.db.DB_PASSWORD}"
                f"@{_settings.db.DB_HOST}:{_settings.db.DB_PORT}/{_settings.db.DB_NAME}"
            )
            try:
                self.engine = create_engine(
                    url,
                    pool_size=int(_settings.db.DB_POOL_SIZE or 10),
                    max_overflow=int(_settings.db.DB_MAX_OVERFLOW or 20),
                    pool_pre_ping=True,
                    pool_recycle=1800,
                    echo=False,
                )
                self._session_factory = sessionmaker(bind=self.engine, expire_on_commit=False)
                self.Session = scoped_session(self._session_factory)
                self._initialized = True
                logger.info("db engine initialized")
            except Exception as exc:
                tb = traceback.format_exc()
                logger.error(f"db engine init failed: {exc}")
                self._alert_once("engine-init", f"数据库初始化失败: {exc}", extra={"traceback": tb[:2000]})
                raise DBUnreachableError(str(exc), data={"reason": "engine_init"})

    # -------- 基础会话 --------

    def session(self) -> Any:
        self.ensure_connected()
        return self.Session()

    # -------- schema 管理 --------

    def create_all(self) -> None:
        """创建所有继承自 Base 的表（仅开发/初始化用）。"""
        self.ensure_connected()
        try:
            Base.metadata.create_all(bind=self.engine)  # type: ignore[attr-defined]
        except Exception as exc:
            tb = traceback.format_exc()
            logger.error(f"db create_all failed: {exc}")
            self._alert_once("create-all", f"建表失败: {exc}", extra={"traceback": tb[:2000]})
            raise DBQueryError(str(exc), data={"op": "create_all"})

    def drop_all(self) -> None:
        """删除所有继承自 Base 的表（仅测试用）。"""
        self.ensure_connected()
        try:
            Base.metadata.drop_all(bind=self.engine)  # type: ignore[attr-defined]
        except Exception as exc:
            logger.error(f"db drop_all failed: {exc}")
            raise DBQueryError(str(exc), data={"op": "drop_all"})

    def dispose(self) -> None:
        try:
            if self.engine is not None:
                self.engine.dispose()
        except Exception:
            pass

    # -------- 通用工具 --------

    def paginate(
        self,
        query,
        /,
        *,
        page: int = 1,
        page_size: int = 20,
        session: Any = None,
    ) -> PaginationResult:
        """分页查询。"""
        page = max(1, int(page))
        page_size = max(1, min(500, int(page_size)))
        try:
            offset = (page - 1) * page_size
            total = self._count(query, session=session)
            items = query.offset(offset).limit(page_size).all()
            return PaginationResult(items=list(items), page=page, page_size=page_size, total=int(total))
        except Exception as exc:
            tb = traceback.format_exc()
            logger.error(f"db paginate failed: {exc}")
            self._alert_once("paginate", f"分页查询失败: {exc}", extra={"traceback": tb[:2000]})
            raise DBQueryError(str(exc), data={"op": "paginate"})

    def _count(self, query, *, session: Any = None) -> int:
        from sqlalchemy import func as _func
        try:
            return int(query.with_entities(_func.count()).scalar() or 0)
        except Exception:
            # 备用实现
            items = query.all()
            return len(list(items))

    def bulk_insert(
        self,
        model_cls: Type[Any],
        rows: Iterable[Dict[str, Any]],
        *,
        batch_size: int = 500,
        session: Any | None = None,
    ) -> int:
        """批量插入；返回总插入行数。"""
        rows = list(rows)
        total = 0
        if not rows:
            return 0
        own_session = False
        sess = session
        try:
            if sess is None:
                sess = self.session()
                own_session = True
            for start in range(0, len(rows), batch_size):
                batch = [model_cls(**row) for row in rows[start:start + batch_size]]
                sess.add_all(batch)
                sess.commit()
                total += len(batch)
            logger.info(f"bulk_insert {len(rows)} rows into {model_cls.__name__}")
            return total
        except Exception as exc:
            if own_session and sess is not None:
                sess.rollback()
            tb = traceback.format_exc()
            logger.error(f"bulk_insert failed: {exc}")
            self._alert_once("bulk-insert", f"批量插入失败: {exc}", extra={"traceback": tb[:2000]})
            raise DBQueryError(str(exc), data={"op": "bulk_insert", "model": model_cls.__name__})
        finally:
            if own_session and sess is not None:
                sess.close()

    def upsert(
        self,
        model_cls: Any,
        /,
        *,
        conflict_columns: List[str],
        rows: List[Dict[str, Any]],
        session: Any | None = None,
    ) -> List[Any]:
        """按 conflict_columns 做 insert-or-update；rows 为字段字典列表。
        仅更新 rows 中显式提供的字段，未提供字段保持原值。
        """
        if not rows:
            return []
        own_session = False
        sess = session
        try:
            if sess is None:
                sess = self.session()
                own_session = True
            results: List[Any] = []
            for payload in rows:
                q = sess.query(model_cls)
                for col in conflict_columns:
                    if col not in payload:
                        raise ValueError(f"upsert conflict_columns 必须在 rows 中提供: {col}")
                    q = q.filter(getattr(model_cls, col) == payload.get(col))
                existing = q.first()
                if existing is None:
                    inst = model_cls(**payload)
                    sess.add(inst)
                    sess.flush()
                    results.append(inst)
                else:
                    for k, v in payload.items():
                        if k in ("id",) or k in conflict_columns:
                            continue
                        setattr(existing, k, v)
                    results.append(existing)
            sess.commit()
            for inst in results:
                try:
                    sess.refresh(inst)
                except Exception:
                    pass
            return results
        except Exception as exc:
            if own_session and sess is not None:
                sess.rollback()
            tb = traceback.format_exc()
            logger.error(f"upsert failed: {exc}")
            self._alert_once("upsert", f"upsert 失败: {exc}", extra={"traceback": tb[:2000]})
            raise DBQueryError(str(exc), data={"op": "upsert", "model": model_cls.__name__})
        finally:
            if own_session and sess is not None:
                sess.close()

    def mark_archived(
        self,
        model_cls: Type[Any],
        /,
        *,
        where,
        session: Any | None = None,
        batch_size: int = 1000,
    ) -> int:
        """按条件批量将 is_archived 置为 True；返回更新行数。"""
        own_session = False
        sess = session
        total_updated = 0
        try:
            if sess is None:
                sess = self.session()
                own_session = True
            while True:
                from sqlalchemy import select as _sa_select, and_ as _sa_and

                subq = (
                    _sa_select(model_cls.id)
                    .where(where)
                    .where(model_cls.is_archived == False)  # noqa: E712
                    .limit(batch_size)
                )
                stmt = (
                    model_cls.__table__.update()  # type: ignore[attr-defined]
                    .where(model_cls.id.in_(subq))
                    .values(is_archived=True, updated_at=_utc_now())
                )
                result = sess.execute(stmt)
                sess.commit()
                affected = int(getattr(result, "rowcount", 0) or 0)
                total_updated += affected
                logger.info(f"mark_archived batch: {model_cls.__name__} +{affected}")
                if affected == 0 or affected < batch_size:
                    break
            logger.info(f"mark_archived done: {model_cls.__name__} total={total_updated}")
            return total_updated
        except Exception as exc:
            if own_session and sess is not None:
                sess.rollback()
            tb = traceback.format_exc()
            logger.error(f"mark_archived failed: {exc}")
            self._alert_once("mark_archived", f"归档标记失败: {exc}", extra={"traceback": tb[:2000]})
            raise DBQueryError(str(exc), data={"op": "mark_archived", "model": model_cls.__name__})
        finally:
            if own_session and sess is not None:
                sess.close()

    # ---------------- 告警去抖 ----------------
    def _alert_once(self, key: str, message: str, extra: Dict[str, Any] | None = None) -> None:
        now = time.time()
        if now - self._alert_debounce_ts.get(key, 0) < 300:
            return  # 5 分钟内同一 key 不重复告警
        self._alert_debounce_ts[key] = now
        try:
            # 使用模块级（或被测试 mock 注入）的引用，便于测试替换
            svc = globals().get("_alert_service")
            if svc is None:
                from infra.alerting import alert_service as _svc
                svc = _svc
            svc.service_exception_sync(message, extra_data=extra or {})
        except Exception as exc:
            logger.warning(f"alert_service unavailable: {exc}")


# 全局单例，业务直接 `from infra.db_base import database` 使用
database = Database()


__all__ = [
    "Base",
    "BaseModel",
    "Database",
    "database",
    "PaginationResult",
    "DBUnreachableError",
    "DBQueryError",
]
