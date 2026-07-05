"""web_admin/api/compliance_rules — 采集任务前置合规审核（T20）。

纯管理层：任务状态变更 + Redis 持久化配置与记录，不触碰底层爬虫逻辑。
"""

from __future__ import annotations

import json
import time
import uuid
from typing import Any

from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import JSONResponse

from infra.logger_setup import get_logger
from infra.redis_client import get_redis
from web_admin.auth import require_admin

logger = get_logger("web_admin.compliance")
router = APIRouter(tags=["admin"])

# ---------------------------------------------------------------------------
# Redis 键定义
# ---------------------------------------------------------------------------
CK_CHANNEL_RULES = "web_admin:compliance:channel_rules"
CK_AGREEMENT_TEXT = "web_admin:compliance:agreement_text"
CK_RETENTION_OPTIONS = "web_admin:compliance:retention_options"
CK_FORBIDDEN_KEYWORDS = "web_admin:compliance:forbidden_keywords"
CK_AUDIT_RECORDS = "web_admin:compliance:audit_records"   # list of JSON
CK_NOTIFICATION_PREFIX = "web_admin:notification:"         # + username

# 默认合规协议文本
DEFAULT_AGREEMENT_TEXT = (
    "Data Collection Compliance Agreement\n"
    "1. This task is used only for legitimate public data collection; no personal privacy information is collected.\n"
    "2. Collected data is only used for internal business opportunity analysis/market research/bidding decisions.\n"
    "3. I commit to not collecting contact information, ID numbers, addresses or other sensitive personal data.\n"
    "4. Data retention period is chosen by the submitter, and data is automatically cleared upon expiration.\n"
    "5. The task submitter assumes direct responsibility for compliance with the collected content.\n"
    "6. High-risk channel collection must be approved by a compliance officer before execution.\n"
)

# 默认留存周期选项
DEFAULT_RETENTION_OPTIONS = ["30d", "90d", "180d", "1y"]

# 默认违规关键词（隐私类 + 违规类 + 反爬提示）
DEFAULT_FORBIDDEN_KEYWORDS = [
    "phone", "mobile", "email", "id card", "idcard", "address",
    "password", "passport", "driver license",
    "porn", "gamble", "gambling", "hack", "hacker",
    "anti-crawler", "anti_crawler", "robots.txt",
]

# 默认渠道审核规则：短视频/小红书/B2B 三个渠道默认需要审核
DEFAULT_CHANNEL_RULES = {
    "generic_web":   {"risk_level": "LOW",    "need_approval": False},
    "short_video":   {"risk_level": "HIGH",   "need_approval": True},
    "xhs":           {"risk_level": "HIGH",   "need_approval": True},
    "qa_platform":   {"risk_level": "MEDIUM", "need_approval": False},
    "b2b_supply":    {"risk_level": "HIGH",   "need_approval": True},
    "bidding":       {"risk_level": "LOW",    "need_approval": False},
    "company_biz":   {"risk_level": "LOW",    "need_approval": False},
}

COMPLIANCE_STATUSES = {"PENDING_APPROVAL", "REJECTED"}


# ---------------------------------------------------------------------------
# Redis 读写辅助
# ---------------------------------------------------------------------------
def _redis_read(key: str, default: Any) -> Any:
    try:
        r = get_redis()
        if r is None:
            return default
        raw = r.get(key)
        if raw is None:
            return default
        if isinstance(raw, bytes):
            raw = raw.decode("utf-8")
        return json.loads(raw)
    except Exception as exc:
        logger.warning(f"compliance read {key} failed: {exc}; returning default")
        return default


def _redis_write(key: str, value: Any) -> None:
    try:
        r = get_redis()
        if r is None:
            return
        r.set(key, json.dumps(value, ensure_ascii=False))
    except Exception as exc:
        logger.warning(f"compliance write {key} failed: {exc}")


def _redis_append(key: str, item: dict, max_len: int = 1000) -> None:
    try:
        r = get_redis()
        if r is None:
            return
        r.lpush(key, json.dumps(item, ensure_ascii=False))
        r.ltrim(key, 0, max_len - 1)
    except Exception as exc:
        logger.warning(f"compliance append {key} failed: {exc}")


