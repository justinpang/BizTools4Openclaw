"""再次测试 crawl steps preview-render API。"""
import requests, json, re

base = 'http://localhost:8000'
session = requests.Session()

# 测试 preview-render
r2 = session.post(f'{base}/api/admin/crawl/steps/preview-render',
                  json={'url': 'https://www.miit.gov.cn/jgsj/xgj/APPqhyhqyzxzzxd/tzgg/index.html',
                        'render_wait_ms': 1500,
                        'http_method': 'GET'},
                  headers={'Content-Type': 'application/json'})
print('preview status:', r2.status_code)
data = r2.json()
print('keys:', list(data.keys()))

if isinstance(data, dict) and 'data' in data:
    html_preview = data['data'].get('html_preview', '')
    print(f'\nhtml_preview length: {len(html_preview)}')

    scripts = re.findall(r'<script[^>]*>', html_preview, flags=re.IGNORECASE)
    print(f'script tags: {len(scripts)}')

    iframes = re.findall(r'<iframe[^>]*>', html_preview, flags=re.IGNORECASE)
    print(f'iframe tags: {len(iframes)}')

    occurrences = [(m.start(), m.end()) for m in re.finditer(r'通知公告', html_preview)]
    print(f'"通知公告"出现次数: {len(occurrences)}')

    with open(r'c:\projects\BizTools4Openclaw\_api_preview2.html', 'w', encoding='utf-8') as f:
        f.write(html_preview)
    print('\nSaved to _api_preview2.html')

    body_match = re.search(r'<body[^>]*>([\s\S]*?)</body>', html_preview, flags=re.IGNORECASE)
    if body_match:
        body_content = body_match.group(1)
        print(f'\nbody content length: {len(body_content)}')
        for cls in ['page-con', 'main', 'lmy_main', 'wrapper']:
            count = len(re.findall(rf'<div[^>]*class\s*=\s*"[^"]*{re.escape(cls)}[^"]*"', body_content, flags=re.IGNORECASE))
            print(f'  div class="{cls}": {count}')

    # 测试另一个 URL （有 iframe 的）
    print('\n\n===== 测试带 iframe 的页面 =====')
    r3 = session.post(f'{base}/api/admin/crawl/steps/preview-render',
                      json={'url': 'https://www.example.com',
                            'render_wait_ms': 1500,
                            'http_method': 'GET'},
                      headers={'Content-Type': 'application/json'})
    print('status:', r3.status_code)
    d3 = r3.json()
    if 'data' in d3:
        hp3 = d3['data'].get('html_preview', '')
        print(f'html_preview length: {len(hp3)}')
        scripts3 = re.findall(r'<script[^>]*>', hp3, flags=re.IGNORECASE)
        iframes3 = re.findall(r'<iframe[^>]*>', hp3, flags=re.IGNORECASE)
        embeds3 = re.findall(r'<embed[^>]*>', hp3, flags=re.IGNORECASE)
        objects3 = re.findall(r'<object[^>]*>', hp3, flags=re.IGNORECASE)
        print(f'script: {len(scripts3)}, iframe: {len(iframes3)}, embed: {len(embeds3)}, object: {len(objects3)}')
else:
    print('没有 data 字段:', json.dumps(data, ensure_ascii=False, indent=2)[:500])
