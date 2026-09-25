"""
Screen understanding — capture + OCR (spec section 6).

This module implements levels 3 ("OCR") of the four-level UI
interaction hierarchy for Phase 1. Level 1 (UI Automation tree) and
level 4 (vision-model fallback) are Phase 2/5 — find_ui_element()
below already has the right call signature so the planner's calls to
it don't change when those levels are added; it will simply try them
in order and fall through to OCR only when they fail.

Screenshots are never uploaded anywhere (spec section 24) — they are
processed in-memory and only written to disk when explicitly requested
via take_screenshot's save_path.
"""

from __future__ import annotations

import io
import time
from pathlib import Path
from typing import Optional

from core.config import get_config
from core.logging_setup import get_logger
from core.tool_registry import registry

log = get_logger()


def _grab():
    from PIL import ImageGrab

    return ImageGrab.grab()


@registry.register(
    "take_screenshot",
    "Capture the current screen. Optionally save it to a file.",
    {"save_path": {"type": "string", "description": "Optional file path to save the screenshot as PNG."}},
    required=[],
)
def take_screenshot(save_path: Optional[str] = None) -> dict:
    img = _grab()
    if save_path:
        target = Path(save_path).expanduser()
        if not target.is_absolute():
            target = get_config().resolved_workspace_dir() / target
        target.parent.mkdir(parents=True, exist_ok=True)
        img.save(target)
        log.info(f"Saved screenshot to {target}")
        return {"ok": True, "path": str(target), "size": img.size}
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return {"ok": True, "size": img.size, "bytes": len(buf.getvalue())}


def _ocr_words() -> list[dict]:
    """Return [{text, x, y, w, h}] for every OCR-detected word on screen."""
    try:
        import pytesseract
    except ImportError:
        log.error("pytesseract not installed — OCR fallback unavailable")
        return []

    img = _grab()
    data = pytesseract.image_to_data(img, output_type=pytesseract.Output.DICT)
    words = []
    for i, text in enumerate(data["text"]):
        text = text.strip()
        if not text:
            continue
        words.append(
            {
                "text": text,
                "x": data["left"][i],
                "y": data["top"][i],
                "w": data["width"][i],
                "h": data["height"][i],
            }
        )
    return words


@registry.register(
    "read_screen",
    "Read all visible text on screen via OCR. Use to understand what's currently displayed.",
    {},
    required=[],
)
def read_screen() -> dict:
    words = _ocr_words()
    full_text = " ".join(w["text"] for w in words)
    return {"ok": True, "text": full_text, "word_count": len(words)}


@registry.register(
    "find_ui_element",
    "Locate an on-screen element (button/label/field) by its visible text/name and return its click coordinates.",
    {
        "text": {"type": "string", "description": "Visible text or accessible name to search for (case-insensitive substring match)."},
        "window_title_contains": {"type": "string", "description": "Optional: restrict the search to a specific window by its title."},
    },
    required=["text"],
)
def find_ui_element(text: str, window_title_contains: Optional[str] = None) -> dict:
    # Hierarchy per spec section 5/6:
    #   1. UI Automation tree   (Phase 2 — computer/accessibility.py)
    #   2. app-specific API     (Phase 2+, per-app modules)
    #   3. OCR                  (here, this file)
    #   4. vision model         (Phase 5)
    #   5. raw coordinates      (last resort, not attempted here)
    from computer.accessibility import find_element_uia, IS_WINDOWS

    if IS_WINDOWS:
        uia_result = find_element_uia(text, window_title_contains=window_title_contains)
        if uia_result.get("ok"):
            log.info(f"find_ui_element: resolved '{text}' via UIA")
            return uia_result
        log.info(f"find_ui_element: UIA miss for '{text}' ({uia_result.get('error')}), falling back to OCR")

    needle = text.strip().lower()
    words = _ocr_words()
    matches = [w for w in words if needle in w["text"].lower()]
    if matches:
        w = matches[0]
        center_x = w["x"] + w["w"] // 2
        center_y = w["y"] + w["h"] // 2
        return {"ok": True, "text": w["text"], "x": center_x, "y": center_y, "source": "ocr"}

    log.info(f"find_ui_element: OCR miss for '{text}', falling back to vision model")
    from vision.vision_model import locate_element_with_vision

    vision_result = locate_element_with_vision(text)
    if vision_result.get("ok"):
        return vision_result

    return {
        "ok": False,
        "error": (
            f"No visible text matched '{text}' via UI Automation, OCR, or the vision model. "
            f"({vision_result.get('error', 'vision fallback also failed')})"
        ),
    }


@registry.register(
    "list_ui_elements",
    "List the named, interactable elements currently visible (via UI Automation), useful when a target's exact text is unknown.",
    {"window_title_contains": {"type": "string", "description": "Optional: restrict to a specific window by title."}},
    required=[],
)
def list_ui_elements(window_title_contains: Optional[str] = None) -> dict:
    from computer.accessibility import list_interactive_elements

    return list_interactive_elements(window_title_contains=window_title_contains)
