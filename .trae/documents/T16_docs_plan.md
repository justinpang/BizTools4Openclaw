# T16：一键部署脚本、容器化配置、环境初始化全流程工具

> 任务类型：纯部署工具开发（Dockerfile / Compose / PowerShell / SQL / DEPLOY_GUIDE.md）
> 前置任务：T01–T15 全部完成（代码、文档、规范均已就绪）
> 禁止修改：`README.md`、`DEVELOP_RULES.md`、`docs/TASK_LIST.md`、所有 `*.py` 业务代码

---

## 一、现状调研结论

### 1.1 已有文件与目录结构（已确认存在）

```
BizTools4Openclaw/
├── adapter/main.py            # FastAPI 入口（挂载 web_admin）
├── web_admin/main.py          # 后台挂载器
├── infra/db_base.py           # SQLAlchemy Base + Database 单例（PostgreSQL 默认，可降级 SQLite）
├── infra/db_models.py         # 4 张核心表（spider_raw_data / business_opportunities / sales_tasks / system_logs）
├── infra/redis_client.py      # Redis 客户端（连接池 + 断线降级内存缓存）
├── configs/settings.py        # 全部环境配置（DB/REDIS/WEB_ADMIN/SPIDER/CHANNEL/ALERT）
├── requirements.txt           # Python 依赖清单（fastapi/uvicorn/SQLAlchemy/psycopg2/pgvector/playwright/redis/APScheduler 等）
├── .env.example               # 配置模板（PROJECT_NAME/DEBUG/DB_*/REDIS_*/WEB_ADMIN_*/SPIDER_*/CUSTOMER_SEND_*/SALES_TASK_*/ADAPTER_*）
├── docker/                    # 空目录（T16 填充）
└── docs/                      # 现有 TASK_LIST.md + T02_INFRA_USAGE.md
```

### 1.2 关键依赖（用于 Dockerfile 分层设计）

| 层 | 包 | 备注 |
|---|---|---|
| 系统 APT | `libpq-dev`（psycopg2）、`playwright` 浏览器依赖（chromium/ffmpeg/fonts） | `playwright install-deps` 可自动安装 |
| Python PyPI | `fastapi`, `uvicorn[standard]`, `pydantic`, `pydantic-settings` | T01/T13 基础 |
| Python PyPI | `SQLAlchemy>=2.0`, `psycopg2-binary`, `pgvector`, `cryptography`, `alembic` | T04 数据库 |
| Python PyPI | `playwright`, `beautifulsoup4`, `lxml`, `httpx` | T05/T09 爬虫 |
| Python PyPI | `redis`, `APScheduler`, `python-dotenv`, `loguru` | T02/T03 基础设施 |
| Python PyPI | `pytest`, `pytest-asyncio`, `pytest-cov` | 单元测试 |
| Node（可选） | 仅在构建期用 `npx playwright install chromium` | T05 浏览器二进制 |

### 1.3 配置项清单（脚本 / Docker Compose 必须注入）

| 分组 | 关键变量 | 默认值 | 说明 |
|---|---|---|---|
| 项目基础 | `PROJECT_NAME`, `ENV`, `DEBUG`, `APP_HOST=0.0.0.0`, `APP_PORT=8000` | 默认即可 | 容器内 `APP_HOST=0.0.0.0` 必须开启 |
| 数据库 | `DB_HOST`, `DB_PORT=5432`, `DB_USER`, `DB_PASSWORD`, `DB_NAME`, `DB_ENCRYPTION_KEY` | 见 .env.example | `DB_ENCRYPTION_KEY` 必须 ≥ 16 字符，推荐 32 |
| Redis | `REDIS_HOST`, `REDIS_PORT=6379`, `REDIS_PASSWORD`, `REDIS_DB=0` | 见 .env.example | 可通过 `docker-compose` redis 服务注入 |
| Web 后台 | `WEB_ADMIN_USERNAME`, `WEB_ADMIN_PASSWORD_PLAIN`, `WEB_ADMIN_SESSION_TTL_SECONDS=28800` | `admin` / 需填写 | 明文密码会由 `web_admin/auth.py` 自动 bcrypt hash |
| OpenClaw 网关 | `ADAPTER_API_TOKENS`, `ADAPTER_BASE_URL` | `test-token-12345` | 多 token 用逗号分隔 |
| 调度/队列 | `SCHEDULER_ENABLED`, `QUEUE_*`, `CUSTOMER_SEND_*`, `SPIDER_*` | 默认即可 | 生产环境视需调整 |

