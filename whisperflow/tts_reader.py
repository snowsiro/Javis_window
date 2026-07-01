"""TTS (Text-to-Speech) 모듈 - Windows SAPI5 (pyttsx3) 사용

macOS 원본의 NSSpeechSynthesizer / `say` 를 Windows SAPI5 로 대체한다.
pyttsx3 는 Windows(SAPI5) / macOS(NSSS) / Linux(espeak) 를 모두 지원하므로
크로스 플랫폼으로 동작한다.
"""

import sys
import threading
from typing import Optional

try:
    import pyttsx3
    HAS_PYTTSX3 = True
except ImportError:
    HAS_PYTTSX3 = False

_IS_WINDOWS = sys.platform.startswith("win")


def _com_initialize() -> bool:
    """Windows SAPI5(COM)를 현재 스레드에서 사용 가능하게 초기화.

    pyttsx3 를 백그라운드 스레드에서 쓰려면 스레드마다 CoInitialize 가
    필요하다 (없으면 'CoInitialize has not been called' 에러).
    초기화에 성공(또는 이미 초기화)하면 True 반환.
    """
    if not _IS_WINDOWS:
        return False
    try:
        import pythoncom  # pywin32
        pythoncom.CoInitialize()
        return True
    except Exception:
        try:
            import comtypes
            comtypes.CoInitialize()
            return True
        except Exception:
            return False


def _com_uninitialize() -> None:
    """_com_initialize 와 짝을 이루는 해제."""
    if not _IS_WINDOWS:
        return
    try:
        import pythoncom
        pythoncom.CoUninitialize()
    except Exception:
        try:
            import comtypes
            comtypes.CoUninitialize()
        except Exception:
            pass


def detect_language(text: str) -> str:
    """텍스트의 주요 언어를 유니코드 범위로 감지

    Returns:
        언어 코드: "ko", "ja", "zh", "en"
    """
    if not text:
        return "en"

    counts = {"ko": 0, "ja": 0, "zh": 0, "en": 0}

    for char in text:
        cp = ord(char)
        # 한글 (가-힣, ㄱ-ㅎ, ㅏ-ㅣ)
        if (0xAC00 <= cp <= 0xD7A3 or
                0x3131 <= cp <= 0x318E):
            counts["ko"] += 1
        # 히라가나/카타카나
        elif (0x3040 <= cp <= 0x309F or
              0x30A0 <= cp <= 0x30FF):
            counts["ja"] += 1
        # CJK 통합 한자 (한국어/일본어/중국어 공용)
        elif 0x4E00 <= cp <= 0x9FFF:
            counts["zh"] += 1
        elif char.isascii() and char.isalpha():
            counts["en"] += 1

    # 한글/일본어가 있으면 CJK 한자는 해당 언어에 포함
    if counts["ko"] > 0 and counts["zh"] > 0:
        counts["ko"] += counts["zh"]
        counts["zh"] = 0
    elif counts["ja"] > 0 and counts["zh"] > 0:
        counts["ja"] += counts["zh"]
        counts["zh"] = 0

    # 가장 많은 언어 반환
    max_lang = max(counts, key=counts.get)
    if counts[max_lang] == 0:
        return "en"
    return max_lang


# 언어별 선호 음성 이름 후보 (Windows SAPI5 내장 음성)
# 설치된 언어팩에 따라 없을 수 있으므로 이름 부분 문자열로 매칭한다.
PREFERRED_VOICES = {
    "ko": ["heami", "korean", "ko-kr"],
    "en": ["zira", "david", "mark", "en-us", "english"],
    "ja": ["haruka", "ayumi", "sayaka", "ichiro", "ja-jp", "japanese"],
    "zh": ["huihui", "yaoyao", "kangkang", "zh-cn", "chinese"],
}


