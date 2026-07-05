#!/usr/bin/env python3
"""将 web_admin 前端与页面 Python 中的英文文本替换为中文。"""
from __future__ import annotations

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
WEB_ADMIN = PROJECT_ROOT / "web_admin"

# ============== 1) admin.js: 英文消息 -> 中文 ==============
JS_REPLACEMENTS: list[tuple[str, str]] = [
    # --- 空数据提示 ---
    ('<div class="empty-inline">No funnel data available.</div>',
     '<div class="empty-inline">暂无漏斗数据</div>'),
    ('<div class="empty-inline">No data available.</div>',
     '<div class="empty-inline">暂无数据</div>'),
    ('<div class="empty-inline">No trend data available.</div>',
     '<div class="empty-inline">暂无趋势数据</div>'),
    ('<tr><td colspan="5" class="empty">No items found</td></tr>',
     '<tr><td colspan="5" class="empty">暂无数据</td></tr>'),
    ('<tr><td colspan="7" class="empty">No items found</td></tr>',
     '<tr><td colspan="7" class="empty">暂无数据</td></tr>'),
    ('<tr><td colspan="9" class="empty">暂无批量任务</td></tr>',
     '<tr><td colspan="9" class="empty">暂无批量任务</td></tr>'),
    ('<tr><td colspan="9" class="empty">暂无导出记录</td></tr>',
     '<tr><td colspan="9" class="empty">暂无导出记录</td></tr>'),
    ('<div class="empty-inline">No timeline events available for this lead.</div>',
     '<div class="empty-inline">此商机暂无时间线事件</div>'),

    # --- 分页相关 ---
    ('<span class="muted">Page ',
     '<span class="muted">第 '),
    (' / ', ' / '),
    (' (total ', ' (共 '),
    ('">Prev</button>', '">上一页</button>'),
    ('">Next</button>', '">下一页</button>'),

    # --- 异常池按钮/状态 ---
    ('">Reinsert</button>', '">重新入库</button>'),
    ('">Discard</button>', '">废弃</button>'),
    ('">FP</button>', '">标记误判</button>'),
    ('">View</button>', '">查看</button>'),
    ('">操作</button>', '">操作</button>'),
    ('pending" === item.status', 'pending" === item.status'),
    ('"pending"', '"待处理"'),

    # --- 批量状态显示 ---
    ('\'<div><strong>Batch ID:</strong> \' + st.batch_id + \'</div>\'',
     '\'<div><strong>批量任务ID:</strong> \' + st.batch_id + \'</div>\''),
    ('\'Status: \' + st.status + \' | Total: \' + st.total + \' | Succeeded: \' + st.succeeded + \' | Failed: \' + st.failed',
     '\'状态：\' + ({"completed":"已完成","running":"执行中","pending":"等待中","failed":"已失败"}.get(st.status, st.status)) + \' | 总数：\' + st.total + \' | 成功：\' + st.succeeded + \' | 失败：\' + st.failed'),
    ('admin.showToast("批量任务完成：" + st.batch_id, "success");',
     'admin.showToast("批量任务已完成：" + st.batch_id, "success");'),

    # --- 导出相关 ---
    ('"batch operation"', '"批量操作"'),
    ('"data export"', '"数据导出"'),
    ('generating...', '生成中...'),
    ('\'<div><strong>Export ID:</strong> \' + st.export_id + \'</div>\'',
     '\'<div><strong>导出ID:</strong> \' + st.export_id + \'</div>\''),
    ('\'状态：\' + ({"completed":"已完成","running":"执行中","pending":"等待中","failed":"已失败"}.get(st.status, st.status))',
     '\'状态：\' + ({"ready":"已就绪","generating":"生成中","error":"错误","pending":"等待中"}.get(st.status, st.status))'),
    ('\'<div style="font-size:12px;color:#6b7a90;margin-top:4px;">Status: \' + st.status + \' | Rows: \' + rows + \' | Size: \' + size + \'</div>\'',
     '\'<div style="font-size:12px;color:#6b7a90;margin-top:4px;">状态：\' + ({"ready":"已就绪","generating":"生成中","error":"出错","pending":"等待中"}.get(st.status, st.status)) + \' | 行数：\' + rows + \' | 大小：\' + size + \'</div>\''),
    ('📥 Download CSV', '📥 下载CSV文件'),
    ('Masked', '已脱敏'),

    # --- 渠道漏斗 ---
    ('"By Conversion"', '"按转化率"'),
    ('"By Won Deals"', '"按成单数"'),
    ('"By Cost (Asc)"', '"按成本(升序)"'),
    ('"Period"', '"周期"'),
    ('Avg Cycle: ', '平均周期: '),
    (' days | ', ' 天 | '),
    ('Cost/Won: ', '成单成本: '),

    # --- 数据阶段映射（英文状态 -> 中文显示） ---
    ('\'Unknown\'', '\'未知\''),

    # --- 其他提示 ---
    ('"Spider task creation requires backend integration."',
     '"爬虫任务创建需要后端集成"'),
    ('"(stub)"', '"（占位）"'),
    ('"请填写操作类型 + 条目 ID"', '"请填写操作类型 + 条目ID"'),
    ('"批量任务已提交"', '"批量任务已提交"'),
    ("'提交失败：' + (data.msg || '未知错误')",
     "'提交失败：' + (data.msg || '未知错误')"),
    ("'提交异常：' + e", "'提交异常：' + e"),
    ("'导出任务已提交'", "'导出任务已提交'"),
    ("'导出失败：' + (data.msg || '未知错误')",
     "'导出失败：' + (data.msg || '未知错误')"),
    ("'导出异常：' + e", "'导出异常：' + e"),
    ("'导出已就绪：' + st.export_id, 'success'",
     "'导出已就绪：' + st.export_id, 'success'"),
    ("'文件下载已触发'", "'文件下载已触发'"),
    ("'下载异常：' + e", "'下载异常：' + e"),
]


