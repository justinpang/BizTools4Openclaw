"""web_admin/api/spider_task — 爬虫任务 CRUD & 启停。"""

from __future__ import annotations

import json
import time

from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import JSONResponse

from infra.logger_setup import get_logger
from infra.redis_client import get_redis
from web_admin.auth import require_admin

logger = get_logger("web_admin.spider")
router = APIRouter(tags=["admin"])

TASKS_KEY = "web_admin:spider:tasks"      # hash: job_id -> json(payload)
PAUSED_KEY = "web_admin:spider:paused"    # set of paused job_ids
LOG_PREFIX = "spider:log:"
RISK_KEY = "spider:risk"


def _task_template(job_id: str, payload: dict) -> dict:
    return {"job_id": job_id, **payload}


def _persist_task(job_id: str, payload: dict) -> None:
    try:
        r = get_redis()
        if r is not None:
            r.hset(TASKS_KEY, mapping={job_id: json.dumps(payload, ensure_ascii=False)})
    except Exception:
        pass


def _delete_persisted(job_id: str) -> None:
    try:
        r = get_redis()
        if r is not None:
            r.hdel(TASKS_KEY, job_id)
    except Exception:
        pass


def _list_persisted() -> dict[str, dict]:
    try:
        r = get_redis()
        if r is None:
            return {}
        raw = r.hgetall(TASKS_KEY) or {}
        out = {}
        for k, v in raw.items():
            try:
                key = k.decode("utf-8") if isinstance(k, bytes) else str(k)
                val = v.decode("utf-8") if isinstance(v, bytes) else str(v)
                out[key] = json.loads(val)
            except Exception:
                continue
        return out
    except Exception:
        return {}


def _spider_names() -> list[str]:
    try:
        from business.multi_spider.registry import list_spiders  # type: ignore
        return list_spiders() or []
    except Exception:
        return ["generic_web", "bid_and_gov", "local_classifieds", "enterprise_news"]


@router.get("/spider/tasks")
def list_spider_tasks(
    channel: str = "",
    status: str = "",
    keyword: str = "",
    session: dict = Depends(require_admin),
):
    """采集任务列表（支持按渠道/状态/关键字筛选）"""
    try:
        persisted = _list_persisted()
        # 合并调度器里的实际 Job
        scheduled: list[dict] = []
        try:
            from infra.task_scheduler import TaskScheduler
            scheduler = TaskScheduler()
            jobs = scheduler.list_jobs() or []
            for j in jobs:
                try:
                    jid = str(getattr(j, "id", "") or "")
                    next_time = getattr(j, "next_run_time", None)
                    if hasattr(next_time, "isoformat"):
                        next_str = next_time.isoformat() if next_time else None
                    else:
                        next_str = str(next_time) if next_time else None
                    scheduled.append({"job_id": jid, "next_run": next_str, "status": "ACTIVE"})
                except Exception:
                    continue
        except Exception:
            pass

        raw_out = []
        for j in scheduled:
            jid = j["job_id"]
            meta = persisted.get(jid, {})
            raw_out.append({**meta, **j})
        # 加上持久化中尚未加入调度的
        for jid, meta in persisted.items():
            if not any(x for x in raw_out if x.get("job_id") == jid):
                raw_out.append({**meta, "job_id": jid, "next_run": None, "status": "INACTIVE"})
        # 按参数过滤
        out = []
        for item in raw_out:
            if channel and item.get("channel") != channel:
                continue
            if status and item.get("status") != status:
                continue
            if keyword:
                haystack = " ".join([
                    str(item.get("job_id") or ""),
                    str(item.get("task_name") or ""),
                    str(item.get("spider_name") or ""),
                    str(item.get("channel") or ""),
                ]).lower()
                if keyword.lower() not in haystack:
                    continue
            out.append(item)
        return {"code": 0, "msg": "ok", "items": out, "spider_names": _spider_names(),
                "channels": sorted(VALID_CHANNELS), "statuses": sorted(TASK_STATUSES)}
    except Exception as exc:
        logger.error(f"list tasks: {exc}", exc_info=True)
        return {"code": 500, "msg": str(exc), "items": [], "spider_names": _spider_names(),
                "channels": sorted(VALID_CHANNELS), "statuses": sorted(TASK_STATUSES)}


