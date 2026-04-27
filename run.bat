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

:: Cleanup any orphaned Whisper model worker processes
:: We look for python processes that were started as multiprocessing spawns
echo Cleaning up orphaned AI worker processes...
for /f "tokens=2 delims=," %%p in ('wmic process where "name='python.exe' and CommandLine like '%%multiprocessing%%'" get ProcessId /format:csv ^| findstr /r [0-9]') do (
    echo Terminating orphaned worker PID: %%p
    taskkill /F /PID %%p >nul 2>&1
)

echo.
echo Please select Whisper AI Model:
echo [1] Tiny   (Fastest, lowest accuracy, ~1GB VRAM)
echo [2] Base   (Very Fast, low accuracy, ~1GB VRAM)
echo [3] Small  (Fast, ~2GB VRAM)
echo [4] Medium (Balanced, ~5GB VRAM - RECOMMENDED)
echo [5] Large  (High Quality, ~10GB VRAM)
echo [6] Turbo  (High Quality, Near Large-v3 but much faster, ~6GB VRAM)
echo.
echo [D] Download all models locally
echo.

set /p choice="Enter choice (1-6 or D) [Default: 4]: "

if "%choice%"=="1" set WHISPER_MODEL=tiny
if "%choice%"=="2" set WHISPER_MODEL=base
if "%choice%"=="3" set WHISPER_MODEL=small
if "%choice%"=="4" set WHISPER_MODEL=medium
if "%choice%"=="5" set WHISPER_MODEL=large-v3
if "%choice%"=="6" set WHISPER_MODEL=turbo
if "%choice%"=="d" goto download_all
if "%choice%"=="D" goto download_all
if "%choice%"=="" set WHISPER_MODEL=medium

echo.
echo Please select Whisper Engine:
echo [1] OpenAI Whisper (Standard)
echo [2] Faster-Whisper  (High Performance, Optimized, default)
echo.
set /p engine_choice="Enter engine choice (1-2) [Default: 2]: "

set WHISPER_ENGINE=faster
if "%engine_choice%"=="1" set WHISPER_ENGINE=openai

echo.
echo Checking model files for %WHISPER_MODEL%...
if not exist "models\whisper\%WHISPER_MODEL%.pt" (
    if "%WHISPER_ENGINE%"=="openai" (
        echo.
        echo --- WARNING: %WHISPER_MODEL% model not found locally. ---
        echo It will be downloaded automatically on first run.
        echo --------------------------------------------------------
    )
)

echo Starting application (%WHISPER_ENGINE% engine)...
echo.
echo Server is starting... 
echo Local: http://localhost:8000
echo.

call venv\Scripts\activate.bat
python backend\web.py --model %WHISPER_MODEL% --engine %WHISPER_ENGINE%
goto end

:download_all
echo.
echo --- Pre-downloading all Whisper models... ---
call venv\Scripts\activate.bat
python download_models.py --all
echo.
echo All models checked/downloaded.
pause
goto :eof

:end
pause
