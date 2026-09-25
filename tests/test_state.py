import pytest

from core.state import AgentState, AgentStateMachine, InvalidTransition


def test_happy_path_transitions():
    sm = AgentStateMachine()
    sequence = [
        AgentState.WAKE,
        AgentState.LISTENING,
        AgentState.TRANSCRIBING,
        AgentState.PLANNING,
        AgentState.EXECUTING,
        AgentState.OBSERVING,
        AgentState.VERIFYING,
        AgentState.RESPONDING,
        AgentState.LISTENING,
    ]
    for state in sequence:
        sm.transition(state)
    assert sm.state == AgentState.LISTENING


def test_illegal_transition_raises():
    sm = AgentStateMachine()
    with pytest.raises(InvalidTransition):
        sm.transition(AgentState.EXECUTING)  # can't jump straight from IDLE


def test_force_idle_always_works():
    sm = AgentStateMachine()
    sm.transition(AgentState.WAKE)
    sm.transition(AgentState.LISTENING)
    sm.task.raw_command = "do something"
    sm.force_idle()
    assert sm.state == AgentState.IDLE
    assert sm.task.raw_command is None  # task memory resets on IDLE


def test_task_memory_advance():
    sm = AgentStateMachine()
    from core.state import PlanStep

    sm.task.plan = [PlanStep(description="a"), PlanStep(description="b")]
    assert sm.task.current_step().description == "a"
    sm.task.advance()
    assert sm.task.current_step().description == "b"
    sm.task.advance()
    assert sm.task.is_complete()
