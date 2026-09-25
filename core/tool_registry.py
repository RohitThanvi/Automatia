"""
Tool registry (spec section 28.3: "Do not make the LLM directly
execute arbitrary shell commands without the security layer").

Every capability the agent exposes to the LLM must be registered
here with an explicit JSON schema. The LLM never gets raw code
execution — it can only request one of these named, schema-validated
tools, and every call still passes through security/permissions.py
before it runs.
"""

from __future__ import annotations

import inspect
from dataclasses import dataclass
from typing import Any, Callable, Optional

from core.logging_setup import get_logger

log = get_logger()


@dataclass
class ToolSpec:
    name: str
    description: str
    parameters: dict[str, Any]  # JSON schema "properties" block
    required: list[str]
    fn: Callable[..., Any]

    def to_openai_schema(self) -> dict[str, Any]:
        """Format compatible with Ollama's function-calling / tools field."""
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": {
                    "type": "object",
                    "properties": self.parameters,
                    "required": self.required,
                },
            },
        }


class ToolRegistry:
    def __init__(self) -> None:
        self._tools: dict[str, ToolSpec] = {}

    def register(
        self,
        name: str,
        description: str,
        parameters: Optional[dict[str, Any]] = None,
        required: Optional[list[str]] = None,
    ):
        """Decorator: @registry.register("open_application", "...", {...})"""

        def decorator(fn: Callable[..., Any]) -> Callable[..., Any]:
            if name in self._tools:
                raise ValueError(f"Tool '{name}' already registered")
            self._tools[name] = ToolSpec(
                name=name,
                description=description,
                parameters=parameters or {},
                required=required or [],
                fn=fn,
            )
            return fn

        return decorator

    def get(self, name: str) -> Optional[ToolSpec]:
        return self._tools.get(name)

    def all_specs(self) -> list[ToolSpec]:
        return list(self._tools.values())

    def schemas(self) -> list[dict[str, Any]]:
        return [t.to_openai_schema() for t in self._tools.values()]

    def call(self, name: str, args: dict[str, Any]) -> Any:
        spec = self.get(name)
        if spec is None:
            raise KeyError(f"Unknown tool: {name}")
        sig = inspect.signature(spec.fn)
        # Filter to only the kwargs the function actually declares, so a
        # slightly-too-generous LLM tool call can't inject stray kwargs.
        accepted = {k: v for k, v in args.items() if k in sig.parameters}
        return spec.fn(**accepted)


# Process-wide singleton. Individual tool modules import this and
# register themselves on import — main.py imports every tools/*
# and computer/* module once at startup to populate it.
registry = ToolRegistry()
