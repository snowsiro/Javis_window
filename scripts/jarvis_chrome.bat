@echo off
REM JARVIS Chrome - launch Chrome with debug profile + start browser feed (Windows)
REM Usage: scripts\jarvis_chrome.bat
setlocal
set PORT=9222
set PROFILE=%USERPROFILE%\.chrome-debug-profile
set SCRIPT_DIR=%~dp0..

REM Locate Chrome executable
set CHROME=
if exist "%ProgramFiles%\Google\Chrome\Application\chrome.exe" set CHROME=%ProgramFiles%\Google\Chrome\Application\chrome.exe
if exist "%ProgramFiles(x86)%\Google\Chrome\Application\chrome.exe" set CHROME=%ProgramFiles(x86)%\Google\Chrome\Application\chrome.exe
if exist "%LocalAppData%\Google\Chrome\Application\chrome.exe" set CHROME=%LocalAppData%\Google\Chrome\Application\chrome.exe
if "%CHROME%"=="" (
  echo [ERROR] Chrome not found.
  exit /b 1
)

REM Start Chrome in debug mode
start "" "%CHROME%" --remote-debugging-port=%PORT% --user-data-dir="%PROFILE%"

echo Waiting for Chrome CDP...
timeout /t 3 >nul

REM Start browser feed
cd /d "%SCRIPT_DIR%"
if exist "venv\Scripts\activate.bat" call venv\Scripts\activate.bat
start "" python -m whisperflow.browser_feed

REM Send boot sequence to JARVIS UI
python -m whisperflow.jarvis_send ui_action browser_boot
echo JARVIS Chrome ready.
endlocal
