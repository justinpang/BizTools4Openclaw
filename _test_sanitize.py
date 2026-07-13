"""测试 _sanitize_html 对实际 HTML 的处理。"""
import re

# 测试：有多个 script 块
html_multi_script = '''<!DOCTYPE html>
<html><head><meta charset="utf-8"><title>测试页</title></head>
<body>
<script>
var config = { foo: "bar" };
</script>

<div class="content-block-1">
  <h2>第一块：工作动态</h2>
  <ul><li>条目 1</li><li>条目 2</li></ul>
</div>

<script>
function doSomething() { alert("hi"); }
</script>

<div class="content-block-2">
  <h2>第二块：通知公告</h2>
  <ul><li>条目 A</li><li>条目 B</li></ul>
</div>

</body></html>
'''

def _sanitize_html(html, max_bytes=200*1024):
    if not html:
        return ""
    if len(html) > max_bytes:
        html = html[:max_bytes]
    html = re.sub(r"<script[\s>].*?</script>", "", html, flags=re.IGNORECASE | re.DOTALL)
    html = re.sub(r"<script[\s>].*?>", "", html, flags=re.IGNORECASE)
    html = re.sub(r"</script>", "", html, flags=re.IGNORECASE)
    return html

result = _sanitize_html(html_multi_script)
print('After sanitize:')
print(result)
print()
print('---')
# 统计 div content-block 出现次数
content_count = len(re.findall(r'content-block', result))
print(f'content-block count: {content_count}')

# 问题 2：miit.gov.cn 页面的 script 标签可能在 body 中
print('\n\n=== TEST 2: 检查实际 miit HTML 的 script 位置 ===')
with open(r'c:\projects\BizTools4Openclaw\_raw_html2.html', encoding='utf-8') as f:
    real_html = f.read()
print('Original length:', len(real_html))
clean = _sanitize_html(real_html)
print('Cleaned length:', len(clean))

# 找出 script 标签的位置
positions = [(m.start(), m.end(), m.group()) for m in re.finditer(r'<script[^>]*>.*?</script>', real_html, flags=re.IGNORECASE | re.DOTALL)]
print(f'Matched {len(positions)} script blocks (DOTALL greedy - single match!):')
for p in positions:
    print(f'  {p[0]}-{p[1]}: {p[2][:80]}')

# 非贪婪模式
positions2 = [(m.start(), m.end()) for m in re.finditer(r'<script[^>]*>.*?</script>', real_html, flags=re.IGNORECASE | re.DOTALL)]
print(f'Non-greedy? Actually DOTALL without ? is greedy')
print(f'  but with [^>]* on opening tag it would find each. Let me count:')

# 用非贪婪测试
clean_non_greedy = re.sub(r"<script[\s>].*?</script>", "", real_html, flags=re.IGNORECASE | re.DOTALL)
clean_with_question = re.sub(r"<script[\s>].*?</script>", "", real_html, flags=re.IGNORECASE | re.DOTALL)
# 添加 ? 试试
clean_fixed = re.sub(r"<script[\s>].*?</script>", "", real_html, flags=re.IGNORECASE | re.DOTALL)
print('Same - ? required for non-greedy')

clean_non_greedy2 = re.sub(r"<script[\s>].*?</script>?", "", real_html, flags=re.IGNORECASE | re.DOTALL)  # no, ? applies to preceding
clean_lazy = re.sub(r"<script[\s>].*?</script>", "", real_html, flags=re.IGNORECASE | re.DOTALL)
clean_lazy2 = re.sub(r"<script[\s>][\s\S]*?</script>", "", real_html, flags=re.IGNORECASE)

# 正确的非贪婪：添加 ? 在 * 后面
clean_proper = re.sub(r"<script[\s>].*?</script>", "", real_html, flags=re.IGNORECASE | re.DOTALL)
clean_lazy_proper = re.sub(r"<script[\s>].*?</script>", "", real_html, flags=re.IGNORECASE | re.DOTALL | re.UNICODE)

clean_correct = re.sub(r"<script(\s[^>]*)?>.*?</script>", "", real_html, flags=re.IGNORECASE | re.DOTALL)  # same greedy
clean_correct_lazy = re.sub(r"<script(\s[^>]*)?>.*?</script>", "", real_html, flags=re.IGNORECASE | re.DOTALL)

print('len original:', len(real_html))
print('len after greedy DOTALL sub:', len(clean_correct))
print('len after non-greedy sub:', len(re.sub(r"<script(\s[^>]*)?>.*?</script>", "", real_html, flags=re.IGNORECASE)))  # no DOTALL

# 不带 DOTALL，只匹配单行内的 script
clean_no_dotall = re.sub(r"<script[\s>][\s\S]*?</script>", "", real_html, flags=re.IGNORECASE)
print('len using [\s\S]*? pattern:', len(re.sub(r"<script\b[^>]*>[\s\S]*?</script>", "", real_html, flags=re.IGNORECASE)))

# 用 [\s\S]*? 非贪婪匹配
clean_lazy_chars = re.sub(r"<script\b[^>]*>[\s\S]*?</script>", "", real_html, flags=re.IGNORECASE)
print('len with lazy [\s\S]*? :', len(clean_lazy_chars))

# 查看 clean 后的 HTML 结构
from bs4 import BeautifulSoup
soup_original = BeautifulSoup(real_html, 'html.parser')
print('\nOriginal body structure:')
body = soup_original.find('body')
if body:
    for tag in body.find_all(['div', 'ul', 'table', 'ol']):
        cls = tag.get('class', '')
        ids = tag.get('id', '')
        text = tag.get_text(' ', strip=True)[:50]
        print(f'  <{tag.name}> class={cls} id={ids}: {text}')

print('\nAfter clean (greedy DOTALL) body structure:')
soup_clean = BeautifulSoup(clean_correct, 'html.parser')
body2 = soup_clean.find('body')
if body2:
    for tag in body2.find_all(['div', 'ul', 'table', 'ol']):
        cls = tag.get('class', '')
        ids = tag.get('id', '')
        text = tag.get_text(' ', strip=True)[:50]
        print(f'  <{tag.name}> class={cls} id={ids}: {text}')

# 保存两个版本对比
with open(r'c:\projects\BizTools4Openclaw\_clean_greedy.html', 'w', encoding='utf-8') as f:
    f.write(clean_correct)
with open(r'c:\projects\BizTools4Openclaw\_clean_lazy.html', 'w', encoding='utf-8') as f:
    f.write(clean_lazy_chars)

# 查找 clean_greedy 中是否有明显的结构断裂
break_positions = []
for m in re.finditer(r'</?script', real_html, flags=re.IGNORECASE):
    break_positions.append(m.start())
print(f'\nscript tag positions: {break_positions}')
print(f'first script at {break_positions[0] if break_positions else -1}')
print(f'last </script> at {break_positions[-1] if break_positions else -1}')
print(f'content between them would be LOST with greedy DOTALL match!')
