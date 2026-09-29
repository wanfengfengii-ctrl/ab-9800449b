# syntax=docker/dockerfile:1

# ---------------------------------------------------------------------------
# 阶段 1：构建前端静态产物
# ---------------------------------------------------------------------------
FROM node:22-bookworm-slim AS frontend-builder
WORKDIR /build
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci
COPY frontend/ ./
RUN npm run build && test -f dist/index.html

# ---------------------------------------------------------------------------
# 阶段 2：生产运行镜像（后端 + 前端静态文件 + 健康检查）
# ---------------------------------------------------------------------------
FROM python:3.11-slim-bookworm AS runtime

ENV PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    APP_HOST=0.0.0.0 \
    APP_PORT=8000 \
    STATIC_DIR=/app/frontend/dist

WORKDIR /app/backend

# curl 供容器健康检查使用
RUN apt-get update \
    && apt-get install -y --no-install-recommends curl \
    && rm -rf /var/lib/apt/lists/*

COPY backend/requirements.txt ./requirements.txt
RUN pip install -r requirements.txt

COPY backend ./
COPY --from=frontend-builder /build/dist /app/frontend/dist

EXPOSE 8000

HEALTHCHECK --interval=10s --timeout=5s --start-period=8s --retries=5 \
    CMD-SHELL curl -fsS "http://127.0.0.1:${APP_PORT}/health" || exit 1

# 监听地址/端口可由容器环境变量 APP_HOST / APP_PORT 覆盖
CMD ["sh", "-c", "uvicorn app.main:app --host ${APP_HOST} --port ${APP_PORT}"]

# ---------------------------------------------------------------------------
# 阶段 3：一次性 verify 镜像（Python 测试 + 前端构建 + API 冒烟）
# ---------------------------------------------------------------------------
FROM node:22-bookworm-slim AS verify

RUN apt-get update \
    && apt-get install -y --no-install-recommends python3 python3-venv curl ca-certificates \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY backend ./backend
COPY frontend ./frontend
COPY scripts ./scripts

RUN python3 -m venv /opt/venv \
    && /opt/venv/bin/pip install --no-cache-dir -r backend/requirements.txt \
    && chmod +x scripts/verify.sh

CMD ["/app/scripts/verify.sh"]
