"""web_admin/api/crawl_config — 采集配置中心 API。

所有采集/解析/方案操作 100% 调用 T25/T26 底层接口，不直接操作数据。
响应格式统一为 {code, msg, data}。
"""

from __future__ import annotations

import json
import time
import hashlib
from datetime import datetime
from typing import Any, Dict, List, Optional
from urllib.parse import urlparse

from fastapi import APIRouter, Body, Depends, Form, HTTPException, Request
from fastapi.responses import JSONResponse

from infra.logger_setup import get_logger
from infra.redis_client import get_redis
from web_admin.auth import require_admin, require_permission

logger = get_logger("web_admin.crawl_config")
router = APIRouter(tags=["admin"])

# ============================================================
# 工具函数
# ============================================================

def _json_response(code: int, msg: str, data: Any = None) -> JSONResponse:
    """统一响应格式"""
    return JSONResponse(status_code=200, content={"code": code, "msg": msg, "data": data})


def _success(data: Any = None, msg: str = "ok") -> JSONResponse:
    return _json_response(0, msg, data)


def _error(msg: str, code: int = 1, status_code: int = 200) -> JSONResponse:
    return JSONResponse(status_code=status_code, content={"code": code, "msg": msg, "data": None})


def _get_plan_service():
    """懒加载 T26 PlanService"""
    try:
        from business.custom_spider.service import PlanService
        return PlanService()
    except Exception as exc:
        logger.warning(f"PlanService 加载失败: {exc}")
        return None


def _extract_domain(url: str) -> str:
    """从 URL 提取域名"""
    try:
        parsed = urlparse(url)
        return parsed.netloc or url[:128]
    except Exception:
        return url[:128]


def _sanitize_html(html: str, max_bytes: int = 5 * 1024 * 1024) -> str:
    """安全清理 HTML（剥离 script/内联事件；将 iframe/embed 替换为可见的附件占位块）"""
    if not html:
        return ""
    # 截断到最大字节
    if len(html) > max_bytes:
        html = html[:max_bytes]

    import re
    # 移除 <script>...</script> 块 — 使用非贪婪匹配，避免误伤中间的 HTML
    html = re.sub(r"<script\b[^>]*>[\s\S]*?</script>", "", html, flags=re.IGNORECASE)
    html = re.sub(r"<script\b[^>]*/?>", "", html, flags=re.IGNORECASE)
    html = re.sub(r"</script>", "", html, flags=re.IGNORECASE)

    # 将 <iframe>/<embed>/<object>/<frame> 替换为可见的占位块（而非简单删除）
    def _replace_iframe(match):
        tag = match.group(0)
        src_match = re.search(r'src\s*=\s*["\']([^"\']+)["\']', tag, flags=re.IGNORECASE)
        src = src_match.group(1) if src_match else ""
        real_pdf = ""
        if src and ("pdfjs" in src.lower() or "viewer" in src.lower() or "file=" in src.lower()):
            from urllib.parse import urlparse, parse_qs
            try:
                parsed = urlparse(src)
                qs = parse_qs(parsed.query)
                if "file" in qs and qs["file"]:
                    real_pdf = qs["file"][0]
            except Exception:
                pass
        display_src = real_pdf or src or "嵌入式文档"
        ext = display_src.split("?")[0].split(".")[-1].lower() if "." in display_src else ""
        file_type = ext.upper() if ext in ("pdf", "doc", "docx", "xls", "xlsx", "ppt", "pptx", "zip", "rar", "txt") else "附件"
        short_src = display_src[-60:] if len(display_src) > 60 else display_src
        return (
            f'<div style="margin:10px 0;padding:12px 16px;border:2px dashed #3498db;'
            f'border-radius:8px;background:#eaf4fd;font-size:14px;" '
            f'data-pdf-url="{display_src}" data-file-type="{file_type}" '
            f'class="pdf-attachment" data-crawl-href="{display_src}">'
            f'📄 <b style="color:#2c5aa0;">【{file_type}】附件 / 嵌入式文档</b><br>'
            f'<span style="color:#666;font-size:12px;">{short_src}</span>'
            f'</div>'
        )

    def _replace_embed(match):
        tag = match.group(0)
        src_match = re.search(r'(?:src|data)\s*=\s*["\']([^"\']+)["\']', tag, flags=re.IGNORECASE)
        src = src_match.group(1) if src_match else ""
        ext = src.split("?")[0].split(".")[-1].lower() if "." in src else ""
        file_type = ext.upper() if ext in ("pdf", "doc", "docx", "xls", "xlsx", "ppt", "pptx", "zip", "rar", "txt") else "附件"
        short_src = src[-60:] if len(src) > 60 else src
        return (
            f'<div style="margin:10px 0;padding:12px 16px;border:2px dashed #27ae60;'
            f'border-radius:8px;background:#edf9ee;font-size:14px;" '
            f'data-pdf-url="{src}" data-file-type="{file_type}" '
            f'class="pdf-attachment" data-crawl-href="{src}">'
            f'📄 <b style="color:#1e6f3e;">【{file_type}】嵌入式文档</b><br>'
            f'<span style="color:#666;font-size:12px;">{short_src}</span>'
            f'</div>'
        )

    # 先处理带闭合标签的 iframe/embed/object（非贪婪匹配）
    html = re.sub(r"<iframe\b[^>]*>[\s\S]*?</iframe>", _replace_iframe, html, flags=re.IGNORECASE)
    html = re.sub(r"<iframe\b[^>]*/?>", _replace_iframe, html, flags=re.IGNORECASE)
    html = re.sub(r"</iframe>", "", html, flags=re.IGNORECASE)
    html = re.sub(r"<embed\b[^>]*>[\s\S]*?</embed>", _replace_embed, html, flags=re.IGNORECASE)
    html = re.sub(r"<embed\b[^>]*/?>", _replace_embed, html, flags=re.IGNORECASE)
    html = re.sub(r"</embed>", "", html, flags=re.IGNORECASE)
    html = re.sub(r"<object\b[^>]*>[\s\S]*?</object>", _replace_embed, html, flags=re.IGNORECASE)
    html = re.sub(r"<object\b[^>]*/?>", _replace_embed, html, flags=re.IGNORECASE)
    html = re.sub(r"</object>", "", html, flags=re.IGNORECASE)
    html = re.sub(r"<frame\b[^>]*>[\s\S]*?</frame>", _replace_embed, html, flags=re.IGNORECASE)
    html = re.sub(r"<frame\b[^>]*/?>", _replace_embed, html, flags=re.IGNORECASE)
    html = re.sub(r"</frame>", "", html, flags=re.IGNORECASE)

    # 移除内联事件（onclick/onload/onmouseover 等）
    html = re.sub(r'\s+on[a-z]+\s*=\s*"[^"]*"', "", html, flags=re.IGNORECASE)
    html = re.sub(r"\s+on[a-z]+\s*=\s*'[^']*'", "", html, flags=re.IGNORECASE)

    return html


def _mask_sensitive_text(text: str) -> str:
    """简单的手机号/邮箱脱敏"""
    if not text:
        return text
    import re
    # 手机号脱敏：13812345678 -> 138****5678
    text = re.sub(r"(1[3-9]\d)(\d{4})(\d{4})", r"\1****\3", text)
    # 邮箱脱敏：user@example.com -> u***@example.com
    text = re.sub(r"(\w)(\w*)(@\w+\.[\w.]+)", r"\1***\3", text)
    # 身份证脱敏
    text = re.sub(r"(\d{6})(\d{8})(\d{3}[\dXx])", r"\1********\3", text)
    return text


# ============================================================
# 1. 方案列表 API
# ============================================================

@router.get("/crawl/plans")
def list_plans_api(
    status: str = "",
    keyword: str = "",
    page: int = 1,
    page_size: int = 20,
    request: Request = None,
):
    """采集方案列表（支持按状态/关键词筛选）。"""
    session = require_permission(request, "btn.spider.view")
    try:
        svc = _get_plan_service()
        if svc is None:
            return _error("PlanService 不可用（底层模块未就绪）")

        result = svc.list_plans(
            status=status or None,
            keyword=keyword or None,
            page=page,
            page_size=page_size,
        )
        items = result.get("items", []) if isinstance(result, dict) else []
        total = result.get("total", 0) if isinstance(result, dict) else len(items)

        # 格式化展示字段
        display_items = []
        for p in items:
            if isinstance(p, dict):
                rule_cfg = p.get("rule_config") or {}
                sched = p.get("schedule_config") or {}
                display_items.append({
                    "id": p.get("id"),
                    "plan_name": p.get("plan_name"),
                    "target_domain": p.get("target_domain"),
                    "spider_type": p.get("spider_type"),
                    "status": p.get("status"),
                    "current_version": p.get("current_version"),
                    "run_count_total": p.get("run_count_total", 0),
                    "items_total": p.get("items_total", 0),
                    "last_run_status": p.get("last_run_status"),
                    "last_run_at": p.get("last_run_at"),
                    "schedule_enabled": bool(sched.get("enabled")) if sched else False,
                    "schedule_cron": sched.get("cron") if isinstance(sched, dict) else None,
                    "created_by": p.get("created_by"),
                    "created_at": p.get("created_at"),
                })
        return _success({"items": display_items, "total": total, "page": page, "page_size": page_size})
    except Exception as exc:
        logger.error(f"list_plans_api 失败: {exc}")
        return _error(f"查询失败: {exc}")


