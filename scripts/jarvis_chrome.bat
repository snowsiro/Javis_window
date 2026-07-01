@echo off
REM JARVIS Chrome — 디버그 프로필로 Chrome 실행 + 브라우저 피드 시작 (Windows)
REM 사용법: scripts\jarvis_chrome.bat
setlocal
set PORT=9222
set PROFILE=%USERPROFILE%\.chrome-debug-profile
set SCRIPT_DIR=%~dp0..

REM Chrome 실행 파일 찾기
set CHROME=
if exist "%ProgramFiles%\Google\Chrome\Application\chrome.exe" set CHROME=%ProgramFiles%\Google\Chrome\Application\chrome.exe
if exist "%ProgramFiles(x86)%\Google\Chrome\Application\chrome.exe" set CHROME=%ProgramFiles(x86)%\Google\Chrome\Application\chrome.exe
if exist "%LocalAppData%\Google\Chrome\Application\chrome.exe" set CHROME=%LocalAppData%\Google\Chrome\Application\chrome.exe
if "%CHROME%"=="" (
  echo Chrome 을 찾을 수 없습니다.
  exit /b 1
)

REM Chrome 디버그 모드 실행
start "" "%CHROME%" --remote-debugging-port=%PORT% --user-data-dir="%PROFILE%"

echo Chrome CDP 연결 대기 중...
timeout /t 3 >nul

REM 브라우저 피드 시작
cd /d "%SCRIPT_DIR%"
start "" python -m whisperflow.browser_feed

REM JARVIS UI 부팅 시퀀스 전송
python -m whisperflow.jarvis_send ui_action browser_boot
echo JARVIS Chrome 준비 완료
endlocal
