@echo off
:: This is a one-click start script (Most Universal Version - using py.exe)
:: 1. Compile data (compile.py)
:: 2. Start AI server (app.py)
:: 3. Start Pygame client (main.py)

title Stardew AI Demo Launcher (Full)
set PYTHON_EXE=py

cd ..
echo [LAUNCHER] Current Working Directory (CWD) set to: %CD%
echo.

echo [LAUNCHER] (1/3) Running compiler (project/runtime/compile.py)...
%PYTHON_EXE% project/runtime/compile.py
echo [LAUNCHER] Compiler finished.
echo.

echo [LAUNCHER] (2/3) Starting AI Server (project/app.py)...
start "AI Server" %PYTHON_EXE% project/app.py

echo [LAUNCHER] Waiting 5 seconds for the server to load models...
timeout /t 5 > nul

echo [LAUNCHER] (3/3) Starting Pygame Client (demo/main.py)...
start "Pygame Client" %PYTHON_EXE% demo/main.py

echo [LAUNCHER] All systems launched!