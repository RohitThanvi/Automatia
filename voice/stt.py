"""
Speech-to-text (spec section 2).

Recording uses VAD to detect end-of-utterance (silence_timeout_ms)
so the user doesn't have to hit a button to stop talking. Transcription
runs locally via faster-whisper — no audio ever leaves the machine
(spec section 24).

Optional end-phrase mode: if audio.end_phrase is configured (e.g.
"over"), an ordinary pause no longer ends the recording — only saying
that phrase does (or hitting max_utterance_seconds as a hard cap).
This is for dictating something with natural pauses (an essay, a long
multi-clause instruction) without getting cut off mid-thought. Since
there's no cheap way to detect a spoken phrase without transcribing,
end-phrase mode re-transcribes the audio captured so far every time a
pause lasts end_phrase_recheck_ms, checking only whether it ends with
the phrase — not on every frame, and not a continuous stream.
"""

from __future__ import annotations

import os
import queue
import re
import time
from typing import Optional

import numpy as np
import sounddevice as sd

from core.config import get_config
from core.logging_setup import get_logger
from voice.vad import VoiceActivityDetector

log = get_logger()


def _normalize(text: str) -> str:
    return re.sub(r"[^\w\s]", "", text).strip().lower()


def ends_with_phrase(text: str, phrase: Optional[str]) -> bool:
    """Pure text logic, deliberately separated from any audio/model
    code so it's covered by fast unit tests with plain strings."""
    if not phrase:
        return False
    norm_phrase = _normalize(phrase)
    if not norm_phrase:
        return False
    return _normalize(text).endswith(norm_phrase)


def strip_end_phrase(text: str, phrase: Optional[str]) -> str:
    """Remove a trailing end-phrase from the final transcript before it
    reaches the planner — the user said "over" to stop talking, not as
    part of their actual command."""
    if not ends_with_phrase(text, phrase):
        return text
    words = text.split()
    n = len(phrase.split())
    trimmed = " ".join(words[: max(len(words) - n, 0)])
    return trimmed.strip().rstrip(",.!?;:").strip()


class AudioRecorder:
    """Records one utterance from the microphone, stopping automatically
    after a configured amount of trailing silence — or, in end-phrase
    mode, only when that phrase is heard (or the max length is hit)."""

    def __init__(self, stt: Optional["SpeechToText"] = None) -> None:
        self._cfg = get_config().audio
        self._vad = VoiceActivityDetector()
        # WebRTC VAD requires exactly 10/20/30ms frames.
        self._frame_ms = 30
        self._frame_samples = int(self._cfg.sample_rate * self._frame_ms / 1000)
        self._stt = stt

        if self._cfg.end_phrase and self._stt is None:
            log.warning(
                f"audio.end_phrase is set to '{self._cfg.end_phrase}' but no SpeechToText "
                "instance was passed to AudioRecorder — falling back to plain silence-timeout "
                "behavior. Construct AudioRecorder(stt=...) to enable end-phrase mode."
            )

    def record_utterance(self) -> np.ndarray:
        cfg = self._cfg
        end_phrase = cfg.end_phrase if self._stt is not None else None
        q: queue.Queue[np.ndarray] = queue.Queue()

        def callback(indata, frames, time_info, status):
            if status:
                log.debug(f"Audio status: {status}")
            q.put(indata.copy())

        frames: list[np.ndarray] = []
        silence_ms = 0
        next_phrase_check_ms = cfg.silence_timeout_ms
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
            log.info(f"Recording utterance{' (end-phrase mode)' if end_phrase else ''}...")
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
                    next_phrase_check_ms = cfg.silence_timeout_ms
                elif speech_detected:
                    silence_ms += self._frame_ms

                    if end_phrase is None:
                        if silence_ms >= cfg.silence_timeout_ms:
                            log.info("Silence detected, ending utterance")
                            break
                    elif silence_ms >= next_phrase_check_ms:
                        partial_audio = np.concatenate(frames, axis=0).flatten()
                        partial_text = self._stt.transcribe(partial_audio)
                        if ends_with_phrase(partial_text, end_phrase):
                            log.info(f"End phrase '{end_phrase}' detected, ending utterance")
                            break
                        log.debug(
                            f"Pause without end phrase (checked at {silence_ms}ms) — continuing to listen"
                        )
                        next_phrase_check_ms += cfg.end_phrase_recheck_ms

        if not frames:
            return np.zeros(0, dtype=np.int16)
        return np.concatenate(frames, axis=0).flatten()


class SpeechToText:
    def __init__(self) -> None:
        cfg = get_config().stt
        self._provider = cfg.provider
        self._language = cfg.language

        if self._provider == "groq":
            # No local model to load at all — every transcribe() call is a
            # network request to Groq's hosted whisper-large-v3-turbo.
            # This is what actually fixes CPU-bound latency: local
            # faster-whisper on a CPU was re-transcribing the whole growing
            # buffer on every end-phrase recheck (~20s+ per call observed);
            # Groq's LPU inference does the same call in well under a second.
            from groq import Groq

            api_key = os.environ.get("GROQ_API_KEY")
            if not api_key:
                raise RuntimeError(
                    "stt.provider is 'groq' in config.yaml but the GROQ_API_KEY "
                    "environment variable is not set. Get a key at "
                    "https://console.groq.com/keys, then (PowerShell) "
                    '$env:GROQ_API_KEY = "gsk_..." before running.'
                )
            self._groq_client = Groq(api_key=api_key)
            self._groq_model = cfg.model
            log.info(f"Using Groq hosted STT ('{self._groq_model}') — no local model to load")
            return

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

    @staticmethod
    def _detect_device() -> str:
        try:
            import torch

            return "cuda" if torch.cuda.is_available() else "cpu"
        except ImportError:
            return "cpu"

    @staticmethod
    def _to_wav_bytes(audio_int16: np.ndarray, sample_rate: int = 16000) -> bytes:
        """Groq's transcription endpoint wants a file, not raw PCM — wrap
        the int16 samples in a minimal WAV container using only the
        stdlib (no extra dependency for this)."""
        import io
        import wave

        buf = io.BytesIO()
        with wave.open(buf, "wb") as wf:
            wf.setnchannels(1)
            wf.setsampwidth(2)  # int16 = 2 bytes
            wf.setframerate(sample_rate)
            wf.writeframes(audio_int16.tobytes())
        return buf.getvalue()

    def _transcribe_groq(self, audio_int16: np.ndarray) -> str:
        wav_bytes = self._to_wav_bytes(audio_int16)
        result = self._groq_client.audio.transcriptions.create(
            file=("audio.wav", wav_bytes),
            model=self._groq_model,
            language=self._language,  # None -> auto-detect
        )
        return (result.text or "").strip()

    def transcribe(self, audio_int16: np.ndarray) -> str:
        if audio_int16.size == 0:
            return ""

        if self._provider == "groq":
            text = self._transcribe_groq(audio_int16)
            log.info(f"Transcribed {len(text)} chars (groq)")
            return text

        audio_float = audio_int16.astype(np.float32) / 32768.0
        segments, _info = self._model.transcribe(
            audio_float,
            language=self._language,  # None -> auto-detect (handles Hindi/English mixed speech)
            vad_filter=True,
        )
        text = " ".join(seg.text.strip() for seg in segments)
        log.info(f"Transcribed {len(text)} chars")
        return text.strip()
