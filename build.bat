@echo off
chcp 65001 >nul 2>&1
echo ============================================================
echo  PyMC 服务端 Nuitka 打包脚本
echo  Minecraft 1.21.1 - 协议版本 767
echo ============================================================
echo.

REM 设置 MSYS2 ucrt64 编译器路径 (Nuitka 需要 C 编译器)
if exist "C:\msys64\ucrt64\bin\gcc.exe" (
    set "CC=C:\msys64\ucrt64\bin\gcc.exe"
    set "PATH=C:\msys64\ucrt64\bin;%PATH%"
    echo [信息] 已添加 MSYS2 ucrt64 到 PATH
)

REM 尝试多种方式找到 Python
set PYTHON_CMD=
for %%P in (py python python3) do (
    %%P --version >nul 2>&1
    if not errorlevel 1 (
        set PYTHON_CMD=%%P
        goto :found_python
    )
)

echo [错误] 未找到 Python，请先安装 Python 3.10 或更高版本。
pause
exit /b 1

:found_python
echo [信息] 使用 Python: %PYTHON_CMD%
%PYTHON_CMD% --version

REM 检查 Nuitka
%PYTHON_CMD% -c "import nuitka" >nul 2>&1
if errorlevel 1 (
    echo [提示] 正在安装 Nuitka...
    %PYTHON_CMD% -m pip install nuitka ordered-set
    if errorlevel 1 (
        echo [错误] Nuitka 安装失败。
        pause
        exit /b 1
    )
)

REM 检查 zstandard
%PYTHON_CMD% -c "import zstandard" >nul 2>&1
if errorlevel 1 (
    echo [提示] 正在安装 zstandard...
    %PYTHON_CMD% -m pip install zstandard
    if errorlevel 1 (
        echo [错误] zstandard 安装失败。
        pause
        exit /b 1
    )
)

echo [信息] 开始编译 PyMC 服务端...
echo.

%PYTHON_CMD% -m nuitka ^
    --standalone ^
    --onefile ^
    --mingw64 ^
    --output-dir=dist ^
    --output-filename=pymc-server.exe ^
    --include-package=protocol ^
    --include-package=network ^
    --include-package=handlers ^
    --include-package=world ^
    --include-module=config ^
    --include-data-files=native/terrain_gen.exe=native/terrain_gen.exe ^
    --include-data-files=world/blocks.json=world/blocks.json ^
    --follow-imports ^
    --assume-yes-for-downloads ^
    --windows-console-mode=force ^
    --company-name=PyMC ^
    --product-name="PyMC Minecraft Server" ^
    --file-version=1.0.0 ^
    --product-version=1.21.1 ^
    --file-description="PyMC - Python Minecraft 1.21.1 服务端" ^
    main.py

if errorlevel 1 (
    echo.
    echo [错误] 编译失败!
    pause
    exit /b 1
)

echo.
echo ============================================================
echo [完成] 编译成功!
echo 输出文件: dist\pymc-server.exe
echo.
echo 使用方法:
echo   1. 将 pymc-server.exe 复制到任意目录
echo   2. 运行 pymc-server.exe
echo   3. 首次运行会自动生成 server.properties 配置文件
echo   4. 使用 Minecraft 1.21.1 客户端连接 localhost:25565
echo ============================================================
pause
