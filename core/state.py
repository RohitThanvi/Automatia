"""
The agent's state machine (spec section 1).

    IDLE -> WAKE -> LISTENING -> TRANSCRIBING -> PLANNING
         -> EXECUTING -> OBSERVING -> VERIFYING -> RESPONDING
         -> LISTENING / IDLE

This module owns *only* the state transitions and the short-term
task memory described in spec section 18. It has no I/O of its own —
voice/vision/execution modules call into it, which keeps it trivially
testable.
"""

from __future__ import annotations

import enum
import time
from dataclasses import dataclass, field
from typing import Any, Optional


class AgentState(enum.Enum):
    IDLE = "IDLE"
    WAKE = "WAKE"
    LISTENING = "LISTENING"
    TRANSCRIBING = "TRANSCRIBING"
    PLANNING = "PLANNING"
    EXECUTING = "EXECUTING"
    OBSERVING = "OBSERVING"
    VERIFYING = "VERIFYING"
    RESPONDING = "RESPONDING"
    PAUSED = "PAUSED"


# States it is legal to move to from a given state. Kept explicit and
# strict — an illegal transition raises rather than silently happening,
# because a state machine that repairs itself silently hides bugs.
_ALLOWED: dict[AgentState, set[AgentState]] = {
    AgentState.IDLE: {AgentState.WAKE, AgentState.PAUSED},
    AgentState.WAKE: {AgentState.LISTENING, AgentState.IDLE},
    AgentState.LISTENING: {AgentState.TRANSCRIBING, AgentState.IDLE, AgentState.PAUSED},
    AgentState.TRANSCRIBING: {AgentState.PLANNING, AgentState.IDLE},
    AgentState.PLANNING: {AgentState.EXECUTING, AgentState.RESPONDING, AgentState.IDLE},
    AgentState.EXECUTING: {AgentState.OBSERVING, AgentState.RESPONDING, AgentState.IDLE, AgentState.PAUSED},
    AgentState.OBSERVING: {AgentState.VERIFYING, AgentState.EXECUTING},
    AgentState.VERIFYING: {AgentState.EXECUTING, AgentState.RESPONDING, AgentState.PLANNING},
    AgentState.RESPONDING: {AgentState.LISTENING, AgentState.IDLE},
    AgentState.PAUSED: {AgentState.IDLE, AgentState.LISTENING},
}


@dataclass
class PlanStep:
    description: str
    tool: Optional[str] = None
    args: dict[str, Any] = field(default_factory=dict)
    done: bool = False
    result: Optional[Any] = None
    error: Optional[str] = None


@dataclass
class TaskMemory:
    """Short-term memory for the task currently in flight (spec 18)."""

    raw_command: Optional[str] = None
    plan: list[PlanStep] = field(default_factory=list)
    current_step_index: int = 0
    current_application: Optional[str] = None
    current_document: Optional[str] = None
    last_action: Optional[str] = None
    last_observation: Optional[str] = None
    errors: list[str] = field(default_factory=list)
    retry_count: int = 0
    max_retries: int = 3
    started_at: float = field(default_factory=time.time)

    def reset(self) -> None:
        self.__init__()  # type: ignore[misc]

    def current_step(self) -> Optional[PlanStep]:
        if 0 <= self.current_step_index < len(self.plan):
            return self.plan[self.current_step_index]
        return None

    def advance(self) -> None:
        self.current_step_index += 1
        self.retry_count = 0

    def remaining_steps(self) -> list[PlanStep]:
        return self.plan[self.current_step_index :]

    def is_complete(self) -> bool:
        return self.current_step_index >= len(self.plan)


class InvalidTransition(RuntimeError):
    pass


class AgentStateMachine:
    def __init__(self) -> None:
        self._state = AgentState.IDLE
        self.task = TaskMemory()
        self._history: list[tuple[float, AgentState, AgentState]] = []

    @property
    def state(self) -> AgentState:
        return self._state

    def transition(self, new_state: AgentState, *, force: bool = False) -> None:
        if not force and new_state not in _ALLOWED.get(self._state, set()):
            raise InvalidTransition(
                f"Cannot go from {self._state.value} to {new_state.value}"
            )
        self._history.append((time.time(), self._state, new_state))
        self._state = new_state
        if new_state == AgentState.IDLE:
            self.task.reset()

    def force_idle(self) -> None:
        """Used by 'stop' / 'cancel' / 'abort' — always succeeds, from any state."""
        self.transition(AgentState.IDLE, force=True)

    def pause(self) -> None:
        self.transition(AgentState.PAUSED, force=True)

    def history(self) -> list[tuple[float, AgentState, AgentState]]:
        return list(self._history)
