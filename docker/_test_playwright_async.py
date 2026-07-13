"""在容器内模拟 FastAPI async 上下文，测试 Playwright 渲染。"""
import asyncio
import sys
sys.path.insert(0, "/app")

test_url = "https://www.example.com"

async def test_render_in_async_context():
    """模拟 FastAPI async route 中的调用"""
    print("=" * 60)
    print("Test 1: 直接在 async 函数中调用 renderer.render(render_js=True)")
    print("=" * 60)

    from core.spider_core.page_renderer import SmartPageRenderer
    renderer = SmartPageRenderer()

    # 方式 1: 直接在 async 函数中同步调用（模拟修复前的问题）
    print("\n  [方式1] 直接同步调用...")
    try:
        page = renderer.render(test_url, render_js=True, timeout=30, robot_check=False, risk_check=False)
        print(f"  ✅ 成功！status={page.status_code}, html_len={len(page.html or '')}, error={page.error}")
    except Exception as e:
        print(f"  ❌ 失败: {e}")

    # 方式 2: 使用 loop.run_in_executor（API 层采用的方式）
    print("\n" + "=" * 60)
    print("Test 2: 使用 loop.run_in_executor（API 层采用的方式）")
    print("=" * 60)

    loop = asyncio.get_event_loop()
    try:
        page = await loop.run_in_executor(
            None,
            lambda: renderer.render(test_url, render_js=True, timeout=30, robot_check=False, risk_check=False)
        )
        print(f"  ✅ 成功！status={page.status_code}, html_len={len(page.html or '')}, error={page.error}")
    except Exception as e:
        print(f"  ❌ 失败: {e}")

    # 方式 3: render_js=False（走 HTTP requests 路径，不需要 Playwright）
    print("\n" + "=" * 60)
    print("Test 3: render_js=False (requests HTTP 路径)")
    print("=" * 60)

    try:
        page = renderer.render(test_url, render_js=False, timeout=30, robot_check=False, risk_check=False)
        print(f"  ✅ 成功！status={page.status_code}, html_len={len(page.html or '')}, error={page.error}")
    except Exception as e:
        print(f"  ❌ 失败: {e}")

    print("\n" + "=" * 60)
    print("All tests completed")
    print("=" * 60)

if __name__ == "__main__":
    asyncio.run(test_render_in_async_context())
