#!/bin/sh
# 容器启动时安装依赖（满足"启动时安装依赖"的交付要求），
# 随后启动 uvicorn。
set -e

echo "[entrypoint] Installing Python dependencies from requirements.txt ..."
pip install --no-cache-dir -r /app/requirements.txt

echo "[entrypoint] Starting uvicorn on ${HOST}:${PORT} ..."
exec uvicorn app.main:app --host "${HOST:-0.0.0.0}" --port "${PORT:-8000}"