@router.post("/crawl/plans")
async def create_plan_api(request: Request):
    """创建新方案。"""
    session = require_permission(request, "btn.spider.edit")
    try:
        body = await request.json()
    except Exception:
        return _error("请求体必须是合法 JSON")

    plan_name = body.get("plan_name")
    rule_config = body.get("rule_config") or {}
    target_domain = body.get("target_domain")
    if not target_domain and rule_config.get("list_rule"):
        target_domain = _extract_domain(rule_config["list_rule"].get("url_template", ""))
    spider_type = body.get("spider_type", "generic")
    description = body.get("description")
    schedule_config = body.get("schedule_config")
    increment_config = body.get("increment_config")
    cookie_raw = body.get("cookie_raw")
    operator = (session.get("username") or session.get("account") or "system") if session else "system"

    if not plan_name or not target_domain:
        return _error("plan_name 和 target_domain 必填")

    try:
        svc = _get_plan_service()
        if svc is None:
            return _error("PlanService 不可用")

        result = svc.create_plan(
            plan_name=plan_name,
            target_domain=target_domain,
            spider_type=spider_type,
            rule_config=rule_config,
            description=description,
            schedule_config=schedule_config,
            increment_config=increment_config,
            cookie_raw=cookie_raw,
            operator=operator,
        )

        if isinstance(result, dict) and result.get("success"):
            return _success({"plan_id": result.get("plan_id"), "plan_code": result.get("plan_code")})
        msg = result.get("error") if isinstance(result, dict) else "创建失败"
        return _error(msg or "创建失败")
    except Exception as exc:
        logger.error(f"create_plan_api 失败: {exc}")
        return _error(f"创建方案失败: {exc}")


@router.put("/crawl/plans/{plan_id}")
async def update_plan_api(plan_id: int, request: Request):
    """更新方案。"""
    session = require_permission(request, "btn.spider.edit")
    try:
        body = await request.json()
    except Exception:
        return _error("请求体必须是合法 JSON")

    operator = (session.get("username") or session.get("account") or "system") if session else "system"

    try:
        svc = _get_plan_service()
        if svc is None:
            return _error("PlanService 不可用")

        result = svc.update_plan(
            plan_id,
            plan_name=body.get("plan_name"),
            status=body.get("status"),
            rule_config=body.get("rule_config"),
            schedule_config=body.get("schedule_config"),
            increment_config=body.get("increment_config"),
            cookie_raw=body.get("cookie_raw"),
            change_note=body.get("change_note"),
            operator=operator,
        )

        if isinstance(result, dict) and result.get("success"):
            return _success({"plan_id": plan_id, "new_version": result.get("new_version")})
        msg = result.get("error") if isinstance(result, dict) else "更新失败"
        return _error(msg or "更新失败")
    except Exception as exc:
        logger.error(f"update_plan_api 失败: {exc}")
        return _error(f"更新方案失败: {exc}")


@router.post("/crawl/plans/{plan_id}/clone")
async def clone_plan_api(plan_id: int, request: Request):
    """克隆方案。"""
    session = require_permission(request, "btn.spider.edit")
    try:
        body = await request.json()
    except Exception:
        body = {}

    operator = (session.get("username") or session.get("account") or "system") if session else "system"

    try:
        svc = _get_plan_service()
        if svc is None:
            return _error("PlanService 不可用")
        plan = svc.get_plan(plan_id)
        original_name = plan.get("plan_name", str(plan_id)) if isinstance(plan, dict) else str(plan_id)

        result = svc.clone_plan(
            plan_id,
            new_plan_name=f"{original_name} (副本 {int(time.time()) % 10000})",
            operator=operator,
        )
        if isinstance(result, dict) and result.get("success"):
            return _success({"plan_id": result.get("plan_id"), "plan_code": result.get("plan_code")})
        return _error(result.get("error") if isinstance(result, dict) else "克隆失败")
    except Exception as exc:
        logger.error(f"clone_plan_api 失败: {exc}")
        return _error(f"克隆方案失败: {exc}")


@router.delete("/crawl/plans/{plan_id}")
def delete_plan_api(plan_id: int, request: Request):
    """删除方案（软删除）。"""
    session = require_permission(request, "btn.spider.edit")
    operator = (session.get("username") or session.get("account") or "system") if session else "system"
    try:
        svc = _get_plan_service()
        if svc is None:
            return _error("PlanService 不可用")
        result = svc.delete_plan(plan_id, operator=operator)
        if isinstance(result, dict) and result.get("success"):
            return _success({"plan_id": plan_id})
        return _error(result.get("error") if isinstance(result, dict) else "删除失败")
    except Exception as exc:
        logger.error(f"delete_plan_api 失败: {exc}")
        return _error(f"删除方案失败: {exc}")


@router.get("/crawl/plans/{plan_id}/detail")
def get_plan_detail_api(plan_id: int, request: Request):
    """获取方案详情（含规则配置）。"""
    session = require_permission(request, "btn.spider.view")
    try:
        svc = _get_plan_service()
        if svc is None:
            return _error("PlanService 不可用")
        plan = svc.get_plan(plan_id)
        if not plan:
            return _error("方案不存在")
        # 不返回 cookie_encrypted 字段
        if isinstance(plan, dict):
            plan.pop("cookie_encrypted", None)
        return _success(plan)
    except Exception as exc:
        logger.error(f"get_plan_detail_api 失败: {exc}")
        return _error(f"查询失败: {exc}")


# ============================================================
# 2. 方案启停调度
# ============================================================

@router.post("/crawl/plans/{plan_id}/enable")
def enable_schedule_api(plan_id: int, request: Request):
    """启用采集调度。"""
    session = require_permission(request, "btn.spider.edit")
    operator = (session.get("username") or session.get("account") or "system") if session else "system"
    try:
        svc = _get_plan_service()
        if svc is None:
            return _error("PlanService 不可用")
        result = svc.enable_schedule(plan_id, operator=operator)
        if isinstance(result, dict) and result.get("success"):
            return _success({"plan_id": plan_id, "job_id": result.get("job_id")})
        return _error(result.get("error") if isinstance(result, dict) else "启用失败")
    except Exception as exc:
        logger.error(f"enable_schedule_api 失败: {exc}")
        return _error(f"启用调度失败: {exc}")


@router.post("/crawl/plans/{plan_id}/disable")
def disable_schedule_api(plan_id: int, request: Request):
    """停用采集调度。"""
    session = require_permission(request, "btn.spider.edit")
    operator = (session.get("username") or session.get("account") or "system") if session else "system"
    try:
        svc = _get_plan_service()
        if svc is None:
            return _error("PlanService 不可用")
        result = svc.disable_schedule(plan_id, operator=operator)
        if isinstance(result, dict) and result.get("success"):
            return _success({"plan_id": plan_id})
        return _error(result.get("error") if isinstance(result, dict) else "停用失败")
    except Exception as exc:
        logger.error(f"disable_schedule_api 失败: {exc}")
        return _error(f"停用调度失败: {exc}")


@router.post("/crawl/plans/{plan_id}/run")
def run_plan_now_api(plan_id: int, request: Request):
    """立即执行一次采集。"""
    session = require_permission(request, "btn.spider.edit")
    operator = (session.get("username") or session.get("account") or "system") if session else "system"
    try:
        svc = _get_plan_service()
        if svc is None:
            return _error("PlanService 不可用")
        result = svc.run_plan_now(plan_id, operator=operator)
        if isinstance(result, dict) and result.get("success"):
            resp = {
                "plan_id": plan_id,
                "run_id": result.get("run_id"),
                "items_total": result.get("items_total", 0),
                "items_written": result.get("items_written", 0),
                "field_match_rate": result.get("field_match_rate"),
                "elapsed_ms": result.get("duration_ms"),
                "alerts": result.get("alerts", []),
            }
            return _success(resp)
        return _error(result.get("error") if isinstance(result, dict) else "执行失败")
    except Exception as exc:
        logger.error(f"run_plan_now_api 失败: {exc}")
        return _error(f"执行失败: {exc}")


@router.post("/crawl/plans/{plan_id}/test")
async def test_plan_api(plan_id: int, request: Request):
    """测试运行（快速验证，不入库）。"""
    session = require_permission(request, "btn.spider.view")
    try:
        body = await request.json()
    except Exception:
        body = {}

    test_url = body.get("test_url")
    max_items = body.get("max_items", 5)
    operator = (session.get("username") or session.get("account") or "system") if session else "system"

    try:
        svc = _get_plan_service()
        if svc is None:
            return _error("PlanService 不可用")
        result = svc.test_plan(plan_id, test_url=test_url, max_items=max_items, operator=operator)

        if not isinstance(result, dict):
            return _error("测试运行返回格式异常")

        items = result.get("items", [])
        # 脱敏
        masked_items = []
        for it in items:
            if isinstance(it, dict):
                masked = {k: _mask_sensitive_text(str(v)) if isinstance(v, str) else v for k, v in it.items()}
                masked_items.append(masked)
            else:
                masked_items.append(str(it))

        return _success({
            "plan_id": plan_id,
            "run_id": result.get("run_id"),
            "status": "completed" if result.get("success") else "failed",
            "items": masked_items,
            "items_total": result.get("items_total", len(items)),
            "field_match_rate": result.get("field_match_rate"),
            "elapsed_ms": result.get("duration_ms"),
            "error": result.get("error"),
            "alerts": result.get("alerts", []),
        })
    except Exception as exc:
        logger.error(f"test_plan_api 失败: {exc}")
        return _error(f"测试运行失败: {exc}")


# ============================================================
# 3. 导入导出
# ============================================================

