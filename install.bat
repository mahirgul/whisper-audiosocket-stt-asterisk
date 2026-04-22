@echo off
setlocal EnableDelayedExpansion
cd /d %~dp0

echo.
echo ============================================================
echo   Stereo Dubbing Pro - V2  ^|  Setup / Installation
echo ============================================================
echo.

:: ------------------------------------------------------------
:: 1) Check Python
:: ------------------------------------------------------------
echo [1/5] Checking Python installation...
python --version >nul 2>&1
if %errorlevel% neq 0 (
    echo   Python not found. Installing via winget...
    winget install -e --id Python.Python.3.14 --accept-source-agreements --accept-package-agreements
    if %errorlevel% neq 0 (
        echo   ERROR: Python could not be installed. Please install manually: https://www.python.org/downloads/
        pause
        exit /b 1
    )
    echo   Python installed. You may need to open a new terminal for PATH to update.
) else (
    for /f "tokens=*" %%v in ('python --version 2^>^&1') do echo   Found: %%v
)

:: ------------------------------------------------------------
:: 2) Check FFmpeg
:: ------------------------------------------------------------
echo.
echo [2/5] Checking FFmpeg installation...
ffmpeg -version >nul 2>&1
if %errorlevel% neq 0 (
    echo   FFmpeg not found. Installing via winget...
    winget install -e --id Gyan.FFmpeg --accept-source-agreements --accept-package-agreements
    if %errorlevel% neq 0 (
        echo   ERROR: FFmpeg could not be installed. Please install manually: https://ffmpeg.org/download.html
        pause
        exit /b 1
    )
    echo   FFmpeg installed.
) else (
    echo   FFmpeg is already installed.
)

:: ------------------------------------------------------------
:: 3) Create virtual environment
:: ------------------------------------------------------------
echo.
echo [3/5] Setting up virtual environment (venv)...
if exist "venv\Scripts\activate.bat" (
    echo   Existing venv found, skipping creation.
) else (
    python -m venv venv
    if %errorlevel% neq 0 (
        echo   ERROR: Failed to create virtual environment.
        pause
        exit /b 1
    )
    echo   Virtual environment created.
)

:: ------------------------------------------------------------
:: 4) Install dependencies
:: ------------------------------------------------------------
echo.
echo [4/5] Installing dependencies from requirements.txt...
call venv\Scripts\activate.bat
pip install --upgrade pip >nul
pip install -r requirements.txt
if %errorlevel% neq 0 (
    echo   ERROR: Failed to install dependencies.
    pause
    exit /b 1
)

echo.
echo   Installing audioop-lts (required for Python 3.13+)...
pip install audioop-lts
if %errorlevel% neq 0 (
    echo   WARNING: audioop-lts could not be installed. May not be needed for your Python version.
)

:: ------------------------------------------------------------
:: 5) Create required directories
:: ------------------------------------------------------------
echo.
echo [5/5] Creating required directories...
if not exist "models\whisper" mkdir "models\whisper"
if not exist "outputs"        mkdir "outputs"
echo   Directories are ready.

:: ------------------------------------------------------------
:: Done
:: ------------------------------------------------------------
echo.
echo ============================================================
echo   Setup complete!
echo.
echo   To start the application, run: run.bat
echo ============================================================
echo.
pause