### 1.4 启动方式

```bash
# 方式 A：模块方式（推荐，已在 T14 验证）
python -m adapter.main

# 方式 B：uvicorn（容器内使用，可用环境变量控制进程数）
uvicorn adapter.main:app --host 0.0.0.0 --port 8000 --workers 2
```

启动时 `web_admin/main.py` 的 `mount_on(app)` 被调用，自动挂载后台路由 + 静态文件。

`infra/db_base.py` 会在首次查询时懒加载 DB 连接；部署脚本需显式触发 `create_all()` 来建表。

---

## 二、本次新增文件清单（共 6 个）

| 序号 | 文件路径 | 用途 | 预计行数 |
|---|---|---|---|
| 1 | `docker/Dockerfile` | 应用镜像分层构建（base + deps + app） | ~80 |
| 2 | `docker/docker-compose.yml` | 编排 app / postgres / redis 三服务，dev/prod profile | ~120 |
| 3 | `docker/.dockerignore` | 镜像构建忽略清单（.venv / .git / logs / *.pyc 等） | ~20 |
| 4 | `docker/init_db.sql` | 数据库初始化 SQL（建表、索引、管理员账号） | ~150 |
| 5 | `start_win.ps1` | Windows 一键启动脚本（依赖检测、.env 生成、服务启动、日志查看、停止） | ~350 |
| 6 | `docs/DEPLOY_GUIDE.md` | 完整部署指南（Windows 本地 / Docker / Linux / 故障排查） | ~300 |

**总计：6 个文件，约 1020 行**

---

## 三、Dockerfile 分层构建规则

### 3.1 镜像基础选型（三阶段 build，减小最终镜像体积）

```
Stage 1: python:3.11-slim   # builder-base
  └─ apt 安装系统依赖（libpq-dev, curl, nodejs 最小化）
  └─ pip install --upgrade pip

Stage 2: python:3.11-slim   # builder-deps（编译依赖阶段）
  └─ 复制 requirements.txt
  └─ pip wheel --wheel-dir=/wheels -r requirements.txt  # 编译为 wheel 缓存

Stage 3: python:3.11-slim   # final（生产镜像）
  └─ apt 安装运行期依赖（libpq5, ca-certificates, ttf 字体）
  └─ 从 builder-deps 复制 /wheels，pip install（无网络）
  └─ playwright install chromium  # 浏览器二进制
  └─ 创建非 root 用户 appuser
  └─ 复制项目源码（已忽略 venv/logs/.git）
  └─ CMD ["uvicorn", "adapter.main:app", "--host", "0.0.0.0", "--port", "8000"]
```

### 3.2 关键安全点

- **非 root 用户**：最终镜像以 `appuser (uid=1000)` 运行
- **最小化 apt 包**：不安装 gcc/build-essential（编译依赖仅在 builder-deps 阶段，最终镜像不带）
- **敏感信息不入库**：`DB_PASSWORD`, `DB_ENCRYPTION_KEY`, `WEB_ADMIN_PASSWORD_PLAIN` 等仅通过容器运行期环境变量注入，**不写入 Dockerfile 或镜像层**
- **镜像体积目标**：最终镜像 ≤ 350 MB（python:3.11-slim ~120MB + pip 依赖 ~100MB + playwright chromium ~100MB）

### 3.3 Dockerfile 结构大纲

