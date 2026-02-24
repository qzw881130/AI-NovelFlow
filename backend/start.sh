#!/bin/bash

# NovelFlow 后端启动脚本

# 获取脚本所在目录
SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
cd "$SCRIPT_DIR"

# 停止已有的 uvicorn 进程
echo "正在停止已有的服务..."
pkill -f "uvicorn app.main:app" 2>/dev/null || true
sleep 2

# 激活虚拟环境
if [ -d "venv" ]; then
    echo "激活虚拟环境..."
    source venv/bin/activate
else
    echo "错误：找不到虚拟环境 venv 目录"
    exit 1
fi

# 获取本机所有 IP 地址
echo ""
echo "📡 本机可访问地址列表:"
echo "────────────────────────────────────────"

# 获取所有 IP 地址（排除 127.0.0.1）
IP_LIST=()
if command -v ifconfig &> /dev/null; then
    # macOS / BSD
    while IFS= read -r line; do
        if [[ -n "$line" ]]; then
            IP_LIST+=("$line")
        fi
    done < <(ifconfig | grep "inet " | grep -v "127.0.0.1" | awk '{print $2}')
elif command -v ip &> /dev/null; then
    # Linux
    while IFS= read -r line; do
        if [[ -n "$line" ]]; then
            IP_LIST+=("$line")
        fi
    done < <(ip addr show | grep "inet " | grep -v "127.0.0.1" | awk '{print $2}' | cut -d'/' -f1)
fi

# 显示所有可访问地址
echo "  🌐 http://localhost:8000"
for ip in "${IP_LIST[@]}"; do
    echo "  🌐 http://${ip}:8000"
done
echo "────────────────────────────────────────"
echo ""

# 启动服务
echo "启动 NovelFlow 后端服务..."
echo "按 Ctrl+C 停止服务"
echo ""

# 使用 nohup 在后台运行，输出到 backend.log
nohup python -m uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload > backend.log 2>&1 &

# 等待服务启动
sleep 3

# 检查服务是否启动成功
if curl -s http://localhost:8000/api/health/ > /dev/null 2>&1; then
    echo "✅ 服务启动成功！"
    echo "健康检查: http://localhost:8000/api/health/"
    echo "日志文件: $SCRIPT_DIR/backend.log"
else
    echo "⚠️ 服务可能未完全启动，请检查日志: $SCRIPT_DIR/backend.log"
fi

echo ""
echo "查看日志: tail -f $SCRIPT_DIR/backend.log"
