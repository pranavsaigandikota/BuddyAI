@echo off
echo ==============================================
echo            BUDDY LOCAL ASSISTANT
echo ==============================================
echo.
echo Starting up all services...
echo.

:: 1. Start Ollama model serving (background window)
echo [1/3] Starting Ollama...
start "Ollama Server" cmd /k "ollama serve"

:: 2. Start F5-TTS API Server
echo [2/3] Starting F5-TTS Server...
start "F5-TTS API" cmd /k "conda activate tts && python buddy_tts_server.py"

:: Wait for a bit to let servers start
echo.
echo Waiting 15 seconds for models to warm up...
timeout /t 15 /nobreak >nul

:: 3. Start Buddy Core Orchestrator
echo [3/3] Starting Buddy Core...
start "Buddy Core (Listening)" cmd /k "conda activate whisperx && python buddy_core.py"

echo.
echo All services launched! 
echo.
echo Leave the windows running. Buddy is now listening for "Buddy".
echo To quit, close all the black terminal windows.
echo.
pause
