import pytest


@pytest.fixture(autouse=True)
def temp_env(tmp_path, monkeypatch):
    from core.config import reload_config

    cfg = reload_config()
    cfg.memory.db_path = str(tmp_path / "test_memory.sqlite3")
    yield tmp_path
    reload_config()


def test_register_and_open_known_project(tmp_path, monkeypatch):
    from apps.vscode import register_project, open_project

    project_dir = tmp_path / "VAYU"
    project_dir.mkdir()

    reg_result = register_project("VAYU", str(project_dir))
    assert reg_result["ok"] is True

    launched = {}

    class FakePopen:
        def __init__(self, args):
            launched["args"] = args

    monkeypatch.setattr("subprocess.Popen", FakePopen)

    open_result = open_project("VAYU")
    assert open_result["ok"] is True
    assert str(project_dir.resolve()) in open_result["path"]
    assert launched["args"][0] == "code"


def test_register_nonexistent_path_fails():
    from apps.vscode import register_project

    result = register_project("Ghost", "/this/does/not/exist")
    assert result["ok"] is False


def test_open_unknown_project_lists_known_ones(tmp_path):
    from apps.vscode import register_project, open_project

    project_dir = tmp_path / "Known"
    project_dir.mkdir()
    register_project("Known", str(project_dir))

    result = open_project("TotallyUnknownProject")
    assert result["ok"] is False
    assert "known" in result["error"].lower()


def test_run_in_project_uses_project_cwd(tmp_path, monkeypatch):
    from apps.vscode import register_project, run_in_project

    project_dir = tmp_path / "Proj"
    project_dir.mkdir()
    register_project("Proj", str(project_dir))

    captured = {}

    def fake_run_command(command, cwd=None, timeout_s=60):
        captured["cwd"] = cwd
        return {"ok": True, "stdout": "", "stderr": ""}

    monkeypatch.setattr("apps.vscode.run_command", fake_run_command)

    result = run_in_project("Proj", "echo hi")
    assert result["ok"] is True
    assert captured["cwd"] == str(project_dir.resolve())
