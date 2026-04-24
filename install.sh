#!/bin/bash

# ============================================================
#   WASA - Whisper AudioSocket Asterisk | Setup / Installation
# ============================================================

echo ""
echo "============================================================"
echo "   WASA Setup for Linux"
echo "============================================================"
echo ""

# 1) Check Python
echo "[1/5] Checking Python installation..."
if ! command -v python3 &> /dev/null; then
    echo "   ERROR: Python3 not found. Please install it (e.g., sudo apt install python3 python3-venv)"
    exit 1
fi
python3 --version

# 2) Check FFmpeg
echo ""
echo "[2/5] Checking FFmpeg installation..."
if ! command -v ffmpeg &> /dev/null; then
    echo "   ERROR: FFmpeg not found. Please install it (e.g., sudo apt install ffmpeg)"
    exit 1
fi
echo "   FFmpeg is installed."

# 3) Create virtual environment
echo ""
echo "[3/5] Setting up virtual environment (venv)..."
if [ -d "venv" ]; then
    echo "   Existing venv found, skipping creation."
else
    python3 -m venv venv
    if [ $? -ne 0 ]; then
        echo "   ERROR: Failed to create virtual environment."
        exit 1
    fi
    echo "   Virtual environment created."
fi

# 4) Install dependencies
echo ""
echo "[4/5] Installing dependencies..."
source venv/bin/activate
pip install --upgrade pip
pip install -r requirements.txt
if [ $? -ne 0 ]; then
    echo "   ERROR: Failed to install dependencies."
    exit 1
fi

echo ""
echo "   Installing audioop-lts (for modern Python compatibility)..."
pip install audioop-lts

# 5) Create required directories
echo ""
echo "[5/5] Creating required directories..."
mkdir -p models/whisper
mkdir -p outputs
echo "   Directories are ready."

echo ""
echo "============================================================"
echo "   Setup complete!"
echo ""
echo "   To start the application, run: ./run.sh"
echo "============================================================"
echo ""
