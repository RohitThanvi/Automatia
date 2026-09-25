"""
Agent orchestrator — drives the state machine defined in core/state.py
through one full wake -> listen -> plan -> execute -> respond cycle.

This module has no idea *how* speech is captured or *how* a tool
works; it only sequences the pieces, which is what makes each of them
independently testable and replaceable (spec section 28.7).
"""

from __future__ import annotations

from typing import Optional

from core.config import get_config
from core.executor import Executor
from core.logging_setup import get_logger
from core.memory import Memory
from core.planner import Planner, ToolCall
from core.state import AgentState, AgentStateMachine, PlanStep
from security.confirmation import Confirmer

log = get_logger()

_STOP_WORDS = {"stop", "cancel", "abort"}
_PAUSE_WORDS = {"pause"}

MAX_STEPS_PER_TASK = 25  # spec 28.5: hard cap so a bad plan can't loop forever


class Agent:
    def __init__(
        self,
        planner: Planner,
        executor: Executor,
        confirmer: Confirmer,
        speak_fn,
    ) -> None:
        self.sm = AgentStateMachine()
        self._planner = planner
        self._executor = executor
        self._confirmer = confirmer
        self._speak = speak_fn
        self._memory = Memory()
        self._conversation: list[dict[str, str]] = []

    def _auto_verify(self, call: ToolCall) -> Optional[str]:
        """Post-condition checks that don't require the LLM to ask for
        them (spec section 8). Returns an error string if verification
        fails, or None if the action's effect was confirmed (or isn't
        independently verifiable, in which case we trust the tool's own
        'ok' result)."""
        if call.name == "open_application":
            from computer.windows import verify_application_open

            app_name = call.args.get("app_name", "")
            if app_name and not verify_application_open(app_name, timeout_s=5.0):
                return f"'{app_name}' does not appear to have opened (no matching window found after 5s)"
            self.sm.task.current_application = app_name
        elif call.name == "close_application":
            self.sm.task.current_application = None
        return None

    def _is_control_word(self, text: str) -> Optional[str]:
        t = text.strip().lower().rstrip(".!")
        if t in _STOP_WORDS:
            return "stop"
        if t in _PAUSE_WORDS:
            return "pause"
        return None

    def handle_utterance(self, text: str) -> str:
        """Entry point once STT has produced text for one user utterance.
        Returns the text the agent should speak back."""
        control = self._is_control_word(text)
        if control == "stop":
            log.info("Stop word received — aborting current task")
            self.sm.force_idle()
            self._conversation.clear()
            return "Stopped."
        if control == "pause":
            self.sm.pause()
            return "Paused."

        self.sm.task.raw_command = text
        self.sm.transition(AgentState.PLANNING, force=True)
        self._conversation.append({"role": "user", "content": text})

        reply = self._run_plan_execute_loop(text)

        self.sm.transition(AgentState.RESPONDING, force=True)
        self.sm.transition(AgentState.LISTENING, force=True)
        return reply

    def _run_plan_execute_loop(self, user_text: str) -> str:
        steps_run = 0
        while steps_run < MAX_STEPS_PER_TASK:
            steps_run += 1
            response = self._planner.plan_next_step(user_text, self._conversation)

            if response.tool_call is None:
                # Model decided the task is done, or it's asking a clarifying
                # question — either way, no tool call means we stop here.
                final_text = response.message or "Done."
                self._conversation.append({"role": "assistant", "content": final_text})
                self._memory.log_task(user_text, outcome="success", detail=final_text)
                return final_text

            self.sm.transition(AgentState.EXECUTING, force=True)
            call: ToolCall = response.tool_call
            self.sm.task.plan.append(PlanStep(description=call.name, tool=call.name, args=call.args))
            self.sm.task.last_action = f"{call.name}({call.args})"

            result = self._executor.execute_with_retry(call)

            self.sm.transition(AgentState.OBSERVING, force=True)
            self.sm.task.last_observation = str(result.output)[:500]
            self.sm.transition(AgentState.VERIFYING, force=True)

            # Automatic post-condition verification (spec section 8's own
            # example: "if the agent expects PowerPoint to be open but it
            # is not, it should detect this"). This does NOT depend on the
            # LLM remembering to call a verification tool — it always runs
            # for actions whose success can be independently confirmed.
            if result.ok:
                verify_error = self._auto_verify(call)
                if verify_error:
                    result.ok = False
                    result.error = verify_error
                    self.sm.task.current_application = None

            if result.denied:
                msg = f"Okay, I won't run {call.name}."
                self._conversation.append({"role": "assistant", "content": msg})
                self._memory.log_task(user_text, outcome="cancelled", detail=msg)
                return msg

            if not result.ok:
                self.sm.task.errors.append(result.error or "unknown error")
                log.warning(f"Step failed permanently: {call.name}: {result.error}")
                self._conversation.append(
                    {
                        "role": "tool",
                        "content": f"Tool '{call.name}' failed: {result.error}. Choose a different approach or report the failure to the user.",
                    }
                )
                self.sm.transition(AgentState.PLANNING, force=True)
                continue

            self.sm.task.current_step().done = True  # type: ignore[union-attr]
            self.sm.task.current_step().result = result.output  # type: ignore[union-attr]
            self.sm.task.advance()
            self._conversation.append(
                {"role": "tool", "content": f"Tool '{call.name}' succeeded: {result.output}"}
            )
            self.sm.transition(AgentState.PLANNING, force=True)

        msg = "I stopped after reaching the maximum number of steps for this task. Would you like me to continue?"
        self._memory.log_task(user_text, outcome="failed", detail="max steps reached")
        return msg

    def start_wake(self) -> None:
        self.sm.transition(AgentState.WAKE, force=True)
        self.sm.transition(AgentState.LISTENING, force=True)
        self._conversation.clear()

    def speak(self, text: str) -> None:
        self._speak(text)
