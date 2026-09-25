"""
Browser automation (spec section 12), Playwright bridge.

Earlier versions of this module used `webbrowser.open()`, which can
launch pages but has no way to enumerate, switch, or close tabs — it
fires an OS-level "open this URL" request and loses all control the
instant the browser process takes over. This version drives a real,
persistent Chromium profile via Playwright, which is what
switch_browser_tab/close_browser_tab/read_page require to actually
work (spec section 12: "Switch tabs", "Close tabs", "Read page").

Persistent context (not an ephemeral incognito browser) so the user's
logins/cookies carry over between agent runs — you shouldn't have to
re-log into ChatGPT every time the agent restarts.

Setup: `playwright install chromium` once, after `pip install -r
requirements.txt` (see README).
"""

from __future__ import annotations

import atexit
import threading
from typing import Optional
from urllib.parse import quote_plus

from core.config import get_config
from core.logging_setup import get_logger
from core.tool_registry import registry

log = get_logger()

_lock = threading.Lock()
_playwright = None
_context = None


def _profile_dir() -> str:
    d = get_config().resolved_workspace_dir() / ".browser_profile"
    d.mkdir(parents=True, exist_ok=True)
    return str(d)


def _ensure_context():
    """Lazily launch a single persistent Chromium context, reused for
    the lifetime of the process. Not created at import time — most
    tasks never touch the browser, and Playwright's browser download
    shouldn't block agent startup."""
    global _playwright, _context
    with _lock:
        if _context is not None:
            return _context
        from playwright.sync_api import sync_playwright

        _playwright = sync_playwright().start()
        _context = _playwright.chromium.launch_persistent_context(
            _profile_dir(),
            headless=False,
            viewport={"width": 1280, "height": 800},
        )
        atexit.register(_shutdown)
        log.info("Launched persistent Chromium context")
        return _context


def _shutdown() -> None:
    global _playwright, _context
    try:
        if _context is not None:
            _context.close()
        if _playwright is not None:
            _playwright.stop()
    except Exception as e:
        log.warning(f"Error during browser shutdown: {e}")


def _active_page():
    ctx = _ensure_context()
    pages = ctx.pages
    if not pages:
        return ctx.new_page()
    return pages[-1]


def _find_page(title_contains: str):
    ctx = _ensure_context()
    needle = title_contains.strip().lower()
    for page in ctx.pages:
        try:
            if needle in page.title().lower() or needle in page.url.lower():
                return page
        except Exception:
            continue
    return None


@registry.register(
    "open_url",
    "Open a URL in a new browser tab.",
    {"url": {"type": "string"}},
    required=["url"],
)
def open_url(url: str) -> dict:
    if not url.startswith(("http://", "https://")):
        url = "https://" + url
    ctx = _ensure_context()
    page = ctx.new_page()
    page.goto(url, wait_until="domcontentloaded")
    log.info(f"Opened URL: {url}")
    return {"ok": True, "url": url, "title": page.title()}


@registry.register(
    "browser_search",
    "Open a web search for the given query in a new browser tab.",
    {"query": {"type": "string"}},
    required=["query"],
)
def browser_search(query: str) -> dict:
    url = f"https://www.google.com/search?q={quote_plus(query)}"
    return open_url(url)


@registry.register(
    "browser_navigate",
    "Navigate the current (most recently active) browser tab to a URL.",
    {"url": {"type": "string"}},
    required=["url"],
)
def browser_navigate(url: str) -> dict:
    if not url.startswith(("http://", "https://")):
        url = "https://" + url
    page = _active_page()
    page.goto(url, wait_until="domcontentloaded")
    log.info(f"Navigated current tab to: {url}")
    return {"ok": True, "url": url, "title": page.title()}


@registry.register(
    "list_browser_tabs",
    "List all currently open browser tabs with their titles and URLs.",
    {},
    required=[],
)
def list_browser_tabs() -> dict:
    ctx = _ensure_context()
    tabs = [{"title": p.title(), "url": p.url} for p in ctx.pages]
    return {"ok": True, "tabs": tabs}


@registry.register(
    "switch_browser_tab",
    "Bring a browser tab matching a title/URL substring to the front.",
    {"title_contains": {"type": "string"}},
    required=["title_contains"],
)
def switch_browser_tab(title_contains: str) -> dict:
    page = _find_page(title_contains)
    if page is None:
        return {"ok": False, "error": f"No open tab matches '{title_contains}'"}
    page.bring_to_front()
    return {"ok": True, "title": page.title(), "url": page.url}


@registry.register(
    "close_browser_tab",
    "Close a browser tab matching a title/URL substring.",
    {"title_contains": {"type": "string"}},
    required=["title_contains"],
)
def close_browser_tab(title_contains: str) -> dict:
    page = _find_page(title_contains)
    if page is None:
        return {"ok": False, "error": f"No open tab matches '{title_contains}'"}
    title = page.title()
    page.close()
    return {"ok": True, "closed": title}


@registry.register(
    "read_page",
    "Read the visible text content of a browser tab (defaults to the current tab).",
    {"title_contains": {"type": "string", "description": "Optional: read a specific tab instead of the current one."}},
    required=[],
)
def read_page(title_contains: Optional[str] = None) -> dict:
    page = _find_page(title_contains) if title_contains else _active_page()
    if page is None:
        return {"ok": False, "error": f"No open tab matches '{title_contains}'"}
    try:
        text = page.inner_text("body")
    except Exception as e:
        return {"ok": False, "error": f"Could not read page: {e}"}
    return {"ok": True, "title": page.title(), "url": page.url, "text": text[:8000]}


def get_or_open_page(url_contains: str, fallback_url: str):
    """Non-tool helper used by apps/chatgpt.py: return the tab matching
    url_contains, opening fallback_url in a new tab if none is open yet."""
    page = _find_page(url_contains)
    if page is not None:
        page.bring_to_front()
        return page
    ctx = _ensure_context()
    page = ctx.new_page()
    page.goto(fallback_url, wait_until="domcontentloaded")
    return page
