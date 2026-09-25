"""
ChatGPT integration (spec section 14).

Uses normal browser automation against chatgpt.com through the same
persistent Playwright context as browser/browser.py — no undocumented
API, exactly as the spec requires ("Use normal browser/UI automation
unless an official API integration is explicitly configured").

Selectors are the fragile part of any web-UI-automation module: ChatGPT's
DOM changes over time, so `_INPUT_SELECTOR`/`_RESPONSE_SELECTOR` are
isolated at the top of the file as the first thing to fix if this stops
working, rather than buried in logic.
"""

from __future__ import annotations

from core.logging_setup import get_logger
from core.tool_registry import registry

log = get_logger()

_CHATGPT_URL = "https://chatgpt.com"
_INPUT_SELECTOR = "#prompt-textarea"
_RESPONSE_SELECTOR = '[data-message-author-role="assistant"]'
_SEND_TIMEOUT_MS = 60_000


def _get_page():
    from browser.browser import get_or_open_page

    return get_or_open_page("chatgpt.com", _CHATGPT_URL)


@registry.register(
    "open_chatgpt",
    "Open (or focus) the ChatGPT web app in the browser.",
    {},
    required=[],
)
def open_chatgpt() -> dict:
    page = _get_page()
    return {"ok": True, "url": page.url, "title": page.title()}


@registry.register(
    "send_chatgpt_prompt",
    "Type a prompt into ChatGPT's input box and send it. Opens ChatGPT first if it isn't already open.",
    {"text": {"type": "string", "description": "The prompt text to send."}},
    required=["text"],
)
def send_chatgpt_prompt(text: str) -> dict:
    page = _get_page()
    try:
        page.wait_for_selector(_INPUT_SELECTOR, timeout=15_000)
        page.click(_INPUT_SELECTOR)
        page.fill(_INPUT_SELECTOR, text)
        page.keyboard.press("Enter")
    except Exception as e:
        return {
            "ok": False,
            "error": (
                f"Could not send prompt — ChatGPT's page layout may have changed "
                f"(selector '{_INPUT_SELECTOR}' not found/usable): {e}"
            ),
        }
    log.info(f"Sent ChatGPT prompt ({len(text)} chars)")
    return {"ok": True, "sent": len(text)}


@registry.register(
    "read_chatgpt_response",
    "Read ChatGPT's most recent response text. Waits briefly for the response to finish streaming.",
    {},
    required=[],
)
def read_chatgpt_response() -> dict:
    page = _get_page()
    try:
        page.wait_for_selector(_RESPONSE_SELECTOR, timeout=_SEND_TIMEOUT_MS)
        # Give streaming a moment to settle rather than reading a partial answer.
        page.wait_for_timeout(1500)
        responses = page.query_selector_all(_RESPONSE_SELECTOR)
        if not responses:
            return {"ok": False, "error": "No ChatGPT response found on page"}
        text = responses[-1].inner_text()
    except Exception as e:
        return {"ok": False, "error": f"Could not read response: {e}"}
    return {"ok": True, "text": text}
