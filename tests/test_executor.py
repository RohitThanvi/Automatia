from core.executor import Executor, ExecutionResult, FailureCategory, _categorize
from core.planner import ToolCall
from core.tool_registry import ToolRegistry
from security.confirmation import Confirmer


def test_categorize_not_found():
    assert _categorize("File not found: x.txt") == FailureCategory.NOT_FOUND


def test_categorize_timeout():
    assert _categorize("Command timed out after 30s") == FailureCategory.TIMEOUT


def test_categorize_permission():
    assert _categorize("Permission denied") == FailureCategory.PERMISSION


def test_categorize_unavailable():
    assert _categorize("Connection refused") == FailureCategory.UNAVAILABLE


def test_categorize_unknown_falls_back():
    assert _categorize("something bizarre happened") == FailureCategory.UNKNOWN


class _AlwaysApprove(Confirmer):
    def confirm(self, message: str) -> bool:
        return True


def test_permission_failure_is_not_retried(monkeypatch):
    import core.executor as executor_module

    call_count = {"n": 0}

    def flaky_tool():
        call_count["n"] += 1
        return {"ok": False, "error": "Permission denied"}

    reg = ToolRegistry()
    reg.register("flaky", "desc", {}, [])(flaky_tool)
    monkeypatch.setattr(executor_module, "registry", reg)

    ex = Executor(_AlwaysApprove(), auto_approve_low_risk=True)
    result = ex.execute_with_retry(ToolCall(name="flaky", args={}), max_retries=3)

    assert result.ok is False
    assert result.category == FailureCategory.PERMISSION
    assert call_count["n"] == 1  # must NOT have retried


def test_not_found_failure_is_retried_up_to_limit(monkeypatch):
    import core.executor as executor_module

    call_count = {"n": 0}

    def flaky_tool():
        call_count["n"] += 1
        return {"ok": False, "error": "Element not found"}

    reg = ToolRegistry()
    reg.register("flaky", "desc", {}, [])(flaky_tool)
    monkeypatch.setattr(executor_module, "registry", reg)

    ex = Executor(_AlwaysApprove(), auto_approve_low_risk=True)
    result = ex.execute_with_retry(ToolCall(name="flaky", args={}), max_retries=3)

    assert result.ok is False
    assert call_count["n"] == 3  # retried up to the limit
