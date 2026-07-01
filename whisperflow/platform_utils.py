"""
platform_utils.py — 크로스 플랫폼(주로 Windows) 시스템 유틸리티 추상화 레이어.

macOS 원본의 osascript/afplay/say/pbcopy/open/pgrep/pkill/Quartz 호출을
Windows에서 동작하는 순수 파이썬 구현으로 대체한다.

이 모듈은 다른 모든 모듈이 OS별 분기 없이 사용할 수 있도록
공통 API를 제공한다:
  - 임시 파일 경로 (temp_path)
  - 사운드 재생/정지 (play_sound / stop_all_sounds)  ※ 재생 속도 배율 지원
  - 클립보드 복사 + 활성 창 붙여넣기 (copy_to_clipboard / paste_to_active)
  - 앱 실행 / URL 열기 / 폴더 열기 (open_app / open_url / open_path)
  - 프로세스 종료 (kill_processes)
  - 알림 표시 (show_notification)
  - 마우스/화면 제어 (move_mouse / click_mouse / scroll / screen_size ...)
  - 시스템 제어 단축키 (system_control)
"""

from __future__ import annotations

import os
import sys
import tempfile
import threading
import wave
from pathlib import Path
from typing import Callable, Iterable, Optional

# ----------------------------------------------------------------------
# 플랫폼 감지
# ----------------------------------------------------------------------
IS_WINDOWS = sys.platform.startswith("win")
IS_MAC = sys.platform == "darwin"
IS_LINUX = sys.platform.startswith("linux")


# ----------------------------------------------------------------------
# 임시 파일 경로 (macOS의 /tmp 대체)
# ----------------------------------------------------------------------
_TEMP_DIR = Path(tempfile.gettempdir())


def temp_dir() -> Path:
    """OS 임시 디렉토리 경로 반환 (Windows: %TEMP%, 그 외: /tmp)."""
    return _TEMP_DIR


def temp_path(name: str) -> str:
    """임시 디렉토리 하위의 파일 경로 문자열 반환."""
    return str(_TEMP_DIR / name)


# ----------------------------------------------------------------------
# 사운드 재생 (afplay 대체)
#   - sounddevice + wave 로 WAV 를 재생한다.
#   - rate 배율(afplay -r) 지원: 재생 샘플레이트를 배율만큼 올려 빠르게 재생.
#   - stop_all_sounds() 로 재생 중인 모든 사운드를 즉시 중단.
# ----------------------------------------------------------------------
_playback_lock = threading.Lock()


def _load_wav(path: str):
    """WAV 파일을 (float32 ndarray, samplerate) 로 로드. numpy 필요."""
    import numpy as np

    with wave.open(path, "rb") as wf:
        n_channels = wf.getnchannels()
        sampwidth = wf.getsampwidth()
        framerate = wf.getframerate()
        n_frames = wf.getnframes()
        raw = wf.readframes(n_frames)

    if sampwidth == 2:
        data = np.frombuffer(raw, dtype=np.int16).astype(np.float32) / 32768.0
    elif sampwidth == 4:
        data = np.frombuffer(raw, dtype=np.int32).astype(np.float32) / 2147483648.0
    elif sampwidth == 1:
        data = (np.frombuffer(raw, dtype=np.uint8).astype(np.float32) - 128.0) / 128.0
    else:
        data = np.frombuffer(raw, dtype=np.int16).astype(np.float32) / 32768.0

    if n_channels > 1:
        data = data.reshape(-1, n_channels)
    return data, framerate


def play_sound(path: str, rate: float = 1.0, blocking: bool = True) -> bool:
    """WAV 사운드를 재생한다.

    Args:
        path: WAV 파일 경로
        rate: 재생 속도 배율 (1.4 = 1.4배 빠르게, afplay -r 과 동일)
        blocking: True면 재생이 끝날 때까지 대기

    Returns:
        재생 성공 여부
    """
    if not os.path.exists(path):
        return False
    try:
        import sounddevice as sd

        data, framerate = _load_wav(path)
        play_rate = int(framerate * rate) if rate and rate > 0 else framerate
        with _playback_lock:
            sd.stop()
            sd.play(data, samplerate=play_rate)
        if blocking:
            sd.wait()
        return True
    except Exception:
        # sounddevice 실패 시 winsound 로 폴백 (Windows, 속도 배율 미지원)
        if IS_WINDOWS:
            try:
                import winsound

                flags = winsound.SND_FILENAME
                if not blocking:
                    flags |= winsound.SND_ASYNC
                winsound.PlaySound(path, flags)
                return True
            except Exception:
                return False
        return False


