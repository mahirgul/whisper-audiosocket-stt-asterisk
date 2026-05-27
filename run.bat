@echo off
setlocal
cd /d %~dp0

echo ========================================
echo   WASA - Whisper AudioSocket Asterisk
echo ========================================
echo.

:: Kill any process running on port 8000 (Web UI)
echo Checking for existing processes on port 8000...
for /f "tokens=5" %%a in ('netstat -aon ^| findstr /R /C:":8000 " ^| findstr LISTENING') do (
    if not "%%a"=="" (
        echo Found existing process %%a. Terminating...
        taskkill /F /PID %%a >nul 2>&1
        timeout /t 2 >nul
    )
)

:: Cleanup any orphaned Whisper model worker processes
echo Cleaning up orphaned AI worker processes...
for /f "tokens=2 delims=," %%p in ('wmic process where "name='python.exe' and CommandLine like '%%multiprocessing%%'" get ProcessId /format:csv ^| findstr /r [0-9]') do (
    echo Terminating orphaned worker PID: %%p
    taskkill /F /PID %%p >nul 2>&1
)

echo Starting application...
echo.
echo Server is starting... 
echo Local: http://localhost:8000
echo.

if not exist "venv\Scripts\activate.bat" (
    echo ERROR: Virtual environment not found. Please run install.bat first.
    pause
    exit /b 1
)

call venv\Scripts\activate.bat
python backend\web.py
pause
