#!/usr/bin/env python3
"""第四轮（最终）：爬虫任务创建、登录页、合规模块等所有英文 -> 中文。"""
from __future__ import annotations

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
WEB_ADMIN = PROJECT_ROOT / "web_admin"

PAGES_ROUND4: list[tuple[str, str]] = [
    # --- 登录页面 ---
    ('<title>Login · BizTools4Openclaw Admin Panel</title>',
     '<title>登录 · BizTools4Openclaw 管理后台</title>'),
    ('<h1>[Lock] Admin Panel Login</h1>',
     '<h1>🔒 管理后台登录</h1>'),
    ('<p class="hint">Username / password configured by ops in .env. Visible menus depend on role.</p>',
     '<p class="hint">账号 / 密码 由运维配置在 .env 中。可见菜单随角色变化。</p>'),
    ('      <label>Account\n        <input type="text" name="username" required autocomplete="username" placeholder="Enter username"/>\n      </label>\n',
     '      <label>账号\n        <input type="text" name="username" required autocomplete="username" placeholder="请输入用户名"/>\n      </label>\n'),
    ('      <label>Password\n        <input type="password" name="password" required autocomplete="current-password" placeholder="Enter password"/>\n      </label>\n',
     '      <label>密码\n        <input type="password" name="password" required autocomplete="current-password" placeholder="请输入密码"/>\n      </label>\n'),
    ('<button type="submit" class="btn btn-primary">LOG IN</button>',
     '<button type="submit" class="btn btn-primary">登 录</button>'),
    ('<p class="footer">&copy; BizTools4Openclaw · Sessions encrypted, auto-expire.</p>',
     '<p class="footer">&copy; BizTools4Openclaw · 会话加密存储，自动过期。</p>'),

    # --- Permission denied in _render_with_permission ---
    ('_layout_v2("Permission denied", "403",',
     '_layout_v2("权限不足", "403",'),

    # --- Spider: channel cards ---
    ('<span class="channel-title">Corporate Business</span>',
     '<span class="channel-title">企业工商</span>'),
    ('<span class="channel-desc">Qcc/Tianyancha/Industry disclosure</span>',
     '<span class="channel-desc">企查查/天眼查/行业信息披露</span>'),

    # --- Spider: new task form ---
    ('<h3>[+] New Collection Task</h3>',
     '<h3>➕ 新建采集任务</h3>'),
    ('<label>Channel Type <select id="task-channel-select"',
     '<label>渠道类型 <select id="task-channel-select"'),
    ('<option value="">Please select a channel</option>',
     '<option value="">请选择渠道</option>'),
    ('<label>Task ID <input type="text" name="job_id" placeholder="e.g. sp_daily_001"/></label>',
     '<label>任务ID <input type="text" name="job_id" placeholder="例如 sp_daily_001"/></label>'),
    ('<label>Task Name <input type="text" name="task_name" placeholder="Task description"/></label>',
     '<label>任务名称 <input type="text" name="task_name" placeholder="任务描述"/></label>'),
    ('<label>Speed Level (1-5) <input type="number" name="speed_level" value="3" min="1" max="5"/></label>',
     '<label>速度等级(1-5) <input type="number" name="speed_level" value="3" min="1" max="5"/></label>'),
    ('<label>Crawl Limit <input type="number" name="max_items" value="500" min="1"/></label>',
     '<label>抓取上限 <input type="number" name="max_items" value="500" min="1"/></label>'),
    ('<label>Schedule Mode <select name="schedule_mode"><option value="off">Manual</option><option value="hourly">Hourly</option><option value="daily">Daily</option></select></label>',
     '<label>调度模式 <select name="schedule_mode"><option value="off">手动</option><option value="hourly">每小时</option><option value="daily">每天</option></select></label>'),
    ('<label>Time Range <input type="text" name="time_range" placeholder="e.g. Last 7 days"/></label>',
     '<label>时间范围 <input type="text" name="time_range" placeholder="例如：最近7天"/></label>'),
    ('<span class="muted">Please select a channel type to display custom parameters</span>',
     '<span class="muted">请选择渠道类型以显示自定义参数</span>'),

    # --- Compliance agreement block ---
    ('<h4 style="margin:0 0 12px 0;font-size:15px;">[Scale] Data Collection Compliance Checklist (required before save)</h4>',
     '<h4 style="margin:0 0 12px 0;font-size:15px;">⚖ 数据采集合规检查清单（保存前必须勾选）</h4>'),
    ('加载中 compliance agreement...</div>',
     '加载中 合规协议...</div>'),
    ('<label><input type="checkbox" name="compliance_agreed" value="true" form="task-create-form"/> I have read and agree to the Data Collection Compliance Agreement</label>',
     '<label><input type="checkbox" name="compliance_agreed" value="true" form="task-create-form"/> 我已阅读并同意《数据采集合规协议》</label>'),

    # --- Data purpose & retention ---
    ('<label>Data Purpose <select name="compliance_data_purpose" form="task-create-form">\n',
     '<label>数据用途 <select name="compliance_data_purpose" form="task-create-form">\n'),
    ('<option value="">Please select</option>',
     '<option value="">请选择</option>'),
    ('<option value="opportunity">Opportunity Analysis</option>',
     '<option value="opportunity">商机分析</option>'),
    ('<option value="market_research">Market Research</option>',
     '<option value="market_research">市场调研</option>'),
    ('<option value="bidding_decision">招投标 Decision</option>',
     '<option value="bidding_decision">招投标决策</option>'),
    ('<option value="industry_monitoring">Industry Monitoring</option>',
     '<option value="industry_monitoring">行业监控</option>'),
    ('<label>Retention Period <select name="compliance_retention" form="task-create-form">\n',
     '<label>留存周期 <select name="compliance_retention" form="task-create-form">\n'),
    ('<option value="30d">30 days</option>',
     '<option value="30d">30天</option>'),
    ('<option value="90d">90 days</option>',
     '<option value="90d">90天</option>'),
    ('<option value="180d">180 days</option>',
     '<option value="180d">180天</option>'),
    ('<option value="1y">1 year</option>',
     '<option value="1y">1年</option>'),
    ('<label><input type="checkbox" name="compliance_privacy" value="true" form="task-create-form"/> I commit to not collecting personal privacy information (phone/email/ID number)</label>',
     '<label><input type="checkbox" name="compliance_privacy" value="true" form="task-create-form"/> 我承诺不采集个人隐私信息（手机号/邮箱/身份证号）</label>'),
    ('<label><input type="checkbox" name="compliance_site_verified" value="true" form="task-create-form"/> I verify that the collection sites do not violate compliance rules (no forbidden keywords in URLs/titles)</label>',
     '<label><input type="checkbox" name="compliance_site_verified" value="true" form="task-create-form"/> 我确认采集站点未违反合规规则（URL/标题中不含违禁关键词）</label>'),
    ('<button class="btn btn-primary" type="submit" form="task-create-form" data-requires-permission="btn.spider.create">Save Task</button>',
     '<button class="btn btn-primary" type="submit" form="task-create-form" data-requires-permission="btn.spider.create">保存任务</button>'),

    # --- Spider task table ---
    ('      <th>任务ID</th><th>渠道</th><th>任务名称</th><th>Submitter</th>\n',
     '      <th>任务ID</th><th>渠道</th><th>任务名称</th><th>提交人</th>\n'),
    ('      <th>Submission Time</th><th>Data Purpose</th><th>Retention</th><th>Actions</th>\n',
     '      <th>提交时间</th><th>数据用途</th><th>留存周期</th><th>操作</th>\n'),

    # --- Spider detail tables ---
    ('<h3>[Cog] Task Detail — ',
     '<h3>⚙ 任务详情 — '),
    ('      if (admin.loadPendingTasks) admin.loadPendingTasks();\n',
     '      if (admin.loadPendingTasks) admin.loadPendingTasks();\n'),

    # --- Spider compliance config ---
    ('<label>待审核任务ID <input type="text" name="task_id"/></label>',
     '<label>待审核任务ID <input type="text" name="task_id"/></label>'),

    # --- Spider 7-channel quick entry cards ---
    # Already handled
]


def replace_in_file(path: Path, replacements: list[tuple[str, str]]) -> int:
    if not path.exists():
        return 0
    text = path.read_text(encoding="utf-8")
    count = 0
    for old, new in replacements:
        if old in text:
            n = text.count(old)
            text = text.replace(old, new)
            count += n
    if count:
        path.write_text(text, encoding="utf-8")
    return count


def main() -> int:
    total = 0
    print("=" * 60)
    print("🔤 第四轮（最终）：登录页+爬虫任务+合规模块全面中文化")
    print("=" * 60)

    pages_path = WEB_ADMIN / "pages.py"
    n = replace_in_file(pages_path, PAGES_ROUND4)
    print(f"  pages.py: 替换 {n} 处")
    total += n

    print("\n" + "=" * 60)
    print(f"✅ 完成，共替换 {total} 处")
    print("=" * 60)
    return 0


if __name__ == "__main__":
    sys.exit(main())
