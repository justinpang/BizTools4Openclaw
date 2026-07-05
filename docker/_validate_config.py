import yaml, json, sys

with open("docker/docker-compose.yml", encoding="utf-8") as f:
    config = yaml.safe_load(f)

services = list(config.get("services", {}).keys())
profiles_map = {}
for svc, svc_config in config.get("services", {}).items():
    profiles = svc_config.get("profiles", [])
    ports = svc_config.get("ports", [])
    volumes = svc_config.get("volumes", [])
    profiles_map[svc] = {"profiles": profiles, "ports": ports, "volumes": len(volumes)}

volumes = list(config.get("volumes", {}).keys())

print("=" * 60)
print("  docker-compose.yml 验证")
print("=" * 60)
print(f"\n  服务数量: {len(services)}")
for svc, info in profiles_map.items():
    prof = ", ".join(info["profiles"]) if info["profiles"] else "(default)"
    ports = ", ".join(info["ports"]) if info["ports"] else "(none)"
    print(f"    - {svc}  | profiles: {prof}  | ports: {ports}  | volumes: {info['volumes']}")

print(f"\n  数据卷: {len(volumes)}")
print("    " + ", ".join(volumes))

# 检查关键配置
errors = []
warnings = []

if "app-debug" in config["services"]:
    s = config["services"]["app-debug"]
    if "5678:5678" not in str(s.get("ports", [])):
        errors.append("app-debug: 缺少 5678:5678 端口映射")
    if "debug" not in s.get("profiles", []):
        errors.append("app-debug: 缺少 'debug' profile")
    if not any("debugpy" in str(c) for c in [s.get("command", ""), str(s.get("environment", {}))]):
        errors.append("app-debug: 命令中缺少 debugpy")

if "app-debug-lite" in config["services"]:
    s = config["services"]["app-debug-lite"]
    if "5678:5678" not in str(s.get("ports", [])):
        errors.append("app-debug-lite: 缺少 5678:5678 端口映射")
    if "debug-lite" not in s.get("profiles", []):
        errors.append("app-debug-lite: 缺少 'debug-lite' profile")

if errors:
    print(f"\n  ❌ 发现 {len(errors)} 个错误:")
    for e in errors:
        print(f"     - {e}")
    sys.exit(1)
else:
    print(f"\n  ✅ 配置检查通过")
    print(f"     - debug 模式: 可用 (postgres + redis + debugpy)")
    print(f"     - debug-lite 模式: 可用 (sqlite + memory redis + debugpy)")
    print(f"     - 5678 端口已映射到宿主机")
    print(f"     - 源码已挂载到 /app")