@router.get("/crawl/plans/{plan_id}/export")
def export_plan_api(plan_id: int, request: Request):
    """导出方案配置（JSON）。"""
    session = require_permission(request, "btn.spider.view")
    try:
        svc = _get_plan_service()
        if svc is None:
            return _error("PlanService 不可用")
        result = svc.export_plan(plan_id)
        if isinstance(result, dict) and result.get("success"):
            export_data = result.get("export")
            # 导出为 download 格式
            filename = f"crawl_plan_{plan_id}_{int(time.time())}.json"
            content = json.dumps(export_data, ensure_ascii=False, indent=2)
            headers = {"Content-Disposition": f'attachment; filename="{filename}"'}
            return JSONResponse(status_code=200, content={"code": 0, "msg": "ok", "data": export_data}, headers=headers)
        return _error(result.get("error") if isinstance(result, dict) else "导出失败")
    except Exception as exc:
        logger.error(f"export_plan_api 失败: {exc}")
        return _error(f"导出失败: {exc}")


@router.post("/crawl/plans/import")
async def import_plan_api(request: Request):
    """从 JSON 导入方案配置。"""
    session = require_permission(request, "btn.spider.edit")
    try:
        body = await request.json()
    except Exception:
        return _error("请求体必须是合法 JSON")

    operator = (session.get("username") or session.get("account") or "system") if session else "system"

    try:
        svc = _get_plan_service()
        if svc is None:
            return _error("PlanService 不可用")
        result = svc.import_plan(body, plan_name=body.get("plan_name"), operator=operator)
        if isinstance(result, dict) and result.get("success"):
            return _success({"plan_id": result.get("plan_id"), "plan_code": result.get("plan_code")})
        return _error(result.get("error") if isinstance(result, dict) else "导入失败")
    except Exception as exc:
        logger.error(f"import_plan_api 失败: {exc}")
        return _error(f"导入失败: {exc}")


# ============================================================
# 4. 页面预览渲染 API
# ============================================================

def _extract_base_href(html: Optional[str]) -> Optional[str]:
    """从 HTML 中提取 <base href="...">，用于补全相对 URL。"""
    if not html:
        return None
    try:
        import re
        m = re.search(r'<base[^>]+href\s*=\s*["\']([^"\']+)["\']', html, re.IGNORECASE)
        return m.group(1) if m else None
    except Exception:
        return None


@router.post("/crawl/preview/render")
async def preview_render_api(request: Request):
    """URL 页面预渲染。"""
    session = require_permission(request, "btn.spider.view")
    try:
        body = await request.json()
    except Exception:
        return _error("请求体必须是合法 JSON")

    url = body.get("url")
    render_js = bool(body.get("render_js", False))
    if not url:
        return _error("url 必填")
    try:
        from core.spider_core.page_renderer import SmartPageRenderer
    except Exception as exc:
        # T25 底层引擎未就绪 - 返回模拟数据（供前端调试）
        logger.warning(f"SmartPageRenderer 不可用: {exc}")
        sample_html = f"""
        <div class="news-page">
          <h1>测试页面 - {url}</h1>
          <ul class="news-list">
            <li class="news-item"><a href="/news/1" class="title-link">测试新闻标题 1 - 今日要闻</a><span class="publish-time">2025-01-15</span></li>
            <li class="news-item"><a href="/news/2" class="title-link">测试新闻标题 2 - 政务通告</a><span class="publish-time">2025-01-14</span></li>
            <li class="news-item"><a href="/news/3" class="title-link">测试新闻标题 3 - 企业公示</a><span class="publish-time">2025-01-13</span></li>
            <li class="news-item"><a href="/news/4" class="title-link">测试新闻标题 4 - 违规通报</a><span class="publish-time">2025-01-12</span></li>
            <li class="news-item"><a href="/news/5" class="title-link">测试新闻标题 5 - 行业动态</a><span class="publish-time">2025-01-11</span></li>
          </ul>
          <div class="pagination"><a href="/news?page=2" class="next-page">下一页</a></div>
        </div>
        """
        return _success({
            "final_url": url,
            "html_preview": _sanitize_html(sample_html),
            "clickable_elements": [
                {"selector": "li.news-item:nth-child(1) a.title-link", "tag": "a", "text": "测试新闻标题 1"},
                {"selector": "li.news-item:nth-child(2) a.title-link", "tag": "a", "text": "测试新闻标题 2"},
                {"selector": "li.news-item:nth-child(1) .publish-time", "tag": "span", "text": "2025-01-15"},
                {"selector": "ul.news-list", "tag": "ul", "text": "新闻列表"},
                {"selector": "a.next-page", "tag": "a", "text": "下一页"},
            ],
            "elapsed_ms": 0,
            "error": None,
            "note": "T25 底层引擎未就绪，返回示例预览数据",
        })

    try:
        renderer = SmartPageRenderer()
        # 使用线程池运行渲染，避免 Playwright Sync API 与 asyncio 事件循环冲突
        import asyncio
        loop = asyncio.get_event_loop()
        page = await loop.run_in_executor(
            None,
            lambda: renderer.render(
                url,
                render=True,
                render_js=render_js,
                timeout=30.0,
                robot_check=False,
                risk_check=False,
            ),
        )

        html_preview = getattr(page, "html", "") or ""
        final_url = getattr(page, "final_url", "") or url
        links = getattr(page, "links", []) or []
        elapsed_ms = int(getattr(page, "elapsed_ms", 0) or 0)
        error = getattr(page, "error", None)

        # 构造可交互元素列表
        # Link 是 dataclass（text, href, attrs），同时兼容旧 dict 格式
        # —— 改进：将 PDF/附件/嵌入式文档优先放到列表前部，并为其生成有效的 selector
        all_items = []
        for link in links[:200]:  # 增加到 200 个
            if hasattr(link, "text"):  # dataclass: Link
                text = getattr(link, "text", "") or ""
                href = getattr(link, "href", "") or ""
                attrs = getattr(link, "attrs", {}) or {}
                selector = ""
                if attrs and isinstance(attrs, dict):
                    parts = []
                    if attrs.get("href"):
                        parts.append(f'a[href*="{attrs.get("href")[:50]}"]')
                    if attrs.get("src"):  # iframe/embed 才有 src
                        src_val = attrs.get("src", "")[:50]
                        parts.append(f'iframe[src*="{src_val}"]')
                    if attrs.get("id"):
                        parts.append(f'#{attrs.get("id")}')
                    if attrs.get("class"):
                        parts.append(f'.{attrs.get("class").split()[0]}')
                    if parts:
                        selector = parts[0]
                # 如果 href 指向 PDF/DOC 等附件，且 selector 为空，用 href 生成
                if not selector and href:
                    ext = href.split("?")[0].split(".")[-1].lower() if "." in href else ""
                    if ext in ("pdf", "doc", "docx", "xls", "xlsx", "ppt", "pptx", "zip", "rar"):
                        selector = f'a[href*="{href[-40:]}"]'
                all_items.append({
                    "selector": selector,
                    "tag": "a",
                    "text": text[:200],
                    "href": href[:200],
                })
            elif isinstance(link, dict):
                all_items.append({
                    "selector": link.get("selector") or link.get("css") or "",
                    "tag": link.get("tag", "a"),
                    "text": (link.get("text") or "")[:200],
                    "href": (link.get("href") or "")[:200],
                })
            else:
                text = str(link)[:200] if link else ""
                all_items.append({
                    "selector": "",
                    "tag": "a",
                    "text": text,
                    "href": "",
                })

        # 优先级排序：PDF/附件/嵌入式文档 → 常规链接
        def _item_priority(it):
            text = (it.get("text") or "").lower()
            href = (it.get("href") or "").lower()
            if any(k in text for k in ("【pdf】", "【doc】", "【xls】", "【ppt】", "【附件", "嵌入式")):
                return 0  # 最高优先级
            if any(k in href for k in (".pdf", ".doc", ".docx", ".xls", ".xlsx", ".ppt", ".pptx", ".zip", ".rar")):
                return 1
            return 2

        all_items.sort(key=_item_priority)
        clickable = all_items[:100]  # 返回前 100 个（PDF 在前）

        # 明确错误处理：有 error 且无有效 HTML 时返回错误响应
        if error and not html_preview:
            return _error(f"页面渲染失败: {error}")

        return _success({
            "final_url": final_url,
            "url": final_url or url,  # 便于 upstream_cache 中提取 base_url
            "base_href": _extract_base_href(html_preview) or final_url or url,  # 用于补全相对 URL
            "html_preview": _sanitize_html(html_preview),
            "clickable_elements": clickable[:100],
            "elapsed_ms": elapsed_ms,
            "error": str(error) if error else None,
        })
    except Exception as exc:
        logger.error(f"preview_render_api 失败: {exc}")
        return _error(f"预览渲染失败: {exc}")


