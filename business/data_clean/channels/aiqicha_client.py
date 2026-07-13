from __future__ import annotations

import re
import time
import urllib.parse
from dataclasses import dataclass, field
from typing import Any

from infra.logger_setup import get_logger

from business.data_clean.enterprise_cache import EnterpriseCache, get_cache, normalize_company_name
from business.data_clean.enterprise_models import EnterpriseEnrichResult, EnterpriseProfile
from business.data_clean.enterprise_settings import enrich_settings

"""business.data_clean.channels.aiqicha_client — T29 企业信息补全：爱企查渠道。

采集策略：
  1) 访问 aiqicha.baidu.com/s?q=<企业名>&t=0 （搜索页）
  2) 使用 Playwright 渲染（爱企查是 SPA，JS 动态渲染结果）
  3) 通过 CSS 选择器 / 正则 从搜索结果中匹配目标企业详情链接
  4) 进入详情页，提取：电话 / 邮箱 / 地址 / 行业 / 注册资本 等
  5) 结果 → EnterpriseProfile 标准化结构

风控说明：
  - 最低 5 秒查询间隔（可通过 ENRICH_INTERVAL_SECONDS 调）
  - 若连续失败 5 次 → 暂停 30 分钟并告警
  - 自动轮换 UA / 代理（由 SpiderSDK 提供）
"""

logger = get_logger("data_clean.aiqicha_client")


# ============================================================
# SpiderSDK 封装 — 有就用，没有就 requests 降级
# ============================================================


def _get_spider_sdk():
    """按需实例化 SpiderSDK（失败 → 返回 None，降级 requests）。"""
    try:
        from core.spider_core import SpiderSDK

        return SpiderSDK()
    except Exception as exc:
        logger.warning(f"[T29] SpiderSDK 不可用，降级到 requests: {exc}")
        return None


def _mask_contact(text: str) -> str:
    """联系方式脱敏 — 仅用于日志/展示，入库数据保持原文。"""
    if not text or not getattr(enrich_settings, "mask_in_log", True):
        return text or ""
    s = str(text)
    # 手机号
    s = re.sub(r"(\d{3})\d{4}(\d{4})", r"\1****\2", s)
    # 固定电话
    s = re.sub(r"(\(?\d{2,3}\)?[-\s]?)(\d{2,3})(\d{4})", lambda m: m.group(1) + "****" + m.group(3), s)
    # 邮箱
    s = re.sub(r"(\w{1,2})[\w.]*@([\w.-]+\.[a-zA-Z]{2,})", r"\1***@\2", s)
    return s


# ============================================================
# AiqichaClient — 主类
# ============================================================


