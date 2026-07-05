# 基础Python镜像
FROM python:3.11-slim AS builder-base

# 切换阿里云稳定PyPI源，解决域名解析失败问题
ENV PIP_INDEX_URL=https://mirrors.aliyun.com/pypi/simple
ENV PIP_DEFAULT_TIMEOUT=120
ENV PYTHONUNBUFFERED=1
ENV PYTHONDONTWRITEBYTECODE=1

# 替换Debian国内apt源，加速系统包下载
RUN echo "deb https://mirrors.aliyun.com/debian/ trixie main" > /etc/apt/sources.list \
    && echo "deb https://mirrors.aliyun.com/debian/ trixie-updates main" >> /etc/apt/sources.list \
    && echo "deb https://mirrors.aliyun.com/debian-security/ trixie-security main" >> /etc/apt/sources.list

# 安装系统基础依赖
RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        libpq5 \
        ca-certificates \
        curl \
    && rm -rf /var/lib/apt/lists/* \
    && apt-get clean

# 升级pip，自动走阿里云PyPI源
RUN pip install --upgrade pip wheel setuptools

# ================= Stage 2: builder-deps 安装项目全部依赖 =================
FROM builder-base AS builder-deps
WORKDIR /app

COPY requirements.txt .
RUN --mount=type=cache,target=/root/.cache/pip \
    pip install -r requirements.txt

# 安装调试工具（debugpy 用于 VS Code/PyCharm 远程调试）
RUN pip install --no-cache-dir debugpy>=1.8.0

# 安装Playwright浏览器驱动
RUN playwright install --with-deps chromium

# ================= Stage 3: 生产运行镜像 =================
FROM builder-base AS runtime
WORKDIR /app

# 拷贝预安装Python依赖
COPY --from=builder-deps /usr/local/lib/python3.11/site-packages /usr/local/lib/python3.11/site-packages
COPY --from=builder-deps /usr/local/bin /usr/local/bin

# 拷贝项目源码
COPY . .

EXPOSE 8000
CMD ["uvicorn", "adapter.main:app", "--host", "0.0.0.0", "--port", "8000"]