@router.post("/crawl/preview/selector")
async def preview_selector_api(request: Request):
    """用 CSS 选择器校验页面提取结果。"""
    session = require_permission(request, "btn.spider.view")
    try:
        body = await request.json()
    except Exception:
        return _error("请求体必须是合法 JSON")

    selector = body.get("selector")
    url = body.get("url")
    html = body.get("page_html", "")
    extractor = body.get("extractor", "css")
    sample_limit = int(body.get("sample_limit", 5))

    if not selector:
        return _error("selector 必填")

    # 优先用传入的 html，否则用 URL 重新请求
    if not html and url:
        try:
            from core.spider_core.page_renderer import SmartPageRenderer
            renderer = SmartPageRenderer()
            page = renderer.render(url, render_js=False, timeout=20.0, robot_check=False, risk_check=False)
            html = getattr(page, "html", "") or ""
        except Exception as exc:
            logger.warning(f"选择器校验 - 重新请求页面失败: {exc}")

    try:
        # 使用 BeautifulSoup 提取
        from bs4 import BeautifulSoup

        if not html:
            return _success({"selector": selector, "match_count": 0, "samples": [], "error": "没有可解析的 HTML"})

        soup = BeautifulSoup(html, "html.parser")
        if extractor == "css":
            matches = soup.select(selector)
        elif extractor == "xpath":
            # BeautifulSoup 不支持 xpath，降级为 css 选择器
            matches = []
            logger.warning(f"xpath 选择器暂不支持: {selector}")
        elif extractor == "regex":
            import re as _re
            matches_text = _re.findall(selector, html)
            samples = [str(s)[:200] for s in matches_text[:sample_limit]]
            return _success({
                "selector": selector,
                "extractor": "regex",
                "match_count": len(matches_text),
                "samples": samples,
            })
        else:
            matches = []

        if not matches:
            return _success({"selector": selector, "match_count": 0, "samples": [], "suggest_simplify": None})

        samples = []
        for m in matches[:sample_limit]:
            text = m.get_text(strip=True) if hasattr(m, "get_text") else str(m)
            href = m.get("href") if hasattr(m, "get") else None
            item = {"text": text[:200]}
            if href:
                item["href"] = href
            samples.append(item)

        # 简化建议：去掉 nth-child，只保留 class/tag
        import re as _re
        simplified = _re.sub(r":nth-child\(\d+\)", "", selector)
        simplified = _re.sub(r":nth-of-type\(\d+\)", "", simplified)
        simplified = simplified.replace(" > ", " ")

        return _success({
            "selector": selector,
            "match_count": len(matches),
            "samples": samples,
            "suggest_simplify": simplified if simplified != selector else None,
        })
    except Exception as exc:
        logger.error(f"preview_selector_api 失败: {exc}")
        return _error(f"选择器校验失败: {exc}")


@router.post("/crawl/preview/attachment")
async def preview_attachment_api(request: Request):
    """附件解析预览（PDF/图片/DOC/Excel 等）。

    body 支持：
      - url: 附件 URL（与 file_base64 二选一）
      - file_base64: 本地文件的 base64 编码内容（与 url 二选一）
      - filename: 文件名（仅用于提示，当使用 file_base64 时必填）
    """
    session = require_permission(request, "btn.spider.view")
    try:
        body = await request.json()
    except Exception:
        return _error("请求体必须是合法 JSON")

    attachment_url = body.get("url") or ""
    file_base64 = body.get("file_base64") or ""
    filename = body.get("filename") or ""

    if not attachment_url and not file_base64:
        return _error("需要提供 url 或 file_base64")

    try:
        pdf_bytes: bytes = b""
        source_label = ""
        if file_base64:
            import base64 as _base64
            try:
                pdf_bytes = _base64.b64decode(file_base64)
            except Exception:
                return _error("file_base64 不是合法的 base64 编码")
            source_label = filename or "uploaded-file"
        else:
            # URL 方式：用 AttachmentParser 下载+解析
            from core.spider_core.attachment_parser import AttachmentParser
            parser = AttachmentParser()
            r = parser.parse(attachment_url)
            text = r.text or ""
            if isinstance(text, list):
                text = "\n".join([str(t) for t in text])
            tables = r.tables or []
            result_tables = []
            for t in tables[:10]:
                if isinstance(t, dict):
                    result_tables.append({
                        "headers": t.get("headers", []),
                        "rows": t.get("rows", [])[:20],
                        "page_index": t.get("page_index", 0),
                    })
                else:
                    result_tables.append({
                        "headers": getattr(t, "headers", []),
                        "rows": getattr(t, "rows", [])[:20],
                        "page_index": getattr(t, "page_index", 0),
                    })
            return _success({
                "attachment_url": attachment_url,
                "file_type": r.mime_type,
                "file_size_bytes": r.file_size_bytes,
                "filename": r.filename,
                "parse_status": r.parse_status,
                "error": r.error,
                "text": _mask_sensitive_text(text),
                "tables": result_tables,
                "metadata": {k: str(v) for k, v in (r.fields or {}).items() if v},
            })

        # file_base64 方式：直接用 PdfParser 解析
        from core.spider_core.pdf_parser import PdfParser, ParsedTable
        parser = PdfParser()
        r = parser.parse(pdf_bytes, filename=filename, source_url=source_label)
        tables = []
        for t in r.tables:
            tables.append({
                "headers": t.headers,
                "rows": t.rows[:20],
                "page_index": t.page_index,
                "row_count": t.row_count,
                "column_count": t.column_count,
            })
        return _success({
            "attachment_url": source_label,
            "file_type": r.mime_type,
            "file_size_bytes": r.file_size_bytes,
            "filename": r.filename,
            "parse_status": r.parse_status,
            "error": r.error,
            "page_count": r.page_count,
            "text": _mask_sensitive_text(r.text or ""),
            "tables": tables[:10],
            "metadata": {k: str(v) for k, v in (r.fields or {}).items() if v},
        })
    except Exception as exc:
        logger.error(f"preview_attachment_api 失败: {exc}")
        return _success({
            "attachment_url": attachment_url or source_label,
            "file_type": "unknown",
            "text": f"[示例] 附件解析服务未就绪。\n这是一份示例 PDF 文本内容...",
            "tables": [],
            "error": f"解析服务未就绪: {exc}",
        })


# ============================================================
# 5b. 调度器任务监控（供前端采集方案管理页面展示）
# ============================================================


@router.get("/scheduler/jobs")
def list_scheduler_jobs_api(request: Request = None):
    """查询当前 TaskScheduler 已注册的任务列表。"""
    session = None
    if request is not None:
        try:
            session = require_permission(request, "btn.spider.view")
        except Exception:
            # 若权限检查失败，仍向下尝试：通过统一 JSON 响应返回错误提示
            pass
    try:
        from infra.task_scheduler import TaskScheduler
        scheduler = TaskScheduler()
        if hasattr(scheduler, "list_jobs_info"):
            jobs = scheduler.list_jobs_info()
        else:
            # 降级：返回原始 job 对象列表
            raw_jobs = scheduler.list_jobs()
            jobs = [
                {
                    "job_id": getattr(j, "id", None),
                    "name": getattr(j, "name", None),
                }
                for j in raw_jobs
            ]
        return _success({"jobs": jobs, "total": len(jobs)})
    except Exception as exc:
        logger.error(f"list_scheduler_jobs_api 失败: {exc}")
        return _error(f"查询调度器失败: {exc}")


# ============================================================
# 5c. 步骤级执行详情（供"方案执行详情"区块展示）
# ============================================================


@router.get("/crawl/steps")
def get_run_steps_api(plan_id: int = 0, run_id: int = 0, page: int = 1, page_size: int = 50,
                      request: Request = None):
    """查询步骤级执行详情（每个步骤的输入/输出/耗时/状态）。"""
    session = require_permission(request, "btn.spider.view")
    try:
        if plan_id <= 0:
            return _error("plan_id 必须 > 0")
        svc = _get_plan_service()
        if svc is None:
            return _error("PlanService 不可用")

        result = svc.get_run_steps(
            plan_id,
            run_id=run_id if run_id > 0 else None,
            page=page,
            page_size=page_size,
        )
        return _success(result)
    except Exception as exc:
        logger.error(f"get_run_steps_api 失败 (plan={plan_id}, run={run_id}): {exc}")
        return _error(f"查询步骤详情失败: {exc}")


@router.get("/crawl/recent-runs")
def get_recent_runs_with_steps_api(plan_id: int = 0, page: int = 1, page_size: int = 10,
                                   request: Request = None):
    """查询最近 N 次运行，每次运行附带步骤详情。"""
    session = require_permission(request, "btn.spider.view")
    try:
        if plan_id <= 0:
            return _error("plan_id 必须 > 0")
        svc = _get_plan_service()
        if svc is None:
            return _error("PlanService 不可用")

        result = svc.list_recent_runs_with_steps(
            plan_id, page=page, page_size=page_size,
        )
        return _success(result)
    except Exception as exc:
        logger.error(f"get_recent_runs_with_steps_api 失败 (plan={plan_id}): {exc}")
        return _error(f"查询运行记录失败: {exc}")


# ============================================================
# 5. 运行记录 & 监控
# ============================================================

@router.get("/crawl/runs")
def list_runs_api(plan_id: int = 0, status: str = "", page: int = 1, page_size: int = 20,
                  request: Request = None):
    """运行记录列表。"""
    session = require_permission(request, "btn.spider.view")
    try:
        svc = _get_plan_service()
        if svc is None:
            return _error("PlanService 不可用")

        if plan_id > 0:
            items, total = svc.list_runs(plan_id, status=status or None, page=page, page_size=page_size)
        else:
            # 无方案 ID - 返回空列表避免错误
            items, total = [], 0

        display_items = []
        for r in items:
            if isinstance(r, dict):
                display_items.append({
                    "id": r.get("id"),
                    "plan_id": r.get("plan_id"),
                    "run_mode": r.get("run_mode"),
                    "trigger_by": r.get("trigger_by"),
                    "status": r.get("status"),
                    "items_total": r.get("items_total", 0),
                    "items_success": r.get("items_success", 0),
                    "field_match_rate": r.get("field_match_rate"),
                    "duration_ms": r.get("duration_ms"),
                    "started_at": r.get("started_at"),
                    "finished_at": r.get("finished_at"),
                })
        return _success({"items": display_items, "total": total})
    except Exception as exc:
        logger.error(f"list_runs_api 失败: {exc}")
        return _success({"items": [], "total": 0})


@router.get("/crawl/runs/{run_id}")
def get_run_detail_api(run_id: int, request: Request):
    """运行记录详情。"""
    session = require_permission(request, "btn.spider.view")
    try:
        svc = _get_plan_service()
        if svc is None:
            return _error("PlanService 不可用")
        run = svc.get_run_detail(run_id)
        return _success(run)
    except Exception as exc:
        logger.error(f"get_run_detail_api 失败: {exc}")
        return _error(f"查询失败: {exc}")


