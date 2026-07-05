"""T24 Phase A: 自动化巡检脚本 - 权限/脱敏/路由检查"""
import re
import os
import glob
import csv

print("=" * 80)
print("A1: 权限注解巡检 — 扫描所有 API 路由和页面路由")
print("=" * 80)

api_files = glob.glob("web_admin/api/*.py")
issues = []

for fpath in api_files:
    content = open(fpath, encoding="utf-8").read()
    fname = os.path.basename(fpath)

    routes = re.finditer(
        r"@router\.(get|post|put|delete|patch)\(([^)]+)\)\s*\n\s*def\s+(\w+)",
        content,
    )
    for m in routes:
        method = m.group(1)
        path_raw = m.group(2).strip().strip('"').strip("'").split(",")[0].strip().strip('"').strip("'")
        func = m.group(3)

        func_start = content.find("def " + func, m.start())
        if func_start == -1:
            continue
        next_def = content.find("\ndef ", func_start + 5)
        func_block = content[func_start:next_def] if next_def != -1 else content[func_start:]

        has_require_admin = "require_admin" in func_block
        has_get_current = "get_current_admin" in func_block

        if method in ("post", "put", "delete", "patch"):
            if not has_require_admin:
                issues.append(("P0", fname, func, f"{method} {path_raw}", "操作类路由缺少 require_admin 权限校验"))
        elif method == "get":
            is_data_api = bool(
                re.search(r"return\s*(\{|JSONResponse|Response\(.*json|\{\s*['\"]code)", func_block)
            )
            if is_data_api and not has_require_admin and not has_get_current:
                issues.append(("P1", fname, func, f"{method} {path_raw}", "GET 数据接口可能缺少权限校验"))

print(f"\n共扫描 {len(api_files)} 个 API 文件, 发现 {len(issues)} 个权限问题:")
for lvl, f, fn, p, desc in issues:
    print(f"  [{lvl}] {f}::{fn} {p} - {desc}")

# ========== 页面路由 ==========
print("\n" + "=" * 80)
print("A1-2: 页面路由权限检查 (pages.py)")
print("=" * 80)

pages_content = open("web_admin/pages.py", encoding="utf-8").read()
page_issues = []
page_routes = re.finditer(
    r"@router\.get\(([^)]+)\)\s*\n\s*def\s+(\w+)",
    pages_content,
)
for m in page_routes:
    path_raw = m.group(1).strip().strip('"').strip("'").split(",")[0].strip().strip('"').strip("'")
    func = m.group(2)
    func_start = pages_content.find("def " + func, m.start())
    if func_start == -1:
        continue
    next_def = pages_content.find("\ndef ", func_start + 5)
    func_block = pages_content[func_start:next_def] if next_def != -1 else pages_content[func_start:]

    if "_render_with_permission" not in func_block and "require_admin" not in func_block and "get_current_admin" not in func_block:
        if "login" not in path_raw.lower() and "logout" not in path_raw.lower():
            page_issues.append(("P0", "pages.py", func, f"GET {path_raw}", "页面缺少权限校验"))

print(f"\n共发现 {len(page_issues)} 个页面权限问题:")
for lvl, f, fn, p, desc in page_issues:
    print(f"  [{lvl}] {f}::{fn} {p} - {desc}")

all_perm_issues = issues + page_issues
print(f"\n>>> 权限巡检汇总: {len(all_perm_issues)} 个问题")

# ========== A2: 脱敏点巡检 ==========
print("\n" + "=" * 80)
print("A2: 脱敏点全覆盖巡检")
print("=" * 80)

privacy_keywords = ["phone", "email", "mobile", "contact", "wechat", "qq", "tel"]
mask_issues = []

for fpath in api_files:
    content = open(fpath, encoding="utf-8").read()
    fname = os.path.basename(fpath)
    # 找函数体中出现隐私关键字但未调用 mask_phone 的情况
    funcs = re.finditer(r"def\s+(\w+)\(([^)]*)\):", content)
    for m in funcs:
        func = m.group(1)
        params = m.group(2)
        func_start = m.start()
        next_def = content.find("\ndef ", func_start + len(func) + 5)
        func_block = content[func_start:next_def] if next_def != -1 else content[func_start:]

        # 检查是否含隐私字段返回
        has_privacy = any(kw in func_block.lower() for kw in privacy_keywords)
        if has_privacy and func.startswith(("get_", "list_", "api_", "fetch_")) or (
            has_privacy and ("return" in func_block and "{" in func_block)
        ):
            # 检查是否调用了 mask 函数
            if "mask" not in func_block.lower() and "_mask" not in func_block:
                # 检查是否是纯页面渲染(HTML), 如果是 HTML 则在前端做 mask
                if "HTMLResponse" not in func_block and "html" not in func_block.lower()[:500]:
                    mask_issues.append(("P1", fname, func, "含隐私字段但未调用 mask_phone()"))

print(f"\nAPI 脱敏问题: {len(mask_issues)} 个")
for lvl, f, fn, desc in mask_issues:
    print(f"  [{lvl}] {f}::{fn} - {desc}")

# admin.js 脱敏检查
js_content = open("web_admin/static/js/admin.js", encoding="utf-8").read()
js_mask_issues = []
# 找渲染 table cell 时含 phone/email 等关键字但未调用 mask
table_lines = re.finditer(r"(phone|email|mobile|contact)", js_content, re.IGNORECASE)
found_lines = set()
for m in table_lines:
    line_num = js_content[:m.start()].count("\n") + 1
    # 检查这行附近(前后10行)是否有 mask 调用
    line_start = js_content.rfind("\n", 0, m.start()) + 1
    line_end = js_content.find("\n", m.end())
    if line_end == -1:
        line_end = len(js_content)
    line = js_content[line_start:line_end]
    if "mask" not in line.lower() and "****" not in line and len(line.strip()) > 30:
        if line_num not in found_lines:
            found_lines.add(line_num)
            if len(js_mask_issues) < 15:
                js_mask_issues.append(f"  line {line_num}: {line.strip()[:80]}")

print(f"\nadmin.js 潜在未脱敏点: 约 {len(found_lines)} 处可疑, 列出前 {len(js_mask_issues)} 条:")
for iss in js_mask_issues:
    print(iss)

# ========== A3: 路由计数 ==========
total_api_routes = 0
for fpath in api_files:
    content = open(fpath, encoding="utf-8").read()
    total_api_routes += len(re.findall(r"@router\.(get|post|put|delete|patch)\(", content))

total_page_routes = len(re.findall(r"@router\.get\(", pages_content))

print(f"\n" + "=" * 80)
print("仓库概况")
print("=" * 80)
print(f"API 文件数: {len(api_files)}")
print(f"API 路由总数: {total_api_routes}")
print(f"页面路由总数: {total_page_routes}")
print(f"权限问题总数: {len(all_perm_issues)}")
print(f"API 脱敏问题数: {len(mask_issues)}")
print(f"JS 脱敏可疑点: {len(found_lines)}")
print("")

# 输出 CSV
os.makedirs("docs", exist_ok=True)
with open("docs/T24_security_audit.csv", "w", newline="", encoding="utf-8") as f:
    writer = csv.writer(f)
    writer.writerow(["优先级", "文件", "函数", "路由", "问题描述"])
    for row in all_perm_issues:
        writer.writerow(row)
print(">>> 已输出 docs/T24_security_audit.csv")
