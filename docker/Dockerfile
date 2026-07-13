# BizTools4Openclaw - 单阶段 Dockerfile
# 单阶段构建确保 Playwright Chromium 浏览器和系统依赖完整保留
# （之前多阶段构建因只拷贝 site-packages 导致 Chromium 丢失）

FROM python:3.11-slim

WORKDIR /app

# 环境变量
ENV PIP_INDEX_URL=https://mirrors.aliyun.com/pypi/simple
ENV PIP_DEFAULT_TIMEOUT=120
ENV PYTHONUNBUFFERED=1
ENV PYTHONDONTWRITEBYTECODE=1
ENV DEBIAN_FRONTEND=noninteractive

# 1. 替换 Debian 国内 apt 源
RUN echo "deb https://mirrors.aliyun.com/debian/ trixie main" > /etc/apt/sources.list \
    && echo "deb https://mirrors.aliyun.com/debian/ trixie-updates main" >> /etc/apt/sources.list \
    && echo "deb https://mirrors.aliyun.com/debian-security/ trixie-security main" >> /etc/apt/sources.list

# 2. 安装系统基础依赖（PostgreSQL 客户端库 + curl + SSL 证书）
RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        libpq5 \
        ca-certificates \
        curl \
    && rm -rf /var/lib/apt/lists/* \
    && apt-get clean

# 3. 升级 pip
RUN pip install --upgrade pip wheel setuptools

# 4. 安装项目 Python 依赖
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# 5. 安装调试工具（debugpy 用于 VS Code/PyCharm 远程调试）
RUN pip install --no-cache-dir debugpy>=1.8.0

# 6. 安装 Playwright Chromium 浏览器（含系统依赖，关键步骤！）
#    —— 必须放在 Python 依赖之后，且使用 --with-deps 安装系统级库
#    —— 浏览器二进制会被下载到 /root/.cache/ms-playwright/
RUN playwright install --with-deps chromium

# 7. 清理 apt 缓存（减小镜像体积）
RUN apt-get clean && rm -rf /var/lib/apt/lists/* /tmp/* /var/tmp/*

# 8. 拷贝项目源码
COPY . .

# 9. 暴露端口
EXPOSE 8000

# 10. 默认启动命令（可被 docker-compose 覆盖）
CMD ["uvicorn", "adapter.main:app", "--host", "0.0.0.0", "--port", "8000"]