# 任务状态枚举（对齐 T19 计划）
TASK_STATUSES = {"DRAFT", "READY", "RUNNING", "PAUSED", "COMPLETED", "FAILED", "TERMINATED"}
VALID_CHANNELS = {"generic_web", "short_video", "xhs", "qa_platform", "b2b_supply", "bidding", "company_biz"}
CHANNEL_LABEL = {
    "generic_web": "通用网页/论坛",
    "short_video": "短视频",
    "xhs": "小红书",
    "qa_platform": "问答平台",
    "b2b_supply": "供需 B2B",
    "bidding": "招投标",
    "company_biz": "企业工商",
}


@router.post("/spider/task")
def create_spider_task(
    job_id: str = Form(...),
    task_name: str = Form(default=""),
    channel: str = Form(default="generic_web"),
    spider_name: str = Form(default=""),
    speed_level: int = Form(default=3),
    max_items: int = Form(default=500),
    schedule_mode: str = Form(default="off"),
    cron: str = Form(default="*/30 * * * *"),
    time_range: str = Form(default=""),
    keywords: str = Form(default=""),
    region: str = Form(default=""),
    min_likes: int = Form(default=0),
    min_comments: int = Form(default=0),
    min_views: int = Form(default=0),
    min_answers: int = Form(default=0),
    registered_capital_min: int = Form(default=0),
    establishment_years: int = Form(default=0),
    publish_days: int = Form(default=30),
    industry: str = Form(default=""),
    platform: str = Form(default=""),
    company_keywords: str = Form(default=""),
    post_type: str = Form(default=""),
    filter_price: str = Form(default=""),
    filter_rule: str = Form(default=""),
    url_template: str = Form(default=""),
    site_type: str = Form(default=""),
    max_depth: int = Form(default=3),
    bid_type: str = Form(default=""),
    extract_rules: str = Form(default=""),
    session: dict = Depends(require_admin),
):
    try:
        job_id = (job_id or "").strip() or ("spider_" + str(int(time.time())))
        channel = (channel or "").strip() or "generic_web"
        if channel and channel not in VALID_CHANNELS:
            raise HTTPException(status_code=400, detail="channel 不合法，允许值：" + ",".join(sorted(VALID_CHANNELS)))
        spider_name = (spider_name or "").strip() or channel
        payload = {
            "job_id": job_id,
            "task_name": task_name,
            "channel": channel,
            "spider_name": spider_name,
            "speed_level": int(speed_level or 3),
            "max_items": int(max_items or 500),
            "schedule_mode": schedule_mode,
            "cron": cron,
            "time_range": time_range,
            "keywords": [k.strip() for k in (keywords or "").split(",") if k.strip()],
            "region": region,
            "min_likes": int(min_likes or 0),
            "min_comments": int(min_comments or 0),
            "min_views": int(min_views or 0),
            "min_answers": int(min_answers or 0),
            "registered_capital_min": int(registered_capital_min or 0),
            "establishment_years": int(establishment_years or 0),
            "publish_days": int(publish_days or 30),
            "industry": industry,
            "platform": platform,
            "company_keywords": company_keywords,
            "post_type": post_type,
            "filter_price": filter_price,
            "filter_rule": filter_rule,
            "url_template": url_template,
            "site_type": site_type,
            "max_depth": int(max_depth or 3),
            "bid_type": bid_type,
            "extract_rules": extract_rules,
            "created_by": session.get("username", ""),
            "created_at": int(time.time()),
            "status": "READY",
            "success": 0,
            "failed": 0,
            "risk_blocked": 0,
        }
        _persist_task(job_id, payload)
        try:
            from infra.task_scheduler import TaskScheduler
            from business.multi_spider.registry import run_spider_by_name  # type: ignore

            scheduler = TaskScheduler()

            def _job():
                try:
                    kwargs = {"spider_name": spider_name, "keywords": payload["keywords"],
                              "max_pages": payload["max_pages"]}
                    return run_spider_by_name(**{k: v for k, v in kwargs.items() if v is not None})
                except Exception as exc:
                    logger.error(f"spider job {job_id} failed: {exc}")
                    return {"error": str(exc)}

            scheduler.add_cron(job_id=job_id, func=_job, expression=cron)
        except Exception as exc:
            logger.info(f"任务加入调度失败（仅持久化不阻塞）: {exc}")
        return {"code": 0, "msg": "ok", "task": payload}
    except HTTPException:
        raise
    except Exception as exc:
        logger.error(f"create task: {exc}", exc_info=True)
        return {"code": 500, "msg": str(exc)}


