"""Keyboard tools (spec section 5)."""

from __future__ import annotations

import pyautogui

from core.logging_setup import get_logger
from core.tool_registry import registry

log = get_logger()


@registry.register(
    "type_text",
    "Type text at the current cursor/focus position, as if typed on a keyboard.",
    {"text": {"type": "string"}, "interval": {"type": "number", "description": "Seconds between keystrokes."}},
    required=["text"],
)
def type_text(text: str, interval: float = 0.01) -> dict:
    pyautogui.write(text, interval=interval)
    log.info(f"Typed {len(text)} characters")
    return {"ok": True, "length": len(text)}


@registry.register(
    "press_key",
    "Press a single key (e.g. 'enter', 'esc', 'tab', 'f5').",
    {"key": {"type": "string"}},
    required=["key"],
)
def press_key(key: str) -> dict:
    pyautogui.press(key)
    return {"ok": True, "key": key}


@registry.register(
    "hotkey",
    "Press a key combination, e.g. keys=['ctrl','s'] for Ctrl+S.",
    {"keys": {"type": "array", "items": {"type": "string"}}},
    required=["keys"],
)
def hotkey(keys: list[str]) -> dict:
    pyautogui.hotkey(*keys)
    log.info(f"Pressed hotkey: {'+'.join(keys)}")
    return {"ok": True, "keys": keys}
