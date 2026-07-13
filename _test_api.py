"""测试 api_crawl_steps_preview_render 的实际返回。"""
import requests

# 模拟登录后调用
session = requests.Session()
# 先从浏览器获取的 cookie
login_url = 'http://localhost:8000/admin/login'
# 调用预览 API
r = session.post('http://localhost:8000/api/admin/crawl/steps/preview-render',
                 json={'url': 'https://www.miit.gov.cn/jgsj/xgj/APPqhyhqyzxzzxd/tzgg/index.html',
                       'render_wait_ms': 1500})
print('status:', r.status_code)
data = r.json()
print('keys:', list(data.keys()))
print('html_preview length:', len(data.get('data', {}).get('html_preview', '') if isinstance(data.get('data'), dict) else data.get('html_preview', '')))

# 打印 html_preview
if isinstance(data.get('data'), dict):
    html = data['data'].get('html_preview', '')
else:
    html = data.get('html_preview', '')
print(f'\nhtml_preview length: {len(html)}')

# 检查是否包含 <script
import re
script_count = len(re.findall(r'<script\b', html, flags=re.IGNORECASE))
print(f'<script count: {script_count}')

# 检查是否包含 iframe
iframe_count = len(re.findall(r'<iframe\b', html, flags=re.IGNORECASE))
print(f'<iframe count: {iframe_count}')

# 检查是否有明显的结构重复
# 查找 "通知公告" 出现次数
tzgg_count = len(re.findall(r'通知公告', html))
print(f'"通知公告" count: {tzgg_count}')

# 保存
with open(r'c:\projects\BizTools4Openclaw\_api_result.html', 'w', encoding='utf-8') as f:
    f.write(html)
print('Saved _api_result.html')

# 分析 body 里的内容
body_match = re.search(r'<body[^>]*>([\s\S]*?)</body>', html, flags=re.IGNORECASE)
if body_match:
    print(f'\nbody length: {len(body_match.group(1))}')
    # 找 div 结构
    divs = [(m.start(), m.group()) for m in re.finditer(r'<div[^>]*>', body_match.group(1), flags=re.IGNORECASE)]
    print(f'divs in body: {len(divs)}')
    for pos, d in divs:
        cls_match = re.search(r'class\s*=\s*"([^"]+)"', d, flags=re.IGNORECASE)
        cls = cls_match.group(1) if cls_match else ''
        print(f'  {pos}: {d[:120]} | class={cls}')
else:
    print('\nNo <body> tag - checking raw head')
    print(html[:1500])
