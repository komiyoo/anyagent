from __future__ import annotations

from pathlib import Path
import json

import yaml

from anyagent.cli import main
from anyagent.model_config import WorkspaceModelsConfig
from anyagent.protocol.plugins import PluginCatalogResponse
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


def test_init_coding_template_enables_exec_sandbox(tmp_path, capsys) -> None:
    rc = main(["init", "--workspace", str(tmp_path), "--template", "coding-agent"])

    assert rc == 0
    WorkspaceInitResult.model_validate_json(capsys.readouterr().out)
    agent_yaml = (tmp_path / ".agents" / "agents" / "main" / "agent.yaml").read_text(encoding="utf-8")
    assert "    - exec\n" in agent_yaml
    assert "  mode: local-unsafe\n" in agent_yaml
    assert "Coding Agent" in (tmp_path / ".agents" / "agents" / "main" / "AGENTS.md").read_text(encoding="utf-8")


def test_init_multi_agent_template_creates_independent_agent_packs(tmp_path, capsys) -> None:
    rc = main(["init", "--workspace", str(tmp_path), "--template", "multi-agent-team"])

    assert rc == 0
    WorkspaceInitResult.model_validate_json(capsys.readouterr().out)
    assert (tmp_path / ".agents" / "agents" / "main").is_dir()
    assert (tmp_path / ".agents" / "agents" / "researcher").is_dir()
    assert (tmp_path / ".agents" / "agents" / "coder").is_dir()
    main_yaml = (tmp_path / ".agents" / "agents" / "main" / "agent.yaml").read_text(encoding="utf-8")
    coder_yaml = (tmp_path / ".agents" / "agents" / "coder" / "agent.yaml").read_text(encoding="utf-8")
    researcher_yaml = (tmp_path / ".agents" / "agents" / "researcher" / "agent.yaml").read_text(encoding="utf-8")
    assert "    - researcher\n" in main_yaml
    assert "    - coder\n" in main_yaml
    assert "    - exec\n" in coder_yaml
    assert "    - core.web_fetch\n" in researcher_yaml


def test_doctor_accepts_initialized_workspace(tmp_path, capsys) -> None:
    assert main(["init", "--workspace", str(tmp_path), "--with-example-skill"]) == 0
    capsys.readouterr()

    rc = main(["doctor", "--workspace", str(tmp_path), "--json"])

    assert rc == 0
    payload = WorkspaceDoctorReport.model_validate_json(capsys.readouterr().out)
    assert payload.ok is True
    assert any(item.code == "agent_loaded" for item in payload.findings)


def test_config_init_creates_models_config_and_agent_selection(tmp_path, capsys) -> None:
    rc = main(
        [
            "config",
            "init",
            "--workspace",
            str(tmp_path),
            "--agent-id",
            "delivery-agent",
            "--model-alias",
            "fast",
            "--model",
            "gpt-4.1-mini",
            "--provider",
            "openai",
        ]
    )

    assert rc == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["ok"] is True
    models = WorkspaceModelsConfig.model_validate(
        yaml.safe_load((tmp_path / "models.yaml").read_text(encoding="utf-8"))
    )
    assert models.default_model == "fast"
    assert models.models["fast"].model == "gpt-4.1-mini"
    agent_yaml = (tmp_path / ".agents" / "agents" / "delivery-agent" / "agent.yaml").read_text(encoding="utf-8")
    assert "model:\n  default: fast\n" in agent_yaml


def test_doctor_rejects_missing_workspace(tmp_path, capsys) -> None:
    rc = main(["doctor", "--workspace", str(tmp_path), "--json"])

    assert rc == 1
    payload = WorkspaceDoctorReport.model_validate_json(capsys.readouterr().out)
    assert payload.ok is False
    assert payload.findings[0].code == "missing_agent_root"


