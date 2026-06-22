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

# 检查 zstandard
if ! python3 -c "import zstandard" &> /dev/null; then
    echo "[提示] 正在安装 zstandard..."
    pip3 install zstandard
fi

# 检查 C++ 编译器
if ! command -v g++ &> /dev/null; then
    echo "[错误] 未找到 g++，请先安装。"
    exit 1
fi

echo "[信息] 正在编译原生地形生成器..."
mkdir -p native build
g++ -O3 -std=c++17 -o native/terrain_gen native/terrain_gen.cpp

if [ $? -ne 0 ]; then
    echo "[错误] terrain_gen 编译失败!"
    exit 1
fi

echo "[信息] 正在编译原生生物 AI..."
g++ -O3 -std=c++17 -o native/mob_ai native/mob_ai.cpp

if [ $? -ne 0 ]; then
    echo "[错误] mob_ai 编译失败!"
    exit 1
fi

echo "[信息] 正在编译 C++ 加速层 (共享内存 IPC + 红石引擎 + 光照引擎 + 物理引擎)..."
if command -v cmake &> /dev/null; then
    cd build
    cmake .. -DCMAKE_BUILD_TYPE=Release
    make -j$(nproc 2>/dev/null || echo 2)
    cd ..
    # Copy built artifacts
    cp -f build/pymc_native_server native/ 2>/dev/null || true
    cp -f build/libpymc_native.so native/ 2>/dev/null || true
    echo "[信息] C++ 加速层编译完成"
else
    echo "[警告] 未找到 cmake，跳过 C++ 加速层编译"
    echo "[警告] 将使用 Python 回退模式"
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
    --include-data-dir=native=native \
    --include-data-files=native/terrain_gen=terrain_gen \
    --include-data-files=native/mob_ai=mob_ai \
    --include-data-files=native/pymc_native_server=pymc_native_server \
    --include-data-files=native/libpymc_native.so=libpymc_native.so \
    --include-data-files=world/blocks.json=world/blocks.json \
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
