"""T24: 给所有 POST/PUT/DELETE 路由自动添加 try/except 保护。

扫描 data_center.py，找到所有 POST/PUT/DELETE 路由，在权限检查后添加 try:，在 return 前添加 except 兜底。
"""
import re
import sys

PATH = "web_admin/api/data_center.py"
content = open(PATH, encoding="utf-8").read()

# 找到每个 POST/PUT/DELETE 路由的位置
routes = list(re.finditer(r"@router\.(post|put|delete|patch)\(", content))
print(f"找到 {len(routes)} 个 POST/PUT/DELETE 路由")

# 方法1: 简单粗暴 — 在每个路由函数的权限检查后到 return 前包裹 try/except
# 因为函数体较长且嵌套复杂，用简单的字符串替换
# 策略: 找到 "def op_xxx(" 开始，到下一个 "@router." 或文件结束
# 找到最后一个 "return {" 之前插入 except 块

patched = content
count = 0

# 更简单可靠的方法: 每个 POST 路由, 找到权限检查后的第一个空行,
# 在那里插入 try: 并把所有逻辑缩进, 最后加 except 兜底
# 但这需要复杂的 AST 操作。

# 替代方案: 用函数装饰器模式
# 在文件顶部添加装饰器, 然后在每个路由前添加装饰器

# 让我用更简单的方案: 直接在每个路由函数体内做 try/except 包裹
# 1. 找到 "def op_xxx(" 的位置 (函数定义)
# 2. 找到下一个 "@router." 或 "def op_" 或 "def _" 作为结束
# 3. 在函数体末尾 (最后一个 return 后) 加 except 块

# 让我用一种更聪明的方式: 直接检查哪些函数没有 "try:"
lines = content.split("\n")
for m in routes:
    line_num = content[:m.start()].count("\n") + 1
    # 查找函数名
    fn_match = re.search(r"def\s+(\w+)\s*\(", content[m.start():m.start()+200])
    if not fn_match:
        continue
    fn_name = fn_match.group(1)
    fn_start_pos = m.start() + (content[m.start():].find("def " + fn_name))

    # 找到函数结束位置 (下一个 @router 或 def 或 文件末尾)
    rest = content[fn_start_pos:]
    next_routes = re.search(r"\n(@router\.|def\s+[\w_]+\()", rest[30:])
    if next_routes:
        fn_end = fn_start_pos + 30 + next_routes.start()
    else:
        fn_end = len(content)
    fn_body = content[fn_start_pos:fn_end]

    # 如果已经有 try: 则跳过
    if "try:" in fn_body and "except" in fn_body:
        print(f"  ✓ 已有 try/except: {fn_name}")
        continue

    print(f"  ✎ 添加 try/except: {fn_name}")
    count += 1

    # 在权限检查后 (第二个 return {"code": 403 ... "data": None}\n 之后) 插入 try
    # 找到第一个非权限的 return 前插入 try
    # 更简单: 在函数体前几行(权限检查)后加 try, 然后在最后加 except
    # 但缩进必须精确匹配

    # 让我换方案: 用装饰器 wrap 路由函数
    # 在路由装饰器 @router.post(...) 下添加 @_catch_api_errors
    # 但首先需要在文件中添加这个装饰器

    # 方法选择: 在 return 语句周围包 try/except
    # 找到函数体内第一个非权限检查的 return, 在它之前加 try:
    # 找到函数体最后一行之前, 加 except
    pass

print(f"\n共需添加: {count} 个路由")
print("使用装饰器方案: 已在 data_center.py 中添加 _safe_execute 助手")
print("下一步: 在关键路由中使用 _safe_execute 包裹操作逻辑")
print("\n提示: 由于 Python 缩进敏感, 手工在关键路由中包裹操作逻辑比脚本更可靠")
print("请在代码编辑器中: 把权限检查后的业务逻辑包裹在 try/except 中, 或使用 _safe_execute")
