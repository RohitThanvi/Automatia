"""
Filesystem tools (spec section 11 / tool list in section 5).

All paths are resolved relative to the configured workspace directory
unless an absolute path is given, so a spoken "create a folder called
Research" can't accidentally write outside the sandbox the user chose.
"""

from __future__ import annotations

import shutil
from pathlib import Path

from core.config import get_config
from core.logging_setup import get_logger
from core.tool_registry import registry

log = get_logger()


def _resolve(path: str) -> Path:
    p = Path(path).expanduser()
    if not p.is_absolute():
        p = get_config().resolved_workspace_dir() / p
    return p


@registry.register(
    "create_file",
    "Create a new file (and any parent folders/directories) with optional initial text content.",
    {
        "path": {"type": "string", "description": "File or folder path, relative to the workspace unless absolute."},
        "content": {"type": "string", "description": "Initial text content. Omit or leave empty to create a folder instead of a file."},
        "is_directory": {"type": "boolean", "description": "True to create a directory instead of a file."},
    },
    required=["path"],
)
def create_file(path: str, content: str = "", is_directory: bool = False) -> dict:
    target = _resolve(path)
    if is_directory:
        target.mkdir(parents=True, exist_ok=True)
        log.info(f"Created directory {target}")
        return {"ok": True, "path": str(target), "type": "directory"}

    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(content, encoding="utf-8")
    log.info(f"Created file {target} ({len(content)} chars)")
    return {"ok": True, "path": str(target), "type": "file"}


@registry.register(
    "read_file",
    "Read the text content of a file.",
    {"path": {"type": "string", "description": "File path, relative to the workspace unless absolute."}},
    required=["path"],
)
def read_file(path: str) -> dict:
    target = _resolve(path)
    if not target.exists():
        return {"ok": False, "error": f"File not found: {target}"}
    text = target.read_text(encoding="utf-8", errors="replace")
    return {"ok": True, "path": str(target), "content": text}


@registry.register(
    "write_file",
    "Overwrite or append text content to an existing (or new) file.",
    {
        "path": {"type": "string", "description": "File path, relative to the workspace unless absolute."},
        "content": {"type": "string", "description": "Text to write."},
        "append": {"type": "boolean", "description": "True to append instead of overwrite."},
    },
    required=["path", "content"],
)
def write_file(path: str, content: str, append: bool = False) -> dict:
    target = _resolve(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    mode = "a" if append else "w"
    with open(target, mode, encoding="utf-8") as f:
        f.write(content)
    log.info(f"{'Appended to' if append else 'Wrote'} {target} ({len(content)} chars)")
    return {"ok": True, "path": str(target)}


@registry.register(
    "rename_file",
    "Rename a file or folder in place.",
    {
        "path": {"type": "string", "description": "Existing file/folder path."},
        "new_name": {"type": "string", "description": "New file/folder name (not a full path)."},
    },
    required=["path", "new_name"],
)
def rename_file(path: str, new_name: str) -> dict:
    src = _resolve(path)
    if not src.exists():
        return {"ok": False, "error": f"Not found: {src}"}
    dst = src.parent / new_name
    src.rename(dst)
    log.info(f"Renamed {src} -> {dst}")
    return {"ok": True, "path": str(dst)}


@registry.register(
    "move_file",
    "Move a file or folder to a new location.",
    {
        "path": {"type": "string", "description": "Existing file/folder path."},
        "destination": {"type": "string", "description": "Destination folder path."},
    },
    required=["path", "destination"],
)
def move_file(path: str, destination: str) -> dict:
    src = _resolve(path)
    dst_dir = _resolve(destination)
    if not src.exists():
        return {"ok": False, "error": f"Not found: {src}"}
    dst_dir.mkdir(parents=True, exist_ok=True)
    dst = shutil.move(str(src), str(dst_dir))
    log.info(f"Moved {src} -> {dst}")
    return {"ok": True, "path": str(dst)}


@registry.register(
    "copy_file",
    "Copy a file to a new location.",
    {
        "path": {"type": "string", "description": "Existing file path."},
        "destination": {"type": "string", "description": "Destination folder path."},
    },
    required=["path", "destination"],
)
def copy_file(path: str, destination: str) -> dict:
    src = _resolve(path)
    dst_dir = _resolve(destination)
    if not src.exists():
        return {"ok": False, "error": f"Not found: {src}"}
    dst_dir.mkdir(parents=True, exist_ok=True)
    dst = shutil.copy2(str(src), str(dst_dir))
    log.info(f"Copied {src} -> {dst}")
    return {"ok": True, "path": str(dst)}


@registry.register(
    "delete_file",
    "Permanently delete a file or folder. HIGH RISK — always requires explicit user confirmation.",
    {
        "path": {"type": "string", "description": "File or folder path to delete."},
        "recursive": {"type": "boolean", "description": "True to delete a non-empty folder and its contents."},
    },
    required=["path"],
)
def delete_file(path: str, recursive: bool = False) -> dict:
    # NOTE: the executor enforces confirmation for this tool via
    # security/permissions.py — this function assumes it has already
    # been approved by the time it is called.
    target = _resolve(path)
    if not target.exists():
        return {"ok": False, "error": f"Not found: {target}"}
    if target.is_dir():
        if recursive:
            shutil.rmtree(target)
        else:
            target.rmdir()
    else:
        target.unlink()
    log.info(f"Deleted {target}")
    return {"ok": True, "path": str(target)}