def play_sound_async(path: str, rate: float = 1.0) -> None:
    """사운드를 백그라운드 스레드에서 재생 (논블로킹)."""
    threading.Thread(
        target=play_sound, args=(path, rate, True), daemon=True
    ).start()


def stop_all_sounds() -> None:
    """재생 중인 모든 사운드를 즉시 중단 (afplay 프로세스 kill 대체)."""
    try:
        import sounddevice as sd

        sd.stop()
    except Exception:
        pass
    if IS_WINDOWS:
        try:
            import winsound

            winsound.PlaySound(None, winsound.SND_PURGE)
        except Exception:
            pass


# ----------------------------------------------------------------------
# 클립보드 + 붙여넣기 (pbcopy + osascript Cmd+V 대체)
# ----------------------------------------------------------------------
def copy_to_clipboard(text: str) -> bool:
    """텍스트를 클립보드에 복사."""
    try:
        import pyperclip

        pyperclip.copy(text)
        return True
    except Exception as e:  # noqa: BLE001
        print(f"[platform] 클립보드 복사 오류: {e}")
        return False


def paste_to_active(enter: bool = False, restore_hwnd: Optional[int] = None) -> bool:
    """현재 활성 창에 Ctrl+V 로 붙여넣기 (+ 선택적으로 Enter).

    macOS 의 osascript 'key code 9 using command down' 대체.

    Args:
        enter: True면 붙여넣기 후 Enter 전송
        restore_hwnd: 지정 시 붙여넣기 전에 해당 창을 포그라운드로 복원 (Windows)
    """
    import time

    try:
        if restore_hwnd is not None and IS_WINDOWS:
            _restore_foreground(restore_hwnd)
            time.sleep(0.2)

        from pynput.keyboard import Controller, Key

        kb = Controller()
        # Ctrl+V
        kb.press(Key.ctrl)
        kb.press("v")
        kb.release("v")
        kb.release(Key.ctrl)
        if enter:
            time.sleep(0.3)
            kb.press(Key.enter)
            kb.release(Key.enter)
        return True
    except Exception as e:  # noqa: BLE001
        print(f"[platform] 붙여넣기 오류: {e}")
        return False


# ----------------------------------------------------------------------
# 활성 창 추적 (osascript frontmost 앱 대체)
# ----------------------------------------------------------------------
def get_foreground_window() -> Optional[int]:
    """현재 포그라운드 창 핸들(HWND) 반환. Windows 전용, 실패 시 None."""
    if not IS_WINDOWS:
        return None
    try:
        import win32gui  # type: ignore

        return win32gui.GetForegroundWindow()
    except Exception:
        return None


def get_foreground_app_name() -> Optional[str]:
    """포그라운드 창 프로세스의 실행 파일명(확장자 제외) 반환. 실패 시 None."""
    if not IS_WINDOWS:
        return None
    try:
        import win32gui  # type: ignore
        import win32process  # type: ignore
        import psutil  # type: ignore

        hwnd = win32gui.GetForegroundWindow()
        _, pid = win32process.GetWindowThreadProcessId(hwnd)
        proc = psutil.Process(pid)
        return os.path.splitext(proc.name())[0]
    except Exception:
        return None


def _restore_foreground(hwnd: int) -> None:
    """지정한 창을 포그라운드로 복원 (Windows)."""
    try:
        import win32gui  # type: ignore
        import win32con  # type: ignore

        if win32gui.IsIconic(hwnd):
            win32gui.ShowWindow(hwnd, win32con.SW_RESTORE)
        win32gui.SetForegroundWindow(hwnd)
    except Exception:
        pass


# ----------------------------------------------------------------------
# 앱 실행 / URL / 폴더 열기 (open -a / open url / open 대체)
# ----------------------------------------------------------------------
def open_url(url: str) -> bool:
    """기본 브라우저에서 URL 열기 (macOS 'open url' 대체)."""
    try:
        import webbrowser

        webbrowser.open(url)
        return True
    except Exception as e:  # noqa: BLE001
        print(f"[platform] URL 열기 오류: {e}")
        return False


