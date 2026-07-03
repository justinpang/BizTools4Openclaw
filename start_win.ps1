# ====================================================================
#  BizTools4Openclaw — Windows 一键部署脚本
#  支持：Docker Compose / 本地进程 / 服务管理
#
#  使用方法（在项目根目录 PowerShell 中执行）：
#    Set-ExecutionPolicy RemoteSigned -Scope CurrentUser   # 首次需允许脚本
#    .\start_win.ps1                                        # 交互式（推荐首次）
#    .\start_win.ps1 -Mode docker-prod                      # Docker 生产模式
#    .\start_win.ps1 -Mode docker-dev                       # Docker 开发模式（热重载）
#    .\start_win.ps1 -Mode local                            # 本地进程模式（无 Docker）
#    .\start_win.ps1 -Stop                                  # 停止所有服务
#    .\start_win.ps1 -Logs                                  # 查看服务日志
#    .\start_win.ps1 -Clean                                 # 清理 .venv / docker volumes
# ====================================================================

param(
    [Parameter(Mandatory = $false)]
    [ValidateSet("interactive", "docker-prod", "docker-dev", "local", "stop", "logs", "clean")]
    [string]$Mode = "interactive"
)

# ============================================================
#  0. 彩色日志工具函数
# ============================================================
function Write-Info  ($msg) { Write-Host "[INFO ] $msg" -ForegroundColor Cyan }
function Write-Ok    ($msg) { Write-Host "[OK   ] $msg" -ForegroundColor Green }
function Write-Warn  ($msg) { Write-Host "[WARN ] $msg" -ForegroundColor Yellow }
function Write-Err   ($msg) { Write-Host "[ERROR] $msg" -ForegroundColor Red }
function Write-Tip   ($msg) { Write-Host "[TIP  ] $msg" -ForegroundColor Magenta }
function Write-Banner($title) {
    $line = "=" * 70
    Write-Host ""
    Write-Host $line -ForegroundColor Gray
    Write-Host "  $title" -ForegroundColor White
    Write-Host $line -ForegroundColor Gray
}

# ============================================================
#  1. 环境预检
# ============================================================
function Test-PortInUse([int]$port) {
    try {
        $conn = Get-NetTCPConnection -LocalPort $port -State Listen -ErrorAction SilentlyContinue
        return ($null -ne $conn)
    } catch { return $false }
}

function Invoke-EnvironmentCheck {
    Write-Banner "步骤 1 / 4  —  环境预检查"

    # --- Python ---
    try {
        $py = python --version 2>&1
        if ($LASTEXITCODE -eq 0) {
            Write-Ok "Python 已安装: $py"
        } else {
            Write-Err "未检测到 Python，请先安装 Python 3.10+：https://www.python.org/downloads/"
            exit 1
        }
    } catch {
        Write-Err "未检测到 Python，请先安装 Python 3.10+：https://www.python.org/downloads/"
        exit 1
    }

    # --- Docker（非强制）---
    try {
        $dockerVer = docker --version 2>&1
        if ($LASTEXITCODE -eq 0) {
            Write-Ok "Docker 已安装: $dockerVer"
        } else {
            Write-Warn "未检测到 Docker。如需容器部署请先安装：https://www.docker.com/products/docker-desktop/"
        }
    } catch {
        Write-Warn "未检测到 Docker。如需容器部署请先安装：https://www.docker.com/products/docker-desktop/"
    }

    # --- 端口检查 ---
    $portsToCheck = @(8000, 5432, 6379)
    $usedPorts = @()
    foreach ($p in $portsToCheck) {
        if (Test-PortInUse $p) { $usedPorts += $p }
    }
    if ($usedPorts.Count -gt 0) {
        Write-Warn "以下端口可能被占用：$($usedPorts -join ', ')"
        Write-Tip "  查看占用进程： netstat -ano | findstr :<port>"
    } else {
        Write-Ok "关键端口（8000/5432/6379）可用"
    }
}

