"""深入分析 miit.gov.cn HTML 的潜在重复点。"""
import re
from bs4 import BeautifulSoup

with open(r'c:\projects\BizTools4Openclaw\_raw_html2.html', encoding='utf-8') as f:
    html = f.read()

# 检查是否有 <noscript> 标签 - 有些网站会在 JS 渲染和 <noscript> 两种情况下重复渲染内容
print('=== NOSCRIPT TAGS ===')
noscript_count = 0
for ns in re.finditer(r'<noscript[^>]*>[\s\S]*?</noscript>', html, flags=re.IGNORECASE):
    noscript_count += 1
    print(f'Match {noscript_count}: {ns.group()[:200]}')
print(f'Total noscript: {noscript_count}')

# 检查是否有多个包含相同 class 名称的 div 区块
print('\n=== 检查重复 class 的 div ===')
div_classes = {}
for div in re.finditer(r'<div[^>]*class\s*=\s*"([^"]+)"', html, flags=re.IGNORECASE):
    cls = div.group(1)
    div_classes[cls] = div_classes.get(cls, 0) + 1
for cls, cnt in sorted(div_classes.items(), key=lambda x: -x[1]):
    if cnt > 1:
        print(f'  {cnt}x: {cls}')

# 检查 HTML 中的 <body 内是否有重复内容
print('\n=== BODY 中的 div 结构 ===')
body_match = re.search(r'<body[^>]*>([\s\S]*?)</body>', html, flags=re.IGNORECASE)
if body_match:
    body_text = body_match.group(1)
    # 找出所有 div 的开始
    divs = [(m.start(), m.group()) for m in re.finditer(r'<div[^>]*>', body_text, flags=re.IGNORECASE)]
    print(f'total divs in body: {len(divs)}')
    for pos, d in divs:
        cls_match = re.search(r'class\s*=\s*"([^"]+)"', d, flags=re.IGNORECASE)
        cls = cls_match.group(1) if cls_match else ''
        print(f'  pos {pos}: {d[:100]} | class={cls}')

# 检查是否存在包含"通知公告"文字的两个不同区域
print('\n=== "通知公告" 出现位置 ===')
text_locs = [(m.start(), m.end()) for m in re.finditer(r'通知公告', html)]
print(f'"通知公告" count: {len(text_locs)}, positions: {text_locs}')

# 检查 iframe 注入后的实际内容
def _sanitize_html(html, max_bytes=200*1024):
    if not html:
        return ""
    if len(html) > max_bytes:
        html = html[:max_bytes]
    html = re.sub(r"<script[\s>].*?</script>", "", html, flags=re.IGNORECASE | re.DOTALL)
    html = re.sub(r"<script[\s>].*?>", "", html, flags=re.IGNORECASE)
    html = re.sub(r"</script>", "", html, flags=re.IGNORECASE)
    html = re.sub(r"<iframe[\s>].*?</iframe>", "", html, flags=re.IGNORECASE | re.DOTALL)
    html = re.sub(r"<iframe[\s>].*?>", "", html, flags=re.IGNORECASE)
    html = re.sub(r"</iframe>", "", html, flags=re.IGNORECASE)
    html = re.sub(r"<embed[\s>].*?</embed>", "", html, flags=re.IGNORECASE | re.DOTALL)
    html = re.sub(r"<embed[\s>].*?>", "", html, flags=re.IGNORECASE)
    html = re.sub(r"</embed>", "", html, flags=re.IGNORECASE)
    html = re.sub(r"<object[\s>].*?</object>", "", html, flags=re.IGNORECASE | re.DOTALL)
    html = re.sub(r"<object[\s>].*?>", "", html, flags=re.IGNORECASE)
    html = re.sub(r"</object>", "", html, flags=re.IGNORECASE)
    html = re.sub(r"\son[a-z]+\s*=\s*\"[^\"]*\"", "", html, flags=re.IGNORECASE)
    html = re.sub(r"\son[a-z]+\s*=\s*'[^']*'", "", html, flags=re.IGNORECASE)
    return html

clean = _sanitize_html(html)
print(f'\nAfter sanitize: {len(clean)} chars')

# 关键：检查 clean 中是否有两个几乎一样的大区块
# 方法：查找出现多次的长字符串（100+ chars）
def find_repeated_blocks(text, min_len=100, min_count=2):
    """找出重复出现的长字符串区块。"""
    results = []
    # 使用滑窗法
    seen = {}
    for i in range(0, len(text) - min_len, 10):
        substr = text[i:i+min_len]
        if substr in seen:
            # 检查是否已经记录
            key = text[seen[substr]:seen[substr]+200]
            if not any(r[1] == key for r in results):
                results.append((seen[substr], text[seen[substr]:seen[substr]+200]))
        else:
            seen[substr] = i
    return results

repeated = find_repeated_blocks(clean, 150, 2)
print(f'\nRepeated 150+ char blocks: {len(repeated)}')
for pos, content in repeated[:5]:
    print(f'  pos {pos}: {content[:150]}')

# 另一种方法：检查 lmy_main 相关的 div 是否有两个一样的结构
print('\n=== lmy_main 相关元素 ===')
lmy_positions = [(m.start(), m.group()) for m in re.finditer(r'<div[^>]*class\s*=\s*"[^"]*lmy_main[^"]*"[^>]*>', clean, flags=re.IGNORECASE)]
for pos, tag in lmy_positions:
    print(f'  {pos}: {tag}')

# 检查 page-con 相关元素
print('\n=== page-con 相关元素 ===')
pc_positions = [(m.start(), m.group()) for m in re.finditer(r'<div[^>]*class\s*=\s*"[^"]*page-con[^"]*"[^>]*>', clean, flags=re.IGNORECASE)]
for pos, tag in pc_positions:
    print(f'  {pos}: {tag}')

# 检查 main 相关元素
print('\n=== main 相关元素 ===')
main_positions = [(m.start(), m.group()) for m in re.finditer(r'<div[^>]*class\s*=\s*"[^"]*\bmain\b[^"]*"[^>]*>', clean, flags=re.IGNORECASE)]
for pos, tag in main_positions:
    print(f'  {pos}: {tag}')

# 直接打印 clean html 前后 1000 chars
print('\n=== 预览 clean html 的关键部分 ===')
# 打印 body 开始部分
body_idx = clean.lower().find('<body')
if body_idx >= 0:
    print(f'body start at {body_idx}')
    print(clean[body_idx:body_idx + 1500])

# 结尾部分
print('\n=== 结尾部分 ===')
print(clean[-1000:])
