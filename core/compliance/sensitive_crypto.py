from __future__ import annotations

import base64
import hashlib
import os
import threading
from typing import Any

from infra.logger_setup import get_logger

logger = get_logger("compliance.crypto")


class AES256Crypto:
    """AES-256-CBC 单例；密钥从 settings.db.DB_ENCRYPTION_KEY 派生。

    - 每次加密都使用新的随机 IV（16 字节）
    - 密文格式：base64(IV + ciphertext)
    - 空字符串 / None 原样返回，避免对 NULL 字段做无意义处理
    """

    _instance: "AES256Crypto | None" = None
    _lock = threading.Lock()

    def __new__(cls) -> "AES256Crypto":
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    inst = super().__new__(cls)
                    inst._initialized = False
                    cls._instance = inst
        return cls._instance

    def _ensure_key(self) -> None:
        if self._initialized:
            return
        from configs.settings import settings as _settings
        key = str(_settings.db.DB_ENCRYPTION_KEY or "").strip()
        if not key or len(key) < 16:
            raise ValueError(
                "DB_ENCRYPTION_KEY 未配置或长度不足 16 字符，"
                "请在 .env 中配置 DB_ENCRYPTION_KEY"
            )
        # SHA-256 派生 32 字节密钥，保证 AES-256
        self._key: bytes = hashlib.sha256(key.encode("utf-8")).digest()
        self._initialized = True

    # ---------------- public ----------------
    def encrypt(self, plaintext: str | None) -> str | None:
        if plaintext is None or plaintext == "":
            return plaintext
        self._ensure_key()
        from cryptography.hazmat.primitives import padding as _pad
        from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes

        iv = os.urandom(16)
        padder = _pad.PKCS7(128).padder()
        data = padder.update(plaintext.encode("utf-8")) + padder.finalize()
        cipher = Cipher(algorithms.AES(self._key), modes.CBC(iv))
        enc = cipher.encryptor()
        ct = enc.update(data) + enc.finalize()
        return base64.b64encode(iv + ct).decode("ascii")

    def decrypt(self, ciphertext: str | None) -> str | None:
        if ciphertext is None or ciphertext == "":
            return ciphertext
        self._ensure_key()
        from cryptography.hazmat.primitives import padding as _pad
        from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes

        try:
            raw = base64.b64decode(ciphertext.encode("ascii"))
        except Exception:
            # 非 base64 视为明文，直接返回（兼容历史数据）
            return ciphertext
        if len(raw) < 32:
            return ciphertext
        iv, ct = raw[:16], raw[16:]
        try:
            cipher = Cipher(algorithms.AES(self._key), modes.CBC(iv))
            dec = cipher.decryptor()
            pt = dec.update(ct) + dec.finalize()
            unpadder = _pad.PKCS7(128).unpadder()
            return (unpadder.update(pt) + unpadder.finalize()).decode("utf-8")
        except Exception:
            return ciphertext  # 解密失败，原样返回，避免抛出异常打断查询


# ---------------- 脱敏工具 ----------------

def mask_phone(phone: str | None) -> str | None:
    if not phone:
        return phone
    digits = "".join(ch for ch in phone if ch.isdigit())
    if len(digits) <= 4:
        return "*" * len(digits)
    head = 3
    tail = 4 if len(digits) >= 7 else 2
    return digits[:head] + "*" * max(4, len(digits) - head - tail) + digits[-tail:]


def mask_email(email: str | None) -> str | None:
    if not email or "@" not in email:
        return email
    user, domain = email.rsplit("@", 1)
    if len(user) <= 2:
        masked_user = user[0] + "*" * max(2, len(user))
    else:
        masked_user = user[0] + "*" * (len(user) - 2) + user[-1]
    return f"{masked_user}@{domain}"


def mask_wechat(wx: str | None) -> str | None:
    if not wx:
        return wx
    if len(wx) <= 2:
        return "*" * len(wx)
    return wx[0] + "*" * (len(wx) - 2) + wx[-1]


def mask_value(field_name: str, value: str | None) -> str | None:
    """根据字段名智能选择脱敏策略。

    当 settings.db.DB_SENSITIVE_MASK_ENABLED 为 False 时，原样返回。
    """
    if value is None or value == "":
        return value
    try:
        from configs.settings import settings as _settings
        if not _settings.db.DB_SENSITIVE_MASK_ENABLED:
            return value
    except Exception:
        pass
    fn = field_name.lower() if isinstance(field_name, str) else ""
    if any(k in fn for k in ("phone", "mobile", "tel")):
        return mask_phone(value)
    if "email" in fn:
        return mask_email(value)
    if any(k in fn for k in ("wechat", "wx", "weixin")):
        return mask_wechat(value)
    # 默认：保留前 2 位，其余打码
    if len(value) <= 2:
        return "*" * len(value)
    return value[:2] + "*" * max(2, len(value) - 2)


# ---------------- SQLAlchemy TypeDecorator ----------------

try:
    from sqlalchemy import TypeDecorator, String as _String
    from sqlalchemy.sql.sqltypes import String as _StringType

    class SensitiveString(TypeDecorator):
        """敏感字段类型；写入自动加密，查询自动解密。

        用法：
            contact_phone: Mapped[str | None] = mapped_column(SensitiveString(256))
        """
        impl = _String
        cache_ok = True

        def __init__(self, length: int = 256, *args: Any, **kwargs: Any) -> None:
            super().__init__(length=length, *args, **kwargs)

        def process_bind_param(self, value: Any, dialect: Any) -> str | None:
            if value is None:
                return None
            return AES256Crypto().encrypt(str(value))

        def process_result_value(self, value: Any, dialect: Any) -> str | None:
            if value is None:
                return None
            decrypted = AES256Crypto().decrypt(str(value))
            return decrypted if decrypted is not None else value  # 保留原样

except Exception:  # pragma: no cover - 在 SQLAlchemy 未安装时兜底
    class SensitiveString:  # type: ignore[no-redef]
        """SensitiveString 占位（SQLAlchemy 未安装时）。"""

        def __init__(self, length: int = 256, *args: Any, **kwargs: Any) -> None:
            self.length = length


__all__ = [
    "AES256Crypto",
    "SensitiveString",
    "mask_value",
    "mask_phone",
    "mask_email",
    "mask_wechat",
]