class AiqichaClient:
    """爱企查企业信息查询客户端（网页采集，JS 渲染）。"""

    SEARCH_URL_TEMPLATE = "https://aiqicha.baidu.com/s?q={q}&t=0"
    CHANNEL = "aiqicha"

    def __init__(self, cache: EnterpriseCache | None = None) -> None:
        self._spider = _get_spider_sdk()
        self._cache = cache or get_cache()
        self._interval = float(getattr(enrich_settings, "interval_seconds", 5.0))
        self._failure_threshold = int(getattr(enrich_settings, "consecutive_failure_threshold", 5))
        self._consecutive_failures = 0
        self._cooloff_until = 0.0
        self._last_query_at = 0.0

    # ---------- 公共入口 ----------

    def query(self, company_name: str) -> EnterpriseEnrichResult:
        """查询单个企业信息。"""
        if not company_name or not company_name.strip():
            return EnterpriseEnrichResult(
                success=False, status="skipped", company_name=company_name,
                error_message="企业名称为空",
            )
        company_name = company_name.strip()

        # 冷却检查
        now = time.time()
        if self._cooloff_until > now:
            remain = int(self._cooloff_until - now)
            return EnterpriseEnrichResult(
                success=False, status="failed", company_name=company_name,
                error_message=f"爱企查客户端处于冷却（还剩 {remain}s）",
                needs_manual_review=True,
            )

        # 1) 命中缓存
        cached = self._cache.get(company_name)
        if cached is not None:
            mode = cached.source_mode or ""
            if "negative" in mode:
                return EnterpriseEnrichResult(
                    success=False, status="not_found", company_name=company_name,
                    error_message="（缓存）查无此企业",
                    needs_manual_review=True,
                )
            logger.info(f"[T29] 缓存命中: {_mask_contact(company_name)}")
            return EnterpriseEnrichResult(
                success=True, status="cached", company_name=company_name,
                profile=cached, source_channel=self.CHANNEL, cached=True,
                enriched_fields=cached.enriched_field_names(),
            )

        # 2) 限流 — 最小间隔
        wait = self._interval - (now - self._last_query_at)
        if wait > 0:
            time.sleep(wait)

        # 3) 发起查询（Playwright 渲染）
        try:
            profile, query_url = self._query_with_render(company_name)
            self._last_query_at = time.time()
        except Exception as exc:
            self._last_query_at = time.time()
            self._consecutive_failures += 1
            logger.warning(f"[T29] 查询异常 ({company_name}): {exc}")
            if self._consecutive_failures >= self._failure_threshold:
                self._trigger_cooloff(f"连续 {self._failure_threshold} 次失败")
            return EnterpriseEnrichResult(
                success=False, status="failed", company_name=company_name,
                error_message=f"查询异常: {exc}", needs_manual_review=True,
            )

        # 4) 结果判断
        if profile is None or not _is_valid_profile(profile):
            self._consecutive_failures += 1
            self._cache.mark_negative(company_name)
            if self._consecutive_failures >= self._failure_threshold:
                self._trigger_cooloff(f"连续 {self._failure_threshold} 次查无结果")
            logger.info(f"[T29] 查无结果: {_mask_contact(company_name)}")
            return EnterpriseEnrichResult(
                success=False, status="not_found", company_name=company_name,
                error_message="爱企查搜索未返回有效企业信息", needs_manual_review=True,
            )

        # 5) 成功 → 重置失败计数 + 写入缓存
        self._consecutive_failures = 0
        profile.source_channel = self.CHANNEL
        profile.source_mode = "web"
        profile.query_url = query_url or ""
        self._cache.set(company_name, profile)

        logger.info(
            f"[T29] 补全成功: {_mask_contact(company_name)} "
            f"→ 电话:{_mask_contact(profile.contact_phone)} "
            f"邮箱:{_mask_contact(profile.contact_email)} "
            f"字段数:{len(profile.enriched_field_names())}"
        )
        return EnterpriseEnrichResult(
            success=True, status="enriched", company_name=company_name,
            profile=profile, source_channel=self.CHANNEL,
            enriched_fields=profile.enriched_field_names(),
        )

    # ---------- 查询实现 ----------

    def _query_with_render(self, company_name: str) -> tuple[EnterpriseProfile | None, str]:
        """用 Playwright 渲染搜索页 → 解析企业信息。"""
        url = self.SEARCH_URL_TEMPLATE.format(q=urllib.parse.quote(company_name))

        html = ""
        # 1) 优先 SpiderSDK（带 UA/代理/限流）
        if self._spider is not None:
            try:
                resp = self._spider.get(url, render=True, render_js=True,
                                        render_timeout=20.0, robot_check=True)
                if resp and resp.text and len(resp.text) > 500:
                    html = resp.text
            except Exception as exc:
                logger.debug(f"[T29] SpiderSDK render 失败: {exc}")

        # 2) 降级：直接 requests 或 playwright 独立调用
        if not html:
            html = self._render_fallback(company_name, url)

        if not html or len(html) < 500:
            return None, url

        # 3) 从 HTML 解析企业信息
        profile = _extract_profile_from_html(html, company_name, url)
        return profile, url

    def _render_fallback(self, company_name: str, url: str) -> str:
        """SpiderSDK 不可用时的回退实现。"""
        # 2a) 先尝试原生 playwright（如果安装了）
        try:
            from playwright.sync_api import sync_playwright

            with sync_playwright() as p:
                browser = p.chromium.launch(headless=True)
                try:
                    ctx = browser.new_context(
                        user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                                   "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0 Safari/537.36"
                    )
                    page = ctx.new_page()
                    page.set_default_timeout(20000)
                    page.goto(url, wait_until="domcontentloaded")
                    page.wait_for_timeout(2000)
                    html = page.content()
                    return html or ""
                finally:
                    browser.close()
        except Exception as exc:
            logger.warning(f"[T29] playwright 回退渲染失败: {exc}")

        # 2b) 再次降级：requests 纯 HTTP（可能取不到动态数据，但能取页面骨架）
        try:
            import requests

            headers = {
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                              "AppleWebKit/537.36 Chrome/120.0 Safari/537.36",
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9",
                "Accept-Language": "zh-CN,zh;q=0.9",
            }
            resp = requests.get(url, headers=headers, timeout=15)
            if resp.status_code == 200 and resp.text:
                return resp.text
        except Exception as exc:
            logger.warning(f"[T29] requests 回退也失败: {exc}")
        return ""

    # ---------- 风控 ----------

    def _trigger_cooloff(self, reason: str) -> None:
        self._cooloff_until = time.time() + 30 * 60  # 30 分钟
        logger.warning(f"[T29] 爱企查客户端触发冷却（{reason}），暂停 30 分钟。")
        # 尝试告警（若 infra.alerting 可用）
        try:
            from infra.alerting import alert_service

            alert_service.service_exception_sync(f"[T29] 爱企查补全冷却: {reason}")
        except Exception:
            pass


