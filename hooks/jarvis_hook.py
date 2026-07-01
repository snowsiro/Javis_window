#!/usr/bin/env python3
"""Claude Code Hook — JARVIS UI 에 응답 전송 (Stop 이벤트용, 크로스 플랫폼).

macOS 원본 jarvis_hook.sh 의 Windows/크로스 플랫폼 포팅.

Claude Code settings.json 예시:
    "hooks": {
      "Stop": [
        { "hooks": [ { "type": "command",
          "command": "python \"C:/path/to/Javis_window/hooks/jarvis_hook.py\"" } ] }
      ]
    }
"""

from _hook_common import read_stdin_json, extract_last_assistant_text, jarvis_send


def main():
    payload = read_stdin_json()
    response = extract_last_assistant_text(payload)
    if not response:
        return
    # UI 표시용으로 처음 500자만 전송
    jarvis_send("output", response[:500])


if __name__ == "__main__":
    main()