# ============== 2) pages.py: 页面标题 & 静态内容 ==============
PAGES_TITLE_REPLACEMENTS: list[tuple[str, str]] = [
    ('"dashboard": "Dashboard",', '"dashboard": "仪表板",'),
    ('"spider": "Spider Tasks",', '"spider": "爬虫任务",'),
    ('"spider_detail": "Task Detail",', '"spider_detail": "任务详情",'),
    ('"leads": "Leads",', '"leads": "商机线索",'),
    ('"channels": "Channel Accounts",', '"channels": "渠道账号",'),
    ('"sales": "Sales Assignment",', '"sales": "销售分配",'),
    ('"audit_log": "Audit Log",', '"audit_log": "操作日志",'),
    ('"accounts": "Account Management",', '"accounts": "账号管理",'),
    ('"compliance_review": "Compliance Review",', '"compliance_review": "合规审核",'),
    ('"compliance_config": "Compliance Rules",', '"compliance_config": "合规规则配置",'),
    ('"notifications": "Message Center",', '"notifications": "消息中心",'),
    ('"data_center_dashboard": "Funnel Dashboard",', '"data_center_dashboard": "全链路漏斗看板",'),
    ('"data_center_collection": "Collection Stage",', '"data_center_collection": "采集阶段",'),
    ('"data_center_cleaning": "Cleaning Stage",', '"data_center_cleaning": "清洗结构化",'),
    ('"data_center_compliance": "Compliance Stage",', '"data_center_compliance": "合规校验",'),
    ('"data_center_grading": "Grading Stage",', '"data_center_grading": "商机分级",'),
    ('"data_center_outreach": "Outreach Stage",', '"data_center_outreach": "客户触达",'),
    ('"data_center_sales": "Sales Closing Stage",', '"data_center_sales": "销售闭环",'),
    ('"data_center_opportunity": "Opportunity Timeline",', '"data_center_opportunity": "商机时间线",'),
    ('"empty": "Empty State Demo",', '"empty": "空状态演示",'),
    ('"403": "Permission Denied",', '"403": "权限不足",'),
]

PAGES_FORBIDDEN_REPLACEMENTS: list[tuple[str, str]] = [
    ('[NoEntry]', '🚫'),
    ('Permission Denied', '权限不足'),
    ('Current role cannot access this page', '当前角色无权访问此页面'),
    ('missing permission', '缺少权限'),
    ('Please ask the super admin', '请联系超级管理员开通'),
    ('Back to Dashboard', '返回仪表板'),
]

PAGES_DASHBOARD_REPLACEMENTS: list[tuple[str, str]] = [
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
    ('<div id="funnel-area" class="funnel-area"><div class="empty-inline">No data</div></div>',
     '<div id="funnel-area" class="funnel-area"><div class="empty-inline">暂无数据</div></div>'),
    ('<h3>[Clock] Recent Scheduled Tasks</h3>',
     '<h3>🕒 最近调度任务</h3>'),
    ('<div id="recent-tasks"><div class="empty-inline">No data</div></div>',
     '<div id="recent-tasks"><div class="empty-inline">暂无数据</div></div>'),
]

