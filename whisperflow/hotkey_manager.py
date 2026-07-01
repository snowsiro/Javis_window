"""전역 단축키 관리 모듈 (크로스 플랫폼, pynput)

Windows 에서는 modifier 로 Ctrl/Shift/Alt/Win(cmd) 를 사용한다.
문자 키 감지는 우선 key.char, 실패 시 key.vk(가상 키 코드)로 역매핑한다.
"""

import threading
import time
from typing import Callable, Optional, Set

from pynput import keyboard

from . import platform_utils as plat


# 가상 키 코드 → 문자 매핑 (플랫폼별)
if plat.IS_WINDOWS:
    # Windows Virtual-Key Codes: A-Z = 0x41..0x5A, 0-9 = 0x30..0x39
    VK_TO_CHAR = {vk: chr(vk).lower() for vk in range(0x41, 0x5B)}
    VK_TO_CHAR.update({vk: chr(vk) for vk in range(0x30, 0x3A)})
else:
    # macOS virtual key code → 문자 매핑
    VK_TO_CHAR = {
        0: "a", 1: "s", 2: "d", 3: "f", 4: "h",
        5: "g", 6: "z", 7: "x", 8: "c", 9: "v",
        11: "b", 12: "q", 13: "w", 14: "e", 15: "r",
        16: "y", 17: "t", 18: "1", 19: "2", 20: "3",
        21: "4", 22: "6", 23: "5", 24: "=", 25: "9",
        26: "7", 27: "-", 28: "8", 29: "0", 30: "]",
        31: "o", 32: "u", 33: "[", 34: "i", 35: "p",
        37: "l", 38: "j", 39: "'", 40: "k", 41: ";",
        42: "\\", 43: ",", 44: "/", 45: "n", 46: "m",
        47: ".", 50: "`",
    }


