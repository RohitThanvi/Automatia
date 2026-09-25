"""
Windows UI Automation tree (spec section 6, hierarchy level 1).

This is the PRIMARY way the agent should find and interact with UI
elements from Phase 2 onward — it reads the OS accessibility tree
directly (via pywinauto's UIA backend), so it gets exact element
bounds, control types, and enabled/visible state without ever taking
a screenshot. OCR (vision/screen.py) and the vision model (Phase 5)
are fallbacks for the — increasingly rare — elements that don't
expose themselves to UIA (some custom-drawn/game-engine UIs).

Design note: pywinauto/UIA only exists on Windows. Every function
here degrades to a clear {"ok": False, "error": ...} on other
platforms rather than raising, so the rest of the codebase (and its
tests) stay importable cross-platform.
"""

from __future__ import annotations

import platform
from dataclasses import dataclass
from typing import Optional

from core.logging_setup import get_logger

log = get_logger()
IS_WINDOWS = platform.system() == "Windows"

_MAX_DEPTH = 6            # how deep to walk the tree before giving up
_MAX_NODES_SCANNED = 4000  # hard cap so a huge window (e.g. a browser) can't hang the agent


@dataclass
class UiElement:
    name: str
    control_type: str
    x: int
    y: int
    width: int
    height: int
    enabled: bool
    automation_id: str = ""

    @property
    def center(self) -> tuple[int, int]:
        return (self.x + self.width // 2, self.y + self.height // 2)


def _require_windows() -> Optional[dict]:
    if not IS_WINDOWS:
        return {"ok": False, "error": "UI Automation requires Windows (pywinauto)"}
    return None


def _desktop():
    from pywinauto import Desktop

    return Desktop(backend="uia")


def get_foreground_window_info() -> dict:
    """Used by the executor's verify step to confirm e.g. 'PowerPoint is
    actually the active window' without a screenshot."""
    err = _require_windows()
    if err:
        return err
    try:
        win = _desktop().active_window()
        rect = win.rectangle()
        return {
            "ok": True,
            "title": win.window_text(),
            "control_type": win.element_info.control_type,
            "rect": {"left": rect.left, "top": rect.top, "right": rect.right, "bottom": rect.bottom},
        }
    except Exception as e:
        return {"ok": False, "error": str(e)}


def _walk(element, depth: int, budget: list[int]) -> list[UiElement]:
    """Depth- and node-budget-limited walk of the UIA tree. Returns only
    elements that are visible, enabled-or-not (callers filter), and have
    either a name or an automation id — nameless containers are skipped
    since they're never what a spoken command refers to."""
    found: list[UiElement] = []
    if depth > _MAX_DEPTH or budget[0] <= 0:
        return found

    try:
        children = element.children()
    except Exception:
        return found

    for child in children:
        budget[0] -= 1
        if budget[0] <= 0:
            break
        try:
            info = child.element_info
            name = (info.name or "").strip()
            auto_id = (getattr(info, "automation_id", "") or "").strip()
            if name or auto_id:
                rect = info.rectangle
                found.append(
                    UiElement(
                        name=name,
                        control_type=info.control_type or "",
                        x=rect.left,
                        y=rect.top,
                        width=max(rect.right - rect.left, 0),
                        height=max(rect.bottom - rect.top, 0),
                        enabled=child.is_enabled() if hasattr(child, "is_enabled") else True,
                        automation_id=auto_id,
                    )
                )
        except Exception:
            pass  # a single unreadable node shouldn't abort the whole walk

        found.extend(_walk(child, depth + 1, budget))

    return found


def find_element_uia(text: str, window_title_contains: Optional[str] = None) -> dict:
    """Search the active window's (or a named window's) UIA tree for an
    element whose visible name contains `text` (case-insensitive).
    This is tried BEFORE OCR by vision.screen.find_ui_element."""
    err = _require_windows()
    if err:
        return err

    try:
        desktop = _desktop()
        window = None
        if window_title_contains:
            matches = desktop.windows(title_re=f".*{window_title_contains}.*")
            window = matches[0] if matches else None
        if window is None:
            window = desktop.active_window()

        budget = [_MAX_NODES_SCANNED]
        elements = _walk(window, depth=0, budget=budget)
    except Exception as e:
        return {"ok": False, "error": f"UIA tree walk failed: {e}"}

    needle = text.strip().lower()
    candidates = [e for e in elements if needle in e.name.lower() and e.enabled]
    if not candidates:
        # Fall back to disabled matches only to report *why* a click would fail,
        # never to click them.
        disabled = [e for e in elements if needle in e.name.lower()]
        if disabled:
            return {"ok": False, "error": f"Element '{text}' found but disabled: {disabled[0].name}"}
        return {"ok": False, "error": f"No UIA element matched '{text}'"}

    best = min(candidates, key=lambda e: len(e.name))  # prefer the most specific/shortest match
    cx, cy = best.center
    return {
        "ok": True,
        "text": best.name,
        "control_type": best.control_type,
        "x": cx,
        "y": cy,
        "automation_id": best.automation_id,
        "source": "uia",
    }


def list_interactive_elements(window_title_contains: Optional[str] = None, limit: int = 50) -> dict:
    """Diagnostic tool: dump the named, enabled elements the agent can
    currently see, useful when a spoken command's target text doesn't
    match what's on screen."""
    err = _require_windows()
    if err:
        return err
    try:
        desktop = _desktop()
        window = None
        if window_title_contains:
            matches = desktop.windows(title_re=f".*{window_title_contains}.*")
            window = matches[0] if matches else None
        if window is None:
            window = desktop.active_window()
        budget = [_MAX_NODES_SCANNED]
        elements = _walk(window, depth=0, budget=budget)
    except Exception as e:
        return {"ok": False, "error": str(e)}

    enabled = [e for e in elements if e.enabled][:limit]
    return {
        "ok": True,
        "count": len(enabled),
        "elements": [{"name": e.name, "type": e.control_type, "x": e.x, "y": e.y} for e in enabled],
    }
