"""
Wake word detection (spec section 3).

Uses openWakeWord, which runs a small ONNX model continuously on the
microphone stream with negligible CPU usage — no audio is buffered
or sent anywhere except into this in-memory model.

IMPORTANT: openWakeWord ships a few pre-trained demo models (e.g.
"alexa", "hey_jarvis") but not one for the literal word "start".
For a real deployment, either:
  1. Train a custom model for "start" with openWakeWord's training
     notebook (github.com/dscripka/openWakeWord) and point
     wake_word.model in config.yaml at the resulting .onnx file, or
  2. Use "hey_jarvis" (bundled) as the wake phrase instead, which
     needs zero extra setup.
Phase 1 defaults to the bundled model and logs a warning so this
limitation is visible rather than silently wrong.
"""

from __future__ import annotations

import numpy as np

from core.config import get_config
from core.logging_setup import get_logger

log = get_logger()

_BUNDLED_MODELS = {"alexa", "hey_jarvis", "hey_mycroft", "timer"}


class WakeWordDetector:
    def __init__(self) -> None:
        cfg = get_config().wake_word
        self._threshold = cfg.threshold
        self._model_name = cfg.model

        if cfg.phrase.lower() == "start" and cfg.model in _BUNDLED_MODELS:
            log.warning(
                f"wake_word.phrase is 'start' but wake_word.model is the bundled "
                f"'{cfg.model}' demo model, which listens for '{cfg.model}', not 'start'. "
                "Train a custom openWakeWord model for 'start' or say the bundled "
                "phrase instead. See voice/wakeword.py docstring."
            )

        from openwakeword.model import Model

        self._model = Model(wakeword_models=[cfg.model],inference_framework="onnx",)
    def process_frame(self, frame: np.ndarray) -> bool:
        """frame: int16 mono PCM samples at 16kHz, ~80ms chunks.
        Returns True the instant the wake word score crosses threshold."""
        predictions = self._model.predict(frame)
        return any(score >= self._threshold for score in predictions.values())

    def reset(self) -> None:
        self._model.reset()
