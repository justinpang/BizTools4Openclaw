from __future__ import annotations

import json
import os
import re
import threading
from typing import Any

from infra.logger_setup import get_logger

logger = get_logger("compliance.privacy_stripper")


def _normalize_key(key: str) -> str:
    return re.sub(r"[\s_\-\.:/\\]", "", str(key)).lower()


_DEFAULT_PRIVACY_KEYS = {
    "phone", "mobile", "tel", "telephone", "手机号", "电话",
    "wechat", "weixin", "微信",
    "qq",
    "email", "mail", "邮箱",
    "idcard", "idnumber", "身份证",
    "bankcard", "cardnumber", "银行卡",
    "nickname", "nick", "昵称", "用户名",
    "realname", "真实姓名",
    "company", "companyname", "企业名称",
    "address", "地址",
    "contact", "contactinfo", "contactperson", "联系方式", "联系人",
    "username",
    "password", "pwd", "passwd", "secret", "apikey", "token", "cookie",
}

_DEFAULT_PRESERVE_KEYS: set[str] = set()


class PrivacyStripper:
    """隐私字段自动剔除 / 掩码工具。

    - dict：对 key 做归一化匹配，命中时直接删除或掩码
    - list/tuple：递归
    - str：做正则驱动的掩码
    """

    def __init__(
        self,
        *,
        pii_mask: Any | None = None,
        strip_keys: list[str] | None = None,
        preserve_keys: list[str] | None = None,
        keep_masked: bool = True,
    ) -> None:
        self._pii_mask = pii_mask
        self._keep_masked = bool(keep_masked)
        self._extra_keys: set[str] = set()
        if strip_keys:
            for k in strip_keys:
                if k:
                    self._extra_keys.add(_normalize_key(k))
        self._preserve_keys: set[str] = set()
        if preserve_keys:
            for k in preserve_keys:
                if k:
                    self._preserve_keys.add(_normalize_key(k))
        self._lock = threading.RLock()

    # ---------- 公开 API ----------

    def strip(self, data: Any, *, mode: str = "auto") -> Any:
        """mode ∈ {"auto", "strip", "mask"}。"""
        return self._strip_impl(data, mode=mode)

    def scan_report(self, data: Any) -> dict:
        """返回扫描报告：{stripped_keys, masked_values, total_hits}。"""
        report = {"stripped_keys": [], "masked_values": [], "total_hits": 0}
        self._scan_impl(data, report)
        return report

    # ---------- 内部实现 ----------

    def _is_privacy_key(self, key: str) -> bool:
        nk = _normalize_key(key)
        if not nk:
            return False
        if nk in self._preserve_keys:
            return False
        if nk in self._extra_keys:
            return True
        # 前缀 / 包含匹配
        for pk in _DEFAULT_PRIVACY_KEYS | self._extra_keys:
            if pk and (nk == pk or nk.startswith(pk) or pk in nk):
                return True
        return False

    def _strip_impl(self, data: Any, *, mode: str) -> Any:
        if data is None:
            return None
        if isinstance(data, bool):
            return data
        if isinstance(data, (int, float)):
            return data
        if isinstance(data, str):
            # PrivacyStripper 只做字段级别的剔除/掩码；
            # 内容级别的隐私字符串替换由 PIIMask.auto_mask / compliance_checker 负责。
            # 此处保持字符串原样返回，避免过度处理。
            return data
        if isinstance(data, dict):
            result: dict[Any, Any] = {}
            for k, v in data.items():
                if isinstance(k, str) and self._is_privacy_key(k):
                    if mode == "strip" or (mode == "auto" and not self._keep_masked):
                        continue  # 直接删除字段
                    # mask 模式：对 value 做字段级脱敏
                    if self._pii_mask is not None and hasattr(self._pii_mask, "_mask_by_key"):
                        result[k] = self._pii_mask._mask_by_key(k, v)
                    elif isinstance(v, str):
                        result[k] = self._mask_char_by_length(v)
                    else:
                        result[k] = None
                else:
                    # 非隐私字段：保留结构递归，不触碰字符串内容
                    result[k] = self._strip_impl(v, mode=mode)
            return result
        if isinstance(data, list):
            return [self._strip_impl(item, mode=mode) for item in data]
        if isinstance(data, tuple):
            return tuple(self._strip_impl(item, mode=mode) for item in data)
        return data

    def _mask_char_by_length(self, s: str) -> str:
        return "*" * max(8, min(len(s), 16))

    def _scan_impl(self, data: Any, report: dict) -> None:
        if data is None:
            return
        if isinstance(data, dict):
            for k, v in data.items():
                if isinstance(k, str) and self._is_privacy_key(k):
                    report["stripped_keys"].append(k)
                    report["total_hits"] += 1
                else:
                    self._scan_impl(v, report)
        elif isinstance(data, (list, tuple)):
            for item in data:
                self._scan_impl(item, report)


# 模块级单例（从 .env 加载）
def _build_default_stripper() -> PrivacyStripper:
    from core.compliance.pii_mask import pii_mask
    keep_masked_str = (os.environ.get("PRIVACY_KEEP_MASKED", "true") or "true").strip().lower()
    keep_masked = keep_masked_str not in {"false", "0", "no", "off"}

    strip_keys: list[str] = []
    raw_strip = os.environ.get("PRIVACY_STRIP_KEYS_JSON", "")
    if raw_strip:
        try:
            parsed = json.loads(raw_strip)
            if isinstance(parsed, list):
                strip_keys = [str(k) for k in parsed if k]
        except json.JSONDecodeError:
            logger.warning("PRIVACY_STRIP_KEYS_JSON 解析失败，忽略")

    preserve_keys: list[str] = []
    raw_preserve = os.environ.get("PRIVACY_PRESERVE_KEYS_JSON", "")
    if raw_preserve:
        try:
            parsed = json.loads(raw_preserve)
            if isinstance(parsed, list):
                preserve_keys = [str(k) for k in parsed if k]
        except json.JSONDecodeError:
            logger.warning("PRIVACY_PRESERVE_KEYS_JSON 解析失败，忽略")

    return PrivacyStripper(
        pii_mask=pii_mask,
        strip_keys=strip_keys,
        preserve_keys=preserve_keys,
        keep_masked=keep_masked,
    )


privacy_stripper: PrivacyStripper | None = None
try:
    privacy_stripper = _build_default_stripper()
except Exception as exc:
    logger.warning(f"默认 PrivacyStripper 初始化失败: {exc}")
    privacy_stripper = PrivacyStripper()


__all__ = ["PrivacyStripper", "privacy_stripper"]
