# BizTools4Openclaw — Docker 部署指南

> 支持 **3 种部署模式**，一行命令跑起来。  
> 本项目是一个带 **Web 管理后台 + OpenClaw 适配网关** 的商业智能工具平台。

## 镜像源说明

> 默认使用 DaoCloud 国内加速镜像源：`docker.m.daocloud.io`
> 
> - `docker.m.daocloud.io/library/python:3.11-slim`（应用基础镜像）
> - `docker.m.daocloud.io/pgvector/pgvector:pg16`（PostgreSQL + 向量扩展）
> - `docker.m.daocloud.io/library/redis:7.2-alpine`（Redis 缓存）
>
> 如需切换回 Docker Hub，把 `docker.m.daocloud.io/library/` 和 `docker.m.daocloud.io/` 前缀去掉即可。

## 项目结构

```
/
├── adapter/               # OpenClaw 适配网关（FastAPI）
│   └── main.py           # → 应用入口（默认挂载到 /api/v1 + /docs）
├── web_admin/            # Web 管理后台（页面 + /admin/api/*）
├── business/             # 业务模块（商机触达、爬虫、清洗、销售调度）
├── infra/                # 基础设施（数据库、Redis、日志、异常处理）
├── configs/settings.py  # 全局配置（所有环境变量都在这里）
├── requirements.txt      # Python 依赖清单
└── docker/               # ← 本指南所在目录
    ├── Dockerfile         # 应用镜像（python:3.11-slim 基础）
    ├── docker-compose.yml # 三模式编排
    ├── init_db.sql        # PostgreSQL 初始化脚本（dev/prod 用）
    ├── _quick_check.py    # 本地快速验证脚本
    └── verify_deploy.py  # 端点验证脚本
```

## 模式对比

| 模式 | 服务组成 | 适用场景 | 命令 |
|------|---------|---------|------|
| **lite** | 仅 app 容器（SQLite + 内存 Redis stub） | 演示 / 功能测试 / CI | `docker compose --profile lite up -d --build` |
| **dev** | app + db(postgres+pgvector) + redis | 开发调试 | `docker compose --profile dev up -d --build` |
| **prod** | app + db + redis（更严格资源配置） | 生产部署 | `docker compose --profile prod up -d --build` |

## 快速启动（推荐，无需安装 PostgreSQL/Redis）

```bash
# 【重要】请在**项目根目录**下执行（而不是 docker/ 子目录）
cd BizTools4Openclaw
# 如果之前没有 .env，请复制一份：
cp .env.docker .env
# 然后启动（-f 指定 compose 文件位置
docker compose -f docker/docker-compose.yml --profile lite up -d --build
```

### 如果您已经在 `docker/` 目录下，也可以这样运行（需显式指定 env-file）：

```bash
cd docker
docker compose --env-file ../.env --profile lite up -d --build
```

然后打开浏览器访问：
- **主应用 / 健康检查**: http://localhost:8000/health
- **API 文档**: http://localhost:8000/docs
- **管理后台**: http://localhost:8000/admin
- **登录页面**: http://localhost:8000/admin/login

### 验证启动是否成功

容器启动后，可通过以下方式验证：

```bash
# 1. 检查容器状态
docker compose ps

# 2. 健康检查（HTTP 200 = 正常）
curl http://localhost:8000/health
# 期望输出: {"status":"OK","version":"T13-v1.0",...}

# 3. 查看应用日志
docker compose logs app-lite -f   # lite 模式
# 或
docker compose logs app -f          # prod 模式
```

### 默认账号（lite / dev / prod 通用）

| 项 | 值 |
|----|----|
| 用户名 | `admin` |
| 密码 | `admin123` |
| 适配器 API Token | `test-token-12345` |

> ⚠️ **生产部署前请务必修改** `.env` 中的 `WEB_ADMIN_PASSWORD_PLAIN` 和 `DB_ENCRYPTION_KEY`。

## 环境变量详解

所有可用的环境变量都定义在 `configs/settings.py` 中。以下是最常用的：

### 数据库

