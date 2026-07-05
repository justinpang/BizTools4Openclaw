#!/usr/bin/env python3
"""第三轮：pages.py 中剩余的英文 select 选项、标签、标题全面清理。"""
from __future__ import annotations

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
WEB_ADMIN = PROJECT_ROOT / "web_admin"

PAGES_ROUND3: list[tuple[str, str]] = [
    # --- Spider task filter (lines 408-429) ---
    ('<h3>[Search] Task Filtering</h3>',
     '<h3>🔍 任务筛选</h3>'),
    ('<option value="">All</option>',
     '<option value="">全部</option>'),
    ('<option value="PENDING_APPROVAL">Pending Approval</option>',
     '<option value="PENDING_APPROVAL">待审核</option>'),
    ('<option value="REJECTED">Rejected</option>',
     '<option value="REJECTED">已拒绝</option>'),
    ('<option value="READY">Ready</option>',
     '<option value="READY">就绪</option>'),
    ('<option value="RUNNING">Running</option>',
     '<option value="RUNNING">运行中</option>'),
    ('<option value="PAUSED">Paused</option>',
     '<option value="PAUSED">已暂停</option>'),
    ('<option value="COMPLETED">Completed</option>',
     '<option value="COMPLETED">已完成</option>'),
    ('<option value="FAILED">Failed</option>',
     '<option value="FAILED">失败</option>'),
    ('<option value="TERMINATED">Terminated</option>',
     '<option value="TERMINATED">已终止</option>'),
    ('<option value="company_biz">Corporate Business</option>',
     '<option value="company_biz">企业工商</option>'),

    # --- Leads page filter ---
    ('<h3>[Search] Filter</h3>',
     '<h3>🔍 筛选</h3>'),
    ('placeholder="Keyword (title/customer)"/>',
     'placeholder="关键词（标题/客户）"/>'),
    ('<option value="">All Statuses</option>',
     '<option value="">全部状态</option>'),
    ('<option value="PENDING">Pending Review</option>',
     '<option value="PENDING">待复核</option>'),
    ('<option value="APPROVED">Approved</option>',
     '<option value="APPROVED">已通过</option>'),
    ('<option value="REJECTED">Rejected</option>',
     '<option value="REJECTED">已拒绝</option>'),
    ('onclick="admin.loadLeads()">Query</button>',
     'onclick="admin.loadLeads()">查询</button>'),
    ('<h3>📋 Leads List</h3>',
     '<h3>📋 线索列表</h3>'),
    ('<thead><tr><th>ID</th><th>标题</th><th>Customer</th><th>状态</th><th>操作</th></tr></thead>',
     '<thead><tr><th>ID</th><th>标题</th><th>客户</th><th>状态</th><th>操作</th></tr></thead>'),

    # --- Leads blacklist section ---
    ('<h3>[Stop] Blacklist Management</h3>',
     '<h3>🛑 黑名单管理</h3>'),
    ('<label>Type <select name="type"><option value="phone">Phone</option><option value="email">Email</option><option value="company_name">Company Name</option><option value="domain">Domain</option></select></label>',
     '<label>类型 <select name="type"><option value="phone">手机号</option><option value="email">邮箱</option><option value="company_name">公司名</option><option value="domain">域名</option></select></label>'),
    ('<label>Identifier <input type="text" name="identifier" placeholder="identifier"/></label>',
     '<label>标识 <input type="text" name="identifier" placeholder="标识内容"/></label>'),
    ('<label>Reason <input type="text" name="reason" placeholder="e.g. Invalid opportunity"/></label>',
     '<label>原因 <input type="text" name="reason" placeholder="例：无效商机"/></label>'),
    ('<button class="btn btn-danger" type="submit">Add to Blacklist</button>',
     '<button class="btn btn-danger" type="submit">加入黑名单</button>'),
    ('onclick="admin.loadBlacklist()">Load Blacklist</button>',
     'onclick="admin.loadBlacklist()">加载黑名单</button>'),
    ('(click to load)', '(点击加载)'),

    # --- Channels page ---
    ('<h3>[Rocket] 渠道账号</h3>',
     '<h3>🚀 渠道账号</h3>'),
    ('<label>渠道\n              <select name="channel">\n              <option value="email">email</option>',
     '<label>渠道\n              <select name="channel">\n              <option value="email">邮件</option>'),
    ('<label>渠道 <select name="channel">\n',
     '<label>渠道 <select name="channel">\n'),
    ('<option value="email">email</option>',
     '<option value="email">邮件</option>'),
    ('<option value="wechat">企业微信</option>',
     '<option value="wechat">企业微信</option>'),
    ('<option value="feishu">飞书</option>',
     '<option value="feishu">飞书</option>'),
    ('<option value="dingtalk">钉钉</option>',
     '<option value="dingtalk">钉钉</option>'),
    ('<option value="feishu">飞书</option>',
     '<option value="feishu">飞书</option>'),

    # --- Sales page tables ---
    ('<thead><tr><th>ID</th><th>Name</th><th>Industry</th><th>Weight</th><th>Phone</th><th>Email</th></tr></thead>',
     '<thead><tr><th>ID</th><th>姓名</th><th>行业</th><th>权重</th><th>手机</th><th>邮箱</th></tr></thead>'),
    ('<thead><tr><th>Assign ID</th><th>Opportunity</th><th>Sales</th><th>状态</th><th>Time</th></tr></thead>',
     '<thead><tr><th>分配ID</th><th>商机</th><th>销售人员</th><th>状态</th><th>时间</th></tr></thead>'),
    ('<thead><tr><th>ID</th><th>Opportunity</th><th>渠道</th><th>Content</th><th>Operator</th><th>Time</th></tr></thead>',
     '<thead><tr><th>ID</th><th>商机</th><th>渠道</th><th>内容</th><th>操作人</th><th>时间</th></tr></thead>'),
    ('<thead><tr><th>Opportunity</th><th>Sales</th><th>Last</th><th>Hint</th></tr></thead>',
     '<thead><tr><th>商机</th><th>销售人员</th><th>上次跟进</th><th>提示</th></tr></thead>'),

    # --- Audit log page ---
    ('      <th>Time</th><th>User</th><th>Role</th><th>IP</th><th>Operation</th>\n',
     '      <th>时间</th><th>用户</th><th>角色</th><th>IP</th><th>操作</th>\n'),
    ('      <th>Path/Content</th><th>状态</th><th>Duration</th><th>trace_id</th>\n',
     '      <th>路径/内容</th><th>状态</th><th>耗时(ms)</th><th>trace_id</th>\n'),

    # --- Accounts page ---
    ('<thead><tr><th>Account</th><th>Role</th><th>状态</th><th>创建时间</th><th>操作</th></tr></thead>',
     '<thead><tr><th>账号</th><th>角色</th><th>状态</th><th>创建时间</th><th>操作</th></tr></thead>'),

    # --- Compliance review ---
    ('<h3>[Scale] Pending Approval Tasks</h3>',
     '<h3>⚖ 待审核任务</h3>'),
    ('data-requires-permission="btn.compliance.review" onclick="admin.loadPendingTasks()">Load Pending</button>',
     'data-requires-permission="btn.compliance.review" onclick="admin.loadPendingTasks()">加载待审核</button>'),

    # --- Dashboard stat cards (lines 931-935) ---
    ('<div class="label">[Sun] Today Added</div>',
     '<div class="label">☀ 今日新增</div>'),
    ('<div class="label">[Folder] Total Leads</div>',
     '<div class="label">📁 商机总数</div>'),
    ('<div class="label">[Star] High Intent</div>',
     '<div class="label">⭐ 高意向</div>'),
    ('<div class="label">[User] Pending Followup</div>',
     '<div class="label">👤 待跟进</div>'),
    ('<div class="label">[Check] Closed/Won</div>',
     '<div class="label">✅ 已成交</div>'),

    # --- Other generic ---
    ('<h3>[Cog] New Spider Task</h3>',
     '<h3>⚙ 新建爬虫任务</h3>'),
    ('<h3>[Folder] Existing Tasks</h3>',
     '<h3>📁 已有任务</h3>'),
    ('<h3>[Scroll] Task Execution Logs</h3>',
     '<h3>📜 任务执行日志</h3>'),
    ('<h3>[Alert] Risk/Abnormal Events</h3>',
     '<h3>⚠ 风险/异常事件</h3>'),

    # --- Admin init JSON labels ---
    ('"title": "Login Required",',
     '"title": "请登录",'),
    ('"message": "Please login to access the admin panel",',
     '"message": "请登录后访问管理后台",'),
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
    print("🔤 第三轮：剩余英文 select/标签全面清理")
    print("=" * 60)

    pages_path = WEB_ADMIN / "pages.py"
    n = replace_in_file(pages_path, PAGES_ROUND3)
    print(f"  pages.py: 替换 {n} 处")
    total += n

    print("\n" + "=" * 60)
    print(f"✅ 第三轮完成，共替换 {total} 处")
    print("=" * 60)
    return 0


if __name__ == "__main__":
    sys.exit(main())
