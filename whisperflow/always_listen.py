"""상시 마이크 청취 모듈 - openWakeWord 기반 웨이크 워드 감지 + VAD (크로스 플랫폼)

macOS 의 /tmp 시그널 파일과 pgrep/pkill/afplay 를 platform_utils 로 대체.
"""

import threading
import time
from pathlib import Path
from typing import Optional, Callable

import numpy as np
import sounddevice as sd
import torch
from openwakeword.model import Model
from silero_vad import load_silero_vad

from . import platform_utils as plat


# 시그널/플래그 파일 (OS 임시 디렉토리)
CONV_SIGNAL_PATH = Path(plat.temp_path("whisperflow-conversation-continue"))
TTS_FLAG_PATH = Path(plat.temp_path("whisperflow-tts-playing"))


# 청취 상태 상수
_STATE_BOOT_WAIT = "boot_wait"  # 박수 2번 대기 (시스템 온라인 전)
_STATE_IDLE = "idle"            # 웨이크 워드 대기 중
_STATE_SPEECH = "speech"        # 웨이크 워드 감지 후 녹음 중
_STATE_CONV_WAIT = "conv_wait"  # 대화 모드 — 웨이크 워드 없이 음성 대기


class AlwaysListen:
    """openWakeWord 기반 상시 마이크 모니터링 클래스.

    흐름:
      1. 대기(IDLE): openWakeWord가 16kHz 오디오를 분석하여 "Hey Jarvis" 감지 대기
      2. 감지: on_wake 콜백 호출 + 녹음 시작
      3. 녹음(SPEECH): VAD로 묵음 지속 시 녹음 종료
      4. on_speech_detected 콜백 호출 → 다시 대기 상태
    """

    def __init__(
        self,
        on_double_clap: Optional[Callable[[], None]] = None,
        on_wake: Optional[Callable[[], None]] = None,
        on_speech_detected: Optional[Callable[[np.ndarray, int], None]] = None,
        on_audio_level: Optional[Callable[[float], None]] = None,
        on_conversation_end: Optional[Callable[[], None]] = None,
        clap_threshold: float = 0.025,
        wake_threshold: float = 0.5,
        speech_threshold: float = 0.5,
        sample_rate: int = 16000,
        skip_boot_wait: bool = False,
        audio_gain: float = 20,
        conversation_timeout: float = 10.0,
    ):
        self.on_double_clap = on_double_clap
        self.on_wake = on_wake
        self.on_speech_detected = on_speech_detected
        self.on_audio_level = on_audio_level
        self.on_conversation_end = on_conversation_end
        self.clap_threshold = clap_threshold
        self.wake_threshold = wake_threshold
        self.speech_threshold = speech_threshold
        self.sample_rate = sample_rate
        self._skip_boot_wait = skip_boot_wait
        self._audio_gain = audio_gain

        self._running = False
        self._stream: Optional[sd.InputStream] = None
        self._lock = threading.Lock()
        self._muted = False

        # --- 상태 (박수 대기부터 시작) ---
        self._state: str = _STATE_BOOT_WAIT

        # --- 박수 감지 ---
        self._clap_prev_quiet: bool = True
        self._clap_last_peak: float = 0.0
        self._clap_fired: bool = False

        # --- TTS 중 박수 감지 ---
        self._tts_clap_prev_quiet: bool = True
        self._tts_clap_last_peak: float = 0.0
        self._tts_interrupted: bool = False

        # --- 웨이크 워드 감지 쿨다운 ---
        self._wake_cooldown: float = 5.0
        self._last_wake_time: float = 0.0

        # --- VAD 상태 ---
        self._silence_duration: float = 0.0
        self._silence_end: float = 3.0
        self._min_record_time: float = 3.0
        self._record_start_time: float = 0.0
        self._record_buffer: list[np.ndarray] = []

        # --- Silero VAD ---
        self._silero_model = None
        self._vad_buffer = np.array([], dtype=np.float32)

        # --- 대화 모드 ---
        self._conversation_timeout = conversation_timeout
        self._conv_wait_start: float = 0.0

        # --- openWakeWord 모델 ---
        self._oww_model: Optional[Model] = None

        self._block_samples: int = 1280  # 80ms @ 16kHz

    # ------------------------------------------------------------------
    # 공개 인터페이스
    # ------------------------------------------------------------------

    def start(self) -> None:
        if self._running:
            return

        print("[AlwaysListen] Silero VAD 모델 로드 중...")
        self._silero_model = load_silero_vad()
        print("[AlwaysListen] Silero VAD 로드 완료.")

        print("[AlwaysListen] openWakeWord 모델 로드 중 (hey_jarvis)...")
        self._oww_model = Model(
            wakeword_models=["hey_jarvis"],
            inference_framework="onnx",
        )
        print("[AlwaysListen] 모델 로드 완료.")

        CONV_SIGNAL_PATH.unlink(missing_ok=True)

        self._running = True
        self._state = _STATE_IDLE if self._skip_boot_wait else _STATE_BOOT_WAIT
        self._last_wake_time = time.monotonic()
        self._clap_fired = False

        self._stream = sd.InputStream(
            samplerate=self.sample_rate,
            channels=1,
            dtype=np.float32,
            blocksize=self._block_samples,
            callback=self._audio_callback,
        )
        self._stream.start()
        print("[AlwaysListen] 스트림 시작. Hey Jarvis를 기다리는 중...")

    def mute(self) -> None:
        self._muted = True

    def unmute(self) -> None:
        self._muted = False

    def reset_recording(self) -> None:
        self._record_buffer.clear()
        self._record_start_time = time.monotonic()
        self._silence_duration = 0.0
        self._vad_buffer = np.array([], dtype=np.float32)
        if self._silero_model is not None:
            self._silero_model.reset_states()

    def enter_conversation_mode(self) -> None:
        with self._lock:
            self._state = _STATE_CONV_WAIT
            self._conv_wait_start = time.monotonic()
            self._silence_duration = 0.0
            self._vad_buffer = np.array([], dtype=np.float32)
            if self._silero_model is not None:
                self._silero_model.reset_states()
        print(f"[AlwaysListen] 대화 모드 진입 (타임아웃: {self._conversation_timeout}초)")

    def stop(self) -> None:
        self._running = False
        if self._stream is not None:
            self._stream.stop()
            self._stream.close()
            self._stream = None
        print("[AlwaysListen] 중지됨.")

    # ------------------------------------------------------------------
    # 내부 구현
    # ------------------------------------------------------------------

    def _audio_callback(self, indata, frames, time_info, status) -> None:
        if not self._running or self._muted:
            return
        if status:
            print(f"[AlwaysListen] stream status: {status}")

        audio_raw = indata[:, 0].copy()
        block_duration = frames / self.sample_rate

        audio_amplified = np.clip(audio_raw * self._audio_gain, -1.0, 1.0)
        audio_int16 = (audio_amplified * 32767).astype(np.int16)

        try:
            if CONV_SIGNAL_PATH.exists():
                CONV_SIGNAL_PATH.unlink(missing_ok=True)
                if self._tts_interrupted:
                    self._tts_interrupted = False
                    print("[AlwaysListen] 파일 시그널 무시 (TTS 박수 중단 직후)")
                    return
                with self._lock:
                    self._state = _STATE_CONV_WAIT
                    self._conv_wait_start = time.monotonic()
                    self._silence_duration = 0.0
                    self._vad_buffer = np.array([], dtype=np.float32)
                    if self._silero_model is not None:
                        self._silero_model.reset_states()
                print("[AlwaysListen] 파일 시그널 → 대화 모드 진입")
                return

            with self._lock:
                if self._state == _STATE_BOOT_WAIT:
                    self._process_clap(audio_raw, block_duration)
                elif self._state == _STATE_IDLE:
                    if self._is_tts_playing():
                        self._process_tts_clap(audio_raw)
                    else:
                        self._process_wake(audio_int16, audio_raw)
                elif self._state == _STATE_SPEECH:
                    self._process_vad(audio_raw, block_duration)
                    if self.on_audio_level:
                        self._send_audio_bands(audio_raw)
                elif self._state == _STATE_CONV_WAIT:
                    self._process_conv_wait(audio_raw, block_duration)
        except Exception as e:  # noqa: BLE001
            print(f"[AlwaysListen] 오디오 콜백 에러 (무시): {e}")

    def _send_audio_bands(self, audio: np.ndarray) -> None:
        fft = np.abs(np.fft.rfft(audio))
        freq_count = len(fft)
        low_end = int(freq_count * 300 / 8000)
        mid_end = int(freq_count * 2000 / 8000)
        low = float(np.mean(fft[:low_end])) if low_end > 0 else 0
        mid = float(np.mean(fft[low_end:mid_end])) if mid_end > low_end else 0
        high = float(np.mean(fft[mid_end:])) if freq_count > mid_end else 0
        gain = 80
        low = min(1.0, low * gain)
        mid = min(1.0, mid * gain)
        high = min(1.0, high * gain * 1.5)
        rms = float(np.sqrt(np.mean(audio ** 2)))
        level = min(1.0, rms * 50)
        self.on_audio_level(level, low, mid, high)

    def _process_clap(self, audio: np.ndarray, block_duration: float) -> None:
        if self._clap_fired:
            return
        amplitude = float(np.max(np.abs(audio)))
        now = time.monotonic()
        is_loud = amplitude >= self.clap_threshold
        if is_loud and self._clap_prev_quiet:
            gap = now - self._clap_last_peak
            if self._clap_last_peak > 0 and 0.15 <= gap <= 1.0:
                self._clap_fired = True
                self._state = _STATE_IDLE
                print("[AlwaysListen] 더블 클랩 감지! → 웨이크 워드 대기로 전환")
                threading.Thread(target=self._fire_clap, daemon=True).start()
            else:
                self._clap_last_peak = now
        self._clap_prev_quiet = not is_loud

    def _fire_clap(self) -> None:
        if self.on_double_clap:
            try:
                self.on_double_clap()
            except Exception as e:  # noqa: BLE001
                print(f"[AlwaysListen] on_double_clap 오류: {e}")

    def _is_tts_playing(self) -> bool:
        """TTS 재생 중인지 플래그 파일로 확인. 오래된(잔여) 플래그는 정리."""
        if not TTS_FLAG_PATH.exists():
            return False
        try:
            # 플래그 파일이 30초 이상 오래되었으면 잔여로 간주하고 제거
            age = time.time() - TTS_FLAG_PATH.stat().st_mtime
            if age > 30:
                TTS_FLAG_PATH.unlink(missing_ok=True)
                print("[AlwaysListen] TTS 플래그 잔류 감지 → 제거 (오래됨)")
                return False
        except Exception:
            pass
        return True

    def _is_clap_like(self, audio: np.ndarray) -> bool:
        fft = np.abs(np.fft.rfft(audio))
        freq_count = len(fft)
        mid_end = int(freq_count * 3000 / 8000)
        low_mid = float(np.mean(fft[:mid_end])) if mid_end > 0 else 0.001
        high = float(np.mean(fft[mid_end:])) if freq_count > mid_end else 0
        ratio = high / (low_mid + 0.001)
        return ratio >= 0.6

    def _process_tts_clap(self, audio: np.ndarray) -> None:
        amplitude = float(np.max(np.abs(audio)))
        now = time.monotonic()
        tts_clap_threshold = 0.3
        is_loud = amplitude >= tts_clap_threshold
        if is_loud and self._tts_clap_prev_quiet:
            if self._is_clap_like(audio):
                gap = now - self._tts_clap_last_peak
                if self._tts_clap_last_peak > 0 and 0.1 <= gap <= 0.7:
                    self._tts_clap_last_peak = 0.0
                    print("[AlwaysListen] TTS 중 더블 클랩 감지! → TTS 중지")
                    self._tts_interrupted = True
                    CONV_SIGNAL_PATH.unlink(missing_ok=True)
                    TTS_FLAG_PATH.unlink(missing_ok=True)
                    threading.Thread(target=self._kill_tts_processes, daemon=True).start()
                else:
                    self._tts_clap_last_peak = now
        self._tts_clap_prev_quiet = not is_loud

    def _kill_tts_processes(self) -> None:
        """재생 중인 TTS 를 중단 + 인터럽트 응답음 재생 (크로스 플랫폼)."""
        import random
        import os

        plat.stop_all_sounds()
        try:
            from .tts_reader import tts_reader
            tts_reader.stop()
        except Exception:
            pass
        plat.kill_processes(["qwen_tts", "serve.py"])
        print("[AlwaysListen] TTS 중단 완료")

        sounds_dir = os.path.join(os.path.dirname(__file__), "static", "sounds")
        try:
            interrupt_files = [
                f for f in os.listdir(sounds_dir)
                if f.startswith("interrupt_") and f.endswith(".wav")
            ]
        except Exception:
            interrupt_files = []
        if interrupt_files:
            chosen = os.path.join(sounds_dir, random.choice(interrupt_files))
            plat.play_sound(chosen, rate=1.4, blocking=True)

    def _process_wake(self, audio_int16: np.ndarray, audio_f32: np.ndarray) -> None:
        if self._oww_model is None:
            return
        now = time.monotonic()
        if now - self._last_wake_time < self._wake_cooldown:
            return
        prediction = self._oww_model.predict(audio_int16)
        score = prediction.get("hey_jarvis", 0.0)
        if score >= self.wake_threshold:
            self._last_wake_time = now
            self._state = _STATE_SPEECH
            self._silence_duration = 0.0
            self._record_start_time = now
            self._record_buffer.clear()
            self._vad_buffer = np.array([], dtype=np.float32)
            if self._silero_model is not None:
                self._silero_model.reset_states()
            self._oww_model.reset()
            print(f"[AlwaysListen] 웨이크 워드 감지! (점수: {score:.3f})")
            threading.Thread(target=self._fire_wake, daemon=True).start()

    def _process_vad(self, audio: np.ndarray, block_duration: float) -> None:
        self._record_buffer.append(audio.copy())
        elapsed = time.monotonic() - self._record_start_time
        if elapsed < self._min_record_time:
            return
        self._vad_buffer = np.concatenate([self._vad_buffer, audio]) if len(self._vad_buffer) > 0 else audio.copy()
        is_speech = False
        while len(self._vad_buffer) >= 512:
            chunk = self._vad_buffer[:512]
            self._vad_buffer = self._vad_buffer[512:]
            tensor = torch.from_numpy(chunk)
            speech_prob = self._silero_model(tensor, self.sample_rate).item()
            if speech_prob >= self.speech_threshold:
                is_speech = True
        if int(elapsed * 10) % 10 == 0:
            print(f"[VAD-Silero] {elapsed:.1f}s speech={is_speech} silence={self._silence_duration:.1f}s")
        if is_speech:
            self._silence_duration = 0.0
        else:
            self._silence_duration += block_duration
            if self._silence_duration >= self._silence_end:
                self._state = _STATE_IDLE
                recorded = np.concatenate(self._record_buffer)
                self._record_buffer.clear()
                self._silence_duration = 0.0
                self._vad_buffer = np.array([], dtype=np.float32)
                if self._silero_model is not None:
                    self._silero_model.reset_states()
                if self._oww_model is not None:
                    self._oww_model.reset()
                print(f"[AlwaysListen] 녹음 종료. ({len(recorded) / self.sample_rate:.1f}초)")
                threading.Thread(
                    target=self._fire_speech,
                    args=(recorded, self.sample_rate),
                    daemon=True,
                ).start()

    def _process_conv_wait(self, audio: np.ndarray, block_duration: float) -> None:
        elapsed = time.monotonic() - self._conv_wait_start
        self._vad_buffer = np.concatenate([self._vad_buffer, audio]) if len(self._vad_buffer) > 0 else audio.copy()
        is_speech = False
        while len(self._vad_buffer) >= 512:
            chunk = self._vad_buffer[:512]
            self._vad_buffer = self._vad_buffer[512:]
            tensor = torch.from_numpy(chunk)
            speech_prob = self._silero_model(tensor, self.sample_rate).item()
            if speech_prob >= self.speech_threshold:
                is_speech = True
        if is_speech:
            self._state = _STATE_SPEECH
            self._silence_duration = 0.0
            self._record_start_time = time.monotonic()
            self._record_buffer.clear()
            self._record_buffer.append(audio.copy())
            self._vad_buffer = np.array([], dtype=np.float32)
            if self._silero_model is not None:
                self._silero_model.reset_states()
            print("[AlwaysListen] 대화 모드 → 음성 감지! 녹음 시작")
            return
        if elapsed >= self._conversation_timeout:
            self._state = _STATE_IDLE
            self._vad_buffer = np.array([], dtype=np.float32)
            if self._silero_model is not None:
                self._silero_model.reset_states()
            print(f"[AlwaysListen] 대화 모드 타임아웃 ({self._conversation_timeout}초) → 웨이크 워드 대기")
            threading.Thread(target=self._fire_conversation_end, daemon=True).start()

    def _fire_conversation_end(self) -> None:
        if self.on_conversation_end:
            try:
                self.on_conversation_end()
            except Exception as e:  # noqa: BLE001
                print(f"[AlwaysListen] on_conversation_end 오류: {e}")

    def _fire_wake(self) -> None:
        if self.on_wake:
            try:
                self.on_wake()
            except Exception as e:  # noqa: BLE001
                print(f"[AlwaysListen] on_wake 오류: {e}")

    def _fire_speech(self, audio: np.ndarray, sample_rate: int) -> None:
        if self.on_speech_detected:
            try:
                self.on_speech_detected(audio, sample_rate)
            except Exception as e:  # noqa: BLE001
                print(f"[AlwaysListen] on_speech_detected 오류: {e}")


# ------------------------------------------------------------------
# Standalone 테스트
# ------------------------------------------------------------------
if __name__ == "__main__":
    def on_wake():
        print("[웨이크] 자비스 감지!")

    def on_speech(audio: np.ndarray, sr: int):
        print(f"[음성] {len(audio) / sr:.1f}초 녹음됨 (샘플 수: {len(audio)})")

    listener = AlwaysListen(on_wake=on_wake, on_speech_detected=on_speech)
    listener.start()
    print("Hey Jarvis 라고 말해보세요...")
    while True:
        time.sleep(0.5)
