"""A2-2: 精细 JS 脱敏检查"""
import re
js = open("web_admin/static/js/admin.js", encoding="utf-8").read()
lines = js.split("\n")

print("=" * 80)
print("A2-2: JS 数据渲染脱敏检查")
print("=" * 80)

keywords = ["phone", "email", "mobile", "contact", "wechat"]
suspicious = []

for i, line in enumerate(lines):
    lower = line.lower()
    for kw in keywords:
        if kw in lower:
            is_render = any(tok in line for tok in [
                "innerHTML", "textContent", ".text", "</td>", "cell",
                "appendChild", "createElement"
            ]) or (("' + " in line or '"+' in line) and "td" in lower)
            has_mask = "mask" in lower or "****" in line or "hide" in lower or "***" in line
            if is_render and not has_mask:
                suspicious.append((i+1, line.strip()[:120]))
                break

print(f"发现 {len(suspicious)} 处可疑渲染点:")
for ln, txt in suspicious[:30]:
    print(f"  line {ln}: {txt}")

# 另外: 查找明文显示 lead.phone 或 lead.email 的情况
print("\n" + "=" * 80)
print("A2-3: 检查 lead.xxx / item.xxx / row.xxx 形式的字段访问")
print("=" * 80)

access_points = []
for i, line in enumerate(lines):
    # 找 lead.phone / row.email / item.contact 等
    matches = re.findall(r"(lead|row|item|data)\.(phone|email|mobile|contact|wechat)", line, re.IGNORECASE)
    if matches:
        lower = line.lower()
        has_mask = "mask" in lower or "****" in line or "***" in line
        if not has_mask and len(line.strip()) > 20:
            access_points.append((i+1, line.strip()[:120]))

print(f"发现 {len(access_points)} 处字段访问:")
for ln, txt in access_points[:30]:
    print(f"  line {ln}: {txt}")
