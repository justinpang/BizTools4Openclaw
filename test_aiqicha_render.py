import sys, json, urllib.parse

# 测试 SpiderSDK 渲染模式
from core.spider_core import SpiderSDK
spider_sdk = SpiderSDK()

company = '阿里云计算有限公司'
url = 'https://aiqicha.baidu.com/s?q=' + urllib.parse.quote(company) + '&t=0'
print('=== SpiderSDK render 模式测试 ===')
print('URL:', url)
print()

# 使用 render 模式
print('发起 render 渲染...')
try:
    resp = spider_sdk.get(url, render=True, render_js=True, render_timeout=20.0)
    print('Status:', resp.status_code if hasattr(resp, 'status_code') else 'n/a')
    print('Mode:', resp.mode)
    print('Length:', len(resp.text))
    print('Error:', resp.error)
    print()

    # 查看页面内容
    html = resp.text

    # 检查是否有企业信息
    keywords = ['电话', '邮箱', '地址', '法人', '注册资本', '成立日期', '统一社会信用代码', '经营范围']
    found = [k for k in keywords if k in html]
    print('检测到的关键字段:', found)
    print()

    # 提取 pageData
    import re
    # 尝试不同的 pageData 提取
    m = re.search(r'window\.pageData\s*=\s*(\{[\s\S]*?\})\s*;', html)
    if m:
        try:
            data = json.loads(m.group(1))
            print('=== pageData 结构 ===')
            for k in list(data.keys())[:30]:
                v = data[k]
                if isinstance(v, (dict, list)):
                    print(f'  {k}: {type(v).__name__}')
                else:
                    print(f'  {k}: {str(v)[:80]}')
        except:
            print('pageData 解析失败')
    else:
        print('未找到 window.pageData')

    print()

    # 查找企业卡片/详情链接
    # 查看详情页 URL
    m2 = re.search(r'/companydetails/detail/(\d+)', html)
    if m2:
        print('找到企业详情链接:', '/companydetails/detail/' + m2.group(1))
    else:
        print('未找到企业详情链接')

    # 查找企业名称匹配
    if company in html:
        print(f'✓ 企业名称 "{company}" 出现在页面中')
    else:
        # 尝试部分匹配
        partial = company[:4]
        if partial in html:
            print(f'部分名称 "{partial}" 出现')

    print()

    # 查看是否有 React root 内容
    if '公司信息' in html or '公司概况' in html or '工商信息' in html:
        print('✓ 页面包含企业信息')

    # 保存 HTML 以便手动检查
    with open('aiqicha_rendered.html', 'w', encoding='utf-8') as f:
        f.write(html)
    print(f'HTML 已保存到 aiqicha_rendered.html (大小: {len(html)} bytes)')

except Exception as e:
    print('Error:', e)
    import traceback
    traceback.print_exc()
