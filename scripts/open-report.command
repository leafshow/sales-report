#!/bin/bash
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"
cd "$PROJECT_DIR/templates"

# 启动本地服务器（含 API）
python3 server.py 8081 &
SERVER_PID=$!

# 等待服务器启动
sleep 2

# 打开浏览器
open http://127.0.0.1:8081/index.html

echo "服务器已启动 (PID: $SERVER_PID)"
echo "报告地址: http://127.0.0.1:8081/index.html"
echo ""
echo "按 Ctrl+C 停止服务器"
wait $SERVER_PID
