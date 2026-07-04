# 자비스 음성 서버 (5단계)

WhisperFlow(JARVIS) 앱에 **자비스 스타일 음성**을 붙이는 로컬 TTS 서버입니다.
원작자(macOS)의 Qwen TTS 서버와 **동일한 API 규격**을 제공하므로 앱 코드 수정 없이 그대로 연동됩니다.

- 영어 응답: `en-GB-RyanNeural` — **영국 남성** (자비스 억양 느낌)
- 한국어 응답: `ko-KR-InJoonNeural` — 남성
- GPU/대용량 모델 불필요, 단 **인터넷 연결 필요** (Microsoft Edge 신경망 음성 사용)

## 설치 (원클릭)

레포 루트에서:
```cmd
setup_voice.bat
```
이 스크립트가 자동으로:
1. 앱 venv에 의존성 설치 (`edge-tts`, `miniaudio`)
2. 훅 파일을 `%USERPROFILE%\.claude\hooks\qwen_tts_speak.py`로 복사
3. 환경변수 등록: `QWEN_TTS_DIR`, `QWEN_TTS_HOOK`

**⚠️ 설치 후 반드시 모든 창을 닫고 새 창에서 `run_whisperflow.bat`을 다시 실행하세요** (환경변수는 새 프로세스부터 적용).

## 동작 확인

앱 실행 후:
1. DOS창에 `[TTS] Qwen TTS 서버 자동 시작` 로그 확인
2. 브라우저에서 `http://localhost:9093/health` → `ok` 표시
3. 아무 텍스트 복사 후 `Ctrl+Shift+S` → **새 목소리**로 읽으면 성공

## API 규격 (앱 호환)

| 엔드포인트 | 설명 |
|---|---|
| `GET /health` | 200 `ok` |
| `POST /generate` | JSON `{"text","voice","speed","seed","instruct"}` → WAV 바이트 |

- `voice`에 `clone:jarvis`/`clone:tars`가 오면 언어 자동감지로 기본 음성 매핑
- `voice`에 edge 음성 이름(예: `en-GB-ThomasNeural`)이 직접 오면 그대로 사용
- `speed` 1.4 → 재생속도 +40%

## 목소리 바꾸기

이 폴더에 `voices.json` 생성:
```json
{
  "en": "en-GB-ThomasNeural",
  "ko": "ko-KR-HyunsuMultilingualNeural"
}
```
사용 가능한 음성 목록: `venv` 활성화 후 `edge-tts --list-voices`

## 참고: 진짜 "영화 자비스" 클론 목소리는?

원작자는 별도의 음성 클로닝 모델을 개인적으로 학습해 사용했습니다. 특정 인물(배우)의 목소리 클로닝은 권리 문제가 있어 이 레포에는 포함하지 않습니다. 이 서버는 대신 정식 라이선스된 고품질 신경망 음성(영국 남성)으로 같은 분위기를 냅니다. 본인 목소리 등 권리가 있는 음성으로 클로닝 백엔드를 붙이는 것은 추후 확장 가능합니다.
