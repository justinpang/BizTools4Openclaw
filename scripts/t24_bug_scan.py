"""T24 A3/D: JS/API 边界条件缺陷扫描"""
import re
import os

# ========== JS 缺陷扫描 ==========
js_path = "web_admin/static/js/admin.js"
js = open(js_path, encoding="utf-8").read()
lines = js.split("\n")

issues = []

print("=" * 80)
print("JS Issue 1: fetch().then() 无 .catch() - 网络异常时页面挂起")
print("=" * 80)

# 找 fetch 调用, 检查是否有 .catch()
fetch_matches = re.finditer(r"fetch\(", js)
for m in fetch_matches:
    line_num = js[:m.start()].count("\n") + 1
    # 看后面 15 行内是否有 .catch
    end_idx = min(m.end() + 500, len(js))
    after = js[m.end():end_idx]
    lines_after = after.split("\n")[:15]
    has_catch = any(".catch" in l for l in lines_after)
    if not has_catch:
        issues.append(("P2", "JS", line_num, "fetch 缺少 .catch() 错误处理", lines[line_num-1].strip()[:80]))

# ========== Issue 2: 重复提交保护 ==========
print("\n" + "=" * 80)
print("JS Issue 2: 表单提交按钮无 disabled 保护")
print("=" * 80)

submit_btns = re.finditer(r"(submit|submitForm|op_batch_submit|op_export_submit)\s*[=:]", js)
for m in submit_btns:
    line_num = js[:m.start()].count("\n") + 1
    # 检查前后 30 行是否有 disabled = true/false
    start = max(0, m.start() - 300)
    end = min(len(js), m.end() + 300)
    context = js[start:end]
    if "disabled" not in context.lower():
        issues.append(("P3", "JS", line_num, "提交按钮可能缺少 disabled 保护", lines[line_num-1].strip()[:80]))

# ========== Issue 3: data.items 为空时渲染问题 ==========
print("\n" + "=" * 80)
print("JS Issue 3: data.items 为空时的渲染问题")
print("=" * 80)

# 找 for/forEach 循环渲染表格
render_loops = re.finditer(r"(data\.items|items\.forEach|\.map\()", js)
for m in render_loops:
    line_num = js[:m.start()].count("\n") + 1
    # 检查附近是否有空状态检查
    start = max(0, m.start() - 200)
    end = min(len(js), m.end() + 200)
    context = js[start:end]
    has_empty_check = any(tok in context for tok in ["empty", "length == 0", "length === 0", "!data.items", "if (!items", "no data"])
    if not has_empty_check and len([x for x in issues if x[2] == line_num]) == 0:
        # 只记录一个典型的
        pass

# ========== Issue 4: 数据类型问题 ==========
print("\n" + "=" * 80)
print("JS Issue 4: parseInt/parseFloat 无默认值")
print("=" * 80)

parse_calls = re.finditer(r"(parseInt|parseFloat)\(([^)]*)\)", js)
for m in parse_calls:
    line_num = js[:m.start()].count("\n") + 1
    args = m.group(2)
    # 检查是否有 || 0 或 ?? 0 保护
    line = lines[line_num - 1] if line_num <= len(lines) else ""
    if "||" not in line and "??" not in line and "||" not in args and "default" not in args:
        if len([x for x in issues if abs(x[2] - line_num) < 2]) == 0:
            issues.append(("P3", "JS", line_num, "数值解析可能缺少默认值保护", line.strip()[:80]))

# ========== Issue 5: 越权按钮显示控制 ==========
print("\n" + "=" * 80)
print("JS Issue 5: 按钮权限显示控制")
print("=" * 80)

# 找 .onclick / addEventListener 绑定操作, 看是否有权限过滤
op_buttons = re.finditer(r"(admin\.|window\.)?(op_|submit|apply|delete|remove|mark|resend|reinsert|retry|grade|assign|close)", js)
for m in list(op_buttons)[:20]:
    line_num = js[:m.start()].count("\n") + 1
    pass  # 太宽泛, 后续手动审核

