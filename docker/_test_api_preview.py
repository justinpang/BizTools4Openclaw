"""测试 Web 管理员预览渲染 API 端点"""
import json
import sys
import urllib.request

sys.path.insert(0, "/app")

results = []
print("=" * 60)
print("测试: 模拟浏览器调用预览渲染 (render_js=True)")
print("=" * 60)

try:
    body = json.dumps({"url": "https://www.example.com", "render_js": True}).encode("utf-8")
    req = urllib.request.Request(
        "http://127.0.0.1:8000/api/admin/crawl/preview/render",
        data=body,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    resp = urllib.request.urlopen(req, timeout=60)
    data = json.loads(resp.read().decode("utf-8"))
    print(f"  HTTP 状态: {resp.status}")
    print(f"  响应代码: {data.get('code')}")
    if data.get("data"):
        d = data["data"]
        print(f"  final_url: {d.get('final_url')}")
        print(f"  html length: {len(d.get('html_preview', ''))}")
        print(f"  可点击元素: {len(d.get('clickable_elements', []))}")
        print(f"  错误: {d.get('error')}")
        html_len = len(d.get('html_preview', ''))
        if html_len > 100:
            print(f"\n  ✅ API 调用成功！HTML 长度 {html_len}")
            results.append(True)
        else:
            print(f"\n  ⚠️ HTML 长度不足")
            results.append(False)
    else:
        print(f"  msg: {data.get('msg')}")
        results.append(False)
except urllib.error.HTTPError as e:
    print(f"  ❌ HTTP 错误: {e.code}")
    results.append(False)
except Exception as e:
    print(f"  ❌ 其他错误: {e}")
    results.append(False)

print("\n" + "=" * 60)
print("测试: 预览渲染 (render_js=False)")
print("=" * 60)

try:
    body = json.dumps({"url": "https://www.example.com", "render_js": False}).encode("utf-8")
    req = urllib.request.Request(
        "http://127.0.0.1:8000/api/admin/crawl/preview/render",
        data=body,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    resp = urllib.request.urlopen(req, timeout=60)
    data = json.loads(resp.read().decode("utf-8"))
    print(f"  HTTP 状态: {resp.status}")
    print(f"  响应代码: {data.get('code')}")
    if data.get("data"):
        d = data["data"]
        print(f"  final_url: {d.get('final_url')}")
        print(f"  html length: {len(d.get('html_preview', ''))}")
        print(f"  错误: {d.get('error')}")
        html_len = len(d.get('html_preview', ''))
        if html_len > 100:
            print(f"\n  ✅ API 调用成功！HTML 长度 {html_len}")
            results.append(True)
        else:
            print(f"\n  ⚠️ HTML 长度不足")
            results.append(False)
    else:
        print(f"  msg: {data.get('msg')}")
        results.append(False)
except urllib.error.HTTPError as e:
    print(f"  ❌ HTTP 错误: {e.code}")
    results.append(False)
except Exception as e:
    print(f"  ❌ 其他错误: {e}")
    results.append(False)

print("\n" + "=" * 60)
print(f"最终结果: {sum(results)}/{len(results)} 个通过")
print("=" * 60)
