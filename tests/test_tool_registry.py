import pytest

from core.tool_registry import ToolRegistry


def test_register_and_call():
    reg = ToolRegistry()

    @reg.register("add", "Add two numbers", {"a": {"type": "integer"}, "b": {"type": "integer"}}, ["a", "b"])
    def add(a: int, b: int) -> int:
        return a + b

    assert reg.call("add", {"a": 2, "b": 3}) == 5


def test_call_unknown_tool_raises():
    reg = ToolRegistry()
    with pytest.raises(KeyError):
        reg.call("nonexistent", {})


def test_duplicate_registration_raises():
    reg = ToolRegistry()

    @reg.register("x", "desc")
    def x():
        return None

    with pytest.raises(ValueError):
        @reg.register("x", "desc again")
        def x2():
            return None


def test_extra_kwargs_are_filtered_not_passed():
    reg = ToolRegistry()

    @reg.register("greet", "greet someone", {"name": {"type": "string"}}, ["name"])
    def greet(name: str) -> str:
        return f"hi {name}"

    # An LLM-supplied stray kwarg must not raise a TypeError.
    result = reg.call("greet", {"name": "Rohit", "unexpected_field": "ignored"})
    assert result == "hi Rohit"


def test_schema_shape():
    reg = ToolRegistry()

    @reg.register("noop", "does nothing", {}, [])
    def noop():
        return None

    schemas = reg.schemas()
    assert schemas[0]["function"]["name"] == "noop"
    assert schemas[0]["type"] == "function"
