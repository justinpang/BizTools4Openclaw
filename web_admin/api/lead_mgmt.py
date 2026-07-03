"""web_admin/api/lead_mgmt — 商机线索管理 + 黑名单。"""

from __future__ import annotations

import json
import time

from fastapi import APIRouter, Depends, Form, HTTPException

from infra.logger_setup import get_logger
from infra.redis_client import get_redis
from web_admin.auth import require_admin

logger = get_logger("web_admin.leads")
router = APIRouter(tags=["admin"])

LEADS_KEY = "web_admin:leads"        # hash: lead_id -> json
BLACKLIST_KEY = "web_admin:blacklist"  # list of entries
REJECT_BATCH_KEY = "web_admin:leads_reject"


def _mask_value(v: str) -> str:
    v = (v or "").strip()
    if not v:
        return v
    if "@" in v:
        parts = v.split("@")
        pre = parts[0]
        return (pre[0] + "***" + (pre[-1] if len(pre) > 1 else "")) + "@" + "***"
    if v.isdigit() and len(v) >= 7:
        return v[:3] + "****" + v[-4:]
    if len(v) > 4:
        return v[0] + "***" + v[-1]
    return v[:1] + "*" * max(1, len(v) - 1)


def _mask_lead(lead: dict) -> dict:
    sensitive_keys = {"phone", "email", "mobile", "contact", "idcard", "passport",
                      "wechat", "qq", "secret", "customer_name", "company_contact"}
    out = {}
    for k, v in lead.items():
        if any(sk in str(k).lower() for sk in sensitive_keys):
            if isinstance(v, str):
                out[k] = _mask_value(v)
            elif isinstance(v, (list, tuple)):
                out[k] = [_mask_value(str(x)) for x in v]
            else:
                out[k] = v
        else:
            out[k] = v
    return out


@router.get("/leads")
def list_leads(page: int = 1, page_size: int = 20, status: str = "",
               keyword: str = "", session: dict = Depends(require_admin)):
    page = max(1, int(page))
    page_size = max(1, min(int(page_size), 200))
    try:
        from business.data_clean.storage import query_leads  # type: ignore
        result = query_leads(page=page, page_size=page_size, status=status or None, keyword=keyword or None)
        if isinstance(result, dict):
            items = result.get("items") or []
            total = int(result.get("total", len(items)))
        elif hasattr(result, "items"):
            items = list(result.items)
            total = int(getattr(result, "total", len(items)))
        else:
            items, total = [], 0
        return {"code": 0, "msg": "ok", "items": [_mask_lead(dict(x)) if hasattr(x, "keys") else _mask_lead({}) for x in items], "total": total}
    except Exception as exc:
        logger.info(f"leads query fallback: {exc}")
        # 降级：Redis 缓存的简单线索
        try:
            r = get_redis()
            if r is not None:
                raws = r.hgetall(LEADS_KEY) or {}
                all_items = []
                for k, v in raws.items():
                    try:
                        s = v.decode("utf-8") if isinstance(v, bytes) else str(v)
                        d = json.loads(s)
                        all_items.append(d)
                    except Exception:
                        continue
                if keyword:
                    all_items = [x for x in all_items if keyword in str(x.get("title", ""))]
                if status:
                    all_items = [x for x in all_items if x.get("status") == status]
                total = len(all_items)
                start = (page - 1) * page_size
                items = all_items[start:start + page_size]
                return {"code": 0, "msg": "ok",
                        "items": [_mask_lead(x) for x in items], "total": total}
        except Exception:
            pass
        return {"code": 0, "msg": "ok", "items": [], "total": 0}


@router.get("/leads/{lead_id}")
def get_lead_detail(lead_id: str, session: dict = Depends(require_admin)):
    try:
        from business.data_clean.storage import get_lead  # type: ignore
        detail = get_lead(lead_id)
        if isinstance(detail, dict):
            return {"code": 0, "msg": "ok", "detail": _mask_lead(detail)}
        if hasattr(detail, "model_dump"):
            return {"code": 0, "msg": "ok", "detail": _mask_lead(detail.model_dump())}
        return {"code": 0, "msg": "ok", "detail": str(detail)}
    except Exception as exc:
        logger.info(f"get lead fallback: {exc}")
        return {"code": 0, "msg": "ok", "detail": {"id": lead_id, "status": "N/A"}}