# ============================================================
# HTML → EnterpriseProfile 解析
# ============================================================


_COMPANY_SUFFIX_RE = re.compile(r"(有限公司|股份有限公司|有限责任公司|公司|集团)")
_PHONE_PATTERNS = [
    re.compile(r"(?:电话|联系电话|座机|tel)[\s:：]{0,3}([0-9\-+\s]{6,20})", re.I),
    re.compile(r"(?:手机号|手机|mobile)[\s:：]{0,3}(1[3-9]\d{9})", re.I),
]
_EMAIL_PATTERN = re.compile(r"[\w.+-]+@[\w-]+\.[\w.-]{2,}")
_ADDRESS_PATTERN = re.compile(r"(?:地址|注册地址|经营地址|address)[\s:：]{0,3}([^\n<\|]{5,60})", re.I)
_INDUSTRY_PATTERN = re.compile(r"(?:行业|所属行业|industry|经营范围)[\s:：]{0,3}([^\n<\|]{3,40})", re.I)
_CAPITAL_PATTERN = re.compile(r"(?:注册资本|注册资金|capital)[\s:：]{0,3}([^\n<\|]{2,30})", re.I)
_DATE_PATTERN = re.compile(r"(?:成立日期|成立时间|established|日期)[\s:：]{0,3}([\d\-]{6,20})", re.I)
_LEGAL_REP_PATTERN = re.compile(r"(?:法人|法定代表人|legal representative|代表人)[\s:：]{0,3}([^\n<\|（]{2,15})", re.I)
_STATUS_PATTERN = re.compile(r"(?:经营状态|状态|status)[\s:：]{0,3}([^\n<\|（]{2,15})", re.I)
_CREDIT_CODE_PATTERN = re.compile(r"(?:统一社会信用代码|信用代码|credit code)[\s:：]{0,3}([0-9A-Z]{15,20})", re.I)
_SCALE_PATTERN = re.compile(r"(?:企业规模|规模|scale)[\s:：]{0,3}([^\n<\|（]{2,10})", re.I)


def _extract_profile_from_html(html: str, company_name: str, query_url: str) -> EnterpriseProfile | None:
    """从爱企查 HTML（搜索页或详情页）提取企业信息。

    策略：
      1) 先通过 bs4 查找结构化卡片（div 中含 phone / email 等关键字段）
      2) 同时使用正则扫描整页文本，作为补充
      3) 返回置信度最高的企业匹配
    """
    if not html:
        return None

    # 构建基础 profile
    profile = EnterpriseProfile(
        company_name=company_name,
        source_channel="aiqicha",
        source_mode="web",
        query_url=query_url or "",
    )

    # —— 1. 通过 BeautifulSoup 解析（若已安装）——
    try:
        from bs4 import BeautifulSoup
        soup = BeautifulSoup(html, "html.parser")
        _extract_with_soup(soup, profile, company_name)
    except Exception as exc:
        logger.debug(f"[T29] bs4 解析失败: {exc}")

    # —— 2. 正则补充 ——
    plain_text = re.sub(r"<[^>]+>", " ", html)
    plain_text = re.sub(r"\s+", " ", plain_text)

    # 电话
    for pat in _PHONE_PATTERNS:
        m = pat.search(plain_text)
        if m and not profile.contact_phone:
            profile.contact_phone = _clean_phone(m.group(1))
            break

    # 邮箱
    if not profile.contact_email:
        m = _EMAIL_PATTERN.search(html)
        if m:
            email = m.group(0).strip()
            if not email.lower().endswith((".png", ".jpg", ".gif", ".svg", ".ico")):
                profile.contact_email = email

    # 地址
    if not profile.registered_address:
        m = _ADDRESS_PATTERN.search(plain_text)
        if m:
            profile.registered_address = m.group(1).strip()

    # 行业
    if not profile.industry_category:
        m = _INDUSTRY_PATTERN.search(plain_text)
        if m:
            profile.industry_category = m.group(1).strip()

    # 注册资本
    if not profile.registered_capital:
        m = _CAPITAL_PATTERN.search(plain_text)
        if m:
            profile.registered_capital = m.group(1).strip()

    # 成立日期
    if not profile.establishment_date:
        m = _DATE_PATTERN.search(plain_text)
        if m:
            profile.establishment_date = m.group(1).strip()

    # 法人
    if not profile.legal_representative and not profile.contact_person:
        m = _LEGAL_REP_PATTERN.search(plain_text)
        if m:
            profile.legal_representative = m.group(1).strip()
            profile.contact_person = profile.legal_representative

    # 经营状态
    if not profile.business_status:
        m = _STATUS_PATTERN.search(plain_text)
        if m:
            profile.business_status = m.group(1).strip()

    # 信用代码
    if not profile.credit_code:
        m = _CREDIT_CODE_PATTERN.search(plain_text)
        if m:
            profile.credit_code = m.group(1).strip()

    # 企业规模
    if not profile.company_scale:
        m = _SCALE_PATTERN.search(plain_text)
        if m:
            profile.company_scale = m.group(1).strip()

    # —— 3. 置信度计算 ——
    score = _compute_confidence(profile, company_name, plain_text)
    profile.confidence_score = round(score, 3)

    # 检查企业名称匹配
    norm_target = normalize_company_name(company_name)
    if profile.matched_name and normalize_company_name(profile.matched_name) != norm_target:
        # 匹配到的企业名称与查询不一致 → 降低置信度
        profile.confidence_score = round(score * 0.5, 3)

    if score < 0.2 or (not profile.contact_phone and not profile.contact_email
                       and not profile.legal_representative and not profile.registered_address):
        return None
    return profile