```dockerfile
# -------- Stage 1: 基础依赖层 --------
FROM python:3.11-slim AS builder-base
ENV DEBIAN_FRONTEND=noninteractive
RUN apt-get update && apt-get install -y --no-install-recommends \
    libpq-dev build-essential curl nodejs npm \
    && rm -rf /var/lib/apt/lists/*
RUN pip install --upgrade pip wheel setuptools

# -------- Stage 2: Python wheel 编译缓存 --------
FROM builder-base AS builder-deps
WORKDIR /wheels
COPY requirements.txt .
RUN pip wheel --wheel-dir=/wheels -r requirements.txt

# -------- Stage 3: 最终运行镜像 --------
FROM python:3.11-slim AS final
ENV DEBIAN_FRONTEND=noninteractive \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    APP_HOST=0.0.0.0 \
    APP_PORT=8000
# 运行期依赖：libpq5（psycopg2 运行期）、ca-certificates（HTTPS）、字体（playwright 渲染中文字）
RUN apt-get update && apt-get install -y --no-install-recommends \
    libpq5 ca-certificates ttf-dejavu fonts-noto-cjk \
    && rm -rf /var/lib/apt/lists/*
# 从 wheel 安装 Python 依赖（无需网络）
COPY --from=builder-deps /wheels /wheels
COPY requirements.txt /app/requirements.txt
WORKDIR /app
RUN pip install --no-index --find-links=/wheels -r requirements.txt \
    && rm -rf /wheels /root/.cache
# 安装 playwright 浏览器（chromium 足够，避免下载所有浏览器）
RUN python -m playwright install chromium --with-deps 2>/dev/null \
    || true  # 失败不阻塞（无爬虫需求时可跳过）
# 非 root 用户
RUN useradd -m -u 1000 appuser && chown -R appuser:appuser /app
COPY --chown=appuser:appuser . /app/
USER appuser
# 健康检查
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD curl -fsS http://localhost:8000/health || exit 1
# 启动
EXPOSE 8000
CMD ["uvicorn", "adapter.main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "2"]
```

---

## 四、docker-compose.yml 多服务编排逻辑

### 4.1 三服务架构

```
            ┌──────────────────────────────────────────┐
            │              biz-tools                    │
            │   FastAPI + Web Admin (port 8000)        │
            │   依赖：db, redis                          │
            └────────┬────────────────────┬────────────┘
                     │                    │
           depends_on: db            depends_on: redis
                     │                    │
                     ▼                    ▼
           ┌────────────────┐   ┌────────────────┐
           │       db       │   │     redis      │
           │  PostgreSQL 16 │   │  Redis 7.2     │
           │ + pgvector     │   │ + 持久化 AOF   │
           │ + 初始化 SQL    │   │ + 密码可选     │
           │   /docker-entrypoint-initdb.d/       │
           │ volume: pg_data│   │ volume: redis_data│
           └────────────────┘   └────────────────┘
```

### 4.2 环境变量与 `.env` 文件

Compose 会自动读取项目根目录的 `.env` 作为环境变量源。**敏感项必须显式覆盖**：

- `DB_HOST=db`（Docker Compose 服务名，自动 DNS 解析）
- `DB_PASSWORD=<生成的强随机密码>`
- `DB_ENCRYPTION_KEY=<32 字符随机字符串>`
- `REDIS_HOST=redis`（同理由）
- `WEB_ADMIN_PASSWORD_PLAIN=<管理员密码>`
- `ADAPTER_API_TOKENS=<为 OpenClaw 生成的 token>`
- 其余沿用 `.env.example` 默认值

### 4.3 Profile 机制：区分 dev / prod

- `docker compose --profile dev up`
  - `app` → `command: uvicorn adapter.main:app --host 0.0.0.0 --port 8000 --reload --workers 1`
  - 挂载 `./:/app` 代码 volume → 代码变更热重载
  - `LOG_LEVEL=DEBUG`
  - `db` 暴露 `5432:5432` 到宿主
  - `redis` 暴露 `6379:6379` 到宿主
- `docker compose --profile prod up`
  - `app` → `command: uvicorn adapter.main:app --host 0.0.0.0 --port 8000 --workers 4`
  - 仅读镜像内代码（不可变部署）
  - `LOG_LEVEL=INFO`
  - `db`, `redis` 不暴露端口（仅容器间网络访问）
  - `restart: unless-stopped`

