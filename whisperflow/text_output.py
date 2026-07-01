"""텍스트 출력 모듈 (크로스 플랫폼)

macOS 의 osascript 기반 붙여넣기/활성앱 추적을 platform_utils 로 대체.
"""

from typing import Literal, Optional

from .config import config
from . import platform_utils as plat


class TextOutput:
    """텍스트 출력 클래스"""

    # 마지막 활성 창/앱
    _last_active_app: Optional[str] = None
    _last_hwnd: Optional[int] = None

    @staticmethod
    def to_clipboard(text: str) -> bool:
        """클립보드에 복사"""
        return plat.copy_to_clipboard(text)

    @classmethod
    def save_active_app(cls):
        """현재 활성화된 창을 저장 (녹음 시작 전에 호출 → 붙여넣기 시 복원)."""
        try:
            cls._last_hwnd = plat.get_foreground_window()
            cls._last_active_app = plat.get_foreground_app_name()
            if cls._last_active_app:
                print(f"[앱 저장] {cls._last_active_app}")
        except Exception as e:  # noqa: BLE001
            print(f"[앱 저장 오류] {e}")

    @classmethod
    def type_text(cls, text: str) -> bool:
        """클립보드에 복사 후 이전 활성 창에 자동 붙여넣기 (Ctrl+V)"""
        import time
        try:
            plat.copy_to_clipboard(text)
            print("[붙여넣기] 클립보드 복사 완료")
            time.sleep(0.3)
            success = plat.paste_to_active(
                enter=config.auto_enter, restore_hwnd=cls._last_hwnd
            )
            if success:
                print(f"[붙여넣기] Ctrl+V 전송 완료 -> {cls._last_active_app}")
            return success
        except Exception as e:  # noqa: BLE001
            print(f"[붙여넣기] 오류: {e}")
            return False

    @classmethod
    def output(cls, text: str, mode: Literal["clipboard", "type"] = None) -> bool:
        """설정에 따라 텍스트 출력"""
        if mode is None:
            mode = config.output_mode

        if mode == "type":
            return cls.type_text(text)
        else:
            return cls.to_clipboard(text)

    @staticmethod
    def show_notification(title: str, message: str) -> None:
        """데스크톱 알림 표시"""
        plat.show_notification(title, message)