PAGES_SPIDER_FILTER_REPLACEMENTS: list[tuple[str, str]] = [
    ('<h3>[Folder] 7-Channel Quick Entry</h3>',
     '<h3>📁 七渠道快速入口</h3>'),
    ('[Globe]', '🌐'),
    ('General Web/Forum', '通用网页/论坛'),
    ('Portal/Forum/BBS crawling', '门户/论坛/BBS采集'),
    ('[Movie]', '🎬'),
    ('Short Video', '短视频'),
    ('Douyin/Kuaishou/Video Channel', '抖音/快手/视频号'),
    ('[Book]', '📕'),
    ('Little Red Book', '小红书'),
    ('Notes/Videos/Likes filtering', '笔记/视频/点赞筛选'),
    ('[Q]', '❓'),
    ('Q&A Platform', '问答平台'),
    ('Zhihu/Baidu Knows', '知乎/百度知道'),
    ('[Factory]', '🏭'),
    ('B2B Supply', '供需B2B'),
    ('Supply/Sourcing platforms', '供应/采购平台'),
    ('[Clipboard]', '📋'),
    ('Bidding', '招投标'),
    ('Government/Private bids', '政府/企业招投标'),
    ('[Building]', '🏢'),
    ('Company Info', '企业工商'),
    ('Business registration data', '工商注册数据'),
    ('[Spreadsheet]', '📊'),
    ('Leads Dashboard', '商机看板'),
    ('Summarized opportunity overview', '商机汇总总览'),
]

# pages.py: 渠道账号页面 (channels)
PAGES_CHANNELS_REPLACEMENTS: list[tuple[str, str]] = [
    ('<h3>[Rocket] Channel Accounts (encrypted storage)</h3>',
     '<h3>📡 渠道账号（加密存储，永不回显明文）</h3>'),
    ('<div class="section-title">Add/Update Account</div>',
     '<div class="section-title">新增 / 更新账号</div>'),
    ('Channel:', '渠道：'),
    ('Account ID:', '账号ID：'),
    ('Username:', '用户名：'),
    ('Password (encrypted):', '密码（加密存储）：'),
    ('Daily Quota:', '每日发送额度：'),
    ('<span class="hint">Example: wechat_sender_01 / marketing@corp.com</span>',
     '<span class="hint">示例：wechat_sender_01 / marketing@corp.com</span>'),
    ('<div class="section-title">Existing Accounts</div>',
     '<div class="section-title">现有账号</div>'),
    ('"No channel accounts yet."', '"暂无渠道账号"'),
]

# pages.py: 销售页面 (sales)
PAGES_SALES_REPLACEMENTS: list[tuple[str, str]] = [
    ('<h3>[Users] Sales Team</h3>',
     '<h3>👥 销售团队</h3>'),
    ('<div class="section-title">Add/Update Salesperson</div>',
     '<div class="section-title">新增 / 更新销售人员</div>'),
    ('Sales ID:', '销售ID：'),
    ('Full Name:', '姓名：'),
    ('Industries (comma-separated):', '负责行业（逗号分隔）：'),
    ('Weight:', '权重：'),
    ('Phone (encrypted):', '手机（加密存储）：'),
    ('Email:', '邮箱：'),
    ('<div class="section-title">Assign Opportunities</div>',
     '<div class="section-title">分配商机</div>'),
    ('Opportunity ID:', '商机ID：'),
    ('Customer:', '客户：'),
    ('Sales ID (empty=auto):', '销售ID（留空=自动分配）：'),
    ('<div class="section-title">Recent Assignments</div>',
     '<div class="section-title">最近分配记录</div>'),
    ('<div class="section-title">Manual Follow-up</div>',
     '<div class="section-title">手动跟进记录</div>'),
    ('Content:', '内容：'),
    ('<div class="section-title">Overdue Follow-up</div>',
     '<div class="section-title">逾期跟进</div>'),
]

# pages.py: 合规审核页面 (compliance)
PAGES_COMPLIANCE_REPLACEMENTS: list[tuple[str, str]] = [
    ('<h3>[Shield] Compliance Review</h3>',
     '<h3>🛡 合规审核</h3>'),
    ('<div class="section-title">Review Queue</div>',
     '<div class="section-title">待审核队列</div>'),
    ('<div class="section-title">Compliance Rules</div>',
     '<div class="section-title">合规规则</div>'),
    ('<div class="section-title">Review History</div>',
     '<div class="section-title">审核历史</div>'),
]