| 变量 | 默认 | 说明 |
|------|------|------|
| `DB_BACKEND` | `postgres` | **关键**: 设为 `sqlite` 则完全不需要数据库服务 |
| `DB_HOST` | `127.0.0.1` | PostgreSQL 主机（dev/prod 模式下应为 `db`） |
| `DB_PORT` | `5432` | PostgreSQL 端口 |
| `DB_USER` | `postgres` | 数据库用户名 |
| `DB_PASSWORD` | - | **必须**配置（dev/prod 模式） |
| `DB_NAME` | `openclaw_biz` | 数据库名 |
| `DB_SQLITE_PATH` | 空 | SQLite 文件路径（留空 = 内存数据库） |
| `DB_SQLITE_CHECK_SAME_THREAD` | `false` | SQLite 线程安全设置 |
| `DB_ENCRYPTION_KEY` | - | **必须**≥16 字符，用于敏感字段加密 |
| `DB_ARCHIVE_DAYS` | `90` | 数据冷热分离天数 |
| `DB_ARCHIVE_HOT_THRESHOLD` | `1000` | 高价值商机保留阈值 |

### 缓存 / 异步队列

| 变量 | 默认 | 说明 |
|------|------|------|
| `QUEUE_REDIS_HOST` | `127.0.0.1` | Redis 主机（dev/prod 模式下应为 `redis`） |
| `QUEUE_REDIS_PORT` | `6379` | Redis 端口 |
| `QUEUE_REDIS_DB` | `1` | Redis 数据库索引 |
| `REDIS_HOST` | `127.0.0.1` | 会话 Redis（同队列服务器） |
| `REDIS_PORT` | `6379` | 会话 Redis 端口 |

### 应用 / 安全

| 变量 | 默认 | 说明 |
|------|------|------|
| `APP_HOST` | `0.0.0.0` | 绑定地址（容器内） |
| `APP_PORT` | `8000` | 端口（容器内） |
| `LOG_LEVEL` | `INFO` | 日志级别：DEBUG/INFO/WARNING/ERROR |
| `ENV` | `dev` | 环境标签：dev/test/prod |
| `DEBUG` | `true` | 是否开启调试模式 |
| `WEB_ADMIN_ENABLED` | `true` | 是否启用管理后台 |
| `WEB_ADMIN_USERNAME` | `admin` | 后台登录用户名 |
| `WEB_ADMIN_PASSWORD_PLAIN` | - | 后台登录密码（明文，应用会自动 hash） |
| `WEB_ADMIN_SESSION_TTL_SECONDS` | `28800` | 会话有效期（秒），默认 8 小时 |
| `ADAPTER_API_TOKENS` | `test-token-12345` | 允许的 Bearer Token（逗号分隔） |
| `ADAPTER_BASE_URL` | `http://localhost:8000` | 外部访问地址，用于回调 |
| `SECRET_KEY` | - | 可选：额外的签名密钥 |

### 业务相关（可选）

| 变量 | 说明 |
|------|------|
| `OPENCLAW_GATEWAY_URL` | OpenClaw 网关地址（留空则不调用） |
| `OPENCLAW_CALLBACK_URL` | 任务完成回调地址 |
| `PROXY_ENABLED` | 爬虫是否使用代理 |
| `PROXY_HTTP` / `PROXY_HTTPS` | 代理地址 |
| `CRAWLER_UA` | 爬虫 User-Agent |
| `CUSTOMER_SEND_EMAIL_ENABLED` | 邮件渠道开关 |
| `ALERT_ENABLED` | 告警开关 |

### 完整的配置参考

见项目根目录的 `.env.docker` 文件，它包含了全量环境变量和默认值。

## 详细启动步骤

### 模式 1：lite 模式（推荐用于快速验证）

**不需要任何外部依赖** — 数据库自动使用内置 SQLite，Redis 自动使用进程内内存 stub。

```bash
cd BizTools4Openclaw
cp .env.docker .env        # 复制一份默认配置
cd docker
docker compose --profile lite up -d --build
# 等待 30 秒左右，然后访问 http://localhost:8000/health
```

### 模式 2：dev 模式（推荐开发人员）

同时启动 PostgreSQL + Redis + app：

```bash
cd BizTools4Openclaw
cp .env.docker .env
# 编辑 .env，将 DB_PASSWORD 设置为安全密码
cd docker
docker compose --profile dev up -d --build
```

dev 模式特点：
- `db` (PostgreSQL 16 + pgvector) 端口映射到 `5432`，可直接用 DBeaver 等连接
- `redis` 端口映射到 `6379`，可 `redis-cli` 调试
- `app-dev` 容器中可查看完整调试日志

### 模式 3：prod 模式（生产部署）