### 4.4 docker-compose.yml 大纲

```yaml
version: "3.9"
name: biz-tools
services:
  db:
    image: pgvector/pgvector:pg16
    environment:
      POSTGRES_USER: ${DB_USER:-postgres}
      POSTGRES_PASSWORD: ${DB_PASSWORD:?请在 .env 中配置 DB_PASSWORD}
      POSTGRES_DB: ${DB_NAME:-openclaw_biz}
    volumes:
      - pg_data:/var/lib/postgresql/data
      - ./docker/init_db.sql:/docker-entrypoint-initdb.d/init.sql:ro
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U postgres -d ${DB_NAME:-openclaw_biz}"]
      interval: 10s
      timeout: 5s
      retries: 10
    profiles:
      - dev
      - prod

  redis:
    image: redis:7.2-alpine
    command: redis-server --save 900 1 --save 300 10 --appendonly yes ${REDIS_PASSWORD:+--requirepass $REDIS_PASSWORD}
    volumes:
      - redis_data:/data
    healthcheck:
      test: ["CMD", "redis-cli", ${REDIS_PASSWORD:+-a $REDIS_PASSWORD} ping"]
      interval: 5s
      timeout: 3s
      retries: 5
    profiles:
      - dev
      - prod

  app:
    build:
      context: ..
      dockerfile: docker/Dockerfile
    env_file:
      - ../.env
    environment:
      DB_HOST: db
      REDIS_HOST: redis
      APP_HOST: 0.0.0.0
    ports:
      - "${APP_PORT:-8000}:8000"
    depends_on:
      db: { condition: service_healthy }
      redis: { condition: service_healthy }
    restart: unless-stopped
    profiles:
      - prod
    # dev profile 额外挂载本地代码
    command: >-
      uvicorn adapter.main:app --host 0.0.0.0 --port 8000 --workers 4

  # dev 专用的 app 配置（通过 docker compose --profile dev up 启动）
  app-dev:
    extends:
      file: docker-compose.yml
      service: app
    volumes:
      - ../:/app
    environment:
      LOG_LEVEL: DEBUG
      DEBUG: "true"
    command: uvicorn adapter.main:app --host 0.0.0.0 --port 8000 --reload --workers 1
    profiles:
      - dev

volumes:
  pg_data:
  redis_data:
```

---

## 五、Windows PowerShell 一键脚本 `start_win.ps1`

### 5.1 脚本执行流程（交互 CLI）

```
用户执行： .\start_win.ps1
            │
       ┌────┴──────────────────┐
       ▼                       ▼
【步骤 1：环境预检】        【步骤 2：自动生成 .env】
  · python --version           · 检测 .env 是否存在
  · docker version             · 不存在则从 .env.example 复制
  · redis-cli ping（可选）      · 提示用户填入敏感密码
  · 端口占用检测 5432/6379/8000
                              【步骤 3：创建虚拟环境 .venv & 安装依赖】
                                · python -m venv .venv
                                · pip install -r requirements.txt
                                · python -m playwright install chromium
                              【步骤 4：启动模式选择】
                                (A) Docker Compose（推荐）
                                (B) 本地进程（FastAPI 直启）
                                (C) 仅启动 DB + Redis（外部应用连接）
                              【步骤 5：数据库初始化】
                                · docker exec db ... psql -f init_db.sql
                                · 或本地: python -c "from infra.db_base import database; database.create_all()"
                              【步骤 6：健康检查 / 显示访问地址】
                                · curl http://localhost:8000/health
                                · 打印: Web 管理后台 http://localhost:8000/admin
```

### 5.2 脚本支持命令（parameter-based）

```powershell
# 完整部署（交互式，推荐首次使用）
.\start_win.ps1 -Mode interactive

# Docker Compose 一键启动（生产模式）
.\start_win.ps1 -Mode docker-prod

# Docker Compose 一键启动（开发模式，热重载）
.\start_win.ps1 -Mode docker-dev

# 本地进程启动（Windows 原生，无 Docker）
.\start_win.ps1 -Mode local

# 停止所有服务（无论哪种模式）
.\start_win.ps1 -Stop

# 查看服务日志
.\start_win.ps1 -Logs

# 清理（删除 .venv / docker volumes）
.\start_win.ps1 -Clean
```

