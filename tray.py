"""
System tray (spec section 20).

Runs as its own small process, separate from both `python main.py`
(the voice/agent loop) and `python -m dashboard.server` (the web UI).
It launches/stops the agent as a subprocess and opens the dashboard
in the browser — it does not import voice/vision/computer modules
itself, so the tray icon staying up doesn't depend on any of the
heavy ML stack being importable.

"Start with Windows" is implemented via a shortcut in the user's
Startup folder (shell:startup) rather than a registry Run key — this
is the standard, easily-reversible mechanism (the user can just
delete the shortcut) and doesn't require admin rights.
"""

from __future__ import annotations

import os
import platform
import subprocess
import sys
import webbrowser
from pathlib import Path
from typing import Optional

from core.config import get_config
from core.logging_setup import get_logger

log = get_logger()

PROJECT_ROOT = Path(__file__).resolve().parent
IS_WINDOWS = platform.system() == "Windows"


def _startup_folder() -> Path:
    return Path(os.environ.get("APPDATA", "")) / "Microsoft" / "Windows" / "Start Menu" / "Programs" / "Startup"


def _shortcut_path() -> Path:
    return _startup_folder() / "PC Agent Tray.lnk"


def is_startup_enabled() -> bool:
    return _shortcut_path().exists()


def set_startup_enabled(enabled: bool) -> None:
    """Create/remove a .lnk shortcut in the Startup folder that runs
    this file with the same Python interpreter and venv currently
    active. Uses PowerShell's WScript.Shell COM object — no extra
    dependency (pywin32) needed just for shortcut creation."""
    if not IS_WINDOWS:
        log.warning("set_startup_enabled is a no-op outside Windows")
        return

    shortcut = _shortcut_path()
    if not enabled:
        if shortcut.exists():
            shortcut.unlink()
            log.info("Removed startup shortcut")
        return

    target = sys.executable
    script = str(PROJECT_ROOT / "tray.py")
    ps_script = f"""
$WshShell = New-Object -ComObject WScript.Shell
$Shortcut = $WshShell.CreateShortcut("{shortcut}")
$Shortcut.TargetPath = "{target}"
$Shortcut.Arguments = '"{script}"'
$Shortcut.WorkingDirectory = "{PROJECT_ROOT}"
$Shortcut.Save()
"""
    subprocess.run(["powershell", "-NoProfile", "-Command", ps_script], check=True)
    log.info(f"Created startup shortcut at {shortcut}")


class TrayApp:
    def __init__(self) -> None:
        self._agent_process: Optional[subprocess.Popen] = None
        self._dashboard_process: Optional[subprocess.Popen] = None

    def _agent_running(self) -> bool:
        return self._agent_process is not None and self._agent_process.poll() is None

    def start_agent(self, icon=None, item=None) -> None:
        if self._agent_running():
            log.info("Agent already running")
            return
        log.info("Starting agent subprocess")
        self._agent_process = subprocess.Popen([sys.executable, str(PROJECT_ROOT / "main.py")])

    def stop_agent(self, icon=None, item=None) -> None:
        if not self._agent_running():
            return
        log.info("Stopping agent subprocess")
        self._agent_process.terminate()
        try:
            self._agent_process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            self._agent_process.kill()

    def open_dashboard(self, icon=None, item=None) -> None:
        cfg = get_config().dashboard
        if self._dashboard_process is None or self._dashboard_process.poll() is not None:
            log.info("Starting dashboard subprocess")
            self._dashboard_process = subprocess.Popen(
                [sys.executable, "-m", "dashboard.server"], cwd=str(PROJECT_ROOT)
            )
            import time

            time.sleep(1.0)  # give uvicorn a moment to bind before opening the browser
        webbrowser.open(f"http://{cfg.host}:{cfg.port}")

    def toggle_startup(self, icon=None, item=None) -> None:
        set_startup_enabled(not is_startup_enabled())

    def exit_app(self, icon, item=None) -> None:
        self.stop_agent()
        if self._dashboard_process is not None and self._dashboard_process.poll() is None:
            self._dashboard_process.terminate()
        icon.stop()

    def _build_icon_image(self):
        from PIL import Image, ImageDraw

        img = Image.new("RGB", (64, 64), color=(31, 111, 235))
        draw = ImageDraw.Draw(img)
        draw.ellipse((16, 16, 48, 48), fill=(255, 255, 255))
        return img

    def run(self) -> None:
        import pystray
        from pystray import MenuItem as Item

        menu = pystray.Menu(
            Item("Start Agent", self.start_agent),
            Item("Stop Agent", self.stop_agent),
            Item("Open Dashboard", self.open_dashboard),
            Item(
                "Start with Windows",
                self.toggle_startup,
                checked=lambda item: is_startup_enabled(),
            ),
            Item("Exit", self.exit_app),
        )
        icon = pystray.Icon("pc_agent", self._build_icon_image(), "PC Agent", menu)
        icon.run()


def main() -> None:
    TrayApp().run()


if __name__ == "__main__":
    main()
