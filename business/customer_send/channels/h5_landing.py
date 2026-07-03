"""business/customer_send/channels/h5_landing — H5 落地页动态生成。"""

from __future__ import annotations

import hashlib
import html
from typing import Any

from infra.logger_setup import get_logger
from configs.settings import settings

logger = get_logger("customer_send.h5")


class H5Landing:
    """根据 H5PageSpec 生成 HTML；同时提供短链 URL。"""

    name = "h5"

    def page_id_for(self, spec: Any) -> str:
        key = f"{getattr(spec, 'tenant_id', '')}|{getattr(spec, 'opportunity_id', '')}|{settings.customer_send.CUSTOMER_SEND_VERSION}"
        digest = hashlib.md5(key.encode("utf-8")).hexdigest()[:12]
        return f"h5_{digest}"

    def short_url(self, page_id: str) -> str:
        base = settings.customer_send.CUSTOMER_SEND_H5_BASE_URL.rstrip("/")
        return f"{base}/p/{page_id}"

    def generate_html(self, spec: Any) -> str:
        """生成完整 HTML 页面（用于静态托管或直接邮件链接显示）。"""
        title = html.escape(str(getattr(spec, "title", "") or "商机详情"))
        summary = html.escape(str(getattr(spec, "summary", "") or ""))
        industry = html.escape(str(getattr(spec, "industry", "") or ""))
        region = html.escape(str(getattr(spec, "region", "") or ""))
        customer = html.escape(str(getattr(spec, "customer_name_masked", "") or ""))
        keywords = ", ".join(html.escape(str(k)) for k in (getattr(spec, "keywords", []) or []))
        cta = html.escape(str(getattr(spec, "cta_label", "") or "立即报名"))
        page_id = html.escape(str(getattr(spec, "page_id", self.page_id_for(spec))))

        form_fields_html = ""
        fields = getattr(spec, "form_fields", []) or []
        for fld in fields:
            f_name = html.escape(str(fld.get("name", "")))
            f_type = html.escape(str(fld.get("type", "text")))
            f_label = html.escape(str(fld.get("label", f_name)))
            f_required = "required" if fld.get("required") else ""
            form_fields_html += (
                f'  <label class="f">{f_label}'
                f'<input type="{f_type}" name="{f_name}" {f_required}/>'
                f'</label>\n'
            )
        if not form_fields_html:
            form_fields_html = (
                '  <label class="f">您的姓名 <input type="text" name="name" required/></label>\n'
                '  <label class="f">联系电话 <input type="tel" name="phone" required/></label>\n'
            )

        return (
            "<!DOCTYPE html>\n"
            '<html lang="zh-CN"><head><meta charset="utf-8"/>\n'
            '<meta name="viewport" content="width=device-width, initial-scale=1, maximum-scale=1"/>\n'
            f"<title>{title}</title>\n"
            '<style>\n'
            ' body{font-family:-apple-system,BlinkMacSystemFont,"PingFang SC","Microsoft YaHei",Arial,sans-serif;margin:0;color:#1f2937;background:#f9fafb;padding:18px;}\n'
            ' .card{background:#fff;border-radius:12px;padding:18px;box-shadow:0 2px 10px rgba(0,0,0,.05);max-width:520px;margin:0 auto;}\n'
            ' h1{font-size:18px;margin:0 0 10px;}\n'
            ' .tags span{display:inline-block;background:#eff6ff;color:#2563eb;padding:3px 10px;border-radius:999px;font-size:12px;margin-right:6px;margin-top:6px;}\n'
            ' .summary{line-height:1.7;margin-top:12px;font-size:14px;}\n'
            ' form{margin-top:16px;}\n'
            ' .f{display:block;font-size:14px;margin-top:12px;}\n'
            ' .f input{width:100%;padding:10px;border:1px solid #d1d5db;border-radius:8px;margin-top:6px;box-sizing:border-box;font-size:14px;}\n'
            ' button{background:#2563eb;color:#fff;border:none;border-radius:8px;padding:12px 18px;margin-top:14px;font-size:15px;}\n'
            ' .meta{color:#9ca3af;font-size:12px;margin-top:12px;}\n'
            '</style></head><body>\n'
            '<div class="card">\n'
            f"  <h1>{title}</h1>\n"
            f'  <div class="tags"><span>{industry or "全行业"}</span><span>{region or "全国"}</span>'
            f"<span>{keywords or '—'}</span></div>\n"
            f'  <p class="summary">客户：<b>{customer}</b><br/>{summary or "详情请点击提交意向"}</p>\n'
            f'  <form action="/api/h5/{page_id}/submit" method="POST">\n'
            f'{form_fields_html}'
            f'  <button type="submit">{cta}</button>\n'
            '  </form>\n'
            f'  <p class="meta">page_id: {page_id}</p>\n'
            '</div></body></html>\n'
        )


__all__ = ["H5Landing"]
