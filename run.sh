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
echo "Please select Whisper AI Model:"
echo "[1] Tiny   (Fastest, lowest accuracy, ~1GB VRAM)"
echo "[2] Base   (Very Fast, low accuracy, ~1GB VRAM)"
echo "[3] Small  (Fast, ~2GB VRAM)"
echo "[4] Medium (Balanced, ~5GB VRAM - RECOMMENDED)"
echo "[5] Large  (High Quality, ~10GB VRAM)"
echo "[6] Turbo  (High Quality, Near Large-v3 but much faster, ~6GB VRAM)"
echo ""

read -p "Enter choice (1-6) [Default: 4]: " choice

case $choice in
    1) WHISPER_MODEL="tiny" ;;
    2) WHISPER_MODEL="base" ;;
    3) WHISPER_MODEL="small" ;;
    4) WHISPER_MODEL="medium" ;;
    5) WHISPER_MODEL="large-v3" ;;
    6) WHISPER_MODEL="turbo" ;;
    *) WHISPER_MODEL="medium" ;;
esac

echo ""
echo "Please select Whisper Engine:"
echo "[1] OpenAI Whisper (Standard)"
echo "[2] Faster-Whisper  (High Performance, Optimized, default)"
echo ""
read -p "Enter engine choice (1-2) [Default: 2]: " engine_choice

case $engine_choice in
    1) WHISPER_ENGINE="openai" ;;
    *) WHISPER_ENGINE="faster" ;;
esac

echo ""
echo "Starting application with model: $WHISPER_MODEL ($WHISPER_ENGINE engine)..."
echo "Local Dashboard: http://localhost:8000"
echo ""

source venv/bin/activate
python3 backend/web.py --model $WHISPER_MODEL --engine $WHISPER_ENGINE