### 5.3 脚本设计要点

- **彩色日志**：`Write-Host -ForegroundColor Green/Yellow/Red`
- **幂等**：已创建虚拟环境 / 已生成 .env / 已运行 docker 时跳过重复操作
- **异常捕获**：try/catch 包裹关键段，失败时打印**清晰的排查路径**（链接到 `docs/DEPLOY_GUIDE.md` 的对应章节）
- **端口占用提示**：检测 8000/5432/6379 被占用时，打印 `netstat -ano | findstr :<port>` 命令帮助用户找到占用进程
- **数据库连接失败**：自动检查 `DB_HOST` / `DB_PASSWORD` / `DB_ENCRYPTION_KEY` 的存在性
- **Redis 未启动降级**：显式提示 "Redis 不可达，将降级为内存缓存（异步任务/会话无法跨进程共享）"
- **不修改业务代码**：脚本仅读取 .env 与项目源码，不改任何 `.py`

### 5.4 PowerShell 脚本大纲（部分关键片段）

```powershell
# ===== 顶部：参数定义 =====
param(
    [ValidateSet("interactive","docker-prod","docker-dev","local","stop","logs","clean")]
    [string]$Mode = "interactive"
)

# ===== 彩色日志工具函数 =====
function Write-Info($msg) { Write-Host "[INFO ] $msg" -ForegroundColor Cyan }
function Write-Ok  ($msg) { Write-Host "[OK   ] $msg" -ForegroundColor Green }
function Write-Warn($msg) { Write-Host "[WARN ] $msg" -ForegroundColor Yellow }
function Write-Err ($msg) { Write-Host "[ERROR] $msg" -ForegroundColor Red }
function Write-Tip ($msg) { Write-Host "[TIP  ] $msg" -ForegroundColor Magenta }

# ===== 关键：检测 .env，不存在则从 .env.example 复制 =====
function Ensure-EnvFile {
    if (-not (Test-Path .\.env.example)) { Write-Err "找不到 .env.example，项目目录不正确"; exit 1 }
    if (-not (Test-Path .\.env)) {
        Copy-Item .\.env.example .\.env
        Write-Ok "已从 .env.example 生成 .env，建议修改以下字段："
        Write-Tip "  DB_PASSWORD, DB_ENCRYPTION_KEY(≥32字符), WEB_ADMIN_PASSWORD_PLAIN, ADAPTER_API_TOKENS"
    } else { Write-Ok ".env 已存在，跳过生成" }
}

# ===== 关键：Docker Compose 启动 =====
function Start-DockerCompose($profile) {
    docker compose --profile $profile -f docker\docker-compose.yml up -d --build
    Write-Ok "等待数据库与 Redis 就绪..."
    # 健康检查轮询
    for ($i=1; $i -le 30; $i++) {
        $status = (docker compose ps --format json | ConvertFrom-Json | Where-Object {$_.Name -like "*db*"}).State
        if ($status -eq "running") { break }
        Start-Sleep -Seconds 2
    }
    # 健康检查：curl http://localhost:8000/health
    Write-Ok "部署完成，访问："
    Write-Tip "  · Web 管理后台: http://localhost:8000/admin"
    Write-Tip "  · API 文档:     http://localhost:8000/docs"
    Write-Tip "  · 健康检查:     http://localhost:8000/health"
}
```

---

## 六、数据库初始化 SQL `docker/init_db.sql`

### 6.1 设计原则

