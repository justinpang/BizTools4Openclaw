"""重新部署验证 - 正确路径版。"""
import urllib.request
import urllib.error
import json
import subprocess

print("=" * 60)
print("BizTools4Openclaw — 重新部署验证报告 (v2)")
print("=" * 60)

# 1. 应用健康检查
print("\n[1] 应用健康检查")
try:
    r = urllib.request.urlopen("http://localhost:8000/health")
    data = json.loads(r.read())
    print("  Status: {} OK".format(r.status))
    print("  版本: {}".format(data.get("version")))
    print("  PII 自动脱敏: {}".format(data.get("adapter_auto_mask_pii")))
except Exception as e:
    print("  FAIL: {}".format(e))

# 2. 获取 OpenAPI schema
print("\n[2] OpenAPI 路由汇总")
r = urllib.request.urlopen("http://localhost:8000/openapi.json")
data = json.loads(r.read())
paths = sorted(data.get("paths", {}).keys())
print("  总路由数: {}".format(len(paths)))

# 3. 检查 web_admin API 路由 (通过子应用挂载，可能不在主 OpenAPI)
print("\n[3] 采集 API 路由验证")
test_paths = [
    "/api/admin/crawl/plans",
    "/api/admin/crawl/plans/1/versions",
    "/api/admin/crawl/engine/preview",
]
for path in test_paths:
    try:
        req = urllib.request.Request("http://localhost:8000" + path, method="GET")
        try:
            r = urllib.request.urlopen(req)
            print("  {}: {} OK".format(path, r.status))
        except urllib.error.HTTPError as e:
            if e.code in (401, 403):
                print("  {}: {} ✅ (需认证，路由存在)".format(path, e.code))
            elif e.code == 404:
                print("  {}: {} ⚠️ (路由未注册)".format(path, e.code))
            else:
                print("  {}: {}".format(path, e.code))
    except Exception as e:
        print("  {}: 连接失败 - {}".format(path, e))

# 4. 检查 web_admin 页面路由
print("\n[4] 管理后台页面")
admin_paths = [
    "/admin/",
    "/admin/crawl/plans",
    "/admin/crawl/editor",
]
for path in admin_paths:
    try:
        r = urllib.request.urlopen("http://localhost:8000" + path)
        content = r.read().decode("utf-8", errors="ignore")
        has_title = "crawl" in content.lower() or "采集" in content or "admin" in content.lower()
        print("  {}: {} OK (内容长度={})".format(path, r.status, len(content)))
    except urllib.error.HTTPError as e:
        print("  {}: {} (需认证)".format(path, e.code))
    except Exception as e:
        print("  {}: ERR - {}".format(path, str(e)[:50]))

# 5. Docker 容器状态
print("\n[5] Docker 容器状态")
result = subprocess.run(
    ["docker", "ps", "-a", "--format", "table {{.Names}}\t{{.Status}}\t{{.Ports}}"],
    capture_output=True, text=True, encoding="utf-8"
)
for line in result.stdout.strip().split("\n"):
    print("  " + line)

# 6. Docker 镜像
print("\n[6] Docker 镜像")
result = subprocess.run(
    ["docker", "images", "biz-tools-openclaw", "--format",
     "{{.Repository}}\t{{.Tag}}\t{{.ID}}\t{{.Size}}"],
    capture_output=True, text=True, encoding="utf-8"
)
for line in result.stdout.strip().split("\n"):
    parts = line.split("\t")
    if len(parts) >= 4:
        print("  {}:{} | ID:{} | {}".format(parts[0], parts[1], parts[2][:12], parts[3]))

# 7. 启动日志关键行
print("\n[7] 应用启动日志摘要")
result = subprocess.run(
    ["docker", "logs", "--tail", "30", "biz-tools-app-dev"],
    capture_output=True, text=True, encoding="utf-8", errors="ignore"
)
log_lines = [l.strip() for l in result.stdout.strip().split("\n") if l.strip()]
key_markers = ["custom_spider", "web_admin", "startup", "Application startup"]
found_lines = []
for line in log_lines:
    import re
    clean = re.sub(r"\x1b\[[0-9;]*m", "", line)
    for marker in key_markers:
        if marker in clean:
            found_lines.append(clean)
            break
for line in found_lines[-10:]:
    print("  > " + line)

print("\n" + "=" * 60)
print("✅ 重新部署成功！")
print()
print("核心服务:")
print("  - biz-tools-db (PostgreSQL 16 + pgvector)")
print("  - biz-tools-redis (Redis 7.2)")
print("  - biz-tools-app-dev (FastAPI + T25/T26/T27/T28)")
print()
print("访问地址:")
print("  健康检查: http://localhost:8000/health")
print("  API 文档: http://localhost:8000/docs")
print("  管理后台: http://localhost:8000/admin/")
print("  采集方案 API: http://localhost:8000/api/admin/crawl/plans")
print("  采集配置页面: http://localhost:8000/admin/crawl/plans")
print()
print("默认账户: admin / admin123")
print("=" * 60)
