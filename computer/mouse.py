"""
Mouse tools (spec section 5).

These use raw coordinates only as the documented last-resort fallback
(spec section 5's UI-interaction hierarchy). Phase 2 adds
find_ui_element() via the accessibility tree so the planner can pass
element references instead of x/y most of the time.
"""

from __future__ import annotations

import pyautogui

from core.logging_setup import get_logger
from core.tool_registry import registry

log = get_logger()

pyautogui.FAILSAFE = True  # move mouse to a screen corner to abort — keep this on
pyautogui.PAUSE = 0.05


@registry.register(
    "move_mouse",
    "Move the mouse cursor to absolute screen coordinates.",
    {"x": {"type": "integer"}, "y": {"type": "integer"}},
    required=["x", "y"],
)
def move_mouse(x: int, y: int) -> dict:
    pyautogui.moveTo(x, y, duration=0.15)
    return {"ok": True, "x": x, "y": y}


@registry.register(
    "click_element",
    "Left-click at absolute screen coordinates.",
    {"x": {"type": "integer"}, "y": {"type": "integer"}},
    required=["x", "y"],
)
def click_element(x: int, y: int) -> dict:
    pyautogui.click(x, y)
    log.info(f"Clicked at ({x}, {y})")
    return {"ok": True, "x": x, "y": y}


@registry.register(
    "double_click_element",
    "Double-click at absolute screen coordinates.",
    {"x": {"type": "integer"}, "y": {"type": "integer"}},
    required=["x", "y"],
)
def double_click_element(x: int, y: int) -> dict:
    pyautogui.doubleClick(x, y)
    return {"ok": True, "x": x, "y": y}


@registry.register(
    "right_click_element",
    "Right-click at absolute screen coordinates.",
    {"x": {"type": "integer"}, "y": {"type": "integer"}},
    required=["x", "y"],
)
def right_click_element(x: int, y: int) -> dict:
    pyautogui.rightClick(x, y)
    return {"ok": True, "x": x, "y": y}


@registry.register(
    "scroll",
    "Scroll the mouse wheel. Positive amount scrolls up, negative scrolls down.",
    {"amount": {"type": "integer", "description": "Scroll amount/clicks, e.g. 5 or -5."}},
    required=["amount"],
)
def scroll(amount: int) -> dict:
    pyautogui.scroll(amount)
    return {"ok": True, "amount": amount}


@registry.register(
    "drag",
    "Click-and-drag from one point to another.",
    {
        "from_x": {"type": "integer"}, "from_y": {"type": "integer"},
        "to_x": {"type": "integer"}, "to_y": {"type": "integer"},
    },
    required=["from_x", "from_y", "to_x", "to_y"],
)
def drag(from_x: int, from_y: int, to_x: int, to_y: int) -> dict:
    pyautogui.moveTo(from_x, from_y, duration=0.1)
    pyautogui.dragTo(to_x, to_y, duration=0.3, button="left")
    return {"ok": True, "from": [from_x, from_y], "to": [to_x, to_y]}