def _redis_range(key: str, start: int = 0, end: int = 99) -> list[dict]:
    try:
        r = get_redis()
        if r is None:
            return []
        raws = r.lrange(key, start, end) or []
        out = []
        for raw in raws:
            try:
                s = raw.decode("utf-8") if isinstance(raw, bytes) else str(raw)
                out.append(json.loads(s))
            except Exception:
                continue
        return out
    except Exception as exc:
        logger.warning(f"compliance range {key} failed: {exc}")
        return []


# ---------------------------------------------------------------------------
# 公共函数：供 spider_task.py 创建任务时调用判定
# ---------------------------------------------------------------------------
def needs_approval_for_channel(channel: str) -> bool:
    """判断某渠道是否需要合规审批（读取配置）。"""
    rules = _redis_read(CK_CHANNEL_RULES, DEFAULT_CHANNEL_RULES)
    # 兼容 dict/list 两种结构
    if isinstance(rules, dict):
        rule = rules.get(channel) or {}
        return bool(rule.get("need_approval", False))
    return False


def get_channel_rules() -> dict:
    return _redis_read(CK_CHANNEL_RULES, DEFAULT_CHANNEL_RULES)


def get_forbidden_keywords() -> list[str]:
    return _redis_read(CK_FORBIDDEN_KEYWORDS, DEFAULT_FORBIDDEN_KEYWORDS)


def get_retention_options() -> list[str]:
    return _redis_read(CK_RETENTION_OPTIONS, DEFAULT_RETENTION_OPTIONS)


def get_agreement_text() -> str:
    return _redis_read(CK_AGREEMENT_TEXT, DEFAULT_AGREEMENT_TEXT)


def detect_forbidden_words(text: str) -> list[str]:
    """检测一段文本是否包含违规关键词，返回命中列表。"""
    if not text:
        return []
    lowered = text.lower()
    hits = []
    for kw in get_forbidden_keywords():
        if not kw:
            continue
        if kw.lower() in lowered:
            hits.append(kw)
    # 去重保留顺序
    seen = set()
    unique_hits = []
    for h in hits:
        if h not in seen:
            seen.add(h)
            unique_hits.append(h)
    return unique_hits


def record_audit_entry(entry: dict) -> None:
    """写入审核记录，供审核工作台查询。"""
    _redis_append(CK_AUDIT_RECORDS, entry)


def push_notification(username: str, notif: dict) -> None:
    """写入某用户的通知列表。"""
    if not username:
        return
    key = CK_NOTIFICATION_PREFIX + username
    _redis_append(key, notif, 500)


# ---------------------------------------------------------------------------
# 1. 获取全部配置
# ---------------------------------------------------------------------------
@router.get("/compliance/config")
def get_compliance_config(session: dict = Depends(require_admin)):
    return {
        "code": 0,
        "msg": "ok",
        "channel_rules": get_channel_rules(),
        "agreement_text": get_agreement_text(),
        "retention_options": get_retention_options(),
        "forbidden_keywords": get_forbidden_keywords(),
        "pending_status": "PENDING_APPROVAL",
        "rejected_status": "REJECTED",
    }


# ---------------------------------------------------------------------------
# 2-3. 渠道审批规则读写
# ---------------------------------------------------------------------------
@router.post("/compliance/config/channel_rules")
def update_channel_rules(
    channel: str = Form(...),
    risk_level: str = Form(default="LOW"),
    need_approval: str = Form(default="false"),
    session: dict = Depends(require_admin),
):
    rules = get_channel_rules()
    rules[channel] = {
        "risk_level": risk_level.upper(),
        "need_approval": need_approval.lower() in ("true", "1", "yes", "on"),
    }
    _redis_write(CK_CHANNEL_RULES, rules)
    logger.info(f"compliance: channel_rules updated by {session.get('username')} for {channel}")
    return {"code": 0, "msg": "ok", "channel_rules": rules}


@router.get("/compliance/channel_rules")
def get_channel_rules_api(session: dict = Depends(require_admin)):
    return {"code": 0, "msg": "ok", "channel_rules": get_channel_rules()}


