from __future__ import annotations

import json
import os
import re
import threading
from dataclasses import dataclass, field
from typing import Any, Iterable
from urllib.parse import urlparse

from infra.logger_setup import get_logger

logger = get_logger("data_core.blacklist")

# ============================================================
# 数据类
# ============================================================


@dataclass
class BlacklistItem:
    """单条黑名单记录。"""
    type: str  # company / phone / wechat / domain / email / keyword / user_id
    value: str
    reason: str = ""

    # user_id 类型额外需要平台信息
    platform: str | None = None


@dataclass
class BlacklistMatch:
    """单条匹配结果。"""
    clue_id: str
    item_type: str
    matched_value: str
    reason: str
    severity: str = "full"  # full / partial（完全拦截 / 部分命中扣分）


@dataclass
class BlacklistFilterResult:
    is_blocked: bool
    matches: list[BlacklistMatch] = field(default_factory=list)
    block_reason: str | None = None


# ============================================================
# 字段标准化工具
# ============================================================

def _normalize_phone(value: str) -> str:
    """标准化手机号：去空格/+/86/-/括号，只留数字。"""
    digits = re.sub(r"\D", "", value or "")
    # 去除前缀 86
    if digits.startswith("86") and len(digits) > 11:
        digits = digits[2:]
    return digits


def _normalize_wechat(value: str) -> str:
    """标准化微信号：去空格/"微信号:"/"wechat:"/"wx_" 前缀，小写。"""
    v = (value or "").strip().lower()
    for prefix in ("微信号:", "微信号：", "wechat:", "wechat_", "wx:", "wx_"):
        if v.startswith(prefix):
            v = v[len(prefix):]
            break
    return re.sub(r"\s+", "", v)


def _normalize_company_name(value: str) -> str:
    """标准化企业名称：去空格/标点，统一中文括号，小写。"""
    if not value:
        return ""
    v = value.strip().lower()
    # 统一全角括号为半角括号
    v = v.replace("（", "(").replace("）", ")")
    # 去除常见标点
    v = re.sub(r"[\s\-_,，。.!！？?\"'\\/]", "", v)
    return v


def _normalize_domain(value: str) -> str:
    """标准化域名：取 host，小写，去 www. 前缀。"""
    if not value:
        return ""
    v = value.strip().lower()
    if "://" in v:
        try:
            parsed = urlparse(v)
            v = parsed.netloc or v
        except Exception:
            pass
    v = v.split("/")[0]
    v = v.split(":")[0]  # 去掉端口
    if v.startswith("www."):
        v = v[4:]
    return v


def _normalize_email(value: str) -> str:
    """标准化邮箱：小写、去空格。"""
    return (value or "").strip().lower()


# ============================================================
# BlacklistFilter 主类
# ============================================================


