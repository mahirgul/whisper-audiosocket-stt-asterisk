#!/bin/bash

# ============================================================
#   WASA - Whisper AudioSocket Asterisk Launcher (Linux)
# ============================================================

echo "========================================"
echo "   WASA Launcher for Linux"
echo "========================================"
echo ""

# Kill any process running on port 8000
echo "Checking for existing processes on port 8000..."
PID=$(lsof -t -i:8000)
if [ ! -z "$PID" ]; then
    echo "Found existing process $PID. Terminating..."
    kill -9 $PID
    sleep 2
fi

echo ""
echo "Starting application..."
echo "Local Dashboard: http://localhost:8000"
echo ""

if [ ! -f "venv/bin/activate" ]; then
    echo "ERROR: Virtual environment not found. Please run ./install.sh first."
    exit 1
fi

source venv/bin/activate
python3 backend/web.py