# ============================================================
#  2. 自动生成 .env（从 .env.example 复制）
# ============================================================
function Invoke-GenerateEnv {
    Write-Banner "步骤 2 / 4  —  生成 .env 配置"

    if (-not (Test-Path .\.env.example)) {
        Write-Err "找不到 .env.example，请确认当前目录是项目根目录。"
        exit 1
    }
    if (Test-Path .\.env) {
        Write-Ok ".env 已存在，跳过生成。如要重置请删除 .env 后重新执行。"
        return
    }

    Copy-Item .\.env.example .\.env
    Write-Ok "已从 .env.example 生成 .env"
    Write-Tip "  ⚠ 请在 .env 中至少填写以下字段："
    Write-Tip "      DB_PASSWORD                 : PostgreSQL 数据库密码（强随机）"
    Write-Tip "      DB_ENCRYPTION_KEY           : 敏感字段加密密钥（≥32 字符，生成后不可更改）"
    Write-Tip "      WEB_ADMIN_PASSWORD_PLAIN    : Web 管理后台登录密码"
    Write-Tip "      REDIS_PASSWORD              : （可选）Redis 密码"
    Write-Tip "      ADAPTER_API_TOKENS          : （可选）OpenClaw 网关访问 token"
}

# ============================================================
#  3. 虚拟环境 + Python 依赖
# ============================================================
function Invoke-SetupVenv {
    Write-Banner "步骤 3 / 4  —  创建虚拟环境并安装依赖"

    if (Test-Path .\.venv) {
        Write-Ok ".venv 已存在，跳过创建"
    } else {
        Write-Info "创建虚拟环境 .venv ..."
        python -m venv .venv
        if ($LASTEXITCODE -ne 0) {
            Write-Err "创建虚拟环境失败"
            exit 1
        }
        Write-Ok "虚拟环境创建成功"
    }

    Write-Info "激活虚拟环境并安装依赖（pip install -r requirements.txt）..."
    $activateScript = ".\.venv\Scripts\Activate.ps1"
    if (-not (Test-Path $activateScript)) {
        Write-Err "找不到虚拟环境激活脚本: $activateScript"
        exit 1
    }

    & $activateScript
    pip install -r requirements.txt
    if ($LASTEXITCODE -ne 0) {
        Write-Err "依赖安装失败。请检查网络或 requirements.txt。"
        exit 1
    }
    Write-Ok "Python 依赖安装完成。"

    # --- 可选：安装 Playwright Chromium ---
    try {
        $pwExists = python -c "import playwright" 2>&1
        if ($LASTEXITCODE -eq 0) {
            Write-Info "安装 Playwright Chromium 浏览器（供爬虫使用，可跳过）..."
            python -m playwright install chromium 2>&1 | Out-Null
            if ($LASTEXITCODE -eq 0) { Write-Ok "Playwright Chromium 已安装" }
            else { Write-Warn "Playwright Chromium 安装失败（网络问题？），爬虫功能将受限。" }
        }
    } catch {
        Write-Warn "跳过 Playwright 安装（不影响基本功能）。"
    }
}

