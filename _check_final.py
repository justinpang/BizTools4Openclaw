"""生成完整的 iframe srcdoc HTML，检查是否有重复。"""
import re

with open(r'c:\projects\BizTools4Openclaw\_raw_html2.html', encoding='utf-8') as f:
    html = f.read()

# 1. 用正则提取脚本之外的内容（不清理 script，保留给 iframe 实际执行）
# 模拟 _buildIframeContent
our_css = 'body{margin:0;padding:12px;font-family:"Microsoft YaHei",Arial,sans-serif;font-size:14px;line-height:1.6;color:#333;background:#fff;}' \
         'table{border-collapse:collapse;border-spacing:0;margin:12px 0;}' \
         'table td,table th{border:1px solid #ddd;padding:6px 10px;text-align:left;}' \
         'table th{background:#f5f5f5;font-weight:600;}' \
         'table tr:nth-child(even){background:#fafafa;}' \
         'ul,ol{margin:8px 0;padding-left:24px;}' \
         'li{margin:4px 0;}' \
         'a{color:#2563eb;text-decoration:none;}' \
         'a:hover{text-decoration:underline;}' \
         'h1,h2,h3,h4,h5{margin:12px 0 8px 0;font-weight:600;color:#111;}' \
         '.dqwz,.breadcrumb{background:#f0f7ff;padding:10px;border-radius:4px;font-size:12px;color:#666;}' \
         '.main,.page-con{max-width:100%;}' \
         '.list{list-style:none;padding:0;margin:12px 0;}' \
         '.list li{padding:8px 12px;border-bottom:1px solid #eee;}' \
         '.list li a{color:#333;}' \
         'img{max-width:100%;height:auto;}' \
         '.lmy_main_l{float:left;width:220px;margin-right:16px;background:#f8fafc;padding:12px;border-radius:6px;}' \
         '.lmy_main_r{overflow:hidden;}' \
         '.lmy_main_rt{font-size:18px;font-weight:600;color:#0f172a;border-bottom:2px solid #2563eb;padding-bottom:8px;margin-bottom:12px;}' \
         '.lmy_main_rb{background:#fff;padding:16px;}' \
         '.lmy_main_rb li{list-style:none;padding:8px 0;border-bottom:1px dashed #e5e7eb;}' \
         '.lmy_main_rb li .fl{color:#334155;}' \
         '.lmy_main_rb li .fr{color:#94a3b8;font-size:12px;float:right;}'

base_href = 'https://www.miit.gov.cn/jgsj/xgj/APPqhyhqyzxzzxd/tzgg/'
base_tag = f'<base href="{base_href}" target="_blank">'
click_script = '<script>(function(){ /* click handler */ })();</script>'

lower_html = html.lower()
head_idx = lower_html.find("</head>")
print(f'head_idx: {head_idx}')

if head_idx >= 0:
    inject = base_tag + '<meta name="viewport" content="width=device-width,initial-scale=1">' + '<style>' + our_css + '</style>' + click_script
    result = html[:head_idx] + inject + html[head_idx:]
    with open(r'c:\projects\BizTools4Openclaw\_iframe_final.html', 'w', encoding='utf-8') as f:
        f.write(result)
    print(f'Written {len(result)} chars to _iframe_final.html')

# 现在分析生成的 HTML 的 DOM 结构
from bs4 import BeautifulSoup
soup = BeautifulSoup(result, 'html.parser')

# 打印 body 内的 div 结构
body = soup.find('body')
if body:
    print('\n=== Body 内的顶层元素 ===')
    for i, child in enumerate(body.find_all(recursive=False)):
        if hasattr(child, 'name') and child.name:
            cls = child.get('class', '')
            ids = child.get('id', '')
            text = child.get_text(' ', strip=True)[:80]
            print(f'{i}. <{child.name}> class={cls} id={ids}: {text}')

    # 检查是否有两个结构相似的大容器
    print('\n=== 检查 page-con 和 main 容器 ===')
    for cls_name in ['page-con', 'main', 'wrapper']:
        elements = soup.find_all('div', class_=cls_name)
        print(f'{cls_name}: {len(elements)} 个')
        for j, el in enumerate(elements):
            # 计算每个元素内的文本长度
            txt_len = len(el.get_text(' ', strip=True))
            child_divs = el.find_all('div', recursive=False)
            print(f'  #{j}: text_len={txt_len}, direct_children={len(child_divs)}')

    # 检查是否有 "大容器" 内容被重复包含
    print('\n=== 检查包含关系 ===')
    wrappers = soup.find_all('div', class_='wrapper')
    if wrappers:
        wrapper = wrappers[0]
        # 检查 wrapper 里是否包含了 page-con 和 main，同时 wrapper 外也有内容
        print(f'wrapper 内 div 数量: {len(wrapper.find_all("div"))}')
        # 打印 wrapper 内直接子元素
        for k, child in enumerate(wrapper.find_all(recursive=False)):
            if hasattr(child, 'name') and child.name:
                cls = child.get('class', '')
                txt = child.get_text(' ', strip=True)[:60]
                print(f'  直接子元素 #{k}: <{child.name}> class={cls}: {txt}')

# 检查是否有两个"通知公告"文本块（可能是左侧导航和右侧标题都显示"通知公告"）
print('\n=== 包含"通知公告"的元素 ===')
from bs4 import NavigableString
for tag in soup.find_all():
    text = tag.get_text(' ', strip=True)
    if '通知公告' in text and len(text) < 200:
        # 检查是否是叶节点或小节点
        if tag.name in ['li', 'p', 'h1', 'h2', 'h3', 'div', 'a']:
            cls = tag.get('class', '')
            text_short = tag.get_text(' ', strip=True)[:100]
            print(f'  <{tag.name}> class={cls}: {text_short}')
