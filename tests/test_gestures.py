import time

import pytest

from vision.gestures import GestureController, classify_static_gesture, _Debouncer


def _make_landmarks(finger_extended: dict[str, bool], thumb_up: bool = False) -> list[tuple[float, float]]:
    """Build a synthetic 21-point landmark set. y=0 is top of frame
    (MediaPipe convention), so 'extended' fingers have a smaller y
    (higher up) than their curled counterparts."""
    lm = [(0.5, 0.5)] * 21
    wrist_y = 0.9
    lm[0] = (0.5, wrist_y)  # wrist

    tips = {"index": 8, "middle": 12, "ring": 16, "pinky": 20}
    pips = {"index": 6, "middle": 10, "ring": 14, "pinky": 18}
    for name in tips:
        pip_y = 0.6
        lm[pips[name]] = (0.5, pip_y)
        lm[tips[name]] = (0.5, pip_y - 0.15) if finger_extended[name] else (0.5, pip_y + 0.05)

    # thumb: MCP at (0.45, 0.6); tip either far to the side (extended,
    # not near index tip) or tucked near the palm.
    lm[2] = (0.45, 0.6)  # thumb MCP
    if thumb_up:
        lm[4] = (0.5, wrist_y - 0.3)  # thumb tip well above wrist
    else:
        lm[4] = (0.55, 0.6)  # thumb tip extended sideways, not pinching

    return lm


def test_open_palm():
    lm = _make_landmarks({"index": True, "middle": True, "ring": True, "pinky": True})
    assert classify_static_gesture(lm) == "open_palm"


def test_closed_fist():
    lm = _make_landmarks({"index": False, "middle": False, "ring": False, "pinky": False}, thumb_up=False)
    lm[4] = (0.46, 0.85)  # thumb tucked in near the wrist, not raised
    assert classify_static_gesture(lm) == "closed_fist"


def test_thumbs_up():
    lm = _make_landmarks({"index": False, "middle": False, "ring": False, "pinky": False}, thumb_up=True)
    lm[4] = (0.5, 0.4)  # thumb tip well clear of the wrist (0.9), unambiguously "up"
    assert classify_static_gesture(lm) == "thumbs_up"


def test_pinch():
    lm = _make_landmarks({"index": True, "middle": False, "ring": False, "pinky": False})
    # Bring thumb tip right next to index tip.
    lm[4] = lm[8][0] + 0.01, lm[8][1] + 0.01
    assert classify_static_gesture(lm) == "pinch"


def test_wrong_landmark_count_returns_none():
    assert classify_static_gesture([(0.0, 0.0)] * 5) is None


def test_debouncer_suppresses_rapid_repeats():
    d = _Debouncer(cooldown_s=1.0)
    assert d.should_fire("open_palm", now=0.0) is True
    assert d.should_fire("open_palm", now=0.3) is False  # within cooldown
    assert d.should_fire("open_palm", now=1.1) is True  # cooldown elapsed


def test_debouncer_tracks_gestures_independently():
    d = _Debouncer(cooldown_s=1.0)
    assert d.should_fire("open_palm", now=0.0) is True
    assert d.should_fire("pinch", now=0.1) is True  # different gesture, no shared cooldown


def test_swipe_right_detected_and_fires_action():
    actions = []
    controller = GestureController(on_action=actions.append, cooldown_s=0.1)

    # First frame: an ambiguous, non-static-gesture hand pose (one
    # finger extended, three curled) so only the swipe path can fire —
    # isolates swipe detection from static gesture classification.
    lm = _make_landmarks({"index": True, "middle": False, "ring": False, "pinky": False})
    lm[4] = (0.9, 0.9)  # thumb far from index tip, so it can't register as a pinch either
    lm[0] = (0.1, 0.9)  # wrist starts at left
    first = controller.process_landmarks(lm)
    assert first is None

    lm[0] = (0.5, 0.9)  # wrist moves right by 0.4 (> swipe threshold)
    gesture = controller.process_landmarks(lm)

    assert gesture == "swipe_right"
    assert actions == ["next"]


def test_gesture_action_mapping_covers_all_gestures():
    from vision.gestures import GESTURE_ACTIONS

    expected = {"open_palm", "pinch", "thumbs_up", "closed_fist", "swipe_left", "swipe_right"}
    assert set(GESTURE_ACTIONS.keys()) == expected
