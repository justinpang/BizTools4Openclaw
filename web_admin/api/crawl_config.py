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

from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import JSONResponse

from infra.logger_setup import get_logger
from infra.redis_client import get_redis
from web_admin.auth import require_admin, _admin_session_key

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


def _sanitize_html(html: str, max_bytes: int = 200 * 1024) -> str:
    """安全清理 HTML（剥离 script/iframe/内联事件）"""
    if not html:
        return ""
    # 截断到最大字节
    if len(html) > max_bytes:
        html = html[:max_bytes]

    # 移除 <script>...</script> 块
    import re
    html = re.sub(r"<script[\s>].*?</script>", "", html, flags=re.IGNORECASE | re.DOTALL)
    html = re.sub(r"<script[\s>].*?>", "", html, flags=re.IGNORECASE)
    html = re.sub(r"</script>", "", html, flags=re.IGNORECASE)

    # 移除 <iframe>/<frame>
    html = re.sub(r"<iframe[\s>].*?</iframe>", "", html, flags=re.IGNORECASE | re.DOTALL)
    html = re.sub(r"<iframe[\s>].*?>", "", html, flags=re.IGNORECASE)
    html = re.sub(r"</iframe>", "", html, flags=re.IGNORECASE)
    html = re.sub(r"<frame[\s>].*?</frame>", "", html, flags=re.IGNORECASE | re.DOTALL)
    html = re.sub(r"<frame[\s>].*?>", "", html, flags=re.IGNORECASE)
    html = re.sub(r"</frame>", "", html, flags=re.IGNORECASE)

    # 移除内联事件 onclick/onload/onmouseover 等
    html = re.sub(r'\son[a-z]+\s*=\s*"[^"]*"', "", html, flags=re.IGNORECASE)
    html = re.sub(r"\son[a-z]+\s*=\s*'[^']*'", "", html, flags=re.IGNORECASE)

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
    session: dict = Depends(require_admin),
):
    """采集方案列表（支持按状态/关键词筛选）"""
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
async def create_plan_api(request: Request, session: dict = Depends(require_admin)):
    """创建新方案"""
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
async def update_plan_api(plan_id: int, request: Request, session: dict = Depends(require_admin)):
    """更新方案"""
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
def clone_plan_api(plan_id: int, request: Request, session: dict = Depends(require_admin)):
    """克隆方案"""
    try:
        body = await request.json() if False else {}  # 支持简单的 GET 式请求
        # 简化：直接克隆，新名称自动生成
        pass
    except Exception:
        pass

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
def delete_plan_api(plan_id: int, session: dict = Depends(require_admin)):
    """删除方案（软删除）"""
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
def get_plan_detail_api(plan_id: int, session: dict = Depends(require_admin)):
    """获取方案详情（含规则配置）"""
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
def enable_schedule_api(plan_id: int, session: dict = Depends(require_admin)):
    """启用采集调度"""
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
def disable_schedule_api(plan_id: int, session: dict = Depends(require_admin)):
    """停用采集调度"""
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
def run_plan_now_api(plan_id: int, session: dict = Depends(require_admin)):
    """立即执行一次采集"""
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
async def test_plan_api(plan_id: int, request: Request, session: dict = Depends(require_admin)):
    """测试运行（快速验证，不入库）"""
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
def export_plan_api(plan_id: int, session: dict = Depends(require_admin)):
    """导出方案配置（JSON）"""
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
async def import_plan_api(request: Request, session: dict = Depends(require_admin)):
    """从 JSON 导入方案配置"""
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

