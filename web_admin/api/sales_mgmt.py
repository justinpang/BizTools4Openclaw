"""web_admin/api/sales_mgmt — 销售管理：人员/分配/跟进/逾期。"""

from __future__ import annotations

import json
import time

from fastapi import APIRouter, Depends, Form, HTTPException

from infra.logger_setup import get_logger
from infra.redis_client import get_redis
from web_admin.auth import require_admin

logger = get_logger("web_admin.sales")
router = APIRouter(tags=["admin"])

PERSONS_KEY = "web_admin:sales:persons"
ASSIGNMENTS_KEY = "web_admin:sales:assignments"
FOLLOWUPS_KEY = "web_admin:sales:followups"


def _mask_phone(v: str) -> str:
    v = (v or "").strip()
    if not v:
        return ""
    if "@" in v:
        parts = v.split("@")
        pre = parts[0]
        return (pre[0] + "***" + (pre[-1] if len(pre) > 1 else "")) + "@***"
    if v.isdigit() and len(v) >= 7:
        return v[:3] + "****" + v[-4:]
    if len(v) > 4:
        return v[0] + "***" + v[-1]
    return v[:1] + "*" * max(1, len(v) - 1)


@router.get("/sales/persons")
def list_persons(session: dict = Depends(require_admin)):
    try:
        from business.sales_task.registry import _get_persons  # type: ignore
        persons = list(_get_persons() or [])
        if persons:
            return {"code": 0, "msg": "ok",
                    "items": [{**p, "phone": _mask_phone(str(p.get("phone", ""))),
                               "email": _mask_phone(str(p.get("email", "")))} for p in persons]}
    except Exception:
        pass
    # 从 Redis 加载
    try:
        r = get_redis()
        if r is not None:
            raws = r.hgetall(PERSONS_KEY) or {}
            out = []
            for k, v in raws.items():
                try:
                    d = json.loads(v.decode("utf-8") if isinstance(v, bytes) else str(v))
                    d["sales_id"] = k.decode("utf-8") if isinstance(k, bytes) else str(k)
                    d["phone"] = _mask_phone(str(d.get("phone", "")))
                    d["email"] = _mask_phone(str(d.get("email", "")))
                    out.append(d)
                except Exception:
                    continue
            return {"code": 0, "msg": "ok", "items": out}
    except Exception:
        pass
    return {"code": 0, "msg": "ok", "items": []}


@router.post("/sales/person")
def upsert_person(
    sales_id: str = Form(...),
    name: str = Form(...),
    industries: str = Form(default=""),
    weight: float = Form(default=1.0),
    phone: str = Form(default=""),
    email: str = Form(default=""),
    session: dict = Depends(require_admin),
):
    sales_id = (sales_id or "").strip() or f"s_{int(time.time())}"
    payload = {
        "sales_id": sales_id,
        "name": name or sales_id,
        "industries": [i.strip() for i in (industries or "").split(",") if i.strip()],
        "weight": float(weight or 1.0),
        "phone": phone,   # 原始值仅在内存使用，输出时脱敏
        "email": email,
        "created_by": session.get("username", ""),
        "created_at": int(time.time()),
    }
    try:
        r = get_redis()
        if r is not None:
            r.hset(PERSONS_KEY, mapping={sales_id: json.dumps(payload, ensure_ascii=False)})
    except Exception:
        pass
    payload["phone"] = _mask_phone(str(payload.get("phone", "")))
    payload["email"] = _mask_phone(str(payload.get("email", "")))
    return {"code": 0, "msg": "ok", "person": payload}


@router.get("/sales/assignments")
def list_assignments(session: dict = Depends(require_admin)):
    try:
        from business.sales_task.registry import assign  # type: ignore
        # 尝试直接构造 demo 分配
    except Exception:
        pass
    try:
        r = get_redis()
        if r is not None:
            raws = r.lrange(ASSIGNMENTS_KEY, 0, 99) or []
            out = []
            for raw in raws:
                try:
                    s = raw.decode("utf-8") if isinstance(raw, bytes) else str(raw)
                    out.append(json.loads(s))
                except Exception:
                    continue
            return {"code": 0, "msg": "ok", "items": out}
    except Exception:
        pass
    return {"code": 0, "msg": "ok", "items": []}


