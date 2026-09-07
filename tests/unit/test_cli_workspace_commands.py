from __future__ import annotations

from pathlib import Path
import json

import pytest
import yaml

from anyagent.agent_packs import AgentPackError, load_agent_catalog
from anyagent.cli import main
from anyagent.model_config import WorkspaceModelsConfig
from anyagent.protocol.admin_storage import StorageHealthResponse
from anyagent.protocol.plugins import PluginCatalogResponse
from anyagent.protocol.workspace import WorkspaceDoctorReport, WorkspaceInitResult


def test_init_creates_minimal_workspace_with_example_skill(tmp_path, capsys) -> None:
    rc = main(["init", "--workspace", str(tmp_path), "--with-example-skill"])

    assert rc == 0
    payload = WorkspaceInitResult.model_validate_json(capsys.readouterr().out)
    assert payload.ok is True
    assert (tmp_path / ".anyagent" / "agents" / "main" / "agent.yaml").is_file()
    assert (tmp_path / ".anyagent" / "agents" / "main" / "AGENTS.md").is_file()
    assert (tmp_path / ".anyagent" / "agents" / "main" / "mcp.json").is_file()
    assert (tmp_path / ".anyagent" / "skills" / "example-skill" / "SKILL.md").is_file()
    assert (tmp_path / "plugins" / "demo" / "plugin.json").is_file()
    assert (tmp_path / "plugins" / "demo" / "plugin.py").is_file()
    assert (tmp_path / "plugins" / "demo" / "README.md").is_file()
    assert (tmp_path / "plugins" / "demo" / "schemas" / "config.schema.json").is_file()
    assert (tmp_path / "plugins" / "demo" / "tests" / "smoke.py").is_file()
    agent_yaml = (tmp_path / ".anyagent" / "agents" / "main" / "agent.yaml").read_text(encoding="utf-8")
    agent_config = yaml.safe_load(agent_yaml)
    plugin_py = (tmp_path / "plugins" / "demo" / "plugin.py").read_text(encoding="utf-8")
    plugin_readme = (tmp_path / "plugins" / "demo" / "README.md").read_text(encoding="utf-8")
    assert "app.demo.echo" not in agent_config["tools"]["requested_tool_names"]
    assert "intentionally inactive by" in plugin_py
    assert "not visible to agents by default" in plugin_readme
    assert (tmp_path / ".gitignore").is_file()
    gitignore = (tmp_path / ".gitignore").read_text(encoding="utf-8")
    assert ".run/\n" in gitignore
    assert ".runs/\n" in gitignore


def test_init_coding_template_enables_exec_sandbox(tmp_path, capsys) -> None:
    rc = main(["init", "--workspace", str(tmp_path), "--template", "coding-agent"])

    assert rc == 0
    WorkspaceInitResult.model_validate_json(capsys.readouterr().out)
    agent_yaml = (tmp_path / ".anyagent" / "agents" / "main" / "agent.yaml").read_text(encoding="utf-8")
    assert "    - exec\n" in agent_yaml
    assert "  mode: local-unsafe\n" in agent_yaml
    assert "Coding Agent" in (tmp_path / ".anyagent" / "agents" / "main" / "AGENTS.md").read_text(encoding="utf-8")


def test_init_multi_agent_template_creates_independent_agent_packs(tmp_path, capsys) -> None:
    rc = main(["init", "--workspace", str(tmp_path), "--template", "multi-agent-team"])

    assert rc == 0
    WorkspaceInitResult.model_validate_json(capsys.readouterr().out)
    assert (tmp_path / ".anyagent" / "agents" / "main").is_dir()
    assert (tmp_path / ".anyagent" / "agents" / "researcher").is_dir()
    assert (tmp_path / ".anyagent" / "agents" / "coder").is_dir()
    main_yaml = (tmp_path / ".anyagent" / "agents" / "main" / "agent.yaml").read_text(encoding="utf-8")
    coder_yaml = (tmp_path / ".anyagent" / "agents" / "coder" / "agent.yaml").read_text(encoding="utf-8")
    researcher_yaml = (tmp_path / ".anyagent" / "agents" / "researcher" / "agent.yaml").read_text(encoding="utf-8")
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


