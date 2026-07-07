"""core/spider_core/rule_engine — 规则化采集执行引擎。

核心执行链路（按 CrawlRuleSet 配置）：

  [阶段 1：列表页采集]
    ├─ 按 list_rule.url_template 组装 URL（支持 {page}, {keyword} 占位符）
    ├─ 使用 SpiderSDK.get(...) 抓取列表页（含代理/UA/限流/风控/robots）
    ├─ 按 list_rule.item_selector 解析每条列表项
    ├─ 从每条 item 提取 detail_link（按 link_selector + link_attribute）
    └─ 分页循环：next_button 点击 / page_param 递增，直到 max_pages

  [阶段 2：详情页采集]
    ├─ 对每个 detail_url 执行 sdk.get(...)
    ├─ 按 detail_rule.fields 提取字段（CSS / XPath / Regex / Text）
    ├─ 必填字段校验 → 缺失告警
    └─ field_mapping 重命名 → 业务字段输出

  [阶段 3：附件解析（可选）]
    ├─ 在详情页 DOM 中按 attachment_rule.link_selector 提取附件
    ├─ AttachmentParser.parse_batch 下载 + 解析
    └─ 文本/表格 拼接到 items 的 attachments 字段

  [阶段 4：合规预检（可选）]
    ├─ 对 content/title 文本字段执行 PII mask
    └─ 写回 item["_compliance"] 元信息

  [阶段 5：增量去重]
    └─ 按 dedup_mode（url / field / none）判重，重复项跳过

  [阶段 6：告警统计]
    └─ 字段匹配率、失败率、阈值触发告警

整个引擎对上层仅暴露一个入口：run(CrawlRuleSet) -> EngineResult。
"""

from __future__ import annotations

import time as _time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from infra.logger_setup import get_logger
from core.spider_core.config import enhanced_config
from core.spider_core.dedup_store import DedupStore, get_dedup_store
from core.spider_core.alert_manager import AlertManager, get_alert_manager
from core.spider_core.field_extractor import FieldExtractor
from core.spider_core.attachment_parser import AttachmentParser, get_attachment_parser
from core.spider_core.rule_models import CrawlRuleSet, ListRule, DetailRule, AttachmentRule

try:
    from bs4 import BeautifulSoup
    _HAS_BS4 = True
except Exception:
    _HAS_BS4 = False

logger = get_logger("spider.rule_engine")


# =========================================================================
# EngineResult
# =========================================================================

@dataclass
class EngineResult:
    task_id: str
    total_pages_crawled: int = 0
    total_items: int = 0
    success_items: int = 0
    failed_items: int = 0
    items: List[Dict[str, Any]] = field(default_factory=list)
    attachments: List[Any] = field(default_factory=list)
    field_match_rate: float = 0.0
    failure_rate: float = 0.0
    alerts: List[Any] = field(default_factory=list)
    elapsed_ms: int = 0
    errors: List[str] = field(default_factory=list)


# =========================================================================
# RuleCrawlEngine
# =========================================================================

