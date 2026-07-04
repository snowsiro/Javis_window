@echo off
REM WhisperFlow (JARVIS) voice server setup (step 5)
REM - Installs TTS server dependencies into the app venv
REM - Copies the Claude hook to %USERPROFILE%\.claude\hooks
REM - Sets QWEN_TTS_DIR / QWEN_TTS_HOOK user environment variables
cd /d "%~dp0"

if not exist "venv\Scripts\activate.bat" (
    echo [ERROR] venv not found. Run setup_windows.bat first.
    pause
    exit /b 1
)
call venv\Scripts\activate.bat

echo === Installing voice server dependencies ===
pip install edge-tts miniaudio
if errorlevel 1 (
    echo [ERROR] Dependency installation failed. See messages above.
    pause
    exit /b 1
)

echo === Installing Claude hook ===
if not exist "%USERPROFILE%\.claude\hooks" mkdir "%USERPROFILE%\.claude\hooks"
copy /Y "qwen_tts_server\qwen_tts_speak.py" "%USERPROFILE%\.claude\hooks\qwen_tts_speak.py" >nul
if errorlevel 1 (
    echo [ERROR] Failed to copy hook file.
    pause
    exit /b 1
)

echo === Setting environment variables ===
setx QWEN_TTS_DIR "%~dp0qwen_tts_server" >nul
setx QWEN_TTS_HOOK "%USERPROFILE%\.claude\hooks\qwen_tts_speak.py" >nul

echo.
echo Voice setup complete.
echo IMPORTANT: close ALL app/console windows, open a NEW window,
echo then start run_whisperflow.bat again so the new environment
echo variables take effect.
pause
