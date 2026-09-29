"""容器健康检查：轮询本机 /healthz。端口取 APP_PORT（默认 8000）。"""
import os
import sys
import urllib.request

port = os.environ.get("APP_PORT", "8000")
try:
    with urllib.request.urlopen(f"http://127.0.0.1:{port}/healthz", timeout=2) as resp:
        sys.exit(0 if resp.status == 200 else 1)
except Exception:
    sys.exit(1)
