"""WhisperFlow (JARVIS) 메인 앱 — Windows 시스템 트레이 버전.

macOS 의 rumps 메뉴바 앱을 pystray 시스템 트레이 앱으로 포팅했다.
모든 기능(녹음/변환/TTS/드라이브·도서관·촬영 모드/제스처/Hue/JARVIS UI)을 유지한다.
"""

import sys
import os
import json
import datetime
import threading
import subprocess
import webbrowser
from pathlib import Path

import pystray
from PIL import Image, ImageDraw

from . import platform_utils as plat
from .config import config
from .audio_recorder import AudioRecorder
from .transcriber import Transcriber
from .hotkey_manager import HotkeyManager
from .text_output import TextOutput
from .history_manager import history_manager
from .tts_reader import tts_reader

LOG_FILE = plat.temp_path("whisperflow.log")
TTS_FLAG_PATH = Path(plat.temp_path("whisperflow-tts-playing"))
CAMERA_FRAME_PATH = plat.temp_path("jarvis_camera_latest.jpg")


def log(msg):
    """파일과 콘솔에 로그 출력"""
    timestamp = datetime.datetime.now().strftime("%H:%M:%S")
    line = f"[{timestamp}] {msg}"
    print(line)
    # 윈도우 windowed 실행(pythonw/PyInstaller console=False)에서는
    # sys.stdout 이 None 이므로 flush 를 가드한다.
    try:
        if sys.stdout is not None:
            sys.stdout.flush()
    except Exception:
        pass
    try:
        with open(LOG_FILE, "a", encoding="utf-8") as f:
            f.write(line + "\n")
    except Exception:
        pass


try:
    from .ws_server import WhisperFlowWSServer
except ImportError:
    WhisperFlowWSServer = None

try:
    from .camera_feed import CameraFeed
except ImportError:
    CameraFeed = None

try:
    from .gesture_control import GestureControl
except ImportError:
    GestureControl = None

try:
    from .always_listen import AlwaysListen
except ImportError:
    AlwaysListen = None


# 상태별 트레이 아이콘 색상
_STATE_COLORS = {
    "idle": (0, 200, 255),        # cyan
    "recording": (255, 40, 40),   # red
    "processing": (255, 165, 0),  # orange
}


def _make_icon(color) -> Image.Image:
    """상태 색상의 원형 트레이 아이콘 이미지를 생성한다."""
    size = 64
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    draw.ellipse((8, 8, size - 8, size - 8), fill=color)
    # arc-reactor 느낌의 중앙 링
    draw.ellipse((22, 22, size - 22, size - 22), outline=(255, 255, 255, 220), width=3)
    return img


_ICON_IMAGES = {state: _make_icon(color) for state, color in _STATE_COLORS.items()}


