from __future__ import annotations

from datetime import datetime

from infra.logger_setup import get_logger
from infra.db_base import database
from infra.db_models import SpiderRawData
from configs.settings import settings

from business.data_clean.models import CleanTaskParams, RawRecord

logger = get_logger("data_clean.loader")


def _parse_cursor(cursor: str | None) -> tuple[int, datetime | None]:
    """解析 cursor 格式 "id:<id>|at:<ISO_DATETIME>"；None 则返回 (0, None).

    返回 (min_id, since_dt)：下次查询最小的 id，以及 since 参数（可为 None）。
    """
    if not cursor:
        return 0, None
    min_id = 0
    since_dt: datetime | None = None
    for part in cursor.split("|"):
        key, _, value = part.partition(":")
        if key == "id":
            try:
                min_id = int(value)
            except ValueError:
                pass
        elif key == "at":
            try:
                since_dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
            except Exception:
                pass
    return min_id, since_dt


def _make_cursor(last_record: RawRecord) -> str:
    """从 RawRecord 生成 cursor。"""
    at_iso = last_record.captured_at.isoformat() if last_record.captured_at else ""
    return f"id:{last_record.id}|at:{at_iso}"


def load_pending_records(params: CleanTaskParams) -> tuple[list[RawRecord], str | None]:
    """从 SpiderRawData 加载待处理数据。

    返回 (records, next_cursor) —— 当 records 为空或不足 batch 时 cursor=None。
    """
    batch_size = params.batch_size or int(settings.cleaning.CLEAN_BATCH_SIZE)
    min_id, since_from_cursor = _parse_cursor(params.cursor)

    # since 参数：优先级 params.since > cursor since
    since_dt: datetime | None = None
    if params.since:
        try:
            since_dt = datetime.strptime(params.since, "%Y-%m-%d")
        except ValueError:
            try:
                since_dt = datetime.fromisoformat(params.since.replace("Z", "+00:00"))
            except Exception:
                since_dt = None
    if since_dt is None and since_from_cursor is not None:
        since_dt = since_from_cursor

    # 使用 database.session() 构造查询
    try:
        with database.session() as sess:
            query = sess.query(SpiderRawData).filter(
                SpiderRawData.tenant_id == params.tenant_id,
                SpiderRawData.is_archived == False,  # noqa: E712
                SpiderRawData.id > min_id,
            )
            if params.spider_names:
                query = query.filter(SpiderRawData.spider_name.in_(params.spider_names))
            if since_dt is not None:
                query = query.filter(SpiderRawData.captured_at >= since_dt)
            query = query.order_by(SpiderRawData.id.asc()).limit(batch_size + 1)
            rows = query.all()
    except Exception as exc:
        logger.warning(f"load_pending_records 查询失败: {exc}")
        return [], None

    has_more = len(rows) > batch_size
    active_rows = list(rows[:batch_size]) if has_more else list(rows)

    records: list[RawRecord] = []
    for r in active_rows:
        # 兼容 raw_payload：可能是 dict 或 JSON 字符串
        payload = getattr(r, "raw_payload", None) or {}
        if isinstance(payload, str):
            try:
                import json

                payload = json.loads(payload)
            except Exception:
                payload = {}
        records.append(
            RawRecord(
                id=int(r.id),
                tenant_id=str(r.tenant_id),
                spider_name=str(r.spider_name),
                source_url=str(r.source_url),
                source_id=str(r.source_id or ""),
                raw_text=str(r.raw_text or ""),
                raw_payload=payload or {},
                captured_at=r.captured_at,
                source_country=str(r.source_country) if r.source_country else None,
                fetch_status=int(r.fetch_status or 0),
                fetch_error=str(r.fetch_error) if r.fetch_error else None,
            )
        )

    # 生成下一页 cursor
    next_cursor: str | None = None
    if has_more and records:
        next_cursor = _make_cursor(records[-1])
    elif records and len(records) == batch_size:
        # 即使我们无法确定是否有更多，只要正好满 batch 就生成 cursor
        next_cursor = _make_cursor(records[-1])

    logger.info(f"load_pending_records: 返回 {len(records)} 条, next_cursor={next_cursor}")
    return records, next_cursor


__all__ = ["load_pending_records"]
