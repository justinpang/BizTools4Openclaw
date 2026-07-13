"""测试从已运行进程使用相同的路径调用 _sanitize_html。"""
import sys, re, importlib.util

with open(r'c:\projects\BizTools4Openclaw\_api_preview.html', encoding='utf-8') as f:
    html = f.read()

print(f"输入 html 长度: {len(html)}")
print(f"输入中 <script> 数量: {len(re.findall(r'<script', html, re.IGNORECASE))}")

# 导入 crawl_config 模块
spec = importlib.util.spec_from_file_location('crawl_config', r'c:\projects\BizTools4Openclaw\web_admin\api\crawl_config.py')
mod = importlib.util.module_from_spec(spec)
import logging
mod.logger = logging.getLogger('test')
spec.loader.exec_module(mod)

result = mod._sanitize_html(html)
print(f"清理后 html 长度: {len(result)}")
print(f"清理后 <script> 数量: {len(re.findall(r'<script', result, re.IGNORECASE))}")
print(f"清理后 <iframe> 数量: {len(re.findall(r'<iframe', result, re.IGNORECASE))}")

# 打印实际 HTML 的前 200 字节，看看 script 标签的格式
print("\n前 500 字节:")
print(html[:500])

# 检查实际 script 标签的格式
scripts = re.findall(r'<script[^>]*>', html[:2000], re.IGNORECASE)
print(f"\n前 2000 字节内 script 标签:")
for s in scripts[:5]:
    print(f'  {s}')
