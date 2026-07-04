# 🎤 WhisperFlow (JARVIS) — Windows Edition

> **Windows**에서 로컬 음성인식 + AI 음성 응답 + 시각화 UI를 통합한 개인 어시스턴트
> (macOS 원본 [`javis`](https://github.com/snowsiro/javis)를 Windows로 100% 포팅)

![WhisperFlow JARVIS UI](./jarvis_idle.png)

---

## ✨ 핵심 기능

### 🎙️ 음성 인식 & 입력
- **오프라인 STT**: OpenAI Whisper (faster-whisper, 로컬 실행 · 프라이버시 보장)
- **다국어**: 한국어 · 영어 · 일본어 · 중국어 · 자동감지
- **전역 단축키**: `Ctrl+Shift+R` 꾹 누르기로 녹음 (커스터마이징 가능)
- **자동 입력**: 변환된 텍스트를 활성 창에 `Ctrl+V`로 자동 입력

### 🔊 음성 응답 (TTS)
- **Windows SAPI5 음성 합성** (pyttsx3) — 언어 자동 감지 후 음성 선택
- **Qwen TTS(선택)**: 자비스 목소리 (서버 실행 시), 없으면 SAPI5로 자동 폴백
- **모드**: 드라이브 모드 · 도서관 모드 · JARVIS 촬영 모드

### 🎨 JARVIS UI
- **실시간 파티클**: AI 응답에 반응하는 420입자 성운 효과
- **음성 동기화**: TTS 음량 · 3-band 주파수에 파티클이 실시간 반응
- **상태별 색상**: Standby / Recording / Thinking / Speaking

### 🤖 추가 기능 (선택 의존성)
- **상시 청취**: "Hey Jarvis" 웨이크 워드 + 박수 2번 부팅 (openWakeWord + Silero VAD)
- **제스처 컨트롤**: MediaPipe 손 인식으로 마우스·시스템 제어
- **카메라 / 얼굴 인식**: OpenCV + InsightFace
- **Hue 라이트**: 상태별 스마트 조명 연동
- **히스토리**: 음성 파일 + 변환 텍스트 자동 저장

---

## 🚀 설치 & 실행 (Windows)

### 요구사항
- Windows 10 / 11
- Python 3.10+ ([python.org](https://www.python.org/downloads/) 설치 시 "Add to PATH" 체크)
- 메모리 4GB 이상 (large 모델은 8GB+ 권장)

### 빠른 설치
```powershell
git clone https://github.com/snowsiro/Javis_window.git
cd Javis_window

REM 최초 1회: 가상환경 + 핵심 의존성 설치
setup_windows.bat

REM (선택) 카메라/제스처/얼굴 인식 기능
pip install -r requirements-extras.txt

REM 실행
run_whisperflow.bat

REM (선택) 자비스 음성 서버 — 영국 남성 신경망 음성으로 응답 읽기
setup_voice.bat
```
> 수동 실행: `python -m whisperflow` · 자비스 음성 상세: [`qwen_tts_server/README.md`](qwen_tts_server/README.md)

실행하면 **작업 표시줄 트레이(오른쪽 아래)** 에 🔵 아이콘이 나타납니다.
아이콘을 우클릭하면 모든 메뉴에 접근할 수 있습니다.

### 권한
- **마이크**: 설정 → 개인정보 → 마이크 → "데스크톱 앱이 마이크에 액세스" 허용
- 전역 단축키/입력 자동화는 관리자 권한이 필요할 수 있습니다(일부 앱에 붙여넣기 시).

---

## 📖 사용법

### 🎙️ 음성 입력
기본 단축키: **`Ctrl + Shift + R`**

| 동작 | 설명 |
|------|------|
| **꾹 누르기** | 누르는 동안 녹음, 떼면 자동 변환 |
| **짧게 탭** | 토글 모드 (다시 탭하면 종료) |
| **Alt 홀드(옵션)** | Alt만 길게 눌러 녹음 (트레이 → 단축키 설정) |

### 🎯 트레이 메뉴
트레이 🔵 아이콘 우클릭:
- **녹음 시작/중지** — 수동 녹음 제어 (좌클릭 기본 동작)
- **🚗 드라이브 / 📚 도서관 / 🎬 JARVIS 촬영 모드**
- **모델 선택** — tiny/base/small/medium/large-v3
- **언어 선택** — 한/영/일/중/자동
- **단축키 설정** — Ctrl/Alt/Shift/Win 조합 + Alt 홀드
- **히스토리** — 폴더 열기 / 전체 삭제
- **TTS** — 활성화 / 읽기 속도 / Qwen 속도 / 읽기 중지
- **🖐 제스처 컨트롤 · 💡 Hue 조명 · JARVIS UI 열기**

### ⚙️ 설정 파일
`%USERPROFILE%\.config\whisperflow\config.json`
```json
{
  "model_size": "base",
  "language": "ko",
  "hotkey": "ctrl+shift+r",
  "tts_hotkey": "ctrl+shift+s",
  "output_mode": "type",
  "sample_rate": 16000
}
```

---

## 🧩 macOS → Windows 포팅 매핑

모든 OS 종속 호출은 `whisperflow/platform_utils.py` 한 곳에 모여 있습니다.

| macOS 원본 | Windows 구현 |
|-----------|-------------|
| rumps 메뉴바 | **pystray 시스템 트레이** |
| `afplay` 사운드 | sounddevice + wave (재생 속도 배율 지원) |
| `say` / NSSpeechSynthesizer | **pyttsx3 (SAPI5)** |
| `pbcopy` + osascript Cmd+V | pyperclip + pynput **Ctrl+V** |
| osascript 활성 앱 추적 | **win32 GetForegroundWindow** |
| `open -a` / `open url` | `start` / webbrowser |
| `pgrep`/`pkill`/`killall` | **psutil** / sounddevice stop |
| Quartz CGEvent (마우스) | **pyautogui** |
| AppKit NSScreen | **win32 GetSystemMetrics** |
| Mission Control | **Win+Tab (Task View)** |
| `/tmp/...` | `%TEMP%` |

---

## 🛠️ 배포 빌드 (선택)
```powershell
pip install pyinstaller
pyinstaller whisperflow.spec
REM 결과물: dist\WhisperFlow\WhisperFlow.exe
```
> 대형 의존성(torch/faster-whisper/mediapipe) 때문에 빌드가 무겁습니다.
> 개발 중에는 소스 실행(`python -m whisperflow`)을 권장합니다.

---

## 🐛 문제 해결

**트레이 아이콘이 안 보임** → 작업 표시줄 "숨겨진 아이콘 표시(^)" 확인, 콘솔 로그(`%TEMP%\whisperflow.log`) 확인.

**단축키 작동 안 함** → 다른 앱과 충돌 시 트레이 → 단축키 설정에서 조합 변경. 관리자 권한으로 실행.

**녹음 안 됨** → 설정 → 개인정보 → 마이크 권한, 사운드 설정에서 입력 장치 확인.

**TTS 음성이 이상함** → 언어팩 설치(설정 → 시간 및 언어 → 음성)로 한/일/중 음성 추가.

**AI 음성 응답(Qwen)이 안 나옴** → `QWEN_TTS_DIR` 미설정 시 SAPI5로 폴백됩니다. Qwen 사용 시 포트 9093 확인.

**웨이크 워드/제스처/얼굴 기능 없음** → `pip install -r requirements-extras.txt` 로 선택 의존성 설치.

---

## 🔧 선택적 통합

**Philips Hue** — `%USERPROFILE%\.config\whisperflow\hue_config.json`
```json
{ "enabled": true, "bridge_ip": "192.168.1.X", "api_key": "your-key", "light_id": 26 }
```

**Obsidian / Qwen TTS** — 환경변수
```
OBSIDIAN_VAULT_PATH, HOME_ADDRESS_FILE, QWEN_TTS_DIR, QWEN_TTS_HOOK
```

---

## 📝 라이선스
MIT License

**Made with ❤️ — WhisperFlow (JARVIS) Windows Port**
