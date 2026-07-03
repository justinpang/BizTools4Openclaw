# ====================================================================
#  BizTools4Openclaw — 应用 Dockerfile
#  三阶段分层构建：builder-base → builder-deps → final
#  目标：最小化最终镜像体积，移除构建工具，非 root 用户运行
# ====================================================================

# ================= Stage 1: builder-base =================
# 安装系统构建依赖（后续 stage 继承）
FROM python:3.11-slim AS builder-base

ENV DEBIAN_FRONTEND=noninteractive \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

# 系统构建期依赖：libpq-dev (psycopg2), build-essential (gcc), curl, nodejs (playwright)
RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        libpq-dev \
        build-essential \
        curl \
        ca-certificates \
    && rm -rf /var/lib/apt/lists/*

RUN pip install --upgrade pip wheel setuptools

# ================= Stage 2: builder-deps =================
# 预编译 Python 依赖为 wheel，缓存复用
FROM builder-base AS builder-deps

WORKDIR /wheels
COPY requirements.txt .
RUN pip wheel --wheel-dir=/wheels -r requirements.txt

# ================= Stage 3: final（运行镜像） =================
FROM python:3.11-slim AS final

# --- 运行期环境变量（均可通过 docker run -e 覆盖） ---
ENV DEBIAN_FRONTEND=noninteractive \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    APP_HOST=0.0.0.0 \
    APP_PORT=8000 \
    LOG_LEVEL=INFO \
    ENV=production

# --- 运行期系统依赖（轻量，不含 gcc） ---
# libpq5: psycopg2 运行期动态库
# ca-certificates: HTTPS/SSL 证书
# ttf-dejavu + fonts-noto-cjk: Playwright 中文字体
RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        libpq5 \
        ca-certificates \
        ttf-dejavu \
        fonts-noto-cjk \
        curl \
    && rm -rf /var/lib/apt/lists/* \
    && apt-get clean

# --- 从 builder-deps 拷贝 wheel 并安装（无需网络） ---
WORKDIR /app
COPY --from=builder-deps /wheels /wheels
COPY requirements.txt /app/requirements.txt

RUN pip install --no-index --find-links=/wheels -r requirements.txt \
    && rm -rf /wheels /root/.cache /tmp/*

# --- 安装 Playwright Chromium 浏览器（失败不阻塞 — 无爬虫需求可跳过） ---
RUN python -m playwright install chromium --with-deps 2>/dev/null || \
    echo "[WARN] playwright chromium 安装失败，可能是网络问题。爬虫功能将受限。"

# --- 创建非 root 用户 ---
RUN useradd -m -u 1000 appuser \
    && chown -R appuser:appuser /app

# --- 拷贝项目源码（build context 是项目根，会自动遵循 .dockerignore） ---
COPY --chown=appuser:appuser . /app/

USER appuser

# --- 健康检查（调用 FastAPI /health 端点） ---
HEALTHCHECK --interval=30s --timeout=5s --start-period=15s --retries=3 \
    CMD curl -fsS http://127.0.0.1:8000/health > /dev/null 2>&1 || exit 1

# --- 暴露端口（仅声明，实际映射由 docker-compose 决定） ---
EXPOSE 8000

# --- 默认启动命令（可通过 docker compose command 覆盖） ---
CMD ["uvicorn", "adapter.main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "2"]