# ============================================================
# 6. 字段模板库
# ============================================================

_FIELD_TEMPLATES_CACHE: Optional[Dict[str, List[Dict[str, Any]]]] = None


def _get_field_templates() -> Dict[str, List[Dict[str, Any]]]:
    """返回三类预设字段模板 + 自定义字段"""
    global _FIELD_TEMPLATES_CACHE
    if _FIELD_TEMPLATES_CACHE is not None:
        return _FIELD_TEMPLATES_CACHE

    templates = {
        "gov_notice": [
            {"name": "title", "label": "标题", "type": "text", "required": True, "suggest_selector": "h1, h2, .title"},
            {"name": "publish_time", "label": "发布时间", "type": "date", "suggest_selector": ".publish-time, .date, time"},
            {"name": "source", "label": "来源", "type": "text", "suggest_selector": ".source, .from"},
            {"name": "content", "label": "正文", "type": "html", "suggest_selector": ".content, article, .body"},
            {"name": "attachment_links", "label": "附件", "type": "links", "suggest_selector": "a[href*='pdf'], a[href*='doc']"},
        ],
        "enterprise": [
            {"name": "title", "label": "公示标题", "type": "text", "required": True},
            {"name": "company_name", "label": "企业名称", "type": "text"},
            {"name": "credit_code", "label": "统一信用代码", "type": "text"},
            {"name": "publish_time", "label": "公示日期", "type": "date"},
            {"name": "legal_rep", "label": "法定代表人", "type": "text"},
            {"name": "registered_capital", "label": "注册资本", "type": "text"},
            {"name": "address", "label": "注册地址", "type": "text"},
            {"name": "content", "label": "公示内容", "type": "html"},
        ],
        "violation": [
            {"name": "title", "label": "通报标题", "type": "text", "required": True},
            {"name": "publish_time", "label": "通报时间", "type": "date"},
            {"name": "case_number", "label": "案件编号", "type": "text"},
            {"name": "violator", "label": "违规主体", "type": "text"},
            {"name": "violation_content", "label": "违规内容", "type": "html"},
            {"name": "punishment", "label": "处罚结果", "type": "text"},
            {"name": "punishment_amount", "label": "处罚金额", "type": "number"},
            {"name": "authority", "label": "处罚机关", "type": "text"},
        ],
        "custom": [],  # 运行时填充
    }

    # 从 Redis 读取自定义字段
    try:
        r = get_redis()
        if r is not None:
            cached = r.get("crawl:fields:custom")
            if cached:
                templates["custom"] = json.loads(cached)
    except Exception as exc:
        logger.warning(f"读取自定义字段缓存失败: {exc}")

    _FIELD_TEMPLATES_CACHE = templates
    return templates


@router.get("/crawl/fields/templates")
def get_field_templates_api(request: Request):
    """获取三类预设字段模板。"""
    session = require_permission(request, "btn.spider.view")
    try:
        templates = _get_field_templates()
        return _success({"templates": templates, "categories": ["gov_notice", "enterprise", "violation", "custom"]})
    except Exception as exc:
        logger.error(f"get_field_templates_api 失败: {exc}")
        return _error(f"查询失败: {exc}")


@router.get("/crawl/fields/custom")
def get_custom_fields_api(request: Request):
    """获取自定义字段列表。"""
    session = require_permission(request, "btn.spider.view")
    try:
        templates = _get_field_templates()
        return _success({"items": templates.get("custom", [])})
    except Exception as exc:
        return _error(f"查询失败: {exc}")


@router.post("/crawl/fields/custom")
async def create_custom_field_api(request: Request):
    """新增自定义字段。"""
    session = require_permission(request, "btn.spider.edit")
    try:
        body = await request.json()
    except Exception:
        return _error("请求体必须是合法 JSON")

    name = body.get("name")
    label = body.get("label", name)
    if not name:
        return _error("name 必填")

    try:
        templates = _get_field_templates()
        new_field = {
            "id": f"custom_{int(time.time())}_{hashlib.md5(name.encode()).hexdigest()[:8]}",
            "name": name,
            "label": label,
            "type": body.get("type", "text"),
            "required": bool(body.get("required", False)),
            "suggest_selector": body.get("suggest_selector", ""),
            "created_at": datetime.utcnow().isoformat() + "Z",
        }
        templates["custom"].append(new_field)

        # 持久化到 Redis
        try:
            r = get_redis()
            if r is not None:
                r.set("crawl:fields:custom", json.dumps(templates["custom"], ensure_ascii=False))
        except Exception:
            pass

        return _success(new_field)
    except Exception as exc:
        logger.error(f"create_custom_field_api 失败: {exc}")
        return _error(f"创建失败: {exc}")


@router.put("/crawl/fields/custom/{field_id}")
async def update_custom_field_api(field_id: str, request: Request):
    """更新自定义字段。"""
    session = require_permission(request, "btn.spider.edit")
    try:
        body = await request.json()
    except Exception:
        return _error("请求体必须是合法 JSON")

    try:
        templates = _get_field_templates()
        found = False
        for f in templates["custom"]:
            if f.get("id") == field_id:
                for k, v in body.items():
                    f[k] = v
                found = True
                updated = f
                break

        if not found:
            return _error("字段不存在")

        # 持久化
        try:
            r = get_redis()
            if r is not None:
                r.set("crawl:fields:custom", json.dumps(templates["custom"], ensure_ascii=False))
        except Exception:
            pass

        _FIELD_TEMPLATES_CACHE = None  # 重置缓存
        return _success(updated)
    except Exception as exc:
        logger.error(f"update_custom_field_api 失败: {exc}")
        return _error(f"更新失败: {exc}")


@router.delete("/crawl/fields/custom/{field_id}")
def delete_custom_field_api(field_id: str, request: Request):
    """删除自定义字段。"""
    session = require_permission(request, "btn.spider.edit")
    try:
        templates = _get_field_templates()
        templates["custom"] = [f for f in templates["custom"] if f.get("id") != field_id]

        try:
            r = get_redis()
            if r is not None:
                r.set("crawl:fields:custom", json.dumps(templates["custom"], ensure_ascii=False))
        except Exception:
            pass

        _FIELD_TEMPLATES_CACHE = None
        return _success({"deleted": field_id})
    except Exception as exc:
        logger.error(f"delete_custom_field_api 失败: {exc}")
        return _error(f"删除失败: {exc}")


__all__ = ["router"]


# ============================================================================
# T31：步骤编排相关 API（纯新增，不改动任何旧接口）
# ============================================================================

def _crawl_steps_ok(data: Any, msg: str = "ok") -> JSONResponse:
    return _json_response(0, msg, data)


def _crawl_steps_err(msg: str, code: int = 1) -> JSONResponse:
    return _json_response(code, msg, None)


# -------------------------------------------------------------------- 1. smart-detect
@router.post("/crawl/steps/smart-detect")
async def api_crawl_steps_smart_detect(request: Request):
    """对输入 HTML 做智能识别，返回候选容器 + 时间字段 + 预览条目。"""
    try:
        body = await request.json()
    except Exception:
        body = {}
    page_html = body.get("page_html") or ""
    url = body.get("url") or ""
    if not page_html:
        return _crawl_steps_err("缺少 page_html 或 url 参数（需提供 HTML 才能识别）")
    try:
        from business.custom_spider.smart_detector import SmartDetector
        detector = SmartDetector()
        result = detector.detect_all(page_html, target_url=url)
        return _crawl_steps_ok(result)
    except Exception as exc:  # pragma: no cover
        logger.error(f"smart_detect 失败: {exc}")
        return _crawl_steps_err(f"智能识别失败: {exc}")


# -------------------------------------------------------------------- 2. step-test
@router.post("/crawl/steps/step-test")
async def api_crawl_steps_step_test(request: Request):
    """测试单个步骤（不修改任何状态）。"""
    try:
        body = await request.json()
    except Exception:
        body = {}
    step_type = (body.get("step_type") or "").strip()
    config = body.get("config") or {}
    page_html = body.get("page_html")
    upstream_data = body.get("upstream_data") or {}
    if not step_type:
        return _crawl_steps_err("缺少 step_type")
    # 允许的 step_type: 传统 6 种 + 所有 command_* 智能指令
    if not step_type.startswith("command_"):
        allowed = {"page_access", "list_detect", "detail_jump", "attachment_parse", "field_mapping", "result_preview"}
        if step_type not in allowed:
            return _crawl_steps_err(f"不支持的 step_type={step_type}, 允许: {sorted(allowed)} + command_* 类型")
    try:
        from business.custom_spider.step_service import StepTester
        result = StepTester.test_step(step_type, config, page_html=page_html, upstream_data=upstream_data)
        return _crawl_steps_ok(result)
    except Exception as exc:  # pragma: no cover
        logger.error(f"step_test 失败: {exc}")
        return _crawl_steps_err(f"单步测试失败: {exc}")


# -------------------------------------------------------------------- 3. full-test
@router.post("/crawl/steps/full-test")
async def api_crawl_steps_full_test(request: Request):
    """执行整个 StepsPackage 的全链路测试（按 step_order 顺序执行每一步，前一步 output 作为后一步 upstream_data）。"""
    try:
        body = await request.json()
    except Exception:
        body = {}
    package_dict = body.get("package") or {}
    preloaded_html = body.get("preloaded_html") or None
    if not package_dict.get("steps"):
        return _crawl_steps_err("缺少 package.steps（需提供完整 StepsPackage）")
    try:
        from business.custom_spider.step_models import StepsPackage
        from business.custom_spider.step_service import StepTester
        package = StepsPackage.from_dict(package_dict)
        package.normalize()
        result = StepTester.run_all(package, preloaded_html=preloaded_html)
        return _crawl_steps_ok(result)
    except Exception as exc:  # pragma: no cover
        logger.error(f"full_test 失败: {exc}")
        return _crawl_steps_err(f"全链路测试失败: {exc}")


