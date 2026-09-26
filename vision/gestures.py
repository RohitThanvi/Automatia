"""
Gesture recognition (spec section 15).

Two independent, testable pieces on purpose:
  1. classify_static_gesture(landmarks) — pure geometry, no I/O, no
     MediaPipe/camera dependency at import time, so it's covered by
     fast unit tests with synthetic landmark data.
  2. GestureController — the actual webcam loop, built on top of (1)
     plus swipe tracking and per-gesture debounce/cooldown (spec:
     "Gestures must have debounce/cooldown logic to prevent accidental
     repeated actions").

Disabled by default (config.yaml gestures.enabled: false) and never
uses an LLM per frame (spec: "Do not use an LLM for every webcam
frame") — classification is 21-point landmark geometry only.
"""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass, field
from typing import Callable, Optional

from core.config import get_config
from core.logging_setup import get_logger

log = get_logger()

# MediaPipe Hands landmark indices (21 points per hand).
_WRIST = 0
_THUMB_TIP, _THUMB_MCP = 4, 2
_FINGER_TIPS = {"index": 8, "middle": 12, "ring": 16, "pinky": 20}
_FINGER_PIPS = {"index": 6, "middle": 10, "ring": 14, "pinky": 18}

# Gesture name -> agent action (spec section 15's mapping table).
GESTURE_ACTIONS: dict[str, str] = {
    "open_palm": "wake",
    "pinch": "click",
    "thumbs_up": "confirm",
    "closed_fist": "stop",
    "swipe_left": "previous",
    "swipe_right": "next",
}


def _dist(a: tuple[float, float], b: tuple[float, float]) -> float:
    return ((a[0] - b[0]) ** 2 + (a[1] - b[1]) ** 2) ** 0.5


def classify_static_gesture(landmarks: list[tuple[float, float]]) -> Optional[str]:
    """landmarks: 21 (x, y) points in MediaPipe's normalized [0,1] image
    coordinates (y increases downward). Returns one of "open_palm",
    "pinch", "thumbs_up", "closed_fist", or None if no static gesture
    is recognized (e.g. mid-swipe, or an ambiguous hand pose).

    Swipe left/right is NOT classified here — it's a multi-frame wrist
    trajectory, handled by GestureController._check_swipe below.
    """
    if len(landmarks) != 21:
        return None

    # A finger counts as "extended" when its tip is meaningfully above
    # (smaller y than) its own PIP joint — a simple, orientation-
    # sensitive but camera-facing-user heuristic that's good enough for
    # the five gestures this agent needs.
    extended = {
        name: landmarks[tip][1] < landmarks[_FINGER_PIPS[name]][1] - 0.02
        for name, tip in _FINGER_TIPS.items()
    }
    thumb_extended = landmarks[_THUMB_TIP][0] > landmarks[_THUMB_MCP][0] + 0.02 or \
        landmarks[_THUMB_TIP][0] < landmarks[_THUMB_MCP][0] - 0.02

    pinch_dist = _dist(landmarks[_THUMB_TIP], landmarks[_FINGER_TIPS["index"]])
    if pinch_dist < 0.04:
        return "pinch"

    if all(extended.values()) and thumb_extended:
        return "open_palm"

    if not any(extended.values()):
        # Closed fist vs. thumbs up both have four curled fingers;
        # thumbs up is distinguished by the thumb tip being clearly
        # above the wrist (pointing up) rather than tucked in.
        if landmarks[_THUMB_TIP][1] < landmarks[_WRIST][1] - 0.2:
            return "thumbs_up"
        return "closed_fist"

    return None


@dataclass
class _Debouncer:
    cooldown_s: float
    _last_fired: dict[str, float] = field(default_factory=dict)

    def should_fire(self, gesture: str, now: Optional[float] = None) -> bool:
        t = now if now is not None else time.time()
        last = self._last_fired.get(gesture)
        if last is not None and t - last < self.cooldown_s:
            return False
        self._last_fired[gesture] = t
        return True


class GestureController:
    """Owns the webcam loop. Only instantiate/run this when
    config.gestures.enabled is true — importing this module never
    touches the camera or MediaPipe on its own."""

    def __init__(
        self,
        on_action: Callable[[str], None],
        cooldown_s: float = 1.0,
        paused: Optional["threading.Event"] = None,
    ) -> None:
        self._on_action = on_action
        self._debouncer = _Debouncer(cooldown_s=cooldown_s)
        self._wrist_x_history: list[tuple[float, float]] = []  # (timestamp, x)
        self._swipe_window_s = 0.5
        self._swipe_min_delta = 0.25  # fraction of frame width
        self._paused = paused  # set externally (e.g. by the dashboard's "disable gestures" command)

    def _check_swipe(self, wrist_x: float) -> Optional[str]:
        now = time.time()
        self._wrist_x_history.append((now, wrist_x))
        self._wrist_x_history = [
            (t, x) for t, x in self._wrist_x_history if now - t <= self._swipe_window_s
        ]
        if len(self._wrist_x_history) < 2:
            return None
        start_x = self._wrist_x_history[0][1]
        delta = wrist_x - start_x
        if abs(delta) >= self._swipe_min_delta:
            self._wrist_x_history.clear()
            return "swipe_right" if delta > 0 else "swipe_left"
        return None

    def process_landmarks(self, landmarks: list[tuple[float, float]]) -> Optional[str]:
        """Feed one frame's 21 landmarks in; returns the debounced
        gesture name if one fired this frame, else None."""
        if self._paused is not None and self._paused.is_set():
            return None
        swipe = self._check_swipe(landmarks[_WRIST][0])
        gesture = swipe or classify_static_gesture(landmarks)
        if gesture is None:
            return None
        if not self._debouncer.should_fire(gesture):
            return None
        action = GESTURE_ACTIONS.get(gesture)
        if action:
            self._on_action(action)
        return gesture

    def run(self) -> None:
        """Blocking webcam loop. Not covered by unit tests (needs a real
        camera + MediaPipe runtime) — process_landmarks() above is
        exercised directly with synthetic data instead."""
        cfg = get_config().gestures
        if not cfg.enabled:
            log.info("Gestures disabled in config; not starting camera loop")
            return

        import cv2
        import mediapipe as mp

        hands = mp.solutions.hands.Hands(
            max_num_hands=1, min_detection_confidence=0.6, min_tracking_confidence=0.5
        )
        cap = cv2.VideoCapture(cfg.camera_index)
        log.info(f"Gesture loop started on camera {cfg.camera_index}")
        try:
            while True:
                ok, frame = cap.read()
                if not ok:
                    time.sleep(0.05)
                    continue
                rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
                result = hands.process(rgb)
                if result.multi_hand_landmarks:
                    lm = result.multi_hand_landmarks[0].landmark
                    points = [(p.x, p.y) for p in lm]
                    self.process_landmarks(points)
        finally:
            cap.release()
            hands.close()
