"""在应用启动环境下测试渲染引擎。"""
import sys
import json

print("=" * 60)
print("测试 1: 直接测试 requests 库")
print("=" * 60)

url = "https://www.miit.gov.cn/jgsj/xgj/APPqhyhqyzxzzxd/tzgg/index.html"

try:
    import requests
    r = requests.get(
        url,
        headers={
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        },
        timeout=30,
        allow_redirects=True,
    )
    print(f"  Status: {r.status_code}")
    print(f"  Encoding: {r.encoding}")
    print(f"  Text[:300]: {r.text[:300]!r}")
    print(f"  Text length: {len(r.text)}")
except Exception as e:
    print(f"  Error: {e}")

print()
print("=" * 60)
print("测试 2: 使用 SmartPageRenderer 渲染")
print("=" * 60)

try:
    from core.spider_core.page_renderer import SmartPageRenderer
    print("  SmartPageRenderer 导入成功")
    renderer = SmartPageRenderer()
    print("  SmartPageRenderer 实例化成功")

    # 不使用 JS 渲染
    print("\n  --- render_js=False ---")
    page = renderer.render(url, render_js=False, timeout=30.0, robot_check=False, risk_check=False)
    print(f"  status_code: {page.status_code}")
    print(f"  final_url: {page.final_url}")
    print(f"  error: {page.error}")
    print(f"  html length: {len(page.html or '')}")
    print(f"  title: {page.title}")
    print(f"  links: {len(page.links)}")
    print(f"  elapsed_ms: {page.elapsed_ms}")

    # 使用 JS 渲染（需要 Playwright）
    print("\n  --- render_js=True ---")
    try:
        page2 = renderer.render(url, render_js=True, timeout=30.0, robot_check=False, risk_check=False)
        print(f"  status_code: {page2.status_code}")
        print(f"  error: {page2.error}")
        print(f"  html length: {len(page2.html or '')}")
    except Exception as e:
        print(f"  Error with render_js=True: {e}")

except Exception as e:
    print(f"  Error: {e}")
    import traceback
    traceback.print_exc()

print()
print("=" * 60)
print("测试 3: 检查 SDK 内部组件")
print("=" * 60)

try:
    from core.spider_core.sdk import SpiderSDK
    sdk = SpiderSDK()
    print(f"  SDK UA: {sdk._ua.next()}")
    print(f"  SDK Proxy: {sdk._proxy.next()}")

    print("\n  --- 测试 _http_get ---")
    from core.spider_core.sdk import CrawlResponse
    resp = CrawlResponse(url=url, final_url=url)
    ua = sdk._ua.next()
    final_headers = {"User-Agent": ua}
    proxy = sdk._proxy.next()
    try:
        sdk._http_get(
            url,
            params=None,
            headers=final_headers,
            proxy=proxy,
            timeout=30,
            resp=resp,
        )
        print(f"  status_code: {resp.status_code}")
        print(f"  error: {resp.error}")
        print(f"  text length: {len(resp.text or '')}")
        print(f"  text[:300]: {resp.text[:300]!r}")
    except Exception as e:
        print(f"  _http_get 错误: {e}")
        import traceback
        traceback.print_exc()
except Exception as e:
    print(f"  SDK 测试失败: {e}")
    import traceback
    traceback.print_exc()

print()
print("=" * 60)
print("完成")
print("=" * 60)