class BlacklistFilter:
    """黑名单加载、匹配、过滤工具。"""

    def __init__(
        self,
        *,
        blacklist_file: str | None = None,
        items: Iterable[BlacklistItem | dict] | None = None,
    ) -> None:
        # 按类型存储
        self._by_type: dict[str, list[BlacklistItem]] = {
            "company": [],
            "phone": [],
            "wechat": [],
            "domain": [],
            "email": [],
            "keyword": [],
            "user_id": [],
        }
        # keyword 集合（O(1) 查询）
        self._keywords: list[str] = []
        # 为 company 使用 normalized 存储
        self._companies_normalized: list[tuple[str, BlacklistItem]] = []
        self._lock = threading.RLock()

        # 从文件加载
        if blacklist_file:
            try:
                self.load_file(blacklist_file)
            except Exception as exc:
                logger.warning(f"加载黑名单文件失败: {exc}")

        # 运行时注入
        if items:
            for it in items:
                try:
                    if isinstance(it, BlacklistItem):
                        self.add_item(it)
                    elif isinstance(it, dict):
                        self.add_item(
                            BlacklistItem(
                                type=it.get("type", "keyword"),
                                value=it.get("value", ""),
                                reason=it.get("reason", ""),
                                platform=it.get("platform"),
                            )
                        )
                except Exception as exc:
                    logger.warning(f"添加黑名单项异常: {exc}")

    # ------------------------ 加载 ------------------------

    def load_file(self, file_path: str) -> int:
        """从文件加载，返回新增数量。支持 JSON 数组与 TXT 两种格式。"""
        if not file_path or not os.path.exists(file_path):
            return 0
        with open(file_path, "r", encoding="utf-8") as f:
            content = f.read().strip()
        if not content:
            return 0
        # 尝试 JSON 数组
        items: list[BlacklistItem] = []
        if content.startswith("["):
            try:
                raw_items = json.loads(content)
                for raw in raw_items:
                    if isinstance(raw, dict):
                        items.append(
                            BlacklistItem(
                                type=raw.get("type", "keyword"),
                                value=str(raw.get("value", "")),
                                reason=str(raw.get("reason", "")),
                                platform=raw.get("platform"),
                            )
                        )
                    elif isinstance(raw, str):
                        # 纯字符串视为 keyword
                        items.append(BlacklistItem(type="keyword", value=raw))
            except json.JSONDecodeError:
                # 回退为 TXT 解析
                items = list(self._parse_txt(content))
        else:
            items = list(self._parse_txt(content))

        count = 0
        with self._lock:
            for it in items:
                if self.add_item(it, _locked=True):
                    count += 1
        logger.info(f"黑名单加载完成：新增 {count} 条（来自 {file_path}）")
        return count

    @staticmethod
    def _parse_txt(content: str) -> Iterable[BlacklistItem]:
        """TXT 格式解析。支持以下前缀：wechat:/phone:/company:/domain:/email:/user_id:
        无前缀默认 keyword。以 '#' 开头行视为注释。"""
        for line in content.splitlines():
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            lower = line.lower()
            # 识别前缀
            for prefix, item_type in (
                ("company:", "company"),
                ("phone:", "phone"),
                ("wechat:", "wechat"),
                ("domain:", "domain"),
                ("email:", "email"),
                ("user_id:", "user_id"),
                ("keyword:", "keyword"),
            ):
                if lower.startswith(prefix):
                    v = line[len(prefix):].strip()
                    if v:
                        # 可选：" value, reason" 或 " value|reason"
                        for sep in (",", "|", ";"):
                            if sep in v:
                                parts = [x.strip() for x in v.split(sep, 1)]
                                yield BlacklistItem(type=item_type, value=parts[0], reason=parts[1])
                                break
                        else:
                            yield BlacklistItem(type=item_type, value=v)
                    break
            else:
                # 无前缀 → keyword
                for sep in (",", "|", ";"):
                    if sep in line:
                        parts = [x.strip() for x in line.split(sep, 1)]
                        yield BlacklistItem(type="keyword", value=parts[0], reason=parts[1])
                        break
                else:
                    yield BlacklistItem(type="keyword", value=line)

    # ------------------------ 运行时添加 ------------------------

    def add_item(self, item: BlacklistItem, *, _locked: bool = False) -> bool:
        """返回是否实际新增（已存在相同 value + type 则忽略）。"""
        if not item or not item.value:
            return False
        item_type = (item.type or "keyword").lower()
        if item_type not in self._by_type:
            item_type = "keyword"
        item.type = item_type

        def _add() -> bool:
            # 判重
            if item_type in ("phone",):
                norm = _normalize_phone(item.value)
                if any(_normalize_phone(existing.value) == norm for existing in self._by_type[item_type]):
                    return False
            elif item_type == "wechat":
                norm = _normalize_wechat(item.value)
                if any(_normalize_wechat(existing.value) == norm for existing in self._by_type[item_type]):
                    return False
            elif item_type == "company":
                norm = _normalize_company_name(item.value)
                if any(existing_norm == norm for existing_norm, _ in self._companies_normalized):
                    return False
            elif item_type == "email":
                norm = _normalize_email(item.value)
                if any(_normalize_email(existing.value) == norm for existing in self._by_type[item_type]):
                    return False
            elif item_type == "domain":
                norm = _normalize_domain(item.value)
                if any(_normalize_domain(existing.value) == norm for existing in self._by_type[item_type]):
                    return False
            elif item_type == "user_id":
                key = (item.platform or "", item.value)
                if any(
                    (existing.platform or "") == key[0] and existing.value == key[1]
                    for existing in self._by_type[item_type]
                ):
                    return False
            else:  # keyword
                if any(existing.value == item.value for existing in self._by_type[item_type]):
                    return False

            self._by_type[item_type].append(item)
            if item_type == "keyword":
                self._keywords.append(item.value.lower())
            if item_type == "company":
                self._companies_normalized.append((_normalize_company_name(item.value), item))
            return True

        if _locked:
            return _add()
        with self._lock:
            return _add()

    # ------------------------ 匹配 ------------------------

    def match(self, clue: dict[str, Any]) -> list[BlacklistMatch]:
        """对单条线索执行匹配，返回所有命中项（含 full / partial）。"""
        if not clue or not isinstance(clue, dict):
            return []
        clue_id = str(clue.get("clue_id") or clue.get("id") or id(clue))
        results: list[BlacklistMatch] = []

        with self._lock:
            # phone 维度
            phones = _as_list(clue.get("contact_phone")) + _as_list(clue.get("phone"))
            if phones:
                for phone in phones:
                    norm = _normalize_phone(str(phone))
                    if not norm:
                        continue
                    for bl in self._by_type["phone"]:
                        if _normalize_phone(bl.value) == norm:
                            results.append(BlacklistMatch(
                                clue_id=clue_id, item_type="phone",
                                matched_value=bl.value, reason=bl.reason, severity="full",
                            ))
                            break

            # wechat 维度
            wechats = _as_list(clue.get("contact_wechat")) + _as_list(clue.get("wechat"))
            if wechats:
                for wx in wechats:
                    norm = _normalize_wechat(str(wx))
                    if not norm:
                        continue
                    for bl in self._by_type["wechat"]:
                        if _normalize_wechat(bl.value) == norm:
                            results.append(BlacklistMatch(
                                clue_id=clue_id, item_type="wechat",
                                matched_value=bl.value, reason=bl.reason, severity="full",
                            ))
                            break

            # company 维度（包含匹配）
            company = clue.get("company_name") or clue.get("company")
            if company:
                norm_company = _normalize_company_name(str(company))
                if norm_company:
                    for norm, bl in self._companies_normalized:
                        if norm and (norm == norm_company or norm in norm_company or norm_company in norm):
                            results.append(BlacklistMatch(
                                clue_id=clue_id, item_type="company",
                                matched_value=bl.value, reason=bl.reason, severity="full",
                            ))

            # domain 维度（source_url）
            url = clue.get("source_url") or clue.get("url")
            if url:
                norm_url = _normalize_domain(str(url))
                if norm_url:
                    for bl in self._by_type["domain"]:
                        norm_bl = _normalize_domain(bl.value)
                        if norm_bl and (norm_bl == norm_url or norm_url.endswith("." + norm_bl)):
                            results.append(BlacklistMatch(
                                clue_id=clue_id, item_type="domain",
                                matched_value=bl.value, reason=bl.reason, severity="full",
                            ))
                            break

            # email 维度
            email = clue.get("email") or clue.get("contact_email")
            if email:
                norm_email = _normalize_email(str(email))
                if norm_email:
                    for bl in self._by_type["email"]:
                        if _normalize_email(bl.value) == norm_email:
                            results.append(BlacklistMatch(
                                clue_id=clue_id, item_type="email",
                                matched_value=bl.value, reason=bl.reason, severity="full",
                            ))
                            break

            # user_id 维度
            user_id = clue.get("user_id")
            platform = clue.get("source_platform") or clue.get("platform") or ""
            if user_id:
                key_user = (str(platform), str(user_id))
                for bl in self._by_type["user_id"]:
                    if (str(bl.platform or "") == key_user[0]) and bl.value == key_user[1]:
                        results.append(BlacklistMatch(
                            clue_id=clue_id, item_type="user_id",
                            matched_value=bl.value, reason=bl.reason, severity="full",
                        ))
                        break

            # keyword 维度：在需求文本 + 公司名中搜索
            texts: list[str] = []
            for key in ("requirement_text", "requirement", "company_name", "company"):
                v = clue.get(key)
                if v:
                    texts.append(str(v).lower())
            combined = " ".join(texts)
            if combined:
                for kw in self._keywords:
                    if not kw:
                        continue
                    if kw in combined:
                        # keyword 命中 → partial（仅扣分，不直接拦截）
                        results.append(BlacklistMatch(
                            clue_id=clue_id, item_type="keyword",
                            matched_value=kw, reason="keyword_hit", severity="partial",
                        ))

        return results

    # ------------------------ 批处理 ------------------------

    def filter_batch(self, clues: list[dict[str, Any]]) -> list[BlacklistFilterResult]:
        """对线索列表批量过滤。返回每条线索的匹配结果列表。"""
        results: list[BlacklistFilterResult] = []
        for clue in clues:
            matches = self.match(clue)
            is_blocked = any(m.severity == "full" for m in matches)
            reasons = [m.reason or m.item_type for m in matches if m.severity == "full"]
            results.append(BlacklistFilterResult(
                is_blocked=is_blocked,
                matches=matches,
                block_reason="; ".join(reasons) if reasons else None,
            ))
        return results

    # ------------------------ 状态查询 ------------------------

    def size(self) -> dict[str, int]:
        with self._lock:
            return {k: len(v) for k, v in self._by_type.items()}


# ============================================================
# 辅助
# ============================================================


def _as_list(value: Any) -> list[Any]:
    if value is None:
        return []
    if isinstance(value, (list, tuple)):
        return [v for v in value if v is not None]
    return [value]


# ============================================================
# 模块级实例（从 .env 加载文件路径）
# ============================================================


def _build_default_filter() -> BlacklistFilter:
    file_path = os.environ.get("BLACKLIST_FILE") or None
    return BlacklistFilter(blacklist_file=file_path)


blacklist_filter: BlacklistFilter
try:
    blacklist_filter = _build_default_filter()
except Exception as exc:
    logger.warning(f"默认 BlacklistFilter 初始化失败: {exc}")
    blacklist_filter = BlacklistFilter()


__all__ = [
    "BlacklistItem",
    "BlacklistMatch",
    "BlacklistFilterResult",
    "BlacklistFilter",
    "blacklist_filter",
]
