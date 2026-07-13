"""分析 _sanitize_html 和 _buildIframeContent 的组合效果。"""
import re

# 1. 测试 _sanitize_html
def _sanitize_html(html, max_bytes=200*1024):
    if not html:
        return ""
    if len(html) > max_bytes:
        html = html[:max_bytes]
    html = re.sub(r"<script[\s>].*?</script>", "", html, flags=re.IGNORECASE | re.DOTALL)
    html = re.sub(r"<script[\s>].*?>", "", html, flags=re.IGNORECASE)
    html = re.sub(r"</script>", "", html, flags=re.IGNORECASE)
    return html

# 2. 模拟 JS 的 _buildIframeContent
def build_iframe_content(raw_html, base_href):
    our_css = '<style>body{margin:0;padding:12px;}</style>'
    base_tag = f'<base href="{base_href}" target="_blank">'
    click_script = '<script>(function(){})();</script>'
    
    lower_html = raw_html.lower()
    is_full_doc = lower_html.find("<!doctype") >= 0 or lower_html.find("<html") >= 0
    
    if is_full_doc:
        head_idx = lower_html.find("</head>")
        if head_idx >= 0:
            inject = base_tag + our_css + click_script
            result = raw_html[:head_idx] + inject + raw_html[head_idx:]
            return result
        body_open_idx = lower_html.find("<body")
        if body_open_idx >= 0:
            body_close_idx = lower_html.find(">", body_open_idx)
            inject = base_tag + our_css + click_script
            return raw_html[:body_close_idx+1] + inject + raw_html[body_close_idx+1:]
    
    return f'<!DOCTYPE html><html><head><meta charset="utf-8">{base_tag}{our_css}</head><body>{click_script}{raw_html}</body></html>'

# 测试 1：典型 HTML，head 中有 meta, 有 body
html1 = '''<!DOCTYPE html>
<html><head><meta charset="utf-8"><title>测试</title></head>
<body>
<div class="lmy_main_rb"><ul><li>条目1</li><li>条目2</li></ul></div>
</body></html>
'''
result1 = build_iframe_content(html1, 'https://example.com/')
print('TEST 1 - normal doc')
print('result length:', len(result1))
print(result1)
print()

# 测试 2：</head> 出现在字符串常量中（即有字符串 "head" 出现在脚本内容中）
html2 = '''<!DOCTYPE html>
<html><head><meta charset="utf-8"><script>
var x = "</head>";
alert("fake end");
</script><title>测试</title></head>
<body>
<div class="lmy_main_rb"><ul><li>条目1</li><li>条目2</li></ul></div>
</body></html>
'''
result2 = build_iframe_content(html2, 'https://example.com/')
print('TEST 2 - </head> in script')
print('result length:', len(result2))
print(result2)
print()

# 测试 3：有多个 </head> 或 字符串中含有 </head>
html3 = '''<!DOCTYPE html>
<html><head><meta charset="utf-8">
<script>
document.write('</head>');
</script>
<title>测试</title></head>
<body>
<div class="content"><p>内容 A</p></div>
<div class="content"><p>内容 B</p></div>
</body></html>
'''
result3 = build_iframe_content(html3, 'https://example.com/')
print('TEST 3 - fake </head> in script')
print('result length:', len(result3))
print(result3)
print()