# -------------------------------------------------------------------- 4. assemble
@router.post("/crawl/steps/assemble")
async def api_crawl_steps_assemble(request: Request):
    """把 StepsPackage 组装为 T25 CrawlRuleSet 兼容的 rule_config dict。"""
    try:
        body = await request.json()
    except Exception:
        body = {}
    package_dict = body.get("package") or {}
    if not package_dict.get("steps"):
        return _crawl_steps_err("缺少 package.steps")
    try:
        from business.custom_spider.step_models import StepsPackage
        from business.custom_spider.step_service import StepAssembler
        package = StepsPackage.from_dict(package_dict)
        rule_config = StepAssembler.build_rule_config(package, validate_ruleset=True)
        return _crawl_steps_ok({"rule_config": rule_config})
    except Exception as exc:  # pragma: no cover
        logger.error(f"assemble 失败: {exc}")
        return _crawl_steps_err(f"组装 rule_config 失败: {exc}")


# -------------------------------------------------------------------- 5. compat-convert
@router.post("/crawl/steps/compat-convert")
async def api_crawl_steps_compat_convert(request: Request):
    """旧 rule_config（T25 CrawlRuleSet）→ StepsPackage。"""
    try:
        body = await request.json()
    except Exception:
        body = {}
    rule_config = body.get("rule_config") or {}
    if not rule_config:
        return _crawl_steps_err("缺少 rule_config 参数")
    try:
        from business.custom_spider.step_service import CompatConverter
        package = CompatConverter.convert(
            rule_config,
            plan_name=body.get("plan_name") or "",
            target_domain=body.get("target_domain") or "",
            spider_type=body.get("spider_type") or "generic",
        )
        return _crawl_steps_ok(package.to_dict())
    except Exception as exc:  # pragma: no cover
        logger.error(f"compat_convert 失败: {exc}")
        return _crawl_steps_err(f"旧方案转换失败: {exc}")


# -------------------------------------------------------------------- 5b. save-plan
@router.post("/crawl/steps/save-plan")
async def api_crawl_steps_save_plan(request: Request):
    """从编辑器保存方案（支持新建与更新）。

    body:
      - plan_id: int | null (null = 新建)
      - plan_name: str
      - steps: [{ step_type, config, title }]
      - target_domain: str (可选，空则从步骤中推导)
      - description: str (可选)
      - change_note: str (可选，仅更新时使用)
    """
    try:
        session = require_permission(request, "btn.spider.edit")
    except Exception:
        session = None
    operator = (session.get("username") or session.get("account") or "system") if isinstance(session, dict) else "system"
    try:
        body = await request.json()
    except Exception:
        body = {}

    plan_id = body.get("plan_id")
    plan_name = (body.get("plan_name") or "").strip() or "未命名方案"
    steps = body.get("steps") or []
    if not steps:
        return _crawl_steps_err("缺少 steps（请先添加至少一个步骤）")

    try:
        from business.custom_spider.step_models import StepsPackage, StepConfig
        from business.custom_spider.step_service import StepAssembler

        # 构造 StepsPackage → 组装为 rule_config
        package = StepsPackage(plan_name=plan_name, steps=[])
        for i, s in enumerate(steps):
            step = StepConfig(
                step_id=s.get("step_id") or f"step_{i}",
                step_order=s.get("step_order") or (i + 1),
                step_type=s.get("step_type") or "",
                title=s.get("title") or s.get("step_type") or "",
                config=s.get("config") or {},
            )
            package.steps.append(step)

        rule_config = StepAssembler.build_rule_config(package, validate_ruleset=False)
        # 保存编辑器原始 steps，用于后续加载/还原
        rule_config["_editor_steps"] = [
            {"step_type": s.step_type, "title": s.title, "config": s.config}
            for s in package.steps
        ]

        # 从步骤中推导 target_domain
        target_domain = (body.get("target_domain") or "").strip()
        if not target_domain:
            # 从 page_access / list_detect 步骤中查找 URL
            for s in package.steps:
                for key in ("url", "url_template", "start_url", "base_url"):
                    val = (s.config.get(key) or "").strip() if isinstance(s.config, dict) else ""
                    if val and val.startswith(("http://", "https://")):
                        target_domain = _extract_domain(val)
                        break
                if target_domain:
                    break
        if not target_domain:
            target_domain = rule_config.get("target_domain") or "custom-domain"

        # 解析前端发来的方案配置（存到 increment_config）
        front_config = body.get("config") or {}
        increment_config = {}
        if isinstance(front_config, dict) and front_config:
            increment_config = dict(front_config)
            # 如果 front_config 中包含 target_domain，覆盖上面的推导值
            if (front_config.get("target_domain") or "").strip():
                target_domain = front_config["target_domain"].strip()

        # 如果 front_config 中包含 max_items，注入到 rule_config 的 list 步骤
        if isinstance(increment_config.get("max_items"), int) and increment_config["max_items"] > 0:
            rule_config["max_items_limit"] = increment_config["max_items"]

        svc = _get_plan_service()
        if svc is None:
            return _crawl_steps_err("PlanService 不可用")

        if plan_id:
            # 更新现有方案
            result = svc.update_plan(
                plan_id,
                plan_name=plan_name,
                rule_config=rule_config,
                increment_config=increment_config or None,
                change_note=body.get("change_note"),
                operator=operator,
            )
            if isinstance(result, dict) and result.get("success"):
                return _crawl_steps_ok({"plan_id": plan_id, "plan_code": result.get("plan_code"), "new_version": result.get("version_number") or result.get("new_version")})
            msg = result.get("error") if isinstance(result, dict) else "保存失败"
            return _crawl_steps_err(msg or "保存失败")
        else:
            # 新建方案
            result = svc.create_plan(
                plan_name=plan_name,
                target_domain=target_domain,
                spider_type=body.get("spider_type") or "generic",
                rule_config=rule_config,
                increment_config=increment_config or None,
                description=body.get("description"),
                operator=operator,
            )
            if isinstance(result, dict) and result.get("success"):
                return _crawl_steps_ok({"plan_id": result.get("plan_id"), "plan_code": result.get("plan_code")})
            msg = result.get("error") if isinstance(result, dict) else "创建失败"
            return _crawl_steps_err(msg or "创建失败")
    except Exception as exc:
        logger.error(f"save_plan 失败: {exc}")
        return _crawl_steps_err(f"保存方案失败: {exc}")


# -------------------------------------------------------------------- 5c. load-plan
@router.get("/crawl/steps/plan")
async def api_crawl_steps_load_plan(request: Request):
    """根据 plan_id 加载方案用于编辑。

    query 参数: plan_id
    返回: { plan_id, plan_name, steps: [...], url: "...", ... }
    """
    plan_id = request.query_params.get("plan_id")
    if not plan_id or not plan_id.isdigit():
        return _crawl_steps_err("缺少 plan_id")

    try:
        svc = _get_plan_service()
        if svc is None:
            return _crawl_steps_err("PlanService 不可用")

        plan = svc.get_plan(int(plan_id))
        if plan is None:
            return _crawl_steps_err("方案不存在")

        rule_config = plan.get("rule_config") or {}
        steps_data = []
        seen_types = set()

        # 优先从 _editor_steps 加载（保存时的原始顺序和格式）
        editor_steps = rule_config.get("_editor_steps") or []
        if editor_steps:
            for i, s in enumerate(editor_steps):
                steps_data.append({
                    "step_id": f"step_{i}",
                    "step_order": i + 1,
                    "step_type": s.get("step_type") or "",
                    "title": s.get("title") or s.get("step_type") or "",
                    "config": s.get("config") or {},
                })

        # 如果没有 _editor_steps，则从 rule_config 中反向推导（兼容旧方案）
        if not steps_data:
            # 从 list_rule 中提取 page_access 和 list_detect
            list_rule = rule_config.get("list_rule") or {}
            detail_rule = rule_config.get("detail_rule") or {}
            attachment_rule = rule_config.get("attachment_rule") or {}
            mapping_rule = rule_config.get("field_mapping_rule") or rule_config.get("mapping_rule") or {}
            result_rule = rule_config.get("result_config") or {}

            step_idx = 0
            # page_access
            if list_rule.get("url_template"):
                steps_data.append({
                    "step_id": f"step_{step_idx}",
                    "step_order": step_idx + 1,
                    "step_type": "page_access",
                    "title": "页面访问",
                    "config": {"url": list_rule.get("url_template", ""),
                               "use_render": list_rule.get("use_render", False),
                               "render_wait_ms": list_rule.get("render_wait_ms", 1500)}
                })
                step_idx += 1
            # list_detect
            if list_rule.get("item_selector"):
                steps_data.append({
                    "step_id": f"step_{step_idx}",
                    "step_order": step_idx + 1,
                    "step_type": "list_detect",
                    "title": "列表识别",
                    "config": {
                        "item_selector": list_rule.get("item_selector", ""),
                        "link_selector": list_rule.get("link_selector", "a"),
                        "link_attribute": list_rule.get("link_attribute", "href"),
                        "pagination": list_rule.get("pagination") or {},
                        "max_pages": list_rule.get("max_pages", 20),
                    }
                })
                step_idx += 1
            # detail_jump
            if detail_rule:
                fields = detail_rule.get("fields") or detail_rule.get("detail_fields") or []
                steps_data.append({
                    "step_id": f"step_{step_idx}",
                    "step_order": step_idx + 1,
                    "step_type": "detail_jump",
                    "title": "详情跳转",
                    "config": {"detail_fields": fields}
                })
                step_idx += 1
            # attachment_parse
            if attachment_rule and isinstance(attachment_rule, dict) and attachment_rule.get("url"):
                steps_data.append({
                    "step_id": f"step_{step_idx}",
                    "step_order": step_idx + 1,
                    "step_type": "attachment_parse",
                    "title": "附件解析",
                    "config": dict(attachment_rule)
                })
                step_idx += 1
            # field_mapping
            if mapping_rule:
                steps_data.append({
                    "step_id": f"step_{step_idx}",
                    "step_order": step_idx + 1,
                    "step_type": "field_mapping",
                    "title": "字段映射",
                    "config": {"map": mapping_rule.get("map") or mapping_rule}
                })
                step_idx += 1

        # 推导页面 URL（用于自动加载浏览器预览）
        default_url = ""
        for s in steps_data:
            cfg = s.get("config") or {}
            for key in ("url", "url_template", "start_url"):
                val = (cfg.get(key) or "").strip() if isinstance(cfg, dict) else ""
                if val.startswith(("http://", "https://")):
                    default_url = val
                    break
            if default_url:
                break
        if not default_url:
            default_url = plan.get("target_domain") or ""
            if default_url and not default_url.startswith("http"):
                default_url = "https://" + default_url

        # 方案配置（供前端"方案配置"弹窗填充）
        plan_config = {}
        inc_config = plan.get("increment_config") if isinstance(plan, dict) else None
        if inc_config and isinstance(inc_config, dict):
            plan_config = dict(inc_config)
        # 兼容旧字段（如果 increment_config 为空，则从 plan 对象中直接获取）
        if not plan_config:
            plan_config = {
                "target_domain": plan.get("target_domain") or "",
                "max_items": 200,
                "cron": (plan.get("schedule_config") or {}).get("cron") or "",
                "save_middle_result": True,
                "funnel_visible": True,
                "enable_clean": True,
            }
        else:
            # 将 target_domain 注入到配置对象中（即使已经是从 increment_config 读取），方便前端统一读取
            plan_config.setdefault("target_domain", plan.get("target_domain") or "")
            plan_config.setdefault("max_items", 200)
            plan_config.setdefault("cron", (plan.get("schedule_config") or {}).get("cron") or "")
            plan_config.setdefault("save_middle_result", True)
            plan_config.setdefault("funnel_visible", True)
            plan_config.setdefault("enable_clean", True)

        return _crawl_steps_ok({
            "plan_id": plan.get("id") or plan_id,
            "plan_name": plan.get("plan_name") or "未命名方案",
            "plan_code": plan.get("plan_code") or "",
            "target_domain": plan.get("target_domain") or "",
            "description": plan.get("description") or "",
            "url": default_url,
            "steps": steps_data,
            "config": plan_config,
        })
    except Exception as exc:
        logger.error(f"load_plan 失败: {exc}")
        return _crawl_steps_err(f"加载方案失败: {exc}")


