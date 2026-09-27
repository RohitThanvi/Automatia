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

# The 21 MediaPipe Hands landmarks, connected as bones, for drawing the
# skeleton overlay ourselves. Kept independent of mp.solutions.drawing_utils
# (same "legacy solutions" surface that broke — see run()), so the preview
# window still works even on mediapipe builds that trim that helper.
_HAND_CONNECTIONS = [
    (0, 1), (1, 2), (2, 3), (3, 4),          # thumb
    (0, 5), (5, 6), (6, 7), (7, 8),          # index
    (5, 9), (9, 10), (10, 11), (11, 12),     # middle
    (9, 13), (13, 14), (14, 15), (15, 16),   # ring
    (13, 17), (17, 18), (18, 19), (19, 20),  # pinky
    (0, 17),                                  # palm base
]

# Cursor-tracking tuning. Index fingertip position only drives the OS
# cursor while the index finger is "extended" per get_extended_fingers —
# curl your fingers (fist/thumbs-up) to act as a clutch and freeze the
# cursor while you reposition your hand, same idea as lifting a mouse
# off the pad.
_CURSOR_SMOOTHING = 0.35  # EMA factor: higher = snappier, lower = smoother but laggier
_CURSOR_MARGIN = 0.12     # fraction trimmed off each camera-frame edge before mapping to
                          # the screen, so you don't have to reach into the frame's corners

# Thumb-tip-to-index-tip distance (normalized [0,1] frame units) below
# which a pinch registers. 0.04 (the original value) proved too tight
# for typical webcam distance/resolution in practice; 0.065 is more
# forgiving. If pinches still don't register, watch the "pinch dist"
# readout in the preview window and raise this further to match.
_PINCH_THRESHOLD = 0.065
_CLICK_COOLDOWN_S = 0.35  # deliberately shorter than the 1.0s shared with wake/stop/confirm


def _dist(a: tuple[float, float], b: tuple[float, float]) -> float:
    return ((a[0] - b[0]) ** 2 + (a[1] - b[1]) ** 2) ** 0.5


