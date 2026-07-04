#!/usr/bin/env python3
"""
qwen_tts_speak.py — 자비스 음성 재생 훅 (Windows / 크로스 플랫폼, 자체 완결형)

WhisperFlow(JARVIS) 앱이 호출하는 스크립트:
  - Ctrl+Shift+S (클립보드 읽기): QWEN_TTS_HOOK 환경변수 경로로 실행
  - 채팅 응답 TTS: ~/.claude/hooks/qwen_tts_speak.py 경로로 실행
    (setup_voice.bat 이 이 파일을 그 위치에 복사한다)

사용법:
    python qwen_tts_speak.py [--no-say] [--no-play] <읽을 텍스트...>

동작:
  1. 로컬 TTS 서버(http://localhost:9093/generate)로 WAV 생성
  2. JARVIS UI 로 오디오 전송 (WebSocket tts_audio, 실패해도 무시)
  3. --no-play 가 아니면 로컬 재생 (재생 중 플래그 파일 유지 →
     상시 청취의 '박수로 TTS 끊기'가 이 플래그를 본다)

주의: 아래 SPEED 줄은 앱 메뉴(Qwen TTS 속도)가 정규식으로 직접 수정하므로
      형식을 바꾸지 말 것.
"""

SPEED = 1.4

import json
import sys
import tempfile
import urllib.request
from pathlib import Path

SERVER = "http://localhost:9093"
WS_URL = "ws://localhost:8767"


def _parse_args(argv):
    no_say = "--no-say" in argv
    no_play = "--no-play" in argv
    words = [a for a in argv if a not in ("--no-say", "--no-play")]
    return no_say, no_play, " ".join(words).strip()


def _generate(text: str) -> bytes | None:
    """서버에서 WAV 생성. 실패 시 None."""
    try:
        payload = json.dumps({
            "text": text,
            "voice": "clone:jarvis",
            "speed": SPEED,
        }).encode("utf-8")
        req = urllib.request.Request(
            f"{SERVER}/generate", data=payload,
            headers={"Content-Type": "application/json"}, method="POST",
        )
        with urllib.request.urlopen(req, timeout=60) as resp:
            data = resp.read()
        return data if data[:4] == b"RIFF" else None
    except Exception as e:  # noqa: BLE001
        print(f"[qwen_tts_speak] 생성 실패: {e}", file=sys.stderr)
        return None


def _send_to_ui(wav_bytes: bytes) -> None:
    """JARVIS UI 로 오디오 전송 (모바일/브라우저 재생용). 실패해도 무시."""
    try:
        import asyncio
        import base64
        import websockets

        async def _send():
            async with websockets.connect(
                WS_URL, open_timeout=2, close_timeout=2, max_size=20 * 1024 * 1024
            ) as ws:
                b64 = base64.b64encode(wav_bytes).decode("utf-8")
                await ws.send(json.dumps({"type": "tts_audio", "value": b64}))
                await asyncio.sleep(0.2)

        asyncio.run(_send())
    except Exception:
        pass


def _play(wav_bytes: bytes) -> None:
    """로컬 재생. 재생 동안 플래그 파일 유지 (박수 인터럽트 연동)."""
    flag = Path(tempfile.gettempdir()) / "whisperflow-tts-playing"
    tmp = tempfile.NamedTemporaryFile(suffix=".wav", delete=False)
    try:
        tmp.write(wav_bytes)
        tmp.close()
        flag.touch()
        try:
            import wave

            import numpy as np
            import sounddevice as sd

            with wave.open(tmp.name, "rb") as wf:
                rate = wf.getframerate()
                ch = wf.getnchannels()
                raw = wf.readframes(wf.getnframes())
            data = np.frombuffer(raw, dtype=np.int16).astype(np.float32) / 32768.0
            if ch > 1:
                data = data.reshape(-1, ch)
            sd.play(data, samplerate=rate)
            sd.wait()
        except Exception:
            # sounddevice 실패 시 winsound 폴백 (Windows)
            if sys.platform.startswith("win"):
                try:
                    import winsound
                    winsound.PlaySound(tmp.name, winsound.SND_FILENAME)
                except Exception:
                    pass
    finally:
        flag.unlink(missing_ok=True)
        try:
            Path(tmp.name).unlink(missing_ok=True)
        except Exception:
            pass


def main():
    no_say, no_play, text = _parse_args(sys.argv[1:])
    if not text:
        print("사용법: qwen_tts_speak.py [--no-say] [--no-play] <텍스트>")
        sys.exit(1)

    wav = _generate(text)
    if wav is None:
        sys.exit(1)

    _send_to_ui(wav)
    if not no_play:
        _play(wav)


if __name__ == "__main__":
    main()
