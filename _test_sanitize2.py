import sys, re, importlib.util, logging

with open(r'c:\projects\BizTools4Openclaw\_raw_html2.html', encoding='utf-8') as f:
    html = f.read()

spec = importlib.util.spec_from_file_location('crawl_config', r'c:\projects\BizTools4Openclaw\web_admin\api\crawl_config.py')
mod = importlib.util.module_from_spec(spec)
mod.logger = logging.getLogger('test')
spec.loader.exec_module(mod)

result = mod._sanitize_html(html)
print(f'原始长度: {len(html)}, 清理后: {len(result)}')
print(f'包含 script: {"<script" in result.lower()}')
print(f'包含 iframe: {"<iframe" in result.lower()}')
print(f'包含 pdf-attachment: {"pdf-attachment" in result}')

cleaned = mod._sanitize_html(html[:204800])
print(f'\n最终 html_preview 长度: {len(cleaned)}')
remaining = len(re.findall(r'<script', cleaned, re.IGNORECASE))
print(f'残留 script 标签: {remaining}')