```bash
cd BizTools4Openclaw
cp .env.docker .env
# 必须修改：DB_PASSWORD / DB_ENCRYPTION_KEY / WEB_ADMIN_PASSWORD_PLAIN
#           / ADAPTER_API_TOKENS
cd docker
docker compose --profile prod up -d --build
```

prod 模式特点：
- **不再暴露** db/redis 的端口到宿主，仅限容器间通信
- 使用 `restart: unless-stopped` 自动重启
- 建议搭配 nginx/caddy 等反向代理做 TLS

## 常见操作

### 查看日志

```bash
# 指定模式查看日志
docker compose --profile lite logs -f app-lite   # 实时跟踪
docker compose --profile prod logs --tail 100 app # 最近 100 行
```

### 进入容器

```bash
# 进入 app-lite 容器，交互式调试
docker exec -it biz-tools-app-lite bash
# 或直接进入 Python 解释器
docker exec -it biz-tools-app-lite python
```

### 停止 / 清理

```bash
# 停止当前模式的所有服务
docker compose --profile lite down
# 同时清理数据卷（⚠️ 会丢失数据库/Redis 数据）
docker compose --profile lite down -v
```

### 查看容器状态 & 资源使用

```bash
docker compose ps
docker stats
```

## 本地测试（在容器外直接跑 Python）

如果不想启动 Docker，也可以直接在本地运行：

```bash
cd BizTools4Openclaw
cp .env.docker .env
# 让它走 SQLite + 内存 stub：
export DB_BACKEND=sqlite
export DB_SQLITE_PATH=
export QUEUE_REDIS_HOST=127.0.0.1
# 安装依赖
pip install -r requirements.txt
# 运行
uvicorn adapter.main:app --host 0.0.0.0 --port 8000 --reload
```

## 健康检查端点

| URL | 方法 | 说明 |
|-----|------|------|
| `/health` | GET | 核心健康检查，返回 `{status: "OK", version: "..."}` |
| `/docs` | GET | Swagger/OpenAPI 自动文档 |
| `/redoc` | GET | ReDoc 文档 |
| `/admin` | GET | 管理后台入口 |
| `/api/v1/info` | GET | 网关信息 |
| `/api/v1/tools` | GET | 工具清单（需 Bearer Token） |
| `/api/v1/tasks/enqueue` | POST | 创建任务（需 Bearer Token） |

## API 认证

适配器 API 必须在请求头中携带 `Authorization: Bearer <TOKEN>`，其中 TOKEN 必须是 `ADAPTER_API_TOKENS` 中已配置的值之一（逗号分隔）。

示例：
```bash
curl -H "Authorization: Bearer test-token-12345" \
     http://localhost:8000/api/v1/tools
```

## 关键实现细节

### SQLite 自动降级

`infra/db_base.py` 中的 `Database.ensure_connected()` 会：
1. 首先检查 `settings.db.DB_BACKEND`
   - 如果是 `sqlite`，直接构造 SQLite 引擎
2. 否则尝试连接 PostgreSQL
3. 如果 PostgreSQL 不可达（超时约 3 秒），自动降级到 SQLite
4. 任何模式下，ORM 表类会通过 `Base.metadata.create_all()` 自动建表

这样可以确保：
- lite 模式：零依赖启动
- dev/prod 模式：数据库一旦断线，应用仍能应急运行

### Redis 自动降级到内存 stub

`infra/redis_client.py` 中的 `RedisClient._ensure_connected()`：
1. 先尝试连接配置的 Redis 服务器
2. 如 `redis.exceptions.ConnectionError` 或超时，返回 `InMemoryRedisStub`
3. `InMemoryRedisStub` 实现了 `get/set/delete/exists/incr/hset/hget/lpush/rpop/brpop/ping`

这样：
- 即使没有 Redis，管理后台登录 / 会话 / 队列也能正常工作
- 内存数据不持久化 — 适合演示 / 测试场景

## 故障排查

**1. `docker compose up` 后立即退出**
- 检查 `.env` 是否存在于项目根目录（docker-compose.yml 中有 `env_file: ../.env`）
- 查看日志：`docker compose logs app-lite -f`

**2. 浏览器访问 http://localhost:8000 报错 404**
- 确认容器已启动：`docker compose ps`
- 确认使用的是正确的 URL（不是 `/`），应访问 `/health`、`/docs` 或 `/admin`