# pages.py: 操作日志 (audit log)
PAGES_AUDIT_REPLACEMENTS: list[tuple[str, str]] = [
    ('<h3>[Scroll] Admin Operation Log</h3>',
     '<h3>📜 管理后台操作日志</h3>'),
    ('<div class="section-title">Recent Actions</div>',
     '<div class="section-title">最近操作</div>'),
]

# pages.py: 商机线索 (leads)
PAGES_LEADS_REPLACEMENTS: list[tuple[str, str]] = [
    ('<h3>[Briefcase] Leads & Opportunities</h3>',
     '<h3>💼 商机线索与机会</h3>'),
    ('<div class="section-title">Filter</div>',
     '<div class="section-title">筛选条件</div>'),
    ('Keyword (title/customer):', '关键词（标题/客户）：'),
    ('Status:', '状态：'),
    ('<div class="section-title">Leads List</div>',
     '<div class="section-title">线索列表</div>'),
]

# pages.py: 通知页面 (notifications)
PAGES_NOTIFICATIONS_REPLACEMENTS: list[tuple[str, str]] = [
    ('<h3>[Bell] Admin Notifications</h3>',
     '<h3>🔔 管理通知</h3>'),
    ('<div class="section-title">Unread</div>',
     '<div class="section-title">未读消息</div>'),
    ('<div class="section-title">All</div>',
     '<div class="section-title">全部消息</div>'),
]

# pages.py: 账号管理 (accounts)
PAGES_ACCOUNTS_REPLACEMENTS: list[tuple[str, str]] = [
    ('<h3>[User] Admin Accounts</h3>',
     '<h3>👤 管理账号</h3>'),
    ('<div class="section-title">Create/Update Account</div>',
     '<div class="section-title">新建 / 更新账号</div>'),
    ('Role:', '角色：'),
    ('<div class="section-title">Existing Accounts</div>',
     '<div class="section-title">现有账号</div>'),
]

# pages.py: 数据中心所有阶段页面 中文标题/描述
PAGES_DATACENTER_REPLACEMENTS: list[tuple[str, str]] = [
    ('Funnel Dashboard — 6-Stage Pipeline Overview',
     '全链路漏斗看板 — 六阶段流程总览'),
    ('Collection Stage — Raw crawled items',
     '采集阶段 — 原始抓取数据'),
    ('Cleaning Stage — Structured items',
     '清洗结构化 — 结构化后数据'),
    ('Compliance Stage — PII/Sensitive review',
     '合规校验 — 个人/敏感信息复核'),
    ('Grading Stage — Quality & opportunity score',
     '商机分级 — 质量与商机评分'),
    ('Outreach Stage — Email/WeChat sending',
     '客户触达 — 邮件/微信发送'),
    ('Sales Closing Stage — Assignment & follow-up',
     '销售闭环 — 分配与跟进'),
]

# pages.py: data_center 各阶段 HTML 中的英文表格列标题
TABLE_HEADER_REPLACEMENTS: list[tuple[str, str]] = [
    # collection stage columns
    ('<th>Task ID</th>', '<th>任务ID</th>'),
    ('<th>Task Name</th>', '<th>任务名称</th>'),
    ('<th>Channel</th>', '<th>渠道</th>'),
    ('<th>Status</th>', '<th>状态</th>'),
    ('<th>Crawled</th>', '<th>已抓取</th>'),
    ('<th>Failed</th>', '<th>失败</th>'),
    ('<th>Created At</th>', '<th>创建时间</th>'),
    # cleaning stage columns
    ('<th>Lead ID</th>', '<th>商机ID</th>'),
    ('<th>Title</th>', '<th>标题</th>'),
    ('<th>Company</th>', '<th>公司</th>'),
    ('<th>Contact (Masked)</th>', '<th>联系方式（已脱敏）</th>'),
    # compliance stage columns
    ('<th>Compliance Status</th>', '<th>合规状态</th>'),
    ('<th>Compliance Score</th>', '<th>合规评分</th>'),
    ('<th>Risk Level</th>', '<th>风险等级</th>'),
    ('<th>PII Types</th>', '<th>敏感信息类型</th>'),
    # grading stage columns
    ('<th>Grade</th>', '<th>等级</th>'),
    ('<th>Score</th>', '<th>分数</th>'),
    ('<th>Budget</th>', '<th>预算</th>'),
    ('<th>Urgency</th>', '<th>紧急程度</th>'),
    ('<th>Tags</th>', '<th>标签</th>'),
    # outreach stage columns
    ('<th>Batch ID</th>', '<th>批次ID</th>'),
    ('<th>Target Lead</th>', '<th>目标商机</th>'),
    ('<th>Target Count</th>', '<th>目标数量</th>'),
    ('<th>Succeeded</th>', '<th>成功数</th>'),
    ('<th>Sent At</th>', '<th>发送时间</th>'),
    # sales stage columns
    ('<th>Assignee</th>', '<th>负责人</th>'),
    ('<th>Follow-ups</th>', '<th>跟进次数</th>'),
    ('<th>Last Follow-up</th>', '<th>最近跟进</th>'),
    ('<th>Value</th>', '<th>预估价值</th>'),
]


