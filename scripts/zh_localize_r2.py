#!/usr/bin/env python3
"""第二轮：针对 data_center 阶段页、异常池、批量/导出、商机追踪的深度中文化。
同时补全 channels / sales / audit / spider 等页面的剩余英文。"""
from __future__ import annotations

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
WEB_ADMIN = PROJECT_ROOT / "web_admin"

# ===================== pages.py 第二轮 =====================
PAGES_ROUND2: list[tuple[str, str]] = [
    # --- _stage_detail_page_body 通用模板 ---
    ('<div class="label">[Folder] Total Items</div>',
     '<div class="label">📁 条目总数</div>'),
    ('<div class="label">[Check] Passed/Valid</div>',
     '<div class="label">✅ 已通过/有效</div>'),
    ('<div class="label">[Alert] Exceptions</div>',
     '<div class="label">⚠ 异常数</div>'),
    ('<div class="label">[Clock] Recent 24h</div>',
     '<div class="label">🕓 近24小时新增</div>'),
    ('[Filter] ', '🔍 筛选：'),
    ('  <h3>[Manual Ops] 阶段手工管控 手工操作</h3>',
     '  <h3>🛠 阶段手工管控</h3>'),
    ('    <label>Status <select id=',
     '    <label>状态 <select id='),
    ('<option value="">All</option><option value="APPROVED">Approved</option><option value="PENDING">Pending</option><option value="REJECTED">Rejected</option>',
     '<option value="">全部</option><option value="APPROVED">已通过</option><option value="PENDING">待处理</option><option value="REJECTED">已拒绝</option>'),
    ('    <label>Channel <select id=',
     '    <label>渠道 <select id='),
    ('<option value="">All</option><option value="generic_web">General Web</option><option value="short_video">短视频</option><option value="xhs">小红书</option><option value="qa_platform">问答平台</option><option value="b2b_supply">供需B2B</option><option value="bidding">招投标</option><option value="company_biz">Corporate</option>',
     '<option value="">全部</option><option value="generic_web">通用网页</option><option value="short_video">短视频</option><option value="xhs">小红书</option><option value="qa_platform">问答平台</option><option value="b2b_supply">供需B2B</option><option value="bidding">招投标</option><option value="company_biz">企业工商</option>'),
    ('    <label>Keyword <input type="text"',
     '    <label>关键词 <input type="text"'),
    ('placeholder="Search..."/></label>',
     'placeholder="输入关键词搜索..."/></label>'),
    # 动态按钮文本：按静态字面量方式替换（注意原 pages.py 中的 onclick 里的函数调用）
    ('">Apply</button>', '">应用</button>'),
    ('">Refresh</button>', '">刷新</button>'),
    ('<th>Actions</th>', '<th>操作</th>'),
    # loading 文本（仅匹配明确的 "Loading XXXX data..."）
    ('Loading ', '加载中 '),

    # --- 各阶段标题/描述/列标题 ---
    # collection
    ('stage_title="Collection Stage",\n        stage_desc="Spider tasks and crawled items",\n        table_headers=["Task ID", "Task Name", "Channel", "Status", "Crawled", "Failed", "Created At"],',
     'stage_title="采集阶段",\n        stage_desc="爬虫任务 + 抓取条目",\n        table_headers=["任务ID", "任务名称", "渠道", "状态", "已抓取", "失败", "创建时间"],'),
    # cleaning
    ('stage_title="Cleaning Stage",\n        stage_desc="Structured and validated lead records",\n        table_headers=["Lead ID", "Title", "Channel", "Company", "Contact", "Status", "Created"],',
     'stage_title="清洗结构化",\n        stage_desc="结构化并校验的商机记录",\n        table_headers=["商机ID", "标题", "渠道", "公司", "联系方式", "状态", "创建时间"],'),
    # compliance
    ('stage_title="Compliance Stage",\n        stage_desc="PII detection and compliance scoring",\n        table_headers=["Lead ID", "Title", "Channel", "Compliance Status", "Score", "Risk Level", "PII Types"],',
     'stage_title="合规校验",\n        stage_desc="敏感信息检测 + 合规评分",\n        table_headers=["商机ID", "标题", "渠道", "合规状态", "合规分数", "风险等级", "敏感信息类型"],'),
    # grading
    ('stage_title="Grading Stage",\n        stage_desc="Opportunity grade A/B/C/D + intent scoring",\n        table_headers=["Lead ID", "Title", "Channel", "Grade", "Score", "Budget", "Urgency", "Tags"],',
     'stage_title="商机分级",\n        stage_desc="商机等级A/B/C/D + 意向评分",\n        table_headers=["商机ID", "标题", "渠道", "等级", "评分", "预算", "紧急程度", "标签"],'),
    # outreach
    ('stage_title="Outreach Stage",\n        stage_desc="Email/IM sends and response tracking",\n        table_headers=["Batch ID", "Title", "Target Lead", "Channel", "Target", "Success", "Failed", "Status", "Sent At"],',
     'stage_title="客户触达",\n        stage_desc="邮件/IM 发送 + 响应追踪",\n        table_headers=["批次ID", "标题", "目标商机", "渠道", "目标数", "成功", "失败", "状态", "发送时间"],'),
    # sales
    ('stage_title="Sales Closing",\n        stage_desc="Follow-ups, assignments, and won/lost deals",\n        table_headers=["Lead ID", "Title", "Company", "Assignee", "Grade", "Status", "Followups", "Last Followup", "Value"],',
     'stage_title="销售闭环",\n        stage_desc="跟进、分配、成交流转",\n        table_headers=["商机ID", "标题", "公司", "负责人", "等级", "状态", "跟进次数", "最近跟进", "预估价值"],'),

    # --- Opportunity timeline ---
    ('<h3>[User] Opportunity Timeline \u2014 ',
     '<h3>👤 商机追踪时间线 \u2014 '),
    ('<div class="label">Lead ID</div>',
     '<div class="label">商机ID</div>'),
    ('<div class="label">Title</div>',
     '<div class="label">标题</div>'),
    ('<div class="label">Company</div>',
     '<div class="label">公司</div>'),
    ('<div class="label">Channel</div>',
     '<div class="label">渠道</div>'),
    ('<div class="label">Grade</div>',
     '<div class="label">等级</div>'),
    ('<div class="label">Score</div>',
     '<div class="label">评分</div>'),
    ('<div class="label">Status</div>',
     '<div class="label">状态</div>'),
    ('<div class="label">Contact (masked)</div>',
     '<div class="label">联系方式(已脱敏)</div>'),
    ('Loading...</div>', '加载中...</div>'),
    ('Refresh Timeline</button>', '刷新时间线</button>'),
    ('<h3>[Clock] Lifecycle Timeline</h3>',
     '<h3>🕓 生命周期时间线</h3>'),
    ('Loading timeline data...</div>', '正在加载时间线数据...</div>'),
    ('<h3>[Link] Related Links</h3>',
     '<h3>🔗 相关链接</h3>'),
    ('View Source Task</a>', '查看源任务</a>'),
    ('Back to Leads</a>', '返回商机列表</a>'),
    ('Back to Funnel</a>', '返回漏斗看板</a>'),

    # --- Exception Pool ---
    ('<h3>[Exclamation] Exception Pool \u2014 异常数据集中管理</h3>',
     '<h3>⚠ 异常数据池 \u2014 异常集中管理</h3>'),
    ('<div class="stat-label">Total</div>',
     '<div class="stat-label">总数</div>'),
    ('<div class="stat-label">Pending</div>',
     '<div class="stat-label">待处理</div>'),
    ('<div class="stat-label">Resolved</div>',
     '<div class="stat-label">已处理</div>'),
    ('<div class="stat-label">7-Day Trend</div>',
     '<div class="stat-label">7日趋势</div>'),
    ('<h3>[Chart] Exception Types</h3>',
     '<h3>📊 异常类型分布</h3>'),
    ('<h3>[Filter] Filter Exception Items</h3>',
     '<h3>🔍 筛选异常条目</h3>'),
    ('<label>Type <select id="exception-filter-type">',
     '<label>类型 <select id="exception-filter-type">'),
    ('<option value="">All Types</option>',
     '<option value="">全部类型</option>'),
    ('<label>Channel <select id="exception-filter-channel">',
     '<label>渠道 <select id="exception-filter-channel">'),
    ('<option value="">All Channels</option>',
     '<option value="">全部渠道</option>'),
    ('<label>Status <select id="exception-filter-status">',
     '<label>状态 <select id="exception-filter-status">'),
    ('<option value="">All</option><option value="pending">Pending</option><option value="resolved">Resolved</option><option value="discarded">Discarded</option><option value="false_positive">False Positive</option>',
     '<option value="">全部</option><option value="pending">待处理</option><option value="resolved">已处理</option><option value="discarded">已废弃</option><option value="false_positive">误判</option>'),
    ('Apply Filter</button>', '应用筛选</button>'),
    ('<h3>[Ops] Manual Operations</h3>',
     '<h3>🛠 手工操作</h3>'),
    ('<h3>[Table] Exception Items</h3>',
     '<h3>📋 异常条目列表</h3>'),
    ('<thead><tr><th>Exception ID</th><th>Type</th><th>渠道</th><th>标题</th><th>状态</th><th>Created</th><th>Operations</th></tr></thead>',
     '<thead><tr><th>异常ID</th><th>类型</th><th>渠道</th><th>标题</th><th>状态</th><th>创建时间</th><th>操作</th></tr></thead>'),

    # --- Channel Funnel ---
    ('<h3>[Chart] Channel Funnel \u2014 分渠道转化效果看板</h3>',
     '<h3>📊 分渠道漏斗 \u2014 分渠道转化效果看板</h3>'),
    ('<label>Period <select id="channel-period">',
     '<label>周期 <select id="channel-period">'),
    ('<option value="week">Last 4 Weeks</option><option value="month">Last 3 Months</option>',
     '<option value="week">最近4周</option><option value="month">最近3个月</option>'),
    ('<label>Days <input type="number" id="channel-days"',
     '<label>天数 <input type="number" id="channel-days"'),
    ('Reload</button>', '重新加载</button>'),
    ('<div class="stat-label">Total Crawl</div>',
     '<div class="stat-label">累计抓取</div>'),
    ('<div class="stat-label">Total Won</div>',
     '<div class="stat-label">累计成交</div>'),
    ('<div class="stat-label">Overall Conv.</div>',
     '<div class="stat-label">综合转化率</div>'),
    ('<h3>[Cards] Channel Performance</h3>',
     '<h3>📇 各渠道表现</h3>'),
    ('Loading channel data...</div>', '正在加载渠道数据...</div>'),
    ('<h3>[Ranking] Top Channels by Category</h3>',
     '<h3>🏆 分类渠道排名</h3>'),
    ('<h3>[Clock] Period Trend</h3>',
     '<h3>🕓 周期趋势</h3>'),

    # --- Batch Operation ---
    ('<h3>[Cog] Submit Batch Operation</h3>',
     '<h3>⚙ 提交批量操作</h3>'),
    ('<label>Operation Type <select id="batch-op-type"',
     '<label>操作类型 <select id="batch-op-type"'),
    ('<label>Item IDs (comma separated, max 1000) ',
     '<label>条目ID（英文逗号分隔，最多1000条）'),
    ('placeholder="LEAD-123,LEAD-456,RAW-789..."',
     'placeholder="例如：LEAD-123,LEAD-456,RAW-789..."'),
    ('<label>Reason <input type="text" id="batch-reason"',
     '<label>操作原因 <input type="text" id="batch-reason"'),
    ('placeholder="Why this batch operation?"',
     'placeholder="请说明本次批量操作的原因"'),
    ('Submit Batch</button>', '提交批量操作</button>'),
    ('Fill Demo IDs</button>', '填充示例ID</button>'),
    ('<h3>[Spinner] Batch Progress</h3>',
     '<h3>⏳ 批量执行进度</h3>'),
    ('Refresh Status</button>', '刷新状态</button>'),
    ('<h3>[History] Recent Batch Operations</h3>',
     '<h3>📋 最近批量操作</h3>'),
    ('<thead><tr><th>批次ID</th><th>Operation</th><th>Operator</th><th>Total</th><th>成功数</th><th>失败</th><th>状态</th><th>Risk</th><th>Started</th></tr></thead>',
     '<thead><tr><th>批次ID</th><th>操作</th><th>操作人</th><th>总数</th><th>成功数</th><th>失败数</th><th>状态</th><th>风险等级</th><th>开始时间</th></tr></thead>'),

    # --- Export Center ---
    ('<h3>[Download] Export Center</h3>',
     '<h3>📥 数据导出中心</h3>'),
    ('<label>Stage <select id="export-stage"',
     '<label>阶段 <select id="export-stage"'),
    ('<label><input type="checkbox" id="export-plaintext"',
     '<label><input type="checkbox" id="export-plaintext"'),
    ('Export Plaintext (Super Admin only)</label>',
     '导出明文（仅超级管理员）</label>'),
    ('<label>Reason <input type="text" id="export-reason"',
     '<label>导出原因 <input type="text" id="export-reason"'),
    ('placeholder="Brief description of the export purpose"',
     'placeholder="简要说明本次导出的用途"'),
    ('Submit Export</button>', '提交导出</button>'),
    ('<h3>[Spinner] Current Export</h3>',
     '<h3>⏳ 当前导出</h3>'),
    ('<h3>[History] Export History</h3>',
     '<h3>📋 导出历史</h3>'),
    ('<thead><tr><th>Export ID</th><th>Stage</th><th>Operator</th><th>Rows</th><th>Size</th><th>Masked</th><th>状态</th><th>Time</th><th>Download</th></tr></thead>',
     '<thead><tr><th>导出ID</th><th>阶段</th><th>操作人</th><th>行数</th><th>大小</th><th>脱敏</th><th>状态</th><th>时间</th><th>下载</th></tr></thead>'),

    # --- 其他剩余页面 ---
    # channels page
    ('<h3>[Rocket] Channel Accounts',
     '<h3>🚀 渠道账号'),
    ('Add/Update Account</div>',
     '新增 / 更新账号</div>'),
    ('Account ID:</div>', '账号ID</div>'),
    ('Username:</div>', '用户名：</div>'),
    ('Password (encrypted):</div>', '密码（加密存储）：</div>'),
    ('Daily Quota:</div>', '每日发送额度：</div>'),
    ('Existing Accounts</div>', '现有账号</div>'),
    ('"No channel accounts yet."', '"暂无渠道账号。"'),

    # sales page
    ('<h3>[Users] Sales Team</h3>',
     '<h3>👥 销售团队</h3>'),
    ('<div class="section-title">Add/Update Salesperson</div>',
     '<div class="section-title">新增 / 更新销售人员</div>'),
    ('Sales ID:</div>', '销售ID：</div>'),
    ('Full Name:</div>', '姓名：</div>'),
    ('Industries (comma separated):</div>',
     '负责行业（逗号分隔）：</div>'),
    ('Weight:</div>', '权重：</div>'),
    ('Phone (encrypted):</div>', '手机（加密存储）：</div>'),
    ('Email:</div>', '邮箱：</div>'),
    ('<div class="section-title">Assign Opportunities</div>',
     '<div class="section-title">商机分配</div>'),
    ('Opportunity ID:</div>', '商机ID：</div>'),
    ('Customer:</div>', '客户：</div>'),
    ('Sales ID (empty=auto):</div>',
     '销售ID（留空=自动分配）：</div>'),
    ('<div class="section-title">Recent Assignments</div>',
     '<div class="section-title">最近分配记录</div>'),
    ('<div class="section-title">Manual Follow-up</div>',
     '<div class="section-title">手动跟进记录</div>'),
    ('Content:</div>', '内容：</div>'),
    ('<div class="section-title">Overdue Follow-up</div>',
     '<div class="section-title">逾期跟进</div>'),

    # spider task page
    ('<h3>[Folder] 7-Channel Quick Entry</h3>',
     '<h3>📁 七渠道快速入口</h3>'),
    ('<h3>[Cog] New Spider Task</h3>',
     '<h3>⚙ 新建爬虫任务</h3>'),
    ('Cron Expression:</div>', 'Cron 表达式：</div>'),
    ('Keywords (comma sep):</div>',
     '关键词（逗号分隔）：</div>'),
    ('Max Pages:</div>', '最大页数：</div>'),
    ('<h3>[Folder] Existing Tasks</h3>',
     '<h3>📁 已有任务</h3>'),
    ('<h3>[Scroll] Task Execution Logs</h3>',
     '<h3>📜 任务执行日志</h3>'),
    ('<h3>[Alert] Risk/Abnormal Events</h3>',
     '<h3>⚠ 风险/异常事件</h3>'),

    # audit log
    ('<h3>[Scroll] Admin Operation Log</h3>',
     '<h3>📜 管理后台操作日志</h3>'),
    ('<div class="section-title">Recent Actions</div>',
     '<div class="section-title">最近操作</div>'),

    # leads
    ('<h3>[Briefcase] Leads & Opportunities</h3>',
     '<h3>💼 商机线索与机会</h3>'),
    ('<div class="section-title">Filter</div>',
     '<div class="section-title">筛选条件</div>'),
    ('Keyword (title/customer):</div>',
     '关键词（标题/客户）：</div>'),
    ('Status:</div>', '状态：</div>'),
    ('<div class="section-title">Leads List</div>',
     '<div class="section-title">线索列表</div>'),

    # accounts
    ('<h3>[User] Admin Accounts</h3>',
     '<h3>👤 管理账号</h3>'),
    ('<div class="section-title">Create/Update Account</div>',
     '<div class="section-title">新建 / 更新账号</div>'),
    ('Role:</div>', '角色：</div>'),
    ('<div class="section-title">Existing Accounts</div>',
     '<div class="section-title">现有账号</div>'),

    # notifications
    ('<h3>[Bell] Admin Notifications</h3>',
     '<h3>🔔 管理通知</h3>'),
    ('<div class="section-title">Unread</div>',
     '<div class="section-title">未读消息</div>'),
    ('<div class="section-title">All</div>',
     '<div class="section-title">全部消息</div>'),

    # compliance review
    ('<h3>[Shield] Compliance Review</h3>',
     '<h3>🛡 合规审核</h3>'),
    ('<div class="section-title">Review Queue</div>',
     '<div class="section-title">待审核队列</div>'),
    ('<div class="section-title">Compliance Rules</div>',
     '<div class="section-title">合规规则</div>'),
    ('<div class="section-title">Review History</div>',
     '<div class="section-title">审核历史</div>'),

    # spider detail
    ('<h3>[Cog] Task Detail \u2014 ',
     '<h3>⚙ 任务详情 \u2014 '),
    ('<h3>[Folder] Task Configuration</h3>',
     '<h3>📁 任务配置</h3>'),
    ('<h3>[Clock] Recent Runs</h3>',
     '<h3>🕓 最近运行</h3>'),
    ('<h3>[Alert] Risk Events</h3>',
     '<h3>⚠ 风险事件</h3>'),

    # Dashboard stat card labels (remaining)
    ('<div class="label">Spider Tasks</div>',
     '<div class="label">爬虫任务数</div>'),
    ('<div class="label">Total Crawled</div>',
     '<div class="label">累计抓取</div>'),
    ('<div class="label">Valid Leads</div>',
     '<div class="label">有效商机</div>'),
    ('<div class="label">Sent Batches</div>',
     '<div class="label">触达批次</div>'),
    ('<div class="label">Channel Accounts</div>',
     '<div class="label">渠道账号数</div>'),
    ('<h3>[Chart] Sales Conversion Funnel</h3>',
     '<h3>📊 销售转化漏斗</h3>'),
    ('<h3>[Clock] Recent Scheduled Tasks</h3>',
     '<h3>🕓 最近调度任务</h3>'),

    # --- 数据看板 funnel area / recent tasks empty ---
    ('funnel-area"><div class="empty-inline">No data</div></div>',
     'funnel-area"><div class="empty-inline">暂无数据</div></div>'),
    ('recent-tasks"><div class="empty-inline">No data</div></div>',
     'recent-tasks"><div class="empty-inline">暂无数据</div></div>'),
]


def replace_in_file(path: Path, replacements: list[tuple[str, str]]) -> int:
    if not path.exists():
        print(f"  [SKIP] {path.name} (不存在)")
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
    print("🔤 第二轮：data_center + 各页面深度中文化")
    print("=" * 60)

    pages_path = WEB_ADMIN / "pages.py"
    n = replace_in_file(pages_path, PAGES_ROUND2)
    print(f"  pages.py: 替换 {n} 处")
    total += n

    print("\n" + "=" * 60)
    print(f"✅ 第二轮完成，共替换 {total} 处")
    print("=" * 60)
    return 0


if __name__ == "__main__":
    sys.exit(main())
