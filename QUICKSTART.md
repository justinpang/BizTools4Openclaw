# ============================================================
# BizTools4Openclaw —— 本地开发快速启动指南
# ============================================================

# 前置要求：
#   1. Python 3.11.x (推荐 3.11.9 / 3.11.11)
#   2. Docker Desktop（可选，用于全栈部署）
#   3. Windows 10/11 或 Linux/macOS

# ============================================================
# 第 1 步：安装 Python 3.11
# ============================================================

# Windows 用户（推荐使用 Python Launcher）：
# 方法 A: 通过 Python Launcher（py）
#   打开 PowerShell，执行：
#     py install 3.11
#   安装完成后验证：
#     py -3.11 --version
#     # 预期输出：Python 3.11.x

# 方法 B: 官方安装程序
#   访问 https://www.python.org/downloads/windows/
#   下载 Python 3.11.x 安装程序（推荐 3.11.9）
#   勾选 "Add Python to PATH" 后安装

# 方法 C: Windows Store
#   在 Microsoft Store 搜索 "Python 3.11" 并安装

# Linux / macOS 用户：
#   pyenv install 3.11
#   pyenv local 3.11

# ============================================================
# 第 2 步：创建虚拟环境并安装依赖
# ============================================================

# Windows (PowerShell)
#   py -3.11 -m venv .venv
#   .\.venv\Scripts\Activate.ps1
#   pip install --upgrade pip
#   pip install -r requirements.txt

# Linux / macOS (bash)
#   python3.11 -m venv .venv
#   source .venv/bin/activate
#   pip install --upgrade pip
#   pip install -r requirements.txt

# ============================================================
# 第 3 步：配置环境变量
# ============================================================

# 复制 .env.example 为 .env（已为您准备好）
#   Windows: copy .env.example .env
#   Linux/mac: cp .env.example .env
#
# 注意：默认配置为 SQLite 模式，无需任何外部数据库即可运行

# ============================================================
# 第 4 步：启动服务
# ============================================================

# 开发模式（不使用 Docker）
#   uvicorn adapter.main:app --host 0.0.0.0 --port 8000 --reload
#
# 或使用模块方式：
#   python -m adapter.main

# 然后访问：
#   - API 文档: http://localhost:8000/docs
#   - 健康检查: http://localhost:8000/health

# ============================================================
# 第 5 步（可选）：使用 Docker 部署
# ============================================================

# 启动 Docker Desktop，确保 docker 命令可用：
#   docker --version

# 完整栈部署（应用 + PostgreSQL + Redis）
#   docker compose -f docker/docker-compose.yml --profile dev up -d --build

# 轻量部署（仅应用，SQLite 模式）
#   docker compose -f docker/docker-compose.yml --profile lite up -d --build

# 停止服务
#   docker compose -f docker/docker-compose.yml --profile dev down

# ============================================================
# 快速验证命令
# ============================================================

# 1. 验证 Python 版本
python --version
# 预期: Python 3.11.x

# 2. 验证依赖导入
python -c "import fastapi, uvicorn, sqlalchemy; print('✓ 核心依赖正常')"

# 3. 健康检查（服务启动后）
curl http://localhost:8000/health
