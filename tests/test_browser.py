"""
These tests fake out Playwright's context/page objects entirely, so
they run without a real browser installed. They verify the bridge's
own logic (tab matching, URL normalization, error shapes) — not
Playwright itself.
"""

from unittest.mock import MagicMock

import pytest


class FakePage:
    def __init__(self, title: str, url: str):
        self._title = title
        self.url = url
        self.closed = False

    def title(self):
        return self._title

    def goto(self, url, wait_until=None):
        self.url = url

    def bring_to_front(self):
        pass

    def close(self):
        self.closed = True

    def inner_text(self, selector):
        return f"body text of {self._title}"


class FakeContext:
    def __init__(self, pages):
        self.pages = pages

    def new_page(self):
        p = FakePage("New Tab", "about:blank")
        self.pages.append(p)
        return p


@pytest.fixture
def fake_context(monkeypatch):
    import browser.browser as browser_module

    pages = [FakePage("GitHub", "https://github.com"), FakePage("ChatGPT", "https://chatgpt.com")]
    ctx = FakeContext(pages)
    monkeypatch.setattr(browser_module, "_ensure_context", lambda: ctx)
    return ctx


def test_open_url_creates_new_page(fake_context):
    from browser.browser import open_url

    result = open_url("example.com")
    assert result["ok"] is True
    assert result["url"] == "https://example.com"
    assert len(fake_context.pages) == 3


def test_open_url_preserves_explicit_scheme(fake_context):
    from browser.browser import open_url

    result = open_url("http://example.com")
    assert result["url"] == "http://example.com"


def test_list_browser_tabs(fake_context):
    from browser.browser import list_browser_tabs

    result = list_browser_tabs()
    assert result["ok"] is True
    assert len(result["tabs"]) == 2
    assert {"title": "GitHub", "url": "https://github.com"} in result["tabs"]


def test_switch_browser_tab_found(fake_context):
    from browser.browser import switch_browser_tab

    result = switch_browser_tab("github")
    assert result["ok"] is True
    assert result["title"] == "GitHub"


def test_switch_browser_tab_not_found(fake_context):
    from browser.browser import switch_browser_tab

    result = switch_browser_tab("nonexistent")
    assert result["ok"] is False


def test_close_browser_tab(fake_context):
    from browser.browser import close_browser_tab

    result = close_browser_tab("chatgpt")
    assert result["ok"] is True
    assert fake_context.pages[1].closed is True


def test_read_page_current_tab(fake_context, monkeypatch):
    import browser.browser as browser_module

    monkeypatch.setattr(browser_module, "_active_page", lambda: fake_context.pages[-1])
    from browser.browser import read_page

    result = read_page()
    assert result["ok"] is True
    assert "ChatGPT" in result["text"]