class HotkeyManager:
    """modifier + 문자 키 기반 단축키 관리 클래스

    - 짧게 탭: 토글 모드 (탭하면 녹음 시작, 다시 탭하면 중지)
    - 꾹 누르기: 누르는 동안 녹음, 떼면 중지
    """

    HOLD_THRESHOLD = 0.3  # 꾹 누르기 판정 시간 (초)

    # 키 매핑 (modifier)
    # Windows 에서 Key.cmd 는 Windows(Super) 키에 해당한다.
    KEY_MAP = {
        "cmd": keyboard.Key.cmd,
        "ctrl": keyboard.Key.ctrl,
        "option": keyboard.Key.alt,
        "shift": keyboard.Key.shift,
        "space": keyboard.Key.space,
    }

    # stale key 정리 임계값 (초)
    STALE_KEY_TIMEOUT = 2.0

    def __init__(self,
                 on_hold_start: Optional[Callable] = None,
                 on_hold_end: Optional[Callable] = None,
                 on_toggle: Optional[Callable] = None,
                 on_hotkey: Optional[Callable] = None,
                 on_tts_trigger: Optional[Callable] = None):

        self._listener: Optional[keyboard.Listener] = None
        self._lock = threading.Lock()

        # 콜백
        self.on_hold_start = on_hold_start
        self.on_hold_end = on_hold_end
        self.on_toggle = on_toggle
        self.on_hotkey = on_hotkey
        self.on_tts_trigger = on_tts_trigger

        # 단축키 조합 (기본값)
        from .config import config
        self._load_modifiers_from_config(config.hotkey)
        self._option_hold_enabled = config.option_hold_enabled

        # === TTS 단축키 ===
        self._tts_modifiers: Set = set()
        self._tts_char_key: Optional[str] = None
        self._tts_active = False
        self._tts_enabled = config.tts_enabled
        self._load_tts_hotkey(config.tts_hotkey)

        # 현재 눌린 키
        self._pressed_keys: Set = set()
        self._pressed_times: dict = {}

        # 상태
        self._hotkey_press_time = 0
        self._last_hotkey_release_time = 0
        self._is_holding = False
        self._toggle_mode = False
        self._hold_timer: Optional[threading.Timer] = None
        self._hotkey_active = False

        # Option(Alt) 키 길게 누르기 상태
        self._option_press_time = 0
        self._option_hold_timer: Optional[threading.Timer] = None
        self._option_is_holding = False

    def _load_tts_hotkey(self, hotkey_str: str) -> None:
        keys = hotkey_str.lower().replace(" ", "").split("+")
        self._tts_modifiers = set()
        self._tts_char_key = None
        for key in keys:
            if key in self.KEY_MAP:
                self._tts_modifiers.add(self.KEY_MAP[key])
            else:
                self._tts_char_key = key
        print(f"[TTS 단축키] 설정됨: {hotkey_str}")

    def update_tts_hotkey(self, hotkey_str: str) -> None:
        self._load_tts_hotkey(hotkey_str)
        self._tts_active = False

    def set_tts_enabled(self, enabled: bool) -> None:
        self._tts_enabled = enabled
        self._tts_active = False
        print(f"[TTS 단축키] {'활성화' if enabled else '비활성화'}")

    def _is_tts_hotkey_pressed(self) -> bool:
        if not self._tts_enabled:
            return False
        modifiers_ok = self._tts_modifiers.issubset(self._pressed_keys)
        char_ok = self._tts_char_key in self._pressed_keys if self._tts_char_key else True
        return modifiers_ok and char_ok

    def _load_modifiers_from_config(self, hotkey_str: str) -> None:
        keys = hotkey_str.lower().replace(" ", "").split("+")
        self.HOTKEY_MODIFIERS = set()
        self.CHAR_KEY = None
        for key in keys:
            if key in self.KEY_MAP:
                self.HOTKEY_MODIFIERS.add(self.KEY_MAP[key])
            else:
                self.CHAR_KEY = key
                print(f"[단축키] 문자 키 설정: '{key}'")

    def update_modifiers(self, modifiers: list) -> None:
        self.HOTKEY_MODIFIERS = set()
        self.CHAR_KEY = None
        for key in modifiers:
            if key in self.KEY_MAP:
                self.HOTKEY_MODIFIERS.add(self.KEY_MAP[key])
            else:
                self.CHAR_KEY = key
        self._pressed_keys.clear()
        self._pressed_times.clear()
        self._hotkey_active = False
        self._is_holding = False
        self._toggle_mode = False
        print(f"[단축키] 업데이트: {modifiers}")

    def set_option_hold_enabled(self, enabled: bool) -> None:
        self._option_hold_enabled = enabled
        if self._option_hold_timer:
            self._option_hold_timer.cancel()
            self._option_hold_timer = None
        self._option_is_holding = False
        print(f"[단축키] Alt(Option) 키 길게 누르기: {'활성화' if enabled else '비활성화'}")

    def _normalize_key(self, key):
        """키를 정규화 (좌/우 구분 없이).

        문자 키를 누르면 key.char 로 감지하고, 실패 시 key.vk 로 역매핑한다.
        """
        if key in (keyboard.Key.cmd, keyboard.Key.cmd_l, keyboard.Key.cmd_r):
            return keyboard.Key.cmd
        elif key in (keyboard.Key.ctrl, keyboard.Key.ctrl_l, keyboard.Key.ctrl_r):
            return keyboard.Key.ctrl
        elif key in (keyboard.Key.alt, keyboard.Key.alt_l, keyboard.Key.alt_r,
                     getattr(keyboard.Key, "alt_gr", keyboard.Key.alt)):
            return keyboard.Key.alt
        elif key in (keyboard.Key.shift, keyboard.Key.shift_l, keyboard.Key.shift_r):
            return keyboard.Key.shift
        elif key == keyboard.Key.space:
            return keyboard.Key.space
        elif hasattr(key, 'char') or hasattr(key, 'vk'):
            # char 가 정상 문자(제어문자 아님)면 사용
            if hasattr(key, 'char') and key.char and key.char.isprintable():
                return key.char.lower()
            # char 가 None/제어문자면 vk 코드로 역매핑
            if hasattr(key, 'vk') and key.vk is not None:
                char = VK_TO_CHAR.get(key.vk)
                if char:
                    return char
        return None

    def _is_hotkey_pressed(self) -> bool:
        all_modifiers = {keyboard.Key.cmd, keyboard.Key.ctrl,
                        keyboard.Key.alt, keyboard.Key.shift}
        pressed_modifiers = self._pressed_keys & all_modifiers

        if pressed_modifiers != self.HOTKEY_MODIFIERS:
            return False

        char_ok = self.CHAR_KEY in self._pressed_keys if self.CHAR_KEY else True
        return char_ok

    def _is_only_option_pressed(self) -> bool:
        return (self._pressed_keys == {keyboard.Key.alt} and
                self._option_hold_enabled)

    def _start_option_hold_recording(self):
        with self._lock:
            if self._is_only_option_pressed() and not self._option_is_holding:
                self._option_is_holding = True
                print("[단축키] Alt 키 길게 누르기 - 녹음 시작")
                if self.on_hold_start:
                    threading.Thread(target=self.on_hold_start, daemon=True).start()

    def _cleanup_stale_keys(self) -> None:
        now = time.time()
        stale_keys = [
            k for k, t in self._pressed_times.items()
            if now - t > self.STALE_KEY_TIMEOUT
        ]
        if stale_keys:
            for k in stale_keys:
                self._pressed_keys.discard(k)
                del self._pressed_times[k]
            print(f"[단축키] stale 키 정리: {stale_keys}")
            if self._hotkey_active and not self._is_hotkey_pressed():
                self._hotkey_active = False
                print("[단축키] stale 정리로 hotkey_active 리셋")

    def _on_press(self, key) -> None:
        normalized = self._normalize_key(key)
        if normalized is None:
            return

        with self._lock:
            self._cleanup_stale_keys()

            self._pressed_keys.add(normalized)
            self._pressed_times[normalized] = time.time()

            # Alt 키만 눌렸을 때 (Alt 홀드 모드가 활성화된 경우)
            if self._is_only_option_pressed() and not self._option_is_holding:
                now = time.time()
                self._option_press_time = now
                if self._option_hold_timer:
                    self._option_hold_timer.cancel()
                self._option_hold_timer = threading.Timer(
                    self.HOLD_THRESHOLD,
                    self._start_option_hold_recording
                )
                self._option_hold_timer.start()
                return

            if self._option_hold_timer and not self._is_only_option_pressed():
                self._option_hold_timer.cancel()
                self._option_hold_timer = None

            # === TTS 중지 단축키 (Ctrl+Alt+Win 정확히 3개) ===
            tts_stop_keys = {keyboard.Key.ctrl, keyboard.Key.alt, keyboard.Key.cmd}
            pressed_mods = self._pressed_keys & {keyboard.Key.cmd, keyboard.Key.ctrl,
                                                  keyboard.Key.alt, keyboard.Key.shift}
            if pressed_mods == tts_stop_keys:
                plat.stop_all_sounds()
                try:
                    from .tts_reader import tts_reader
                    tts_reader.stop()
                except Exception:
                    pass
                print("[단축키] TTS 중지됨")
                return

            # === TTS 단축키 감지 ===
            if self._is_tts_hotkey_pressed() and not self._tts_active:
                self._tts_active = True
                print("[TTS 단축키] 트리거됨")
                if self._hold_timer:
                    self._hold_timer.cancel()
                    self._hold_timer = None
                if self._hotkey_active:
                    self._hotkey_active = False
                if self._is_holding:
                    self._is_holding = False
                    if self.on_hold_end:
                        threading.Thread(target=self.on_hold_end, daemon=True).start()
                if self.on_tts_trigger:
                    threading.Thread(target=self.on_tts_trigger, daemon=True).start()
                return

            # 단축키 조합이 처음 완성됨
            if self._is_hotkey_pressed() and not self._hotkey_active:
                self._hotkey_active = True
                now = time.time()
                self._hotkey_press_time = now

                if self._toggle_mode:
                    return

                if self._hold_timer:
                    self._hold_timer.cancel()

                self._hold_timer = threading.Timer(
                    self.HOLD_THRESHOLD,
                    self._start_hold_recording
                )
                self._hold_timer.start()

    def _start_hold_recording(self):
        with self._lock:
            if not self._toggle_mode and self._hotkey_active:
                if not self._is_hotkey_pressed():
                    print("[단축키] 홀드 시작 취소 - 키가 이미 떼어짐")
                    self._hotkey_active = False
                    return
                self._is_holding = True
                print("[단축키] 꾹 누르기 - 녹음 시작")
                if self.on_hold_start:
                    threading.Thread(target=self.on_hold_start, daemon=True).start()

    def _on_release(self, key) -> None:
        normalized = self._normalize_key(key)
        if normalized is None:
            return

        with self._lock:
            if normalized == keyboard.Key.alt:
                if self._option_hold_timer:
                    self._option_hold_timer.cancel()
                    self._option_hold_timer = None
                if self._option_is_holding:
                    self._option_is_holding = False
                    print("[단축키] Alt 키 길게 누르기 끝 - 녹음 중지")
                    if self.on_hold_end:
                        threading.Thread(target=self.on_hold_end, daemon=True).start()
                    self._pressed_keys.discard(normalized)
                    self._pressed_times.pop(normalized, None)
                    return

            was_tts_active = self._tts_active
            was_hotkey_active = self._hotkey_active

            self._pressed_keys.discard(normalized)
            self._pressed_times.pop(normalized, None)

            if was_tts_active and not self._is_tts_hotkey_pressed():
                self._tts_active = False

            if was_hotkey_active and not self._is_hotkey_pressed():
                self._hotkey_active = False
                now = time.time()
                press_duration = now - self._hotkey_press_time

                if self._hold_timer:
                    self._hold_timer.cancel()
                    self._hold_timer = None

                if self._is_holding:
                    self._is_holding = False
                    print("[단축키] 꾹 누르기 끝 - 녹음 중지")
                    if self.on_hold_end:
                        threading.Thread(target=self.on_hold_end, daemon=True).start()
                    self._last_hotkey_release_time = now
                    return

                if self._toggle_mode:
                    self._toggle_mode = False
                    print("[단축키] 토글 모드 종료 - 녹음 중지")
                    if self.on_hold_end:
                        threading.Thread(target=self.on_hold_end, daemon=True).start()
                    self._last_hotkey_release_time = now
                    return

                if press_duration < self.HOLD_THRESHOLD + 0.1:
                    self._toggle_mode = True
                    print("[단축키] 짧게 탭 - 토글 녹음 시작")
                    if self.on_hold_start:
                        threading.Thread(target=self.on_hold_start, daemon=True).start()

                self._last_hotkey_release_time = now

    def start(self) -> None:
        if self._listener is not None:
            return

        self._listener = keyboard.Listener(
            on_press=self._on_press,
            on_release=self._on_release
        )
        self._listener.start()

        key_names = []
        for key in self.HOTKEY_MODIFIERS:
            if key == keyboard.Key.cmd:
                key_names.append("Win")
            elif key == keyboard.Key.ctrl:
                key_names.append("Ctrl")
            elif key == keyboard.Key.alt:
                key_names.append("Alt")
            elif key == keyboard.Key.shift:
                key_names.append("Shift")
        if self.CHAR_KEY:
            key_names.append(self.CHAR_KEY.upper())
        print(f"[단축키] {'+'.join(key_names)} 리스닝 시작")
        print("  - 짧게 탭: 토글 모드 (다시 탭하면 중지)")
        print("  - 꾹 누르기: 누르는 동안 녹음")
        if self._tts_enabled:
            tts_names = []
            for key in self._tts_modifiers:
                if key == keyboard.Key.cmd:
                    tts_names.append("Win")
                elif key == keyboard.Key.ctrl:
                    tts_names.append("Ctrl")
                elif key == keyboard.Key.alt:
                    tts_names.append("Alt")
                elif key == keyboard.Key.shift:
                    tts_names.append("Shift")
            if self._tts_char_key:
                tts_names.append(self._tts_char_key.upper())
            print(f"[TTS 단축키] {'+'.join(tts_names)} 리스닝 시작")

    def stop(self) -> None:
        if self._hold_timer:
            self._hold_timer.cancel()
        if self._listener:
            self._listener.stop()
            self._listener = None
