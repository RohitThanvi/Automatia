"""
Terminal/command tools (spec 28.3: never let the LLM run arbitrary
shell commands directly). run_command and run_powershell are MEDIUM
risk (see security/permissions.py) and always pass through
confirmation before this code ever runs.
"""

from __future__ import annotations

import platform
import subprocess

from core.config import get_config
from core.logging_setup import get_logger
from core.tool_registry import registry

log = get_logger()

_DEFAULT_TIMEOUT_S = 60


@registry.register(
    "run_command",
    "Run a single shell command and return its stdout/stderr. MEDIUM risk — requires confirmation.",
    {
        "command": {"type": "string", "description": "The exact command line to execute."},
        "cwd": {"type": "string", "description": "Working directory. Defaults to the agent workspace."},
        "timeout_s": {"type": "integer", "description": "Max seconds to wait before killing the process."},
    },
    required=["command"],
)
def run_command(command: str, cwd: str | None = None, timeout_s: int = _DEFAULT_TIMEOUT_S) -> dict:
    workdir = cwd or str(get_config().resolved_workspace_dir())
    log.info(f"Executing command: {command!r} (cwd={workdir})")
    try:
        result = subprocess.run(
            command,
            shell=True,
            cwd=workdir,
            capture_output=True,
            text=True,
            timeout=timeout_s,
        )
        return {
            "ok": result.returncode == 0,
            "returncode": result.returncode,
            "stdout": result.stdout[-4000:],
            "stderr": result.stderr[-4000:],
        }
    except subprocess.TimeoutExpired:
        return {"ok": False, "error": f"Command timed out after {timeout_s}s"}


@registry.register(
    "run_powershell",
    "Run a PowerShell script/command on Windows. MEDIUM risk — requires confirmation.",
    {
        "script": {"type": "string", "description": "PowerShell command or script text."},
        "timeout_s": {"type": "integer", "description": "Max seconds to wait."},
    },
    required=["script"],
)
def run_powershell(script: str, timeout_s: int = _DEFAULT_TIMEOUT_S) -> dict:
    if platform.system() != "Windows":
        return {"ok": False, "error": "run_powershell is only available on Windows"}
    log.info(f"Executing PowerShell: {script[:120]!r}")
    try:
        result = subprocess.run(
            ["powershell", "-NoProfile", "-NonInteractive", "-Command", script],
            capture_output=True,
            text=True,
            timeout=timeout_s,
        )
        return {
            "ok": result.returncode == 0,
            "returncode": result.returncode,
            "stdout": result.stdout[-4000:],
            "stderr": result.stderr[-4000:],
        }
    except subprocess.TimeoutExpired:
        return {"ok": False, "error": f"Script timed out after {timeout_s}s"}


@registry.register(
    "wait",
    "Pause execution for a number of seconds — use between an action and checking its result.",
    {"seconds": {"type": "number", "description": "How long to wait."}},
    required=["seconds"],
)
def wait(seconds: float) -> dict:
    import time

    seconds = max(0.0, min(seconds, 30.0))  # hard cap so the LLM can't stall the agent
    time.sleep(seconds)
    return {"ok": True, "waited": seconds}