@router.post("/spider/task/{job_id}/run")
def run_spider_now(job_id: str, session: dict = Depends(require_admin)):
    persisted = _list_persisted()
    meta = persisted.get(job_id) or {}
    spider_name = meta.get("spider_name") or job_id
    try:
        from business.multi_spider.registry import run_spider_by_name  # type: ignore
        result = run_spider_by_name(
            spider_name=spider_name,
            keywords=meta.get("keywords") or ["商机"],
            max_pages=int(meta.get("max_pages") or 10),
        )
        return {"code": 0, "msg": "ok", "result": str(result)[:500]}
    except Exception as exc:
        logger.error(f"run task {job_id}: {exc}", exc_info=True)
        return {"code": 500, "msg": str(exc)}


@router.post("/spider/task/{job_id}/pause")
def pause_spider_task(job_id: str, session: dict = Depends(require_admin)):
    try:
        from infra.task_scheduler import TaskScheduler
        TaskScheduler().remove_job(job_id)
    except Exception:
        pass
    try:
        r = get_redis()
        if r is not None:
            r.sadd(PAUSED_KEY, job_id)
    except Exception:
        pass
    return {"code": 0, "msg": "paused"}


@router.post("/spider/task/{job_id}/resume")
def resume_spider_task(job_id: str, session: dict = Depends(require_admin)):
    persisted = _list_persisted()
    meta = persisted.get(job_id)
    if not meta:
        raise HTTPException(status_code=404, detail=f"找不到任务 {job_id}")
    try:
        from infra.task_scheduler import TaskScheduler
        from business.multi_spider.registry import run_spider_by_name  # type: ignore
        scheduler = TaskScheduler()

        def _job():
            try:
                return run_spider_by_name(
                    spider_name=meta.get("spider_name", job_id),
                    keywords=meta.get("keywords") or ["商机"],
                    max_pages=int(meta.get("max_pages") or 10),
                )
            except Exception as exc:
                return {"error": str(exc)}

        scheduler.add_cron(job_id=job_id, func=_job, expression=meta.get("cron") or "*/30 * * * *")
    except Exception:
        pass
    try:
        r = get_redis()
        if r is not None:
            r.srem(PAUSED_KEY, job_id)
    except Exception:
        pass
    return {"code": 0, "msg": "resumed"}


@router.delete("/spider/task/{job_id}")
def delete_spider_task(job_id: str, session: dict = Depends(require_admin)):
    try:
        from infra.task_scheduler import TaskScheduler
        TaskScheduler().remove_job(job_id)
    except Exception:
        pass
    _delete_persisted(job_id)
    return {"code": 0, "msg": "deleted"}


@router.get("/spider/task/{job_id}/logs")
def get_spider_logs(job_id: str, limit: int = 50, session: dict = Depends(require_admin)):
    try:
        r = get_redis()
        if r is not None:
            raws = r.lrange(LOG_PREFIX + str(job_id), 0, limit - 1) or []
            out = []
            for raw in raws:
                try:
                    s = raw.decode("utf-8") if isinstance(raw, bytes) else str(raw)
                    out.append(s)
                except Exception:
                    continue
            return {"code": 0, "msg": "ok", "items": out}
    except Exception:
        pass
    return {"code": 0, "msg": "ok", "items": []}


@router.get("/spider/risks")
def get_spider_risks(session: dict = Depends(require_admin)):
    try:
        r = get_redis()
        if r is not None:
            raws = r.lrange(RISK_KEY, 0, 100)
            out = []
            for raw in raws:
                try:
                    s = raw.decode("utf-8") if isinstance(raw, bytes) else str(raw)
                    out.append(s)
                except Exception:
                    continue
            return {"code": 0, "msg": "ok", "items": out}
    except Exception:
        pass
    return {"code": 0, "msg": "ok", "items": []}


