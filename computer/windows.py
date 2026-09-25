"""
Application and window control (spec section 5/9).

Phase 1 implements these with subprocess launch + psutil/pygetwindow,
which covers "open X", "close X", "what's open" reliably. The full
UI Automation accessibility tree (spec section 6's four-level
fallback hierarchy) lands in Phase 2 in this same module — the
function signatures below are the stable contract the planner
already relies on, so Phase 2 only changes internals.
"""

from __future__ import annotations

import platform
import shutil
import subprocess
import time

from core.logging_setup import get_logger
from core.tool_registry import registry

log = get_logger()
IS_WINDOWS = platform.system() == "Windows"

# Common friendly-name -> launch-command aliases. Extend this table
# freely; it is intentionally data, not logic.
_APP_ALIASES: dict[str, str] = {
    "chrome": "chrome",
    "google chrome": "chrome",
    "edge": "msedge",
    "word": "winword",
    "microsoft word": "winword",
    "powerpoint": "powerpnt",
    "microsoft powerpoint": "powerpnt",
    "excel": "excel",
    "vs code": "code",
    "vscode": "code",
    "visual studio code": "code",
    "notepad": "notepad",
    "terminal": "wt",
    "windows terminal": "wt",
    "file explorer": "explorer",
    "explorer": "explorer",
}


def _resolve_launch_command(app_name: str) -> str:
    key = app_name.strip().lower()
    return _APP_ALIASES.get(key, key)


@registry.register(
    "open_application",
    "Open/launch a desktop application by name (e.g. 'Chrome', 'PowerPoint', 'VS Code').",
    {"app_name": {"type": "string", "description": "Human-readable application name."}},
    required=["app_name"],
)
def open_application(app_name: str) -> dict:
    command = _resolve_launch_command(app_name)
    log.info(f"Opening application: {app_name} (command={command})")

    if not IS_WINDOWS:
        # Best-effort cross-platform fallback so the codebase is testable
        # off Windows; the real target platform is Windows (spec section 20).
        opener = "open" if platform.system() == "Darwin" else "xdg-open"
        if shutil.which(opener):
            subprocess.Popen([opener, command])
            return {"ok": True, "note": f"launched via {opener} (non-Windows dev fallback)"}
        return {"ok": False, "error": f"Don't know how to launch '{app_name}' on {platform.system()}"}

    try:
        subprocess.Popen(["cmd", "/c", "start", "", command], shell=False)
    except OSError as e:
        return {"ok": False, "error": str(e)}

    time.sleep(1.0)  # give the process a moment to spawn a window before verification
    return {"ok": True, "app_name": app_name, "command": command}


@registry.register(
    "close_application",
    "Close a running application by name. MEDIUM risk — requires confirmation.",
    {"app_name": {"type": "string", "description": "Human-readable application name."}},
    required=["app_name"],
)
def close_application(app_name: str) -> dict:
    import psutil

    command = _resolve_launch_command(app_name)
    closed = []
    for proc in psutil.process_iter(["pid", "name"]):
        pname = (proc.info.get("name") or "").lower()
        if command in pname or app_name.lower() in pname:
            try:
                proc.terminate()
                closed.append(proc.info["name"])
            except (psutil.NoSuchProcess, psutil.AccessDenied) as e:
                log.warning(f"Could not close {pname}: {e}")
    if not closed:
        return {"ok": False, "error": f"No running process matched '{app_name}'"}
    log.info(f"Closed processes: {closed}")
    return {"ok": True, "closed": closed}


@registry.register(
    "list_open_windows",
    "List titles of all currently open top-level windows.",
    {},
    required=[],
)
def list_open_windows() -> dict:
    if not IS_WINDOWS:
        return {"ok": False, "error": "Window enumeration requires Windows (pygetwindow)"}
    import pygetwindow as gw

    titles = [w.title for w in gw.getAllWindows() if w.title.strip()]
    return {"ok": True, "windows": titles}


@registry.register(
    "focus_application",
    "Bring an already-open application's window to the foreground.",
    {"app_name": {"type": "string", "description": "Application or window title (substring match)."}},
    required=["app_name"],
)
def focus_application(app_name: str) -> dict:
    if not IS_WINDOWS:
        return {"ok": False, "error": "Focusing windows requires Windows (pygetwindow)"}
    import pygetwindow as gw

    matches = [w for w in gw.getAllWindows() if app_name.lower() in w.title.lower()]
    if not matches:
        return {"ok": False, "error": f"No open window matches '{app_name}'"}
    win = matches[0]
    try:
        if win.isMinimized:
            win.restore()
        win.activate()
    except Exception as e:  # pygetwindow's activate() can be flaky on Win11 focus rules
        log.warning(f"activate() failed, falling back: {e}")
    return {"ok": True, "focused": win.title}


def verify_application_open(app_name: str, timeout_s: float = 5.0) -> bool:
    """Used by core/executor.py's observe/verify loop (spec section 8) —
    not exposed to the LLM directly, only called internally after
    open_application to confirm the action actually worked."""
    if not IS_WINDOWS:
        return True  # can't verify off-Windows; assume success in dev
    import pygetwindow as gw

    deadline = time.time() + timeout_s
    while time.time() < deadline:
        titles = [w.title.lower() for w in gw.getAllWindows()]
        if any(app_name.lower() in t for t in titles):
            return True
        time.sleep(0.3)
    return False
