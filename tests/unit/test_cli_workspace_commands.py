from __future__ import annotations

from anyagent.cli import main
from anyagent.protocol.workspace import WorkspaceDoctorReport, WorkspaceInitResult


def test_init_creates_minimal_workspace_with_example_skill(tmp_path, capsys) -> None:
    rc = main(["init", "--workspace", str(tmp_path), "--with-example-skill"])

    assert rc == 0
    payload = WorkspaceInitResult.model_validate_json(capsys.readouterr().out)
    assert payload.ok is True
    assert (tmp_path / ".agents" / "agents" / "main" / "agent.yaml").is_file()
    assert (tmp_path / ".agents" / "agents" / "main" / "AGENTS.md").is_file()
    assert (tmp_path / ".agents" / "agents" / "main" / "mcp.json").is_file()
    assert (tmp_path / ".agents" / "skills" / "example-skill" / "SKILL.md").is_file()


def test_doctor_accepts_initialized_workspace(tmp_path, capsys) -> None:
    assert main(["init", "--workspace", str(tmp_path), "--with-example-skill"]) == 0
    capsys.readouterr()

    rc = main(["doctor", "--workspace", str(tmp_path), "--json"])

    assert rc == 0
    payload = WorkspaceDoctorReport.model_validate_json(capsys.readouterr().out)
    assert payload.ok is True
    assert any(item.code == "agent_loaded" for item in payload.findings)


def test_doctor_rejects_missing_workspace(tmp_path, capsys) -> None:
    rc = main(["doctor", "--workspace", str(tmp_path), "--json"])

    assert rc == 1
    payload = WorkspaceDoctorReport.model_validate_json(capsys.readouterr().out)
    assert payload.ok is False
    assert payload.findings[0].code == "missing_agent_root"