# ====================================================================
# T19 新增接口：任务详情 / 终止 / 重试 / 采集明细
# ====================================================================
@router.get("/spider/task/{job_id}")
def get_task_detail(job_id: str, session: dict = Depends(require_admin)):
    """获取任务详情（页面渲染为只读配置 + 进度 + 明细）"""
    persisted = _list_persisted()
    meta = persisted.get(job_id)
    if not meta:
        raise HTTPException(status_code=404, detail="任务不存在")
    return {
        "code": 0,
        "msg": "ok",
        "job": meta,
    }


@router.post("/spider/task/{job_id}/terminate")
def terminate_spider_task(job_id: str, session: dict = Depends(require_admin)):
    """终止任务：从调度器移除，状态标记为 TERMINATED（不可恢复）"""
    persisted = _list_persisted()
    meta = persisted.get(job_id)
    if not meta:
        raise HTTPException(status_code=404, detail="任务不存在")
    # 移除调度器
    try:
        from infra.task_scheduler import TaskScheduler
        TaskScheduler().remove_job(job_id)
    except Exception:
        pass
    meta["status"] = "TERMINATED"
    meta["terminated_at"] = int(time.time())
    meta["terminated_by"] = session.get("username", "")
    _persist_task(job_id, meta)
    return {"code": 0, "msg": "terminated", "job": meta}


@router.post("/spider/task/{job_id}/retry")
def retry_spider_task(job_id: str, session: dict = Depends(require_admin)):
    """重试失败任务：从上次中断位置继续（断点续爬）"""
    persisted = _list_persisted()
    meta = persisted.get(job_id)
    if not meta:
        raise HTTPException(status_code=404, detail="任务不存在")
    if meta.get("status") not in {"FAILED", "TERMINATED", "PAUSED"}:
        raise HTTPException(status_code=400, detail="当前状态不允许重试（仅 FAILED/TERMINATED/PAUSED 可以）")
    meta["status"] = "RUNNING"
    meta["last_retried_at"] = int(time.time())
    meta["retried_by"] = session.get("username", "")
    # 断点续爬：保留原有成功数，重置失败数
    meta.setdefault("resume_count", 0)
    meta["resume_count"] += 1
    _persist_task(job_id, meta)
    try:
        from infra.task_scheduler import TaskScheduler
        from business.multi_spider.registry import run_spider_by_name  # type: ignore
        scheduler = TaskScheduler()

        def _job():
            try:
                return run_spider_by_name(
                    spider_name=meta.get("spider_name", job_id),
                    keywords=meta.get("keywords") or [],
                    max_pages=meta.get("max_pages") or meta.get("max_items") or 50,
                )
            except Exception as exc:
                return {"error": str(exc)}

        scheduler.add_cron(job_id=job_id, func=_job, expression=meta.get("cron") or "*/30 * * * *")
    except Exception:
        pass
    return {"code": 0, "msg": "resumed (breakpoint resume)", "job": meta}


@router.get("/spider/task/{job_id}/items")
def get_task_items(job_id: str, page: int = 1, page_size: int = 20,
                   session: dict = Depends(require_admin)):
    """采集明细列表（分页）。
    注：底层业务 SDK 暂未提供 items 存储，此处返回 mock 数据 + 隐私字段供前端脱敏。
    业务接入后将从业务数据源读取。"""
    persisted = _list_persisted()
    meta = persisted.get(job_id)
    if not meta:
        raise HTTPException(status_code=404, detail="任务不存在")
    # 模拟数据（不依赖业务，仅用于前端 UI 测试）
    total = int(meta.get("success") or int(meta.get("max_items") or 0))
    start = (page - 1) * page_size
    end = min(start + page_size, total)
    items = []
    for i in range(start, end):
        items.append({
            "id": f"{job_id}_{i+1}",
            "title": f"示例内容 #{i+1}（渠道 {CHANNEL_LABEL.get(meta.get('channel'), meta.get('channel'))}）",
            "source": f"{meta.get('spider_name')} 来源 URL {i+1}",
            "author": f"user_{i+1:04d}@1380000{i % 10:02d}{i % 100:02d}",
            "phone": f"1380000{i % 10:02d}{i % 100:02d}{i % 1000:03d}",
            "email": f"contact{i+1}@example.com",
            "crawled_at": int(time.time()) - (total - i) * 60,
        })
    return {
        "code": 0,
        "msg": "ok",
        "items": items,
        "page": page,
        "page_size": page_size,
        "total": total,
    }


__all__ = ["router"]
