#!/bin/bash

echo "==============================================="
echo " Stardew AI Demo Launcher (macOS)"
echo "==============================================="

# Use venv Python if available
PYTHON_EXE="../venv/bin/python"

if [ ! -f "$PYTHON_EXE" ]; then
    echo "[WARN] venv Python not found, fallback to python3"
    PYTHON_EXE="python3"
fi

echo "[LAUNCHER] (1/3) Running compiler (project/runtime/compile_data.py)..."
$PYTHON_EXE ../project/runtime/compile_data.py
echo "[LAUNCHER] Compiler finished."
echo ""

echo "[LAUNCHER] (2/3) Starting AI Server (project/app.py)..."
$PYTHON_EXE ../project/app.py &
SERVER_PID=$!

echo "[LAUNCHER] Waiting 5 seconds for the server to load..."
sleep 5

echo "[LAUNCHER] (3/3) Starting Pygame Client (demo/main.py)..."
$PYTHON_EXE main.py &
CLIENT_PID=$!

echo ""
echo "[LAUNCHER] All systems launched!"
echo "Server PID: $SERVER_PID"
echo "Client PID: $CLIENT_PID"
echo "Use 'kill PID' to stop them."