- **纯 DDL + 少量初始化数据**：不包含业务逻辑（业务逻辑在 Python 代码）
- **兼容 SQLAlchemy Base.metadata.create_all()**：脚本内容与 `infra/db_models.py` 完全一致，两套方法任选其一均可
- **包含 pgvector 扩展初始化**：`CREATE EXTENSION IF NOT EXISTS vector`
- **包含敏感字段加密密钥占位校验**：检测 `DB_ENCRYPTION_KEY` 是否已配置（通过 SQL 变量打印提示）
- **幂等**：所有 `CREATE TABLE` 使用 `CREATE TABLE IF NOT EXISTS`；所有 `INSERT` 使用 `ON CONFLICT DO NOTHING`

### 6.2 SQL 结构大纲

```sql
-- ===== 1. 扩展 & 基础设置 =====
SET client_encoding = 'UTF8';
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";
CREATE EXTENSION IF NOT EXISTS vector;

-- ===== 2. 核心数据表（与 infra/db_models.py 保持一致） =====
CREATE TABLE IF NOT EXISTS spider_raw_data (
    id BIGSERIAL PRIMARY KEY,
    tenant_id VARCHAR(255) NOT NULL DEFAULT 'default',
    is_archived BOOLEAN NOT NULL DEFAULT FALSE,
    created_at TIMESTAMP NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMP NOT NULL DEFAULT NOW(),
    spider_name VARCHAR(128) NOT NULL,
    source_url VARCHAR(1024) NOT NULL,
    source_id VARCHAR(256),
    raw_payload JSONB NOT NULL DEFAULT '{}',
    raw_text TEXT,
    fetch_status SMALLINT NOT NULL DEFAULT 0,
    fetch_error VARCHAR(512),
    captured_at TIMESTAMP NOT NULL DEFAULT NOW(),
    source_country CHAR(2)
);
CREATE INDEX IF NOT EXISTS idx_spider_raw_source_id ON spider_raw_data(tenant_id, spider_name, source_id);
CREATE INDEX IF NOT EXISTS idx_spider_raw_captured   ON spider_raw_data(captured_at);
CREATE INDEX IF NOT EXISTS idx_spider_raw_archived_name ON spider_raw_data(is_archived, spider_name);

-- （同结构建表：business_opportunities / sales_tasks / system_logs）
-- 注意：
--   · contact_phone / contact_email / contact_wechat 为 SensitiveString
--     （应用层加密，数据库仅存 ciphertext；此处以 VARCHAR(256) 普通存储）
--   · industry / city / status / priority 均建立索引，支持后台列表分页过滤

-- ===== 3. 初始化管理员账号（供 web_admin 登录使用） =====
-- web_admin 的账号来自 .env 的 WEB_ADMIN_USERNAME + WEB_ADMIN_PASSWORD_PLAIN
-- （在 adapter/main.py 启动时由 web_admin/auth.py 自动生成 bcrypt hash 并存入内存 + Redis）
-- 无需数据库表，但此 SQL 提供一条 system_logs 初始记录用于校验部署成功

INSERT INTO system_logs (tenant_id, log_level, log_type, actor, target_resource, message, extra, ip_address, duration_ms)
VALUES ('default', 'info', 'system', 'system', 'deployment', 'T16 docker init_db.sql 初始化完成', '{}', '127.0.0.1', 0)
ON CONFLICT DO NOTHING;

-- ===== 4. 权限收尾 =====
GRANT ALL PRIVILEGES ON ALL TABLES IN SCHEMA public TO CURRENT_USER;
GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO CURRENT_USER;
```

---

## 七、docs/DEPLOY_GUIDE.md 部署说明文档

### 7.1 目录结构

