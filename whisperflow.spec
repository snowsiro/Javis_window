# -*- mode: python ; coding: utf-8 -*-
"""
PyInstaller 스펙 — WhisperFlow (JARVIS) Windows 단일 폴더 빌드.

빌드:
    pip install pyinstaller
    pyinstaller whisperflow.spec

결과물: dist/WhisperFlow/WhisperFlow.exe

참고: faster-whisper/torch/mediapipe 등 대형 의존성 때문에 빌드가 무겁습니다.
개발 중에는 `python -m whisperflow` (소스 실행)를 권장합니다.
"""

from PyInstaller.utils.hooks import collect_data_files, collect_submodules

block_cipher = None

# 정적 리소스(HTML/사운드/아이콘) + 모델을 번들에 포함
datas = [
    ("whisperflow/static", "whisperflow/static"),
    ("whisperflow/models", "whisperflow/models"),
]

# 런타임 데이터가 필요한 패키지들의 데이터 수집
for pkg in ("openwakeword", "silero_vad", "faster_whisper", "pystray"):
    try:
        datas += collect_data_files(pkg)
    except Exception:
        pass

hiddenimports = []
for pkg in ("pynput", "pystray", "comtypes", "win32timezone"):
    try:
        hiddenimports += collect_submodules(pkg)
    except Exception:
        pass


a = Analysis(
    ["whisperflow/__main__.py"],
    pathex=[],
    binaries=[],
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="WhisperFlow",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=False,  # 트레이 앱 — 콘솔 창 숨김
    icon="whisperflow/static/jarvis-icon-192.png",
)

coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name="WhisperFlow",
)
