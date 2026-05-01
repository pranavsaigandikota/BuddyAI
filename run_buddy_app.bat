@echo off
echo ==============================================
echo            BUDDY LOCAL AI APP
echo ==============================================
echo.
echo Starting backend services...

:: 1. Start F5-TTS API Server (explicit tts env Python — bypasses conda activate issues)
echo [1/3] Starting F5-TTS Server...
start "F5-TTS API" cmd /k "cd /d %~dp0 && C:\Users\filma\anaconda3\envs\tts\python.exe buddy_tts_server.py"

:: 2. Start Buddy UI Server (explicit whisperx env Python)
echo [2/3] Starting Buddy Core Backend...
start "Buddy UI Server" cmd /k "cd /d %~dp0 && C:\Users\filma\anaconda3\envs\whisperx\python.exe buddy_ui_server.py"

:: Wait for servers to spin up
echo.
echo Waiting 20 seconds for models to warm up...
timeout /t 20 /nobreak >nul

:: 3. Launch UI in Browser App Mode
echo [3/3] Launching App UI...
start msedge --app=http://localhost:8001 || start chrome --app=http://localhost:8001 || start http://localhost:8001

echo.
echo Buddy is running!
echo - F5-TTS API window: port 8000
echo - Buddy UI window:   port 8001
echo To quit, close both terminal windows.
echo.
pause