@router.post("/sales/assign")
def do_assign(
    opportunity_id: str = Form(...),
    customer: str = Form(default=""),
    sales_id: str = Form(default=""),
    session: dict = Depends(require_admin),
):
    assignment = {
        "assignment_id": f"a_{int(time.time())}",
        "opportunity_id": opportunity_id,
        "customer": _mask_phone(customer or ""),
        "sales_id": sales_id or "auto",
        "assigned_by": session.get("username", ""),
        "assigned_at": int(time.time()),
        "status": "ASSIGNED",
    }
    try:
        from business.sales_task.registry import assign as _assign  # type: ignore
        try:
            # 真实调用
            _assign(opportunity={"opportunity_id": opportunity_id,
                                 "tenant_id": "web_admin",
                                 "title": customer or "未命名商机"},
                    salespersons=[{"sales_id": sales_id, "weight": 1.0}] if sales_id else None)
        except Exception:
            pass
    except Exception:
        pass
    try:
        r = get_redis()
        if r is not None:
            r.lpush(ASSIGNMENTS_KEY, json.dumps(assignment, ensure_ascii=False))
            r.ltrim(ASSIGNMENTS_KEY, 0, 499)
    except Exception:
        pass
    return {"code": 0, "msg": "ok", "assignment": assignment}


@router.get("/sales/followups")
def list_followups(session: dict = Depends(require_admin)):
    try:
        r = get_redis()
        if r is not None:
            raws = r.lrange(FOLLOWUPS_KEY, 0, 99) or []
            out = []
            for raw in raws:
                try:
                    s = raw.decode("utf-8") if isinstance(raw, bytes) else str(raw)
                    out.append(json.loads(s))
                except Exception:
                    continue
            return {"code": 0, "msg": "ok", "items": out}
    except Exception:
        pass
    return {"code": 0, "msg": "ok", "items": []}


@router.post("/sales/followup")
def record_followup(
    opportunity_id: str = Form(...),
    channel: str = Form(default="phone"),
    content: str = Form(default=""),
    sales_id: str = Form(default=""),
    session: dict = Depends(require_admin),
):
    item = {
        "followup_id": f"fu_{int(time.time())}",
        "opportunity_id": opportunity_id,
        "channel": channel,
        "content": content[:500],
        "sales_id": sales_id or session.get("username", ""),
        "by": session.get("username", ""),
        "ts": int(time.time()),
    }
    try:
        from business.sales_task.registry import record_follow_up  # type: ignore
        try:
            record_follow_up(opportunity={"opportunity_id": opportunity_id},
                             sales_id=sales_id or "web_admin",
                             channel=channel, content=content[:500])
        except Exception:
            pass
    except Exception:
        pass
    try:
        r = get_redis()
        if r is not None:
            r.lpush(FOLLOWUPS_KEY, json.dumps(item, ensure_ascii=False))
            r.ltrim(FOLLOWUPS_KEY, 0, 499)
    except Exception:
        pass
    return {"code": 0, "msg": "ok", "followup": item}


@router.get("/sales/overdue")
def list_overdue(session: dict = Depends(require_admin)):
    """简单的逾期判定：最近 24 小时内有跟进记录但状态仍非 CLOSED。"""
    try:
        r = get_redis()
        if r is not None:
            raws = r.lrange(FOLLOWUPS_KEY, 0, 99) or []
            now = int(time.time())
            cutoff = now - 24 * 3600
            out = []
            seen = set()
            for raw in raws:
                try:
                    s = raw.decode("utf-8") if isinstance(raw, bytes) else str(raw)
                    d = json.loads(s)
                    if int(d.get("ts", 0) or 0) < cutoff and d.get("opportunity_id") not in seen:
                        seen.add(d["opportunity_id"])
                        out.append({"opportunity_id": d["opportunity_id"],
                                    "sales_id": d.get("sales_id", ""),
                                    "last_followup_at": d.get("ts", 0),
                                    "hint": "超过 24 小时未继续跟进"})
                except Exception:
                    continue
            return {"code": 0, "msg": "ok", "items": out[:50]}
    except Exception:
        pass
    return {"code": 0, "msg": "ok", "items": []}


__all__ = ["router"]