# ---------------------------------------------------------------------------
# 4-5. 合规协议文本读写
# ---------------------------------------------------------------------------
@router.post("/compliance/config/agreement_text")
def update_agreement_text(
    text: str = Form(...),
    session: dict = Depends(require_admin),
):
    if not text or not text.strip():
        raise HTTPException(status_code=400, detail="协议文本不能为空")
    _redis_write(CK_AGREEMENT_TEXT, text)
    logger.info(f"compliance: agreement_text updated by {session.get('username')}")
    return {"code": 0, "msg": "ok"}


@router.get("/compliance/agreement_text")
def get_agreement_text_api(session: dict = Depends(require_admin)):
    return {"code": 0, "msg": "ok", "agreement_text": get_agreement_text()}


# ---------------------------------------------------------------------------
# 6-7. 留存周期选项读写
# ---------------------------------------------------------------------------
@router.post("/compliance/config/retention_options")
def update_retention_options(
    options: str = Form(...),
    session: dict = Depends(require_admin),
):
    """options 为逗号分隔字符串，例如 '30d,90d,180d,1y'。"""
    parsed = [o.strip() for o in options.split(",") if o.strip()]
    if not parsed:
        raise HTTPException(status_code=400, detail="留存周期选项不能为空")
    _redis_write(CK_RETENTION_OPTIONS, parsed)
    logger.info(f"compliance: retention_options updated by {session.get('username')} -> {parsed}")
    return {"code": 0, "msg": "ok", "retention_options": parsed}


@router.get("/compliance/retention_options")
def get_retention_options_api(session: dict = Depends(require_admin)):
    return {"code": 0, "msg": "ok", "retention_options": get_retention_options()}


# ---------------------------------------------------------------------------
# 8-9. 违规关键词黑名单读写
# ---------------------------------------------------------------------------
@router.post("/compliance/config/forbidden_keywords")
def update_forbidden_keywords(
    keywords: str = Form(...),
    session: dict = Depends(require_admin),
):
    """keywords 为逗号分隔字符串，例如 'phone,email,身份证'。"""
    parsed = [k.strip() for k in keywords.split(",") if k.strip()]
    if not parsed:
        raise HTTPException(status_code=400, detail="违规关键词不能为空")
    _redis_write(CK_FORBIDDEN_KEYWORDS, parsed)
    logger.info(f"compliance: forbidden_keywords updated by {session.get('username')} -> len={len(parsed)}")
    return {"code": 0, "msg": "ok", "forbidden_keywords": parsed}


@router.get("/compliance/forbidden_keywords")
def get_forbidden_keywords_api(session: dict = Depends(require_admin)):
    return {"code": 0, "msg": "ok", "forbidden_keywords": get_forbidden_keywords()}


# ---------------------------------------------------------------------------
# 10. 违规词校验接口（供任务创建页实时校验）
# ---------------------------------------------------------------------------
@router.post("/compliance/validate_keywords")
def validate_keywords_api(
    keywords: str = Form(default=""),
    url_template: str = Form(default=""),
    platform: str = Form(default=""),
    session: dict = Depends(require_admin),
):
    combined = " ".join([keywords, url_template, platform])
    hits = detect_forbidden_words(combined)
    return {
        "code": 0,
        "msg": "ok",
        "ok": len(hits) == 0,
        "hits": hits,
    }


# ---------------------------------------------------------------------------
# 11. 待审核任务列表
# ---------------------------------------------------------------------------
@router.get("/compliance/tasks/pending")
def get_pending_tasks(session: dict = Depends(require_admin)):
    """遍历所有采集任务，返回状态为 PENDING_APPROVAL 的任务。"""
    try:
        from web_admin.api.spider_task import _list_persisted
        persisted = _list_persisted() or {}
    except Exception:
        persisted = {}

    pending = []
    for job_id, meta in persisted.items():
        if not isinstance(meta, dict):
            continue
        if meta.get("status") == "PENDING_APPROVAL":
            pending.append({
                "job_id": job_id,
                "task_name": meta.get("task_name", ""),
                "channel": meta.get("channel", ""),
                "submitted_by": meta.get("created_by", ""),
                "submitted_at": meta.get("created_at", 0),
                "max_items": meta.get("max_items", 0),
                "compliance": meta.get("compliance", {}),
            })
    pending.sort(key=lambda x: x["submitted_at"] or 0, reverse=True)
    return {"code": 0, "msg": "ok", "items": pending, "total": len(pending)}


