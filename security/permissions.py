"""
Permission tiers (spec section 16).

This is the ONLY place that decides whether a tool call executes
automatically or must be confirmed. The LLM never bypasses this —
the executor consults `risk_of(tool_name)` for every single call,
including calls chosen by the fast-path router.
"""

from __future__ import annotations

import enum


class RiskTier(enum.Enum):
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"


# Tool name -> risk tier. Any tool NOT in this table defaults to HIGH
# (fail closed, not open) — see risk_of() below.
_RISK_TABLE: dict[str, RiskTier] = {
    # LOW — auto-executed
    "open_application": RiskTier.LOW,
    "focus_application": RiskTier.LOW,
    "list_open_windows": RiskTier.LOW,
    "read_file": RiskTier.LOW,
    "create_file": RiskTier.LOW,
    "write_file": RiskTier.LOW,
    "type_text": RiskTier.LOW,
    "press_key": RiskTier.LOW,
    "hotkey": RiskTier.LOW,
    "click_element": RiskTier.LOW,
    "double_click_element": RiskTier.LOW,
    "right_click_element": RiskTier.LOW,
    "move_mouse": RiskTier.LOW,
    "scroll": RiskTier.LOW,
    "drag": RiskTier.LOW,
    "take_screenshot": RiskTier.LOW,
    "read_screen": RiskTier.LOW,
    "find_ui_element": RiskTier.LOW,
    "open_url": RiskTier.LOW,
    "browser_search": RiskTier.LOW,
    "browser_navigate": RiskTier.LOW,
    "switch_browser_tab": RiskTier.LOW,
    "close_browser_tab": RiskTier.LOW,
    "list_browser_tabs": RiskTier.LOW,
    "read_page": RiskTier.LOW,
    "wait": RiskTier.LOW,
    "run_python": RiskTier.LOW,  # sandboxed / cwd-scoped, see tools/python.py
    "register_project": RiskTier.LOW,
    "open_project": RiskTier.LOW,
    "create_presentation": RiskTier.LOW,
    "create_document": RiskTier.LOW,
    "open_chatgpt": RiskTier.LOW,
    "send_chatgpt_prompt": RiskTier.LOW,
    "read_chatgpt_response": RiskTier.LOW,

    # MEDIUM — confirm before running
    "close_application": RiskTier.MEDIUM,
    "rename_file": RiskTier.MEDIUM,
    "move_file": RiskTier.MEDIUM,
    "copy_file": RiskTier.MEDIUM,
    "run_powershell": RiskTier.MEDIUM,
    "run_command": RiskTier.MEDIUM,
    "run_in_project": RiskTier.MEDIUM,

    # HIGH — always confirm, no exceptions
    "delete_file": RiskTier.HIGH,
}


def risk_of(tool_name: str) -> RiskTier:
    """Unknown tools are treated as HIGH risk (fail closed)."""
    return _RISK_TABLE.get(tool_name, RiskTier.HIGH)


def requires_confirmation(tool_name: str, *, auto_approve_low_risk: bool) -> bool:
    tier = risk_of(tool_name)
    if tier == RiskTier.LOW:
        return not auto_approve_low_risk
    return True  # MEDIUM and HIGH always require confirmation
