#!/usr/bin/env python3
"""
serve.py — JARVIS 음성 TTS 서버 (Windows / 크로스 플랫폼)

WhisperFlow(JARVIS) 앱이 기대하는 Qwen TTS 서버와 동일한 API 를 제공한다:

    GET  /health    → 200 "ok"
    POST /generate  → JSON {text, voice, speed, seed, instruct} → WAV 바이트

백엔드: edge-tts (Microsoft Edge 신경망 음성)
  - GPU 불필요, 모델 다운로드 없음, 즉시 동작
  - 단, 마이크로소프트 음성 서비스를 호출하므로 인터넷 연결 필요
  - 기본 음성: 영어 = en-GB-RyanNeural (영국 남성 — 자비스 억양),
              한국어 = ko-KR-InJoonNeural (남성)

음성 변경: 같은 폴더의 voices.json 을 수정 (없으면 기본값 사용)
    {"ko": "ko-KR-InJoonNeural", "en": "en-GB-RyanNeural"}

실행:
    python serve.py --port 9093
(앱이 QWEN_TTS_DIR 환경변수를 보고 자동 실행해 주므로 보통 직접 실행할 일 없음)
"""

import argparse
import asyncio
import io
import json
import sys
import wave
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

# ----------------------------------------------------------------------
# 언어별 기본 음성 (Microsoft Edge 신경망 음성)
# ----------------------------------------------------------------------
DEFAULT_VOICES = {
    "ko": "ko-KR-InJoonNeural",   # 한국어 남성
    "en": "en-GB-RyanNeural",     # 영국 남성 (자비스 느낌)
    "ja": "ja-JP-KeitaNeural",    # 일본어 남성
    "zh": "zh-CN-YunxiNeural",    # 중국어 남성
}

_CONFIG_PATH = Path(__file__).parent / "voices.json"


def load_voices() -> dict:
    """voices.json 이 있으면 기본값 위에 덮어쓴다."""
    voices = dict(DEFAULT_VOICES)
    if _CONFIG_PATH.exists():
        try:
            user = json.loads(_CONFIG_PATH.read_text(encoding="utf-8"))
            voices.update({k: v for k, v in user.items() if isinstance(v, str)})
        except Exception as e:  # noqa: BLE001
            print(f"[voices.json] 파싱 실패, 기본 음성 사용: {e}")
    return voices


VOICES = load_voices()


def detect_language(text: str) -> str:
    """텍스트의 주요 언어를 유니코드 범위로 감지 (whisperflow 와 동일 로직)."""
    if not text:
        return "en"
    counts = {"ko": 0, "ja": 0, "zh": 0, "en": 0}
    for ch in text:
        cp = ord(ch)
        if 0xAC00 <= cp <= 0xD7A3 or 0x3131 <= cp <= 0x318E:
            counts["ko"] += 1
        elif 0x3040 <= cp <= 0x309F or 0x30A0 <= cp <= 0x30FF:
            counts["ja"] += 1
        elif 0x4E00 <= cp <= 0x9FFF:
            counts["zh"] += 1
        elif ch.isascii() and ch.isalpha():
            counts["en"] += 1
    if counts["ko"] > 0 and counts["zh"] > 0:
        counts["ko"] += counts["zh"]; counts["zh"] = 0
    elif counts["ja"] > 0 and counts["zh"] > 0:
        counts["ja"] += counts["zh"]; counts["zh"] = 0
    best = max(counts, key=counts.get)
    return best if counts[best] > 0 else "en"


def pick_voice(requested: str, text: str) -> str:
    """요청된 voice 값을 실제 edge 음성으로 매핑.

    - "en-GB-RyanNeural" 처럼 edge 음성 이름이 직접 오면 그대로 사용
    - "clone:jarvis" / "clone:tars" 등 원본 규격 값은 언어 자동감지로 매핑
    """
    if requested and "Neural" in requested:
        return requested
    return VOICES.get(detect_language(text), VOICES["en"])