**3. 数据库连接错误（dev/prod 模式）**
- 确认 `db` 服务健康：`docker compose ps`（查看 STATUS 列应为 `healthy`）
- 确认 `DB_PASSWORD` 已在 `.env` 中配置
- PostgreSQL 容器首次启动需要约 10-20 秒

**4. Redis 连接错误（dev/prod 模式）**
- 确认 `redis` 服务健康
- 确认 `QUEUE_REDIS_HOST=redis`（在容器网络内）

**5. 管理后台登录失败**
- 确认 `WEB_ADMIN_PASSWORD_PLAIN` 已配置
- 确认 `DB_ENCRYPTION_KEY` ≥ 16 字符
- 清除浏览器 Cookie 后重试

**6. SQLite 模式数据不能持久化**
- 默认 `DB_SQLITE_PATH` 留空 = 内存数据库，容器重启丢失
- 如需持久化，可在 `.env` 中设置 `DB_SQLITE_PATH=/app/data/openclaw_biz.db`
  （已在 lite 模式下通过 volume 挂载，数据会持久化到本地磁盘）

## 端口映射

| 模式 | 宿主端口 | 容器内端口 | 服务 |
|------|---------|-----------|------|
| lite | `8000`  | `8000`   | app-lite（FastAPI + Web Admin） |
| dev  | `8000`  | `8000`   | app-dev（含代码热重载） |
| dev  | `5432`  | `5432`   | PostgreSQL（方便调试） |
| dev  | `6379`  | `6379`   | Redis（方便调试） |
| prod | `8000`  | `8000`   | app（不含暴露数据库/缓存端口） |

如需修改宿主端口，可直接修改 `.env` 中的 `APP_PORT`、`DB_PORT`、`REDIS_PORT`。

## 生产部署建议清单

- [ ] 修改 `.env` 中的 `DB_PASSWORD`（至少 16 字符，混合大小写 + 数字 + 符号）
- [ ] 修改 `.env` 中的 `DB_ENCRYPTION_KEY`（至少 32 字符的强随机字符串）
- [ ] 修改 `.env` 中的 `WEB_ADMIN_PASSWORD_PLAIN`（至少 12 字符，混合字符）
- [ ] 修改 `.env` 中的 `ADAPTER_API_TOKENS`（替换为正式的 Token）
- [ ] 修改 `.env` 中的 `SECRET_KEY`（用于其他签名场景）
- [ ] 设置 `ENV=prod` 和 `DEBUG=false`
- [ ] 设置 `LOG_LEVEL=WARNING` 或 `ERROR` 以减少日志噪音
- [ ] 设置反向代理（nginx / caddy）并启用 HTTPS
- [ ] 配置防火墙，仅开放 80 / 443 端口
- [ ] 配置容器日志轮转（docker-compose 中的 logs 驱动已内置）
- [ ] 配置宿主机级别的备份：`docker volume` 定期导出
- [ ] 监控 CPU / 内存 / 磁盘使用
- [ ] 启用健康检查（compose 中已配置，可配合 alertmanager）

## 容器架构图

```
                     ┌─────────────────────┐
   浏览器 / API ───►│ 8000: FastAPI app   │
                     │  ├─ /health, /docs  │
                     │  ├─ /api/v1/*       │← 适配器网关，需 Bearer Token
                     │  └─ /admin/*        │← 管理后台，需账号密码
                     └──┬──────────────────┘
                        │
           ┌────────────┼────────────┐
           ▼            ▼            ▼  ← 仅 dev/prod 模式启用
     ┌──────────┐  ┌──────────┐   ┌──────────┐
     │  SQLite  │  │ Postgres │   │  Redis   │
     │ (内置)   │  │ +pgvector│   │  缓存 +  │
     └──────────┘  └──────────┘   │  会话 +  │
                                  │  异步队列 │
                                  └──────────┘
```

## 参考文档

- [FastAPI](https://fastapi.tiangolo.com/)
- [SQLAlchemy 2.0](https://docs.sqlalchemy.org/en/20/)
- [PostgreSQL](https://www.postgresql.org/docs/)
- [Redis](https://redis.io/docs/)
- [Docker Compose](https://docs.docker.com/compose/)

## 反馈与贡献

发现问题或有改进建议？请提交 Issue 或 Pull Request。

本部署指南版本：T17-v1.0
