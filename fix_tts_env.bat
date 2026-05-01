@echo off
echo =====================================================
echo  Fixing torchaudio for torch 2.11 in tts conda env
echo =====================================================
echo.

call conda activate tts

echo Installing torchaudio 2.11.0 (CPU build, no torchcodec/FFmpeg needed)...
pip install torchaudio==2.11.0 --index-url https://download.pytorch.org/whl/cpu

echo.
echo Done! Now restart buddy_tts_server.py
echo.
pause