# ============================================================
#  4. 启动服务
# ============================================================
function Invoke-StartDocker($profile) {
    Write-Banner "步骤 4 / 4  —  Docker Compose 启动（profile: $profile）"

    try {
        $dockerVer = docker --version 2>&1
        if ($LASTEXITCODE -ne 0) {
            Write-Err "未检测到 Docker。请先安装 Docker Desktop 或选择 -Mode local。"
            exit 1
        }
    } catch {
        Write-Err "未检测到 Docker。请先安装 Docker Desktop 或选择 -Mode local。"
        exit 1
    }

    Set-Location docker
    Write-Info "构建镜像并启动服务（db + redis + app）..."
    docker compose --profile $profile up -d --build
    if ($LASTEXITCODE -ne 0) {
        Set-Location ..
        Write-Err "Docker Compose 启动失败。"
        Write-Tip "  排查： docker compose logs [db|redis|app|app-dev]"
        Write-Tip "  可能原因：端口被占用 / .env 未配置 / 网络无法拉取镜像"
        exit 1
    }

    Write-Info "等待数据库与 Redis 就绪（约 20 秒）..."
    Start-Sleep -Seconds 20

    # --- 健康检查 ---
    try {
        $health = curl -s http://localhost:8000/health 2>&1
        if ($health -match '"status"') {
            Write-Ok "服务健康检查通过： http://localhost:8000/health"
        } else {
            Write-Warn "服务正在启动，健康检查暂未就绪。请稍后重试。"
        }
    } catch {
        Write-Warn "健康检查请求失败，但服务可能仍在启动中。请稍后重试。"
    }

    Set-Location ..
    Write-Banner "部署完成"
    Write-Tip "  · Web 管理后台:   http://localhost:8000/admin"
    Write-Tip "  · API 文档 (Swagger): http://localhost:8000/docs"
    Write-Tip "  · 健康检查:       http://localhost:8000/health"
    Write-Tip "  · 查看日志:        .\start_win.ps1 -Logs"
    Write-Tip "  · 停止服务:        .\start_win.ps1 -Stop"
}

function Invoke-StartLocal {
    Write-Banner "步骤 4 / 4  —  本地进程模式启动（FastAPI 直启）"

    if (-not (Test-Path .\.venv)) {
        Write-Warn "未检测到 .venv，将使用系统 Python（不推荐）。"
    } else {
        & .\.venv\Scripts\Activate.ps1
    }

    # --- 启动 FastAPI ---
    Write-Info "启动 FastAPI 应用（uvicorn）..."
    Write-Tip "  · 进程在前台运行，按 Ctrl+C 停止"
    Write-Tip "  · 请确保持有可用的 Redis（或允许降级为内存缓存）"
    Write-Tip "  · 请确保持有可用的 PostgreSQL（或允许降级为 SQLite）"

    try {
        uvicorn adapter.main:app --host 0.0.0.0 --port 8000 --reload --workers 1
    } catch {
        python -m adapter.main
    }
}

# ============================================================
#  5. 停止服务 / 查看日志 / 清理
# ============================================================
function Invoke-Stop {
    Write-Banner "停止所有服务"
    $foundDocker = $false
    try {
        $null = docker --version 2>&1
        if ($LASTEXITCODE -eq 0) { $foundDocker = $true }
    } catch { $foundDocker = $false }

    if ($foundDocker -and (Test-Path docker\docker-compose.yml)) {
        Set-Location docker
        Write-Info "停止 docker-compose 服务（prod + dev）..."
        docker compose --profile prod down
        docker compose --profile dev down
        Set-Location ..
    } else {
        Write-Info "停止本地 uvicorn 进程..."
        Get-Process | Where-Object { $_.ProcessName -eq "uvicorn" -or $_.ProcessName -eq "python" -and $_.MainWindowTitle -match "adapter" } | Stop-Process -Force -ErrorAction SilentlyContinue
    }
    Write-Ok "已停止所有服务。"
}

function Invoke-ShowLogs {
    Write-Banner "服务日志"
    try {
        $null = docker --version 2>&1
        if ($LASTEXITCODE -eq 0 -and (Test-Path docker\docker-compose.yml)) {
            Set-Location docker
            Write-Info "查看 app / app-dev 日志（按 Ctrl+C 退出）..."
            docker compose logs -f app app-dev
            Set-Location ..
            return
        }
    } catch {}

    Write-Info "查看 logs/ 目录下的日志文件（最近 20 行）..."
    if (-not (Test-Path logs)) {
        Write-Warn "未找到 logs/ 目录（服务尚未启动，或使用 Docker 模式）"
        return
    }
    Get-ChildItem logs\*.log -ErrorAction SilentlyContinue | ForEach-Object {
        Write-Host ""
        Write-Host " --- $($_.FullName)" -ForegroundColor Gray
        Get-Content $_.FullName -Tail 20
    }
}