def test_agent_list_prints_workspace_catalog(tmp_path, capsys) -> None:
    assert main(["init", "--workspace", str(tmp_path), "--agent-id", "worker", "--template", "coding-agent"]) == 0
    capsys.readouterr()

    rc = main(["agent", "list", "--workspace", str(tmp_path), "--json"])

    assert rc == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["workspace"] == str(tmp_path)
    assert [item["agent_id"] for item in payload["agents"]] == ["main", "worker"]
    worker = next(item for item in payload["agents"] if item["agent_id"] == "worker")
    assert worker["exposed"] is True
    assert worker["sandbox_mode"] == "local-unsafe"
    assert worker["requested_tool_names"] == ["exec"]


def test_dev_serve_uses_local_defaults_and_prints_urls(monkeypatch, tmp_path, capsys) -> None:
    assert main(["init", "--workspace", str(tmp_path), "--with-example-skill"]) == 0
    capsys.readouterr()
    calls: dict[str, object] = {}

    def fake_create_app(**kwargs):
        calls["app_kwargs"] = kwargs
        return object()

    def fake_uvicorn_run(app, *, host, port, log_level):
        calls["uvicorn"] = {"app": app, "host": host, "port": port, "log_level": log_level}

    monkeypatch.delenv("API_KEY", raising=False)
    monkeypatch.delenv("ADMIN_API_KEY", raising=False)
    monkeypatch.setattr("anyagent.cli.create_app", fake_create_app)
    monkeypatch.setattr("anyagent.cli.uvicorn.run", fake_uvicorn_run)

    rc = main(["dev", "--workspace", str(tmp_path), "--storage-profile", "postgres"])

    assert rc == 0
    app_kwargs = calls["app_kwargs"]
    assert isinstance(app_kwargs, dict)
    assert app_kwargs["workspace_dir"] == str(tmp_path)
    assert app_kwargs["api_key"] == "anyagent-dev-key"
    assert app_kwargs["admin_api_key"] == "anyagent-dev-key"
    assert app_kwargs["storage_profile"] == "postgres"
    assert app_kwargs["enable_studio"] is True
    uvicorn_call = calls["uvicorn"]
    assert isinstance(uvicorn_call, dict)
    assert uvicorn_call["host"] == "127.0.0.1"
    assert uvicorn_call["port"] == 8787
    banner = json.loads(capsys.readouterr().out)
    assert banner["api"] == "http://127.0.0.1:8787/v1"
    assert banner["studio"] == "http://127.0.0.1:8787/studio/"
    assert banner["agents_exposed"] == ["main"]


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
            "--with-web-fetch",
            "--with-exec",
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
    agent_yaml = (tmp_path / ".anyagent" / "agents" / "delivery-agent" / "agent.yaml").read_text(encoding="utf-8")
    assert "model:\n  default: fast\n" in agent_yaml
    assert "    - core.web_fetch\n" in agent_yaml
    assert "    - exec\n" in agent_yaml
    assert "  mode: local-unsafe\n" in agent_yaml
    main_yaml = (tmp_path / ".anyagent" / "agents" / "main" / "agent.yaml").read_text(encoding="utf-8")
    assert "model:\n  default: fast\n" in main_yaml
    assert "    - delivery-agent\n" in main_yaml
    assert "    - core.web_fetch\n" in main_yaml
    assert "    - exec\n" in main_yaml
    assert (tmp_path / "plugins" / "demo" / "plugin.json").is_file()
    assert (tmp_path / "plugins" / "demo" / "plugin.py").is_file()
    assert "app.demo.echo" not in yaml.safe_load(agent_yaml)["tools"]["requested_tool_names"]
    assert (tmp_path / ".gitignore").read_text(encoding="utf-8").startswith(".venv/\n")