```
# BizTools4Openclaw 部署指南

## 0. 前置条件检查清单
## 1. Windows 本地单机部署（最推荐 · 一键脚本）
##    1.1 下载与环境准备
##    1.2 执行 start_win.ps1
##    1.3 访问 Web 管理后台
## 2. Docker 容器部署（生产推荐）
##    2.1 Docker 安装
##    2.2 配置 .env
##    2.3 docker compose up
##    2.4 首次部署数据库初始化
##    2.5 验证与生产加固建议
## 3. Linux 原生部署（可选）
##    3.1 Python + Redis + PostgreSQL
##    3.2 systemd 服务配置
## 4. 常见问题与故障排查（FAQ）
##    4.1 端口被占用
##    4.2 数据库连接失败
##    4.3 Redis 连不上
##    4.4 Web 管理后台登录失败
##    4.5 容器构建失败（playwright 依赖网络）
##    4.6 爬虫抓取失败（代理 / UA / robots）
## 5. 生产环境加固建议
##    5.1 使用强随机密码生成 .env 中所有密钥
##    5.2 HTTPS（推荐 Caddy / Traefik / Nginx 反代）
##    5.3 数据库备份策略（每日 pg_dump）
##    5.4 日志轮转（项目自带 loguru 轮转）
## 6. 升级与回滚
## 7. 关键配置项速查表（与 configs/settings.py 保持一致）
```

### 7.2 关键章节要点

- **1. Windows 本地部署**：引导用户执行 `Set-ExecutionPolicy RemoteSigned -Scope CurrentUser`，然后 `.\start_win.ps1`
- **2. Docker 部署**：引导用户 `cp .env.example .env` → 填强密码 → `docker compose --profile prod up -d --build`
- **4. FAQ**：每条问题给出**具体命令**与**预期输出**，便于用户自助排查
- **7. 配置项速查表**：以表格形式汇总所有 `.env` 字段（字段名 / 默认值 / 是否必须 / 说明），方便用户对照配置
- 文档所有命令**经过实测**，给出真实返回示例（如 `curl http://localhost:8000/health` 返回 `{"status":"OK","version":"T13-v1.0",...}`）

---

## 八、分步执行开发流程

### 阶段 A：文件编写（按依赖顺序）

| 序号 | 文件 | 依赖 | 内容要点 |
|---|---|---|---|
| A-1 | `docker/.dockerignore` | 无 | 写好后供其他 docker 文件使用 |
| A-2 | `docker/init_db.sql` | `infra/db_models.py` 表结构 | 按 ORM 模型定义反写 DDL |
| A-3 | `docker/Dockerfile` | `requirements.txt` | 三阶段构建，最小化最终镜像 |
| A-4 | `docker/docker-compose.yml` | `Dockerfile`, `init_db.sql`, `configs/settings.py` | 三服务编排 + profile 机制 |
| A-5 | `start_win.ps1` | 所有 docker 文件 + `.env.example` | 交互式参数化 Windows 一键脚本 |
| A-6 | `docs/DEPLOY_GUIDE.md` | 以上全部 | 与脚本/配置完全同步的中文说明 |

### 阶段 B：自测与验证（在 Windows 本地环境）

| 步骤 | 操作 | 验证点 |
|---|---|---|
| B-1 | `git status --short` | 确认仅新增 6 个文件，无其他业务文件变动 |
| B-2 | `cp .env.example .env` | （手动）填写 `DB_PASSWORD`, `DB_ENCRYPTION_KEY=32char`, `WEB_ADMIN_PASSWORD_PLAIN` |
| B-3 | `.\start_win.ps1 -Mode local` | 虚拟环境创建、依赖安装、服务启动成功，访问 `http://localhost:8000/admin` |
| B-4 | 执行 `curl http://localhost:8000/health` | 返回 `status: OK` |
| B-5 | `.\start_win.ps1 -Stop` | 本地进程正常停止 |
| B-6 | `.\start_win.ps1 -Mode docker-dev` | Docker 三容器可启动，`docker compose ps` 显示 `running` |
| B-7 | 在容器模式下验证 | 同 B-3, B-4 流程通过；`docker exec db psql ...` 可看到表已创建 |
| B-8 | `.\start_win.ps1 -Clean` | 可正确清理本地 .venv + docker volumes |
| B-9 | 文档一致性检查 | `docs/DEPLOY_GUIDE.md` 中所有命令均可成功执行、所有路径真实存在 |

### 阶段 C：提交与 push（与 T15 相同流程）

