from unittest.mock import MagicMock, patch

import pytest


def test_is_startup_enabled_false_when_no_shortcut(tmp_path, monkeypatch):
    import tray

    monkeypatch.setattr(tray, "_shortcut_path", lambda: tmp_path / "PC Agent Tray.lnk")
    assert tray.is_startup_enabled() is False


def test_set_startup_enabled_off_windows_is_noop(monkeypatch):
    import tray

    monkeypatch.setattr(tray, "IS_WINDOWS", False)
    # Must not raise even though nothing Windows-specific is available.
    tray.set_startup_enabled(True)


def test_set_startup_disabled_removes_existing_shortcut(tmp_path, monkeypatch):
    import tray

    shortcut = tmp_path / "PC Agent Tray.lnk"
    shortcut.write_text("fake shortcut")
    monkeypatch.setattr(tray, "_shortcut_path", lambda: shortcut)
    monkeypatch.setattr(tray, "IS_WINDOWS", True)

    tray.set_startup_enabled(False)
    assert not shortcut.exists()


def test_start_agent_does_not_launch_twice():
    import tray

    app = tray.TrayApp()
    fake_proc = MagicMock()
    fake_proc.poll.return_value = None  # still running
    app._agent_process = fake_proc

    with patch("subprocess.Popen") as popen:
        app.start_agent()
        popen.assert_not_called()


def test_start_agent_launches_when_not_running():
    import tray

    app = tray.TrayApp()
    with patch("subprocess.Popen") as popen:
        app.start_agent()
        popen.assert_called_once()


def test_stop_agent_terminates_running_process():
    import tray

    app = tray.TrayApp()
    fake_proc = MagicMock()
    fake_proc.poll.return_value = None
    fake_proc.wait.return_value = None
    app._agent_process = fake_proc

    app.stop_agent()
    fake_proc.terminate.assert_called_once()


def test_stop_agent_noop_when_nothing_running():
    import tray

    app = tray.TrayApp()
    # Should not raise even with no process ever started.
    app.stop_agent()


def test_exit_app_stops_agent_and_icon():
    import tray

    app = tray.TrayApp()
    fake_proc = MagicMock()
    fake_proc.poll.return_value = None
    app._agent_process = fake_proc
    fake_icon = MagicMock()

    app.exit_app(fake_icon)
    fake_proc.terminate.assert_called_once()
    fake_icon.stop.assert_called_once()