# ========== API 缺陷扫描 ==========
print("\n" + "=" * 80)
print("API Issue 1: POST/PUT 返回结构一致性")
print("=" * 80)

import glob
api_files = glob.glob("web_admin/api/*.py")
for fpath in api_files:
    content = open(fpath, encoding="utf-8").read()
    fname = os.path.basename(fpath)
    # 找 return {code: ...} 模式看是否有不一致
    returns = re.finditer(r"return\s*\{([^}]{0,200})\}", content)
    for m in returns:
        block = m.group(1)
        line_num = content[:m.start()].count("\n") + 1
        if "code" not in block and '"msg"' not in block and "'msg'" not in block:
            # 可能是纯数据返回, 看是否在 GET 路由内
            func_start = content.rfind("\ndef ", 0, m.start())
            func_name = ""
            if func_start != -1:
                func_match = re.search(r"def\s+(\w+)", content[func_start:func_start+50])
                if func_match:
                    func_name = func_match.group(1)
            if func_name:
                issues.append(("P3", fname, line_num, f"返回结构缺少 code/msg 字段: {func_name}", block.strip()[:60]))

# ========== Issue 2: try/except 覆盖 ==========
print("\n" + "=" * 80)
print("API Issue 2: 关键 API 缺少 try/except")
print("=" * 80)

for fpath in api_files:
    content = open(fpath, encoding="utf-8").read()
    fname = os.path.basename(fpath)
    # 找 POST/PUT/DELETE 路由, 看函数体是否有 try/except
    routes = re.finditer(r"@router\.(post|put|delete|patch)\(([^)]+)\)\s*\n\s*def\s+(\w+)", content)
    for m in routes:
        func = m.group(3)
        func_start = content.find("def " + func, m.start())
        if func_start == -1:
            continue
        next_def = content.find("\ndef ", func_start + 5)
        func_block = content[func_start:next_def] if next_def != -1 else content[func_start:]
        if "try:" not in func_block and "except" not in func_block and len(func_block) > 200:
            line_num = content[:m.start()].count("\n") + 1
            issues.append(("P2", fname, line_num, f"POST/PUT/DELETE 路由 {func} 缺少 try/except 异常保护", ""))

# ========== Issue 3: Redis 不可用时的回退 ==========
print("\n" + "=" * 80)
print("API Issue 3: Redis 调用是否有 try/except 回退")
print("=" * 80)

for fpath in api_files:
    content = open(fpath, encoding="utf-8").read()
    fname = os.path.basename(fpath)
    # 找 get_redis() 或 r.xxx 调用, 看是否在 try/except 内
    redis_calls = re.finditer(r"(get_redis|redis|r\.hget|r\.set|r\.get|r\.sadd|r\.hset|r\.scard|r\.keys)", content)
    for m in list(redis_calls)[:5]:
        line_num = content[:m.start()].count("\n") + 1
        # 向上/下找 try/except
        context_start = max(0, m.start() - 500)
        context_end = min(len(content), m.end() + 500)
        context = content[context_start:context_end]
        has_try = "try:" in context
        if not has_try:
            issues.append(("P3", fname, line_num, "Redis 调用附近缺少 try/except 异常保护", ""))
            break  # 每个文件只记一条

# ========== 汇总输出 ==========
print("\n" + "=" * 80)
print(f"缺陷汇总: 共发现 {len(issues)} 个问题")
print("=" * 80)

# 按优先级排序
priority_order = {"P0": 0, "P1": 1, "P2": 2, "P3": 3}
issues.sort(key=lambda x: priority_order.get(x[0], 9))

for p, f, ln, desc, ctx in issues:
    print(f"  [{p}] {f}:{ln} - {desc}")
    if ctx:
        print(f"         {ctx}")

# 统计
counts = {}
for p, _, _, _, _ in issues:
    counts[p] = counts.get(p, 0) + 1
print(f"\n按优先级: {counts}")