def speed_to_rate(speed: float) -> str:
    """배속(1.4) → edge-tts rate 문자열(+40%)."""
    try:
        pct = int(round((float(speed) - 1.0) * 100))
    except (TypeError, ValueError):
        pct = 0
    pct = max(-50, min(100, pct))
    return f"{'+' if pct >= 0 else ''}{pct}%"


# ----------------------------------------------------------------------
# TTS 생성
# ----------------------------------------------------------------------
async def _edge_generate_mp3(text: str, voice: str, rate: str) -> bytes:
    import edge_tts
    communicate = edge_tts.Communicate(text, voice, rate=rate)
    buf = b""
    async for chunk in communicate.stream():
        if chunk["type"] == "audio":
            buf += chunk["data"]
    return buf


def mp3_to_wav(mp3_bytes: bytes) -> bytes:
    """MP3 → 16bit PCM WAV (miniaudio, ffmpeg 불필요)."""
    import miniaudio
    decoded = miniaudio.decode(
        mp3_bytes, output_format=miniaudio.SampleFormat.SIGNED16
    )
    out = io.BytesIO()
    with wave.open(out, "wb") as wf:
        wf.setnchannels(decoded.nchannels)
        wf.setsampwidth(2)
        wf.setframerate(decoded.sample_rate)
        wf.writeframes(decoded.samples.tobytes())
    return out.getvalue()


def generate_wav(text: str, voice: str, speed: float) -> bytes:
    resolved = pick_voice(voice, text)
    rate = speed_to_rate(speed)
    print(f"[generate] voice={resolved} rate={rate} text={text[:50]!r}")
    mp3 = asyncio.run(_edge_generate_mp3(text, resolved, rate))
    if not mp3:
        raise RuntimeError("edge-tts 가 오디오를 반환하지 않았습니다 (인터넷 연결 확인)")
    return mp3_to_wav(mp3)


# ----------------------------------------------------------------------
# HTTP 서버
# ----------------------------------------------------------------------
class Handler(BaseHTTPRequestHandler):
    def log_message(self, fmt, *args):  # 기본 액세스 로그 억제
        pass

    def _send(self, code: int, body: bytes, content_type: str) -> None:
        self.send_response(code)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        if self.path.rstrip("/") in ("", "/health".rstrip("/"), "/health"):
            self._send(200, b"ok", "text/plain")
        else:
            self._send(404, b"not found", "text/plain")

    def do_POST(self):
        if self.path != "/generate":
            self._send(404, b"not found", "text/plain")
            return
        try:
            length = int(self.headers.get("Content-Length", 0))
            payload = json.loads(self.rfile.read(length).decode("utf-8"))
            text = (payload.get("text") or "").strip()
            if not text:
                self._send(400, b"text is required", "text/plain")
                return
            voice = payload.get("voice", "")
            speed = payload.get("speed", 1.0)
            # seed / instruct 는 원본 규격 호환용으로 받되 사용하지 않음
            wav = generate_wav(text, voice, speed)
            self._send(200, wav, "audio/wav")
        except ImportError as e:
            msg = f"의존성 미설치: {e}. setup_voice.bat 을 실행하세요.".encode("utf-8")
            print(msg.decode("utf-8"))
            self._send(500, msg, "text/plain")
        except Exception as e:  # noqa: BLE001
            msg = f"TTS 생성 실패: {e}".encode("utf-8")
            print(msg.decode("utf-8"))
            self._send(500, msg, "text/plain")


def main():
    parser = argparse.ArgumentParser(description="JARVIS TTS server")
    parser.add_argument("--port", type=int, default=9093)
    args = parser.parse_args()

    try:
        import edge_tts  # noqa: F401
        import miniaudio  # noqa: F401
    except ImportError as e:
        print(f"[오류] 의존성 미설치: {e}")
        print("설치: pip install edge-tts miniaudio  (또는 setup_voice.bat 실행)")
        sys.exit(1)

    server = ThreadingHTTPServer(("127.0.0.1", args.port), Handler)
    print(f"[JARVIS TTS] http://127.0.0.1:{args.port} 대기 중 "
          f"(en={VOICES['en']}, ko={VOICES['ko']})")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n[JARVIS TTS] 종료")


if __name__ == "__main__":
    main()
