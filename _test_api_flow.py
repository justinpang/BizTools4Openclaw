"""测试 api_crawl_steps_preview_render 的完整流程。"""
import sys
sys.path.insert(0, '.')
import asyncio, re

# 模拟 API 调用
from web_admin.api.crawl_config import api_crawl_steps_preview_render
from web_admin.api.crawl_config import _sanitize_html, _crawl_steps_ok, _crawl_steps_err, _extract_title

class FakeRequest:
    def __init__(self, body):
        self._body = body
    async def json(self):
        return self._body

url = 'https://www.miit.gov.cn/jgsj/xgj/APPqhyhqyzxzzxd/tzgg/index.html'
req = FakeRequest({'url': url, 'render_wait_ms': 1500, 'http_method': 'GET'})
result = asyncio.run(api_crawl_steps_preview_render(req))

print('result type:', type(result))
if isinstance(result, dict):
    data = result.get('data', {}) if isinstance(result, dict) else {}
    if isinstance(data, dict):
        html_preview = data.get('html_preview', '')
        print(f'html_preview length: {len(html_preview)}')
        scripts = re.findall(r'<script', html_preview, flags=re.IGNORECASE)
        print(f'script tags in result: {len(scripts)}')
        if scripts:
            print('first few script tags:')
            for m in re.finditer(r'<script[^>]*>', html_preview, flags=re.IGNORECASE):
                print(f'  pos {m.start()}: {html_preview[m.start():m.start()+80]}')
                if m.start() > 50:
                    break
        with open(r'c:\projects\BizTools4Openclaw\_api_direct_test.html', 'w', encoding='utf-8') as f:
            f.write(html_preview)
        print('saved _api_direct_test.html')
else:
    print('result:', result)