@router.post("/crawl/preview/render")
async def preview_render_api(request: Request, session: dict = Depends(require_admin)):
    """URL 页面预渲染"""
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
        page = renderer.render(
            url,
            render_js=render_js,
            timeout=30.0,
            robot_check=False,
            risk_check=False,
        )

        html_preview = getattr(page, "html", "") or ""
        final_url = getattr(page, "final_url", "") or url
        links = getattr(page, "links", []) or []
        elapsed_ms = int(getattr(page, "elapsed_ms", 0) or 0)
        error = getattr(page, "error", None)

        # 构造可交互元素列表（取前 100 个）
        clickable = []
        for link in links[:100]:
            if isinstance(link, dict):
                clickable.append({
                    "selector": link.get("selector") or link.get("css") or "",
                    "tag": link.get("tag", "a"),
                    "text": (link.get("text") or "")[:200],
                })

        return _success({
            "final_url": final_url,
            "html_preview": _sanitize_html(html_preview),
            "clickable_elements": clickable[:100],
            "elapsed_ms": elapsed_ms,
            "error": str(error) if error else None,
        })
    except Exception as exc:
        logger.error(f"preview_render_api 失败: {exc}")
        return _error(f"预览渲染失败: {exc}")


@router.post("/crawl/preview/selector")
async def preview_selector_api(request: Request, session: dict = Depends(require_admin)):
    """用 CSS 选择器校验页面提取结果"""
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
async def preview_attachment_api(request: Request, session: dict = Depends(require_admin)):
    """附件解析预览（PDF/图片）"""
    try:
        body = await request.json()
    except Exception:
        return _error("请求体必须是合法 JSON")

    attachment_url = body.get("url")
    if not attachment_url:
        return _error("url 必填")

    try:
        # 尝试用 T25 AttachmentParser 解析
        from core.spider_core.attachment_parser import AttachmentParser
        parser = AttachmentParser()
        result = parser.parse(attachment_url, timeout=30.0)

        text = getattr(result, "text", "") or ""
        if isinstance(text, list):
            text = "\n".join(text)
        # 只取前 3000 字符作为预览
        preview_text = str(text)[:3000]

        tables = getattr(result, "tables", []) or []
        if not isinstance(tables, list):
            tables = []

        resp = {
            "attachment_url": attachment_url,
            "file_type": getattr(result, "file_type", ""),
            "file_size": getattr(result, "size_kb", 0),
            "text_preview": _mask_sensitive_text(preview_text),
            "tables": [{"rows": t[:5] if isinstance(t, list) else []} for t in tables[:3]],
            "error": getattr(result, "error", None),
        }
        return _success(resp)
    except Exception as exc:
        logger.error(f"preview_attachment_api 失败: {exc}")
        # 返回示例数据
        return _success({
            "attachment_url": attachment_url,
            "file_type": "unknown",
            "text_preview": "[示例] 附件解析服务未就绪。\n这是一份示例 PDF 文本内容...\n表格 1: 名称|数据\n",
            "tables": [],
            "error": f"解析服务未就绪: {exc}",
        })


# ============================================================
# 5. 运行记录 & 监控
# ============================================================

@router.get("/crawl/runs")
def list_runs_api(plan_id: int = 0, status: str = "", page: int = 1, page_size: int = 20,
                   session: dict = Depends(require_admin)):
    """运行记录列表"""
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
def get_run_detail_api(run_id: int, session: dict = Depends(require_admin)):
    """运行记录详情"""
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
def get_field_templates_api(session: dict = Depends(require_admin)):
    """获取三类预设字段模板"""
    try:
        templates = _get_field_templates()
        return _success({"templates": templates, "categories": ["gov_notice", "enterprise", "violation", "custom"]})
    except Exception as exc:
        logger.error(f"get_field_templates_api 失败: {exc}")
        return _error(f"查询失败: {exc}")


@router.get("/crawl/fields/custom")
def get_custom_fields_api(session: dict = Depends(require_admin)):
    """获取自定义字段列表"""
    try:
        templates = _get_field_templates()
        return _success({"items": templates.get("custom", [])})
    except Exception as exc:
        return _error(f"查询失败: {exc}")


@router.post("/crawl/fields/custom")
async def create_custom_field_api(request: Request, session: dict = Depends(require_admin)):
    """新增自定义字段"""
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
async def update_custom_field_api(field_id: str, request: Request, session: dict = Depends(require_admin)):
    """更新自定义字段"""
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
def delete_custom_field_api(field_id: str, session: dict = Depends(require_admin)):
    """删除自定义字段"""
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
