#!/bin/bash

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
BACKEND_DIR="$(cd "$SCRIPT_DIR/../../backend" && pwd)"

if ! curl --max-time 2 -fsS http://127.0.0.1:8000/api/health/ > /dev/null 2>&1; then
    echo "后端服务未运行，正在启动..."
    "$BACKEND_DIR/start.sh"

    if ! curl --max-time 5 -fsS http://127.0.0.1:8000/api/health/ > /dev/null 2>&1; then
        echo "错误：后端服务启动失败，请检查 $BACKEND_DIR/backend.log"
        exit 1
    fi
fi

cd "$SCRIPT_DIR"
npm install
npm run dev