class TTSReader:
    """pyttsx3(SAPI5) 기반 TTS 리더.

    언어를 자동 감지하여 설치된 음성 중 가장 적합한 것을 고른다.
    pyttsx3 엔진은 스레드 안전하지 않으므로 발화마다 별도 스레드에서
    새 엔진을 생성해 재생하고, stop() 시 엔진을 정지한다.
    """

    def __init__(self):
        self._lock = threading.Lock()
        self._rate: int = 200  # words per minute
        self._speaking = False
        self._engine = None  # 현재 재생 중인 엔진 (stop 용)
        self._forced_voice: Optional[str] = None  # set_voice 로 강제 지정된 음성 id
        self._voice_cache: Optional[list] = None

    # ------------------------------------------------------------------
    @property
    def is_speaking(self) -> bool:
        with self._lock:
            return self._speaking

    def set_rate(self, rate: int) -> None:
        """읽기 속도 설정 (words per minute)"""
        self._rate = rate

    def _list_voices(self) -> list:
        """설치된 음성 목록(캐시). 어떤 스레드에서 불려도 안전 (COM 초기화 포함)."""
        if self._voice_cache is not None:
            return self._voice_cache
        if not HAS_PYTTSX3:
            self._voice_cache = []
            return self._voice_cache
        com_ok = _com_initialize()
        try:
            engine = pyttsx3.init()
            voices = engine.getProperty("voices")
            self._voice_cache = list(voices)
            try:
                engine.stop()
            except Exception:
                pass
        except Exception:
            self._voice_cache = []
        finally:
            if com_ok:
                _com_uninitialize()
        return self._voice_cache

    def set_voice(self, voice_name: str) -> None:
        """음성 강제 지정 (이름 부분 문자열 매칭)."""
        for v in self._list_voices():
            if voice_name.lower() in (v.name or "").lower() or \
               voice_name.lower() in (v.id or "").lower():
                self._forced_voice = v.id
                return
        print(f"[TTS] 음성을 찾을 수 없음: {voice_name}")

    def _select_voice_for_language(self, lang: str) -> Optional[str]:
        """언어에 맞는 음성 id 를 선택. 없으면 None(기본 음성)."""
        if self._forced_voice:
            return self._forced_voice
        candidates = PREFERRED_VOICES.get(lang, PREFERRED_VOICES["en"])
        voices = self._list_voices()
        # 1) 선호 이름 후보로 매칭
        for cand in candidates:
            for v in voices:
                haystack = f"{v.name or ''} {v.id or ''}".lower()
                if cand in haystack:
                    return v.id
        # 2) 음성 메타데이터 languages 로 매칭
        lang_prefix = {"ko": "ko", "en": "en", "ja": "ja", "zh": "zh"}.get(lang, "en")
        for v in voices:
            try:
                langs = " ".join(
                    l.decode() if isinstance(l, bytes) else str(l)
                    for l in (v.languages or [])
                ).lower()
            except Exception:
                langs = ""
            if lang_prefix in langs or lang_prefix in (v.id or "").lower():
                return v.id
        return None

    def speak(self, text: str) -> None:
        """텍스트를 음성으로 읽기 (비동기).

        언어를 자동 감지하여 적절한 음성을 선택한다.
        이미 읽기 중이면 중지 후 새 텍스트를 읽는다.
        """
        if not text or not text.strip():
            return
        if not HAS_PYTTSX3:
            print("[TTS] pyttsx3 미설치 — TTS 비활성화")
            return

        if self.is_speaking:
            self.stop()

        lang = detect_language(text)
        voice_id = self._select_voice_for_language(lang)
        print(f"[TTS] 언어: {lang}, 음성: {voice_id}, 텍스트: {text[:50]}...")

        def _run():
            with self._lock:
                self._speaking = True
            com_ok = _com_initialize()  # SAPI5는 스레드마다 COM 초기화 필요
            try:
                engine = pyttsx3.init()
                engine.setProperty("rate", self._rate)
                if voice_id:
                    try:
                        engine.setProperty("voice", voice_id)
                    except Exception:
                        pass
                with self._lock:
                    self._engine = engine
                engine.say(text)
                engine.runAndWait()
            except Exception as e:  # noqa: BLE001
                print(f"[TTS] 재생 오류: {e}")
            finally:
                with self._lock:
                    self._speaking = False
                    self._engine = None
                if com_ok:
                    _com_uninitialize()

        threading.Thread(target=_run, daemon=True).start()

    def stop(self) -> None:
        """읽기 중지"""
        with self._lock:
            engine = self._engine
            self._speaking = False
        if engine is not None:
            try:
                engine.stop()
            except Exception:
                pass
        print("[TTS] 읽기 중지")


# 전역 TTS 인스턴스
tts_reader = TTSReader()
