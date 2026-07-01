#!/usr/bin/env python3
"""Claude Code Hook — 도구 사용 시각화 (Pre/PostToolUse, 크로스 플랫폼).

macOS 원본 jarvis_code_hook.sh 의 Windows/크로스 플랫폼 포팅.
~/.whisperflow_youtube_tts (촬영 모드) 활성화 시에만 동작한다.

Claude Code settings.json 예시:
    "PreToolUse": [
      { "hooks": [ { "type": "command",
        "command": "python \"C:/path/to/Javis_window/hooks/jarvis_code_hook.py\"" } ] }
    ]
"""

import os
from pathlib import Path

from _hook_common import read_stdin_json, jarvis_send


def _basename(path: str) -> str:
    if not path:
        return ""
    return os.path.basename(path.rstrip("/\\"))


def build_code_action(data: dict) -> str:
    """도구 사용 정보를 JARVIS UI code_action 문자열로 변환."""
    tool = data.get("tool_name", "")
    inp = data.get("tool_input", {}) or {}

    def clip(s, n):
        return (str(s)[:n]).replace("\n", " ")

    if tool == "Edit":
        path = _basename(inp.get("file_path", ""))
        old = clip(inp.get("old_string", ""), 80)
        new = clip(inp.get("new_string", ""), 80)
        return f"EDITING|{path}|- {old}|+ {new}"
    if tool == "Write":
        path = _basename(inp.get("file_path", ""))
        content = clip(inp.get("content", ""), 100)
        return f"WRITING|{path}|{content}"
    if tool == "Read":
        return f"READING|{_basename(inp.get('file_path', ''))}|"
    if tool == "Bash":
        return f"EXECUTING|bash|{clip(inp.get('command', ''), 100)}"
    if tool == "Grep":
        pattern = inp.get("pattern", "")
        path = _basename(inp.get("path", "")) if inp.get("path") else "*"
        return f'SEARCHING|"{pattern}"|in {path}'
    if tool == "Glob":
        return f"SCANNING|{inp.get('pattern', '')}|"
    if tool == "Agent":
        return f"AGENT|{clip(inp.get('description', ''), 60)}|"
    if tool:
        return f"{tool.upper()}||"
    return ""


def main():
    # 촬영 모드 플래그가 있을 때만 동작
    if not (Path.home() / ".whisperflow_youtube_tts").exists():
        return
    data = read_stdin_json()
    action = build_code_action(data)
    if action:
        jarvis_send("code_action", action)


if __name__ == "__main__":
    main()