def get_extended_fingers(landmarks: list[tuple[float, float]]) -> dict[str, bool]:
    """A finger counts as "extended" when its tip is meaningfully above
    (smaller y than) its own PIP joint — shared by classify_static_gesture
    and by the cursor-tracking gate below (index extended = 'pointing',
    which drives the cursor; curled = clutch, cursor freezes in place)."""
    return {
        name: landmarks[tip][1] < landmarks[_FINGER_PIPS[name]][1] - 0.02
        for name, tip in _FINGER_TIPS.items()
    }


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

    extended = get_extended_fingers(landmarks)
    thumb_extended = landmarks[_THUMB_TIP][0] > landmarks[_THUMB_MCP][0] + 0.02 or \
        landmarks[_THUMB_TIP][0] < landmarks[_THUMB_MCP][0] - 0.02

    pinch_dist = _dist(landmarks[_THUMB_TIP], landmarks[_FINGER_TIPS["index"]])
    if pinch_dist < _PINCH_THRESHOLD:
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
        self._cursor_smoothed: Optional[tuple[float, float]] = None
        self._cursor_screen_pos: Optional[tuple[int, int]] = None
        self._click_debounce = _Debouncer(cooldown_s=_CLICK_COOLDOWN_S)

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
        # Static gestures (especially pinch) take precedence over swipe:
        # reaching toward something to pinch it often moves the wrist
        # enough to also look like a swipe, and a deliberate pinch should
        # never get silently swallowed by that incidental motion.
        gesture = classify_static_gesture(landmarks) or swipe
        if gesture is None:
            return None
        if not self._debouncer.should_fire(gesture):
            return None
        action = GESTURE_ACTIONS.get(gesture)
        if action:
            self._on_action(action)
        return gesture

    @staticmethod
    def _open_camera(cv2, camera_index: int):
        """cv2.VideoCapture's default backend on Windows (MSMF) is known
        to hang or stall with some webcam drivers — DirectShow is the
        documented workaround and is what was actually causing the
        preview window to freeze. Falls back to the default backend on
        non-Windows platforms or if DSHOW isn't available."""
        import sys

        if sys.platform == "win32" and hasattr(cv2, "CAP_DSHOW"):
            cap = cv2.VideoCapture(camera_index, cv2.CAP_DSHOW)
            if cap.isOpened():
                return cap
            cap.release()
        return cv2.VideoCapture(camera_index)

    @staticmethod
    def _map_to_screen(nx: float, ny: float, screen_w: int, screen_h: int) -> tuple[int, int]:
        """Map a normalized (0..1) camera-frame point to screen pixel
        coordinates, trimming _CURSOR_MARGIN off each edge first so the
        reachable area of the camera view maps to the full screen."""
        def scale(v: float) -> float:
            v = (v - _CURSOR_MARGIN) / (1 - 2 * _CURSOR_MARGIN)
            return min(max(v, 0.0), 1.0)

        return int(scale(nx) * screen_w), int(scale(ny) * screen_h)

    def _update_cursor(self, pyautogui, points: list[tuple[float, float]], screen_w: int, screen_h: int) -> None:
        ix, iy = points[_FINGER_TIPS["index"]]
        if self._cursor_smoothed is None:
            self._cursor_smoothed = (ix, iy)
        else:
            sx, sy = self._cursor_smoothed
            self._cursor_smoothed = (
                sx + _CURSOR_SMOOTHING * (ix - sx),
                sy + _CURSOR_SMOOTHING * (iy - sy),
            )
        screen_x, screen_y = self._map_to_screen(*self._cursor_smoothed, screen_w, screen_h)
        try:
            # _pause=False: skip pyautogui's global inter-call pause
            # (set to 0.05s elsewhere for discrete agent actions) — at
            # continuous per-frame tracking rates that pause would make
            # the cursor visibly stutter.
            pyautogui.moveTo(screen_x, screen_y, duration=0, _pause=False)
        except pyautogui.FailSafeException:
            log.warning("Cursor hit a screen corner (pyautogui failsafe) — tracking paused this frame")
            return
        self._cursor_screen_pos = (screen_x, screen_y)

    @staticmethod
    def _load_mediapipe_hands():
        """Import mediapipe and return the Hands class, tolerating builds
        where `mediapipe.solutions` isn't exposed on the top-level package
        (a real, observed breakage on some mediapipe/Python combinations —
        the fix is really to run `pip install mediapipe==0.10.14`, but we
        fail with a clear message instead of a bare AttributeError)."""
        import mediapipe as mp

        try:
            return mp.solutions.hands
        except AttributeError:
            pass
        try:
            from mediapipe.python.solutions import hands as mp_hands
            return mp_hands
        except ImportError as exc:
            raise RuntimeError(
                "This mediapipe install doesn't expose the legacy "
                "`solutions` API that gestures.py needs. Run:\n"
                "    pip uninstall mediapipe -y\n"
                "    pip install mediapipe==0.10.14\n"
                "then restart the app."
            ) from exc

    def run(self) -> None:
        """Blocking webcam loop. Not covered by unit tests (needs a real
        camera + MediaPipe runtime) — process_landmarks() above is
        exercised directly with synthetic data instead.

        When cfg.show_preview is true, also opens a debug window showing
        the live camera feed with the 21-point hand skeleton drawn on top
        and the most recently fired gesture/action printed in the corner,
        so you can see exactly what the recognizer is seeing."""
        cfg = get_config().gestures
        if not cfg.enabled:
            log.info("Gestures disabled in config; not starting camera loop")
            return

        import cv2

        try:
            mp_hands = self._load_mediapipe_hands()
        except RuntimeError as exc:
            log.error(str(exc))
            return

        hands = mp_hands.Hands(
            max_num_hands=1, min_detection_confidence=0.6, min_tracking_confidence=0.5
        )
        cap = self._open_camera(cv2, cfg.camera_index)
        if not cap.isOpened():
            log.error(
                f"Could not open camera index {cfg.camera_index}. Check "
                "config.yaml gestures.camera_index and that no other app "
                "(Teams/Zoom/browser) is holding the webcam."
            )
            hands.close()
            return

        window_name = "Automatia — Gesture View"
        last_label = "no hand"
        last_action_ts = 0.0
        pyautogui = None
        screen_w = screen_h = 0
        if cfg.cursor_control:
            import pyautogui as _pyautogui
            pyautogui = _pyautogui
            pyautogui.FAILSAFE = True  # move the real cursor into a screen corner to abort tracking
            screen_w, screen_h = pyautogui.size()
        log.info(f"Gesture loop started on camera {cfg.camera_index}")
        try:
            while True:
                ok, frame = cap.read()
                if not ok:
                    time.sleep(0.05)
                    continue

                frame = cv2.flip(frame, 1)  # mirror, feels natural on screen
                rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
                result = hands.process(rgb)

                gesture = None
                if result.multi_hand_landmarks:
                    lm = result.multi_hand_landmarks[0].landmark
                    points = [(p.x, p.y) for p in lm]
                    pointing = pyautogui is not None and get_extended_fingers(points)["index"]
                    if pointing:
                        self._update_cursor(pyautogui, points, screen_w, screen_h)

                    pinch_dist = _dist(points[_THUMB_TIP], points[_FINGER_TIPS["index"]])
                    gesture = self.process_landmarks(points)

                    # Checked against the raw distance + its own fast
                    # debounce, NOT the `gesture` value above — that one
                    # is rate-limited to 1/sec (shared with wake/stop/
                    # confirm) and can also get preempted by a swipe.
                    # Clicking should feel responsive on its own.
                    if (
                        pinch_dist < _PINCH_THRESHOLD
                        and pyautogui is not None
                        and self._cursor_screen_pos
                        and self._click_debounce.should_fire("click")
                    ):
                        try:
                            pyautogui.click(*self._cursor_screen_pos)
                            log.info(f"Gesture click at {self._cursor_screen_pos} (pinch dist {pinch_dist:.3f})")
                            last_label = f"CLICK @ {self._cursor_screen_pos}"
                            last_action_ts = time.time()
                        except Exception:
                            log.exception("Gesture click failed")

                    if cfg.show_preview:
                        self._draw_landmarks(frame, points, highlight_index=pointing)
                    if gesture and gesture != "pinch":
                        last_label = f"{gesture} -> {GESTURE_ACTIONS.get(gesture, '?')}"
                        last_action_ts = time.time()
                    elif pointing and self._cursor_screen_pos and (time.time() - last_action_ts) > 0.6:
                        last_label = f"pointing @ {self._cursor_screen_pos} | pinch dist {pinch_dist:.3f}"
                else:
                    self._cursor_smoothed = None  # avoid a jump when the hand re-enters frame
                    if cfg.show_preview:
                        last_label = "no hand"

                if cfg.show_preview:
                    self._draw_hud(frame, last_label, last_action_ts)
                    cv2.imshow(window_name, frame)
                    # 1ms poll so the window redraws every frame; 'q' or Esc
                    # closes just the preview window, the loop (and gesture
                    # detection) keeps running headless afterward.
                    key = cv2.waitKey(1) & 0xFF
                    if key in (ord("q"), 27):
                        cv2.destroyWindow(window_name)
                        cfg.show_preview = False
                    elif cv2.getWindowProperty(window_name, cv2.WND_PROP_VISIBLE) < 1:
                        # User closed the window via the titlebar X rather
                        # than q/Esc — calling imshow on a destroyed window
                        # on the next frame is what actually caused the
                        # "frozen" preview, so stop targeting it here.
                        cfg.show_preview = False
        finally:
            cap.release()
            hands.close()
            cv2.destroyAllWindows()

    @staticmethod
    def _draw_landmarks(frame, points: list[tuple[float, float]], highlight_index: bool = False) -> None:
        import cv2

        h, w = frame.shape[:2]
        px = [(int(x * w), int(y * h)) for x, y in points]
        for a, b in _HAND_CONNECTIONS:
            cv2.line(frame, px[a], px[b], (0, 220, 0), 2)
        for i, (x, y) in enumerate(px):
            color = (0, 140, 255) if i in _FINGER_TIPS.values() or i == _THUMB_TIP else (0, 220, 0)
            cv2.circle(frame, (x, y), 5, color, -1)
        if highlight_index:
            # Cursor is actively tracking this fingertip — draw a ring
            # around it so it's obvious at a glance vs. the clutch state.
            ix, iy = px[_FINGER_TIPS["index"]]
            cv2.circle(frame, (ix, iy), 14, (0, 255, 255), 2)

    @staticmethod
    def _draw_hud(frame, label: str, last_action_ts: float) -> None:
        import cv2

        highlight = (time.time() - last_action_ts) < 0.6  # flash briefly on fire
        color = (0, 255, 255) if highlight else (255, 255, 255)
        cv2.rectangle(frame, (0, 0), (frame.shape[1], 40), (30, 30, 30), -1)
        cv2.putText(
            frame, f"Gesture: {label}", (10, 27),
            cv2.FONT_HERSHEY_SIMPLEX, 0.7, color, 2, cv2.LINE_AA,
        )
        cv2.putText(
            frame, "q / Esc: close preview", (frame.shape[1] - 200, 27),
            cv2.FONT_HERSHEY_SIMPLEX, 0.5, (180, 180, 180), 1, cv2.LINE_AA,
        )
