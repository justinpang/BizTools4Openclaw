# BizTools4Openclaw — 部署指南

> 文档版本：T16-v1.0  
> 适用版本：BizTools4Openclaw  
> 覆盖平台：**Windows 本地** / **Docker 容器** / **Linux 原生**
> 前置阅读：README.md / DEVELOP_RULES.md
> 故障排查：见第 4 章

---

## 0. 前置条件检查清单

在开始部署前，请逐项确认并填写：

| # | 检查项 | 状态 |
|---|--------|------|
| 0.1 | Python ≥ 3.10 | □ |
| 0.2 | 操作系统：Windows 10/11 / macOS 12+ / Linux kernel ≥ 5.4 | □ |
| 0.3 | 硬盘可用空间 ≥ 2 GB（Docker 镜像 + 数据） | □ |
| 0.4 | 端口 8000 / 5432 / 6379 未被占用 | □ |
| 0.5 | 拥有项目代码仓库访问权限（git clone成功） | □ |
| 0.6 | （若使用 Docker）Docker Desktop 已启动 | □ |
| 0.7 | （若使用本地进程）可访问 pip 源或有镜像源 | □ |

---

## 1. Windows 本地单机部署（推荐）

### 1.1 下载与环境准备

```powershell
# 打开 PowerShell，进入项目根目录
cd .\BizTools4Openclaw

# 允许本地脚本执行（仅首次）
Set-ExecutionPolicy RemoteSigned -Scope CurrentUser
```

### 1.2 交互式一键部署（推荐首次使用）

```powershell
.\start_win.ps1
# 选择 "1 = Docker 生产模式" 或 "3 = 本地进程模式"
```

脚本将自动完成：
- ✅ Python / Docker 环境检查
- ✅ 自动从 `.env.example` 生成 `.env`
- ✅ 创建虚拟环境 `.venv`（本地模式）
- ✅ 安装 Python 依赖（`pip install -r requirements.txt`）
- ✅ 安装 Playwright Chromium（可选）
- ✅ 启动服务并打印访问地址

### 1.3 命令行快速启动（非交互式）

```powershell
# Docker 生产模式（推荐正式环境）
.\start_win.ps1 -Mode docker-prod

# Docker 开发模式（代码热重载）
.\start_win.ps1 -Mode docker-dev

# 本地进程模式（无 Docker）
.\start_win.ps1 -Mode local

# 停止所有服务
.\start_win.ps1 -Stop

# 查看日志
.\start_win.ps1 -Logs

# 清理部署痕迹
.\start_win.ps1 -Clean
```

### 1.4 访问应用

| 服务 | 地址 | 说明 |
|------|------|------|
| **Web 管理后台** | http://localhost:8000/admin | 使用 `.env` 中 `WEB_ADMIN_USERNAME` / `WEB_ADMIN_PASSWORD_PLAIN` 登录 |
| **API 文档（Swagger）** | http://localhost:8000/docs | 交互式 API 调试 |
| **健康检查** | http://localhost:8000/health | 返回 `{"code":0,"msg":"success","data":{"status":"OK"},...}` |

---

## 2. Docker 容器部署（生产推荐）

### 2.1 准备 .env

```bash
cp .env.example .env
# Windows PowerShell: Copy-Item .env.example .env
```

**必填项（必须手动设置）：

| 变量 | 说明 | 示例 |
|------|------|------|
| `DB_PASSWORD` | PostgreSQL 数据库密码（强随机） | `V3ryStr0ng!P@ssw0rd` |
| `DB_ENCRYPTION_KEY` | 敏感字段加密密钥（**≥32 字符**，生成后不可变更） | `c6b5d4a6e0e7f9a0b1c2d3e4f5a6b7c8` |
| `WEB_ADMIN_PASSWORD_PLAIN` | Web 管理后台登录密码 | `MyAdm1n!Pass` |
| `PROJECT_NAME` | 项目名（显示在日志/告警） | `openclaw-biz-tools` |

可选项（按需）：

| 变量 | 默认 | 说明 |
|------|------|------|
| `REDIS_PASSWORD` | 空 | Redis 密码（留空则不启用密码） |
| `DB_USER` | `postgres` | PostgreSQL 用户名 |
| `DB_NAME` | `openclaw_biz` | PostgreSQL 数据库名 |
| `LOG_LEVEL` | `INFO` | 日志级别（DEBUG/INFO/WARNING/ERROR） |
| `APP_PORT` | `8000` | FastAPI 暴露端口 |
| `ADAPTER_API_TOKENS` | 空 | OpenClaw 网关访问 token（逗号分隔多 token） |

### 2.2 构建与启动（生产）

```bash
cd docker
docker compose --profile prod up -d --build
```

容器列表（`docker compose ps`）：

