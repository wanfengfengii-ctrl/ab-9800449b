#!/usr/bin/env sh
# 一次性校验：后端测试 → 前端构建 → 温控审计 API 冒烟。
# 由 Compose 的 verify 服务在 app 健康后执行，退出码即最终结果。
set -eu

APP_URL="${APP_URL:-http://app:8000}"
cd /app

echo "================ [1/3] 后端代码测试 (pytest) ================"
/opt/venv/bin/python -m pytest backend/tests -q

echo "================ [2/3] 前端构建 (vite) ================"
cd frontend
if [ -f package-lock.json ]; then
  npm ci
else
  npm install
fi
npm run build
test -f dist/index.html
cd /app

echo "================ [3/3] 温控审计 API 冒烟 ================"
echo "目标服务：${APP_URL}"
/opt/venv/bin/python scripts/smoke.py "${APP_URL}"

echo "================ verify 全部通过 ================"