def open_path(path: str) -> bool:
    """파일 탐색기에서 폴더/파일 열기 (macOS 'open <path>' 대체)."""
    try:
        if IS_WINDOWS:
            os.startfile(path)  # type: ignore[attr-defined]
        elif IS_MAC:
            import subprocess

            subprocess.run(["open", path], check=False)
        else:
            import subprocess

            subprocess.run(["xdg-open", path], check=False)
        return True
    except Exception as e:  # noqa: BLE001
        print(f"[platform] 경로 열기 오류: {e}")
        return False


def open_app(app_name: str) -> bool:
    """이름/실행파일로 앱 실행 (macOS 'open -a AppName' 대체).

    Windows 에서는 PATH 상의 실행파일명 또는 'start' 셸 명령으로 실행한다.
    """
    try:
        if IS_WINDOWS:
            import subprocess

            # start 는 셸 내장 명령이므로 shell=True 필요.
            # 첫 인자("")는 start 의 창 제목 자리 (경로에 공백 있어도 안전).
            subprocess.Popen(f'start "" "{app_name}"', shell=True)
            return True
        elif IS_MAC:
            import subprocess

            subprocess.run(["open", "-a", app_name], check=True, capture_output=True)
            return True
        else:
            import subprocess

            subprocess.Popen([app_name])
            return True
    except Exception as e:  # noqa: BLE001
        print(f"[platform] 앱 실행 오류({app_name}): {e}")
        return False


# ----------------------------------------------------------------------
# 프로세스 종료 (pgrep / pkill / killall 대체)
# ----------------------------------------------------------------------
def kill_processes(name_patterns: Iterable[str]) -> None:
    """이름에 패턴이 포함된 프로세스를 종료한다 (psutil 기반)."""
    try:
        import psutil  # type: ignore
    except Exception:
        return
    patterns = [p.lower() for p in name_patterns]
    for proc in psutil.process_iter(["name", "cmdline"]):
        try:
            name = (proc.info.get("name") or "").lower()
            cmdline = " ".join(proc.info.get("cmdline") or []).lower()
            if any(p in name or p in cmdline for p in patterns):
                proc.kill()
        except Exception:
            continue


def is_process_running(name_patterns: Iterable[str]) -> bool:
    """이름/커맨드라인에 패턴이 포함된 프로세스가 실행 중인지 확인."""
    try:
        import psutil  # type: ignore
    except Exception:
        return False
    patterns = [p.lower() for p in name_patterns]
    for proc in psutil.process_iter(["name", "cmdline"]):
        try:
            name = (proc.info.get("name") or "").lower()
            cmdline = " ".join(proc.info.get("cmdline") or []).lower()
            if any(p in name or p in cmdline for p in patterns):
                return True
        except Exception:
            continue
    return False


# ----------------------------------------------------------------------
# 알림 (osascript display notification 대체)
#   - 트레이 아이콘이 있으면 app.py 가 set_notifier() 로 등록한다.
#   - 없으면 win10toast/plyer, 최종적으로 콘솔 출력으로 폴백.
# ----------------------------------------------------------------------
_notifier: Optional[Callable[[str, str], None]] = None


def set_notifier(func: Optional[Callable[[str, str], None]]) -> None:
    """알림 표시 콜백 등록 (예: tray.notify)."""
    global _notifier
    _notifier = func


def show_notification(title: str, message: str) -> None:
    """데스크톱 알림 표시."""
    if _notifier is not None:
        try:
            _notifier(title, message)
            return
        except Exception:
            pass
    # 폴백 1: win10toast
    if IS_WINDOWS:
        try:
            from win10toast import ToastNotifier  # type: ignore

            ToastNotifier().show_toast(title, message, duration=3, threaded=True)
            return
        except Exception:
            pass
    # 폴백 2: plyer
    try:
        from plyer import notification  # type: ignore

        notification.notify(title=title, message=message, timeout=3)
        return
    except Exception:
        pass
    # 폴백 3: 콘솔
    print(f"[알림] {title}: {message}")