def test_init_non_main_agent_creates_default_main_entrypoint(tmp_path, capsys) -> None:
    rc = main(["init", "--workspace", str(tmp_path), "--agent-id", "reddit-collector", "--template", "research-agent"])

    assert rc == 0
    WorkspaceInitResult.model_validate_json(capsys.readouterr().out)
    assert (tmp_path / ".anyagent" / "agents" / "reddit-collector" / "agent.yaml").is_file()
    main_yaml = (tmp_path / ".anyagent" / "agents" / "main" / "agent.yaml").read_text(encoding="utf-8")
    main_instructions = (tmp_path / ".anyagent" / "agents" / "main" / "AGENTS.md").read_text(encoding="utf-8")
    assert "    - reddit-collector\n" in main_yaml
    assert "reddit-collector" in main_instructions


def test_doctor_rejects_missing_workspace(tmp_path, capsys) -> None:
    rc = main(["doctor", "--workspace", str(tmp_path), "--json"])

    assert rc == 1
    payload = WorkspaceDoctorReport.model_validate_json(capsys.readouterr().out)
    assert payload.ok is False
    assert payload.findings[0].code == "missing_agent_root"


def test_doctor_reports_cli_profile_warnings_and_conflicts(tmp_path, capsys) -> None:
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


def test_doctor_reports_cli_profile_schema_errors(tmp_path, capsys) -> None:
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
    assert payload.findings[0].code == "agent_catalog_invalid"
    assert "env.set contains sensitive key" in payload.findings[0].message


def test_agent_catalog_ignores_legacy_agents_directory(tmp_path: Path) -> None:
    legacy_agent_dir = tmp_path / ".agents" / "agents" / "main"
    legacy_agent_dir.mkdir(parents=True)
    (legacy_agent_dir / "AGENTS.md").write_text("legacy prompt\n", encoding="utf-8")
    (legacy_agent_dir / "agent.yaml").write_text(
        "exposed: true\ntools:\n  requested_tool_names: []\n",
        encoding="utf-8",
    )

    with pytest.raises(AgentPackError, match=r"missing agent packs root: .*\.anyagent/agents"):
        load_agent_catalog(workspace_dir=tmp_path)


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


def test_storage_health_cli_reads_typed_admin_api(monkeypatch, capsys) -> None:
    calls = []

    class _Response:
        status_code = 200
        text = "{}"

        def json(self):
            return {
                "ok": True,
                "storage_mode": "none",
                "backends": {
                    "event_store": "memory",
                    "run_store": "memory",
                    "session_store": "memory",
                    "session_lock": "local",
                },
                "retention_s": {"events": 86400, "runs": 86400, "sessions": 86400},
                "stores": {"events": {"type": "memory", "layers": ["process"]}},
                "capabilities": {
                    "events": {
                        "tier": "reference",
                        "long_term_owner": "anyagent",
                        "source_of_truth": "packages/anyagent/src/anyagent/storage",
                        "requires_services": [],
                        "restart_recovery": False,
                        "cross_instance": False,
                        "supports_replay": True,
                        "supports_live_tail": True,
                    }
                },
                "postgres": {"configured": False, "reachable": None, "schema": None},
                "redis": {"configured": False, "reachable": None, "namespace": None},
            }

    def fake_get(url, *, headers, timeout):
        calls.append({"url": url, "headers": headers, "timeout": timeout})
        return _Response()

    monkeypatch.setattr("anyagent.cli.httpx.get", fake_get)

    rc = main(
        [
            "storage",
            "health",
            "--admin-url",
            "http://agent-api.local",
            "--admin-key",
            "admin-key",
        ]
    )

    assert rc == 0
    assert calls == [
        {
            "url": "http://agent-api.local/admin/storage/health",
            "headers": {"Authorization": "Bearer admin-key"},
            "timeout": 15.0,
        }
    ]
    payload = StorageHealthResponse.model_validate(json.loads(capsys.readouterr().out))
    assert payload.ok is True
    assert payload.backends.event_store == "memory"
    assert payload.postgres.configured is False


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
