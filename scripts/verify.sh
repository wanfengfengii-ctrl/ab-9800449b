#!/bin/sh
# 一次性校验：代码测试 → 前端构建 → 温控审计 API 冒烟。
# 由 compose 的 verify 服务在 app 健康检查通过后运行；任一失败即以非零码退出。
set -eu

APP_PORT="${APP_PORT:-8000}"
AUDIT_BASE_URL="${AUDIT_BASE_URL:-http://app:${APP_PORT}}"

echo "================ [1/3] 后端代码测试 (pytest) ================"
cd /app
python -m pytest -q
echo "pytest: OK"

echo "================ [2/3] 前端生产构建 (vite build) ================"
cd /app/frontend-src
npm run build
test -f dist/index.html
echo "frontend build: OK"

echo "================ [3/3] 温控审计 API 冒烟 ================"
cd /app
APP_PORT="$APP_PORT" AUDIT_BASE_URL="$AUDIT_BASE_URL" python scripts/smoke.py
echo "smoke: OK"

echo "================ VERIFY 全部通过 ================"