class RuleCrawlEngine:
    """规则化采集执行器。"""

    def __init__(
        self,
        *,
        sdk=None,
        dedup_store: Optional[DedupStore] = None,
        alert_manager: Optional[AlertManager] = None,
        field_extractor: Optional[FieldExtractor] = None,
        attachment_parser: Optional[AttachmentParser] = None,
    ) -> None:
        self._cfg = enhanced_config()
        if sdk is None:
            from core.spider_core.sdk import SpiderSDK
            sdk = SpiderSDK()
        self._sdk = sdk
        self._dedup = dedup_store or get_dedup_store()
        self._alert = alert_manager or get_alert_manager()
        self._extractor = field_extractor or FieldExtractor()
        self._attachment = attachment_parser or get_attachment_parser()

    # ---------- 主入口 ----------

    def run(self, rule: Any, *, task_id: Optional[str] = None) -> EngineResult:
        start = _time.monotonic()
        task_id = task_id or getattr(rule, "task_id", None) or f"task_{int(_time.time())}"
        result = EngineResult(task_id=task_id)

        if not isinstance(rule, CrawlRuleSet):
            # 尝试从 dict 构造（便于外部 JSON 规则直接传入）
            try:
                if isinstance(rule, dict):
                    rule = CrawlRuleSet.model_validate(rule)
                else:
                    raise ValueError(f"rule 类型不支持: {type(rule)}")
            except Exception as exc:
                result.errors.append(f"规则解析失败: {exc}")
                result.elapsed_ms = int((_time.monotonic() - start) * 1000)
                return result

        max_items = int(getattr(rule, "max_items", 1000) or 1000)
        retry_count = int(getattr(rule, "retry_count", 3) or 0)
        retry_backoff = float(getattr(rule, "retry_backoff_sec", 2.0) or 2.0)
        match_rate_threshold = float(getattr(rule, "match_rate_threshold", 0.5) or 0.5)
        failure_rate_threshold = float(getattr(rule, "failure_rate_threshold", 0.3) or 0.3)
        compliance_check = bool(getattr(rule, "compliance_check", True))
        list_rule: ListRule = rule.list_rule  # type: ignore
        detail_rule: Optional[DetailRule] = getattr(rule, "detail_rule", None)
        attachment_rule: Optional[AttachmentRule] = getattr(rule, "attachment_rule", None)
        field_mapping: Dict[str, str] = dict(getattr(rule, "field_mapping", {}) or {})
        dedup_mode = str(getattr(rule, "dedup_mode", "url") or "url")
        dedup_fields = list(getattr(rule, "dedup_fields", []) or [])

        # ================ 阶段 1：列表页抓取 + 详情链接提取 ================
        detail_urls: List[str] = []
        seen_urls: set = set()
        page_idx = 0
        max_pages = int(getattr(list_rule, "max_pages", 10) or 1)
        use_render = bool(getattr(list_rule, "use_render", False))

        while page_idx < max_pages:
            page_url = self._render_url_template(
                list_rule.url_template, page=page_idx + 1, keyword=""
            )
            list_html = self._fetch_with_retry(
                page_url, render=use_render, task_id=task_id,
                retry_count=retry_count, backoff=retry_backoff, result=result,
            )
            result.total_pages_crawled += 1

            if list_html:
                urls_from_page = self._extract_detail_urls(
                    list_html, list_rule, base_url=page_url
                )
                for u in urls_from_page:
                    if u and u not in seen_urls:
                        seen_urls.add(u)
                        detail_urls.append(u)
                        if len(detail_urls) >= max_items * 2:  # 留冗余但不溢出
                            break

            # 翻页
            pagination = getattr(list_rule, "pagination", None)
            if pagination is None:
                break
            page_param_name = getattr(pagination, "page_param_name", None)
            if page_param_name:
                page_idx += 1
                continue
            next_selector = getattr(pagination, "next_selector", None)
            if next_selector and _HAS_BS4:
                try:
                    soup = BeautifulSoup(list_html or "", "html.parser")
                    nxt = soup.select_one(next_selector)
                    if nxt and nxt.get("href"):
                        page_idx += 1
                        # 下次循环将使用更新后的 url_template
                        list_rule.url_template = nxt.get("href") or list_rule.url_template
                        continue
                except Exception as exc:
                    logger.warning(f"翻页选择器失败 {next_selector}: {exc}")
            break

        logger.info(f"[{task_id}] 从 {result.total_pages_crawled} 个列表页提取到 {len(detail_urls)} 个详情链接")

        if not detail_urls:
            result.elapsed_ms = int((_time.monotonic() - start) * 1000)
            result.errors.append("未从列表页提取到任何详情链接")
            return result

        # ================ 阶段 2-3：详情页采集 + 字段提取 + 附件解析 ================
        total_fields = 0
        matched_fields = 0

        for detail_url in detail_urls:
            if result.total_items >= max_items:
                break

            # 去重
            if self._should_skip(detail_url, dedup_mode, dedup_fields, task_id, {}):
                continue

            detail_html = self._fetch_with_retry(
                detail_url,
                render=bool(getattr(detail_rule, "use_render", False)) if detail_rule else False,
                task_id=task_id,
                retry_count=retry_count,
                backoff=retry_backoff,
                result=result,
            )
            if not detail_html:
                result.failed_items += 1
                continue

            item: Dict[str, Any] = {"_source_url": detail_url, "_fetched_at": _time.time()}

            if detail_rule and detail_rule.fields:
                extracted = self._extractor.extract(detail_html, detail_rule.fields)
                for field_name, value in extracted.items():
                    total_fields += 1
                    if value.matched:
                        matched_fields += 1
                        key = field_mapping.get(field_name, field_name)
                        item[key] = value.cleaned
                    else:
                        if getattr([f for f in detail_rule.fields if getattr(f, "name", "") == field_name][0],
                                   "required", False):
                            self._alert.record(
                                task_id=task_id, level="warning", category="parse",
                                message=f"必填字段 '{field_name}' 未匹配 (url: {detail_url[:80]})",
                            )

            # 附件解析
            if attachment_rule:
                try:
                    att_urls = self._extract_attachment_urls(detail_html, attachment_rule, base_url=detail_url)
                    attachments = self._attachment.parse_batch(
                        att_urls,
                        max_items=int(getattr(attachment_rule, "max_attachments_per_page", 10) or 10),
                        task_id=task_id,
                    )
                    item["_attachments"] = [
                        {
                            "url": a.source_url,
                            "filename": a.filename,
                            "text": (a.text or "")[:2000],
                            "table_count": len(getattr(a, "tables", [])),
                            "parse_status": a.parse_status,
                            "ocr_applied": a.ocr_applied,
                        }
                        for a in attachments
                    ]
                    result.attachments.extend(attachments)
                except Exception as exc:
                    logger.warning(f"附件解析失败: {exc}")
                    self._alert.record(
                        task_id=task_id, level="warning", category="attachment",
                        message=f"附件解析异常: {exc}",
                    )

            # 合规预检（PII mask）
            if compliance_check and self._cfg.pii_mask:
                from core.spider_core.field_extractor import apply_cleaners
                for k in list(item.keys()):
                    if isinstance(item[k], str):
                        item[k] = apply_cleaners(item[k], ["remove_pii"])

            # dedup 写入
            self._dedup.mark(task_id, self._dedup_key(detail_url, item, dedup_mode, dedup_fields))

            result.items.append(item)
            result.total_items += 1
            result.success_items += 1

        # ================ 阶段 6：统计 + 告警 ================
        result.field_match_rate = (matched_fields / total_fields) if total_fields > 0 else 0.0
        total_attempts = result.success_items + result.failed_items
        result.failure_rate = (result.failed_items / total_attempts) if total_attempts > 0 else 0.0

        self._alert.check_thresholds(
            task_id=task_id,
            field_match_rate=result.field_match_rate,
            failure_rate=result.failure_rate,
            match_rate_threshold=match_rate_threshold,
            failure_rate_threshold=failure_rate_threshold,
        )
        result.alerts = self._alert.flush(task_id)

        result.elapsed_ms = int((_time.monotonic() - start) * 1000)
        logger.info(
            f"[{task_id}] 完成: items={result.success_items}/{result.total_items}, "
            f"failed={result.failed_items}, match_rate={result.field_match_rate:.0%}, "
            f"耗时={result.elapsed_ms}ms"
        )
        return result

    # ---------- helpers ----------

    def _render_url_template(self, template: str, *, page: int, keyword: str) -> str:
        url = template
        url = url.replace("{page}", str(page))
        url = url.replace("{keyword}", keyword)
        # 兼容更灵活的占位符：{page_offset}, {start}
        url = url.replace("{page_offset}", str(max(0, (page - 1) * 20)))
        url = url.replace("{start}", str(max(0, (page - 1) * 20)))
        return url

    def _fetch_with_retry(
        self,
        url: str,
        *,
        render: bool,
        task_id: str,
        retry_count: int,
        backoff: float,
        result: EngineResult,
    ) -> str:
        last_error: Optional[str] = None
        for attempt in range(max(1, retry_count + 1)):
            try:
                resp = self._sdk.get(url, render=render, task_id=task_id)
                if resp.error:
                    last_error = resp.error
                    _time.sleep(backoff * (2 ** attempt))
                    continue
                if not resp.text and not resp.content:
                    last_error = "empty response"
                    _time.sleep(backoff * (2 ** attempt))
                    continue
                return resp.text or (resp.content.decode("utf-8", errors="ignore") if isinstance(resp.content, bytes) else "")
            except Exception as exc:
                last_error = str(exc)
                logger.warning(f"请求失败 {url} (尝试 {attempt+1}): {exc}")
                _time.sleep(backoff * (2 ** attempt))
        if last_error:
            result.errors.append(f"{url}: {last_error}")
        return ""

    def _extract_detail_urls(self, html: str, list_rule: ListRule, base_url: str) -> List[str]:
        out: List[str] = []
        if not _HAS_BS4:
            # 降级：正则提取所有 href
            import re
            for m in re.finditer(r'''href\s*=\s*["']([^"']+)["']''', html):
                out.append(_resolve_url(m.group(1), base_url))
            return out
        try:
            soup = BeautifulSoup(html, "html.parser")
            for item in soup.select(list_rule.item_selector):
                link_el = item.select_one(list_rule.link_selector) if list_rule.link_selector else item
                if link_el is None:
                    continue
                attr = list_rule.link_attribute or "href"
                href = link_el.get(attr, "") if hasattr(link_el, "get") else ""
                if not href:
                    continue
                out.append(_resolve_url(href, base_url))
        except Exception as exc:
            logger.warning(f"列表项解析失败 '{list_rule.item_selector}': {exc}")
        return out

    def _extract_attachment_urls(self, html: str, attachment_rule: AttachmentRule, base_url: str) -> List[str]:
        out: List[str] = []
        if not _HAS_BS4:
            return out
        try:
            soup = BeautifulSoup(html, "html.parser")
            for el in soup.select(attachment_rule.link_selector):
                href = el.get(attachment_rule.link_attribute or "href") or ""
                if not href:
                    continue
                out.append(_resolve_url(href, base_url))
        except Exception as exc:
            logger.warning(f"附件链接解析失败: {exc}")
        return out

    def _should_skip(
        self,
        detail_url: str,
        mode: str,
        dedup_fields: List[str],
        task_id: str,
        item: Dict[str, Any],
    ) -> bool:
        if mode == "none":
            return False
        if mode == "url":
            return self._dedup.check_and_mark(task_id, detail_url)
        if mode == "field" and dedup_fields:
            key = "|".join(str(item.get(f, "")) for f in dedup_fields)
            return self._dedup.check_and_mark(task_id, key)
        return False

    def _dedup_key(self, detail_url: str, item: Dict[str, Any], mode: str, fields: List[str]) -> str:
        if mode == "field" and fields:
            return "|".join(str(item.get(f, "")) for f in fields)
        return detail_url


def _resolve_url(href: str, base_url: str) -> str:
    if not href:
        return ""
    if href.startswith(("http://", "https://")):
        return href
    if href.startswith("//"):
        return "https:" + href
    # 相对路径
    if href.startswith("/"):
        from urllib.parse import urlparse
        parsed = urlparse(base_url)
        return f"{parsed.scheme}://{parsed.netloc}{href}"
    # 同级路径
    if base_url.endswith("/"):
        return base_url + href
    return base_url.rsplit("/", 1)[0] + "/" + href


# 模块级便捷入口
_default_engine: Optional[RuleCrawlEngine] = None


def run_rule(rule: Any, *, task_id: Optional[str] = None) -> EngineResult:
    global _default_engine
    if _default_engine is None:
        _default_engine = RuleCrawlEngine()
    return _default_engine.run(rule, task_id=task_id)


__all__ = ["EngineResult", "RuleCrawlEngine", "run_rule"]
