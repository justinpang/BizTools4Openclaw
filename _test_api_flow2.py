"""正确解析 JSONResponse 并测试。"""
import sys
sys.path.insert(0, '.')
import asyncio, re, json

from web_admin.api.crawl_config import api_crawl_steps_preview_render

class FakeRequest:
    def __init__(self, body):
        self._body = body
    async def json(self):
        return self._body

url = 'https://www.miit.gov.cn/jgsj/xgj/APPqhyhqyzxzzxd/tzgg/index.html'
req = FakeRequest({'url': url, 'render_wait_ms': 1500, 'http_method': 'GET'})
response = asyncio.run(api_crawl_steps_preview_render(req))
body = response.body if hasattr(response, 'body') else response.content
data = json.loads(body)
print('keys:', list(data.keys()))

if isinstance(data, dict) and data.get('data'):
    html_preview = data['data'].get('html_preview', '')
    print(f'html_preview length: {len(html_preview)}')
    scripts = re.findall(r'<script', html_preview, flags=re.IGNORECASE)
    print(f'script tags: {len(scripts)}')
    iframes = re.findall(r'<iframe', html_preview, flags=re.IGNORECASE)
    print(f'iframe tags: {len(iframes)}')
    print(f'total_size: {data.get("data").get("html_total_size")}')

    with open(r'c:\projects\BizTools4Openclaw\_api_direct2.html', 'w', encoding='utf-8') as f:
        f.write(html_preview)

    # 看看前 1500 字节
    print('\n前 1500 字节:')
    print(html_preview[:1500])
else:
    print('data:', data)