# ----------------------------------------------------------------------
# 마우스 / 화면 제어 (Quartz CGEvent + AppKit NSScreen 대체)
#   pyautogui 기반. pyautogui 의 failsafe 는 끈다 (모서리 이동 시 예외 방지).
# ----------------------------------------------------------------------
_pyautogui = None


def _get_pyautogui():
    global _pyautogui
    if _pyautogui is None:
        try:
            import pyautogui  # type: ignore

            pyautogui.FAILSAFE = False
            pyautogui.PAUSE = 0.0
            _pyautogui = pyautogui
        except Exception:
            _pyautogui = False
    return _pyautogui or None


def screen_size() -> tuple[int, int, int, int]:
    """가상 화면 범위 (min_x, min_y, width, height) 반환."""
    if IS_WINDOWS:
        try:
            import win32api  # type: ignore
            import win32con  # type: ignore

            min_x = win32api.GetSystemMetrics(win32con.SM_XVIRTUALSCREEN)
            min_y = win32api.GetSystemMetrics(win32con.SM_YVIRTUALSCREEN)
            w = win32api.GetSystemMetrics(win32con.SM_CXVIRTUALSCREEN)
            h = win32api.GetSystemMetrics(win32con.SM_CYVIRTUALSCREEN)
            return (int(min_x), int(min_y), int(w), int(h))
        except Exception:
            pass
    pg = _get_pyautogui()
    if pg is not None:
        w, h = pg.size()
        return (0, 0, int(w), int(h))
    return (0, 0, 1920, 1080)


def move_mouse(x: int, y: int) -> None:
    pg = _get_pyautogui()
    if pg is not None:
        try:
            pg.moveTo(x, y, _pause=False)
        except Exception:
            pass


def click_mouse(x: int, y: int) -> None:
    pg = _get_pyautogui()
    if pg is not None:
        try:
            pg.click(x, y, _pause=False)
        except Exception:
            pass


def mouse_down(x: int, y: int) -> None:
    pg = _get_pyautogui()
    if pg is not None:
        try:
            pg.moveTo(x, y, _pause=False)
            pg.mouseDown(_pause=False)
        except Exception:
            pass


def mouse_drag(x: int, y: int) -> None:
    pg = _get_pyautogui()
    if pg is not None:
        try:
            pg.moveTo(x, y, _pause=False)
        except Exception:
            pass


def mouse_up(x: int, y: int) -> None:
    pg = _get_pyautogui()
    if pg is not None:
        try:
            pg.moveTo(x, y, _pause=False)
            pg.mouseUp(_pause=False)
        except Exception:
            pass


def scroll(direction: str, amount: int = 8) -> None:
    """마우스 휠 스크롤. direction: 'up' | 'down'."""
    pg = _get_pyautogui()
    if pg is not None:
        try:
            clicks = amount if direction == "up" else -amount
            pg.scroll(clicks * 20)  # pyautogui 스크롤 단위 보정
        except Exception:
            pass


# ----------------------------------------------------------------------
# 시스템 제어 단축키 (osascript Mission Control 등 대체 → Windows 단축키)
# ----------------------------------------------------------------------
def system_control(action: str) -> None:
    """제스처 → Windows 시스템 제어 단축키 매핑.

    action:
        task_view    → Win+Tab   (Mission Control 대응)
        show_desktop → Win+D
        minimize     → Win+Down
        restore      → Win+Shift+M (최소화된 창 복원)
        maximize     → Win+Up
        close        → Alt+F4
    """
    try:
        from pynput.keyboard import Controller, Key

        kb = Controller()

        def combo(*keys):
            for k in keys:
                kb.press(k)
            for k in reversed(keys):
                kb.release(k)

        if action == "task_view":
            combo(Key.cmd, Key.tab)
        elif action == "show_desktop":
            combo(Key.cmd, "d")
        elif action == "minimize":
            combo(Key.cmd, Key.down)
        elif action == "restore":
            combo(Key.cmd, Key.shift, "m")
        elif action == "maximize":
            combo(Key.cmd, Key.up)
        elif action == "close":
            combo(Key.alt, Key.f4)
    except Exception as e:  # noqa: BLE001
        print(f"[platform] system_control 오류({action}): {e}")
