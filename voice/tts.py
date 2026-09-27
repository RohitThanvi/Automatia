"""
Text-to-speech (spec section 2 / 21).

pyttsx3 is the Phase 1 default: it's offline, needs no model
download, and works out of the box on Windows via SAPI5. Piper/Kokoro
give more natural voices and are supported behind the same interface —
switch `tts.engine` in config.yaml once you've downloaded a voice
model for either.
"""

from __future__ import annotations

from abc import ABC, abstractmethod

from core.config import get_config
from core.logging_setup import get_logger

log = get_logger()


class TextToSpeech(ABC):
    @abstractmethod
    def speak(self, text: str) -> None: ...


class Pyttsx3TTS(TextToSpeech):
    """A fresh pyttsx3 engine is created for every speak() call rather
    than reused. Reusing one engine instance across multiple say()/
    runAndWait() cycles is a well-known pyttsx3-on-Windows failure mode:
    the SAPI5 COM driver works for the first utterance and then silently
    stops producing audio on later calls, with no exception raised —
    it just goes quiet. Recreating the engine costs a small amount of
    latency per call but is what actually keeps this reliable."""

    def __init__(self) -> None:
        self._cfg = get_config().tts

    def _new_engine(self):
        import pyttsx3

        engine = pyttsx3.init()
        engine.setProperty("rate", self._cfg.rate)
        if self._cfg.voice:
            engine.setProperty("voice", self._cfg.voice)
        return engine

    def speak(self, text: str) -> None:
        if not text.strip():
            return
        log.info(f"Speaking ({len(text)} chars)")
        try:
            engine = self._new_engine()
            engine.say(text)
            engine.runAndWait()
            engine.stop()
        except Exception:
            # Never let a TTS hiccup take down the whole voice loop —
            # better to silently skip one spoken reply than crash the
            # process and go fully unresponsive.
            log.exception("TTS speak() failed — continuing without audio for this reply")


class PiperTTS(TextToSpeech):
    """Requires a downloaded .onnx Piper voice model — set
    tts.piper_model_path in config.yaml. Piper produces much more
    natural speech than pyttsx3 and still runs fully offline."""

    def __init__(self) -> None:
        cfg = get_config().tts
        if not cfg.piper_model_path:
            raise ValueError("tts.piper_model_path must be set to use the piper engine")
        from piper.voice import PiperVoice  # pip install piper-tts

        self._voice = PiperVoice.load(cfg.piper_model_path)

    def speak(self, text: str) -> None:
        import io
        import wave

        import sounddevice as sd
        import numpy as np

        if not text.strip():
            return
        buf = io.BytesIO()
        with wave.open(buf, "wb") as wav_file:
            self._voice.synthesize(text, wav_file)
        buf.seek(0)
        with wave.open(buf, "rb") as wav_file:
            audio = np.frombuffer(wav_file.readframes(wav_file.getnframes()), dtype=np.int16)
            sd.play(audio, samplerate=wav_file.getframerate())
            sd.wait()


def build_tts() -> TextToSpeech:
    engine = get_config().tts.engine
    if engine == "pyttsx3":
        return Pyttsx3TTS()
    if engine == "piper":
        return PiperTTS()
    raise ValueError(f"Unsupported tts.engine '{engine}' (kokoro integration is a Phase 8 TODO)")
