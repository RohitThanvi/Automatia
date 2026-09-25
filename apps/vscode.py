"""
VS Code / development agent (spec section 13).

Reading/editing files, running commands, and inspecting output are
already covered by tools/filesystem.py and tools/terminal.py — this
module only adds the VS Code-specific piece: opening a named project
by resolving it against a small table of known project directories,
and running a command scoped to that project's folder so "run the
backend" doesn't require the user to repeat the full path every time.

Destructive repository operations (git reset --hard, force-push, etc.)
are NOT special-cased here — they go through run_command/run_powershell
like any other shell command, which means they already require
MEDIUM-risk confirmation (security/permissions.py). That satisfies
spec section 13's "require confirmation before destructive repository
operations" without needing a git-aware allowlist that would just be
one more thing to keep in sync.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Optional

from core.config import get_config
from core.logging_setup import get_logger
from core.memory import Memory
from core.tool_registry import registry
from tools.terminal import run_command

log = get_logger()

_PREFERENCE_KEY = "known_projects"  # dict[str, str] project name -> absolute path, in long-term memory


def _load_known_projects() -> dict[str, str]:
    mem = Memory()
    return mem.get_preference(_PREFERENCE_KEY, default={})


def _save_known_projects(projects: dict[str, str]) -> None:
    mem = Memory()
    mem.set_preference(_PREFERENCE_KEY, projects)


@registry.register(
    "register_project",
    "Remember a project's folder path under a short name, so it can be opened later just by name.",
    {
        "name": {"type": "string", "description": "Short name to refer to the project by, e.g. 'VAYU'."},
        "path": {"type": "string", "description": "Absolute path to the project's root folder."},
    },
    required=["name", "path"],
)
def register_project(name: str, path: str) -> dict:
    resolved = str(Path(path).expanduser().resolve())
    if not Path(resolved).is_dir():
        return {"ok": False, "error": f"Not a directory: {resolved}"}
    projects = _load_known_projects()
    projects[name.lower()] = resolved
    _save_known_projects(projects)
    log.info(f"Registered project '{name}' -> {resolved}")
    return {"ok": True, "name": name, "path": resolved}


@registry.register(
    "open_project",
    "Open a previously-registered project in VS Code by name, or open an arbitrary folder path directly.",
    {"name_or_path": {"type": "string", "description": "A registered project name, or a folder path."}},
    required=["name_or_path"],
)
def open_project(name_or_path: str) -> dict:
    import subprocess

    projects = _load_known_projects()
    key = name_or_path.lower()
    path = projects.get(key, name_or_path)
    resolved = Path(path).expanduser()

    if not resolved.is_dir():
        known = ", ".join(projects.keys()) or "(none registered yet)"
        return {
            "ok": False,
            "error": f"'{name_or_path}' is not a known project or valid folder. Known projects: {known}",
        }

    try:
        subprocess.Popen(["code", str(resolved)])
    except FileNotFoundError:
        return {"ok": False, "error": "VS Code's 'code' command isn't on PATH. In VS Code, run 'Shell Command: Install code command in PATH'."}

    log.info(f"Opened project in VS Code: {resolved}")
    return {"ok": True, "path": str(resolved)}


@registry.register(
    "run_in_project",
    "Run a shell command with its working directory set to a registered project's folder (e.g. running the backend, running tests). MEDIUM risk — requires confirmation.",
    {
        "name_or_path": {"type": "string", "description": "A registered project name, or a folder path."},
        "command": {"type": "string", "description": "Command to run, e.g. 'python main.py' or 'pytest'."},
        "timeout_s": {"type": "integer"},
    },
    required=["name_or_path", "command"],
)
def run_in_project(name_or_path: str, command: str, timeout_s: int = 120) -> dict:
    projects = _load_known_projects()
    path = projects.get(name_or_path.lower(), name_or_path)
    resolved = Path(path).expanduser()
    if not resolved.is_dir():
        return {"ok": False, "error": f"Unknown project or folder: {name_or_path}"}

    return run_command(command, cwd=str(resolved), timeout_s=timeout_s)
