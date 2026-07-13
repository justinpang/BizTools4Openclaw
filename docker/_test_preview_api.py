"""测试 /api/admin/crawl/preview/render 端点"""
import urllib.request
import json
import sys

sys.path.insert(0, "/app")

base_url = "http://localhost:8000"
test_url = "https://www.example.com"

print("=" * 60)
print("Test: POST /api/admin/crawl/preview/render (render_js=True)")
print("=" * 60)

body = json.dumps({"url": test_url, "render_js": True}).encode("utf-8")
req = urllib.request.Request(
    base_url + "/api/admin/crawl/preview/render",
    data=body,
    headers={"Content-Type": "application/json"},
    method="POST",
)
try:
    resp = urllib.request.urlopen(req, timeout=60)
    data = json.loads(resp.read().decode("utf-8"))
    print(f"  API response: code={data.get('code')}, msg={data.get('msg')}")
    if data.get("data"):
        d = data["data"]
        print(f"  final_url: {d.get('final_url')}")
        print(f"  html_preview length: {len(d.get('html_preview', ''))}")
        print(f"  clickable_elements: {len(d.get('clickable_elements', []))}")
        print(f"  elapsed_ms: {d.get('elapsed_ms')}")
        print(f"  error: {d.get('error')}")
    print("\n  ✅ API 调用成功！")
except urllib.error.HTTPError as e:
    print(f"  ❌ HTTP Error: {e.code} {e.reason}")
    print(f"  Body: {e.read().decode('utf-8', errors='ignore')[:500]}")
except Exception as e:
    print(f"  ❌ Error: {e}")

print("\n" + "=" * 60)
print("Test: POST /api/admin/crawl/preview/render (render_js=False)")
print("=" * 60)

body = json.dumps({"url": test_url, "render_js": False}).encode("utf-8")
req = urllib.request.Request(
    base_url + "/api/admin/crawl/preview/render",
    data=body,
    headers={"Content-Type": "application/json"},
    method="POST",
)
try:
    resp = urllib.request.urlopen(req, timeout=60)
    data = json.loads(resp.read().decode("utf-8"))
    print(f"  API response: code={data.get('code')}, msg={data.get('msg')}")
    if data.get("data"):
        d = data["data"]
        print(f"  final_url: {d.get('final_url')}")
        print(f"  html_preview length: {len(d.get('html_preview', ''))}")
        print(f"  clickable_elements: {len(d.get('clickable_elements', []))}")
        print(f"  elapsed_ms: {d.get('elapsed_ms')}")
        print(f"  error: {d.get('error')}")
    print("\n  ✅ API 调用成功！")
except urllib.error.HTTPError as e:
    print(f"  ❌ HTTP Error: {e.code} {e.reason}")
    print(f"  Body: {e.read().decode('utf-8', errors='ignore')[:500]}")
except Exception as e:
    print(f"  ❌ Error: {e}")

print("\n" + "=" * 60)
print("所有测试完成！")
print("=" * 60)
