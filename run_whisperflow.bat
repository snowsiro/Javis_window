@echo off
chcp 65001 >nul
REM WhisperFlow (JARVIS) 실행 스크립트 (Windows)
cd /d "%~dp0"
if exist "venv\Scripts\activate.bat" (
    call venv\Scripts\activate.bat
)
python -m whisperflow
pause
