"""
Vision-model fallback (spec section 6, hierarchy level 4).

Used ONLY when both UI Automation (computer/accessibility.py) and OCR
(vision/screen.py's own word-matching) fail to find an element —
per spec section 6: "Do not continuously send screenshots to the
vision model unnecessarily." This module is never polled on a loop;
it's called at most once per find_ui_element miss.

Gemma 3's pixel-coordinate accuracy is good but not exact, so callers
should treat the returned point as "click roughly here" — for
anything where a few pixels of error matters (e.g. a tiny icon among
many), UI Automation or OCR should be preferred, which is exactly why
this sits last in the hierarchy rather than first.
"""

from __future__ import annotations

import base64
import io
import json
import re
from typing import Optional

from core.config import get_config
from core.logging_setup import get_logger

log = get_logger()

_PROMPT_TEMPLATE = """You are looking at a screenshot of a Windows desktop, {width}x{height} pixels.
Find the UI element that best matches this description: "{text}"

Respond with ONLY a JSON object, no other text, in exactly this form:
{{"found": true, "x": <pixel x of the element's center>, "y": <pixel y of the element's center>}}
or, if nothing on screen matches:
{{"found": false}}
"""


def _screenshot_b64() -> tuple[str, int, int]:
    from PIL import ImageGrab

    img = ImageGrab.grab()
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return base64.b64encode(buf.getvalue()).decode("utf-8"), img.width, img.height


def _extract_json(text: str) -> Optional[dict]:
    match = re.search(r"\{.*\}", text, re.DOTALL)
    if not match:
        return None
    try:
        return json.loads(match.group(0))
    except json.JSONDecodeError:
        return None


def locate_element_with_vision(text: str) -> dict:
    cfg = get_config().vision
    if not cfg.enabled:
        return {"ok": False, "error": "Vision fallback is disabled in config.yaml (vision.enabled: false)"}

    import ollama

    llm_cfg = get_config().llm
    image_b64, width, height = _screenshot_b64()
    prompt = _PROMPT_TEMPLATE.format(width=width, height=height, text=text)

    log.info(f"Vision fallback: asking {cfg.model} to locate '{text}'")
    try:
        client = ollama.Client(host=llm_cfg.host, timeout=llm_cfg.request_timeout_s)
        response = client.chat(
            model=cfg.model,
            messages=[{"role": "user", "content": prompt, "images": [image_b64]}],
            options={"temperature": 0.0},
        )
    except Exception as e:
        return {"ok": False, "error": f"Vision model request failed: {e}"}

    content = response.get("message", {}).get("content", "")
    parsed = _extract_json(content)
    if parsed is None:
        return {"ok": False, "error": f"Vision model returned unparseable output: {content[:200]!r}"}

    if not parsed.get("found"):
        return {"ok": False, "error": f"Vision model did not find an element matching '{text}'"}

    x, y = parsed.get("x"), parsed.get("y")
    if not isinstance(x, (int, float)) or not isinstance(y, (int, float)):
        return {"ok": False, "error": f"Vision model response missing valid coordinates: {parsed}"}

    return {"ok": True, "text": text, "x": int(x), "y": int(y), "source": "vision"}
