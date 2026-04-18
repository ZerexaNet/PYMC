#!/bin/bash
# ============================================================
# PyMC 服务端 Nuitka 打包脚本 (Linux/macOS)
# Minecraft 1.21.1 - 协议版本 767
# ============================================================

echo "============================================================"
echo " PyMC 服务端 Nuitka 打包脚本"
echo " Minecraft 1.21.1 - 协议版本 767"
echo "============================================================"
echo ""

# 检查 Python
if ! command -v python3 &> /dev/null; then
    echo "[错误] 未找到 Python3，请先安装。"
    exit 1
fi

# 检查 Nuitka
if ! python3 -m nuitka --version &> /dev/null; then
    echo "[提示] 正在安装 Nuitka..."
    pip3 install nuitka ordered-set
fi

echo "[信息] 开始编译 PyMC 服务端..."
echo ""

python3 -m nuitka \
    --standalone \
    --onefile \
    --output-dir=dist \
    --output-filename=pymc-server \
    --include-package=protocol \
    --include-package=network \
    --include-package=handlers \
    --include-package=world \
    --include-module=config \
    --follow-imports \
    --assume-yes-for-downloads \
    main.py

if [ $? -ne 0 ]; then
    echo ""
    echo "[错误] 编译失败!"
    exit 1
fi

echo ""
echo "============================================================"
echo "[完成] 编译成功!"
echo "输出文件: dist/pymc-server"
echo ""
echo "使用方法:"
echo "  1. ./dist/pymc-server"
echo "  2. 首次运行会自动生成 server.properties 配置文件"
echo "  3. 使用 Minecraft 1.21.1 客户端连接 localhost:25565"
echo "============================================================"