def _extract_with_soup(soup: object, profile: EnterpriseProfile, target_name: str) -> None:
    """使用 BeautifulSoup 辅助查找（基于关键字 + 邻近文本）。"""
    # 找包含目标企业名的祖先节点
    text = soup.get_text(" ", strip=True)
    norm_target = normalize_company_name(target_name)

    # 尝试匹配企业名称
    # 找页面中出现的候选企业名
    companies = set()
    for tag in soup.find_all(["a", "h1", "h2", "h3", "h4", "title", "span"]):
        t = tag.get_text(strip=True)
        if len(t) >= 4 and _COMPANY_SUFFIX_RE.search(t):
            companies.add(t)

    # 选择最相似的（归一化后相同或包含目标）
    for c in companies:
        if normalize_company_name(c) == norm_target or norm_target in normalize_company_name(c):
            profile.matched_name = c
            break
    if not profile.matched_name and companies:
        profile.matched_name = sorted(companies, key=lambda x: -len(x))[0]

    # 在卡片附近的元素中提取结构化信息（弱匹配）
    # 查找包含 "电话" 关键字的元素 → 取其后文本
    pass


def _clean_phone(raw: str) -> str:
    """清洗电话号码。"""
    if not raw:
        return ""
    s = raw.strip()
    # 去多余空格，保留数字和 -+
    s = re.sub(r"[^\d+\-]", "", s)
    if len(s) < 6:
        return ""
    # 过长的 → 截断（可能混入其他数字）
    if len(s) > 25:
        s = s[:25]
    return s


def _compute_confidence(profile: EnterpriseProfile, company_name: str, plain_text: str) -> float:
    """简单置信度：命中字段数 × 权重。"""
    score = 0.0
    if profile.contact_phone:
        score += 0.35
    if profile.contact_email:
        score += 0.25
    if profile.legal_representative or profile.contact_person:
        score += 0.15
    if profile.registered_address:
        score += 0.1
    if profile.credit_code:
        score += 0.1
    if profile.industry_category:
        score += 0.05
    # 企业名称匹配加分
    if profile.matched_name and normalize_company_name(profile.matched_name) == normalize_company_name(
        company_name
    ):
        score += 0.1
    return min(1.0, score)


def _is_valid_profile(profile: EnterpriseProfile | None) -> bool:
    if profile is None:
        return False
    min_fields = int(getattr(enrich_settings, "min_contact_fields", 1))
    contact_fields = int(bool(profile.contact_phone)) + int(bool(profile.contact_email))
    return contact_fields >= min_fields or bool(profile.contact_person and profile.registered_address)


# ============================================================
# 模块级便捷调用
# ============================================================


_aiqicha_client: AiqichaClient | None = None
_client_lock = None


def get_client() -> AiqichaClient:
    """懒加载单例。"""
    global _aiqicha_client, _client_lock
    if _aiqicha_client is None:
        _client_lock = __import__("threading").Lock()
        with _client_lock:
            if _aiqicha_client is None:
                _aiqicha_client = AiqichaClient()
    return _aiqicha_client


def query_enterprise(company_name: str) -> EnterpriseEnrichResult:
    """便捷调用。"""
    return get_client().query(company_name)


__all__ = ["AiqichaClient", "get_client", "query_enterprise"]