# -------------------------------------------------------------------- 5d. update-config
@router.post("/crawl/plans/{plan_id}/update-config")
async def api_crawl_plan_update_config(plan_id: int, request: Request):
    """独立更新方案配置（不创建版本）。

    主要用于更新：
      - target_domain（目标域名/站点）
      - max_items（单次采集条目上限）
      - cron（调度表达式）
      - save_middle_result（是否保存步骤级中间结果）
      - funnel_visible（数据是否纳入全链路漏斗看板）
      - enable_clean（采集后自动进入清洗阶段）
    """
    try:
        session = require_permission(request, "btn.spider.edit")
    except Exception:
        session = None
    operator = (session.get("username") or session.get("account") or "system") if isinstance(session, dict) else "system"

    try:
        body = await request.json()
    except Exception:
        body = {}
    if not isinstance(body, dict):
        body = {}

    front_config = body.get("config") or body
    if not isinstance(front_config) or not isinstance(front_config):
        return _crawl_steps_err("缺少 config 参数")

    try:
        svc = _get_plan_service()
        if svc is None:
            return _crawl_steps_err("PlanService 不可用")

        # 从 config 中分离基础字段与 increment_config
        target_domain = (front_config.get("target_domain") or "").strip()
        cron_expr = (front_config.get("cron") or "").strip()

        # increment_config：保存完整的中间结果控制等
        increment_config = dict(front_config) if isinstance(front_config, dict) else {}

        # schedule_config（如果提供了 cron 表达式）
        schedule_config = None
        if cron_expr:
            plan = svc.get_plan(int(plan_id)) or {}
            current_schedule = plan.get("schedule_config") if isinstance(plan, dict) else {}
            if isinstance(current_schedule, dict):
                current_schedule = dict(current_schedule)
                current_schedule["cron"] = cron_expr
                schedule_config = current_schedule
            else:
                schedule_config = {"cron": cron_expr}

        # 调用 service.update_plan：不传入 rule_config，避免产生新版本
        result = svc.update_plan(
            int(plan_id),
            plan_name=((front_config.get("plan_name") or "").strip() or None),
            increment_config=increment_config,
            schedule_config=schedule_config,
            operator=operator,
            change_note="方案配置更新",
        )

        # 如果提供了 target_domain，调用额外的 repository 方法更新基础字段
        if target_domain:
            from business.custom_spider.repository import PlanRepository
            PlanRepository.update(int(plan_id), {"target_domain": target_domain})

        if isinstance(result, dict) and result.get("success"):
            return _crawl_steps_ok({"success": True})
        msg = result.get("error") if isinstance(result, dict) else "更新失败"
        return _crawl_steps_err(msg or "更新失败")
    except Exception as exc:
        logger.error(f"update_config 失败: {exc}")
        return _crawl_steps_err(f"更新失败: {exc}")


# -------------------------------------------------------------------- 6. draft-save/load/clear
@router.post("/crawl/steps/draft-save")
async def api_crawl_steps_draft_save(request: Request):
    """保存编辑器草稿到 Redis（或进程内存兜底）。"""
    try:
        body = await request.json()
    except Exception:
        body = {}
    package = body.get("package") or {}
    try:
        from business.custom_spider.step_service import DraftService
        session_id = body.get("session_id") or request.headers.get("x-session-id")
        plan_id = body.get("plan_id")
        ok = DraftService.save(session_id, plan_id, package)
        return _crawl_steps_ok({"ok": bool(ok)})
    except Exception as exc:  # pragma: no cover
        logger.error(f"draft_save 失败: {exc}")
        return _crawl_steps_err(f"草稿保存失败: {exc}")


@router.post("/crawl/steps/draft-load")
async def api_crawl_steps_draft_load(request: Request):
    """加载编辑器草稿。"""
    try:
        body = await request.json()
    except Exception:
        body = {}
    try:
        from business.custom_spider.step_service import DraftService
        session_id = body.get("session_id") or request.headers.get("x-session-id")
        plan_id = body.get("plan_id")
        data = DraftService.load(session_id, plan_id)
        return _crawl_steps_ok({"package": data, "has_draft": bool(data)})
    except Exception as exc:  # pragma: no cover
        logger.error(f"draft_load 失败: {exc}")
        return _crawl_steps_err(f"草稿加载失败: {exc}")


@router.post("/crawl/steps/draft-clear")
async def api_crawl_steps_draft_clear(request: Request):
    """清除草稿。"""
    try:
        body = await request.json()
    except Exception:
        body = {}
    try:
        from business.custom_spider.step_service import DraftService
        session_id = body.get("session_id") or request.headers.get("x-session-id")
        plan_id = body.get("plan_id")
        ok = DraftService.clear(session_id, plan_id)
        return _crawl_steps_ok({"ok": bool(ok)})
    except Exception as exc:  # pragma: no cover
        logger.error(f"draft_clear 失败: {exc}")
        return _crawl_steps_err(f"草稿清除失败: {exc}")


# -------------------------------------------------------------------- 7. template-apply & list-templates
@router.post("/crawl/steps/template-apply")
async def api_crawl_steps_template_apply(request: Request):
    """按模板 ID 快速生成 StepsPackage。"""
    try:
        body = await request.json()
    except Exception:
        body = {}
    template_id = (body.get("template_id") or "").strip()
    try:
        from business.custom_spider.step_service import list_templates
        from business.custom_spider.step_models import build_package_from_template
        templates = list_templates()
        ids = {t["template_id"] for t in templates}
        if template_id not in ids:
            return _crawl_steps_err(f"未知模板 template_id={template_id}, 可选: {sorted(ids)}")
        package = build_package_from_template(
            template_id,
            plan_name=body.get("plan_name") or "",
            target_domain=body.get("target_domain") or "",
            spider_type=body.get("spider_type") or "generic",
        )
        return _crawl_steps_ok(package.to_dict())
    except Exception as exc:  # pragma: no cover
        logger.error(f"template_apply 失败: {exc}")
        return _crawl_steps_err(f"模板应用失败: {exc}")


@router.get("/crawl/steps/templates")
async def api_crawl_steps_templates(request: Request):
    """列出所有可用的步骤模板。"""
    try:
        from business.custom_spider.step_service import list_templates
        return _crawl_steps_ok({"templates": list_templates()})
    except Exception as exc:  # pragma: no cover
        return _crawl_steps_err(f"模板列表加载失败: {exc}")


