"""app_launcher.py - Windows 앱 실행 / URL 열기 / 카카오톡 메시지 / JARVIS 부팅 시퀀스

macOS 원본(open -a / osascript / afplay / pbcopy)을 Windows 로 포팅.
"""

import os
import sys
import shutil
import subprocess

from . import platform_utils as plat


def find_chrome() -> str | None:
    """Windows 에서 Chrome 실행 파일 경로를 찾는다. 없으면 None."""
    candidates = [
        os.path.expandvars(r"%ProgramFiles%\Google\Chrome\Application\chrome.exe"),
        os.path.expandvars(r"%ProgramFiles(x86)%\Google\Chrome\Application\chrome.exe"),
        os.path.expandvars(r"%LocalAppData%\Google\Chrome\Application\chrome.exe"),
    ]
    for path in candidates:
        if os.path.exists(path):
            return path
    which = shutil.which("chrome")
    return which


class AppLauncher:
    """Windows 앱 실행 및 URL 열기"""

    # 자주 쓰는 앱 이름 매핑 (한국어 → Windows 실행파일/앱 이름)
    # plat.open_app() 는 셸의 'start' 로 실행하므로 실행파일명 또는 등록된 앱 이름이면 된다.
    APP_MAP = {
        '크롬': 'chrome',
        '엣지': 'msedge',
        '익스플로러': 'explorer',
        '터미널': 'wt',            # Windows Terminal (없으면 cmd)
        '명령어': 'cmd',
        '슬랙': 'slack',
        '카카오톡': 'KakaoTalk',
        '메모장': 'notepad',
        '메모': 'notepad',
        '파일탐색기': 'explorer',
        '탐색기': 'explorer',
        '설정': 'ms-settings:',
        'vscode': 'code',
        '코드': 'code',
        '디스코드': 'discord',
        '텔레그램': 'telegram',
        '줌': 'zoom',
        '계산기': 'calc',
        '음악': None,              # URL 로 처리 (Spotify Web 대체 가능)
        '유튜브': None,
        '아마존': None,
        '쿠팡': None,
        '네이버': None,
        '구글': None,
    }

    # URL 매핑
    URL_MAP = {
        '유튜브': 'https://www.youtube.com',
        '아마존': 'https://www.amazon.com',
        '쿠팡': 'https://www.coupang.com',
        '네이버': 'https://www.naver.com',
        '구글': 'https://www.google.com',
        '깃허브': 'https://github.com',
        '지메일': 'https://mail.google.com',
        '인스타': 'https://www.instagram.com',
        '음악': 'https://music.youtube.com',
    }

    # 명령 응답 텍스트 — 텍스트만 등록하면 TTS 자동 생성
    RESPONSE_MAP = {
        'music_play': '네, 음악을 재생하겠습니다, sir.',
        'welcome_home': 'Welcome home, sir.',
        'system_online_final': 'All systems are fully operational, sir! What shall I prepare for you today?',
        'kakao_sent': '카카오톡으로 요청하신 메시지를 전달했습니다, sir.',
        'chrome_open': '크롬을 실행하겠습니다, sir.',
        'youtube_open': '유튜브를 열겠습니다, sir.',
    }

    @classmethod
    def _jarvis_send(cls, msg_type, value):
        """JARVIS UI 로 WebSocket 메시지 전송 (jarvis_send 모듈 사용)."""
        try:
            jarvis_send = os.path.join(os.path.dirname(__file__), "jarvis_send.py")
            if os.path.exists(jarvis_send):
                subprocess.run(
                    [sys.executable, jarvis_send, msg_type, value],
                    capture_output=True,
                )
        except Exception:
            pass

    @classmethod
    def _play_preset_sound(cls, filename: str) -> None:
        sounds_dir = os.path.join(os.path.dirname(__file__), "static", "sounds")
        path = os.path.join(sounds_dir, filename)
        plat.play_sound(path, rate=1.4, blocking=True)

    @classmethod
    def _speak_response(cls, response_key: str) -> None:
        """응답 텍스트로 음성 재생 + JARVIS UI 텍스트 표시. TTS 파일 없으면 자동 생성."""
        text = cls.RESPONSE_MAP.get(response_key, '')
        if not text:
            return

        sounds_dir = os.path.join(os.path.dirname(__file__), "static", "sounds")
        os.makedirs(sounds_dir, exist_ok=True)
        path = os.path.join(sounds_dir, f'{response_key}.wav')

        if not os.path.exists(path):
            try:
                import urllib.request
                import json
                data = json.dumps({'text': text, 'voice': 'clone:jarvis', 'speed': 1.0}).encode()
                req = urllib.request.Request('http://localhost:9093/generate', data=data,
                                             headers={'Content-Type': 'application/json'})
                resp = urllib.request.urlopen(req, timeout=30)
                with open(path, 'wb') as f:
                    f.write(resp.read())
            except Exception:
                # Qwen TTS 서버 없으면 로컬 SAPI TTS 로 대체
                cls._jarvis_send("state", "tts_playing")
                cls._jarvis_send("output", text)
                try:
                    from .tts_reader import tts_reader
                    tts_reader.speak(text)
                except Exception:
                    pass
                cls._jarvis_send("state", "idle")
                return

        if os.path.exists(path):
            cls._jarvis_send("state", "tts_playing")
            cls._jarvis_send("output", text)
            plat.play_sound(path, rate=1.4, blocking=True)
            cls._jarvis_send("state", "idle")

    @classmethod
    def launch_app(cls, app_name: str, move_window: bool = False) -> bool:
        """앱 실행 또는 포커스."""
        return plat.open_app(app_name)

    @classmethod
    def open_url(cls, url: str) -> bool:
        """기본 브라우저에서 URL 열기."""
        return plat.open_url(url)

    @classmethod
    def open_chrome_extension(cls, extension_url: str) -> bool:
        return cls.open_url(extension_url)

    @classmethod
    def send_kakao_message(cls, friend_name: str, message: str, auto_send: bool = False) -> dict:
        """카카오톡(Windows)에서 친구를 찾아 메시지 입력 (best-effort).

        Windows 카카오톡은 Ctrl+F 로 친구 검색이 가능하다.
        앱 UI 변경에 따라 동작이 달라질 수 있는 자동화이다.
        """
        import time
        from pynput.keyboard import Controller, Key

        kb = Controller()

        def clipboard_paste(text):
            plat.copy_to_clipboard(text)
            time.sleep(0.3)
            kb.press(Key.ctrl)
            kb.press('v')
            kb.release('v')
            kb.release(Key.ctrl)

        try:
            # 1. 카카오톡 창을 포그라운드로
            if plat.IS_WINDOWS:
                try:
                    import win32gui  # type: ignore

                    def _find(hwnd, acc):
                        title = win32gui.GetWindowText(hwnd)
                        if title and ('카카오톡' in title or 'KakaoTalk' in title):
                            acc.append(hwnd)
                    found = []
                    win32gui.EnumWindows(_find, found)
                    if found:
                        plat._restore_foreground(found[0])
                    else:
                        plat.open_app('KakaoTalk')
                except Exception:
                    plat.open_app('KakaoTalk')
            else:
                plat.open_app('KakaoTalk')
            time.sleep(2)

            # 2. 친구 검색 (Ctrl+F)
            kb.press(Key.ctrl)
            kb.press('f')
            kb.release('f')
            kb.release(Key.ctrl)
            time.sleep(1)

            # 3. 친구 이름 입력
            clipboard_paste(friend_name)
            time.sleep(1)

            # 4. 첫 번째 결과 선택 → 채팅방 진입
            kb.press(Key.enter)
            kb.release(Key.enter)
            time.sleep(1)

            # 5. 메시지 입력
            clipboard_paste(message)

            # 6. 전송
            if auto_send:
                time.sleep(0.3)
                kb.press(Key.enter)
                kb.release(Key.enter)
                return {"success": True, "action": "kakao_sent", "target": friend_name}

            return {"success": True, "action": "kakao_ready", "target": friend_name}

        except Exception as e:  # noqa: BLE001
            return {"success": False, "action": "kakao_error", "target": str(e)}

    @classmethod
    def handle_command(cls, text: str) -> dict:
        """음성 명령 텍스트 파싱 → 앱 실행, URL 열기, 카카오톡 메시지 등."""
        import re
        text = text.strip()
        text_lower = text.lower()

        # 카카오톡 메시지 패턴
        kakao_pattern = re.search(r'(?:카카오톡|카톡)(?:에서)?\s+(.+?)(?:에게|한테)\s+(.+?)(?:\s*(?:보내|전해|라고|발송|문자))', text)
        if kakao_pattern:
            friend = kakao_pattern.group(1).strip()
            message = kakao_pattern.group(2).strip()
            return cls.send_kakao_message(friend, message, auto_send=True)

        # 유튜브 검색/재생 패턴
        yt_pattern = re.search(r'유튜브\s*(?:에서|가서|에)?\s*(.+?)(?:\s*(?:검색|틀어|재생|보여|찾아))', text)
        if yt_pattern:
            query = yt_pattern.group(1).strip()
            url = f'https://www.youtube.com/results?search_query={query.replace(" ", "+")}'
            cls.open_url(url)
            return {"success": True, "action": "youtube_search", "target": query}

        action_words = ['열어', '실행', '켜줘', '켜봐', '가줘', '가봐', '보여줘', '틀어', '이동']
        has_action = any(w in text_lower for w in action_words)

        if ('음악' in text_lower or '뮤직' in text_lower) and has_action:
            import threading
            cls.open_url(cls.URL_MAP['음악'])
            threading.Thread(target=cls._play_preset_sound, args=('music_play.wav',), daemon=True).start()
            return {"success": True, "action": "launch_app_voice", "target": "음악"}

        if has_action:
            for keyword, url in cls.URL_MAP.items():
                if keyword in text_lower:
                    cls.open_url(url)
                    return {"success": True, "action": "open_url", "target": keyword}
            for keyword, app_name in cls.APP_MAP.items():
                if keyword in text_lower and app_name is not None:
                    success = cls.launch_app(app_name)
                    return {"success": success, "action": "launch_app", "target": keyword}

        if '온라인' in text_lower or ('시스템' in text_lower and '온라인' in text_lower):
            import threading
            threading.Thread(target=cls.jarvis_online, daemon=True).start()
            return {"success": True, "action": "jarvis_online", "target": "system"}

        return {"success": False, "action": "unknown", "target": text}

    @classmethod
    def jarvis_online(cls):
        """자비스 온라인 시퀀스: welcome → 부팅 UI → 완료 음성"""
        import time

        sounds_dir = os.path.join(os.path.dirname(__file__), "static", "sounds")
        welcome = os.path.join(sounds_dir, "welcome_home.wav")
        system_online = os.path.join(sounds_dir, "system_online_final.wav")

        # 0. JARVIS UI 를 Chrome 앱 모드 + 전체화면으로 실행
        chrome = find_chrome()
        try:
            if chrome:
                subprocess.Popen([
                    chrome,
                    "--app=http://localhost:8767",
                    "--user-data-dir=" + os.path.expanduser("~/.chrome-jarvis-ui"),
                    "--start-fullscreen",
                    "--window-position=0,0",
                ])
            else:
                plat.open_url("http://localhost:8767")
        except Exception:
            plat.open_url("http://localhost:8767")
        time.sleep(3)

        cls._jarvis_send("state", "tts_playing")
        if os.path.exists(welcome):
            plat.play_sound_async(welcome, rate=1.4)
            time.sleep(2)
        cls._jarvis_send("state", "idle")

        cls._jarvis_send("ui_action", "system_boot")

        time.sleep(3.5)
        cls._jarvis_send("state", "tts_playing")
        if os.path.exists(system_online):
            plat.play_sound(system_online, rate=1.4, blocking=True)
        cls._jarvis_send("state", "idle")


if __name__ == "__main__":
    if len(sys.argv) > 1:
        text = " ".join(sys.argv[1:])
        result = AppLauncher.handle_command(text)
        print(f"결과: {result}")
