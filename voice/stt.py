"""
Speech-to-text (spec section 2).

Recording uses VAD to detect end-of-utterance (silence_timeout_ms)
so the user doesn't have to hit a button to stop talking. Transcription
runs locally via faster-whisper — no audio ever leaves the machine
(spec section 24).
"""

from __future__ import annotations

import queue
import time

import numpy as np
import sounddevice as sd

from core.config import get_config
from core.logging_setup import get_logger
from voice.vad import VoiceActivityDetector

log = get_logger()


class AudioRecorder:
    """Records one utterance from the microphone, stopping automatically
    after a configured amount of trailing silence."""

    def __init__(self) -> None:
        self._cfg = get_config().audio
        self._vad = VoiceActivityDetector()
        # WebRTC VAD requires exactly 10/20/30ms frames.
        self._frame_ms = 30
        self._frame_samples = int(self._cfg.sample_rate * self._frame_ms / 1000)

    def record_utterance(self) -> np.ndarray:
        cfg = self._cfg
        q: queue.Queue[np.ndarray] = queue.Queue()

        def callback(indata, frames, time_info, status):
            if status:
                log.debug(f"Audio status: {status}")
            q.put(indata.copy())

        frames: list[np.ndarray] = []
        silence_ms = 0
        speech_detected = False
        start_time = time.time()

        with sd.InputStream(
            samplerate=cfg.sample_rate,
            channels=cfg.channels,
            dtype="int16",
            blocksize=self._frame_samples,
            device=cfg.input_device,
            callback=callback,
        ):
            log.info("Recording utterance...")
            while True:
                if time.time() - start_time > cfg.max_utterance_seconds:
                    log.info("Max utterance length reached")
                    break
                try:
                    chunk = q.get(timeout=1.0)
                except queue.Empty:
                    continue

                frames.append(chunk)
                frame_bytes = chunk.tobytes()
                try:
                    is_speech = self._vad.is_speech(frame_bytes)
                except Exception:
                    is_speech = True  # fail open — better to keep recording than cut off

                if is_speech:
                    speech_detected = True
                    silence_ms = 0
                elif speech_detected:
                    silence_ms += self._frame_ms
                    if silence_ms >= cfg.silence_timeout_ms:
                        log.info("Silence detected, ending utterance")
                        break

        if not frames:
            return np.zeros(0, dtype=np.int16)
        return np.concatenate(frames, axis=0).flatten()


class SpeechToText:
    def __init__(self) -> None:
        cfg = get_config().stt
        from faster_whisper import WhisperModel

        device = cfg.device
        compute_type = cfg.compute_type
        if device == "auto":
            device = self._detect_device()
        if compute_type == "auto":
            compute_type = "float16" if device == "cuda" else "int8"

        log.info(f"Loading Whisper model '{cfg.model}' on {device} ({compute_type})")
        try:
            self._model = WhisperModel(cfg.model, device=device, compute_type=compute_type)
        except Exception as e:
            log.warning(f"Failed to load '{cfg.model}' ({e}); falling back to 'small'")
            self._model = WhisperModel("small", device=device, compute_type=compute_type)

        self._language = cfg.language

    @staticmethod
    def _detect_device() -> str:
        try:
            import torch

            return "cuda" if torch.cuda.is_available() else "cpu"
        except ImportError:
            return "cpu"

    def transcribe(self, audio_int16: np.ndarray) -> str:
        if audio_int16.size == 0:
            return ""
        audio_float = audio_int16.astype(np.float32) / 32768.0
        segments, _info = self._model.transcribe(
            audio_float,
            language=self._language,  # None -> auto-detect (handles Hindi/English mixed speech)
            vad_filter=True,
        )
        text = " ".join(seg.text.strip() for seg in segments)
        log.info(f"Transcribed {len(text)} chars")
        return text.strip()
