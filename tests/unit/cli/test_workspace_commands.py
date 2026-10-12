from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
import yaml

from anyagent.cli import main
from anyagent.config.agents import load_agent_catalog
from anyagent.protocol.workspace import WorkspaceDoctorReport, WorkspaceInitResult


def test_init_without_scaffold_exits(tmp_path: Path) -> None:
    with pytest.raises(SystemExit, match="anyagent.scaffold is unavailable"):
        main(["init", "--workspace", str(tmp_path)])


def test_init_maps_flags_and_prints_text(scaffold: dict[str, Any], tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    rc = main(
        [
            "init",
            "--workspace",
            str(tmp_path),
            "--agent-id",
            "worker",
            "--template",
            "coding-agent",
            "--provider",
            "anthropic",
            "--model",
            "claude-sonnet",
            "--base-url",
            "https://example.invalid/v1",
            "--tool",
            "exec",
            "--tool",
            "core.web_fetch",
            "--tool",
            "exec",
            "--with-exec",
            "--with-web-fetch",
            "--sandbox-mode",
            "local-unsafe",
            "--with-example-skill",
            "--force",
        ]
    )

    assert rc == 0
    options = scaffold["init"]
    assert options.workspace == tmp_path.resolve()
    assert options.agent_id == "worker"
    assert options.template == "coding-agent"
    assert options.provider == "anthropic"
    assert options.model == "claude-sonnet"
    assert options.base_url == "https://example.invalid/v1"
    assert options.tools == ["exec", "core.web_fetch"]
    assert options.with_exec is True
    assert options.with_web_fetch is True
    assert options.sandbox_mode == "local-unsafe"
    assert options.with_example_skill is True
    assert options.force is True
    text = capsys.readouterr().out
    assert f"initialized workspace: {tmp_path.resolve()}" in text
    assert "agent: worker" in text
    assert "created: .anyagent/agents/worker/agent.yaml" in text
    assert "next: anyagent doctor" in text
    assert not (tmp_path / ".anyagent").exists()


def test_init_json_keeps_workspace_init_result(scaffold: dict[str, Any], tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    rc = main(["init", "--workspace", str(tmp_path), "--json"])

    assert rc == 0
    payload = WorkspaceInitResult.model_validate_json(capsys.readouterr().out)
    assert payload.ok is True
    assert payload.agent_id == "main"
    assert payload.workspace == str(tmp_path.resolve())
    assert scaffold["init"].template == "basic"
    assert scaffold["init"].provider == "openai"
    assert scaffold["init"].tools == []
    assert scaffold["init"].with_exec is False


def test_init_rejects_invalid_agent_id_before_scaffold(scaffold: dict[str, Any], tmp_path: Path) -> None:
    with pytest.raises(SystemExit, match="must match"):
        main(["init", "--workspace", str(tmp_path), "--agent-id", "has space"])
    assert "init" not in scaffold


def test_init_failure_returns_nonzero(scaffold: dict[str, Any], monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    import anyagent.scaffold as scaffold_mod

    def fail(options: Any) -> WorkspaceInitResult:
        scaffold["init"] = options
        return WorkspaceInitResult(
            ok=False,
            workspace=str(options.workspace),
            agent_id=options.agent_id,
            created=[],
            skipped=["kept"],
            next="fix the workspace",
        )

    monkeypatch.setattr(scaffold_mod, "init_workspace", fail)
    rc = main(["init", "--workspace", str(tmp_path)])

    assert rc == 1
    text = capsys.readouterr().out
    assert "skipped: kept" in text
    assert "next: fix the workspace" in text


def test_add_passes_set_pairs(scaffold: dict[str, Any], tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    rc = main(
        [
            "add",
            "tool",
            "echo",
            "--workspace",
            str(tmp_path),
            "--agent-id",
            "main",
            "--force",
            "--set",
            "bin=echo",
            "--set",
            "note=a=b",
        ]
    )

    assert rc == 0
    options = scaffold["add"]
    assert options.kind == "tool"
    assert options.name == "echo"
    assert options.agent_id == "main"
    assert options.force is True
    assert options.extra == {"bin": "echo", "note": "a=b"}
    text = capsys.readouterr().out
    assert "added tool echo" in text
    assert "created: tool/echo" in text
    assert "next: wire the new component" in text


def test_add_json_dumps_scaffold_result(scaffold: dict[str, Any], tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    rc = main(["add", "skill", "demo", "--workspace", str(tmp_path), "--json"])

    assert rc == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["created"] == ["skill/demo"]
    assert payload["next_steps"] == ["wire the new component"]
    assert scaffold["add"].kind == "skill"


def test_add_rejects_set_without_equals(scaffold: dict[str, Any], tmp_path: Path) -> None:
    with pytest.raises(SystemExit, match="key=value"):
        main(["add", "plugin", "demo", "--workspace", str(tmp_path), "--set", "novalue"])
    assert "add" not in scaffold


def test_config_show_redacts_secrets_and_reports_sources(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    config_dir = tmp_path / ".anyagent"
    config_dir.mkdir()
    (config_dir / "anyagent.yaml").write_text(
        "models:\n  providers:\n    openai:\n      api_key: sk-live-secret\n",
        encoding="utf-8",
    )

    rc = main(["config", "show", "--workspace", str(tmp_path), "--json", "--sources"])

    assert rc == 0
    text = capsys.readouterr().out
    assert "sk-live-secret" not in text
    payload = json.loads(text)
    assert payload["config"]["models"]["providers"]["openai"]["api_key"] == "***"
    assert payload["sources"]["models.providers.openai.api_key"] == {"layer": "workspace", "env": None}


def test_config_show_json_is_the_redacted_document(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    config_dir = tmp_path / ".anyagent"
    config_dir.mkdir()
    (config_dir / "anyagent.yaml").write_text(
        "server:\n  api_key: sk-server-secret\n",
        encoding="utf-8",
    )

    rc = main(["config", "show", "--workspace", str(tmp_path), "--json"])

    assert rc == 0
    text = capsys.readouterr().out
    payload = json.loads(text)
    assert "sources" not in payload
    assert payload["server"]["api_key"] == "***"
    assert "sk-server-secret" not in text


def test_config_show_human_output_lists_sources_and_next_step(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    config_dir = tmp_path / ".anyagent"
    config_dir.mkdir()
    (config_dir / "anyagent.yaml").write_text(
        "models:\n  providers:\n    openai:\n      api_key: sk-live-secret\n",
        encoding="utf-8",
    )

    rc = main(["config", "show", "--workspace", str(tmp_path), "--sources"])

    assert rc == 0
    text = capsys.readouterr().out
    assert "sk-live-secret" not in text
    assert "***" in text
    assert "models.providers.openai.api_key: workspace" in text
    assert f"next: anyagent doctor --workspace {tmp_path.resolve()}" in text


def test_config_schema_prints_and_writes_files(scaffold: dict[str, Any], tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    rc = main(["config", "schema"])

    assert rc == 0
    payload = json.loads(capsys.readouterr().out)
    assert set(payload) == {"anyagent.yaml", "agent.yaml", "mcp.json"}

    out_dir = tmp_path / "schemas"
    rc = main(["config", "schema", "--out", str(out_dir)])
    assert rc == 0
    written = capsys.readouterr().out
    for name in ("anyagent.yaml", "agent.yaml", "mcp.json"):
        path = out_dir / f"{name}.schema.json"
        assert path.is_file()
        assert str(path) in written
        assert json.loads(path.read_text(encoding="utf-8"))["title"]


def test_doctor_accepts_empty_workspace_with_builtin_main(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    rc = main(["doctor", "--workspace", str(tmp_path), "--json"])

    assert rc == 0
    payload = WorkspaceDoctorReport.model_validate_json(capsys.readouterr().out)
    assert payload.ok is True
    codes = {item.code for item in payload.findings}
    assert "builtin_main_agent" in codes
    assert "missing_provider_api_key" in codes
    assert "agent_no_tools" in codes


def test_doctor_human_output_includes_next_step(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    rc = main(["doctor", "--workspace", str(tmp_path)])

    assert rc == 0
    text = capsys.readouterr().out
    assert "anyagent doctor: ok" in text
    assert "[warning] missing_provider_api_key:" in text
    assert f"next: anyagent serve --workspace {tmp_path.resolve()}" in text


def test_doctor_reports_model_provider_origin(monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test-value")

    rc = main(["doctor", "--workspace", str(tmp_path), "--json"])

    assert rc == 0
    text = capsys.readouterr().out
    assert "sk-test-value" not in text
    payload = WorkspaceDoctorReport.model_validate_json(text)
    assert payload.ok is True
    message = next(item.message for item in payload.findings if item.code == "model_provider")
    assert "provider=openai" in message
    assert "api_key_from=default (${OPENAI_API_KEY})" in message
    assert "default_from=default" in message
    assert "model_from=default" in message
    assert not any(item.code == "missing_provider_api_key" for item in payload.findings)


def test_doctor_reports_config_load_error_with_path(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    path = tmp_path / ".anyagent" / "anyagent.yaml"
    path.parent.mkdir(parents=True)
    path.write_text("models: [\n", encoding="utf-8")

    rc = main(["doctor", "--workspace", str(tmp_path), "--json"])

    assert rc == 1
    payload = WorkspaceDoctorReport.model_validate_json(capsys.readouterr().out)
    assert payload.ok is False
    finding = next(item for item in payload.findings if item.code == "config_load_error")
    assert finding.level == "error"
    assert str(path.resolve()) in finding.message


def test_doctor_warns_on_unknown_tools_and_accepts_known_names(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    agent_dir = tmp_path / ".anyagent" / "agents" / "main"
    agent_dir.mkdir(parents=True)
    (agent_dir / "AGENTS.md").write_text("main\n", encoding="utf-8")
    (agent_dir / "agent.yaml").write_text(
        yaml.safe_dump(
            {
                "exposed": True,
                "tools": {
                    "requested_tool_names": [
                        "not.a.tool",
                        "exec",
                        "core.web_fetch",
                        "repo.search",
                        "mcp.demo.search",
                        "mcp.other.search",
                        "mcp.demo.*",
                        "app.echo",
                    ],
                    "cli": [{"name": "repo.search", "cwd": "repo"}],
                },
                "skills": {"default_selected": []},
                "sandbox": {"mode": "disabled"},
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )
    (agent_dir / "mcp.json").write_text(
        json.dumps({"mcpServers": {"demo": {"command": "/bin/true"}}}),
        encoding="utf-8",
    )
    plugin_dir = tmp_path / "plugins" / "echo"
    plugin_dir.mkdir(parents=True)
    (plugin_dir / "plugin.json").write_text(
        json.dumps({"plugin_id": "echo", "tools": ["app.echo"]}),
        encoding="utf-8",
    )

    rc = main(["doctor", "--workspace", str(tmp_path), "--json"])

    assert rc == 0
    payload = WorkspaceDoctorReport.model_validate_json(capsys.readouterr().out)
    unknown = [item.message for item in payload.findings if item.code == "unknown_tool"]
    assert unknown == [
        "agent main requests unknown tool: not.a.tool",
        "agent main requests unknown tool: mcp.other.search",
    ]
    assert all(item.level == "warning" for item in payload.findings if item.code == "unknown_tool")


def test_doctor_reports_cli_profile_warnings_and_conflicts(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    agents_root = tmp_path / ".anyagent" / "agents"
    main_dir = agents_root / "main"
    worker_dir = agents_root / "worker"
    main_dir.mkdir(parents=True)
    worker_dir.mkdir(parents=True)
    (main_dir / "AGENTS.md").write_text("main\n", encoding="utf-8")
    (worker_dir / "AGENTS.md").write_text("worker\n", encoding="utf-8")
    (main_dir / "agent.yaml").write_text(
        "\n".join(
            [
                "exposed: true",
                "tools:",
                "  requested_tool_names: []",
                "  cli:",
                "    - name: app.demo",
                "      cwd: repo",
                "      env:",
                "        inherit: all",
                "        ignore_default_excludes: true",
                "skills:",
                "  default_selected: []",
                "sandbox:",
                "  mode: local-unsafe",
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    (worker_dir / "agent.yaml").write_text(
        "\n".join(
            [
                "exposed: false",
                "tools:",
                "  requested_tool_names: []",
                "  cli:",
                "    - name: app.demo",
                "      cwd: other-repo",
                "skills:",
                "  default_selected: []",
                "sandbox:",
                "  mode: disabled",
            ]
        )
        + "\n",
        encoding="utf-8",
    )

    rc = main(["doctor", "--workspace", str(tmp_path), "--json"])

    assert rc == 1
    payload = WorkspaceDoctorReport.model_validate_json(capsys.readouterr().out)
    codes = {item.code for item in payload.findings}
    assert "cli_profile_local_unsafe_exposed" in codes
    assert "cli_profile_inherit_all_without_filter" in codes
    assert "cli_profile_conflict" in codes


def test_doctor_reports_cli_profile_schema_errors(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    agent_dir = tmp_path / ".anyagent" / "agents" / "main"
    agent_dir.mkdir(parents=True)
    (agent_dir / "AGENTS.md").write_text("main\n", encoding="utf-8")
    (agent_dir / "agent.yaml").write_text(
        "\n".join(
            [
                "exposed: true",
                "tools:",
                "  requested_tool_names: []",
                "  cli:",
                "    - name: app.demo",
                "      cwd: repo",
                "      env:",
                "        set:",
                "          API_KEY: should-fail",
                "skills:",
                "  default_selected: []",
                "sandbox:",
                "  mode: local-unsafe",
            ]
        )
        + "\n",
        encoding="utf-8",
    )

    rc = main(["doctor", "--workspace", str(tmp_path), "--json"])

    assert rc == 1
    payload = WorkspaceDoctorReport.model_validate_json(capsys.readouterr().out)
    finding = next(item for item in payload.findings if item.code == "agent_catalog_invalid")
    assert "env.set contains sensitive key" in finding.message


def test_agent_list_prints_workspace_catalog(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    _write_agent(
        tmp_path,
        "main",
        exposed=True,
        sandbox="disabled",
        tools=["exec"],
        spawn=["worker"],
        model="fast",
    )
    worker_dir = _write_agent(
        tmp_path,
        "worker",
        exposed=False,
        sandbox="local-unsafe",
        tools=["core.web_fetch"],
        spawn=[],
        model=None,
    )

    rc = main(["agent", "list", "--workspace", str(tmp_path), "--json"])

    assert rc == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["workspace"] == str(tmp_path.resolve())
    assert payload["agents_root"] == str((tmp_path / ".anyagent" / "agents").resolve())
    assert [item["agent_id"] for item in payload["agents"]] == ["main", "worker"]
    worker = next(item for item in payload["agents"] if item["agent_id"] == "worker")
    assert worker["exposed"] is False
    assert worker["sandbox_mode"] == "local-unsafe"
    assert worker["model_default"] is None
    assert worker["requested_tool_names"] == ["core.web_fetch"]
    assert worker["default_selected_skills"] == []
    assert worker["spawn_allow_agent_ids"] == []
    assert worker["path"] == str(worker_dir.resolve())


def test_agent_catalog_ignores_legacy_agents_directory(tmp_path: Path) -> None:
    legacy_agent_dir = tmp_path / ".agents" / "agents" / "main"
    legacy_agent_dir.mkdir(parents=True)
    (legacy_agent_dir / "AGENTS.md").write_text("legacy prompt\n", encoding="utf-8")
    (legacy_agent_dir / "agent.yaml").write_text(
        "exposed: true\ntools:\n  requested_tool_names: []\n",
        encoding="utf-8",
    )

    catalog = load_agent_catalog(workspace_dir=tmp_path)

    pack = catalog.get("main")
    assert pack is not None
    assert pack.builtin is True
    assert pack.agents_md_text != "legacy prompt\n"


def _write_agent(
    root: Path,
    agent_id: str,
    *,
    exposed: bool,
    sandbox: str,
    tools: list[str],
    spawn: list[str],
    model: str | None,
) -> Path:
    directory = root / ".anyagent" / "agents" / agent_id
    directory.mkdir(parents=True)
    (directory / "AGENTS.md").write_text(f"{agent_id}\n", encoding="utf-8")
    document: dict[str, Any] = {
        "exposed": exposed,
        "tools": {"requested_tool_names": tools},
        "skills": {"default_selected": []},
        "sandbox": {"mode": sandbox},
        "multiagent": {"spawn_allow_agent_ids": spawn},
    }
    if model is not None:
        document["model"] = {"default": model}
    (directory / "agent.yaml").write_text(yaml.safe_dump(document, sort_keys=False), encoding="utf-8")
    return directory
