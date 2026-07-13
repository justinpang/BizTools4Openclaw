"""T31: 步骤编排服务。

核心能力
--------
* :class:`StepAssembler`: :class:`StepsPackage` -> T25 :class:`CrawlRuleSet` dict
* :class:`CompatConverter`: 旧 CrawlRuleSet dict -> :class:`StepsPackage`
* :class:`StepTester`: 单步测试 / 全链路测试，复用 T25 parser 底层能力
* :class:`DraftService`: 草稿持久化（Redis，无 Redis 时退化为内存 dict）

注意
----
不直接写数据库。所有 IO 走 T25 引擎或 infra 级别的工具，保持对底层只读。
"""

from __future__ import annotations

import json
import time
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import urlparse

from business.custom_spider.step_models import (
    CRAWL_SCOPE_LABELS, STEP_TYPE_LABELS, STEP_TYPES, STEP_TEMPLATES,
    StepConfig, StepsPackage, build_package_from_template,
)

# ---------------------------------------------------------------------------
# 可选外部依赖（都做缺失容错
# ---------------------------------------------------------------------------
try:
    from core.spider_core.rule_models import CrawlRuleSet
    _HAS_RULESET = True
except Exception:  # pragma: no cover - 依赖缺失时
    CrawlRuleSet = None  # type: ignore
    _HAS_RULESET = False

try:
    from infra.logger_setup import get_logger
    _logger = get_logger("custom_spider.step_service")
    _HAS_LOGGER = True
except Exception:  # pragma: no cover
    import logging as _logging
    _logger = _logging.getLogger("custom_spider.step_service")
    _HAS_LOGGER = False

try:
    from infra.redis_client import get_redis
    _HAS_REDIS = True
except Exception:  # pragma: no cover
    _HAS_REDIS = False


# ============================================================================
# 隐私脱敏（由 step_models 之外，对 step_service 用同一份工具
# ============================================================================
try:
    from core.compliance.pii_mask import mask_text as _mask_text  # type: ignore
except Exception:  # pragma: no cover - 依赖缺失时退化为占位
    import re as _re
    def _mask_text(text: str) -> str:
        if not text:
            return text
        text = _re.sub(r"1[3-9]\d{9}", "1***", text)
        text = _re.sub(r"[\w\.-]+@[\w\.-]+\.\w+", "*@*.*", text)
        return text


