"""Claude Code 훅 공통 유틸 (크로스 플랫폼).

- 저장소 루트를 sys.path 에 추가해 whisperflow 패키지를 import 가능하게 한다.
- Claude Code 훅 stdin JSON 을 파싱해 응답 텍스트/도구 정보를 추출한다.
- jarvis_send.py 로 JARVIS UI 에 메시지를 전송한다.
"""

import json
import os
import sys
import subprocess

# 저장소 루트 = hooks/ 의 부모
REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if REPO_ROOT not in sys.path:
    sys.path.insert(0, REPO_ROOT)

JARVIS_SEND = os.path.join(REPO_ROOT, "whisperflow", "jarvis_send.py")


def read_stdin_json() -> dict:
    """stdin 을 JSON 으로 파싱. 실패 시 {'_raw': <원문>} 반환."""
    try:
        raw = sys.stdin.read()
    except Exception:
        return {}
    if not raw:
        return {}
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        return {"_raw": raw}


def extract_last_assistant_text(payload: dict) -> str:
    """훅 payload 에서 마지막 assistant 응답 텍스트를 추출한다.

    우선순위:
      1) payload 에 직접 담긴 텍스트 (_raw / response / message)
      2) transcript_path(JSONL) 의 마지막 assistant 메시지
    """
    for key in ("response", "_raw"):
        val = payload.get(key)
        if isinstance(val, str) and val.strip():
            return val.strip()

    transcript = payload.get("transcript_path")
    if transcript and os.path.exists(transcript):
        try:
            last_text = ""
            with open(transcript, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        obj = json.loads(line)
                    except json.JSONDecodeError:
                        continue
                    msg = obj.get("message", obj)
                    if msg.get("role") != "assistant":
                        continue
                    content = msg.get("content", "")
                    if isinstance(content, list):
                        parts = [
                            b.get("text", "")
                            for b in content
                            if isinstance(b, dict) and b.get("type") == "text"
                        ]
                        text = " ".join(p for p in parts if p)
                    else:
                        text = str(content)
                    if text.strip():
                        last_text = text.strip()
            return last_text
        except Exception:
            return ""
    return ""


def jarvis_send(msg_type: str, value: str) -> None:
    """JARVIS UI 로 WebSocket 메시지 전송 (백그라운드)."""
    if not os.path.exists(JARVIS_SEND):
        return
    try:
        subprocess.Popen(
            [sys.executable, JARVIS_SEND, msg_type, value],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
    except Exception:
        pass
