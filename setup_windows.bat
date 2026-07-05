@echo off
REM WhisperFlow (JARVIS) first-time setup script (Windows)
cd /d "%~dp0"

where python >nul 2>nul
if errorlevel 1 (
    echo [ERROR] Python not found in PATH.
    echo Install Python 3.10+ from https://www.python.org/downloads/
    echo IMPORTANT: check "Add Python to PATH" during installation.
    pause
    exit /b 1
)

echo === Creating virtual environment ===
python -m venv venv
if errorlevel 1 (
    echo [ERROR] Failed to create virtual environment.
    pause
    exit /b 1
)

call venv\Scripts\activate.bat

echo === Upgrading pip ===
python -m pip install --upgrade pip

echo === Installing core dependencies ===
pip install -r requirements.txt
if errorlevel 1 (
    echo [ERROR] Dependency installation failed. See messages above.
    pause
    exit /b 1
)

echo === Downloading wake word models (first time only) ===
python -c "from openwakeword.utils import download_models; download_models(['hey_jarvis'])"
if errorlevel 1 (
    echo [WARN] Wake word model download failed.
    echo        It will be retried automatically on first use.
)

echo.
echo Optional features (camera / gesture / face recognition):
echo   pip install -r requirements-extras.txt
echo.
echo Setup complete. Run run_whisperflow.bat to start.
pause
