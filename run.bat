@echo off
setlocal
cd /d %~dp0

echo ========================================
echo   Stereo Dubbing Pro - V2 Launcher
echo ========================================
echo.

:: Kill any process running on port 8000
echo Checking for existing processes on port 8000...
for /f "tokens=5" %%a in ('netstat -aon ^| findstr /R /C:":8000 " ^| findstr LISTENING') do (
    if not "%%a"=="" (
        echo Found existing process %%a. Terminating...
        taskkill /F /PID %%a >nul 2>&1
        :: Wait for OS to release the socket
        timeout /t 2 >nul
    )
)

echo.
echo Please select Whisper AI Model:
echo [1] Small  (Fast, ~500MB RAM)
echo [2] Medium (Balanced, ~2GB RAM - RECOMMENDED)
echo [3] Large  (High Quality, ~5GB RAM)
echo.

set /p choice="Enter choice (1-3) [Default: 2]: "

if "%choice%"=="1" set WHISPER_MODEL=small
if "%choice%"=="2" set WHISPER_MODEL=medium
if "%choice%"=="3" set WHISPER_MODEL=large-v3
if "%choice%"=="" set WHISPER_MODEL=medium

echo.
echo Checking model files for %WHISPER_MODEL%...
if not exist "models\whisper\%WHISPER_MODEL%.pt" (
    echo.
    echo --- WARNING: %WHISPER_MODEL% model not found locally. ---
    echo It will be downloaded automatically on first run.
    echo This may take several minutes depending on your internet speed.
    echo Please DO NOT close this window.
    echo --------------------------------------------------------
)

echo Starting application...
echo Models will be stored in 'models/whisper' directory.
echo.
echo Server is starting... 
echo Local: http://localhost:8000
echo.

call venv\Scripts\activate.bat
python backend\web.py --model %WHISPER_MODEL%

