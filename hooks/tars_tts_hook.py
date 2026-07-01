#!/usr/bin/env python3
"""Claude Code Hook — TARS TTS (Stop 이벤트용, 크로스 플랫폼).

macOS 원본 tars_tts_hook.sh 의 Windows/크로스 플랫폼 포팅.
~/.whisperflow_tars_mode 활성화 시 Claude 응답을 TARS 음성으로 변환/재생한다.

흐름:
  1. TARS 모드 플래그 체크
  2. 최신 응답 추출 (transcript_path)
  3. 중복 방지 (해시)
  4. 필러 재생 → Qwen TTS(clone:tars) + TARS_FX 후처리 → 재생
  5. TTS 완료 → 대화 모드 진입 시그널

Claude Code settings.json 예시:
    "Stop": [
      { "hooks": [ { "type": "command",
        "command": "python \"C:/path/to/Javis_window/hooks/tars_tts_hook.py\"" } ] }
    ]
"""

import hashlib
import os
import re
import tempfile
import time
from pathlib import Path

from _hook_common import read_stdin_json, extract_last_assistant_text

# whisperflow 패키지 (REPO_ROOT 는 _hook_common 이 sys.path 에 추가)
from whisperflow import tars_mode
from whisperflow import platform_utils as plat

HASH_FILE = Path(plat.temp_path("whisperflow-tars-last-hash"))
TTS_FLAG = Path(plat.temp_path("whisperflow-tts-playing"))
CONV_CONTINUE = Path(plat.temp_path("whisperflow-conversation-continue"))


def split_sentences(text: str) -> list[str]:
    """문장 분리 후 2~3문장(또는 150자)씩 묶는다."""
    sentences = [s.strip() for s in re.split(r'(?<=[.!?])\s+', text) if s.strip()]
    if not sentences:
        return [text]
    chunks: list[str] = []
    current = ""
    count = 0
    for s in sentences:
        current = (current + " " + s).strip() if current else s
        count += 1
        if count >= 3 or len(current) >= 150:
            chunks.append(current)
            current = ""
            count = 0
    if current:
        if chunks and len(current) < 50:
            chunks[-1] += " " + current
        else:
            chunks.append(current)
    return chunks if chunks else [text]


def main():
    if not tars_mode.is_tars_mode():
        return

    # JSONL 기록 대기
    time.sleep(0.5)

    payload = read_stdin_json()
    response = extract_last_assistant_text(payload)
    if not response:
        return

    # 중복 방지 (해시)
    current_hash = hashlib.md5(response.encode("utf-8")).hexdigest()
    try:
        if HASH_FILE.exists() and HASH_FILE.read_text().strip() == current_hash:
            return
        HASH_FILE.write_text(current_hash)
    except Exception:
        pass

    # TARS 필러 재생 (있으면)
    tars_mode.play_filler_sync()

    # TTS 재생 중 플래그
    try:
        TTS_FLAG.touch()
    except Exception:
        pass

    try:
        for chunk in split_sentences(response):
            wav_bytes = tars_mode.tars_tts_generate_and_fx(chunk)
            if not wav_bytes:
                continue
            tmp = tempfile.NamedTemporaryFile(suffix=".wav", delete=False)
            try:
                tmp.write(wav_bytes)
                tmp.close()
                plat.play_sound(tmp.name, blocking=True)
            finally:
                try:
                    os.unlink(tmp.name)
                except OSError:
                    pass
    finally:
        TTS_FLAG.unlink(missing_ok=True)

    # TTS 완료 → 대화 모드 진입 시그널
    try:
        CONV_CONTINUE.touch()
    except Exception:
        pass


if __name__ == "__main__":
    main()
