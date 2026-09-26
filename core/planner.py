"""
Planner (spec section 7 + 25's fast/slow router).

The LLM's ONLY output channel is a tool call chosen from
core/tool_registry.py's schemas — it cannot emit arbitrary code or
shell commands (spec 28.3). This module is deliberately dumb about
*how* to accomplish a task; all of that reasoning lives in the model
prompt/weights. This module's job is: build the prompt, call Ollama,
parse the response into a validated ToolCall, and pick between the
fast and slow model.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from typing import Any, Optional

import ollama

from core.config import get_config
from core.logging_setup import get_logger
from core.tool_registry import registry

log = get_logger()


class _GroqChatAdapter:
    """Wraps groq.Groq so it exposes the same `.chat(model=, messages=,
    tools=, options=) -> {"message": {...}}` shape planner.py already
    expects from ollama.Client — the rest of this module doesn't need to
    know which provider it's actually talking to.

    Groq's API is OpenAI-compatible, which differs from Ollama's shape in
    two ways that matter here: tool_call arguments come back as a JSON
    *string*, not a dict, and finished content lives at
    choice.message.content, not response["message"]["content"]."""

    def __init__(self, client: Any) -> None:
        self._client = client

    def chat(self, model: str, messages: list, tools: list, options: dict) -> dict:
        completion = self._client.chat.completions.create(
            model=model,
            messages=messages,
            tools=tools or None,
            temperature=options.get("temperature"),
            max_tokens=options.get("num_predict"),
        )
        choice = completion.choices[0].message
        tool_calls = []
        for tc in choice.tool_calls or []:
            try:
                args = json.loads(tc.function.arguments)
            except (json.JSONDecodeError, TypeError):
                log.warning(f"Groq returned non-JSON tool arguments: {tc.function.arguments!r}")
                args = {}
            tool_calls.append({"function": {"name": tc.function.name, "arguments": args}})
        return {"message": {"tool_calls": tool_calls, "content": choice.content or ""}}

_SYSTEM_PROMPT = """You are the planning brain of a Windows desktop AI agent that controls \
the computer on the user's behalf via a fixed set of tools.

Rules:
- You may ONLY act by calling one of the provided tools. You cannot run arbitrary code.
- Break multi-step requests into one tool call at a time; you will be called again after \
each result to decide the next step.
- If the task is already fully done, respond with plain text (no tool call) summarizing \
what was accomplished.
- If you are unsure which application/file the user means, ask a brief clarifying question \
as plain text instead of guessing with a destructive tool.
- Never call delete_file, close_application, run_command, or run_powershell unless the \
user's request clearly requires it.
"""


@dataclass
class ToolCall:
    name: str
    args: dict[str, Any]


@dataclass
class PlannerResponse:
    tool_call: Optional[ToolCall]
    message: Optional[str]  # plain-text reply when no tool call is made


class Planner:
    def __init__(self) -> None:
        cfg = get_config().llm
        if cfg.provider == "groq":
            from groq import Groq

            api_key = os.environ.get("GROQ_API_KEY")
            if not api_key:
                raise RuntimeError(
                    "llm.provider is 'groq' in config.yaml but the GROQ_API_KEY "
                    "environment variable is not set. Get a key at "
                    "https://console.groq.com/keys, then (PowerShell) "
                    '$env:GROQ_API_KEY = "gsk_..." before running.'
                )
            self._client = _GroqChatAdapter(Groq(api_key=api_key))
        else:
            self._client = ollama.Client(host=cfg.host, timeout=cfg.request_timeout_s)
        self._model = cfg.model
        self._fast_model = cfg.fast_model
        self._temperature = cfg.temperature
        self._max_tokens = cfg.max_tokens

    def _choose_model(self, user_text: str, history_len: int) -> str:
        """Fast/slow router (spec section 25). Simple heuristic for
        Phase 1: short, single-clause commands with no prior back-and-forth
        go to the small model; anything longer or already mid-task uses
        the full reasoning model."""
        word_count = len(user_text.split())
        if history_len == 0 and word_count <= 6:
            return self._fast_model
        return self._model

    def plan_next_step(
        self,
        user_text: str,
        conversation: list[dict[str, str]],
    ) -> PlannerResponse:
        """conversation is the running message history for the current task
        (spec section 18's short-term memory), NOT the full session history.
        It already contains the user's utterance (appended by the caller
        before the plan/execute loop starts) plus any tool results from
        earlier steps in this task, so it must NOT be re-added here — doing
        so used to re-inject the original command as a fresh "user" turn
        after every single tool call, since the last conversation entry
        after a tool call is a 'tool' message and therefore never equal to
        user_text."""
        model = self._choose_model(user_text, len(conversation))
        messages = [{"role": "system", "content": _SYSTEM_PROMPT}, *conversation]

        log.info(f"Planning with model={model}")
        response = self._client.chat(
            model=model,
            messages=messages,
            tools=registry.schemas(),
            options={"temperature": self._temperature, "num_predict": self._max_tokens},
        )

        msg = response["message"]
        tool_calls = msg.get("tool_calls") or []
        if tool_calls:
            call = tool_calls[0]  # one tool call per turn, per the system prompt
            fn = call["function"]
            return PlannerResponse(
                tool_call=ToolCall(name=fn["name"], args=fn.get("arguments", {})),
                message=None,
            )
        return PlannerResponse(tool_call=None, message=msg.get("content", "").strip())