class WhisperFlowApp:
    """시스템 트레이 앱 클래스"""

    JARVIS_ROLEPLAY_FILE = os.path.expanduser("~/.whisperflow_jarvis_roleplay")

    def __init__(self):
        # 트레이 아이콘
        self.icon = pystray.Icon(
            "WhisperFlow",
            icon=_ICON_IMAGES["idle"],
            title="WhisperFlow (JARVIS)",
        )
        # 알림을 트레이 아이콘으로 연결
        plat.set_notifier(self._notify)

        # WebSocket 서버 초기화 (JARVIS UI)
        try:
            if WhisperFlowWSServer is not None:
                self.ws_server = WhisperFlowWSServer()
                self.ws_server._on_remote_record = self._handle_remote_record
                self.ws_server._on_conversation_continue = self.enter_conversation_mode
                self.ws_server._on_chat_tts = self._handle_chat_tts
                self.ws_server._on_tts_interrupt = self._handle_tts_interrupt
                self.ws_server.start()
            else:
                self.ws_server = None
                log("[WS] websockets 모듈 미설치 - WebSocket 서버 비활성화")
        except Exception as e:  # noqa: BLE001
            self.ws_server = None
            log(f"[WS] 서버 초기화 실패 (무시): {e}")

        # Qwen TTS 서버 자동 시작
        self._start_qwen_tts_server()

        # 컴포넌트 초기화
        self.recorder = AudioRecorder(
            on_recording_start=self._on_recording_start,
            on_recording_stop=self._on_recording_stop,
            on_audio_level=self._on_audio_level_simple,
        )
        self.transcriber = Transcriber(
            on_transcription_start=self._on_transcription_start,
            on_transcription_done=self._on_transcription_done,
            on_transcription_error=self._on_transcription_error,
        )
        self.hotkey_manager = HotkeyManager(
            on_hold_start=self._on_hotkey_start,
            on_hold_end=self._on_hotkey_end,
            on_tts_trigger=self._on_tts_trigger,
        )
        self.text_output = TextOutput()

        self.camera_feed = None
        self.gesture_control = None
        self.gesture_proc = None
        self._gesture_timer = None
        self.always_listen = None

        self._recording_lock = threading.Lock()
        self._remote_recording = False

        import atexit
        atexit.register(self._stop_gesture_proc)

        # 메뉴 구성
        self.icon.menu = self._build_menu()

        # 초기 TTS 속도
        tts_reader.set_rate(config.tts_rate)

        # 단축키 리스닝 시작
        self.hotkey_manager.start()

        # 드라이브 모드가 켜져있으면 상시 청취 자동 시작
        if (Path.home() / ".whisperflow_auto_tts").exists():
            self._start_always_listen(skip_boot_wait=True)
            log("[TTS] 드라이브 모드 자동 시작 (이전 세션 유지)")

    # ------------------------------------------------------------------
    # 트레이 헬퍼
    # ------------------------------------------------------------------
    def _notify(self, title: str, message: str) -> None:
        try:
            self.icon.notify(message, title)
        except Exception:
            log(f"[알림] {title}: {message}")

    def _set_state_icon(self, state: str) -> None:
        """트레이 아이콘을 상태에 맞게 변경."""
        img = _ICON_IMAGES.get(state)
        if img is not None:
            try:
                self.icon.icon = img
            except Exception:
                pass

    # ------------------------------------------------------------------
    # 모드 플래그 헬퍼
    # ------------------------------------------------------------------
    @staticmethod
    def _flag(path: Path) -> bool:
        return path.exists()

    def _drive_on(self) -> bool:
        return (Path.home() / ".whisperflow_auto_tts").exists()

    def _library_on(self) -> bool:
        return (Path.home() / ".whisperflow_library_tts").exists()

    def _shoot_on(self) -> bool:
        return ((Path.home() / ".whisperflow_youtube_tts").exists()
                and Path(self.JARVIS_ROLEPLAY_FILE).exists())

    def _hue_on(self) -> bool:
        return bool(self.ws_server and self.ws_server._hue._config.get("enabled", True))

    def _current_hotkey_keys(self) -> set:
        return set(config.hotkey.lower().replace(" ", "").split("+"))

    # ------------------------------------------------------------------
    # 메뉴 구성 (pystray)
    # ------------------------------------------------------------------
    def _build_menu(self) -> "pystray.Menu":
        Item = pystray.MenuItem
        Menu = pystray.Menu
        SEP = Menu.SEPARATOR

        # 모델 선택 서브메뉴 (radio)
        model_items = [
            Item(m, self._make_model_cb(m),
                 checked=lambda item, m=m: config.model_size == m, radio=True)
            for m in ["tiny", "base", "small", "medium", "large-v3"]
        ]
        model_menu = Item("모델 선택", Menu(*model_items))

        # 언어 선택 서브메뉴 (radio)
        languages = [
            ("auto", "자동 감지 (한/영 혼합)"),
            ("ko", "한국어"),
            ("en", "English"),
            ("ja", "日本語"),
            ("zh", "中文"),
        ]
        lang_items = [
            Item(name, self._make_lang_cb(code),
                 checked=lambda item, c=code: config.language == c, radio=True)
            for code, name in languages
        ]
        lang_menu = Item("언어 선택", Menu(*lang_items))

        # 단축키 설정 서브메뉴 (multi-select modifiers + Alt 홀드)
        # 내부 키는 KEY_MAP 과 config 호환을 위해 "option"(=Alt)을 사용한다
        modifiers = [
            ("ctrl", "Control (Ctrl)"),
            ("option", "Alt"),
            ("shift", "Shift"),
            ("cmd", "Windows (⊞)"),
        ]
        hotkey_items = [
            Item(name, self._make_modifier_cb(key),
                 checked=lambda item, k=key: k in self._current_hotkey_keys())
            for key, name in modifiers
        ]
        hotkey_items.append(SEP)
        hotkey_items.append(Item(
            "Alt 길게 누르기",
            self._toggle_option_hold,
            checked=lambda item: config.option_hold_enabled,
        ))
        hotkey_menu = Item("단축키 설정", Menu(*hotkey_items))

        # 히스토리 서브메뉴
        history_menu = Item("히스토리", Menu(
            Item("히스토리 저장", self._toggle_history,
                 checked=lambda item: config.history_enabled),
            SEP,
            Item("히스토리 폴더 열기", self._open_history_folder),
            Item("히스토리 전체 삭제", self._clear_history),
        ))

        # TTS 서브메뉴
        rates = [
            (100, "느리게 (100)"),
            (150, "약간 느리게 (150)"),
            (200, "보통 (200)"),
            (250, "약간 빠르게 (250)"),
            (300, "빠르게 (300)"),
        ]
        rate_items = [
            Item(name, self._make_rate_cb(rate),
                 checked=lambda item, r=rate: config.tts_rate == r, radio=True)
            for rate, name in rates
        ]
        qwen_speeds = [
            (1.0, "보통 (1.0x)"),
            (1.2, "약간 빠르게 (1.2x)"),
            (1.4, "빠르게 (1.4x)"),
            (1.6, "매우 빠르게 (1.6x)"),
            (1.8, "최고 빠르게 (1.8x)"),
        ]
        qwen_items = [
            Item(name, self._make_qwen_cb(sp),
                 checked=lambda item, s=sp: config.qwen_tts_speed == s, radio=True)
            for sp, name in qwen_speeds
        ]
        tts_menu = Item("TTS (텍스트 읽기)", Menu(
            Item("TTS 활성화", self._toggle_tts,
                 checked=lambda item: config.tts_enabled),
            SEP,
            Item("읽기 속도", Menu(*rate_items)),
            Item("Qwen TTS 속도", Menu(*qwen_items)),
            Item("빠른 응답 (로컬 TTS 선행)", self._toggle_say_first,
                 checked=lambda item: config.tts_say_first),
            SEP,
            Item("읽기 중지", self._stop_tts),
        ))

        return Menu(
            Item("녹음 시작/중지", self._menu_toggle_recording, default=True),
            SEP,
            Item("🚗 드라이브 모드", self._toggle_auto_tts,
                 checked=lambda item: self._drive_on()),
            Item("📚 도서관 모드", self._toggle_library_tts,
                 checked=lambda item: self._library_on()),
            Item("🎬 JARVIS 촬영 모드", self._toggle_jarvis_shoot_mode,
                 checked=lambda item: self._shoot_on()),
            SEP,
            model_menu,
            lang_menu,
            hotkey_menu,
            history_menu,
            tts_menu,
            Item("자동 엔터", self._toggle_auto_enter,
                 checked=lambda item: config.auto_enter),
            Item("🖐 제스처 컨트롤", self._toggle_gesture_control,
                 checked=lambda item: self.gesture_proc is not None),
            Item("💡 Hue 조명 연동", self._toggle_hue,
                 checked=lambda item: self._hue_on()),
            SEP,
            Item("JARVIS UI 열기", self._open_jarvis_ui),
            SEP,
            Item("종료", self._quit),
        )

    # 콜백 팩토리 (클로저)
    def _make_model_cb(self, model):
        def cb(icon, item):
            self._change_model(model)
        return cb

    def _make_lang_cb(self, code):
        def cb(icon, item):
            self._change_language(code)
        return cb

    def _make_modifier_cb(self, key):
        def cb(icon, item):
            self._toggle_hotkey_modifier(key)
        return cb

    def _make_rate_cb(self, rate):
        def cb(icon, item):
            self._change_tts_rate(rate)
        return cb

    def _make_qwen_cb(self, speed):
        def cb(icon, item):
            self._change_qwen_speed(speed)
        return cb

    # ------------------------------------------------------------------
    # 설정 변경 핸들러
    # ------------------------------------------------------------------
    def _toggle_hotkey_modifier(self, key) -> None:
        keys = self._current_hotkey_keys()
        # 문자 키(r 등)는 유지, modifier 만 토글
        char_keys = {k for k in keys if k not in HotkeyManager.KEY_MAP}
        mods = {k for k in keys if k in HotkeyManager.KEY_MAP}
        if key in mods:
            mods.discard(key)
        else:
            mods.add(key)
        if not mods:
            self._notify("WhisperFlow", "최소 하나의 modifier 키를 선택하세요")
            return
        new_keys = mods | char_keys
        config.hotkey = "+".join(sorted(new_keys))
        config.save()
        self.hotkey_manager.update_modifiers(list(new_keys))
        display = "+".join(k.upper() for k in sorted(new_keys))
        log(f"[설정] 단축키 변경: {display}")
        self._notify("WhisperFlow", f"단축키: {display}")

    def _toggle_option_hold(self, icon, item) -> None:
        enabled = not config.option_hold_enabled
        config.option_hold_enabled = enabled
        config.save()
        self.hotkey_manager.set_option_hold_enabled(enabled)
        status = "활성화" if enabled else "비활성화"
        log(f"[설정] Alt 키 길게 누르기: {status}")
        self._notify("WhisperFlow", f"Alt 키 길게 누르기: {status}")

    def _toggle_history(self, icon, item) -> None:
        config.history_enabled = not config.history_enabled
        config.save()
        status = "활성화" if config.history_enabled else "비활성화"
        log(f"[설정] 히스토리 저장: {status}")
        self._notify("WhisperFlow", f"히스토리 저장: {status}")

    def _open_history_folder(self, icon, item) -> None:
        history_dir = history_manager.get_history_dir()
        log(f"[히스토리] 폴더 열기: {history_dir}")
        plat.open_path(str(history_dir))

    def _clear_history(self, icon, item) -> None:
        count = history_manager.clear_all()
        log(f"[히스토리] {count}개 삭제됨")
        self._notify("WhisperFlow", f"히스토리 {count}개 삭제됨")

    def _change_language(self, new_lang) -> None:
        log(f"[설정] 언어 변경: {config.language} → {new_lang}")
        config.language = new_lang
        config.save()
        self._notify("WhisperFlow", f"언어 변경: {new_lang}")

    def _change_model(self, new_model) -> None:
        log(f"[설정] 모델 변경: {config.model_size} → {new_model}")
        config.model_size = new_model
        config.save()
        self.transcriber.reload_model()
        self._notify("WhisperFlow", f"모델 변경: {new_model}")

    def _change_tts_rate(self, new_rate) -> None:
        log(f"[설정] TTS 속도 변경: {config.tts_rate} → {new_rate}")
        config.tts_rate = new_rate
        config.save()
        tts_reader.set_rate(new_rate)
        self._notify("WhisperFlow", f"TTS 속도: {new_rate}")

    def _change_qwen_speed(self, new_speed) -> None:
        log(f"[설정] Qwen TTS 속도 변경: {config.qwen_tts_speed} → {new_speed}")
        config.qwen_tts_speed = new_speed
        config.save()
        import re
        hook_path = Path.home() / ".claude" / "hooks" / "qwen_tts_speak.py"
        if hook_path.exists():
            try:
                content = hook_path.read_text(encoding="utf-8")
                content = re.sub(r'SPEED = [\d.]+', f'SPEED = {new_speed}', content)
                hook_path.write_text(content, encoding="utf-8")
            except Exception:
                pass
        self._notify("WhisperFlow", f"Qwen TTS 속도: {new_speed}x")

    def _toggle_auto_enter(self, icon, item) -> None:
        config.auto_enter = not config.auto_enter
        config.save()
        status = "ON" if config.auto_enter else "OFF"
        log(f"[설정] 자동 엔터: {status}")
        self._notify("WhisperFlow", f"자동 엔터: {status}")

    def _toggle_tts(self, icon, item) -> None:
        config.tts_enabled = not config.tts_enabled
        config.save()
        self.hotkey_manager.set_tts_enabled(config.tts_enabled)
        status = "활성화" if config.tts_enabled else "비활성화"
        log(f"[설정] TTS: {status}")
        self._notify("WhisperFlow", f"TTS: {status}")

    def _toggle_say_first(self, icon, item) -> None:
        config.tts_say_first = not config.tts_say_first
        config.save()
        self._update_hook_no_say_flag()
        status = "ON (로컬TTS+Qwen)" if config.tts_say_first else "OFF (Qwen만)"
        log(f"[설정] 빠른 응답: {status}")
        self._notify("WhisperFlow", f"빠른 응답: {status}")

    def _update_hook_no_say_flag(self) -> None:
        settings_path = Path.home() / ".claude" / "settings.json"
        if not settings_path.exists():
            return
        try:
            data = json.loads(settings_path.read_text(encoding="utf-8"))
            hooks = data.get("hooks", {})
            for event_name, event_hooks in hooks.items():
                if not isinstance(event_hooks, list):
                    continue
                for hook in event_hooks:
                    cmd = hook.get("command", "")
                    if "qwen_tts_speak.py" not in cmd:
                        continue
                    if config.tts_say_first:
                        hook["command"] = cmd.replace(" --no-say", "")
                    else:
                        if "--no-say" not in cmd:
                            hook["command"] = cmd + " --no-say"
            settings_path.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
            log("[설정] hooks settings.json 업데이트 완료")
        except Exception as e:  # noqa: BLE001
            log(f"[설정] hooks 업데이트 실패: {e}")

    def _stop_tts(self, icon, item) -> None:
        tts_reader.stop()
        plat.stop_all_sounds()
        self._ws_broadcast("broadcast_state", "idle")
        log("[TTS] 읽기 중지 (메뉴)")

    def _toggle_hue(self, icon, item) -> None:
        enabled = not self._hue_on()
        if self.ws_server:
            self.ws_server._hue._config["enabled"] = enabled
        log(f"[Hue] 조명 연동 {'ON' if enabled else 'OFF'}")
        self._notify("WhisperFlow", f"Hue 조명 연동 {'ON' if enabled else 'OFF'}")

    def _open_jarvis_ui(self, icon, item) -> None:
        webbrowser.open("http://localhost:8767")

    def _quit(self, icon, item) -> None:
        log("[앱] 종료")
        try:
            self.hotkey_manager.stop()
        except Exception:
            pass
        self._stop_always_listen()
        self._stop_gesture_proc()
        if self.ws_server:
            try:
                self.ws_server.stop()
            except Exception:
                pass
        self.icon.stop()

    # ------------------------------------------------------------------
    # 녹음 제어
    # ------------------------------------------------------------------
    def _menu_toggle_recording(self, icon, item) -> None:
        log("[메뉴] 녹음 토글 클릭됨")
        self._toggle_recording()

    def _toggle_recording(self) -> None:
        with self._recording_lock:
            log(f"[앱] _toggle_recording 호출, 현재 녹음 중: {self.recorder.is_recording}")
            if self.recorder.is_recording:
                self.recorder.stop_recording()
            else:
                TextOutput.save_active_app()
                self.recorder.start_recording()

    def _on_hotkey_start(self) -> None:
        with self._recording_lock:
            if self.recorder.is_recording:
                log("[앱] _on_hotkey_start 무시 - 이미 녹음 중")
                return
            TextOutput.save_active_app()
            self.recorder.start_recording()
            if hasattr(self, '_safety_timer') and self._safety_timer:
                self._safety_timer.cancel()
            self._safety_timer = threading.Timer(120.0, self._safety_stop_recording)
            self._safety_timer.daemon = True
            self._safety_timer.start()

    def _safety_stop_recording(self) -> None:
        if self.recorder.is_recording:
            log("[앱] 안전장치 - 120초 초과 자동 녹음 중지")
            self.recorder.stop_recording()

    def _on_hotkey_end(self) -> None:
        with self._recording_lock:
            if hasattr(self, '_safety_timer') and self._safety_timer:
                self._safety_timer.cancel()
                self._safety_timer = None
            if not self.recorder.is_recording:
                log("[앱] _on_hotkey_end 무시 - 이미 녹음 중 아님")
                return
            self.recorder.stop_recording()

    def _handle_remote_record(self, data: dict) -> None:
        action = data.get("action", "toggle")
        log(f"[원격] remote_record 수신: action={action}")
        with self._recording_lock:
            if action == "start":
                if self.recorder.is_recording:
                    return
                self._remote_recording = True
                self.recorder.start_recording()
            elif action == "stop":
                if not self.recorder.is_recording:
                    return
                self.recorder.stop_recording()
            else:
                if self.recorder.is_recording:
                    self.recorder.stop_recording()
                else:
                    self._remote_recording = True
                    self.recorder.start_recording()

    # ------------------------------------------------------------------
    # 녹음/변환 콜백
    # ------------------------------------------------------------------
    def _on_recording_start(self) -> None:
        log("[녹음] 시작")
        self._set_state_icon("recording")
        self._ws_broadcast("broadcast_state", "recording")

    def _on_recording_stop(self, audio_path: str) -> None:
        log(f"[녹음] 종료 - 파일: {audio_path}")
        self._set_state_icon("processing")
        self._ws_broadcast("broadcast_state", "processing")
        self.transcriber.transcribe_async(audio_path)

    def _on_transcription_start(self) -> None:
        log("[변환] 시작 (모델 로딩 중...)")
        self._set_state_icon("processing")

    def _on_transcription_done(self, text: str) -> None:
        log(f"[변환] 완료 - 텍스트: {text}")
        self._set_state_icon("idle")
        if text:
            jarvis_roleplay = Path(self.JARVIS_ROLEPLAY_FILE).exists()
            if jarvis_roleplay:
                from . import filming_scenarios
                self._ws_broadcast("broadcast_transcript", text)
                if filming_scenarios.handle(text):
                    log(f"[촬영시나리오] 매칭: {text[:50]}")
                    self._ws_broadcast("broadcast_state", "idle")
                    return

            drive_mode = self._drive_on()
            if drive_mode and self._handle_camera_command(text):
                self.enter_conversation_mode()
                return

            self._ws_broadcast("broadcast_state", "thinking")
            self._ws_broadcast("broadcast_transcript", text)
        else:
            self._ws_broadcast("broadcast_state", "idle")

        if text:
            if self._remote_recording:
                if self.camera_feed is not None:
                    frame_b64 = self.camera_feed.get_current_frame()
                    if frame_b64:
                        import base64
                        with open(CAMERA_FRAME_PATH, 'wb') as f:
                            f.write(base64.b64decode(frame_b64))
                        text = f"[카메라가 켜져 있음. 이미지 확인이 필요하면: {CAMERA_FRAME_PATH}] {text}"
                        log(f"[카메라] 최신 프레임 저장: {CAMERA_FRAME_PATH}")

                self._remote_recording = False
                plat.copy_to_clipboard(text)
                log(f"[출력] 클립보드 복사 완료: {text[:50]}")
                import time
                time.sleep(0.3)
                plat.paste_to_active(enter=True, restore_hwnd=TextOutput._last_hwnd)
                success = True
                log("[출력] 원격 → 현재 앱 붙여넣기 완료")
            else:
                success = self.text_output.output(text)
            log(f"[출력] 클립보드 복사: {success}")
            if success:
                preview = text[:50] + "..." if len(text) > 50 else text
                self._notify("WhisperFlow", f"클립보드에 복사됨: {preview}")
        else:
            self._notify("WhisperFlow", "변환된 텍스트가 없습니다")

    def _on_transcription_error(self, error: str) -> None:
        log(f"[오류] {error}")
        self._set_state_icon("idle")
        self._ws_broadcast("broadcast_state", "idle")
        self._notify("WhisperFlow 오류", error)

    # ------------------------------------------------------------------
    # WebSocket / 오디오 레벨
    # ------------------------------------------------------------------
    def _ws_broadcast(self, method: str, *args) -> None:
        if self.ws_server is None:
            return
        try:
            getattr(self.ws_server, method)(*args)
        except Exception:
            pass

    def _on_audio_level_simple(self, level: float) -> None:
        self._ws_broadcast("broadcast_audio_level", level)

    def _on_audio_level(self, level: float, low: float = 0, mid: float = 0, high: float = 0) -> None:
        if self.ws_server:
            self.ws_server.broadcast_audio_level(float(level))

    # ------------------------------------------------------------------
    # Qwen TTS 서버 자동 시작
    # ------------------------------------------------------------------
    def _start_qwen_tts_server(self) -> None:
        try:
            import urllib.request
            urllib.request.urlopen('http://localhost:9093/health', timeout=2)
            log("[TTS] Qwen TTS 서버 이미 실행 중")
        except Exception:
            qwen_dir = os.environ.get('QWEN_TTS_DIR')
            if not qwen_dir:
                log("[TTS] QWEN_TTS_DIR 환경변수 미설정, Qwen TTS 서버 자동 시작 스킵")
                return
            if plat.IS_WINDOWS:
                venv_python = os.path.join(qwen_dir, ".venv", "Scripts", "python.exe")
            else:
                venv_python = os.path.join(qwen_dir, ".venv", "bin", "python")
            if not os.path.exists(venv_python):
                venv_python = sys.executable
            serve_script = os.path.join(qwen_dir, "serve.py")
            if os.path.exists(serve_script):
                try:
                    kwargs = {}
                    if plat.IS_WINDOWS:
                        kwargs["creationflags"] = getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
                    else:
                        kwargs["start_new_session"] = True
                    subprocess.Popen(
                        [venv_python, serve_script, "--port", "9093"],
                        stdout=open(plat.temp_path("qwen_tts_server.log"), "a"),
                        stderr=subprocess.STDOUT,
                        **kwargs,
                    )
                    log("[TTS] Qwen TTS 서버 자동 시작")
                except Exception as e:  # noqa: BLE001
                    log(f"[TTS] Qwen TTS 서버 시작 실패: {e}")

    # ------------------------------------------------------------------
    # 채팅 응답 TTS (WebSocket)
    # ------------------------------------------------------------------
    _chat_conv_timer = None
    _chat_conv_lock = threading.Lock()
    _tts_proc = None
    _tts_cancelled = threading.Event()

    def _handle_chat_tts(self, text: str) -> None:
        import random
        self._tts_cancelled.set()
        with self._chat_conv_lock:
            if self._chat_conv_timer:
                self._chat_conv_timer.cancel()
                self._chat_conv_timer = None
        self._tts_cancelled.clear()
        tts_text = text[:500] if len(text) > 500 else text

        def _tts_worker():
            # 1. ack 효과음 전송
            try:
                sounds_dir = Path(__file__).parent / "static" / "sounds"
                ack_files = sorted(sounds_dir.glob("ack_*.wav"))
                if ack_files:
                    ack_file = random.choice(ack_files)
                    import base64
                    ack_b64 = base64.b64encode(ack_file.read_bytes()).decode('utf-8')
                    self.ws_server.broadcast_raw(
                        json.dumps({"type": "tts_audio", "value": ack_b64})
                    )
            except Exception as e:  # noqa: BLE001
                log(f"[TTS] ack sound error: {e}")

            if self._tts_cancelled.is_set():
                return

            # 2. Qwen TTS 생성 (있으면) 아니면 로컬 SAPI
            hook_path = Path.home() / ".claude" / "hooks" / "qwen_tts_speak.py"
            tts_done = False
            if hook_path.exists():
                try:
                    import urllib.request
                    r = urllib.request.urlopen('http://localhost:9093/health', timeout=2)
                    if r.status == 200:
                        cmd = [sys.executable, str(hook_path), "--no-say", "--no-play", tts_text]
                        proc = subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                        self._tts_proc = proc
                        proc.wait(timeout=120)
                        self._tts_proc = None
                        tts_done = True
                except Exception:
                    self._tts_proc = None
                    self._start_qwen_tts_server()

            if self._tts_cancelled.is_set():
                return

            if not tts_done:
                tts_reader.speak(tts_text)

            try:
                self.ws_server.broadcast_raw(json.dumps({"type": "tts_done"}))
            except Exception as e:  # noqa: BLE001
                log(f"[TTS] tts_done broadcast error: {e}")
            self._enter_post_tts_conversation()

        threading.Thread(target=_tts_worker, daemon=True).start()

    def _enter_post_tts_conversation(self) -> None:
        if self.always_listen:
            self.always_listen.enter_conversation_mode()
        self._ws_broadcast("broadcast_state", "recording")
        log("[채팅TTS] 대화 모드 진입")
        if not self.always_listen:
            with self._chat_conv_lock:
                if self._chat_conv_timer:
                    self._chat_conv_timer.cancel()
                self._chat_conv_timer = threading.Timer(10.0, self._on_chat_conversation_end)
                self._chat_conv_timer.daemon = True
                self._chat_conv_timer.start()

    def _on_chat_conversation_end(self) -> None:
        log("[채팅TTS] 대화 모드 타임아웃 → 대기 모드")
        try:
            import base64
            sound_path = Path(__file__).parent / "static" / "sounds" / "standby.wav"
            if sound_path.exists():
                b64 = base64.b64encode(sound_path.read_bytes()).decode('utf-8')
                self.ws_server.broadcast_raw(json.dumps({"type": "tts_audio", "value": b64}))
        except Exception:
            pass
        self._ws_broadcast("broadcast_state", "idle")

    def _handle_tts_interrupt(self) -> None:
        log("[TTS] 인터럽트 수신 — TTS 중단")
        self._tts_cancelled.set()
        if self._tts_proc:
            try:
                self._tts_proc.terminate()
            except Exception:
                pass
        tts_reader.stop()
        plat.stop_all_sounds()
        with self._chat_conv_lock:
            if self._chat_conv_timer:
                self._chat_conv_timer.cancel()
                self._chat_conv_timer = None
        self._ws_broadcast("broadcast_state", "recording")

    def _kill_tts(self) -> None:
        """실행 중인 TTS(로컬/Qwen/효과음)를 즉시 중단."""
        TTS_FLAG_PATH.unlink(missing_ok=True)
        tts_reader.stop()
        plat.stop_all_sounds()
        if self._tts_proc:
            try:
                self._tts_proc.terminate()
            except Exception:
                pass
        plat.kill_processes(["qwen_tts", "serve.py"])
        log("[TTS] 강제 중지 완료")

    # ------------------------------------------------------------------
    # 상시 청취 / 모드 헬퍼
    # ------------------------------------------------------------------
    def _deactivate_drive_mode(self) -> None:
        (Path.home() / ".whisperflow_auto_tts").unlink(missing_ok=True)
        if not self._shoot_on():
            self._stop_always_listen()

    def _deactivate_library_mode(self) -> None:
        (Path.home() / ".whisperflow_library_tts").unlink(missing_ok=True)

    def _deactivate_jarvis_shoot_mode(self) -> None:
        (Path.home() / ".whisperflow_youtube_tts").unlink(missing_ok=True)
        Path(self.JARVIS_ROLEPLAY_FILE).unlink(missing_ok=True)
        if self.camera_feed is not None:
            self.camera_feed.stop()
            self.camera_feed = None
        if self.gesture_control is not None:
            self.gesture_control.stop()
            self.gesture_control = None
        if not self._drive_on():
            self._stop_always_listen()
        self._ws_broadcast("broadcast_raw", '{"type":"browser_stop"}')

    def _toggle_auto_tts(self, icon, item) -> None:
        if self._drive_on():
            (Path.home() / ".whisperflow_auto_tts").unlink(missing_ok=True)
            self._stop_always_listen()
            log("[TTS] 드라이브 모드 OFF")
            self._notify("WhisperFlow", "드라이브 모드 OFF")
        else:
            (Path.home() / ".whisperflow_auto_tts").touch()
            self._deactivate_library_mode()
            self._deactivate_jarvis_shoot_mode()
            self._start_always_listen(skip_boot_wait=True)
            log("[TTS] 드라이브 모드 ON (상시 청취 시작)")
            self._notify("WhisperFlow", "드라이브 모드 ON")

    def _toggle_library_tts(self, icon, item) -> None:
        if self._library_on():
            (Path.home() / ".whisperflow_library_tts").unlink(missing_ok=True)
            log("[TTS] 도서관 모드 OFF")
            self._notify("WhisperFlow", "도서관 모드 OFF")
        else:
            (Path.home() / ".whisperflow_library_tts").touch()
            self._deactivate_drive_mode()
            self._deactivate_jarvis_shoot_mode()
            log("[TTS] 도서관 모드 ON")
            self._notify("WhisperFlow", "도서관 모드 ON")

    def _toggle_jarvis_shoot_mode(self, icon, item) -> None:
        if self._shoot_on():
            self._deactivate_jarvis_shoot_mode()
            log("[촬영] JARVIS 촬영 모드 OFF")
            self._notify("WhisperFlow", "JARVIS 촬영 모드 OFF")
        else:
            self._deactivate_drive_mode()
            self._deactivate_library_mode()
            (Path.home() / ".whisperflow_youtube_tts").touch()
            Path(self.JARVIS_ROLEPLAY_FILE).touch()
            self._start_always_listen(skip_boot_wait=False)
            if self.always_listen:
                log("[촬영] 상시 청취 시작")
            log("[촬영] JARVIS 촬영 모드 ON (박수 2번으로 시스템 온라인)")
            self._notify("WhisperFlow", "JARVIS 촬영 모드 ON")

    def _detect_mic_preset(self) -> dict:
        try:
            import sounddevice as sd
            dev = sd.query_devices(sd.default.device[0])
            name = dev['name'].lower()
            if 'airpod' in name:
                log(f"[마이크] 에어팟 감지: {dev['name']}")
                return {'audio_gain': 12, 'wake_threshold': 0.35, 'speech_threshold': 0.5}
            elif 'headset' in name or 'bluetooth' in name:
                log(f"[마이크] 헤드셋 감지: {dev['name']}")
                return {'audio_gain': 10, 'wake_threshold': 0.4, 'speech_threshold': 0.5}
            else:
                log(f"[마이크] 기본 마이크 감지: {dev['name']}")
                return {'audio_gain': 20, 'wake_threshold': 0.5, 'speech_threshold': 0.5}
        except Exception as e:  # noqa: BLE001
            log(f"[마이크] 디바이스 감지 실패: {e}")
            return {'audio_gain': 20, 'wake_threshold': 0.5, 'speech_threshold': 0.5}

    def _start_always_listen(self, skip_boot_wait: bool = False) -> None:
        if AlwaysListen is None:
            log("[상시청취] AlwaysListen 모듈 로드 실패 (의존성 미설치)")
            return
        if self.always_listen is not None:
            self.always_listen.stop()
        preset = self._detect_mic_preset()
        log(f"[상시청취] 프리셋: gain={preset['audio_gain']}, wake={preset['wake_threshold']}, speech={preset['speech_threshold']}")
        # 모델 다운로드/마이크 실패 등으로 상시 청취가 못 떠도
        # 앱 본체(받아쓰기/TTS/트레이)는 계속 동작해야 한다.
        try:
            self.always_listen = AlwaysListen(
                on_double_clap=self._on_double_clap,
                on_wake=self._on_wake_word,
                on_speech_detected=self._on_speech_detected,
                on_audio_level=self._on_audio_level,
                on_conversation_end=self._on_conversation_end,
                skip_boot_wait=skip_boot_wait,
                audio_gain=preset['audio_gain'],
                wake_threshold=preset['wake_threshold'],
                speech_threshold=preset['speech_threshold'],
            )
            self.always_listen.start()
        except Exception as e:  # noqa: BLE001
            log(f"[상시청취] 시작 실패 (앱은 계속 동작): {e}")
            self._notify(
                "WhisperFlow",
                "상시 청취 시작 실패 — 인터넷 연결 확인 후 모드를 다시 켜주세요",
            )
            self.always_listen = None
            return
        from . import filming_scenarios
        filming_scenarios._always_listen_ref = self.always_listen

    def _stop_always_listen(self) -> None:
        if self.always_listen is not None:
            self.always_listen.stop()
            self.always_listen = None
        from . import filming_scenarios
        filming_scenarios._always_listen_ref = None

    def enter_conversation_mode(self) -> None:
        if not self.always_listen and self._drive_on():
            self._start_always_listen(skip_boot_wait=True)
            log("[상시청취] 드라이브 모드 감지 — 상시 청취 자동 시작")
        if self.always_listen:
            self.always_listen.enter_conversation_mode()
            self._ws_broadcast("broadcast_state", "recording")
            log("[상시청취] 대화 모드 진입 — 바로 말씀하세요")

    def _on_double_clap(self) -> None:
        log("[상시청취] 더블 클랩 감지! → 시스템 온라인")
        from . import filming_scenarios
        filming_scenarios._handle_system_online("")

    def _play_sound(self, filename: str) -> None:
        import time
        sound_path = os.path.join(os.path.dirname(__file__), "static", "sounds", filename)
        if not os.path.exists(sound_path):
            return
        self._ws_broadcast("broadcast_state", "tts_playing")
        if self.always_listen:
            self.always_listen.mute()
        plat.play_sound(sound_path, blocking=True)
        time.sleep(0.2)
        if self.always_listen:
            self.always_listen.unmute()
        self._ws_broadcast("broadcast_state", "idle")

    def _on_conversation_end(self) -> None:
        import time
        log("[상시청취] 대화 모드 종료 → 대기 모드")
        sound_path = os.path.join(os.path.dirname(__file__), "static", "sounds", "standby.wav")
        if self.always_listen and os.path.exists(sound_path):
            self._ws_broadcast("broadcast_state", "tts_playing")
            self.always_listen.mute()
            try:
                import base64
                with open(sound_path, 'rb') as f:
                    b64 = base64.b64encode(f.read()).decode('utf-8')
                self.ws_server.broadcast_raw(json.dumps({"type": "tts_audio", "value": b64}))
            except Exception:
                pass
            plat.play_sound(sound_path, blocking=True)
            time.sleep(0.2)
            if self.always_listen:
                self.always_listen.unmute()
        self._ws_broadcast("broadcast_state", "idle")

    def _on_wake_word(self) -> None:
        import time
        self._kill_tts()
        log("[상시청취] 헤이 자비스 감지! → TTS 중지 + Yes sir 재생 + 녹음 대기")
        sound_path = os.path.join(os.path.dirname(__file__), "static", "sounds", "yes_sir.wav")
        if self.always_listen and os.path.exists(sound_path):
            self._ws_broadcast("broadcast_state", "tts_playing")
            self.always_listen.mute()
            plat.play_sound(sound_path, blocking=True)
            log("[상시청취] Yes sir 재생 완료 → 녹음 버퍼 리셋 + unmute")
            time.sleep(0.2)
            self.always_listen.reset_recording()
            self.always_listen.unmute()
        self._ws_broadcast("broadcast_state", "recording")
        log("[상시청취] 녹음 대기 중... (말씀하세요)")

    def _on_speech_detected(self, audio_data, sample_rate) -> None:
        log(f"[상시청취] 음성 감지 → Whisper 변환 시작 ({len(audio_data)/sample_rate:.1f}초)")
        import tempfile
        import wave
        try:
            self._play_sound("processing.wav")
            self._ws_broadcast("broadcast_state", "processing")
            tmp = tempfile.NamedTemporaryFile(suffix='.wav', delete=False)
            audio_int16 = (audio_data * 32767).astype('int16')
            with wave.open(tmp.name, 'wb') as wf:
                wf.setnchannels(1)
                wf.setsampwidth(2)
                wf.setframerate(sample_rate)
                wf.writeframes(audio_int16.tobytes())
            self._remote_recording = True
            self.transcriber.transcribe_async(tmp.name)
        except Exception as e:  # noqa: BLE001
            log(f"[상시청취] 변환 오류: {e}")

    def _handle_camera_command(self, text: str) -> bool:
        if len(text) > 30:
            return False
        if '카메라' in text and any(w in text for w in ['켜', '열어', '활성', '시작', '연결']):
            camera_index = 0
            camera_name = "기본"
            if self.camera_feed is not None:
                self.camera_feed.stop()
                self.camera_feed = None
            if CameraFeed is not None:
                self.camera_feed = CameraFeed(camera_index=camera_index, fps=5)
                self.camera_feed.start()
                log(f"[카메라] {camera_name} 카메라 시작 (index={camera_index})")
                self._play_sound("camera_on.wav")
            return True
        if '카메라' in text and any(w in text for w in ['전환', '바꿔', '바꾸', '스위치', '변경']):
            if self.camera_feed is not None:
                current_index = self.camera_feed.camera_index
                new_index = 0 if current_index == 1 else 1
                self.camera_feed.stop()
                self.camera_feed = CameraFeed(camera_index=new_index, fps=5)
                self.camera_feed.start()
                log(f"[카메라] 전환 → index={new_index}")
                self._play_sound("camera_on.wav")
            return True
        if '카메라' in text and any(w in text for w in ['꺼', '닫', '종료', '중지']):
            if self.camera_feed is not None:
                self.camera_feed.stop()
                self.camera_feed = None
                log("[카메라] 카메라 종료")
                self._play_sound("camera_off.wav")
                self._ws_broadcast("broadcast_raw", '{"type":"browser_stop"}')
            return True
        return False

    # ------------------------------------------------------------------
    # 제스처 컨트롤 (서브프로세스 + 미리보기 창)
    # ------------------------------------------------------------------
    def _toggle_gesture_control(self, icon, item) -> None:
        if self.gesture_proc is not None and self.gesture_proc.poll() is not None:
            self.gesture_proc = None

        if self.gesture_proc is not None:
            self._stop_gesture_proc()
            log("[제스처] 제스처 컨트롤 OFF")
            self._notify("WhisperFlow", "제스처 컨트롤 OFF")
        else:
            try:
                project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
                gesture_log = open(plat.temp_path("whisperflow_gesture.log"), "a")
                self.gesture_proc = subprocess.Popen(
                    [sys.executable, "-m", "whisperflow.gesture_control", "--test", "--mac"],
                    cwd=project_root,
                    stdout=gesture_log,
                    stderr=gesture_log,
                )
                self._start_gesture_monitor()
                log(f"[제스처] 제스처 컨트롤 ON (pid={self.gesture_proc.pid})")
                self._notify("WhisperFlow", "제스처 컨트롤 ON — 미리보기 창에서 q로도 종료 가능")
            except Exception as e:  # noqa: BLE001
                log(f"[제스처] 시작 실패: {e}")
                self._notify("WhisperFlow", f"제스처 컨트롤 시작 실패: {e}")

    def _start_gesture_monitor(self) -> None:
        """제스처 서브프로세스가 스스로 종료(q 키 등)됐는지 감시."""
        def _monitor():
            proc = self.gesture_proc
            if proc is None:
                return
            proc.wait()
            if self.gesture_proc is proc:
                self.gesture_proc = None
                log("[제스처] 프로세스 종료 감지 — 토글 OFF")
        self._gesture_timer = threading.Thread(target=_monitor, daemon=True)
        self._gesture_timer.start()

    def _stop_gesture_proc(self) -> None:
        if self.gesture_proc is not None:
            if self.gesture_proc.poll() is None:
                self.gesture_proc.terminate()
                try:
                    self.gesture_proc.wait(timeout=3)
                except subprocess.TimeoutExpired:
                    self.gesture_proc.kill()
            self.gesture_proc = None

    # ------------------------------------------------------------------
    # TTS 단축키 콜백
    # ------------------------------------------------------------------
    def _on_tts_trigger(self) -> None:
        import pyperclip
        if tts_reader.is_speaking:
            tts_reader.stop()
            self._ws_broadcast("broadcast_state", "idle")
            log("[TTS] 읽기 중지 (단축키)")
            return

        log("[TTS] 클립보드 텍스트 읽기 시작")
        try:
            clipboard_text = pyperclip.paste()
            if clipboard_text and clipboard_text.strip():
                preview = clipboard_text[:50] + "..." if len(clipboard_text) > 50 else clipboard_text
                log(f"[TTS] 읽기: {preview}")
                self._notify("WhisperFlow TTS", f"읽는 중: {preview}")
                self._ws_broadcast("broadcast_state", "tts_playing")

                # Qwen TTS 사용 가능하면 Qwen, 아니면 로컬 TTS
                try:
                    import urllib.request
                    r = urllib.request.urlopen('http://localhost:9093/health', timeout=2)
                    if r.status == 200:
                        qwen_hook = os.environ.get('QWEN_TTS_HOOK')
                        if qwen_hook and os.path.exists(qwen_hook):
                            cmd = [sys.executable, qwen_hook]
                            if not config.tts_say_first:
                                cmd.append("--no-say")
                            cmd.append(clipboard_text)
                            subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                            return
                except Exception:
                    pass
                tts_reader.speak(clipboard_text)
            else:
                log("[TTS] 클립보드 비어있음")
                self._notify("WhisperFlow", "먼저 텍스트를 복사해주세요 (Ctrl+C)")
        except Exception as e:  # noqa: BLE001
            log(f"[TTS] 오류: {e}")
            self._notify("WhisperFlow 오류", f"TTS 오류: {e}")

    # ------------------------------------------------------------------
    def run(self) -> None:
        """트레이 앱 실행 (메인 스레드 블로킹)."""
        self.icon.run()


def main():
    """앱 실행"""
    app = WhisperFlowApp()
    app.run()


if __name__ == "__main__":
    main()
