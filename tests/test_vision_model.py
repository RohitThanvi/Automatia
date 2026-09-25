from unittest.mock import MagicMock, patch

import pytest


def test_disabled_in_config_returns_clear_error(monkeypatch):
    from core.config import reload_config

    cfg = reload_config()
    cfg.vision.enabled = False
    from vision.vision_model import locate_element_with_vision

    result = locate_element_with_vision("Save button")
    assert result["ok"] is False
    assert "disabled" in result["error"].lower()
    cfg.vision.enabled = True
    reload_config()


def test_extract_json_from_clean_response():
    from vision.vision_model import _extract_json

    assert _extract_json('{"found": true, "x": 100, "y": 200}') == {"found": True, "x": 100, "y": 200}


def test_extract_json_from_response_with_surrounding_text():
    from vision.vision_model import _extract_json

    text = 'Sure, here is the location:\n{"found": true, "x": 50, "y": 60}\nHope that helps!'
    assert _extract_json(text) == {"found": True, "x": 50, "y": 60}


def test_extract_json_returns_none_for_garbage():
    from vision.vision_model import _extract_json

    assert _extract_json("I cannot find that element.") is None


def test_locate_element_success(monkeypatch):
    from core.config import reload_config

    reload_config()

    monkeypatch.setattr(
        "vision.vision_model._screenshot_b64", lambda: ("fakebase64", 1920, 1080)
    )

    fake_client = MagicMock()
    fake_client.chat.return_value = {
        "message": {"content": '{"found": true, "x": 400, "y": 300}'}
    }
    with patch("ollama.Client", return_value=fake_client):
        from vision.vision_model import locate_element_with_vision

        result = locate_element_with_vision("Submit button")

    assert result["ok"] is True
    assert result["x"] == 400
    assert result["y"] == 300
    assert result["source"] == "vision"


def test_locate_element_not_found(monkeypatch):
    monkeypatch.setattr(
        "vision.vision_model._screenshot_b64", lambda: ("fakebase64", 1920, 1080)
    )
    fake_client = MagicMock()
    fake_client.chat.return_value = {"message": {"content": '{"found": false}'}}
    with patch("ollama.Client", return_value=fake_client):
        from vision.vision_model import locate_element_with_vision

        result = locate_element_with_vision("Nonexistent Widget")

    assert result["ok"] is False


def test_locate_element_handles_request_failure(monkeypatch):
    monkeypatch.setattr(
        "vision.vision_model._screenshot_b64", lambda: ("fakebase64", 1920, 1080)
    )
    fake_client = MagicMock()
    fake_client.chat.side_effect = Exception("connection refused")
    with patch("ollama.Client", return_value=fake_client):
        from vision.vision_model import locate_element_with_vision

        result = locate_element_with_vision("Anything")

    assert result["ok"] is False
    assert "failed" in result["error"].lower()
