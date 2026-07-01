@echo off
chcp 65001 >nul
REM WhisperFlow (JARVIS) 최초 설치 스크립트 (Windows)
cd /d "%~dp0"
echo === 가상환경 생성 ===
python -m venv venv
call venv\Scripts\activate.bat
echo === pip 업그레이드 ===
python -m pip install --upgrade pip
echo === 핵심 의존성 설치 ===
pip install -r requirements.txt
echo.
echo 선택 기능(카메라/제스처/얼굴 인식)을 사용하려면:
echo   pip install -r requirements-extras.txt
echo.
echo 설치 완료. run_whisperflow.bat 로 실행하세요.
pause
