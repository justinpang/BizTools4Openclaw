<#
.SYNOPSIS
    启动 Docker 调试容器
.DESCRIPTION
    一键启动 BizTools4Openclaw 的 Docker 调试容器，并显示所有端口映射和调试信息
.PARAMETER Mode
    调试模式：lite (SQLite+内存Redis) 或 debug (完整 PostgreSQL+Redis)
.EXAMPLE
    .\start-debug.ps1 -Mode lite
    .\start-debug.ps1 -Mode debug
#>

param(
    [ValidateSet("lite", "debug")]
    [string]$Mode = "lite"
)

$ErrorActionPreference = "Stop"

$ProjectRoot = Split-Path -Parent $PSScriptRoot
Set-Location $ProjectRoot

Write-Host ""
Write-Host "========================================" -ForegroundColor Cyan
Write-Host "  BizTools4Openclaw  Docker Debug" -ForegroundColor Cyan
Write-Host "  Mode: $Mode" -ForegroundColor Yellow
Write-Host "========================================" -ForegroundColor Cyan
Write-Host ""

# 检查 Docker 是否运行
try {
    $null = docker version 2>&1
} catch {
    Write-Host "Docker Desktop 未运行，请先启动 Docker Desktop!" -ForegroundColor Red
    exit 1
}

# 根据模式选择 profile
if ($Mode -eq "lite") {
    $ProfileName = "debug-lite"
    $ContainerName = "biz-tools-app-debug-lite"
    Write-Host "[1/3] 启动调试容器（SQLite + 内存 Redis stub)" -ForegroundColor Green
} else {
    $ProfileName = "debug"
    $ContainerName = "biz-tools-app-debug"
    Write-Host "[1/3] 启动调试容器（PostgreSQL + Redis）" -ForegroundColor Green
}

# 检查端口占用并警告
$port8000 = try { (Get-NetTCPConnection -LocalPort 8000 -ErrorAction SilentlyContinue | Select-Object -First 1) } catch { $null }
$port5678 = try { (Get-NetTCPConnection -LocalPort 5678 -ErrorAction SilentlyContinue | Select-Object -First 1) } catch { $null }

if ($port8000 -or $port5678) {
    Write-Host ""
    Write-Host "WARNING: Port 8000 or 5678 may be in use!" -ForegroundColor Yellow
    Write-Host "  You may need to stop other containers first." -ForegroundColor Yellow
    $choice = Read-Host "Continue? (y/n)"
    if ($choice -ne "y") { exit 0 }
}

# 构建并启动
Write-Host ""
Write-Host "[2/3] 构建镜像并启动容器..." -ForegroundColor Green
Write-Host "  docker compose -f docker/docker-compose.yml --profile $ProfileName up -d --build"
Write-Host ""

docker compose -f docker/docker-compose.yml --profile $ProfileName up -d --build

if ($LASTEXITCODE -ne 0) {
    Write-Host ""
    Write-Host "FAILED! Check Docker build error above." -ForegroundColor Red
    exit 1
}

Write-Host ""
Write-Host "[3/3] 容器已启动" -ForegroundColor Green

# 等待容器就绪
$maxWait = 0
$ready = $false
while ($maxWait -lt 30) {
    $status = docker inspect -f '{{.State.Status}}' $ContainerName 2>$null
    if ($status -eq "running") {
        $ready = $true
        break
    }
    Start-Sleep -Seconds 1
    $maxWait++
}

if (-not $ready) {
    Write-Host ""
    Write-Host "WARNING: Container not ready in 30s. Check: docker ps" -ForegroundColor Yellow
}

# 输出使用信息
Write-Host ""
Write-Host "========================================" -ForegroundColor Cyan
Write-Host "  访问地址" -ForegroundColor Cyan
Write-Host "========================================" -ForegroundColor Cyan
Write-Host ""
Write-Host "  应用访问:" -ForegroundColor White
Write-Host "    http://localhost:8000/health" -ForegroundColor Green
Write-Host "    http://localhost:8000/docs" -ForegroundColor Green
Write-Host "    http://localhost:8000/admin" -ForegroundColor Green
Write-Host ""
Write-Host "  调试端口:" -ForegroundColor White
Write-Host "    localhost:5678 (debugpy)" -ForegroundColor Green
Write-Host ""

if ($Mode -eq "debug") {
    Write-Host "  数据库:" -ForegroundColor White
    Write-Host "    localhost:5432 (PostgreSQL)" -ForegroundColor Green
    Write-Host "    localhost:6379 (Redis)" -ForegroundColor Green
    Write-Host ""
}

Write-Host "  VS Code 调试步骤:" -ForegroundColor White
Write-Host "    1. 打开 Run and Debug (Ctrl+Shift+D)" -ForegroundColor Cyan
Write-Host "    2. 选择配置 " -NoNewline
Write-Host "Docker Attach (debug-lite)" -ForegroundColor Yellow
Write-Host "    3. 在断点处暂停" -ForegroundColor Cyan
Write-Host "    4. 触发请求 (http://localhost:8000)" -ForegroundColor Cyan
Write-Host ""
Write-Host "  查看日志:" -ForegroundColor White
Write-Host "    docker compose -f docker/docker-compose.yml logs -f app-debug-lite" -ForegroundColor Green
Write-Host "    docker compose -f docker/docker-compose.yml logs -f app-debug" -ForegroundColor Green
Write-Host ""
Write-Host "  进入容器:" -ForegroundColor White
Write-Host "    docker exec -it $ContainerName /bin/bash" -ForegroundColor Green
Write-Host ""
Write-Host "  停止:" -ForegroundColor White
Write-Host "    docker compose -f docker/docker-compose.yml down" -ForegroundColor Green
Write-Host ""
