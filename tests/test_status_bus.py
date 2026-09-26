import pytest


@pytest.fixture(autouse=True)
def temp_data_dir(tmp_path):
    from core.config import reload_config

    cfg = reload_config()
    cfg.memory.db_path = str(tmp_path / "data" / "agent_memory.sqlite3")
    yield tmp_path
    reload_config()


def test_write_and_read_status():
    from core.status_bus import write_status, read_status

    write_status(state="LISTENING", current_task="make a deck", current_application="PowerPoint")
    status = read_status()
    assert status["state"] == "LISTENING"
    assert status["current_task"] == "make a deck"
    assert status["current_application"] == "PowerPoint"
    assert status["updated_at"] is not None


def test_read_status_before_any_write():
    from core.status_bus import read_status

    status = read_status()
    assert status["state"] == "UNKNOWN"


def test_push_and_pop_commands():
    from core.status_bus import push_command, pop_commands

    push_command("pause")
    push_command("mute")
    commands = pop_commands()
    assert commands == ["pause", "mute"]


def test_pop_commands_clears_the_queue():
    from core.status_bus import push_command, pop_commands

    push_command("stop")
    first = pop_commands()
    second = pop_commands()
    assert first == ["stop"]
    assert second == []


def test_push_invalid_command_rejected():
    from core.status_bus import push_command

    with pytest.raises(ValueError):
        push_command("format_c_drive")


def test_pop_commands_on_empty_queue_returns_empty_list():
    from core.status_bus import pop_commands

    assert pop_commands() == []
