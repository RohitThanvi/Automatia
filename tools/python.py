"""
run_python: executes short Python snippets in a fresh subprocess
(never in-process via exec/eval), with a timeout and output cap.
Classified LOW risk because it runs as the current user with no
elevated privileges and no filesystem access outside the workspace
cwd — but it is still a real subprocess, so keep an eye on this tool
if you ever expose the agent to untrusted voice input from strangers.
"""

from __future__ import annotations

import subprocess
import sys

from core.config import get_config
from core.logging_setup import get_logger
from core.tool_registry import registry

log = get_logger()


@registry.register(
    "run_python",
    "Execute a short Python snippet and return stdout/stderr. Runs in an isolated subprocess.",
    {
        "code": {"type": "string", "description": "Python source code to execute."},
        "timeout_s": {"type": "integer", "description": "Max seconds before the process is killed."},
    },
    required=["code"],
)
def run_python(code: str, timeout_s: int = 30) -> dict:
    workdir = str(get_config().resolved_workspace_dir())
    log.info(f"Executing python snippet ({len(code)} chars)")
    try:
        result = subprocess.run(
            [sys.executable, "-c", code],
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
        return {"ok": False, "error": f"Snippet timed out after {timeout_s}s"}
