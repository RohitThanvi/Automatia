"""
These tests only verify the platform-guard behavior (the part that's
safe and meaningful to test off Windows in CI). The actual UIA tree
walk can only be exercised on a real Windows desktop session.
"""

from unittest.mock import patch

from computer.accessibility import find_element_uia, get_foreground_window_info, list_interactive_elements


def test_find_element_uia_degrades_off_windows():
    with patch("computer.accessibility.IS_WINDOWS", False):
        result = find_element_uia("Save")
        assert result["ok"] is False
        assert "windows" in result["error"].lower()


def test_get_foreground_window_info_degrades_off_windows():
    with patch("computer.accessibility.IS_WINDOWS", False):
        result = get_foreground_window_info()
        assert result["ok"] is False


def test_list_interactive_elements_degrades_off_windows():
    with patch("computer.accessibility.IS_WINDOWS", False):
        result = list_interactive_elements()
        assert result["ok"] is False


def test_ui_element_center_property():
    from computer.accessibility import UiElement

    el = UiElement(name="Save", control_type="Button", x=10, y=20, width=100, height=40, enabled=True)
    assert el.center == (60, 40)
