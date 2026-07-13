"""Debug: 直接测试 API 调用，检查是否真的走到了 _sanitize_html。"""
import requests, re, json

base = 'http://localhost:8000'

# 1) 测试 steps/preview-render
r = requests.post(f'{base}/api/admin/crawl/steps/preview-render',
                  json={'url': 'https://www.miit.gov.cn/jgsj/xgj/APPqhyhqyzxzzxd/tzgg/index.html',
                        'render_wait_ms': 1500,
                        'http_method': 'GET'},
                  headers={'Content-Type': 'application/json'})
print('steps/preview-render status:', r.status_code)
d = r.json()
print('response code:', d.get('code'), 'msg:', d.get('msg'))
if d.get('data'):
    html_p = d['data'].get('html_preview', '')
    print(f'html_preview length: {len(html_p)}')
    print(f'<script count: {len(re.findall(r"<script", html_p, flags=re.IGNORECASE))}')
    print(f'masked: {d["data"].get("masked")}')
    print(f'total_size: {d["data"].get("html_total_size")}')

# 2) 测试 /crawl/preview/render
r2 = requests.post(f'{base}/api/admin/crawl/preview/render',
                   json={'url': 'https://www.miit.gov.cn/jgsj/xgj/APPqhyhqyzxzzxd/tzgg/index.html',
                         'render_js': False})
print('\n/crawl/preview/render status:', r2.status_code)
d2 = r2.json()
print('response code:', d2.get('code'), 'msg:', d2.get('msg'))
if d2.get('data'):
    html_p2 = d2['data'].get('html_preview', '')
    print(f'html_preview length: {len(html_p2)}')
    print(f'<script count: {len(re.findall(r"<script", html_p2, flags=re.IGNORECASE))}')
else:
    print('full response:', json.dumps(d2, ensure_ascii=False)[:500])

# 3) 检查 API router 的 include
print('\n--- 检查 crawl_config router 中的路径 ---')
import sys
sys.path.insert(0, '.')
from web_admin.api.crawl_config import router
print('Router type:', type(router))
print('Router prefix:', getattr(router, 'prefix', 'n/a'))
routes = getattr(router, 'routes', [])
print(f'Number of routes: {len(routes)}')
for route in routes:
    path = getattr(route, 'path', '')
    methods = getattr(route, 'methods', set())
    if 'preview' in path.lower() or 'render' in path.lower():
        print(f'  {methods} {path}')
