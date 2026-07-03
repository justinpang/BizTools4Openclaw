from __future__ import annotations

import json
import os
import re
import threading
from typing import Any, Iterable

from infra.logger_setup import get_logger

logger = get_logger("compliance.pii_mask")


# =====================
# 正则常量（预编译）
# =====================

_PHONE_RE = re.compile(r"(?<!\d)(1[3-9]\d{9})(?!\d)")
_LANDLINE_RE = re.compile(r"(?<!\d)(\(?0\d{2,3}\)?[-\s]?)(\d{7,8})(?!\d)")
_EMAIL_RE = re.compile(r"([A-Za-z0-9._%+\-]+)@([A-Za-z0-9.\-]+\.[A-Za-z]{2,})")
_ID_CARD_RE = re.compile(r"(?<!\d)(\d{6})(\d{8})(\d{3}[\dXx])(?!\d)")
_BANK_CARD_RE = re.compile(r"(?<!\d)(\d{6})(\d{6,12})(\d{4})(?!\d)")
_QQ_RE = re.compile(r"(?<!\d)([1-9]\d{4,11})(?!\d)")
_WECHAT_LIKE_RE = re.compile(r"\b(weixin|wechat|wx_?|微信号[:：]?)\s*([A-Za-z0-9_\-]{5,30})", re.IGNORECASE)

# key 名称识别（大小写不敏感、下划线/驼峰统一）
_PRIVACY_KEY_PATTERNS = [
    "phone", "mobile", "tel", "telephone", "手机号", "电话",
    "wechat", "wx", "weixin", "微信",
    "qq", "qq_id",
    "email", "mail", "邮箱",
    "id_card", "idcard", "id_number", "身份证",
    "bank_card", "card_number", "银行卡",
    "nickname", "nick_name", "用户名", "昵称",
    "real_name", "realname", "真实姓名",
    "company", "company_name", "企业名称",
    "address", "地址",
    "contact", "contact_info", "contact_person", "联系方式", "联系人",
    "user_name", "username",
    "password", "pwd", "passwd", "secret", "api_key", "token", "cookie",
]


def _normalize_key(key: str) -> str:
    """把 key 归一化成小写 + 去除非字母数字的简式，便于前缀/包含匹配。"""
    return re.sub(r"[\s_\-\.:/\\]", "", str(key)).lower()


_NORMALIZED_PRIVACY_KEYS = {_normalize_key(k) for k in _PRIVACY_KEY_PATTERNS}


# =====================
# PIIMask 类
# =====================