| 容器名 | 镜像 | 端口 | 说明 |
|--------|------|------|------|
| biz-tools-db | pgvector/pgvector:pg16 | 5432:5432 (dev 暴露，prod 不暴露） | PostgreSQL + pgvector 扩展 + 初始化 SQL |
| biz-tools-redis | redis:7.2-alpine | 6379:6379 | 缓存 + 任务队列 + 会话存储 |
| biz-tools-app | (自建) | 8000:8000 | FastAPI + Web Admin |

### 2.3 构建与启动（开发，代码热重载）

```bash
cd docker
docker compose --profile dev up -d --build
```

启动后修改本地代码，uvicorn `--reload` 自动重载应用代码变更。

### 2.4 首次数据库初始化

首次启动 docker 时，`init_db.sql` 自动执行，创建 4 张表 + 索引。如需手动重建：

```bash
cd docker
# 查看数据库内容
docker exec -it biz-tools-db psql -U postgres -d openclaw_biz

# 手动执行初始化 SQL（已自动挂载在启动时）
# select count(*) from business_opportunities;
# select count(*) from spider_raw_data;
# select count(*) from sales_tasks;
# select count(*) from system_logs;
```

### 2.5 验证部署验证清单

每次部署后请逐项验证：

```bash
# 1) 容器状态应为 healthy
docker compose --profile prod ps

# 2) 健康检查端点
curl http://localhost:8000/health
# 预期返回：{"code":0,"msg":"success","data":{"status":"OK"},...

# 3) 查看服务日志（确认无 ERROR 级别错误
docker compose logs app
```

### 2.6 生产加固建议

| 措施 | 命令 / 方法 |
|------|----------|
| **HTTPS / 反代 | 在 app 前方挂 Nginx / Traefik / Caddy，将 8000 端口仅本机监听 |
| **DB 备份 | `docker exec biz-tools-db pg_dump -U postgres openclaw_biz > backup_$(date +%Y%m%d).sql`（每周一次） |
| **数据卷备份** | `docker volume inspect biz-tools-pg_data` 查看存储路径，定期备份 |
| **WAF** | 在反代前启用 WAF，拦截常见攻击 |
| **防火墙** | 只对外暴露 80/443，8000 端口仅限内部访问 |
| **密钥管理 | 将 `.env` 中 `DB_ENCRYPTION_KEY` 与 `DB_PASSWORD` 写入安全管理（KMS / 环境变量） |
| **审计日志 | `docker exec biz-tools-app cat logs/openclaw_*.log` 日志轮转 |
| **监控告警** | 集成 Prometheus + Grafana，监控 Redis/DB 指标 |
| **定期升级** | 定期 `docker pull pgvector/pgvector:pg16` 与 `redis:7.2-alpine` 升级镜像 |

### 2.7 停止与清理

```bash
cd docker
# 停止服务（保留数据卷）
docker compose --profile prod down

# 停止并删除数据卷（⚠ 数据会丢失）
docker compose --profile prod down -v
```

---

## 3. Linux 原生部署（可选）

```bash
# 3.1 克隆项目
git clone https://github.com/justinpang/BizTools4Openclaw.git
cd BizTools4Openclaw

# 3.2 准备环境
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

# 3.3 环境变量
cp .env.example .env
# 编辑 .env，填入 DB_PASSWORD / DB_ENCRYPTION_KEY / WEB_ADMIN_PASSWORD_PLAIN

# 3.4 启动（PostgreSQL + Redis）
#   - 方法一：使用系统服务
#   - 方法二：Docker 仅启动 db + redis（推荐）
cd docker
docker compose up db redis -d
cd ..

# 3.5 数据库初始化
# 方法一：通过 SQL 脚本
psql -h localhost -U postgres -d openclaw_biz -f docker/init_db.sql
# 方法二：通过 Python ORM
python -c "
from infra.db_base import Base, engine
from infra import db_models
Base.metadata.create_all(engine)
"

# 3.6 uvicorn
# 前台运行（调试）：
uvicorn adapter.main:app --host 0.0.0.0 --port 8000 --reload

# 3.7 生产：使用 systemd（推荐）
```

### 3.7 systemd 服务单元示例

```ini
# /etc/systemd/system/biz-tools.service
[Unit]
Description=BizTools4Openclaw FastAPI application
After=network.target postgresql.service redis-server.service

[Service]
Type=simple
User=www-data
WorkingDirectory=/opt/BizTools4Openclaw
Environment="PATH=/opt/BizTools4Openclaw/.venv/bin"
# 关键：使用 .env 作为 systemd EnvironmentFile
EnvironmentFile=/opt/BizTools4Openclaw/.env
ExecStart=/opt/BizTools4Openclaw/.venv/bin/uvicorn \
    adapter.main:app --host 0.0.0.0 --port 8000 --workers 4
Restart=on-failure
RestartSec=5

[Install]
WantedBy=multi-user.target
```

启用并启动：

```bash
sudo systemctl daemon-reload
sudo systemctl enable biz-tools.service
sudo systemctl start biz-tools.service
sudo systemctl status biz-tools.service
# 查看日志
journalctl -u biz-tools.service -f
```

---

## 4. 常见问题与故障排查 FAQ

### 4.1 端口被占用

**问题：`Error starting userland proxy: listen tcp 0.0.0.0:8000: bind: address already in use`

解决：
```bash
# Windows 查找占用进程 PID
netstat -ano | findstr :8000
# 结束进程（替换 <PID>）
taskkill /PID <PID> /F
```
或在 `.env` 中修改 `APP_PORT=8001`

### 4.2 数据库连接失败

**问题**：`sqlalchemy.exc.OperationalError: (psycopg2.OperationalError: connection to server at "db" (172.20.0.2), port 5432 failed: FATAL: password authentication failed`

解决：
- 确认 `.env` 中 `DB_PASSWORD`、`DB_USER`、`DB_NAME`、`DB_HOST`（容器内应写 `db` 而非 `localhost`）。

### 4.3 Redis 连接失败

**问题**：`redis.exceptions.ConnectionError: Error 10061 connecting to redis:6379. 由于目标计算机积极拒绝，无法连接。`

解决：
- Docker 部署：检查 `docker compose ps` 中 `biz-tools-redis` 是否 healthy 状态是否为 healthy。
- 本地部署：检查 Redis 服务是否启动；或将 `REDIS_HOST` 设置为空字符串 → 自动降级为内存缓存（无持久化）。
- 若使用密码：需在 `.env` 中正确设置 `REDIS_PASSWORD`。

### 4.4 Web 管理后台登录失败

**问题**：登录后自动登出或 401 Unauthorized（4.5 初始化数据库表不存在

**问题**：`relation "business_opportunities" does not exist`

解决：
1) 确认 `docker/init_db.sql 已执行
2) 若在容器中查看表：`docker exec -it biz-tools-db psql -U postgres -d openclaw_biz
3) 手动执行：`docker exec biz-tools-db psql -U postgres -d openclaw_biz -f /docker-entrypoint-initdb.d/init.sql

### 4.6 Playwright 浏览器下载失败（中国大陆网络）

**问题**：`[WARN] playwright chromium 安装失败`

解决：
- 设置代理：`playwright install chromium --with-deps`
- 使用系统包：`apt-get install -y --no-install-recommends ttf-dejavu fonts-noto-cjk`
- 或使用国内镜像：`PLAYWRIGHT_DOWNLOAD_HOST=https://npmmirror.com/mirrors/playwright-builds/ playwright install chromium

