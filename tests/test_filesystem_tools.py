import os

import pytest


@pytest.fixture(autouse=True)
def temp_workspace(tmp_path, monkeypatch):
    """Point the agent workspace at a pytest tmp_path so tests never
    touch the real filesystem outside a throwaway directory."""
    monkeypatch.setenv("PC_AGENT_TEST_WORKSPACE", str(tmp_path))
    from core.config import reload_config

    cfg = reload_config()
    cfg.paths.workspace_dir = str(tmp_path)
    yield tmp_path
    reload_config()


def test_create_and_read_file(temp_workspace):
    from tools.filesystem import create_file, read_file

    result = create_file("notes.txt", content="hello world")
    assert result["ok"] is True
    assert os.path.exists(result["path"])

    read_result = read_file("notes.txt")
    assert read_result["ok"] is True
    assert read_result["content"] == "hello world"


def test_create_directory(temp_workspace):
    from tools.filesystem import create_file

    result = create_file("Research", is_directory=True)
    assert result["ok"] is True
    assert os.path.isdir(result["path"])


def test_read_missing_file_reports_error(temp_workspace):
    from tools.filesystem import read_file

    result = read_file("does_not_exist.txt")
    assert result["ok"] is False
    assert "not found" in result["error"].lower()


def test_rename_file(temp_workspace):
    from tools.filesystem import create_file, rename_file

    created = create_file("a.txt", content="x")
    renamed = rename_file(created["path"], "b.txt")
    assert renamed["ok"] is True
    assert renamed["path"].endswith("b.txt")


def test_delete_file(temp_workspace):
    from tools.filesystem import create_file, delete_file

    created = create_file("temp.txt", content="x")
    result = delete_file(created["path"])
    assert result["ok"] is True
    assert not os.path.exists(created["path"])
