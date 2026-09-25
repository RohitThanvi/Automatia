from unittest.mock import MagicMock

import pytest


@pytest.fixture
def fake_page(monkeypatch):
    import apps.chatgpt as chatgpt_module

    page = MagicMock()
    page.url = "https://chatgpt.com"
    page.title.return_value = "ChatGPT"
    monkeypatch.setattr(chatgpt_module, "_get_page", lambda: page)
    return page


def test_open_chatgpt(fake_page):
    from apps.chatgpt import open_chatgpt

    result = open_chatgpt()
    assert result["ok"] is True
    assert result["url"] == "https://chatgpt.com"


def test_send_chatgpt_prompt_success(fake_page):
    from apps.chatgpt import send_chatgpt_prompt

    result = send_chatgpt_prompt("hello there")
    assert result["ok"] is True
    fake_page.fill.assert_called_once()
    fake_page.keyboard.press.assert_called_once_with("Enter")


def test_send_chatgpt_prompt_selector_failure_reports_clearly(fake_page):
    from apps.chatgpt import send_chatgpt_prompt

    fake_page.wait_for_selector.side_effect = Exception("timeout")
    result = send_chatgpt_prompt("hello")
    assert result["ok"] is False
    assert "layout may have changed" in result["error"]


def test_read_chatgpt_response(fake_page):
    from apps.chatgpt import read_chatgpt_response

    fake_response = MagicMock()
    fake_response.inner_text.return_value = "This is the answer."
    fake_page.query_selector_all.return_value = [fake_response]

    result = read_chatgpt_response()
    assert result["ok"] is True
    assert result["text"] == "This is the answer."


def test_read_chatgpt_response_no_messages(fake_page):
    from apps.chatgpt import read_chatgpt_response

    fake_page.query_selector_all.return_value = []
    result = read_chatgpt_response()
    assert result["ok"] is False
