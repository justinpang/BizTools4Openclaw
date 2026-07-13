import urllib.request, urllib.parse, json

company = '阿里云计算有限公司'
headers = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0 Safari/537.36',
    'Accept': 'text/html,application/xhtml+xml,application/json',
    'Accept-Language': 'zh-CN,zh;q=0.9',
}

# 测试 1: 搜索页，提取 pageData
url1 = 'https://aiqicha.baidu.com/s?q=' + urllib.parse.quote(company) + '&t=0'
print('=== Test 1: 搜索页 HTML ===')
try:
    req = urllib.request.Request(url1, headers=headers)
    resp = urllib.request.urlopen(req, timeout=15)
    html = resp.read().decode('utf-8', errors='replace')
    print('Status:', resp.status, 'Length:', len(html))

    # 查找 pageData
    import re
    m = re.search(r'window\.pageData\s*=\s*(\{[\s\S]*?\n\s*\})\s*;\s*</script>', html)
    if m:
        try:
            data = json.loads(m.group(1))
            print('pageData keys:', list(data.keys())[:20])
            # 找 search 相关数据
            for k, v in data.items():
                if isinstance(v, (dict, list)) and v:
                    print(f'  {k}: {type(v).__name__}')
        except Exception as e:
            print('pageData 解析失败:', e)
            print('片段:', m.group(1)[:200])
    else:
        # 尝试其他方式
        m2 = re.search(r'pageData\s*=\s*(\{[^{}]*\{[^}]*\}[^}]*\})', html)
        if m2:
            print('找到简化 pageData:', m2.group(1)[:300])
        else:
            print('未找到 pageData')

except Exception as e:
    print('Error:', e)

print()

# 测试 2: XHR API 端点（爱企查常见的）
print('=== Test 2: XHR API 测试 ===')
api_list = [
    'https://aiqicha.baidu.com/searchAjax/searchAjax?kw=' + urllib.parse.quote(company),
    'https://aiqicha.baidu.com/search/searchAjax?kw=' + urllib.parse.quote(company),
    'https://aiqicha.baidu.com/search/getSearchResultAjax?kw=' + urllib.parse.quote(company) + '&p=1',
    'https://aiqicha.baidu.com/xin/searchAjax?kw=' + urllib.parse.quote(company),
    'https://aiqicha.baidu.com/search/companysearch?kw=' + urllib.parse.quote(company),
    'https://aiqicha.baidu.com/detailsAjax/basicDetailsAjax?pid=' + urllib.parse.quote(company),
]

api_headers = headers.copy()
api_headers['X-Requested-With'] = 'XMLHttpRequest'
api_headers['Referer'] = 'https://aiqicha.baidu.com/'
api_headers['Accept'] = 'application/json,text/javascript'

for api_url in api_list:
    try:
        req = urllib.request.Request(api_url, headers=api_headers)
        resp = urllib.request.urlopen(req, timeout=15)
        content = resp.read().decode('utf-8', errors='replace')
        code = resp.status
        ct = resp.headers.get('Content-Type', '')
        path = api_url.replace('https://aiqicha.baidu.com/', '')
        print(f'  [{code}] {path}')
        print(f'       Content-Type: {ct}, Length: {len(content)}')

        # 尝试解析 JSON
        try:
            json_data = json.loads(content)
            print(f'       JSON top-level keys: {list(json_data.keys())[:10]}')
            if 'data' in json_data:
                d = json_data['data']
                if isinstance(d, dict):
                    print(f'       data keys: {list(d.keys())[:15]}')
                elif isinstance(d, list):
                    print(f'       data is list, length={len(d)}')
                    if d and isinstance(d[0], dict):
                        print(f'       first item keys: {list(d[0].keys())[:15]}')
        except:
            if len(content) < 500:
                print(f'       Raw: {content[:200]}')
            else:
                print(f'       (not JSON, length={len(content)})')
        print()
    except Exception as e:
        path = api_url.replace('https://aiqicha.baidu.com/', '')
        print(f'  [ERR] {path}: {e}')
        print()
