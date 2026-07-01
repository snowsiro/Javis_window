# Claude Code 훅 (Windows)

WhisperFlow(JARVIS)와 Claude Code 를 연동하는 훅입니다. macOS 원본의 `.sh` 훅을
크로스 플랫폼 Python(`.py`)으로 포팅했습니다.

| 훅 | 이벤트 | 동작 |
|----|--------|------|
| `jarvis_hook.py` | Stop | Claude 응답을 JARVIS UI 에 표시 |
| `jarvis_code_hook.py` | PreToolUse / PostToolUse | 도구 사용을 JARVIS UI 에 시각화 (촬영 모드 한정) |
| `tars_tts_hook.py` | Stop | TARS 모드 시 응답을 TARS 음성으로 재생 (Qwen TTS + ffmpeg FX) |

## 설정 방법 (Windows)

Claude Code 설정 파일 `%USERPROFILE%\.claude\settings.json` 에 추가하세요.
경로의 백슬래시는 슬래시(`/`)로 쓰거나 `\\` 로 이스케이프합니다.

```json
{
  "hooks": {
    "Stop": [
      { "hooks": [
        { "type": "command", "command": "python \"C:/path/to/Javis_window/hooks/jarvis_hook.py\"" },
        { "type": "command", "command": "python \"C:/path/to/Javis_window/hooks/tars_tts_hook.py\"" }
      ] }
    ],
    "PreToolUse": [
      { "hooks": [
        { "type": "command", "command": "python \"C:/path/to/Javis_window/hooks/jarvis_code_hook.py\"" }
      ] }
    ]
  }
}
```

## 요구사항
- `jarvis_hook.py` / `jarvis_code_hook.py`: 추가 의존성 없음 (WhisperFlow 실행 중이어야 UI 표시)
- `tars_tts_hook.py`: TARS 모드(`~/.whisperflow_tars_mode`), Qwen TTS 서버(포트 9093),
  `ffmpeg` 실행 파일(PATH), `TARS_FILLERS_DIR`(선택)

훅은 실행 시 스스로 저장소 루트를 `sys.path` 에 추가하므로 `whisperflow` 패키지를 import 할 수 있습니다.
가상환경을 쓴다면 `python` 대신 `venv\Scripts\python.exe` 절대경로를 사용하세요.