### 4.7 容器构建失败（pgvector 镜像拉取慢

**问题**：`docker pull pgvector/pgvector:pg16` 超时

解决：
- 使用国内镜像源：

```bash
# 国内镜像加速（请以实际可用镜像为准）
docker pull docker.m.daocloud.io/pgvector/pgvector:pg16
docker tag docker.m.daocloud.io/pgvector/pgvector:pg16 pgvector/pgvector:pg16
```

### 4.8 Docker Hub 访问受限

**问题**：`error pulling image configuration: Get "https://registry-1.docker.io/v2/": dial tcp: lookup registry-1.docker.io: no such host`

解决：
1. 检查网络 DNS 指向：`ping registry-1.docker.io
2. 添加镜像源到 Docker daemon 配置：
```json
{"registry-mirrors": ["https://registry.docker-cn.com", "https://hub-mirror.c.163.com"]}
```
3. 重启 Docker 服务

### 4.9 启动后立即退出（code 状态退出）

**问题**：`biz-tools-app 不断 Exit 状态，`退出代码 1

解决：
1. 检查 `.env` 中必填字段是否完整
2. `docker compose logs app` 查看退出日志
3. 常见原因：`DB_PASSWORD` 未设置
4. `docker compose logs app app-dev` 查看应用退出码

### 4.10 容器健康检查失败

**问题**：`curl: (7) Failed to connect to localhost port 8000: Connection refused`

解决：
1. 等待 30-60 秒，容器启动需要时间
2. `docker compose logs app` 检查应用日志
3. 常见原因：端口冲突 / 应用启动失败 / 健康检查配置错误

### 4.11 敏感字段加密密钥变更后数据无法解密

**问题**：`ValueError: Invalid padding bytes.`

解决：
**⚠ 核心警告：`DB_ENCRYPTION_KEY` 一旦生产环境部署后**绝不可更改**，若需变更需手动解密再加密。请在首次部署时**妥善保存备份