def _mask_any(obj: Any) -> Any:
    if obj is None:
        return None
    if isinstance(obj, str):
        return _mask_text(obj)
    if isinstance(obj, dict):
        return {k: _mask_any(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_mask_any(x) for x in obj]
    return obj


# ============================================================================
# StepAssembler: StepsPackage -> rule_config dict
# ============================================================================
class StepAssembler:
    """把 StepsPackage 组装为 T25 CrawlRuleSet 配置字典。"""

    @staticmethod
    def build_rule_config(package: StepsPackage, *,
                          validate_ruleset: bool = True
                          ) -> Dict[str, Any]:
        package.normalize()

        # 第一步：收集 6 种基础类型的步骤 + T32 智能指令步骤
        page_access: Optional[StepConfig] = None
        list_detect: Optional[StepConfig] = None
        detail_jump: Optional[StepConfig] = None
        attachment_parse: Optional[StepConfig] = None
        field_mapping: Optional[StepConfig] = None
        extra_steps: List[Dict[str, Any]] = []
        pagination_override: Optional[Dict[str, Any]] = None

        for step in package.steps:
            if step.step_type == "page_access" and page_access is None:
                page_access = step
            elif step.step_type == "list_detect" and list_detect is None:
                list_detect = step
            elif step.step_type == "detail_jump" and detail_jump is None:
                detail_jump = step
            elif step.step_type == "attachment_parse" and attachment_parse is None:
                attachment_parse = step
            elif step.step_type == "field_mapping" and field_mapping is None:
                field_mapping = step
            elif step.step_type.startswith("command_"):
                if step.step_type == "command_pagination_loop":
                    pagination_override = dict(step.config)
                extra_steps.append({
                    "step_type": step.step_type,
                    "title": step.title,
                    "config": dict(step.config),
                })

        # 构造 rule_config
        package_dict: Dict[str, Any] = {
            "name": package.plan_name or f"plan_{int(time.time())}",
        }

        # list_rule
        if page_access or list_detect:
            _url = ""
            if page_access:
                _url = page_access.config.get("url") or ""
            if not _url and list_detect:
                _url = list_detect.config.get("url_template") or ""

            _item_selector = ""
            _link_selector = "a"
            _link_attribute = "href"
            _pagination: Dict[str, Any] = {}
            _max_pages = 20
            _use_render = False
            if list_detect:
                _item_selector = list_detect.config.get("item_selector") or ""
                _link_selector = list_detect.config.get("link_selector") or "a"
                _link_attribute = list_detect.config.get("link_attribute") or "href"
                _pagination = list_detect.config.get("pagination") or {} or {}
                _max_pages = int(list_detect.config.get("max_pages") or 20)
                _use_render = bool(list_detect.config.get("use_render"))
            if page_access and not _use_render:
                _use_render = bool(page_access.config.get("use_render"))

            if pagination_override:
                _pagination = {
                    "mode": pagination_override.get("mode", "next_button"),
                    "next_selector": pagination_override.get("next_selector", "a.next-page"),
                    "enabled": True,
                }
                _max_pages = int(pagination_override.get("max_pages") or 20)
                _use_render = True

            package_dict["list_rule"] = {
                "url_template": _url,
                "item_selector": _item_selector,
                "link_selector": _link_selector,
                "link_attribute": _link_attribute,
                "pagination": _pagination,
                "max_pages": _max_pages,
                "use_render": _use_render,
                "extra_steps": extra_steps,
            }

        # detail_rule
        if detail_jump:
            fields = []
            for f in detail_jump.config.get("detail_fields", []):
                # 兼容字符串字段名（如 "title"）和完整字典配置
                if isinstance(f, str):
                    fields.append({
                        "name": f,
                        "extractor": "css",
                        "expression": f".{f}",
                        "attribute": None,
                        "required": False,
                        "default_value": None,
                        "cleaners": [],
                        "date_format": None,
                    })
                else:
                    fields.append({
                        "name": f.get("name", ""),
                        "extractor": f.get("extractor", "css"),
                        "expression": f.get("expression", ""),
                        "attribute": f.get("attribute"),
                        "required": bool(f.get("required")),
                        "default_value": f.get("default_value"),
                        "cleaners": list(f.get("cleaners") or []),
                        "date_format": f.get("date_format"),
                    })
            package_dict["detail_rule"] = {
                "url_template": detail_jump.config.get("url_template"),
                "fields": fields,
                "use_render": bool(detail_jump.config.get("use_render", False)),
            }

        # attachment_rules
        if attachment_parse:
            package_dict["attachment_rules"] = [{
                "link_selector": attachment_parse.config.get("link_selector", "a.attachment"),
                "link_attribute": attachment_parse.config.get("link_attribute", "href"),
                "parse_pdf": bool(attachment_parse.config.get("parse_pdf", True)),
                "parse_image": bool(attachment_parse.config.get("parse_image", False)),
                "parse_docx": bool(attachment_parse.config.get("parse_docx", False)),
            }]

        # field_mapping
        if field_mapping:
            package_dict["field_mapping"] = dict(field_mapping.config.get("map", {}) or {})

        # increment_config
        if package.increment_config:
            package_dict["increment_config"] = dict(package.increment_config)

        package_dict["spider_type"] = package.spider_type or "generic"
        if package.schedule_config:
            package_dict["schedule_config"] = dict(package.schedule_config)

        # 关键映射：crawl_scope -> max_items + increment_config
        if list_detect:
            scope = list_detect.config.get("crawl_scope", "latest")
            if scope == "latest":
                # 自动选最新：组装时把 increment_config 带上
                package_dict["max_items"] = int(list_detect.config.get("top_n_count") or 100)
                inc = package_dict.setdefault("increment_config", {})
                inc["crawl_scope"] = "latest"
                inc["take_latest_by_time"] = True
            elif scope == "top_n":
                package_dict["max_items"] = int(list_detect.config.get("top_n_count") or 50)
                package_dict.setdefault("increment_config", {})["crawl_scope"] = "top_n"
            else:  # all
                package_dict["max_items"] = 9999
                package_dict.setdefault("increment_config", {})["crawl_scope"] = "all"
        else:
            package_dict["max_items"] = 100

        # 把原 StepsPackage 也存入，便于后续回传
        package_dict["_steps_package"] = package.to_dict()

        if validate_ruleset:
            warnings = StepAssembler._validate_with_ruleset(package_dict)
            if warnings:
                package_dict["_warnings"] = warnings

        return package_dict

    @staticmethod
    def _validate_with_ruleset(rule_config: Dict[str, Any]) -> List[str]:
        warnings: List[str] = []
        if not _HAS_RULESET:
            warnings.append("CrawlRuleSet 不可用，跳过二次校验")
            return warnings
        try:
            CrawlRuleSet.model_validate(rule_config)
        except Exception as exc:  # noqa: BLE001
            warnings.append(f"CrawlRuleSet 校验失败: {exc}")
        return warnings


# ============================================================================
# CompatConverter: 旧 rule_config -> StepsPackage
# ============================================================================
class CompatConverter:
    """兼容转换器：将旧 CrawlRuleSet JSON 反向转换为 StepsPackage。"""

    @staticmethod
    def convert(rule_config: Dict[str, Any], *, plan_name: str = "",
              target_domain: str = "", spider_type: str = "generic") -> StepsPackage:
        steps: List[StepConfig] = []
        rc = rule_config or {}
        list_rule = rc.get("list_rule") or {}
        detail_rule = rc.get("detail_rule") or {}
        field_mapping = rc.get("field_mapping") or {}
        attachment_rules = rc.get("attachment_rules") or []

        # Step 1: page_access
        url = (
            list_rule.get("url_template")
            or detail_rule.get("url_template")
            or ""
        )
        use_render = bool(list_rule.get("use_render")) or False
        if url:
            steps.append(StepConfig(
                step_id="s_legacy_1",
                step_type="page_access",
                step_order=len(steps) + 1,
                title="访问列表页",
                config={
                    "url": url,
                    "use_render": use_render,
                    "http_method": "GET",
                },
            ))

        # Step 2: list_detect
        if list_rule:
            steps.append(StepConfig(
                step_id="s_legacy_2",
                step_type="list_detect",
                step_order=len(steps) + 1,
                title="识别列表",
                config={
                    "item_selector": list_rule.get("item_selector", ""),
                    "link_selector": list_rule.get("link_selector", "a"),
                    "link_attribute": list_rule.get("link_attribute", "href"),
                    "title_selector": "",
                    "time_selector": "",
                    "time_format": "%Y-%m-%d",
                    "crawl_scope": (rc.get("increment_config") or {}).get("crawl_scope", "all"),
                    "top_n_count": int((rc.get("increment_config") or {}).get("top_n_count") or 50),
                    "pagination": list_rule.get("pagination") or {},
                    "use_render": use_render,
                },
            ))

        # Step 3: detail_jump
        if detail_rule and detail_rule.get("fields"):
            steps.append(StepConfig(
                step_id="s_legacy_3",
                step_type="detail_jump",
                step_order=len(steps) + 1,
                title="抓取详情",
                config={
                    "detail_fields": [dict(f) for f in detail_rule.get("fields")],
                    "use_render": bool(detail_rule.get("use_render", False)),
                },
            ))

        # Step 4: attachment_parse（若有
        if attachment_rules:
            first = attachment_rules[0] or {}
            steps.append(StepConfig(
                step_id="s_legacy_4",
                step_type="attachment_parse",
                step_order=len(steps) + 1,
                title="解析附件",
                config={
                    "link_selector": first.get("link_selector", "a.attachment"),
                    "link_attribute": first.get("link_attribute", "href"),
                    "parse_pdf": bool(first.get("parse_pdf", True)),
                    "parse_image": bool(first.get("parse_image", False)),
                    "parse_docx": bool(first.get("parse_docx", False)),
                },
            ))

        # Step 5: field_mapping（即便为空也保留，便于字段展示
        steps.append(StepConfig(
            step_id="s_legacy_5",
            step_type="field_mapping",
            step_order=len(steps) + 1,
            title="字段映射",
            config={
                "map": dict(field_mapping) or {"title": "title", "body": "content"},
            },
        ))

        # Step 6: result_preview
        steps.append(StepConfig(
            step_id="s_legacy_6",
            step_type="result_preview",
            step_order=len(steps) + 1,
            title="结果预览",
            config={"sample_size": 20, "compare_raw": True, "mask_pii": True},
        ))

        pkg = StepsPackage(
            version=1,
            plan_name=plan_name or rc.get("name") or "",
            target_domain=target_domain or _extract_domain(url),
            spider_type=spider_type or rc.get("spider_type") or "generic",
            steps=steps,
            schedule_config=rc.get("schedule_config"),
            increment_config=rc.get("increment_config"),
            migrated_from_legacy=True,
        )
        pkg.normalize()
        return pkg


def _extract_domain(url: str) -> str:
    try:
        parsed = urlparse(url or "")
        return parsed.netloc or ""
    except Exception:
        return ""


# ============================================================================
# StepTester: 单步 + 全链路测试
# ============================================================================
class StepTester:
    """封装 T25 底层引擎做单步测试。"""

    # ------------------------------------------------------------ 单步
    @staticmethod
    def test_step(step_type: str,
                  config: Dict[str, Any], *,
                  page_html: Optional[str] = None,
                  upstream_data: Optional[Dict[str, Any]] = None
                  ) -> Dict[str, Any]:
        t0 = time.time()
        try:
            if step_type == "page_access":
                return StepTester._test_page_access(config, page_html, upstream_data, t0)
            if step_type == "list_detect":
                return StepTester._test_list_detect(config, page_html, upstream_data, t0)
            if step_type == "detail_jump":
                return StepTester._test_detail_jump(config, page_html, upstream_data, t0)
            if step_type == "attachment_parse":
                return StepTester._test_attachment(config, page_html, upstream_data, t0)
            if step_type == "field_mapping":
                return StepTester._test_mapping(config, page_html, upstream_data, t0)
            if step_type == "result_preview":
                return StepTester._test_preview(config, page_html, upstream_data, t0)
            if step_type.startswith("command_"):
                # T32: 委托给 command_library 做本地数据变换测试
                from business.custom_spider.command_library import run_command
                result = run_command(step_type, page_html or "", config, upstream_data)
                return {
                    "success": bool(result.get("success")),
                    "duration_ms": int((time.time() - t0) * 1000),
                    "message": result.get("error") or ("指令测试完成" if result.get("success") else "指令返回异常"),
                    "output": _mask_any({k: v for k, v in result.items() if k != "success"}),
                    "masked": True,
                }
            return {
                "success": False, "duration_ms": int((time.time() - t0) * 1000),
                "message": f"未知 step_type={step_type}", "output": {}, "masked": True,
            }
        except Exception as exc:  # pragma: no cover - 生产环境兜底
            _logger.exception("test_step 异常")
            return {
                "success": False, "duration_ms": int((time.time() - t0) * 1000),
                "message": f"测试失败: {exc}", "output": {}, "masked": True,
            }

    @staticmethod
    def _test_page_access(config, page_html, upstream_data, t0) -> Dict[str, Any]:
        """页面访问测试：优先使用 JS 渲染（Playwright）抓取完整页面内容。"""
        url = config.get("url") or (upstream_data or {}).get("url") or ""
        raw_render = config.get("use_render")
        # 支持多种形式：True/False、1/0、"true"/"false"、"yes"/"no"
        if raw_render is None or raw_render == "":
            use_render = True  # 默认启用 JS 渲染，获取更完整的页面内容
        elif isinstance(raw_render, bool):
            use_render = raw_render
        elif isinstance(raw_render, (int, float)):
            use_render = bool(raw_render)
        else:
            use_render = str(raw_render).strip().lower() in ("true", "yes", "1", "y", "on")
        wait_ms = int(config.get("render_wait_ms") or 5000)
        http_method = (config.get("http_method") or "get").lower()

        title = ""
        status_code = 0
        html_out = ""
        final_url = url
        msg = "页面访问测试完成"
        source_type = "js_render" if use_render else "http"

        # 优先使用外部传入的 HTML（如来自前端浏览器加载的完整 HTML），
        # 因为这是用户在浏览器中实际看到的内容，list_detect 等后续步骤
        # 也应该使用相同的内容来确保结果一致
        if page_html and page_html.strip():
            title = _extract_title(page_html) or "（来自浏览器预加载）"
            html_out = _mask_any(page_html) if page_html else ""
            status_code = 200
            source_type = "external_html"
            msg = f"使用浏览器预加载 HTML（{len(html_out)} 字符）"
        elif url:
            # 实际发起 HTTP 请求 / JS 渲染抓取页面
            try:
                from core.spider_core.page_renderer import render_page
                result = render_page(
                    url,
                    wait_ms=wait_ms,
                    timeout=45.0,
                    render_js=use_render,
                )
                html_out = result.get("html") or ""
                title = result.get("title") or ""
                status_code = int(result.get("status_code") or 0)
                final_url = result.get("final_url") or url
                err = result.get("error")

                # JS 渲染失败（如 playwright 未安装）时，自动回退到简单 HTTP 请求
                if use_render and (err or not html_out or status_code == 0):
                    fallback_result = render_page(url, wait_ms=wait_ms, timeout=45.0, render_js=False)
                    if fallback_result.get("html"):
                        html_out = fallback_result["html"]
                        title = fallback_result.get("title") or title
                        status_code = int(fallback_result.get("status_code") or status_code)
                        final_url = fallback_result.get("final_url") or final_url
                        msg = f"页面抓取成功（JS 渲染失败，已回退到 HTTP 请求）：{status_code}，{len(html_out)} 字符"
                        source_type = "http_fallback"
                    else:
                        msg = f"页面抓取异常（JS 渲染失败且 HTTP 回退也失败）：{err}"
                elif err:
                    msg = f"页面抓取完成（有警告: {err[:80]}）"
                elif not html_out or status_code >= 400:
                    msg = f"页面抓取异常: HTTP {status_code}"
                else:
                    msg = f"页面抓取成功（{'JS 渲染' if use_render else 'HTTP 请求'}，{status_code}，{len(html_out)} 字符）"
            except Exception as exc:
                # JS 渲染异常时，尝试 HTTP 回退
                if use_render:
                    try:
                        from core.spider_core.page_renderer import render_page
                        fallback_result = render_page(url, wait_ms=wait_ms, timeout=45.0, render_js=False)
                        if fallback_result.get("html"):
                            html_out = fallback_result["html"]
                            title = fallback_result.get("title") or ""
                            status_code = int(fallback_result.get("status_code") or 0)
                            final_url = fallback_result.get("final_url") or url
                            msg = f"页面抓取成功（JS 渲染异常后回退到 HTTP 请求：{exc}）：{status_code}，{len(html_out)} 字符"
                            source_type = "http_fallback"
                        else:
                            html_out = ""
                            msg = f"页面抓取失败: {exc}"
                    except Exception as exc2:
                        html_out = ""
                        msg = f"页面抓取失败: {exc}; 回退也失败: {exc2}"
                else:
                    html_out = ""
                    msg = f"页面抓取失败: {exc}"
        else:
            msg = "未配置 URL，跳过抓取"

        # 返回完整 HTML（下游步骤如 list_detect 需要完整内容进行选择器匹配）
        return {
            "success": bool(html_out),
            "duration_ms": int((time.time() - t0) * 1000),
            "message": msg,
            "output": {
                "url": url,
                "final_url": final_url,
                "title": title,
                "html_preview": html_out,
                "html_length": len(html_out),
                "status_code": status_code,
                "use_render": use_render,
                "source_type": source_type,
                "render_wait_ms": wait_ms,
                "http_method": http_method,
            },
            "masked": True,
        }

    @staticmethod
    def _test_list_detect(config, page_html, upstream_data, t0):
        """列表识别：优先使用用户配置的选择器，未配置时自动识别。

        config 支持：
          - item_selector: 列表项选择器（如 "li.news-item"）
          - link_selector: 链接选择器（如 "a"）
          - link_attribute: 链接属性（如 "href"）
          - title_selector: 标题选择器（如 ".title"）
          - crawl_scope: "latest" / "top_n"
          - top_n_count: 返回前 N 条
        """
        config = config or {}
        html = page_html or ""
        if not html:
            html = (upstream_data or {}).get("html_preview") or ""
        base_url = (upstream_data or {}).get("final_url") or (upstream_data or {}).get("url") or ""

        item_selector = config.get("item_selector") or ""
        link_selector = config.get("link_selector") or ""
        link_attr = config.get("link_attribute") or "href"
        title_selector = config.get("title_selector") or ""
        top_n = int(config.get("top_n_count") or 20)

        # --- 方案 1：有用户配置的选择器，用 BeautifulSoup 直接提取 ---
        if item_selector and html:
            try:
                from bs4 import BeautifulSoup
                from urllib.parse import urljoin
                soup = BeautifulSoup(html, "html.parser")
                nodes = soup.select(item_selector)
                items_extracted = []
                for idx, node in enumerate(nodes):
                    title_text = ""
                    link_url = ""

                    # 标题
                    if title_selector:
                        t = node.select_one(title_selector)
                        if t:
                            title_text = t.get_text(" ", strip=True)
                    if not title_text:
                        title_text = node.get_text(" ", strip=True)[:120]

                    # 链接: 支持 link_selector 与 item_selector 相同的情况
                    if link_selector:
                        # 如果 link_selector 等于 item_selector，说明 item 本身就是链接节点
                        if link_selector == item_selector:
                            link_url = node.get(link_attr) or node.get("href") or ""
                        else:
                            # 否则在 item 内查找 link_selector
                            lnode = node.select_one(link_selector)
                            if lnode:
                                link_url = lnode.get(link_attr) or lnode.get("href") or ""
                    if not link_url:
                        lnode = node.find("a")
                        if lnode:
                            link_url = lnode.get(link_attr) or lnode.get("href") or ""
                    if not link_url and link_attr and link_attr != "href":
                        link_url = node.get(link_attr) or ""

                    if link_url and base_url:
                        try:
                            link_url = urljoin(base_url, link_url)
                        except Exception:
                            pass

                    items_extracted.append({
                        "title": title_text.strip(),
                        "link": link_url.strip(),
                        "publish_time_iso": "",
                        "_raw_time": "",
                    })
                items_extracted = items_extracted[:top_n]
                return {
                    "success": bool(items_extracted),
                    "duration_ms": int((time.time() - t0) * 1000),
                    "message": f"使用自定义选择器，识别到 {len(items_extracted)} 条记录（item_selector: {item_selector}）",
                    "output": {
                        "containers": [{"selector": item_selector, "item_count": len(nodes),
                                        "confidence": 1.0, "source": "configured"}],
                        "time_fields": [],
                        "items": items_extracted,
                        "item_count_total": len(nodes),
                        "confidence": 1.0,
                        "crawl_scope_suggestion": config.get("crawl_scope") or "top_n",
                    },
                    "masked": True,
                }
            except Exception as exc:
                _logger.warning(f"list_detect 自定义选择器失败: {exc}")

        # --- 方案 2：无配置或配置失败，走智能自动识别 ---
        from business.custom_spider.smart_detector import SmartDetector
        detector = SmartDetector()
        result = detector.detect_all(html, target_url=base_url)

        items_auto = result.get("items", []) or []
        # 对自动识别的结果也做相对 URL 补全
        if base_url and items_auto:
            from urllib.parse import urljoin
            for it in items_auto:
                lk = it.get("link") or ""
                if lk and not lk.startswith(("http://", "https://")):
                    try:
                        it["link"] = urljoin(base_url, lk)
                    except Exception:
                        pass

        items_auto = items_auto[:top_n]
        return {
            "success": bool(items_auto),
            "duration_ms": int((time.time() - t0) * 1000),
            "message": result.get("degrade_reason") or f"自动识别完成，共 {len(items_auto)} 条记录",
            "output": {
                "containers": result.get("containers", []),
                "time_fields": result.get("time_fields", []),
                "items": items_auto,
                "item_count_total": result.get("item_count_total"),
                "confidence": result.get("confidence", 0.0),
                "crawl_scope_suggestion": result.get("crawl_scope_suggestion"),
            },
            "masked": True,
        }

    @staticmethod
    def _test_detail_jump(config, page_html, upstream_data, t0):
        """详情跳转：对于上游识别到的每条记录，访问其 URL 抓取详情内容，
        从详情页实际提取 title / content / publish_date 等字段，
        同时检测详情页中的附件链接（供后续附件解析步骤使用）。

        output.items 中每条记录包含：
          - 提取的字段：title, content, publish_date, link, ...
          - _source_url: 详情页 URL
          - _page_status: HTTP 状态码
          - _page_preview: 详情页文本预览
          - _attachment_urls: 检测到的附件 URL 列表
        """
        detail_fields = config.get("detail_fields", []) or []
        items = []
        source_items = (upstream_data or {}).get("items") or []

        renderer = None
        try:
            from core.spider_core.page_renderer import render_page
            renderer = render_page
        except Exception:
            renderer = None

        def _extract_from_detail_html(html_text: str, base_url: str) -> dict:
            """从详情页 HTML 中提取 content / publish_date / 附件链接。"""
            from bs4 import BeautifulSoup
            from urllib.parse import urljoin
            import re as _re

            result = {"content": "", "publish_date": "",
                    "attachment_urls": [], "title": ""}
            if not html_text:
                return result
            try:
                soup = BeautifulSoup(html_text, "html.parser")
            except Exception:
                return result

            # 1) 提取标题：h1 > h2
            for selector in ["h1", "h2", ".title", ".page-title"]:
                el = soup.select_one(selector)
                if el and el.get_text(strip=True):
                    result["title"] = el.get_text(strip=True)
                    break

            # 2) 提取发布日期：常见日期格式
            date_patterns = [
                r'\d{4}[-/\.]\d{1,2}[-/\.]\d{1,2}',  # 2026-07-02, 2026/07/02
                r'\d{4}年\d{1,2}月\d{1,2}日',  # 2026年7月2日
            ]
            all_text = soup.get_text(" ", strip=True)
            for pat in date_patterns:
                m = _re.search(pat, all_text)
                if m:
                    result["publish_date"] = m.group(0)
                    break
            if not result["publish_date"]:
                meta_date = soup.find("meta", attrs={"name": lambda x: x and ("date" in (x or "").lower())})
                if meta_date:
                    result["publish_date"] = meta_date.get("content", "")

            # 3) 提取正文内容：优先使用纯正文容器（如 #con_con, .ccontent），
            #    它们只包含文章段落，没有标题/来源/分享等噪声。
            #    找不到纯正文容器时，再用 article / .article-content 等通用容器。
            #    最后才用外层容器（.cmain 等）兜底。
            body_containers = [
                # 中文CMS纯正文容器（最高优先级）
                "#con_con", ".ccontent",
                # 通用正文容器
                "article", ".article-content", "#article",
                ".news-content", ".news_content", ".detail-content",
                ".main-text", ".text-content", ".txt-content", ".content_text",
            ]
            outer_containers = [
                "#content", ".content", "#main-content",
                # 通用模糊匹配（可能含噪声，作为兜底）
                "div[class*='article']", "div[class*='content']",
                "div[class*='detail']", "div[class*='text']",
                "section[class*='article']", "section[class*='content']",
                # 外层容器（含标题/来源/分享，优先级最低）
                ".cmain",
            ]
            noise_keywords = [
                "扫一扫", "分享", "返回顶部", "关闭窗口", "打印本页",
                "相关文章", "微信", "微博", "QQ空间", "qr_container",
                "ewmzs", "article_fd", "share-popup", "shareSc",
            ]
            # 需去除的噪声类名（直接从匹配容器中删除这些子节点）
            noise_class_patterns = [
                "share", "related", "ewmzs", "qr_container",
                "article_fd", "share-popup", "shareSc",
            ]

            def _clean_node(node):
                """递归删除噪声子节点（分享、二维码、相关文章等）。"""
                if node is None:
                    return None
                for child in node.find_all(recursive=True):
                    if getattr(child, 'attrs', None) is None:
                        continue
                    cls = " ".join(child.get("class", []) or []).lower()
                    cid = (child.get("id") or "").lower()
                    if any(p in cls for p in noise_class_patterns) or any(p in cid for p in noise_class_patterns):
                        try:
                            child.decompose()
                        except Exception:
                            pass
                return node

            best_el = None
            best_len = 0

            # 策略 1：纯正文容器
            for sel in body_containers:
                try:
                    el = soup.select_one(sel)
                    if el:
                        _clean_node(el)
                        # 优先提取段落文本（p/li/div 等），避免被 h1/h2 等标题干扰
                        parts = []
                        for p in el.find_all(["p", "li", "blockquote", "pre"]):
                            t = p.get_text(" ", strip=True)
                            if t and len(t) > 1:
                                parts.append(t)
                        if parts:
                            text = "\n".join(parts)
                        else:
                            text = el.get_text("\n", strip=True)
                        # 过滤单行噪声（如 "扫一扫", "分享到" 等）
                        clean_lines = []
                        for line in text.splitlines():
                            s = line.strip()
                            if s and not any(n in s for n in noise_keywords):
                                clean_lines.append(s)
                        text = "\n".join(clean_lines)
                        if len(text) > best_len:
                            best_len = len(text)
                            best_el = ("body", el, text)
                            if best_len > 2000:
                                break
                except Exception:
                    continue

            # 策略 2：外层容器兜底
            if best_len < 200:
                for sel in outer_containers:
                    try:
                        el = soup.select_one(sel)
                        if el:
                            _clean_node(el)
                            text = el.get_text("\n", strip=True)
                            # 同样过滤噪声
                            clean_lines = []
                            for line in text.splitlines():
                                s = line.strip()
                                if s and not any(n in s for n in noise_keywords):
                                    clean_lines.append(s)
                            text = "\n".join(clean_lines)
                            if len(text) > best_len and len(text) < 20000:
                                best_len = len(text)
                                best_el = ("outer", el, text)
                                if best_len > 2000:
                                    break
                    except Exception:
                        continue

            # 策略 3：找包含"发布时间"的 div（非标题段落）
            if best_len < 200:
                for el in soup.find_all(['div', 'section']):
                    t = el.get_text(" ", strip=True)
                    if ('发布时间' in t or '来源' in t) and len(t) < 20000:
                        # 跳过标题容器（只看正文）
                        if any(kw in t[:20] for kw in ("发布时间", "来源", "作者")):
                            continue
                        if len(t) > best_len:
                            best_len = len(t)
                            best_el = ("by-keyword", el, t)

            # 策略 4：找包含 h1 的最近父级 div
            if best_len < 200:
                h1 = soup.find("h1")
                if h1:
                    el = h1.parent
                    for _ in range(3):
                        if el and el.name in ('div', 'section', 'article'):
                            t = el.get_text("\n", strip=True)
                            if len(t) > best_len:
                                best_len = len(t)
                                best_el = ("h1-parent", el, t)
                        if el:
                            el = el.parent
                        else:
                            break

            # 最后手段：body 全文（去噪声）
            if best_len < 100:
                body_text = soup.get_text("\n", strip=True)
                clean_lines = []
                for line in body_text.splitlines():
                    s = line.strip()
                    if s and not any(n in s for n in noise_keywords):
                        clean_lines.append(s)
                body_text = "\n".join(clean_lines)
                if len(body_text) > best_len:
                    best_len = len(body_text)
                    best_el = ("body-fallback", soup, body_text)

            if best_el is not None and best_len > 30:
                result["content"] = best_el[2][:5000]
            else:
                result["content"] = ""

            # 4) 检测附件链接
            try:
                from urllib.parse import urlparse, parse_qs, unquote
                seen = set()
                attach_exts = (".pdf", ".doc", ".docx", ".xls", ".xlsx",
                              ".ppt", ".pptx", ".txt", ".csv", ".rtf")

                def _maybe_add(url_or_path: str):
                    if not url_or_path:
                        return
                    # 从 URL 中解析 file 参数 (pdfjs viewer.html?file=xxx)
                    lower = url_or_path.lower()
                    if "file=" in lower and ("viewer" in lower or "pdfjs" in lower):
                        try:
                            qs = parse_qs(urlparse(url_or_path).query)
                            for v in qs.get("file", []):
                                if v and v.lower().endswith(attach_exts):
                                    u = urljoin(base_url, v) if base_url else v
                                    if u not in seen:
                                        seen.add(u)
                                        result["attachment_urls"].append(u)
                            return
                        except Exception:
                            pass
                    # 普通 URL：以扩展名结尾的直接命中
                    url_no_query = url_or_path.split("?", 1)[0].lower()
                    if any(url_no_query.endswith(ext) for ext in attach_exts):
                        u = urljoin(base_url, url_or_path) if base_url else url_or_path
                        if u not in seen:
                            seen.add(u)
                            result["attachment_urls"].append(u)

                # 4.1 普通 <a> 链接
                for a in soup.find_all("a"):
                    href = a.get("href") or ""
                    if not href or href in ("#", "javascript:void(0)"):
                        continue
                    _maybe_add(href)

                # 4.2 <iframe>/<embed>/<object> 内嵌附件（如 pdfjs viewer）
                for el in soup.find_all(["iframe", "embed", "object"]):
                    for attr in ("src", "data", "fileurl"):
                        v = el.get(attr) or ""
                        if v:
                            _maybe_add(v)

                # 4.3 data-* 属性中的附件（如 data-pdf-url、data-file-url 等）
                for el in soup.find_all(True):
                    if not getattr(el, 'attrs', None):
                        continue
                    for k, v in el.attrs.items():
                        if not isinstance(v, str):
                            continue
                        kl = k.lower()
                        if kl.startswith("data") and ("pdf" in kl or "file" in kl or "attach" in kl or "download" in kl):
                            _maybe_add(v)

                # 4.4 从常见的 data-file-url 等显式属性中取
                for attr_name in ("data-file-url", "data-file", "data-attach-url", "data-download-url"):
                    for el in soup.find_all(attrs={attr_name: True}):
                        v = el.get(attr_name) or ""
                        if v:
                            _maybe_add(v)
            except Exception:
                pass

            return result

        for src in source_items[:5]:
            mapped = {}

            # 先从上游已有字段
            title_from_list = src.get("title") or ""
            link_from_list = src.get("link") or src.get("url") or ""

            mapped["title"] = title_from_list
            mapped["link"] = link_from_list
            mapped["_source_url"] = link_from_list

            url = link_from_list
            detail_html = ""

            # 抓取详情页（使用用户配置的渲染选项，未设置时默认启用 JS 渲染）
            use_render = config.get("use_render", True)
            if use_render is False or use_render == "false" or use_render == 0:
                use_render = False
            wait_ms = int(config.get("render_wait_ms", 2000))
            timeout = 45.0

            if url and renderer:
                try:
                    r = renderer(url, wait_ms=wait_ms, timeout=timeout, render_js=use_render)
                    if r and r.get("html"):
                        detail_html = r.get("html") or ""
                        mapped["_page_status"] = int(r.get("status_code") or 200)
                        # 去 HTML 标签，保留纯文本前 500 字符做预览
                        import re as _re2
                        plain = _re2.sub(r"<[^>]+>", "", detail_html)
                        plain = " ".join(plain.split())
                        mapped["_page_preview"] = plain[:500]
                        mapped["_html_size"] = len(detail_html)
                        mapped["_use_render"] = use_render
                        mapped["_render_wait_ms"] = wait_ms
                        if not mapped.get("title") and r.get("title"):
                            mapped["title"] = r["title"]

                        # 从详情页 HTML 实际提取字段
                        extracted = _extract_from_detail_html(detail_html, url)
                        if extracted["title"] and not mapped.get("title"):
                            mapped["title"] = extracted["title"]

                        mapped["content"] = extracted["content"]
                        mapped["publish_date"] = extracted["publish_date"]
                        mapped["_attachment_urls"] = extracted["attachment_urls"]
                    else:
                        mapped["_page_status"] = 0
                except Exception:
                    mapped["_page_status"] = 0

            # 补齐用户配置的其他字段（优先从详情页提取，否则从上游继承）
            for f in detail_fields:
                if isinstance(f, str):
                    key = f
                    if key not in mapped or not mapped[key]:
                        mapped[key] = src.get(key, "") or ""
                else:
                    key = f.get("name") or ""
                    if key not in mapped or not mapped[key]:
                        mapped[key] = src.get(key, f.get("default_value") or "")

            items.append(mapped)

        msg = "详情跳转测试完成" if items else "详情跳转配置验证通过（上游无数据）"
        if items and any(i.get("_page_status") for i in items):
            msg = f"详情跳转完成，已抓取 {sum(1 for i in items if i.get('_page_status'))} 个详情页，共 {len(items)} 条记录"
        elif items:
            msg = f"详情跳转完成，共 {len(items)} 条记录（未实际抓取，仅字段映射）"

        return {
            "success": True, "duration_ms": int((time.time() - t0) * 1000),
            "message": msg,
            "output": {
                "items": items,
            "detail_items": items,
                "item_count": len(items),
            },
            "masked": True,
        }

    @staticmethod
    def _test_attachment(config, page_html, upstream_data, t0):
        """实际执行 PDF/附件解析测试。

        config 支持：
          - url: 附件 URL（优先；没有时从 page_html 自动识别）
          - link_selector: 从 HTML 识别附件链接（默认 "a"）
          - link_attribute: 链接属性（默认 "href"）
          - base_url: 补全相对 URL 用的基础 URL（也可以从 upstream_data.url 自动推断）
          - parse_pdf / parse_doc / parse_excel: 各类型开关
        """
        from bs4 import BeautifulSoup
        from urllib.parse import urljoin, urlparse
        try:
            from core.spider_core.attachment_parser import AttachmentParser
            from core.spider_core.pdf_parser import ParsedTable
        except Exception as e:
            return {
                "success": False,
                "duration_ms": int((time.time() - t0) * 1000),
                "message": f"附件解析模块不可用: {e}",
                "output": {},
                "masked": True,
            }

        results = []
        attachment_urls = []
        config = config or {}
        upstream_data = upstream_data or {}
        base_url = ""

        # 推断 base_url：用于补全相对 URL
        # 1. config 中显式设置
        if config.get("base_url"):
            base_url = str(config["base_url"])
        # 2. 从 upstream_data 顶层取
        if not base_url and isinstance(upstream_data, dict):
            if upstream_data.get("url"):
                base_url = str(upstream_data["url"])
            elif upstream_data.get("final_url"):
                base_url = str(upstream_data["final_url"])

        # 从上游 detail_jump 产出的 items 中收集附件 URL
        upstream_items = upstream_data.get("items") or []
        if isinstance(upstream_items, list):
            for item in upstream_items[:3]:
                if isinstance(item, dict):
                    item_urls = item.get("_attachment_urls") or []
                    if isinstance(item_urls, list):
                        for u in item_urls:
                            if u and u not in attachment_urls:
                                attachment_urls.append(str(u))
                    # 也支持从 link / _source_url 中补全 base_url
                    if not base_url:
                        source_url = item.get("_source_url") or item.get("link") or item.get("url") or ""
                        if source_url:
                            base_url = source_url

        def _make_absolute(u: str) -> str:
            if not u:
                return u
            if u.startswith(("http://", "https://")):
                return u
            if base_url:
                try:
                    return urljoin(base_url, u)
                except Exception:
                    pass
            return u

        def _is_attachment_url(u: str) -> bool:
            if not u:
                return False
            lower = u.lower().split("?", 1)[0]
            return any(lower.endswith(ext) for ext in (
                ".pdf", ".doc", ".docx", ".xls", ".xlsx",
                ".ppt", ".pptx", ".txt", ".csv", ".rtf",
            ))

        # 1) 从配置/HTML 收集附件 URL
        if config.get("url"):
            attachment_urls.append(_make_absolute(config["url"]))
        elif page_html:
            try:
                soup = BeautifulSoup(page_html, "html.parser")
                sel = config.get("link_selector") or "a"
                attr = config.get("link_attribute") or "href"

                # 先尝试用户指定的 selector + attr
                if sel and sel != "a" or attr != "href":
                    for el in soup.select(sel)[:20]:
                        href = el.get(attr) or ""
                        if not href or href in ("#", "javascript:void(0)"):
                            continue
                        if _is_attachment_url(href):
                            attachment_urls.append(_make_absolute(href))

                # 自动扫描：在所有标签中查找常见的附件属性
                common_attrs = ["data-pdf-url", "data-doc-url", "data-attach",
                                 "data-file", "data-src", "data-url", "data-href",
                                 "data-crawl-href", "href", "src"]

                # 先从常见容器（如 div.pdf-attachment）中识别
                # 然后再从所有标签中扫描
                if not attachment_urls:
                    seen = set()
                    for el in soup.find_all(True):
                        for a in common_attrs:
                            v = el.get(a) or ""
                            if v and v not in seen and _is_attachment_url(v):
                                attachment_urls.append(_make_absolute(v))
                                seen.add(v)
                                if len(attachment_urls) >= 5:
                                    break
                        if len(attachment_urls) >= 5:
                            break

            except Exception as exc:
                _logger.warning(f"attachment_parse 收集 URL 失败: {exc}")

        # 去重
        attachment_urls = list(dict.fromkeys(attachment_urls))[:5]

        if not attachment_urls:
            return {
                "success": True,
                "duration_ms": int((time.time() - t0) * 1000),
                "message": "未发现可解析的附件链接（请在配置中手动填写 URL，或在列表选择器中指定附件）",
                "output": {"attachment_urls": [], "results": []},
                "masked": True,
            }

        parser = AttachmentParser()
        for url in attachment_urls[:5]:
            try:
                r = parser.parse(url, base_url=base_url)
                item = {
                    "source_url": r.source_url,
                    "filename": r.filename,
                    "file_type": r.mime_type,  # 前端显示用
                    "mime_type": r.mime_type,   # 保留原始字段
                    "file_size_bytes": r.file_size_bytes,
                    "parse_status": r.parse_status,
                    "error": r.error,
                    "text": str(r.text)[:5000] if r.text else "",
                }
                # 如果有表格，保留结构化信息（全量，不再限制 [:3] 和 [:10]）
                tables = []
                merged_rows = []
                if r.tables:
                    for t in r.tables:
                        if isinstance(t, ParsedTable):
                            tables.append({
                                "page_index": t.page_index,
                                "row_count": t.row_count,
                                "column_count": t.column_count,
                                "headers": t.headers,
                                "rows": [list(row) for row in t.rows],
                            })
                            for row in t.rows:
                                if row and any(str(c).strip() for c in row):
                                    merged_rows.append(list(row))
                        elif isinstance(t, dict):
                            _rows = t.get("rows") or []
                            tables.append({
                                "headers": t.get("headers", []),
                                "rows": [list(rr) for rr in _rows],
                                "row_count": len(_rows),
                                "column_count": len(_rows[0]) if _rows else 0,
                            })
                            for row in _rows:
                                if row and any(str(c).strip() for c in row):
                                    merged_rows.append(list(row))
                item["tables"] = tables
                # merged_rows：所有表格的行扁平化合并，供 field_mapping 遍历
                item["merged_rows"] = merged_rows
                # metadata
                if isinstance(r.fields, dict):
                    item["metadata"] = {k: str(v) for k, v in r.fields.items() if v}
                else:
                    item["metadata"] = {}
                results.append(item)
            except Exception as exc:
                results.append({
                    "source_url": url,
                    "parse_status": "failed",
                    "error": str(exc),
                    "text": "",
                    "tables": [],
                })
        return {
            "success": True,
            "duration_ms": int((time.time() - t0) * 1000),
            "message": f"已解析 {len(results)} 个附件",
            "output": {
                "attachment_urls": attachment_urls,
                "attachments": results,      # 统一字段名
                "results": results,          # 向后兼容
                "item_count": len(results),
            },
            "masked": True,
        }

    @staticmethod
    def _test_mapping(config, page_html, upstream_data, t0):
        """字段映射。支持从 upstream items 和 attachment results 中提取字段。

        map 支持的 source 格式：
          - "items[0].title" → 从 items 第 0 项 title
          - "attachments[0].text" → 从附件 0 全文
          - "attachments[0].tables[0].rows[1][2]" → 表格 0 行 1 列 2
          - "attachments[0].tables[0].headers[1]" → 表格 0 表头 1
          - "attachments[0].tables[0].rows[row][1]" → 遍历表格每行取列 1
            （使用 [row] 表示遍历表格所有行，为每行生成一条记录）
          - "attachments[0].metadata.Author" → 附件元数据
          - 普通 key（如 "title"） → 从 items[*] 的 dict 中直接取
          - 固定值："=某文本" 开头 → 直接作为值
        """
        import re as _re_mapping

        map_dict = config.get("map", {}) or {}
        upstream_data = upstream_data or {}
        upstream_items = upstream_data.get("items") or upstream_data.get("mapped_items") or []
        attachment_results = (upstream_data.get("results") or upstream_data.get("attachments") or [])
        mapped = []

        def _path_eval(root, path: str) -> str:
            """解析像 "[0].tables[0].rows[1][2]" 这样的路径。"""
            parts = path.replace("[", ".").replace("]", "").split(".")
            parts = [p for p in parts if p]
            cur: Any = root
            for p in parts:
                if isinstance(cur, list):
                    try:
                        idx = int(p)
                        cur = cur[idx] if 0 <= idx < len(cur) else ""
                    except (ValueError, IndexError):
                        return ""
                elif isinstance(cur, dict):
                    cur = cur.get(p, "")
                else:
                    try:
                        idx = int(p)
                        if hasattr(cur, "__getitem__"):
                            cur = cur[idx]
                        else:
                            return ""
                    except (ValueError, IndexError, TypeError):
                        return ""
            return str(cur) if cur is not None else ""

        def _resolve_source(source: str, src_item: dict, *, row_idx: int = -1) -> str:
            """解析单个 source 值。row_idx >= 0 时，将 [row] 替换为该行号。"""
            if not source:
                return ""
            source = str(source).strip()
            # 固定值
            if source.startswith("="):
                return source[1:]
            # 处理 [row] 占位符：替换为实际行号字符串
            effective_source = source
            if "[row]" in effective_source and row_idx >= 0:
                effective_source = effective_source.replace("[row]", f"[{row_idx}]")
            # items 路径
            if effective_source.startswith("items["):
                try:
                    rest = effective_source[len("items"):]
                    return _path_eval(upstream_items, rest)
                except Exception:
                    return ""
            # attachments 路径
            if effective_source.startswith("attachments["):
                try:
                    rest = effective_source[len("attachments"):]
                    return _path_eval(attachment_results, rest)
                except Exception:
                    return ""
            # 其他：从 src_item 取
            return str(src_item.get(effective_source, "") or "")

        # —— 关键逻辑：检测是否有 [row] 标记 ——
        # 如果任一 source 中包含 [row]，表示要遍历表格行生成多条记录
        row_marker_sources = [s for s in map_dict.values()
                              if isinstance(s, str) and "[row]" in s]
        if row_marker_sources and attachment_results:
            # 两种 source 格式都支持：
            #   a) attachments[X].merged_rows[row][N]   → 遍历所有表格合并后的行（推荐）
            #   b) attachments[X].tables[Y].rows[row][N] → 遍历某个 table 的行
            first_row_src = row_marker_sources[0]
            target_rows = None
            try:
                # 格式 a: merged_rows
                m_merged = _re_mapping.search(r"attachments\[(\d+)\]\.merged_rows\[row\]", first_row_src)
                if m_merged:
                    a_idx = int(m_merged.group(1))
                    if (a_idx < len(attachment_results)
                            and isinstance(attachment_results[a_idx], dict)):
                        target_rows = attachment_results[a_idx].get("merged_rows") or None
                # 格式 b: 具体 tables[Y]
                if target_rows is None:
                    m_table = _re_mapping.search(r"attachments\[(\d+)\]\.tables\[(\*|\d+)\]", first_row_src)
                    if m_table:
                        a_idx = int(m_table.group(1))
                        t_idx_str = m_table.group(2)
                        if (a_idx < len(attachment_results)
                                and isinstance(attachment_results[a_idx], dict)):
                            tables = attachment_results[a_idx].get("tables") or []
                            if t_idx_str == "*":
                                # tables[*]：遍历所有 tables 合并 rows
                                combined_rows = []
                                for _t in tables:
                                    if isinstance(_t, dict):
                                        combined_rows.extend(_t.get("rows") or [])
                                target_rows = combined_rows
                            else:
                                t_idx = int(t_idx_str)
                                if t_idx < len(tables) and isinstance(tables[t_idx], dict):
                                    target_rows = tables[t_idx].get("rows") or []
            except Exception:
                target_rows = None

            if target_rows:
                # 为每行生成一条记录（过滤空行 / 纯错误描述行）
                for r_idx, row in enumerate(target_rows):
                    if not row:
                        continue
                    row_cells = [c for c in row if isinstance(c, str) and c.strip()]
                    if not row_cells:
                        continue
                    # 启发式：第 1 列（序号列）不能转成数字且其他列也不是应用名时跳过
                    first_cell = str(row[0]).strip() if row else ""
                    if not first_cell.isdigit() and len(row_cells) <= 1:
                        continue
                    out: Dict[str, Any] = {"_row_index": r_idx}
                    for target, source in map_dict.items():
                        out[target] = _resolve_source(str(source), {}, row_idx=r_idx)
                    mapped.append(out)

        # 如果上面没有 [row] 方式或没有匹配到表格，回到按 items 生成记录的逻辑
        if not mapped and upstream_items:
            # 只有在有上游 items 时才生成记录
            # （否则保留空列表，表示没有可映射的数据，避免产生全空占位记录）
            for src in upstream_items:
                out: Dict[str, Any] = {}
                for target, source in map_dict.items():
                    out[target] = _resolve_source(str(source), src)
                mapped.append(out)

        # 同时生成 "扁平预览"：如果 upstream 中有附件，还会在 attachment_map 中显示
        attachment_map = []
        for i, att in enumerate(attachment_results[:3]):
            info = {"attach_index": i, "filename": att.get("filename") or att.get("source_url") or ""}
            for target, source in map_dict.items():
                info[target] = _resolve_source(str(source), {})
            attachment_map.append(info)

        return {
            "success": True,
            "duration_ms": int((time.time() - t0) * 1000),
            "message": f"字段映射完成，共 {len(mapped)} 条记录" if mapped else "字段映射配置验证通过",
            "output": {
                "items": mapped,              # 统一字段名
                "mapped_items": mapped,       # 向后兼容
                "attachment_map": attachment_map,
                "map": dict(map_dict),
                "item_count": len(mapped),
            },
            "masked": True,
        }

    @staticmethod
    def _test_preview(config, page_html, upstream_data, t0):
        """结果预览：展示从前面步骤累积的所有数据。"""
        upstream_data = upstream_data or {}
        items_to_show = []
        attachments_to_show = []
        source_type = "无数据"
        
        # 优先从 items 拿（可能来自 field_mapping/detail_jump/list_detect）
        if upstream_data.get("items"):
            items_to_show = upstream_data.get("items") or []
            source_type = "字段映射/详情跳转"
        elif upstream_data.get("mapped_items"):
            items_to_show = upstream_data.get("mapped_items") or []
            source_type = "字段映射"
        elif upstream_data.get("results"):
            items_to_show = upstream_data.get("results") or []
            source_type = "附件解析"
        
        # 附件数据
        if upstream_data.get("attachments"):
            attachments_to_show = upstream_data.get("attachments") or []
        elif upstream_data.get("results"):
            attachments_to_show = upstream_data.get("results") or []
        
        sample_size = int(config.get("sample_size") or 20)
        items_sample = items_to_show[:sample_size] if isinstance(items_to_show, list) else []
        attachments_sample = attachments_to_show[:5] if isinstance(attachments_to_show, list) else []
        
        return {
            "success": True,
            "duration_ms": int((time.time() - t0) * 1000),
            "message": f"结果预览: {len(items_sample)} 条记录，{len(attachments_sample)} 个附件（来源: {source_type}）",
            "output": {
                "items": items_sample,
                "attachments": attachments_sample,
                "item_count": len(items_sample),
                "attachment_count": len(attachments_sample),
                "sample_size": sample_size,
                "source_type": source_type,
            },
            "masked": True,
        }

    # ------------------------------------------------------------ 全链路
    @staticmethod
    def run_all(package: StepsPackage, preloaded_html: Optional[str] = None) -> Dict[str, Any]:
        results: List[Dict[str, Any]] = []
        # 累积数据：从前面所有步骤收集，而不仅仅是上一步
        accumulated: Dict[str, Any] = {}
        last_output: Dict[str, Any] = {}
        final_items: Any = []
        final_attachments: Any = []
        # 如果前端传入了已加载的 HTML（即用户已经在浏览器中加载过页面），
        # 则第一个 page_access 步骤优先使用这个 HTML 而不是重新抓取，
        # 确保全链路测试与用户看到的内容一致
        used_preloaded = False
        
        for step in package.steps:
            try:
                # 合并：accumulated + last_output，提供更完整的 upstream 上下文
                merged_upstream: Dict[str, Any] = dict(accumulated)
                # 上一步的输出优先级更高（覆盖相同字段）
                if last_output:
                    merged_upstream.update(last_output)
                
                # 关键逻辑：如果前端提供了 preloaded_html，
                # 且当前步骤是 page_access，且步骤 URL 与已加载的页面内容相关，
                # 则优先使用 preloaded_html 作为 page_html，避免重复抓取
                effective_page_html = merged_upstream.get("html_preview")
                if (not used_preloaded and preloaded_html and 
                        step.step_type == "page_access" and 
                        not effective_page_html):
                    effective_page_html = preloaded_html
                    used_preloaded = True
                
                r = StepTester.test_step(
                    step.step_type,
                    step.config,
                    page_html=effective_page_html,
                    upstream_data=merged_upstream
                )
                r["step_id"] = step.step_id
                r["step_type"] = step.step_type
                r["step_title"] = step.title
                results.append(r)
                
                new_output = r.get("output") or {}
                last_output = new_output
                
                # 累积到 accumulated：保留每个步骤有价值的字段
                for key in ["items", "attachments", "results", "html_preview", "url", 
                            "final_url", "base_href", "containers", "mapped_items"]:
                    if key in new_output:
                        # 优先级：后面步骤的 items/attachments 覆盖前面的
                        if key in ("items", "attachments", "results", "mapped_items"):
                            accumulated[key] = new_output[key]
                        elif key in ("html_preview", "url", "final_url", "base_href"):
                            if key not in accumulated:
                                accumulated[key] = new_output[key]
                        elif key == "containers":
                            accumulated[key] = new_output[key]
                
                # 追踪最终输出（用于前端显示总结果）
                # 注意：result_preview 步骤的 items 是预览样本（可能被截断），
                #   不要用它覆盖前面 steps（如 field_mapping / detail_jump）产生的完整 items
                if r.get("success") and step.step_type != "result_preview":
                    if new_output.get("items"):
                        final_items = new_output["items"]
                    if new_output.get("attachments"):
                        final_attachments = new_output["attachments"]
                    elif new_output.get("results"):
                        final_attachments = new_output["results"]
                    
            except Exception as exc:
                _logger.exception(f"run_all 步骤失败: {step.step_type}")
                results.append({
                    "step_id": step.step_id,
                    "step_type": step.step_type,
                    "step_title": step.title,
                    "success": False,
                    "duration_ms": 0,
                    "message": f"执行异常: {exc}",
                    "output": {},
                })
                
        # 确保 final_items 是 list
        final_items_list = final_items if isinstance(final_items, list) else (
            [final_items] if final_items else []
        )
        final_attachments_list = final_attachments if isinstance(final_attachments, list) else (
            [final_attachments] if final_attachments else []
        )
                
        return {
            "success": all(r.get("success") for r in results),
            "duration_ms": sum(int(r.get("duration_ms") or 0) for r in results),
            "steps": results,
            "final_items": final_items_list,
            "final_attachments": final_attachments_list,
            "final_items_count": len(final_items_list),
            "final_attachments_count": len(final_attachments_list),
            "masked": True,
        }


def _extract_title(html: str) -> str:
    try:
        if not html:
            return ""
        import re
        m = re.search(r"<title[^>]*>([^<]*)", html, re.IGNORECASE)
        return (m.group(1) or "").strip()[:128] if m else ""
    except Exception:
        return ""


# ============================================================================
# DraftService: 草稿持久化
# ============================================================================
class DraftService:
    _fallback: Dict[str, str] = {}

    @staticmethod
    def _key(session_id: Optional[str], plan_id: Optional[str]) -> str:
        return f"crawl_steps_draft:{session_id or ''}|{plan_id or ''}"

    @staticmethod
    def save(session_id: Optional[str], plan_id: Optional[str],
              package_dict: Dict[str, Any]) -> bool:
        payload = json.dumps(package_dict, ensure_ascii=False)
        if _HAS_REDIS:
            try:
                client = get_redis()
                client.set(DraftService._key(session_id, plan_id), payload, ex=86400)
                return True
            except Exception as exc:  # pragma: no cover
                _logger.warning(f"DraftService.save Redis 失败: {exc}")
        # 退化为进程内 dict 字典保留
        DraftService._fallback[DraftService._key(session_id, plan_id)] = payload
        return False

    @staticmethod
    def load(session_id: Optional[str], plan_id: Optional[str]) -> Optional[Dict[str, Any]]:
        key = DraftService._key(session_id, plan_id)
        payload: Optional[str] = None
        if _HAS_REDIS:
            try:
                client = get_redis()
                payload = client.get(key)
                if isinstance(payload, bytes):
                    payload = payload.decode("utf-8")
            except Exception as exc:  # pragma: no cover
                _logger.warning(f"DraftService.load Redis 失败: {exc}")
        if payload is None and key in DraftService._fallback:
            payload = DraftService._fallback[key]
        if not payload:
            return None
        try:
            return json.loads(payload)
        except Exception:
            return None

    @staticmethod
    def clear(session_id: Optional[str], plan_id: Optional[str]) -> bool:
        key = DraftService._key(session_id, plan_id)
        try:
            if _HAS_REDIS:
                client = get_redis()
                client.delete(key)
            if key in DraftService._fallback:
                del DraftService._fallback[key]
            return True
        except Exception:  # pragma: no cover
            return False


# ============================================================================
# 模板查询接口
# ============================================================================
def list_templates() -> List[Dict[str, Any]]:
    """返回 STEP_TEMPLATES 的列表视图（用于前端模板选择器。"""
    out = []
    for tid, meta in STEP_TEMPLATES.items():
        out.append({
            "template_id": tid,
            "label": meta.get("label", tid),
            "step_types": [step.get("step_type") for step in meta.get("preset") or []],
        })
    return out


# ============================================================================
# VersionService：采集方案版本管理（T32）
# ============================================================================
class VersionService:
    """基于 Redis（或内存 fallback）的版本快照存储。

    约定
    ----
    * 每次调用 ``save`` 会写入一条新记录（含 version_id + timestamp）
    * ``list_versions`` 按时间倒序返回最近 20 条
    * ``rollback`` 不直接覆盖当前方案，仅返回历史快照 dict 由调用方决定是否覆盖
    """

    _KEY_PREFIX = "openclaw:plan:versions"
    _MAX_KEEP = 20

    @staticmethod
    def _key(plan_id: str) -> str:
        return f"{VersionService._KEY_PREFIX}:{plan_id}"

    @staticmethod
    def save(plan_id: str, rule_config: Dict[str, Any], *,
             operator: Optional[str] = None,
             message: Optional[str] = None) -> Dict[str, Any]:
        """保存为一个版本记录，返回版本信息。"""
        ts = int(time.time())
        version_id = f"v_{plan_id}_{ts}"
        record = {
            "version_id": version_id,
            "plan_id": plan_id,
            "timestamp": ts,
            "created_at": datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ"),
            "operator": operator or "system",
            "message": message or ("自动保存（T32编辑器修改）"),
            "rule_config": rule_config,
        }
        payload = json.dumps(record, ensure_ascii=False)
        try:
            if _HAS_REDIS:
                client = get_redis()
                client.rpush(VersionService._key(plan_id), payload)
                # 保留最近 N 条
                total = client.llen(VersionService._key(plan_id))
                if total > VersionService._MAX_KEEP:
                    client.ltrim(VersionService._key(plan_id),
                                 -VersionService._MAX_KEEP, -1)
            else:
                # 纯内存 fallback：每个 plan_id 的 list
                store = VersionService._fallback_versions()
                if plan_id not in store:
                    store[plan_id] = []
                store[plan_id].append(payload)
                lst = store[plan_id]
                if len(lst) > VersionService._MAX_KEEP:
                    del lst[:len(lst) - VersionService._MAX_KEEP]
        except Exception as exc:  # pragma: no cover
            _logger.warning(f"VersionService.save({plan_id}) 异常: {exc}")
        return record

    @staticmethod
    def _fallback_versions() -> Dict[str, List[str]]:
        if not hasattr(VersionService, "_memory_store"):
            VersionService._memory_store = {}
        return VersionService._memory_store

    @staticmethod
    def list_versions(plan_id: str) -> List[Dict[str, Any]]:
        """返回该 plan_id 的版本列表（按时间倒序）。"""
        payloads: List[str] = []
        try:
            if _HAS_REDIS:
                client = get_redis()
                payloads = list(client.lrange(VersionService._key(plan_id), 0, -1) or [])
            else:
                payloads = list(VersionService._fallback_versions().get(plan_id, []))
        except Exception as exc:  # pragma: no cover
            _logger.warning(f"VersionService.list_versions({plan_id}) 异常: {exc}")
            return []
        # 解析
        records: List[Dict[str, Any]] = []
        for p in payloads:
            if isinstance(p, bytes):
                p = p.decode("utf-8")
            try:
                records.append(json.loads(p))
            except Exception:
                continue
        # 按时间倒序
        records.sort(key=lambda r: r.get("timestamp", 0), reverse=True)
        return records

    @staticmethod
    def get_version(plan_id: str, version_id: str) -> Optional[Dict[str, Any]]:
        for r in VersionService.list_versions(plan_id):
            if r.get("version_id") == version_id:
                return r
        return None

    @staticmethod
    def rollback(plan_id: str, version_id: str) -> Dict[str, Any]:
        """把指定版本置为最前端（相当于标记为“恢复到生产”的版本记录返回）。"""
        # 实际应用：调用方读取到 record 后，替换当前 plan 的 rule_config
        # 此处仅保证能取回该版本，并额外保存一条 "rollback_to_xxx" 的版本记录
        version = VersionService.get_version(plan_id, version_id)
        if version is None:
            return {"success": False, "error": f"找不到版本 {version_id}"}
        # 额外保存一条恢复记录（审计用）
        rc = version.get("rule_config") or {}
        VersionService.save(
            plan_id, rc,
            message=f"rollback_to_{version_id}（由 T32 编辑器触发）",
        )
        return {"success": True, "version": {k: v for k, v in version.items() if k != "rule_config"},
                "rule_config": rc}

    @staticmethod
    def clear_all(plan_id: str) -> int:
        """清除该 plan_id 的所有版本（高危操作，调用方需二次确认）。"""
        try:
            if _HAS_REDIS:
                client = get_redis()
                total = client.llen(VersionService._key(plan_id))
                client.delete(VersionService._key(plan_id))
                return int(total or 0)
            store = VersionService._fallback_versions()
            total = len(store.get(plan_id, []))
            if plan_id in store:
                del store[plan_id]
            return total
        except Exception as exc:  # pragma: no cover
            _logger.warning(f"VersionService.clear_all({plan_id}) 异常: {exc}")
            return 0