@router.post("/leads/{lead_id}/approve")
def approve_lead(lead_id: str, session: dict = Depends(require_admin)):
    try:
        from business.data_clean.storage import set_lead_status  # type: ignore
        set_lead_status(lead_id, "APPROVED")
    except Exception:
        try:
            r = get_redis()
            if r is not None:
                raw = r.hget(LEADS_KEY, lead_id)
                if raw:
                    d = json.loads(raw.decode("utf-8") if isinstance(raw, bytes) else str(raw))
                    d["status"] = "APPROVED"
                    d["reviewed_by"] = session.get("username", "")
                    d["reviewed_at"] = int(time.time())
                    r.hset(LEADS_KEY, mapping={lead_id: json.dumps(d, ensure_ascii=False)})
        except Exception:
            pass
    return {"code": 0, "msg": "approved"}


@router.post("/leads/{lead_id}/reject")
def reject_lead(lead_id: str, reason: str = Form(default="人工复核拒绝"),
                session: dict = Depends(require_admin)):
    try:
        from business.data_clean.storage import set_lead_status  # type: ignore
        set_lead_status(lead_id, "REJECTED")
    except Exception:
        try:
            r = get_redis()
            if r is not None:
                raw = r.hget(LEADS_KEY, lead_id)
                if raw:
                    d = json.loads(raw.decode("utf-8") if isinstance(raw, bytes) else str(raw))
                    d["status"] = "REJECTED"
                    d["reviewed_by"] = session.get("username", "")
                    d["reviewed_at"] = int(time.time())
                    r.hset(LEADS_KEY, mapping={lead_id: json.dumps(d, ensure_ascii=False)})
        except Exception:
            pass
    # 加入黑名单
    try:
        from core.data_core.blacklist_filter import BlacklistFilter  # type: ignore
        bf = BlacklistFilter()
        bf.add_item({"type": "manual_reject", "identifier": lead_id, "reason": reason})
    except Exception:
        try:
            r = get_redis()
            if r is not None:
                r.lpush(BLACKLIST_KEY,
                        json.dumps({"type": "manual_reject", "identifier": lead_id,
                                    "reason": reason, "by": session.get("username", ""),
                                    "ts": int(time.time())}, ensure_ascii=False))
        except Exception:
            pass
    return {"code": 0, "msg": "rejected"}


@router.post("/leads/blacklist/add")
def add_to_blacklist(identifier: str = Form(...), type: str = Form(default="phone"),
                     reason: str = Form(default=""), session: dict = Depends(require_admin)):
    identifier = (identifier or "").strip()
    if not identifier:
        raise HTTPException(status_code=400, detail="identifier 必填")
    try:
        from core.data_core.blacklist_filter import BlacklistFilter  # type: ignore
        bf = BlacklistFilter()
        bf.add_item({"type": type, "identifier": identifier, "reason": reason or "手动添加"})
    except Exception:
        try:
            r = get_redis()
            if r is not None:
                r.lpush(BLACKLIST_KEY,
                        json.dumps({"type": type, "identifier": _mask_value(identifier),
                                    "reason": reason or "手动添加",
                                    "by": session.get("username", ""),
                                    "ts": int(time.time())}, ensure_ascii=False))
        except Exception:
            pass
    return {"code": 0, "msg": "added"}


@router.get("/leads/blacklist")
def list_blacklist(limit: int = 50, session: dict = Depends(require_admin)):
    try:
        from core.data_core.blacklist_filter import BlacklistFilter  # type: ignore
        bf = BlacklistFilter()
        items = []
        if hasattr(bf, "list_all"):
            items = bf.list_all() or []
        if items:
            return {"code": 0, "msg": "ok", "items": [{"type": str(x.get("type", "")),
                                                       "identifier": _mask_value(str(x.get("identifier", ""))),
                                                       "reason": str(x.get("reason", ""))}
                                                      for x in items if isinstance(x, dict)][:limit]}
    except Exception:
        pass
    try:
        r = get_redis()
        if r is not None:
            raws = r.lrange(BLACKLIST_KEY, 0, int(limit) - 1) or []
            out = []
            for raw in raws:
                try:
                    s = raw.decode("utf-8") if isinstance(raw, bytes) else str(raw)
                    d = json.loads(s)
                    if "identifier" in d:
                        d["identifier"] = _mask_value(str(d["identifier"]))
                    out.append(d)
                except Exception:
                    continue
            return {"code": 0, "msg": "ok", "items": out}
    except Exception:
        pass
    return {"code": 0, "msg": "ok", "items": []}


__all__ = ["router"]
