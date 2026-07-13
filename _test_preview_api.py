"""测试 crawl steps preview-render API。"""
import requests, json, re

base = 'http://localhost:8000'
session = requests.Session()

# 1) 登录
r = session.post(f'{base}/api/admin/accounts/login',
                 json={'username': 'admin', 'password': 'admin123'},
                 headers={'Content-Type': 'application/json'})
print('login status:', r.status_code)
print('login body:', r.text[:300])

# 2) 测试 preview-render
r2 = session.post(f'{base}/api/admin/crawl/steps/preview-render',
                  json={'url': 'https://www.miit.gov.cn/jgsj/xgj/APPqhyhqyzxzzxd/tzgg/index.html',
                        'render_wait_ms': 1500,
                        'http_method': 'GET'},
                  headers={'Content-Type': 'application/json'})
print('\npreview status:', r2.status_code)
data = r2.json()
print('keys:', list(data.keys()))

if 'data' in data:
    html_preview = data['data'].get('html_preview', '')
    print(f'\nhtml_preview length: {len(html_preview)}')

    # 检查是否有 <script> 残留
    scripts = re.findall(r'<script[^>]*>', html_preview, flags=re.IGNORECASE)
    print(f'script tags: {len(scripts)}')

    # 检查是否有 <iframe> 残留
    iframes = re.findall(r'<iframe[^>]*>', html_preview, flags=re.IGNORECASE)
    print(f'iframe tags: {len(iframes)}')

    # 检查是否有"通知公告"重复
    occurrences = [(m.start(), m.end()) for m in re.finditer(r'通知公告', html_preview)]
    print(f'"通知公告"出现次数: {len(occurrences)}')

    # 保存 HTML 以便检查
    with open(r'c:\projects\BizTools4Openclaw\_api_preview.html', 'w', encoding='utf-8') as f:
        f.write(html_preview)
    print('\nSaved to _api_preview.html')

    # 检查 body 结构
    body_match = re.search(r'<body[^>]*>([\s\S]*?)</body>', html_preview, flags=re.IGNORECASE)
    if body_match:
        body_content = body_match.group(1)
        print(f'\nbody content length: {len(body_content)}')
        # 检查 div class="page-con" 数量
        for cls in ['page-con', 'main', 'lmy_main', 'wrapper']:
            count = len(re.findall(rf'<div[^>]*class\s*=\s*"[^"]*{re.escape(cls)}[^"]*"', body_content, flags=re.IGNORECASE))
            print(f'  div class="{cls}": {count}')
    else:
        print('\n没有 body 标签 - 检查是否是片段包装：')
        print(html_preview[:500])
else:
    print('\n响应中没有 data 字段:', json.dumps(data, ensure_ascii=False, indent=2)[:1000])
