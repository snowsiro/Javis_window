"""WhisperFlow (JARVIS) — Windows 패키지 설정.

개발 설치:  pip install -e .
실행:       python -m whisperflow   (또는 run_whisperflow.bat)
배포 빌드:  pyinstaller whisperflow.spec   (build_windows.py 참고)
"""

from setuptools import setup, find_packages

setup(
    name="whisperflow",
    version="0.1.0",
    description="WhisperFlow (JARVIS) - Windows 로컬 음성 어시스턴트",
    packages=find_packages(),
    include_package_data=True,
    package_data={
        "whisperflow": [
            "static/*",
            "static/sounds/*",
            "models/*",
        ],
    },
    python_requires=">=3.10",
    install_requires=[
        "pystray>=0.19.4",
        "pillow>=10.0.0",
        "faster-whisper>=1.0.0",
        "sounddevice>=0.4.6",
        "numpy>=1.24.0",
        "pynput>=1.7.6",
        "pyperclip>=1.8.2",
        "pyautogui>=0.9.54",
        "pyttsx3>=2.90",
        "psutil>=5.9.0",
        "websockets>=12.0",
        "openwakeword>=0.6.0",
        "silero-vad>=5.1",
        "onnxruntime>=1.16.0",
        "torch>=2.0.0",
        'pywin32>=306 ; sys_platform == "win32"',
        'win10toast>=0.9 ; sys_platform == "win32"',
    ],
    entry_points={
        "console_scripts": [
            "whisperflow=whisperflow.app:main",
        ],
    },
)
