from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field

"""business.data_clean.enterprise_models — T29 企业信息自动补全：标准化数据模型。

设计原则：
  - 渠道无关（Channel-agnostic）：EnterpriseProfile 屏蔽爱企查/企查查等渠道差异
  - 字段完整但非侵入：补全数据不覆盖已有商机联系方式
  - 可审计：记录查询时间、来源渠道、置信度

Typical usage::

    profile = EnterpriseProfile(
        company_name='阿里云计算有限公司',
        contact_person='王某某',
        contact_phone='010-12345678',
        contact_email='contact@aliyun.com',
        registered_address='北京市海淀区...',
        company_scale='大型',
        industry_category='软件和信息技术服务业',
        registered_capital='5000万元人民币',
        establishment_date='2009-09-10',
        business_status='在营（开业）',
        confidence_score=0.95,
        source_channel='aiqicha',
        source_mode='web',
        query_url='https://aiqicha.baidu.com/s?q=...',
    )
    enrich_result = EnterpriseEnrichResult(success=True, status='enriched',
                                            company_name='阿里云计算有限公司',
                                            profile=profile,
                                            enriched_fields=['contact_phone', 'contact_email'])
"""


# ============================================================
# EnterpriseProfile — 统一企业画像结构
# ============================================================

class EnterpriseProfile(BaseModel):
    """标准化企业信息画像 — 屏蔽渠道差异（爱企查/企查查/天眼查）。

    所有字段均为可选；根据查询到的信息逐步填充。
    """

    # —— 标识 ——
    company_name: str = ""                    # 原始查询的企业名称
    matched_name: str = ""                    # 渠道返回的实际匹配名称
    company_id: str = ""                      # 渠道内部 ID (如 pid)

    # —— 核心联系方式（补全的目标字段）——
    contact_person: str = ""                  # 联系人 / 法定代表人
    contact_phone: str = ""                   # 联系电话
    contact_email: str = ""                   # 企业邮箱

    # —— 画像维度 ——
    registered_address: str = ""              # 注册地址
    company_scale: str = ""                   # 企业规模：微型 / 小型 / 中型 / 大型
    industry_category: str = ""               # 行业分类
    registered_capital: str = ""              # 注册资本
    establishment_date: str = ""              # 成立日期
    business_status: str = ""                 # 经营状态
    credit_code: str = ""                     # 统一社会信用代码
    legal_representative: str = ""            # 法定代表人（与 contact_person 区分：企业法定代表人）

    # —— 元信息（可审计）——
    confidence_score: float = 0.0             # 匹配置信度 0-1
    source_channel: str = "aiqicha"           # 来源渠道：aiqicha / qcc / tianyancha
    source_mode: str = "web"                  # api / web
    query_url: str = ""                       # 原始查询 URL（审计用）
    queried_at: str = Field(
        default_factory=lambda: datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    )

    def has_contact_info(self) -> bool:
        """是否至少包含一项联系信息。"""
        return bool(self.contact_phone or self.contact_email or self.contact_person)

    def enriched_field_names(self) -> list[str]:
        """返回已填充的字段名列表（用于日志/审计）。"""
        fields = []
        for field_name in ("contact_person", "contact_phone", "contact_email",
                           "registered_address", "company_scale", "industry_category",
                           "registered_capital", "establishment_date", "business_status",
                           "credit_code", "legal_representative"):
            if getattr(self, field_name, ""):
                fields.append(field_name)
        return fields

    model_config = {"extra": "ignore"}


# ============================================================
# EnterpriseEnrichResult — 单次补全结果
# ============================================================

class EnterpriseEnrichResult(BaseModel):
    """单次企业补全结果：成功 / 查无结果 / 查询失败 / 跳过。"""

    success: bool = False
    status: str = ""                          # enriched / not_found / failed / skipped / cached
    company_name: str = ""
    profile: EnterpriseProfile | None = None
    error_message: str = ""
    needs_manual_review: bool = False        # 标记需人工复核（查询失败/查无时 True）
    enriched_fields: list[str] = Field(default_factory=list)
    source_channel: str = "aiqicha"
    cached: bool = False                      # 是否来自缓存

    @property
    def is_usable(self) -> bool:
        """结果是否可用：成功 + 有联系方式。"""
        return self.success and self.profile is not None and self.profile.has_contact_info()


# ============================================================
# EnterpriseEnrichBatchResult — 批量任务结果
# ============================================================

class EnterpriseEnrichBatchResult(BaseModel):
    """批量补全结果（异步 worker 返回此对象）。"""

    task_id: str = ""
    total: int = 0
    enriched: int = 0
    not_found: int = 0
    failed: int = 0
    skipped: int = 0
    items: list[EnterpriseEnrichResult] = Field(default_factory=list)
    finished_at: str = Field(
        default_factory=lambda: datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    )

    def summary(self) -> dict[str, int]:
        return {
            "total": self.total,
            "enriched": self.enriched,
            "not_found": self.not_found,
            "failed": self.failed,
            "skipped": self.skipped,
        }


__all__ = [
    "EnterpriseProfile",
    "EnterpriseEnrichResult",
    "EnterpriseEnrichBatchResult",
]