# ---------------------------------------------------------------------------
# 12. 审核历史记录
# ---------------------------------------------------------------------------
@router.get("/compliance/tasks/history")
def get_audit_history(
    limit: int = 50,
    session: dict = Depends(require_admin),
):
    items = _redis_range(CK_AUDIT_RECORDS, 0, max(0, limit - 1))
    return {
        "code": 0,
        "msg": "ok",
        "items": items,
        "total": len(items),
    }


# ---------------------------------------------------------------------------
# 13. 审核通过
# ---------------------------------------------------------------------------
@router.post("/compliance/task/{job_id}/approve")
def approve_task(job_id: str, session: dict = Depends(require_admin)):
    # 1) 从持久化任务中读取
    try:
        from web_admin.api.spider_task import _list_persisted, _persist_task
        persisted = _list_persisted() or {}
    except Exception:
        persisted = {}

    meta = persisted.get(job_id)
    if not meta:
        raise HTTPException(status_code=404, detail=f"任务不存在: {job_id}")
    if isinstance(meta, dict) and meta.get("status") != "PENDING_APPROVAL":
        raise HTTPException(status_code=400, detail=f"当前任务状态不可审批：{meta.get('status')}")

    # 2) 状态变更为 READY
    meta["status"] = "READY"
    meta["reviewed_by"] = session.get("username", "")
    meta["reviewed_at"] = int(time.time())
    meta["review_decision"] = "APPROVED"

    # 3) 写回 Redis
    try:
        _persist_task(job_id, meta)
    except Exception:
        try:
            from web_admin.api.spider_task import _persist_task as _pt2
            _pt2(job_id, meta)
        except Exception:
            pass

    # 4) 写入审核记录
    entry = {
        "job_id": job_id,
        "task_name": meta.get("task_name", ""),
        "channel": meta.get("channel", ""),
        "submitted_by": meta.get("created_by", ""),
        "submitted_at": meta.get("created_at", 0),
        "reviewed_by": session.get("username", ""),
        "reviewed_at": int(time.time()),
        "decision": "APPROVED",
        "reject_reason": None,
        "compliance_snapshot": meta.get("compliance", {}),
    }
    record_audit_entry(entry)

    # 5) 通知提交者
    submitter = meta.get("created_by", "")
    if submitter:
        push_notification(submitter, {
            "id": "notif_" + uuid.uuid4().hex[:12],
            "type": "COMPLIANCE_APPROVE",
            "title": f"任务 {meta.get('task_name') or job_id} 审核通过",
            "content": "您提交的采集任务已通过合规审核，可启动执行。",
            "link": f"/admin/spider/{job_id}",
            "from": session.get("username", ""),
            "to": submitter,
            "created_at": int(time.time()),
            "read": False,
        })
    logger.info(f"compliance: task {job_id} APPROVED by {session.get('username')}")
    return {"code": 0, "msg": "ok", "job": meta}


