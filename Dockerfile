# syntax=docker/dockerfile:1

# ---------- 前端构建 ----------
FROM node:22-alpine AS frontend
WORKDIR /fe
COPY frontend/package*.json ./
RUN npm install --no-audit --no-fund
COPY frontend/ ./
RUN npm run build

# ---------- 应用运行镜像 ----------
FROM python:3.11-slim AS base
WORKDIR /app

COPY backend/requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

COPY backend/ ./
# 生产环境直接托管已构建的前端静态资源
COPY --from=frontend /fe/dist ./frontend/dist
# 健康检查脚本
COPY scripts/healthcheck.py ./scripts/healthcheck.py

ENV APP_PORT=8000 \
    STATIC_DIR=/app/frontend/dist \
    PYTHONPATH=/app

EXPOSE 8000

# 健康检查：APP_PORT 可由宿主机环境变量经 Compose 注入
HEALTHCHECK --interval=5s --timeout=3s --start-period=8s --retries=24 \
  CMD ["python", "/app/scripts/healthcheck.py"]

# uvicorn 监听端口取自环境变量（默认 8000）
CMD ["sh", "-c", "uvicorn app.main:app --host 0.0.0.0 --port ${APP_PORT:-8000}"]

# ---------- 一次性 verify 镜像：代码测试 + 前端构建 + API 冒烟 ----------
FROM base AS verify
# Debian bookworm 自带 Node 18 / npm 9，满足 Vite 5 构建
RUN apt-get update \
    && apt-get install -y --no-install-recommends nodejs npm ca-certificates \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app/frontend-src
COPY frontend/package*.json ./
# 构建期预装依赖，verify 运行时离线可构建
RUN npm install --no-audit --no-fund
COPY frontend/ ./

WORKDIR /app
COPY scripts/ ./scripts/
RUN chmod +x ./scripts/verify.sh

CMD ["sh", "-c", "/app/scripts/verify.sh"]
