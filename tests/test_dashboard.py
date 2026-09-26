import pytest
from fastapi.testclient import TestClient


@pytest.fixture(autouse=True)
def temp_data_dir(tmp_path):
    from core.config import reload_config

    cfg = reload_config()
    cfg.memory.db_path = str(tmp_path / "data" / "agent_memory.sqlite3")
    yield tmp_path
    reload_config()


@pytest.fixture
def client():
    from dashboard.server import app

    return TestClient(app)


def test_index_serves_html(client):
    response = client.get("/")
    assert response.status_code == 200
    assert "PC Agent" in response.text


def test_status_before_agent_running(client):
    response = client.get("/api/status")
    assert response.status_code == 200
    assert response.json()["state"] == "UNKNOWN"


def test_status_reflects_written_state(client):
    from core.status_bus import write_status

    write_status(state="EXECUTING", current_task="open chrome")
    response = client.get("/api/status")
    body = response.json()
    assert body["state"] == "EXECUTING"
    assert body["current_task"] == "open chrome"


def test_valid_command_is_queued(client):
    from core.status_bus import pop_commands

    response = client.post("/api/command/pause")
    assert response.status_code == 200
    assert response.json()["ok"] is True
    assert pop_commands() == ["pause"]


def test_invalid_command_rejected(client):
    response = client.post("/api/command/delete_everything")
    assert response.status_code == 400
    assert response.json()["ok"] is False