```bash
git add docker/Dockerfile docker/docker-compose.yml docker/.dockerignore docker/init_db.sql
git add start_win.ps1 docs/DEPLOY_GUIDE.md
git commit -m "feat(T16): 一键部署脚本、容器化配置、环境初始化全流程工具
- docker/Dockerfile: 三阶段分层构建（builder-base → builder-deps → final），最小化镜像
- docker/docker-compose.yml: app + PostgreSQL + Redis 三服务编排，支持 dev/prod profile
- docker/.dockerignore: 构建期忽略 .venv/logs/.git/__pycache__ 等
- docker/init_db.sql: spider_raw_data/business_opportunities/sales_tasks/system_logs 四表 DDL
- start_win.ps1: Windows 一键脚本，支持 docker-prod/dev/local/stop/logs/clean 六种模式
- docs/DEPLOY_GUIDE.md: Windows/Docker/Linux 三平台部署指南 + 完整故障排查 FAQ"
git push origin main
```

---

## 九、风险与规避

| 风险 | 影响 | 规避措施 |
|---|---|---|
| Docker Hub 访问受限 / `docker pull` 失败 | 镜像构建超时 / 失败 | 在 DEPLOY_GUIDE.md 提供 `--profile local` 无需 Docker 的备选方案 |
| Playwright 浏览器依赖下载失败（中国大陆网络） | `playwright install chromium` 失败 | Dockerfile 中该命令添加 `|| true`，并打印提示；启动后如无需爬虫可跳过 |
| PostgreSQL `pgvector/pgvector:pg16` 镜像拉取慢 | 首次部署耗时久 | DEPLOY_GUIDE.md 提供国内镜像加速建议（如 `docker.m.daocloud.io/pgvector/pgvector:pg16`） |
| `.env` 中密码未填导致启动失败 | 容器无限重启 | docker-compose.yml 使用 `${DB_PASSWORD:?}` 强制校验，未填直接报错退出 |
| `DB_ENCRYPTION_KEY` 变更导致历史数据不可解密 | 敏感字段解密失败 | DEPLOY_GUIDE.md 强调：加密密钥一旦生产部署不可变更 |
| Windows PowerShell 执行策略阻止脚本运行 | 用户无法运行 start_win.ps1 | 脚本首行提示用户执行 `Set-ExecutionPolicy RemoteSigned -Scope CurrentUser` |
| 端口 8000/5432/6379 被宿主机服务占用 | Docker 端口冲突 | 脚本自动检测并提示用户释放端口 |

---

## 十、验证清单（开发完成后逐条打勾）

- [ ] `docker/Dockerfile` 存在且内容完整（三阶段）
- [ ] `docker/docker-compose.yml` 存在且包含 `db` / `redis` / `app` / `app-dev`
- [ ] `docker/.dockerignore` 存在且包含 `.venv` / `.git` / `logs` / `__pycache__` / `*.pyc`
- [ ] `docker/init_db.sql` 包含 4 张核心表 DDL 与索引
- [ ] `start_win.ps1` 支持 `interactive / docker-prod / docker-dev / local / stop / logs / clean` 七种模式
- [ ] `docs/DEPLOY_GUIDE.md` 完整覆盖 Windows / Docker / Linux 三平台
- [ ] 所有 `.py` 业务代码文件未被修改（通过 `git diff --name-only | Select-String -Pattern "\.py$"` 验证为空）
- [ ] README.md / DEVELOP_RULES.md / docs/TASK_LIST.md 未被修改
- [ ] Windows 本地 `.\start_win.ps1 -Mode local` 可成功启动并访问 `/admin`
- [ ] Windows 本地 `.\start_win.ps1 -Mode docker-dev` 可成功启动三容器并访问 `/admin`
- [ ] `curl http://localhost:8000/health` 返回 `status: OK`
- [ ] `docs/DEPLOY_GUIDE.md` 中所有命令 / 路径与实际文件一致
- [ ] `docker/init_db.sql` 表结构与 `infra/db_models.py` 完全一致（字段名/类型/索引）
- [ ] 所有新文件均为 UTF-8 编码、LF 换行符
- [ ] `docker compose --profile prod up -d --build` 在纯净环境首次部署可成功
- [ ] `HEALTHCHECK` 通过（容器 `health: healthy`）