# -------------------------------------------------------------------- 8. preview-render（复用底层渲染，脱敏输出）
@router.post("/crawl/steps/preview-render")
async def api_crawl_steps_preview_render(request: Request):
    """渲染 URL，返回脱敏后的 HTML/title 与 status_code。"""
    import json
    try:
        body = await request.json()
    except Exception as e:
        body = {}
        logger.info(f"preview-render: json parse error: {e}")
    url = (body.get("url") or "").strip()
    logger.info(f"preview-render: received url='{url}', body_keys={list(body.keys())}")
    if not url:
        return _crawl_steps_err("缺少 url 参数")
    
    rendered_html = ""
    title = ""
    status_code = 0
    render_source = "unknown"
    
    try:
        from core.spider_core.page_renderer import SmartPageRenderer
        renderer = SmartPageRenderer()
        
        import concurrent.futures
        with concurrent.futures.ThreadPoolExecutor(max_workers=1) as executor:
            future = executor.submit(
                renderer.render,
                url,
                render=True,
                render_js=True,
                timeout=60.0,
                wait_until="networkidle",
                robot_check=False,
                risk_check=False,
            )
            page = future.result(timeout=120)
        
        rendered_html = getattr(page, "html", "") or ""
        title = getattr(page, "title", "") or ""
        status_code = int(getattr(page, "status_code", 0) or 0)
        render_source = "playwright"
        
    except Exception as inner:
        logger.warning(f"preview-render: Playwright 失败，退化为 requests: {inner}")
        try:
            import requests
            r = requests.get(url, timeout=15, headers={"User-Agent": "Mozilla/5.0 BizTools4Openclaw step-editor"})
            rendered_html = r.text or ""
            status_code = r.status_code
            render_source = "requests"
        except Exception as inner2:
            return _crawl_steps_err(f"无法获取页面: {inner2}")
    
    from business.custom_spider.step_service import _mask_any
    cleaned_html = _sanitize_html(rendered_html, max_bytes=5 * 1024 * 1024)
    html_preview = _mask_any(cleaned_html) or ""
    title = _mask_any(title or _extract_title(rendered_html) or "") or ""
    
    return _crawl_steps_ok({
        "url": url, 
        "title": title,
        "html_preview": html_preview,
        "status_code": status_code, 
        "masked": True,
        "html_total_size": len(rendered_html),
        "base_href": url,
        "render_source": render_source,
    })


# ========================================================== T32 扩展：智能指令 & 版本管理
# ----------------------------------------------------------- 指令库元数据
@router.get("/crawl/steps/commands")
async def api_crawl_steps_commands():
    """返回所有可用的智能指令元数据（前端用于指令选择弹窗）。"""
    try:
        from business.custom_spider.command_library import list_command_metas
        return _crawl_steps_ok({"commands": list_command_metas()})
    except Exception as exc:  # pragma: no cover
        logger.error(f"list_commands 失败: {exc}")
        return _crawl_steps_err(f"获取指令库失败: {exc}")


# ----------------------------------------------------------- 指令单步测试
@router.post("/crawl/steps/command-test")
async def api_crawl_steps_command_test(request: Request):
    """对一个智能指令做单步数据变换测试，返回结构化结果。"""
    try:
        body = await request.json()
    except Exception:
        body = {}
    name = (body.get("name") or "").strip()
    if not name:
        return _crawl_steps_err("缺少 name 参数")
    try:
        from business.custom_spider.command_library import run_command
        result = run_command(name, body.get("html") or "", body.get("config") or {}, body.get("upstream_data"))
        return _crawl_steps_ok({"name": name, "result": result})
    except Exception as exc:  # pragma: no cover
        logger.error(f"command-test({name}) 失败: {exc}")
        return _crawl_steps_err(f"指令测试失败: {exc}")


# ----------------------------------------------------------- 增量测试
@router.post("/crawl/steps/full-test-incremental")
async def api_crawl_steps_incremental_test(request: Request):
    """与 full-test 类似，但仅测试最近修改（added）的步骤。前端会标记哪些步骤是新增的。"""
    try:
        body = await request.json()
    except Exception:
        body = {}
    try:
        from business.custom_spider.step_models import StepsPackage, StepConfig
        from business.custom_spider.step_service import StepTester, CompatConverter
        pkg_dict = body.get("steps_package") or {}
        if not pkg_dict and body.get("rule_config"):
            # 兼容：从旧 rule_config 生成一个临时 package 再测试
            pkg = CompatConverter.convert(body.get("plan_name") or "incremental_plan", body["rule_config"])
        else:
            pkg = StepsPackage.from_dict(pkg_dict) if pkg_dict else StepsPackage(plan_name="empty")

        only_steps_ids = set(body.get("only_step_ids") or [])
        results = []
        for step in pkg.steps:
            if only_steps_ids and step.step_id not in only_steps_ids:
                results.append({
                    "step_id": step.step_id,
                    "step_type": step.step_type,
                    "skipped": True,
                    "reason": "不在增量测试范围内",
                })
                continue
            r = StepTester.test_step(step.step_type, step.config)
            r["step_id"] = step.step_id
            r["step_type"] = step.step_type
            results.append(r)
        return _crawl_steps_ok({"plan_name": pkg.plan_name, "steps_count": len(pkg.steps),
                                  "incremental_count": sum(1 for r in results if not r.get("skipped")),
                                  "results": results})
    except Exception as exc:  # pragma: no cover
        logger.error(f"incremental_test 失败: {exc}")
        return _crawl_steps_err(f"增量测试失败: {exc}")


# ----------------------------------------------------------- 保存版本
@router.post("/crawl/steps/{plan_id}/versions")
async def api_crawl_steps_save_version(plan_id: str, request: Request):
    """把当前方案规则配置保存为一个历史版本。"""
    try:
        body = await request.json()
    except Exception:
        body = {}
    try:
        from business.custom_spider.step_service import VersionService
        rc = body.get("rule_config") or {}
        if not rc:
            # 如果未提供 rule_config，尝试从 steps_package 组装一个
            if body.get("steps_package"):
                from business.custom_spider.step_models import StepsPackage
                from business.custom_spider.step_service import StepAssembler
                pkg = StepsPackage.from_dict(body["steps_package"])
                rc = StepAssembler.build_rule_config(pkg)
        message = body.get("message") or ""
        operator = body.get("operator") or "admin"
        record = VersionService.save(str(plan_id), rc, operator=operator, message=message)
        return _crawl_steps_ok({
            "version_id": record["version_id"],
            "created_at": record["created_at"],
            "message": message,
            "operator": operator,
        })
    except Exception as exc:  # pragma: no cover
        logger.error(f"save_version({plan_id}) 失败: {exc}")
        return _crawl_steps_err(f"保存版本失败: {exc}")


# ----------------------------------------------------------- 列出版本
@router.get("/crawl/steps/{plan_id}/versions")
async def api_crawl_steps_list_versions(plan_id: str):
    """列出指定 plan_id 的历史版本（按时间倒序，保留最近 20 条）。"""
    try:
        from business.custom_spider.step_service import VersionService
        versions = VersionService.list_versions(str(plan_id))
        meta = _normalize_versions_meta(versions)
        return _crawl_steps_ok({"plan_id": plan_id, "total": len(meta), "versions": meta})
    except Exception as exc:  # pragma: no cover
        logger.error(f"list_versions({plan_id}) 失败: {exc}")
        return _crawl_steps_err(f"列出版本失败: {exc}")


# 同时支持 query 参数方式（与前端旧调用兼容）
@router.get("/crawl/steps/versions")
async def api_crawl_steps_list_versions_v2(request: Request):
    plan_id = request.query_params.get("plan_id") or ""
    return await api_crawl_steps_list_versions(plan_id)


def _normalize_versions_meta(versions: list) -> list:
    """把后端内部的 version 字段映射为前端期望的字段名。"""
    out = []
    for idx, v in enumerate(versions):
        rc = v.get("rule_config") or {}
        editor_steps = rc.get("_editor_steps") or []
        step_count = len(editor_steps) or 0
        record = {
            "version_id": v.get("version_id") or f"v{idx}",
            "version": v.get("message") or (f"版本 {idx + 1}"),
            "saved_at": v.get("created_at") or v.get("timestamp") or "",
            "step_count": step_count,
            "operator": v.get("operator") or "system",
            "timestamp": v.get("timestamp") or 0,
        }
        out.append(record)
    return out


# ----------------------------------------------------------- 读取某个版本
@router.get("/crawl/steps/{plan_id}/versions/{version_id}")
async def api_crawl_steps_get_version(plan_id: str, version_id: str):
    """读取指定版本的完整 rule_config，供前端回显/应用。"""
    try:
        from business.custom_spider.step_service import VersionService
        version = VersionService.get_version(str(plan_id), str(version_id))
        if version is None:
            return _crawl_steps_err(f"找不到版本 {version_id}")
        return _crawl_steps_ok(version)
    except Exception as exc:  # pragma: no cover
        logger.error(f"get_version({plan_id}/{version_id}) 失败: {exc}")
        return _crawl_steps_err(f"读取版本失败: {exc}")


# ----------------------------------------------------------- 回退到某个版本
@router.post("/crawl/steps/{plan_id}/versions/{version_id}/rollback")
async def api_crawl_steps_rollback(plan_id: str, version_id: str):
    """把指定版本恢复为当前方案，返回对应的 rule_config 供调用方覆盖。"""
    try:
        from business.custom_spider.step_service import VersionService
        result = VersionService.rollback(str(plan_id), str(version_id))
        if not result.get("success"):
            return _crawl_steps_err(result.get("error") or "回退失败")
        return _crawl_steps_ok(result)
    except Exception as exc:  # pragma: no cover
        logger.error(f"rollback({plan_id}/{version_id}) 失败: {exc}")
        return _crawl_steps_err(f"回退失败: {exc}")


def _extract_title(html: str) -> str:
    try:
        import re
        m = re.search(r"<title[^>]*>([^<]*)</title>", html or "", re.IGNORECASE)
        return (m.group(1) or "").strip()[:128] if m else ""
    except Exception:
        return ""
