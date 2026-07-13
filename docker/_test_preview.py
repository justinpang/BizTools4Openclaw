"""测试预览渲染 API。"""
import urllib.request
import json
import sys

url = "https://www.miit.gov.cn/jgsj/xgj/APPqhyhqyzxzzxd/tzgg/index.html"

# Step 1: 先直接测试 requests 库
print("=" * 60)
print("[1] 测试直接 HTTP 请求")
print("=" * 60)
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
    print(f"  Final URL: {r.url}")
    print(f"  Encoding: {r.encoding}")
    print(f"  Content length: {len(r.content)} bytes")
    print(f"  Text length: {len(r.text)} chars")
    print(f"  Content preview: {r.text[:200]!r}")
except Exception as e:
    print(f"  Error: {e}")

# Step 2: 测试通过应用服务器的 API
print()
print("=" * 60)
print("[2] 测试 /api/admin/crawl/preview/render API")
print("=" * 60)

# 需要先登录获取 session cookie
# 先检查是否有可用的 cookie
try:
    # 先登录
    login_resp = urllib.request.urlopen("http://localhost:8000/admin/")
    cookies = login_resp.headers.get("Set-Cookie", "")
    print(f"  Cookies: {cookies[:100]}")
    if not cookies or "admin_session" not in cookies:
        print("  未登录，尝试用 admin/admin123 登录...")
        import urllib.parse
        login_data = urllib.parse.urlencode({
            "username": "admin",
            "password": "admin123",
        }).encode("utf-8")
        req = urllib.request.Request(
            "http://localhost:8000/admin/login",
            data=login_data,
            method="POST",
            headers={"Content-Type": "application/x-www-form-urlencoded"},
        )
        try:
            login_resp2 = urllib.request.urlopen(req)
            cookies = login_resp2.headers.get("Set-Cookie", "")
            print(f"  登录后 Cookies: {cookies[:200]}")
        except urllib.error.HTTPError as e:
            print(f"  登录失败: {e.code} {e.reason}")
            content = e.read().decode("utf-8", errors="ignore")
            print(f"  登录响应: {content[:200]}")
except Exception as e:
    print(f"  Cookie 失败: {e}")

# 调用预览 API
if cookies:
    session_cookie = cookies.split(";")[0]
    test_cases = [
        (url, False),  # 不使用 JS 渲染
        (url, True),   # 使用 JS 渲染
    ]
    for test_url, use_render in test_cases:
        print(f"\n  --- 测试: {test_url} (render_js={use_render}) ---")
        body = json.dumps({"url": test_url, "render_js": use_render}).encode("utf-8")
        req = urllib.request.Request(
            "http://localhost:8000/api/admin/crawl/preview/render",
            data=body,
            method="POST",
            headers={
                "Content-Type": "application/json",
                "Cookie": session_cookie,
            },
        )
        try:
            resp = urllib.request.urlopen(req, timeout=60)
            data = json.loads(resp.read().decode("utf-8"))
            print(f"  Response code: {resp.status}")
            print(f"  API code: {data.get('code')}")
            print(f"  API msg: {data.get('msg')}")
            if data.get("data"):
                d = data["data"]
                print(f"  final_url: {d.get('final_url')}")
                print(f"  html_preview length: {len(d.get('html_preview', '') or '')}")
                print(f"  clickable_elements: {len(d.get('clickable_elements') or [])}")
                print(f"  elapsed_ms: {d.get('elapsed_ms')}")
                print(f"  error field: {d.get('error')}")
                if d.get('html_preview'):
                    preview = d['html_preview']
                    print(f"  html_preview[:200]: {preview[:200]!r}")
            else:
                print(f"  data: {data.get('data')}")
        except urllib.error.HTTPError as e:
            print(f"  HTTP Error: {e.code} {e.reason}")
            content = e.read().decode("utf-8", errors="ignore")
            print(f"  Body: {content[:300]}")
        except Exception as e:
            print(f"  Error: {e}")
else:
    print("  跳过 API 测试（无 session cookie）")

print()
print("=" * 60)
print("测试完成")
print("=" * 60)
