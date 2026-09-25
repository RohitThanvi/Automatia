"""
Executor (spec section 8): ACTION -> OBSERVE -> VERIFY -> CONTINUE/RETRY/RECOVER.

This is the only place that actually calls into core/tool_registry.py.
Every call is checked against security/permissions.py first.
"""

from __future__ import annotations

import enum
from dataclasses import dataclass
from typing import Any, Optional

from core.logging_setup import get_logger
from core.planner import ToolCall
from core.tool_registry import registry
from security.confirmation import Confirmer
from security.permissions import requires_confirmation

log = get_logger()

MAX_RETRIES = 3


class FailureCategory(enum.Enum):
    """Spec section 23's failure list, collapsed into buckets that
    change *how* the agent should recover — a missing file needs a
    different response than a timeout, which needs a different
    response than a denied confirmation."""

    NOT_FOUND = "NOT_FOUND"            # file/window/element doesn't exist
    TIMEOUT = "TIMEOUT"                # operation took too long
    PERMISSION = "PERMISSION"          # OS-level access denied
    UNAVAILABLE = "UNAVAILABLE"        # dependent service down (Ollama, network, mic, camera)
    DENIED = "DENIED"                  # user declined confirmation — never retried
    UNKNOWN = "UNKNOWN"


def _categorize(error: str) -> FailureCategory:
    e = error.lower()
    if "not found" in e or "no such" in e or "no window" in e or "no ui element" in e or "no visible text" in e:
        return FailureCategory.NOT_FOUND
    if "timed out" in e or "timeout" in e:
        return FailureCategory.TIMEOUT
    if "permission" in e or "access denied" in e or "accessdenied" in e:
        return FailureCategory.PERMISSION
    if "connection" in e or "unavailable" in e or "refused" in e or "not installed" in e:
        return FailureCategory.UNAVAILABLE
    return FailureCategory.UNKNOWN


@dataclass
class ExecutionResult:
    ok: bool
    tool: str
    args: dict[str, Any]
    output: Optional[Any] = None
    error: Optional[str] = None
    denied: bool = False
    category: Optional[FailureCategory] = None


class Executor:
    def __init__(self, confirmer: Confirmer, auto_approve_low_risk: bool = True) -> None:
        self._confirmer = confirmer
        self._auto_approve_low_risk = auto_approve_low_risk

    def _describe(self, call: ToolCall) -> str:
        arg_str = ", ".join(f"{k}={v!r}" for k, v in call.args.items())
        return f"{call.name}({arg_str})"

    def execute(self, call: ToolCall) -> ExecutionResult:
        spec = registry.get(call.name)
        if spec is None:
            return ExecutionResult(ok=False, tool=call.name, args=call.args, error=f"Unknown tool '{call.name}'")

        if requires_confirmation(call.name, auto_approve_low_risk=self._auto_approve_low_risk):
            approved = self._confirmer.confirm(f"About to run: {self._describe(call)}")
            if not approved:
                log.info(f"User denied: {self._describe(call)}")
                return ExecutionResult(ok=False, tool=call.name, args=call.args, denied=True, error="User denied confirmation")

        log.info(f"Executing tool: {self._describe(call)}")
        try:
            output = registry.call(call.name, call.args)
        except Exception as e:  # a tool raising is itself a failure to observe/report, not a crash
            log.error(f"Tool '{call.name}' raised: {e}")
            return ExecutionResult(ok=False, tool=call.name, args=call.args, error=str(e))

        ok = bool(output.get("ok", True)) if isinstance(output, dict) else True
        error = output.get("error") if isinstance(output, dict) else None
        category = _categorize(error) if error else None
        return ExecutionResult(ok=ok, tool=call.name, args=call.args, output=output, error=error, category=category)

    def execute_with_retry(self, call: ToolCall, max_retries: int = MAX_RETRIES) -> ExecutionResult:
        """Spec section 8: 'implement reasonable retry limits to avoid
        infinite loops.' Retries only apply to LOW-risk, idempotent-ish
        automation failures (e.g. a UI element not found yet) — a denied
        confirmation is never retried, since that's a deliberate user choice.
        A DENIED or PERMISSION or UNAVAILABLE failure is also not retried:
        hammering a broken Ollama connection or a locked-down file three
        times wastes the retry budget on something that won't change
        between attempts a few hundred milliseconds apart."""
        last_result: Optional[ExecutionResult] = None
        for attempt in range(1, max_retries + 1):
            result = self.execute(call)
            if result.ok or result.denied:
                return result
            if result.category in (FailureCategory.PERMISSION, FailureCategory.UNAVAILABLE):
                log.warning(f"Not retrying {call.name}: {result.category.value} failures don't self-resolve")
                return result
            last_result = result
            log.warning(
                f"Attempt {attempt}/{max_retries} failed for {call.name} "
                f"[{result.category.value if result.category else 'UNKNOWN'}]: {result.error}"
            )
        assert last_result is not None
        return last_result
