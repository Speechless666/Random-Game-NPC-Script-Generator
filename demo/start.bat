@echo off
:: 这是一个一键启动脚本 (完整版)
:: 1. 编译数据 (compile.py)
:: 2. 启动 AI 服务器 (app.py)
:: 3. 启动 Pygame 客户端 (main.py)

:: 1. 设置标题和 Python 路径
title Stardew AI Demo Launcher (Full)
set PYTHON_EXE="C:/Users/hzy/AppData/Local/Programs/Python/Python313/python.exe"

:: 2. 导航到项目根目录
:: (此脚本在 demo/ 文件夹中，所以我们用 'cd ..' 返回到根目录)
cd ..
echo [LAUNCHER] 当前工作目录 (CWD) 设置为: %CD%
echo.

:: 3. (新增) 运行编译器 (compile.py)
:: 我们在这里 *不* 使用 'start'，因为必须等待它完成后才能启动服务器
echo [LAUNCHER] (1/3) 正在运行编译器 (project/runtime/compile.py)...
%PYTHON_EXE% project/runtime/compile.py
echo [LAUNCHER] 编译器运行完毕。
echo.

:: 4. 启动 AI 服务器 (app.py)
:: 'start "Title"' 会在一个新窗口中运行命令
echo [LAUNCHER] (2/3) 正在启动 AI 服务器 (project/app.py)...
start "AI Server" %PYTHON_EXE% project/app.py

:: 5. 等待 5 秒钟
:: (给服务器足够的时间来加载所有模型和组件)
echo [LAUNCHER] 等待 5 秒钟，让服务器加载模型...
timeout /t 5 > nul

:: 6. 启动 Pygame 客户端 (main.py)
echo [LAUNCHER] (3/3) 正在启动 Pygame 客户端 (demo/main.py)...
start "Pygame Client" %PYTHON_EXE% demo/main.py

echo [LAUNCHER] 已全部启动！