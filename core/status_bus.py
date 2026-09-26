"""
Status/command bus (spec section 19/20).

The dashboard and system tray run as SEPARATE processes from the
agent (`python main.py`) — a tray icon and a live voice loop sharing
one process is fragile on Windows, and a crashed dashboard shouldn't
be able to take the agent down with it. So instead of an in-process
shared object, they talk through two small JSON files:

  data/status.json    — agent process writes, dashboard reads
  data/commands.json  — dashboard process writes (appends), agent
                         process reads and clears (pops)

Both writes are atomic (write to a temp file, then os.replace) so a
reader never sees a half-written file. This is intentionally simple —
a real multi-writer queue would use SQLite or a proper message
broker, but there is exactly one writer per file here, which makes
atomic-replace sufficient and avoids adding a lock-file dependency.
"""

from __future__ import annotations

import json
import os
import tempfile
import time
from pathlib import Path
from typing import Any, Optional

from core.config import get_config

_STATUS_FILENAME = "status.json"
_COMMANDS_FILENAME = "commands.json"


def _data_dir() -> Path:
    d = get_config().resolved_db_path().parent  # reuse the same data/ dir as the SQLite memory DB
    d.mkdir(parents=True, exist_ok=True)
    return d


def _atomic_write_json(path: Path, data: Any) -> None:
    fd, tmp_path = tempfile.mkstemp(dir=str(path.parent), suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(data, f)
        os.replace(tmp_path, path)
    except Exception:
        if os.path.exists(tmp_path):
            os.remove(tmp_path)
        raise


def write_status(
    state: str,
    current_task: Optional[str] = None,
    current_application: Optional[str] = None,
    last_action: Optional[str] = None,
    extra: Optional[dict] = None,
) -> None:
    payload = {
        "state": state,
        "current_task": current_task,
        "current_application": current_application,
        "last_action": last_action,
        "updated_at": time.time(),
        **(extra or {}),
    }
    _atomic_write_json(_data_dir() / _STATUS_FILENAME, payload)


def read_status() -> dict:
    path = _data_dir() / _STATUS_FILENAME
    if not path.exists():
        return {"state": "UNKNOWN", "updated_at": None}
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError):
        return {"state": "UNKNOWN", "updated_at": None}


# Commands the dashboard/tray may send. Kept as a closed set so a
# malformed or malicious write to commands.json can't do anything the
# agent doesn't already explicitly support.
VALID_COMMANDS = {"stop", "cancel", "pause", "resume", "mute", "unmute", "enable_gestures", "disable_gestures"}


def push_command(command: str) -> None:
    if command not in VALID_COMMANDS:
        raise ValueError(f"Unknown command '{command}'. Valid: {sorted(VALID_COMMANDS)}")
    path = _data_dir() / _COMMANDS_FILENAME
    existing = []
    if path.exists():
        try:
            with open(path, "r", encoding="utf-8") as f:
                existing = json.load(f)
        except (json.JSONDecodeError, OSError):
            existing = []
    existing.append({"command": command, "queued_at": time.time()})
    _atomic_write_json(path, existing)


def pop_commands() -> list[str]:
    """Read and clear every pending command in one atomic step. Called
    by the agent's main loop, not by the dashboard."""
    path = _data_dir() / _COMMANDS_FILENAME
    if not path.exists():
        return []
    try:
        with open(path, "r", encoding="utf-8") as f:
            entries = json.load(f)
    except (json.JSONDecodeError, OSError):
        entries = []
    _atomic_write_json(path, [])
    return [e["command"] for e in entries if isinstance(e, dict) and "command" in e]
