# WhisperFlow (JARVIS) — Windows 포트 · Claude Code Instructions

## 프로젝트 개요
WhisperFlow(JARVIS)는 **Windows 시스템 트레이** 음성-텍스트 변환 + AI 음성 어시스턴트입니다.
OpenAI Whisper 모델(faster-whisper)을 로컬에서 실행해 음성을 텍스트로 변환하고,
Windows SAPI5 TTS 로 응답을 읽어줍니다.

> 이 저장소는 macOS 앱(`javis`)을 **Windows에서 100% 동작하도록 포팅**한 버전입니다.
> 모든 기능(녹음/변환/TTS/드라이브·도서관·촬영 모드/상시 청취/제스처/카메라/Hue/JARVIS UI)이
> 그대로 유지됩니다.

## 기술 스택 (Windows)
- Python 3.10+
- **pystray**: Windows 시스템 트레이 앱 프레임워크 (macOS rumps 대체)
- **pyttsx3 (SAPI5)**: 음성 합성 (macOS NSSpeechSynthesizer/`say` 대체)
- **pynput**: 전역 단축키 감지 + 키 입력 자동화 (Ctrl+V 붙여넣기)
- **pyautogui / pywin32**: 마우스·화면 제어, 활성 창 추적 (Quartz/AppKit 대체)
- **faster-whisper**: 음성 인식
- **sounddevice**: 오디오 녹음/재생 (afplay 대체)
- **openwakeword + silero-vad + torch**: 상시 청취 웨이크 워드("Hey Jarvis")
- **websockets**: JARVIS UI 실시간 통신
- 선택: opencv-python, mediapipe, insightface, fer, pillow-heif, ffmpeg

## 플랫폼 추상화 레이어
OS별 호출은 모두 `whisperflow/platform_utils.py` 에 모여 있습니다.
| macOS 원본 | Windows 구현 (platform_utils) |
|-----------|-------------------------------|
| `afplay` | `play_sound` (sounddevice + wave, 배율 지원) |
| `say` / NSSpeechSynthesizer | `tts_reader.py` (pyttsx3/SAPI5) |
| `pbcopy` + osascript Cmd+V | `copy_to_clipboard` + `paste_to_active` (Ctrl+V) |
| osascript frontmost 앱 | `get_foreground_window` (win32) |
| `open -a` / `open url` | `open_app` / `open_url` |
| `pgrep`/`pkill`/`killall` | `kill_processes` / `stop_all_sounds` (psutil) |
| Quartz CGEvent (마우스) | `move_mouse`/`click_mouse`/`scroll` (pyautogui) |
| AppKit NSScreen | `screen_size` (win32) |
| Mission Control 등 | `system_control` (Win+Tab 등) |
| `/tmp/...` | `temp_path` (%TEMP%) |

## 프로젝트 구조
```
whisperflow/
├── app.py               # 메인 트레이 앱 (pystray)
├── platform_utils.py    # ★ OS 추상화 레이어 (Windows 구현)
├── config.py            # 설정 관리 (dataclass)
├── hotkey_manager.py    # 전역 단축키 (pynput, Windows VK 코드)
├── audio_recorder.py    # 오디오 녹음 (sounddevice)
├── transcriber.py       # Whisper 변환 (faster-whisper)
├── text_output.py       # 클립보드/붙여넣기
├── tts_reader.py        # TTS (pyttsx3/SAPI5)
├── history_manager.py   # 히스토리 저장
├── always_listen.py     # 상시 청취 (웨이크 워드 + VAD)
├── ws_server.py         # WebSocket + JARVIS UI 서버
├── assistant_session.py # Claude CLI 멀티 세션
├── tars_session.py / tars_mode.py  # TARS 모드
├── filming_scenarios.py # 촬영 모드 시나리오
├── app_launcher.py      # 앱 실행 / 카카오톡 / 부팅 시퀀스
├── camera_feed.py / camera_capture.py  # 카메라 (OpenCV)
├── browser_feed.py      # Chrome CDP 스크린샷 스트리밍
├── gesture_control.py   # 손 제스처 (MediaPipe → Windows 제어)
├── face_manager.py      # 얼굴 인식 (InsightFace + FER)
├── hue_controller.py    # Philips Hue 조명
├── map_navigator.py     # 네이버/카카오 지도
├── jarvis_send.py       # JARVIS UI 메시지 유틸
├── static/              # JARVIS UI (HTML/Canvas) + 사운드
└── models/hand_landmarker.task  # MediaPipe 모델
```

## 설정 / 히스토리 위치
- 설정: `~/.config/whisperflow/config.json`
- 히스토리: `~/.whisperflow/history/`
- 모드 플래그: `~/.whisperflow_auto_tts`(드라이브), `~/.whisperflow_library_tts`(도서관),
  `~/.whisperflow_youtube_tts` + `~/.whisperflow_jarvis_roleplay`(촬영)

## 실행 방법
```powershell
# 최초 1회
setup_windows.bat            # venv 생성 + 의존성 설치
# 선택 기능(카메라/제스처/얼굴)
pip install -r requirements-extras.txt

# 실행
run_whisperflow.bat          # 또는: python -m whisperflow
```

## 핵심 기능 (동작 확인 대상)
1. **단축키 녹음**: 기본 `Ctrl+Shift+R` (꾹 누르기 / 짧게 탭 토글). Alt 홀드 옵션.
2. **자동 입력**: 변환 텍스트를 활성 창에 Ctrl+V 로 붙여넣기.
3. **TTS 읽기**: `Ctrl+Shift+S` 로 클립보드 텍스트 읽기 (SAPI5 / Qwen).
4. **모드**: 드라이브 / 도서관 / JARVIS 촬영 모드 (트레이 메뉴).
5. **상시 청취**: "Hey Jarvis" 웨이크 워드 + 박수 2번 부팅.
6. **JARVIS UI**: 트레이 → "JARVIS UI 열기" (http://localhost:8767).
7. **제스처/카메라/얼굴/Hue**: 선택 의존성 설치 시 동작.

## 개발 시 주의사항
- OS별 동작이 필요하면 **반드시 `platform_utils.py`** 를 통해 호출하세요.
- Windows 에서 `claude` CLI 는 `claude.cmd` 로 설치되므로 `resolve_claude_cmd()` 사용.
- pystray 는 `icon.run()` 이 메인 스레드를 점유합니다. 나머지는 백그라운드 스레드.
- Whisper 모델은 첫 실행 시 다운로드됩니다.
- 오디오 녹음은 16kHz 샘플레이트를 사용합니다 (Whisper 권장).

## 자비스 모드 (드라이브 모드 통합)
드라이브 모드에서 자비스 스타일로 응답. "연기해줘"/"역할극" 포함 시 도구 실행 없이 대사만 응답.

## Second Brain (세컨드 브레인) - 선택사항
- `OBSIDIAN_VAULT_PATH`: Obsidian vault 경로
- `HOME_ADDRESS_FILE`: 집주소 파일 (map_navigator용)
- `QWEN_TTS_DIR` / `QWEN_TTS_HOOK`: Qwen TTS 서버 (없으면 SAPI5 로 자동 폴백)
