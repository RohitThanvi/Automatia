"""
Voice activity detection using WebRTC VAD.

Used by the recorder in voice/stt.py to know when the user has
stopped speaking, so we don't send silence to Whisper and don't cut
the user off mid-sentence (spec section 2: "voice activity
detection", "partial/final transcription").
"""

from __future__ import annotations

import webrtcvad

from core.config import get_config


class VoiceActivityDetector:
    def __init__(self) -> None:
        cfg = get_config().audio
        self._vad = webrtcvad.Vad(cfg.vad_aggressiveness)
        self._sample_rate = cfg.sample_rate

    def is_speech(self, frame_bytes: bytes) -> bool:
        """frame_bytes must be 16-bit mono PCM, 10/20/30ms at the configured sample rate."""
        return self._vad.is_speech(frame_bytes, self._sample_rate)