class PIIMask:
    """隐私字段脱敏工具。

    - 单个字段提供 mask_phone/mask_landline/mask_wechat/mask_qq/
      mask_email/mask_id_card/mask_nickname/mask_company/mask_bank_card/mask_url
    - auto_mask 自动识别 key 或正则匹配字符串并脱敏
    - detect_pii 仅识别不修改，返回命中明细
    """

    _instance = None
    _instance_lock = threading.Lock()

    def __init__(
        self,
        *,
        mask_char: str = "*",
        mask_short_length: int = 8,
        custom_pii_keys: Iterable[str] | None = None,
    ) -> None:
        self._mask_char = mask_char or "*"
        self._mask_len = int(mask_short_length) if mask_short_length and mask_short_length > 0 else 8
        self._extra_keys: set[str] = set()
        if custom_pii_keys:
            for k in custom_pii_keys:
                if k:
                    self._extra_keys.add(_normalize_key(k))

    # --------- 基础字段 ----------

    def mask_phone(self, value: str) -> str:
        """138****8000 格式。"""
        if not value:
            return ""
        text = str(value).strip()
        def _replace(m: re.Match) -> str:
            raw = m.group(1)
            return raw[:3] + self._mask_char * 4 + raw[-4:]
        return _PHONE_RE.sub(_replace, text)

    def mask_landline(self, value: str) -> str:
        """010-****5678。"""
        if not value:
            return ""
        text = str(value).strip()
        def _replace(m: re.Match) -> str:
            prefix = m.group(1)
            num = m.group(2)
            # 保留区号的数字部分 + 号码后4位，中间mask
            if len(num) <= 4:
                return prefix + self._mask_char * len(num)
            return prefix + self._mask_char * (len(num) - 4) + num[-4:]
        return _LANDLINE_RE.sub(_replace, text)

    def mask_wechat(self, value: str) -> str:
        """仅当匹配到微信号模式时才掩码；否则原样返回。

        - 形如 '微信号:abc123'：只掩码 ID 部分
        - 形如 'wx_abc123' / 'abc123'（纯微信号 ID）：整体 token 掩码
        - 不匹配则原样返回，避免对无意义文本过度处理
        """
        if not value:
            return ""
        text = str(value).strip()
        m = _WECHAT_LIKE_RE.search(text)
        if m:
            raw_id = m.group(2)
            masked = self._mask_single_token(raw_id)
            return text[:m.start(2)] + masked + text[m.end(2):]
        # 形如纯字母数字 ID（长度 5-30）才做 token 级掩码
        if 5 <= len(text) <= 30 and re.fullmatch(r"[A-Za-z0-9_\-]+", text):
            return self._mask_single_token(text)
        return text

    def mask_qq(self, value: str) -> str:
        """QQ号：匹配到正则才替换，否则原样返回。"""
        if not value:
            return ""
        text = str(value).strip()
        def _replace(m: re.Match) -> str:
            raw = m.group(1)
            if len(raw) <= 4:
                return self._mask_char * len(raw)
            return raw[:2] + self._mask_char * (len(raw) - 4) + raw[-2:]
        return _QQ_RE.sub(_replace, text)

    def mask_email(self, value: str) -> str:
        """u***r@example.com。"""
        if not value:
            return ""
        text = str(value).strip()
        def _replace(m: re.Match) -> str:
            user = m.group(1)
            domain = m.group(2)
            if len(user) <= 2:
                masked_user = self._mask_char * len(user)
            else:
                masked_user = user[0] + self._mask_char * max(3, len(user) - 2) + user[-1]
            return masked_user + "@" + domain
        return _EMAIL_RE.sub(_replace, text)

    def mask_id_card(self, value: str) -> str:
        """110101********7777。"""
        if not value:
            return ""
        text = str(value).strip()
        def _replace(m: re.Match) -> str:
            return m.group(1) + self._mask_char * 8 + m.group(3)
        return _ID_CARD_RE.sub(_replace, text)

    def mask_bank_card(self, value: str) -> str:
        """对 16+ 位纯数字卡号做掩码（如 622202********1234）。

        注意：不主动移除文本中的空格/中文，避免破坏整体文本结构；
        仅当连续数字序列匹配银行卡号模式时才掩码。
        """
        if not value:
            return ""
        text = str(value).strip()
        def _replace(m: re.Match) -> str:
            raw = m.group(0)
            if len(raw) < 14:
                return raw
            head = raw[:6]
            tail = raw[-4:]
            return head + self._mask_char * (len(raw) - 10) + tail
        # 仅对 14-19 位连续数字（银行卡号长度）尝试掩码
        return re.sub(r"(?<!\d)\d{14,19}(?!\d)", _replace, text)

    def mask_nickname(self, value: str) -> str:
        """张伟 → 张*；Alice → A****。"""
        if not value:
            return ""
        text = str(value).strip()
        if len(text) <= 1:
            return self._mask_char * len(text)
        # 中文：首字 + "*"*(len-1)
        # 英文：首字母 + "*"*(len-1) （保留末字）
        if any("\u4e00" <= ch <= "\u9fff" for ch in text):
            return text[0] + self._mask_char * (len(text) - 1)
        # ASCII
        if len(text) <= 2:
            return text[0] + self._mask_char * len(text)
        return text[0] + self._mask_char * (len(text) - 2) + text[-1]

    def mask_company(self, value: str) -> str:
        """阿里***限公司 / Ali***Ltd。"""
        if not value:
            return ""
        text = str(value).strip()
        if len(text) <= 4:
            return self._mask_char * len(text)
        return text[:2] + self._mask_char * 3 + text[-2:]

    def mask_url(self, value: str) -> str:
        """https://***.***.com/path。"""
        if not value:
            return ""
        text = str(value).strip()
        try:
            from urllib.parse import urlparse
            parsed = urlparse(text)
            if not parsed.netloc:
                return text
            parts = parsed.netloc.split(".")
            if len(parts) <= 1:
                # 纯 IP
                ip_parts = parts[0].split(":")
                return self._mask_char * 3 + (":" + ip_parts[1] if len(ip_parts) > 1 else "")
            # 保留最后两级（如 example.com），前面mask掉
            if len(parts) <= 2:
                masked = self._mask_char * 3 + "." + parts[-1]
            else:
                masked = ".".join([self._mask_char * 3 for _ in parts[:-2]]) + "." + ".".join(parts[-2:])
            path = parsed.path or ""
            query = ("?" + parsed.query) if parsed.query else ""
            scheme = (parsed.scheme + "://") if parsed.scheme else ""
            return scheme + masked + path + query
        except Exception:
            return text

    # --------- 自动识别 ----------

    def auto_mask(self, data: Any, *, deep: bool = True) -> Any:
        """递归遍历，自动识别 key 或字符串中的隐私并脱敏。"""
        if data is None:
            return None
        if isinstance(data, bool):
            return data
        if isinstance(data, (int, float)):
            # 数字类型可能本身就是手机号/QQ号；转字符串判断
            s = str(data)
            if _PHONE_RE.fullmatch(s):
                return self.mask_phone(s)
            if _QQ_RE.fullmatch(s):
                return self.mask_qq(s)
            if _ID_CARD_RE.fullmatch(s):
                return self.mask_id_card(s)
            return data
        if isinstance(data, str):
            return self._mask_string(data)
        if isinstance(data, dict):
            return {k: self._mask_by_key(k, v) for k, v in data.items()}
        if isinstance(data, list):
            return [self.auto_mask(item, deep=deep) for item in data]
        if isinstance(data, tuple):
            return tuple(self.auto_mask(item, deep=deep) for item in data)
        return data

    # --------- 仅检测 ----------

    def detect_pii(self, text: str) -> list[dict]:
        """扫描文本，返回命中的隐私明细。"""
        if not text:
            return []
        hits: list[dict] = []

        for m in _PHONE_RE.finditer(text):
            hits.append({"type": "phone", "text": m.group(1), "start": m.start(1), "end": m.end(1)})
        for m in _EMAIL_RE.finditer(text):
            hits.append({"type": "email", "text": m.group(0), "start": m.start(), "end": m.end()})
        for m in _ID_CARD_RE.finditer(text):
            hits.append({"type": "id_card", "text": m.group(0), "start": m.start(), "end": m.end()})
        for m in _QQ_RE.finditer(text):
            hits.append({"type": "qq", "text": m.group(1), "start": m.start(1), "end": m.end(1)})
        for m in _LANDLINE_RE.finditer(text):
            hits.append({"type": "landline", "text": m.group(0), "start": m.start(), "end": m.end()})

        # 按 start 排序，去重叠（优先保留 phone / id_card / email）
        hits.sort(key=lambda h: h["start"])
        cleaned: list[dict] = []
        last_end = -1
        for h in hits:
            if h["start"] >= last_end:
                cleaned.append(h)
                last_end = h["end"]
        return cleaned

    # --------- 辅助 ----------

    def _mask_single_token(self, token: str) -> str:
        if len(token) <= 2:
            return self._mask_char * len(token)
        if len(token) <= 5:
            return token[0] + self._mask_char * (len(token) - 1)
        return token[0] + self._mask_char * (len(token) - 2) + token[-1]

    def _mask_string(self, text: str) -> str:
        """对普通字符串做正则驱动的掩码。"""
        if not text:
            return text
        result = text
        result = self.mask_id_card(result)
        result = self.mask_phone(result)
        result = self.mask_bank_card(result)
        result = self.mask_qq(result)
        result = self.mask_landline(result)
        result = self.mask_email(result)
        result = self.mask_wechat(result)
        # URL 可能与邮箱冲突，放在后面
        return result

    def _mask_by_key(self, key: Any, value: Any) -> Any:
        """基于 key 名称判断字段类型。"""
        if not isinstance(key, str) or value is None:
            return self.auto_mask(value)

        nk = _normalize_key(key)
        if not nk:
            return self.auto_mask(value)

        # 精确匹配 + 白名单判断
        matched_key_in_privacy = nk in _NORMALIZED_PRIVACY_KEYS or any(nk.startswith(pk) for pk in _NORMALIZED_PRIVACY_KEYS)
        matched_extra = nk in self._extra_keys or any(nk.startswith(ek) for ek in self._extra_keys)

        if not matched_key_in_privacy and not matched_extra:
            # key 不命中，退化为字符串级别的自动掩码
            if isinstance(value, str):
                return self._mask_string(value)
            return self.auto_mask(value)

        # 针对具体类型
        if isinstance(value, str):
            if "phone" in nk or "mobile" in nk or "tel" in nk or "电话" in nk or "手机号" in nk:
                return self.mask_phone(value) or self.mask_landline(value)
            if "email" in nk or "mail" in nk or "邮箱" in nk:
                return self.mask_email(value)
            if "wechat" in nk or "weixin" in nk or "微信" in nk or nk.startswith("wx"):
                return self.mask_wechat(value)
            if "qq" in nk:
                return self.mask_qq(value)
            if "idcard" in nk or "idcard" in nk or "身份证" in nk:
                return self.mask_id_card(value)
            if "bankcard" in nk or "银行卡" in nk:
                return self.mask_bank_card(value)
            if "company" in nk or "企业" in nk:
                return self.mask_company(value)
            if "nick" in nk or "username" in nk or "昵称" in nk or "用户名" in nk:
                return self.mask_nickname(value)
            # password/secret/token 等直接完全掩码
            if "password" in nk or "passwd" in nk or "pwd" in nk or "secret" in nk or "apikey" in nk or "token" in nk or "cookie" in nk:
                return self._mask_char * max(8, min(len(value), self._mask_len))
            # 默认：字符串级掩码
            return self._mask_string(value)

        if isinstance(value, (list, tuple)):
            return type(value)(self._mask_by_key(key, v) for v in value)
        if isinstance(value, dict):
            return self.auto_mask(value)
        # 数字类型直接当作字符串
        if isinstance(value, (int, float)):
            return self._mask_by_key(key, str(value))
        return value


# 模块级单例（延迟加载 .env）
def _build_default_mask() -> PIIMask:
    mask_char = os.environ.get("PII_MASK_CHAR", "*")
    try:
        mask_len = int(os.environ.get("PII_MASK_SHORT_LEN", "8"))
    except ValueError:
        mask_len = 8
    extra_keys: list[str] = []
    raw_extra = os.environ.get("PII_EXTRA_KEYS_JSON", "")
    if raw_extra:
        try:
            parsed = json.loads(raw_extra)
            if isinstance(parsed, list):
                extra_keys = [str(k) for k in parsed if k]
        except json.JSONDecodeError:
            logger.warning("PII_EXTRA_KEYS_JSON 解析失败，忽略")
    return PIIMask(mask_char=mask_char, mask_short_length=mask_len, custom_pii_keys=extra_keys)


pii_mask: PIIMask | None = None
try:
    pii_mask = _build_default_mask()
except Exception as exc:
    logger.warning(f"默认 PIIMask 初始化失败: {exc}")
    pii_mask = PIIMask()


__all__ = ["PIIMask", "pii_mask"]
