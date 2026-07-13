import requests
from bs4 import BeautifulSoup

url = 'https://www.miit.gov.cn/jgsj/xgj/APPqhyhqyzxzzxd/tzgg/index.html'
r = requests.get(url, timeout=15, headers={'User-Agent': 'Mozilla/5.0 BizTools4Openclaw step-editor'})
html = r.text or ''
print('html length:', len(html))
print('status:', r.status_code)

# 检查 head/body 标签
lower = html.lower()
print('has <!doctype:', lower.find('<!doctype') >= 0)
print('has <html:', lower.find('<html') >= 0)
print('has </head>:', lower.find('</head>') >= 0)
print('has <body:', lower.find('<body') >= 0)

# list/table 计数
soup = BeautifulSoup(html, 'html.parser')
tags = soup.find_all(['ul', 'table', 'ol'])
print('number of ul/table/ol:', len(tags))
for i, t in enumerate(tags[:15]):
    text = t.get_text(' ', strip=True)[:100]
    cls = t.get('class', '')
    ids = t.get('id', '')
    print(f'  #{i} {t.name} class={cls} id={ids}: {text}')

# 检查是否有相同 class 的列表块多次出现
by_class = {}
for t in tags:
    c = ' '.join(t.get('class', []) if isinstance(t.get('class'), list) else [t.get('class', '')])
    key = f'{t.name}.{c}'
    by_class.setdefault(key, 0)
    by_class[key] += 1
print('\nBy class:')
for k, v in sorted(by_class.items(), key=lambda x: -x[1])[:10]:
    print(f'  {v}x: {k}')

# 现在检查 _sanitize_html
import re
max_bytes = 200 * 1024
html2 = html[:max_bytes] if len(html) > max_bytes else html
html2 = re.sub(r"<script[\s>].*?</script>", "", html2, flags=re.IGNORECASE | re.DOTALL)
html2 = re.sub(r"<script[\s>].*?>", "", html2, flags=re.IGNORECASE)
html2 = re.sub(r"</script>", "", html2, flags=re.IGNORECASE)
print('\nAfter sanitize, len:', len(html2))
soup2 = BeautifulSoup(html2, 'html.parser')
tags2 = soup2.find_all(['ul', 'table', 'ol'])
print('after sanitize ul/table/ol count:', len(tags2))

# 看看原始 HTML 的 body 内的 list/table 结构
# 提取 body 内的内容
body_match = re.search(r'<body[^>]*>(.*?)</body>', html, flags=re.IGNORECASE | re.DOTALL)
body_content = body_match.group(1) if body_match else html
soup3 = BeautifulSoup(body_content, 'html.parser')
tags3 = soup3.find_all(['ul', 'table', 'ol'])
print('body content ul/table/ol count:', len(tags3))

# 检查是否有"两张一样的表"
for i, t in enumerate(tags3[:15]):
    text = t.get_text(' ', strip=True)[:100]
    cls = ' '.join(t.get('class', []) if isinstance(t.get('class'), list) else [t.get('class', '')])
    ids = t.get('id', '')
    print(f'  #{i} {t.name} class={cls} id={ids}: {text}')

with open(r'c:\projects\BizTools4Openclaw\_raw_html2.html', 'w', encoding='utf-8') as f:
    f.write(html)
print('saved raw html')
