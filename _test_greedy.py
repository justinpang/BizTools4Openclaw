import re

test = '''start
<script src="a.js"></script>
<div>重要内容 1</div>
<script src="b.js"></script>
<div>重要内容 2</div>
<script>alert('hi')</script>
end
'''

# 1. 当前实现：DOTALL + .* (贪婪)
result1 = re.sub(r'<script[\s>].*?</script>', '', test, flags=re.IGNORECASE | re.DOTALL)
print('=== 1. DOTALL + .* (贪婪 - 当前实现) ===')
print(result1)
print('matches:', len(list(re.finditer(r'<script[\s>].*?</script>', test, flags=re.IGNORECASE | re.DOTALL))))

# 2. 正确：用 .*? 非贪婪
result2 = re.sub(r'<script\b[^>]*>[\s\S]*?</script>', '', test, flags=re.IGNORECASE)
print('=== 2. lazy [\s\S]*? ===')
print(result2)
print('matches:', len(list(re.finditer(r'<script\b[^>]*>[\s\S]*?</script>', test, flags=re.IGNORECASE))))

# 3. 对实际 miit html 的影响
with open(r'c:\projects\BizTools4Openclaw\_raw_html2.html', encoding='utf-8') as f:
    html = f.read()

print('\n=== 对 miit html 的影响 ===')
print(f'原始长度: {len(html)}')
greedy = re.sub(r'<script[\s>].*?</script>', '', html, flags=re.IGNORECASE | re.DOTALL)
print(f'贪婪清理后: {len(greedy)}')
lazy = re.sub(r'<script\b[^>]*>[\s\S]*?</script>', '', html, flags=re.IGNORECASE)
print(f'非贪婪清理后: {len(lazy)}')

# 关键：检查贪婪是否吞掉了中间的 HTML
# 检查 "通知公告" 在贪婪和非贪婪清理后的出现次数
def count_occurrences(text, keyword):
    return len(re.findall(keyword, text))

print(f'\n"通知公告" 在原始: {count_occurrences(html, "通知公告")}')
print(f'"通知公告" 在贪婪清理后: {count_occurrences(greedy, "通知公告")}')
print(f'"通知公告" 在非贪婪清理后: {count_occurrences(lazy, "通知公告")}')

# 检查 div class 数量
def count_divs_with_class(text, cls):
    return len(re.findall(rf'<div[^>]*class\s*=\s*"[^"]*{re.escape(cls)}[^"]*"', text, flags=re.IGNORECASE))

for cls in ['page-con', 'main', 'lmy_main', 'lmy_main_rb', 'wrapper']:
    print(f'div class="{cls}" 原始: {count_divs_with_class(html, cls)}, 贪婪后: {count_divs_with_class(greedy, cls)}, 非贪婪后: {count_divs_with_class(lazy, cls)}')
