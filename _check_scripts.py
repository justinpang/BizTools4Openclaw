"""检查实际 API 返回的 html 中 script 标签的格式。"""
import re

with open(r'c:\projects\BizTools4Openclaw\_api_preview2.html', encoding='utf-8') as f:
    html = f.read()

# 找到所有 script 标签
script_open = [(m.start(), m.group()) for m in re.finditer(r'<script[^>]*>', html, flags=re.IGNORECASE)]
print(f'共找到 {len(script_open)} 个 script 开始标签')

# 打印每个标签的完整格式
for i, (pos, tag) in enumerate(script_open[:30]):
    # 找到结束标签
    end_match = re.search(r'</script>', html[pos:], flags=re.IGNORECASE)
    if end_match:
        end_pos = pos + end_match.end()
        full_block = html[pos:end_pos]
        print(f'  #{i} pos={pos} len={len(full_block)}: {full_block[:120]}')
    else:
        print(f'  #{i} pos={pos} NO end tag: {html[pos:pos+100]}')

# 看看 _sanitize_html 实际能处理多少
print('\n--- 测试手动调用 _sanitize_html ---')
spec_text = open(r'c:\projects\BizTools4Openclaw\web_admin\api\crawl_config.py', encoding='utf-8').read()

# 直接从本地测试
import importlib.util, logging
spec = importlib.util.spec_from_file_location('cc', r'c:\projects\BizTools4Openclaw\web_admin\api\crawl_config.py')
mod = importlib.util.module_from_spec(spec)
mod.logger = logging.getLogger('test')
spec.loader.exec_module(mod)

result = mod._sanitize_html(html)
print(f'原长度 {len(html)}, 清理后 {len(result)}')
print(f'清理后 script 标签: {len(re.findall(r"<script", result, re.IGNORECASE))}')

# 保存清理后的结果
with open(r'c:\projects\BizTools4Openclaw\_sanitized.html', 'w', encoding='utf-8') as f:
    f.write(result)
print('已保存到 _sanitized.html')

# 查看残留的 script 标签格式
residual = [(m.start(), m.group()) for m in re.finditer(r'<script[^>]*>', result, flags=re.IGNORECASE)]
print(f'\n残留的 script 标签: {len(residual)}')
for i, (pos, tag) in enumerate(residual[:10]):
    print(f'  #{i}: {tag[:80]}  (上下文: ...{result[max(0,pos-20):pos+80]}...)')