def test_plugin_catalog_cli_reads_admin_api(monkeypatch, capsys) -> None:
    calls = []

    class _Response:
        status_code = 200
        text = "{}"

        def json(self):
            return {
                "plugin_roots": ["/workspace/plugins"],
                "loaded": [
                    {
                        "plugin_id": "demo",
                        "description": "Demo connector.",
                        "channels": ["demo"],
                        "plugin_dir": "/workspace/plugins/demo",
                        "entrypoint": "plugin.py:register",
                        "tools": [
                            {
                                "name": "demo.echo",
                                "category": "channel",
                                "kind": "command",
                                "description": "Echo text.",
                            }
                        ],
                        "cite": {
                            "manifest": "/workspace/plugins/demo/plugin.json",
                            "entrypoint": "/workspace/plugins/demo/plugin.py",
                        },
                        "docs": ["/workspace/plugins/demo/README.md"],
                        "schemas": ["/workspace/plugins/demo/schemas/config.schema.json"],
                        "tests": ["/workspace/plugins/demo/tests/smoke.py"],
                    }
                ],
                "errors": [],
            }

    def fake_get(url, *, headers, timeout):
        calls.append({"url": url, "headers": headers, "timeout": timeout})
        return _Response()

    monkeypatch.setattr("anyagent.cli.httpx.get", fake_get)

    rc = main(
        [
            "plugin",
            "catalog",
            "--admin-url",
            "http://tool-runtime.local",
            "--admin-key",
            "admin-key",
        ]
    )

    assert rc == 0
    assert calls == [
        {
            "url": "http://tool-runtime.local/admin/plugins/catalog",
            "headers": {"Authorization": "Bearer admin-key"},
            "timeout": 15.0,
        }
    ]
    payload = PluginCatalogResponse.model_validate(json.loads(capsys.readouterr().out))
    assert payload.plugin_roots == ["/workspace/plugins"]
    assert payload.loaded[0].plugin_id == "demo"
    assert payload.loaded[0].tools[0].name == "demo.echo"
    assert payload.loaded[0].docs == ["/workspace/plugins/demo/README.md"]


def test_agent_api_serve_cli_builds_core_distributed_app(monkeypatch, tmp_path: Path) -> None:
    calls: dict[str, object] = {}

    def fake_create_distributed_agent_app(**kwargs):
        calls["app_kwargs"] = kwargs
        return object()

    def fake_uvicorn_run(app, *, host, port, log_level):
        calls["uvicorn"] = {"app": app, "host": host, "port": port, "log_level": log_level}

    monkeypatch.setenv("TOOL_RUNTIME_INTERNAL_KEY", "env-internal-key")
    monkeypatch.setenv("TOOL_RUNTIME_BASE_URL", "http://tool-runtime.local")
    monkeypatch.setenv("MANIFEST_CACHE_TTL_SECONDS", "12.5")
    monkeypatch.setenv("STORAGE_MODE", "none")
    monkeypatch.setattr("anyagent.cli.create_distributed_agent_app", fake_create_distributed_agent_app)
    monkeypatch.setattr("anyagent.cli.uvicorn.run", fake_uvicorn_run)

    rc = main(
        [
            "agent-api",
            "serve",
            "--workspace",
            str(tmp_path),
            "--host",
            "0.0.0.0",
            "--port",
            "9999",
            "--api-key",
            "agent-key",
        ]
    )

    assert rc == 0
    app_kwargs = calls["app_kwargs"]
    assert isinstance(app_kwargs, dict)
    assert app_kwargs["api_key"] == "agent-key"
    assert app_kwargs["enable_keyed_serialization"] is True
    runtime_config = app_kwargs["runtime_config"]
    assert runtime_config.workspace_dir == str(tmp_path)
    assert runtime_config.tool_runtime_base_url == "http://tool-runtime.local"
    assert runtime_config.tool_runtime_internal_key == "env-internal-key"
    assert runtime_config.manifest_cache_ttl_seconds == 12.5
    uvicorn_call = calls["uvicorn"]
    assert isinstance(uvicorn_call, dict)
    assert uvicorn_call["host"] == "0.0.0.0"
    assert uvicorn_call["port"] == 9999