# ---------------------------------------------------------------------------
# 14. 审核驳回
# ---------------------------------------------------------------------------
@router.post("/compliance/task/{job_id}/reject")
def reject_task(
    job_id: str,
    reason: str = Form(default=""),
    session: dict = Depends(require_admin),
):
    if not reason or not reason.strip():
        raise HTTPException(status_code=400, detail="驳回原因不能为空")

    # 1) 读取任务
    try:
        from web_admin.api.spider_task import _list_persisted, _persist_task
        persisted = _list_persisted() or {}
    except Exception:
        persisted = {}

    meta = persisted.get(job_id)
    if not meta:
        raise HTTPException(status_code=404, detail=f"任务不存在: {job_id}")
    if isinstance(meta, dict) and meta.get("status") != "PENDING_APPROVAL":
        raise HTTPException(status_code=400, detail=f"当前任务状态不可审批：{meta.get('status')}")

    # 2) 状态变更为 REJECTED
    meta["status"] = "REJECTED"
    meta["reviewed_by"] = session.get("username", "")
    meta["reviewed_at"] = int(time.time())
    meta["review_decision"] = "REJECTED"
    meta["reject_reason"] = reason.strip()

    # 3) 写回
    try:
        _persist_task(job_id, meta)
    except Exception:
        try:
            from web_admin.api.spider_task import _persist_task as _pt2
            _pt2(job_id, meta)
        except Exception:
            pass

    # 4) 写入审核记录
    entry = {
        "job_id": job_id,
        "task_name": meta.get("task_name", ""),
        "channel": meta.get("channel", ""),
        "submitted_by": meta.get("created_by", ""),
        "submitted_at": meta.get("created_at", 0),
        "reviewed_by": session.get("username", ""),
        "reviewed_at": int(time.time()),
        "decision": "REJECTED",
        "reject_reason": reason.strip(),
        "compliance_snapshot": meta.get("compliance", {}),
    }
    record_audit_entry(entry)

    # 5) 通知提交者
    submitter = meta.get("created_by", "")
    if submitter:
        push_notification(submitter, {
            "id": "notif_" + uuid.uuid4().hex[:12],
            "type": "COMPLIANCE_REJECT",
            "title": f"任务 {meta.get('task_name') or job_id} 被驳回",
            "content": f"驳回原因：{reason.strip()}。请修改后重新提交。",
            "link": f"/admin/spider/{job_id}",
            "from": session.get("username", ""),
            "to": submitter,
            "created_at": int(time.time()),
            "read": False,
        })
    logger.info(f"compliance: task {job_id} REJECTED by {session.get('username')}: {reason[:80]}")
    return {"code": 0, "msg": "ok", "job": meta}


# ---------------------------------------------------------------------------
# 15. 通知中心
# ---------------------------------------------------------------------------
@router.get("/compliance/notifications")
def get_notifications(
    limit: int = 30,
    session: dict = Depends(require_admin),
):
    username = session.get("username", "")
    items = _redis_range(CK_NOTIFICATION_PREFIX + username, 0, max(0, limit - 1))
    return {
        "code": 0,
        "msg": "ok",
        "items": items,
        "total": len(items),
        "unread": sum(1 for it in items if not it.get("read")),
    }


@router.post("/compliance/notifications/read_all")
def mark_all_notifications_read(session: dict = Depends(require_admin)):
    username = session.get("username", "")
    key = CK_NOTIFICATION_PREFIX + username
    try:
        r = get_redis()
        if r is not None:
            raws = r.lrange(key, 0, -1) or []
            for idx, raw in enumerate(raws):
                try:
                    s = raw.decode("utf-8") if isinstance(raw, bytes) else str(raw)
                    item = json.loads(s)
                    item["read"] = True
                    r.lset(key, idx, json.dumps(item, ensure_ascii=False))
                except Exception:
                    continue
    except Exception:
        pass
    return {"code": 0, "msg": "ok"}


@router.post("/compliance/notify/send")
def send_notification_internal(
    to: str = Form(...),
    title: str = Form(...),
    content: str = Form(default=""),
    link: str = Form(default=""),
    type_: str = Form(default="INFO", alias="type"),
    session: dict = Depends(require_admin),
):
    push_notification(to, {
        "id": "notif_" + uuid.uuid4().hex[:12],
        "type": type_,
        "title": title,
        "content": content,
        "link": link,
        "from": session.get("username", ""),
        "to": to,
        "created_at": int(time.time()),
        "read": False,
    })
    return {"code": 0, "msg": "ok"}


# ---------------------------------------------------------------------------
# 16. 审核任务详情（单独接口，便于合规工作台查看完整采集参数）
# ---------------------------------------------------------------------------
@router.get("/compliance/task/{job_id}")
def get_compliance_task_detail(job_id: str, session: dict = Depends(require_admin)):
    try:
        from web_admin.api.spider_task import _list_persisted
        persisted = _list_persisted() or {}
    except Exception:
        persisted = {}

    meta = persisted.get(job_id)
    if not meta:
        raise HTTPException(status_code=404, detail="任务不存在")

    return {
        "code": 0,
        "msg": "ok",
        "job": meta,
        "needs_approval": needs_approval_for_channel(meta.get("channel", "")),
    }


__all__ = [
    "router",
    "needs_approval_for_channel",
    "get_channel_rules",
    "get_forbidden_keywords",
    "get_retention_options",
    "get_agreement_text",
    "detect_forbidden_words",
    "record_audit_entry",
    "push_notification",
]
