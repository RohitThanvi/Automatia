"""
Confirmation gate for MEDIUM/HIGH risk tool calls (spec section 16).

Phase 1 implements this as a synchronous CLI/voice prompt. The
dashboard (Phase 7) will implement the same `Confirmer` interface
over a websocket so the UI can show a "Say 'confirm' to continue"
banner instead — nothing else in the codebase needs to change.
"""

from __future__ import annotations

from abc import ABC, abstractmethod

from core.logging_setup import get_logger

log = get_logger()


class Confirmer(ABC):
    @abstractmethod
    def confirm(self, message: str) -> bool:
        """Block until the user approves or denies. Return True to proceed."""


class CliConfirmer(Confirmer):
    """Default confirmer: prints the prompt and reads a line from stdin.
    `main.py` wires the voice loop's transcription into this same
    interface when running hands-free, so callers never need to know
    whether confirmation came from text or speech."""

    def confirm(self, message: str) -> bool:
        print(f"\n[CONFIRMATION REQUIRED] {message}")
        answer = input("Type 'confirm' to proceed, anything else to cancel: ").strip().lower()
        approved = answer in {"confirm", "yes", "y"}
        log.info(f"Confirmation {'granted' if approved else 'denied'} for: {message[:60]}")
        return approved


class VoiceConfirmer(Confirmer):
    """Wraps STT + TTS so confirmation happens fully by voice.
    Injected with the already-initialized SpeechToText / TextToSpeech
    instances so no models are loaded twice."""

    def __init__(self, stt, tts, listen_fn):
        self._stt = stt
        self._tts = tts
        self._listen_fn = listen_fn  # callable -> bytes of recorded audio

    def confirm(self, message: str) -> bool:
        self._tts.speak(f"{message} Say confirm to proceed, or cancel to stop.")
        audio = self._listen_fn()
        text = self._stt.transcribe(audio).lower()
        approved = "confirm" in text and "cancel" not in text
        log.info(f"Voice confirmation {'granted' if approved else 'denied'}")
        return approved


class AutoDenyConfirmer(Confirmer):
    """Used in tests / headless runs where no human is present to answer.
    Fails closed: denies everything rather than guessing."""

    def confirm(self, message: str) -> bool:
        log.warning(f"AutoDenyConfirmer denied by default: {message[:60]}")
        return False
