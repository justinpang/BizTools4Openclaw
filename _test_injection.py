"""测试 _buildIframeContent 对真实 HTML 的处理效果。"""
import re

with open(r'c:\projects\BizTools4Openclaw\_raw_html2.html', encoding='utf-8') as f:
    html = f.read()

# 先用 _sanitize_html 处理
html2 = re.sub(r"<script[\s>].*?</script>", "", html, flags=re.IGNORECASE | re.DOTALL)
html2 = re.sub(r"<script[\s>].*?>", "", html2, flags=re.IGNORECASE)
html2 = re.sub(r"</script>", "", html2, flags=re.IGNORECASE)
html2 = re.sub(r"<iframe[\s>].*?</iframe>", "", html2, flags=re.IGNORECASE | re.DOTALL)
html2 = re.sub(r"<iframe[\s>].*?>", "", html2, flags=re.IGNORECASE)
html2 = re.sub(r"</iframe>", "", html2, flags=re.IGNORECASE)

# 再模拟 JS 的 _buildIframeContent 
base_href = 'https://www.miit.gov.cn/jgsj/xgj/APPqhyhqyzxzzxd/tzgg/'
our_css = '<style>body{margin:0;padding:12px;font-family:"Microsoft YaHei",Arial,sans-serif;font-size:14px;line-height:1.6;color:#333;background:#fff;}table{border-collapse:collapse;border-spacing:0;margin:12px 0;}table td,table th{border:1px solid #ddd;padding:6px 10px;text-align:left;}table th{background:#f5f5f5;font-weight:600;}table tr:nth-child(even){background:#fafafa;}ul,ol{margin:8px 0;padding-left:24px;}li{margin:4px 0;}a{color:#2563eb;text-decoration:none;}a:hover{text-decoration:underline;}h1,h2,h3,h4,h5{margin:12px 0 8px 0;font-weight:600;color:#111;}.dqwz,.breadcrumb{background:#f0f7ff;padding:10px;border-radius:4px;font-size:12px;color:#666;}.main,.page-con{max-width:100%;}.list{list-style:none;padding:0;margin:12px 0;}.list li{padding:8px 12px;border-bottom:1px solid #eee;}.list li a{color:#333;}img{max-width:100%;height:auto;}.lmy_main_l{float:left;width:220px;margin-right:16px;background:#f8fafc;padding:12px;border-radius:6px;}.lmy_main_r{overflow:hidden;}.lmy_main_rt{font-size:18px;font-weight:600;color:#0f172a;border-bottom:2px solid #2563eb;padding-bottom:8px;margin-bottom:12px;}.lmy_main_rb{background:#fff;padding:16px;}.lmy_main_rb li{list-style:none;padding:8px 0;border-bottom:1px dashed #e5e7eb;}.lmy_main_rb li .fl{color:#334155;}.lmy_main_rb li .fr{color:#94a3b8;font-size:12px;float:right;}</style>'
base_tag = f'<base href="{base_href}" target="_blank">'
click_script = '<script>(function(){})();</script>'

lower_html = html2.lower()
is_full_doc = lower_html.find("<!doctype") >= 0 or lower_html.find("<html") >= 0
print(f'is_full_doc: {is_full_doc}')

head_idx = lower_html.find("</head>")
print(f'head_idx: {head_idx}')
print(f'HTML around head_idx: {repr(html2[max(0,head_idx-50):head_idx+80])}')

if head_idx >= 0:
    inject = base_tag + our_css + click_script
    result = html2[:head_idx] + inject + html2[head_idx:]
    
    print(f'\n=== After injection, result length: {len(result)} ===')
    
    # 检查是否有"两个"body 或 两个"相同的块"
    # 找 body 中的结构
    print('\n=== Looking for duplicate blocks ===')
    body_start = result.lower().find('<body')
    body_end = result.lower().find('</body')
    if body_start >= 0 and body_end >= 0:
        body_content = result[body_start:body_end]
        print(f'body content length: {len(body_content)}')
        
        # 检查是否有两个"page-con"或两个"main"
        for keyword in ['<div class="page-con"', '<div class="main"', '<div class="lmy_main"', '通知公告', '<div class="lmy_main_r"', '<div class="lmy_main_rb"']:
            cnt = len(re.findall(re.escape(keyword), body_content))
            print(f'  {keyword}: {cnt} occurrences')
        
        # 关键测试：检查 body 里有没有注入的 click_script
        # （如果 head_idx 找到但实际在 body 里会导致注入位置错误）
        if click_script[:100] in body_content:
            print('  WARNING: click_script appeared in body - injection position is wrong!')
    
    # 保存结果
    with open(r'c:\projects\BizTools4Openclaw\_injected_result.html', 'w', encoding='utf-8') as f:
        f.write(result)
    print('\nSaved _injected_result.html')
    
    # 检查 head_idx 之前的内容，确认是真正的 head
    print('\n=== Content before </head> ===')
    print(html2[max(0,head_idx-200):head_idx+80])
