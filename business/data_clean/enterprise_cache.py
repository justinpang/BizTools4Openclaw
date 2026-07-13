from __future__ import annotations

import hashlib
import json
import re
import threading
import time
from dataclasses import dataclass
from typing import Any

from infra.logger_setup import get_logger

from business.data_clean.enterprise_models import EnterpriseProfile
from business.data_clean.enterprise_settings import enrich_settings

"""business.data_clean.enterprise_cache — 企业查询结果缓存。

策略：
  - 根据规范化企业名称（去空格/去标点/统一后缀）计算 md5 key
  - Redis 优先（如可用），回退到进程内 dict
  - TTL：7 天（可通过 ENRICH_CACHE_TTL_SECONDS 配置）

键结构：
  qcc:enterprise:<md5>          → JSON(EnterpriseProfile)
  qcc:enterprise:negative:<md5> → "not_found"（TTL 24h，避免重复死查）

Typical usage::

    cache = EnterpriseCache()
    cached = cache.get('阿里云计算有限公司')
    if cached: return cached
    profile = client.query('阿里云计算有限公司')
    cache.set('阿里云计算有限公司', profile)  # 或 cache.mark_negative('xxx')
"""

logger = get_logger("data_clean.enterprise_cache")


# ============================================================
# 企业名称规范化（用作缓存 key 基础）
# ============================================================


def normalize_company_name(name: str) -> str:
    """企业名称规范化 → 去除空格标点/去常见后缀/统一小写。

    说明：
      - 仅作为缓存 key（便于 '阿里云计算有限公司' / '阿里云计算公司' 命中同一缓存）
      - 不会修改外部显示的企业名称
    """
    if not name:
        return ""
    s = str(name).strip().lower()
    # 去所有空白字符
    s = re.sub(r"\s+", "", s)
    # 去常见中英文标点
    s = re.sub(r"[·•.，,（）()\[\]【】\-、！!?？\"'～:：;；/\\]", "", s)
    # 去常见公司后缀（从长到短匹配，避免误删）
    # 中文后缀：有限公司、股份公司、公司、集团等
    suffixes = [
        "集团有限公司", "股份有限公司", "有限责任公司", "有限公司",
        "股份公司", "公司", "集团", "控股", "(中国)", "(北京)",
        "(上海)", "(深圳)", "(杭州)",
        "companylimited", "co.,ltd.", "co.,ltd", "co.ltd", "ltd.", "ltd",
        "limited", "inc.", "inc", "corp.", "corp",
    ]
    for suf in sorted(suffixes, key=len, reverse=True):
        suf_l = suf.lower()
        if s.endswith(suf_l):
            s = s[: -len(suf_l)]
            break
    return s.strip()


def _md5_company_name(name: str) -> str:
    norm = normalize_company_name(name)
    if not norm:
        return ""
    return hashlib.md5(norm.encode("utf-8")).hexdigest()


# ============================================================
# Redis helper — 有就用，没有就算
# ============================================================


def _get_redis():
    """尝试获取 Redis 客户端；不可用 → None。"""
    try:
        from infra.redis_client import redis_client as rc

        if getattr(rc, "ping", None) and rc.ping(fail_silently=True):
            return rc
    except Exception:
        pass
    return None


# ============================================================
# EnterpriseCache — 主类
# ============================================================


@dataclass
class _InMemoryCacheItem:
    value: Any  # EnterpriseProfile | "not_found"
    expires_at: float  # unix timestamp


class EnterpriseCache:
    """企业查询结果缓存（Redis 优先，进程内回退）。"""

    def __init__(self) -> None:
        self._enabled = bool(getattr(enrich_settings, "cache_enabled", True))
        self._ttl = int(getattr(enrich_settings, "cache_ttl_seconds", 7 * 24 * 3600))
        self._negative_ttl = 24 * 3600  # 查无结果 → 24 小时冷却
        self._lock = threading.RLock()
        self._in_memory: dict[str, _InMemoryCacheItem] = {}

        self._redis = _get_redis()
        if self._redis is not None:
            logger.info("[T29] EnterpriseCache 使用 Redis 后端。")
        else:
            logger.info("[T29] EnterpriseCache 使用进程内回退后端。")

    # ---------- 公共 API ----------

    def get(self, company_name: str) -> EnterpriseProfile | None:
        """从缓存读取。未命中或过期 → 返回 None。"""
        if not self._enabled:
            return None
        key = _md5_company_name(company_name)
        if not key:
            return None

        # 1) Redis 路径
        if self._redis is not None:
            try:
                raw = self._redis.get(f"enterprise:{key}")
                if raw is not None:
                    try:
                        data = json.loads(raw) if isinstance(raw, str) else json.loads(raw.decode())
                        return EnterpriseProfile(**data)
                    except Exception:
                        pass
                # 检查 negative 缓存
                negative = self._redis.get(f"enterprise:negative:{key}")
                if negative is not None:
                    return EnterpriseProfile(
                        company_name=company_name,
                        source_channel="aiqicha",
                        source_mode="cached_negative",
                        confidence_score=0.0,
                    )
                return None
            except Exception:
                pass

        # 2) 进程内回退
        with self._lock:
            item = self._in_memory.get(key)
            if item and item.expires_at > time.time():
                if item.value == "not_found":
                    return EnterpriseProfile(
                        company_name=company_name,
                        source_channel="aiqicha",
                        source_mode="cached_negative",
                        confidence_score=0.0,
                    )
                if isinstance(item.value, EnterpriseProfile):
                    return item.value
        return None

    def set(self, company_name: str, profile: EnterpriseProfile) -> None:
        """写入缓存。"""
        if not self._enabled or profile is None:
            return
        key = _md5_company_name(company_name)
        if not key:
            return
        if self._redis is not None:
            try:
                data = profile.model_dump_json()
                self._redis.set(f"enterprise:{key}", data, ex=self._ttl)
                return
            except Exception:
                pass
        # 进程内回退
        with self._lock:
            self._in_memory[key] = _InMemoryCacheItem(
                value=profile, expires_at=time.time() + self._ttl
            )

    def mark_negative(self, company_name: str) -> None:
        """标记「查无此公司」，避免短时间重复查询。"""
        if not self._enabled:
            return
        key = _md5_company_name(company_name)
        if not key:
            return
        if self._redis is not None:
            try:
                self._redis.set(f"enterprise:negative:{key}", "1", ex=self._negative_ttl)
                return
            except Exception:
                pass
        with self._lock:
            self._in_memory[key] = _InMemoryCacheItem(
                value="not_found", expires_at=time.time() + self._negative_ttl
            )

    def clear(self) -> None:
        """仅用于测试：清空本地缓存。"""
        with self._lock:
            self._in_memory.clear()


# ============================================================
# 模块级单例（便于跨文件共享）
# ============================================================

_enterprise_cache: EnterpriseCache | None = None
_cache_lock = threading.Lock()


def get_cache() -> EnterpriseCache:
    """获取企业补全缓存的模块级单例。"""
    global _enterprise_cache
    if _enterprise_cache is None:
        with _cache_lock:
            if _enterprise_cache is None:
                _enterprise_cache = EnterpriseCache()
    return _enterprise_cache


__all__ = [
    "EnterpriseCache",
    "get_cache",
    "normalize_company_name",
]
