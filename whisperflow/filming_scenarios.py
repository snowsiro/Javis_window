"""
filming_scenarios.py - 유튜브 촬영용 고정 시나리오 (Windows 포팅)

촬영 모드에서만 동작. 키워드 매칭 → 액션 실행 + 음성 응답 + JARVIS UI 텍스트.
"""

import os
import re
import sys
import subprocess
import threading

from . import platform_utils as plat


# 경로 설정
_BASE_DIR = os.path.dirname(__file__)
_SOUNDS_DIR = os.path.join(_BASE_DIR, "static", "sounds")
_JARVIS_SEND = os.path.join(_BASE_DIR, "jarvis_send.py")


def _send(msg_type, value):
    if os.path.exists(_JARVIS_SEND):
        subprocess.run([sys.executable, _JARVIS_SEND, msg_type, value], capture_output=True)


_always_listen_ref = None  # app.py에서 설정


def _play_and_display(sound_file, text):
    """음성 재생 + JARVIS UI 텍스트 표시 + speaking 파형 (마이크 일시 중지)"""
    path = os.path.join(_SOUNDS_DIR, sound_file)
    if not os.path.exists(path):
        return
    if _always_listen_ref:
        _always_listen_ref.mute()
    _send("state", "tts_playing")
    _send("output", text)
    plat.play_sound(path, rate=1.4, blocking=True)
    _send("state", "idle")
    import time
    time.sleep(0.5)
    if _always_listen_ref:
        _always_listen_ref.unmute()


def _async_play(sound_file, text):
    threading.Thread(target=_play_and_display, args=(sound_file, text), daemon=True).start()


# ============================================================
#  시나리오 정의
# ============================================================

def _handle_system_online(text):
    """시스템 온라인 → 부팅 시퀀스"""
    from .app_launcher import AppLauncher
    threading.Thread(target=AppLauncher.jarvis_online, daemon=True).start()
    return True


def _handle_music(text):
    """음악 틀어줘 → 음악 서비스 + 음성"""
    plat.open_url("https://music.youtube.com")
    _async_play("music_play.wav", "Playing music, sir.")
    return True


def _handle_youtube(text):
    """유튜브 열어줘 → 유튜브 + 음성"""
    yt_search = re.search(r'유튜브\s*(?:에서|가서|에)?\s*(.+?)(?:\s*(?:검색|틀어|재생|보여|찾아))', text)
    if yt_search:
        query = yt_search.group(1).strip()
        url = f'https://www.youtube.com/results?search_query={query.replace(" ", "+")}'
    else:
        url = 'https://www.youtube.com'
    plat.open_url(url)
    _async_play("youtube_open.wav", "Opening YouTube, sir.")
    return True


def _handle_kakao_open(text):
    """카카오톡 열어줘 → KakaoTalk 실행 + 음성"""
    plat.open_app("KakaoTalk")
    _async_play("kakao_open.wav", "Opening KakaoTalk, sir.")
    return True


def _handle_chrome(text):
    """크롬 열어줘 → Chrome + 음성"""
    plat.open_app("chrome")
    _async_play("chrome_open.wav", "Opening Chrome, sir.")
    return True


def _handle_kakao(text):
    """카톡 [이름]에게 [메시지] 보내줘"""
    pattern = re.search(r'(?:카카오톡|카톡)(?:에서|에)?\s+(.+?)(?:에게|한테)\s+(.+?)(?:\s*(?:보내|전해|라고|발송|문자))', text)
    if not pattern:
        return False
    friend = pattern.group(1).strip()
    message = pattern.group(2).strip()
    from .app_launcher import AppLauncher
    AppLauncher.send_kakao_message(friend, message, auto_send=True)
    _async_play("kakao_sent.wav", "Message sent via KakaoTalk, sir.")
    return True


def _handle_camera_on(text):
    """카메라 켜줘"""
    _send("ui_action", "browser_boot")
    _async_play("camera_on.wav", "Camera activated, sir.")
    return True


def _handle_camera_off(text):
    """카메라 꺼줘"""
    _send("browser_stop", "")
    _async_play("camera_off.wav", "Camera deactivated, sir.")
    return True


# ============================================================
#  시나리오 매칭 테이블
# ============================================================

SCENARIOS = [
    (lambda t: '온라인' in t or '올라인' in t or 'online' in t, _handle_system_online),
    (lambda t: ('카카오톡' in t or '카톡' in t) and ('에게' in t or '한테' in t), _handle_kakao),
    (lambda t: '유튜브' in t and any(w in t for w in ['열어', '실행', '켜', '가', '틀어', '검색', '재생']), _handle_youtube),
    (lambda t: ('음악' in t or '뮤직' in t) and any(w in t for w in ['틀어', '들어', '실행', '켜', '열어', '재생']), _handle_music),
    (lambda t: ('카카오톡' in t or '카톡' in t) and any(w in t for w in ['열어', '실행', '켜']), _handle_kakao_open),
    (lambda t: '크롬' in t and any(w in t for w in ['열어', '실행', '켜']), _handle_chrome),
    (lambda t: '카메라' in t and any(w in t for w in ['켜', '열어', '활성', '시작']), _handle_camera_on),
    (lambda t: '카메라' in t and any(w in t for w in ['꺼', '닫', '종료', '중지']), _handle_camera_off),
]


def _handle_general(text):
    """시나리오 매칭 안 된 일반 명령 → Claude CLI로 처리"""
    def _run():
        try:
            from .assistant_session import resolve_claude_cmd
            prompt = f'[자비스] 다음 질문에 자비스처럼 간결하게 1~3문장으로 답변해. 마크다운 금지. sir로 끝내.: {text}'
            claude = resolve_claude_cmd()
            result = subprocess.run(
                [claude, "-p", prompt],
                capture_output=True, text=True, timeout=120
            )
            response = result.stdout.strip()
            if response:
                if _always_listen_ref:
                    _always_listen_ref.mute()
                _send("state", "tts_playing")
                _send("output", response)

                # Qwen TTS 로 음성 재생 (없으면 로컬 SAPI)
                played = False
                try:
                    import urllib.request
                    import json
                    import tempfile
                    data = json.dumps({'text': response, 'voice': 'clone:jarvis', 'speed': 1.0}).encode()
                    req = urllib.request.Request('http://localhost:9093/generate', data=data,
                                                 headers={'Content-Type': 'application/json'})
                    resp = urllib.request.urlopen(req, timeout=30)
                    audio = resp.read()
                    tmp = tempfile.NamedTemporaryFile(suffix='.wav', delete=False)
                    tmp.write(audio)
                    tmp.close()
                    plat.play_sound(tmp.name, rate=1.4, blocking=True)
                    os.unlink(tmp.name)
                    played = True
                except Exception:
                    played = False
                if not played:
                    try:
                        from .tts_reader import tts_reader
                        tts_reader.speak(response)
                    except Exception:
                        pass

                _send("state", "idle")
                import time
                time.sleep(0.5)
                if _always_listen_ref:
                    _always_listen_ref.unmute()
        except Exception as e:  # noqa: BLE001
            print(f"[촬영시나리오] Claude CLI 오류: {e}")

    threading.Thread(target=_run, daemon=True).start()
    return True


def handle(text: str) -> bool:
    """촬영 시나리오 매칭 및 실행. 매칭 안 되면 Claude CLI로 처리."""
    text_lower = text.strip().lower()
    for condition, handler in SCENARIOS:
        if condition(text_lower):
            try:
                return handler(text)
            except Exception:
                return False
    return _handle_general(text)
