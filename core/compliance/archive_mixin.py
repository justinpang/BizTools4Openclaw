from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any, List, Type

from infra.db_base import BaseModel
from infra.logger_setup import get_logger

logger = get_logger("compliance.archive")


def _utc_now() -> datetime:
    """返回当前 UTC 时间（避免 datetime.utcnow 的弃用告警）。"""
    return datetime.now(timezone.utc).replace(tzinfo=None)


# =============== Mixin ===============

class ArchiveMixin(BaseModel):
    """为业务模型提供 is_archived 过滤辅助方法。

    用法：
        class SomeModel(Base, BaseModel, ArchiveMixin):
            ...
    """

    @classmethod
    def hot_only(cls, query):
        """仅查询未归档（热数据）。"""
        return query.filter(cls.is_archived == False)  # noqa: E712

    @classmethod
    def archived_only(cls, query):
        """仅查询归档（冷数据）。"""
        return query.filter(cls.is_archived == True)  # noqa: E712


# =============== 判定 ===============

def should_archive_row(
    *,
    last_active_at: datetime | None,
    created_at: datetime | None = None,
    estimated_value: float | None = None,
    threshold_days: int | None = None,
    hot_value_threshold: float | None = None,
) -> bool:
    """判定规则：

    - 时间阈值：`last_active_at` 或 `created_at` 距今超过 `threshold_days` 天
    - 价值阈值：`estimated_value < hot_value_threshold`（或为空）
    - 两者同时成立才建议归档（保留高价值、近期活跃的记录）
    """
    from configs.settings import settings as _settings
    days = int(threshold_days if threshold_days is not None else (_settings.db.DB_ARCHIVE_DAYS or 90))
    hot = float(hot_value_threshold if hot_value_threshold is not None
                else (_settings.db.DB_ARCHIVE_HOT_THRESHOLD or 1000.0))
    ref = last_active_at or created_at
    if ref is None:
        return False
    now = _utc_now()
    if (now - ref).days < days:
        return False
    if estimated_value is not None and float(estimated_value) >= hot:
        return False
    return True


# =============== 执行 ===============

def _build_where_for_opportunity(model_cls: Any, *, days: int, hot: float):
    """business_opportunities 特殊：仅归档低价值且长时间未活跃的。"""
    from sqlalchemy import or_, and_
    cutoff = _utc_now() - timedelta(days=days)
    return and_(
        or_(model_cls.last_active_at.is_(None), model_cls.last_active_at < cutoff),
        or_(model_cls.estimated_value.is_(None), model_cls.estimated_value < hot),
    )


def _build_where_for_spider(model_cls: Any, *, days: int):
    cutoff = _utc_now() - timedelta(days=days)
    return model_cls.captured_at < cutoff


def _build_where_for_sales(model_cls: Any, *, days: int):
    from sqlalchemy import or_, and_
    cutoff = _utc_now() - timedelta(days=days)
    return and_(
        model_cls.status.in_(["done", "cancelled", "failed", "closed"]),
        or_(
            model_cls.completed_at.is_(None),
            model_cls.completed_at < cutoff,
        ),
    )


def _build_where_for_systemlog(model_cls: Any, *, days: int):
    cutoff = _utc_now() - timedelta(days=days)
    return model_cls.created_at < cutoff


def mark_rows_archived(
    session: Any,
    model_cls: Type[Any],
    *,
    batch_size: int = 1000,
    days: int | None = None,
    hot_value_threshold: float | None = None,
) -> int:
    """对给定表按规则批量打上 is_archived=True 标记。"""
    from configs.settings import settings as _settings
    from infra.db_base import database as _db

    effective_days = int(days if days is not None else (_settings.db.DB_ARCHIVE_DAYS or 90))
    effective_hot = float(hot_value_threshold if hot_value_threshold is not None
                          else (_settings.db.DB_ARCHIVE_HOT_THRESHOLD or 1000.0))

    table_name = getattr(model_cls, "__tablename__", "").lower()
    if "opportunit" in table_name:
        where = _build_where_for_opportunity(model_cls, days=effective_days, hot=effective_hot)
    elif "spider" in table_name or "raw" in table_name:
        where = _build_where_for_spider(model_cls, days=effective_days)
    elif "sale" in table_name or "task" in table_name:
        where = _build_where_for_sales(model_cls, days=effective_days)
    elif "system_log" in table_name or "log" in table_name:
        # system_logs 默认归档周期更长
        log_days = max(effective_days * 2, 180)
        where = _build_where_for_systemlog(model_cls, days=log_days)
    else:
        # 默认按 created_at 归档
        where = model_cls.created_at < (_utc_now() - timedelta(days=effective_days))

    return _db.mark_archived(model_cls, where=where, session=session, batch_size=batch_size)


# =============== 定时任务对接 ===============

def run_archive_once(*, session: Any | None = None) -> dict:
    """一次性对所有支持归档的表打上归档标记；返回各表受影响行数。"""
    from infra.db_models import SpiderRawData, BusinessOpportunity, SalesTask, SystemLog

    results: dict = {}
    for model in (SpiderRawData, BusinessOpportunity, SalesTask, SystemLog):
        try:
            n = mark_rows_archived(session=session, model_cls=model) if session else _external_mark(model)
            results[model.__tablename__] = n
        except Exception as exc:
            logger.warning(f"archive failed for {model.__tablename__}: {exc}")
            results[model.__tablename__] = f"error: {exc}"
    logger.info(f"archive done: {results}")
    return results


def _external_mark(model_cls: Type[Any]) -> int:
    from infra.db_base import database as _db
    sess = _db.session()
    try:
        return mark_rows_archived(session=sess, model_cls=model_cls)
    finally:
        sess.close()


def schedule_archive_job(
    scheduler: Any,
    *,
    job_id: str = "openclaw-archive-job",
    hour: int = 2,
    minute: int = 0,
) -> str:
    """向 APScheduler 注册每日凌晨冷数据归档任务。"""
    if scheduler is None:
        raise ValueError("scheduler 不能为空")

    def _job_wrapper():
        try:
            return run_archive_once()
        except Exception as exc:
            logger.error(f"archive job failed: {exc}")
            return {"error": str(exc)}

    # 优先使用 cron
    try:
        scheduler.add_job(
            _job_wrapper,
            "cron",
            id=job_id,
            hour=hour,
            minute=minute,
            replace_existing=True,
            misfire_grace_time=600,
            coalesce=True,
        )
        logger.info(f"archive cron scheduled: hour={hour} minute={minute}")
    except Exception as exc:
        # 退化到 interval（每 24h）
        logger.warning(f"archive: cron 添加失败，退回 interval 24h: {exc}")
        scheduler.add_job(
            _job_wrapper,
            "interval",
            hours=24,
            id=job_id,
            replace_existing=True,
            misfire_grace_time=600,
            coalesce=True,
        )
    return job_id


__all__ = [
    "ArchiveMixin",
    "should_archive_row",
    "mark_rows_archived",
    "run_archive_once",
    "schedule_archive_job",
]
