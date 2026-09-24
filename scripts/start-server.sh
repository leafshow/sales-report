#!/bin/bash
# 京东销售日报 - 本地服务器启动脚本
# 使用方法：./start-server.sh [端口]

PORT=${1:-8081}
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"
TEMPLATE_DIR="$PROJECT_DIR/templates"

echo "=================================="
echo "京东销售日报 - 本地服务器"
echo "=================================="
echo ""
echo "项目目录：$PROJECT_DIR"
echo "报告目录：$TEMPLATE_DIR"
echo "端口：$PORT"
echo ""

if [ ! -f "$TEMPLATE_DIR/index.html" ]; then
    echo "错误：找不到 index.html，请先运行构建脚本"
    exit 1
fi

echo "启动服务器..."
cd "$TEMPLATE_DIR"
python3 server.py "$PORT"
