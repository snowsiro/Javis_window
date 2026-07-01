@echo off
REM WhisperFlow (JARVIS) launcher (Windows)
cd /d "%~dp0"
if exist "venv\Scripts\activate.bat" (
    call venv\Scripts\activate.bat
)
python -m whisperflow
pause