function Invoke-Clean {
    Write-Banner "清理本地部署痕迹（谨慎操作）"

    # --- 确认 ---
    Write-Warn "将删除： .venv/   docker volumes(pg_data, redis_data)   logs/*.log"
    $confirm = Read-Host "确认？(y/N)"
    if ($confirm -notmatch "^[Yy]$") { Write-Info "已取消。"; return }

    if (Test-Path .\.venv) {
        Remove-Item -Recurse -Force .\.venv
        Write-Ok "已删除 .venv"
    }
    if (Test-Path logs) {
        Remove-Item -Recurse -Force logs\*.log -ErrorAction SilentlyContinue
        Write-Ok "已清理 logs/*.log"
    }
    try {
        $null = docker --version 2>&1
        if ($LASTEXITCODE -eq 0 -and (Test-Path docker\docker-compose.yml)) {
            Set-Location docker
            docker compose --profile prod down -v 2>&1 | Out-Null
            docker compose --profile dev  down -v 2>&1 | Out-Null
            Set-Location ..
            Write-Ok "已删除 docker volumes。"
        }
    } catch { Write-Warn "未检测到 Docker，跳过 docker volumes 删除。" }

    Write-Ok "清理完成。"
}

# ============================================================
#  6. 交互式选择启动模式
# ============================================================
function Show-InteractiveMenu {
    Write-Banner "BizTools4Openclaw 一键部署（Windows）"
    Write-Host ""
    Write-Host "请选择部署模式："
    Write-Host "  [1] Docker 生产模式  (推荐正式使用)"
    Write-Host "  [2] Docker 开发模式  (代码热重载，适合开发调试)"
    Write-Host "  [3] 本地进程模式    (无需 Docker，直接 uvicorn)"
    Write-Host "  [4] 停止服务"
    Write-Host "  [5] 查看日志"
    Write-Host "  [6] 清理部署痕迹"
    Write-Host "  [0] 退出"
    Write-Host ""
    $choice = Read-Host "输入编号"

    switch ($choice) {
        "1" { Invoke-EnvironmentCheck; Invoke-GenerateEnv; Invoke-StartDocker "prod" }
        "2" { Invoke-EnvironmentCheck; Invoke-GenerateEnv; Invoke-StartDocker "dev" }
        "3" { Invoke-EnvironmentCheck; Invoke-GenerateEnv; Invoke-SetupVenv; Invoke-StartLocal }
        "4" { Invoke-Stop }
        "5" { Invoke-ShowLogs }
        "6" { Invoke-Clean }
        "0" { Write-Info "已退出。" }
        default { Write-Err "无效选择。"; exit 1 }
    }
}

# ============================================================
#  7. 主入口
# ============================================================
try {
    # 确保在项目根目录
    if (-not (Test-Path .\adapter\main.py) -or -not (Test-Path .\.env.example)) {
        Write-Err "当前目录不是项目根目录（找不到 adapter/main.py 或 .env.example）。"
        Write-Tip "  请 cd 到 BizTools4Openclaw 根目录后再执行。"
        exit 1
    }

    if ($Mode -eq "interactive") {
        Show-InteractiveMenu
        return
    }
    if ($Mode -eq "stop")  { Invoke-Stop; return }
    if ($Mode -eq "logs")  { Invoke-ShowLogs; return }
    if ($Mode -eq "clean") { Invoke-Clean; return }

    # --- 需要 .env 的模式 ---
    Invoke-EnvironmentCheck
    Invoke-GenerateEnv

    if ($Mode -eq "docker-prod") { Invoke-StartDocker "prod" }
    elseif ($Mode -eq "docker-dev") { Invoke-StartDocker "dev" }
    elseif ($Mode -eq "local") {
        Invoke-SetupVenv
        Invoke-StartLocal
    }
} catch {
    Write-Err "执行异常: $($_.Exception.Message)"
    Write-Info "完整堆栈："
    Write-Info $_.ScriptStackTrace
    Write-Tip "  · 请查看 docs/DEPLOY_GUIDE.md 故障排查章节"
    Write-Tip "  · 也可直接执行： .\start_win.ps1 -Logs  查看服务日志"
    exit 1
}