# ============== 3) HTML 模板: 英文选项 -> 中文 ==============
HTML_TEMPLATE_REPLACEMENTS: list[tuple[str, str]] = [
    # channels.html: channel select options
    ('<option value="email">Email</option>',
     '<option value="email">邮件</option>'),
    ('<option value="wechat">企业微信</option>',
     '<option value="wechat">企业微信</option>'),
    ('<option value="feishu">飞书</option>',
     '<option value="feishu">飞书</option>'),
    ('<option value="dingtalk">钉钉</option>',
     '<option value="dingtalk">钉钉</option>'),

    # leads.html: status select options
    ('<option value="PENDING">待复核</option>',
     '<option value="PENDING">待复核</option>'),
    ('<option value="APPROVED">已通过</option>',
     '<option value="APPROVED">已通过</option>'),
    ('<option value="REJECTED">已拒绝</option>',
     '<option value="REJECTED">已拒绝</option>'),

    # sales.html: channel select options for follow-up
    ('<option>phone</option>',
     '<option value="phone">电话</option>'),
    ('<option>email</option>',
     '<option value="email">邮件</option>'),
    ('<option>meeting</option>',
     '<option value="meeting">会议</option>'),
    ('<option>wechat</option>',
     '<option value="wechat">微信</option>'),
]


def replace_in_file(path: Path, replacements: list[tuple[str, str]]) -> int:
    if not path.exists():
        print(f"  [SKIP] {path.name} (不存在)")
        return 0
    text = path.read_text(encoding="utf-8")
    changed = 0
    for old, new in replacements:
        if old in text:
            count = text.count(old)
            text = text.replace(old, new)
            changed += count
            # 只显示前几次替换的简短日志
    if changed:
        path.write_text(text, encoding="utf-8")
    return changed


def main() -> int:
    total = 0
    print("=" * 60)
    print("🔤  web_admin 前端/页面中文化")
    print("=" * 60)

    # 1) admin.js
    js_path = WEB_ADMIN / "static" / "js" / "admin.js"
    print(f"\n[1/3] 处理 {js_path.relative_to(PROJECT_ROOT)} ...")
    n = replace_in_file(js_path, JS_REPLACEMENTS)
    print(f"  ✅ 替换 {n} 处")
    total += n

    # 2) pages.py
    pages_path = WEB_ADMIN / "pages.py"
    print(f"\n[2/3] 处理 {pages_path.relative_to(PROJECT_ROOT)} ...")
    all_pages_replace = (
        PAGES_TITLE_REPLACEMENTS + PAGES_FORBIDDEN_REPLACEMENTS
        + PAGES_DASHBOARD_REPLACEMENTS + PAGES_SPIDER_FILTER_REPLACEMENTS
        + PAGES_CHANNELS_REPLACEMENTS + PAGES_SALES_REPLACEMENTS
        + PAGES_COMPLIANCE_REPLACEMENTS + PAGES_AUDIT_REPLACEMENTS
        + PAGES_LEADS_REPLACEMENTS + PAGES_NOTIFICATIONS_REPLACEMENTS
        + PAGES_ACCOUNTS_REPLACEMENTS + PAGES_DATACENTER_REPLACEMENTS
        + TABLE_HEADER_REPLACEMENTS
    )
    n = replace_in_file(pages_path, all_pages_replace)
    print(f"  ✅ 替换 {n} 处")
    total += n

    # 3) HTML 模板
    print(f"\n[3/3] 处理 HTML 模板 ...")
    for html_name in ["login.html", "partials/dashboard.html",
                       "partials/channels.html", "partials/leads.html",
                       "partials/sales.html", "partials/spider_task.html",
                       "partials/audit.html"]:
        html_path = WEB_ADMIN / "templates" / html_name
        n = replace_in_file(html_path, HTML_TEMPLATE_REPLACEMENTS)
        if n:
            print(f"  ✅ {html_name}: {n} 处")
        total += n

    print("\n" + "=" * 60)
    print(f"✅ 完成，共替换 {total} 处英文 -> 中文")
    print("=" * 60)
    return 0


if __name__ == "__main__":
    sys.exit(main())
