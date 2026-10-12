from __future__ import annotations

import asyncio
import importlib.util
import json
from pathlib import Path

import pytest
import yaml

from anyagent.config import load_agent_catalog, load_effective_config
from anyagent.plugins import load_plugins_from_roots
from anyagent.scaffold import AddOptions, InitOptions, ScaffoldError, add_component, init_workspace
from anyagent.skills.loader import load_skill_package
from anyagent.tool_runtime.plugins import ToolRuntimePluginAPI
from anyagent.tool_runtime.registry import ToolRegistry


def _isolate(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> dict[str, str]:
    system = tmp_path / "system-config"
    user = tmp_path / "user-config"
    system.mkdir()
    user.mkdir()
    monkeypatch.setenv("SYSTEM_CONFIG_DIR", str(system))
    monkeypatch.setenv("USER_CONFIG_DIR", str(user))
    return {"SYSTEM_CONFIG_DIR": str(system), "USER_CONFIG_DIR": str(user)}


def _init(tmp_path: Path, name: str = "ws") -> Path:
    workspace = tmp_path / name
    init_workspace(InitOptions(workspace=workspace))
    return workspace


def _document(path: Path) -> dict:
    loaded = yaml.safe_load(path.read_text(encoding="utf-8"))
    return loaded or {}


def test_add_agent_and_skill(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _isolate(monkeypatch, tmp_path)
    workspace = _init(tmp_path)
    result = add_component(
        AddOptions(workspace=workspace, kind="agent", name="reviewer", extra={"exposed": "false"})
    )
    assert any(path.endswith("/reviewer/AGENTS.md") for path in result.created)
    catalog = load_agent_catalog(workspace_dir=workspace)
    assert catalog.get("reviewer").spec.exposed is False
    assert "reviewer" in catalog.get("reviewer").agents_md_text
    assert "Main Agent" not in catalog.get("reviewer").agents_md_text

    again = add_component(
        AddOptions(workspace=workspace, kind="agent", name="reviewer", extra={"exposed": "false"})
    )
    assert again.created == []
    assert again.next_steps[0].startswith("anyagent doctor --workspace ")
    assert again.next_steps[1].startswith("anyagent serve --workspace ")

    visible = add_component(AddOptions(workspace=workspace, kind="agent", name="helper", extra={"exposed": "true"}))
    assert "exposed:" not in (workspace / ".anyagent" / "agents" / "helper" / "agent.yaml").read_text(encoding="utf-8")
    assert visible.created

    skill = add_component(AddOptions(workspace=workspace, kind="skill", name="review-notes"))
    assert any(path.endswith("/skills/review-notes/SKILL.md") for path in skill.created)
    package = load_skill_package(workspace / ".anyagent" / "skills" / "review-notes", scope="repo")
    assert package.frontmatter.name == "review-notes"
    assert package.frontmatter.description == "Use when the review-notes skill applies."
    assert package.frontmatter.metadata is not None
    assert package.frontmatter.metadata.short_description == "review-notes"
    pack = load_agent_catalog(workspace_dir=workspace).get("main")
    assert pack.spec.skills.default_selected == ["review-notes"]

    second = add_component(AddOptions(workspace=workspace, kind="skill", name="review-notes"))
    assert second.created == []
    assert second.updated == []
    assert load_agent_catalog(workspace_dir=workspace).get("main").spec.skills.default_selected == ["review-notes"]


def test_yaml_round_trip_keeps_user_fields(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    environ = _isolate(monkeypatch, tmp_path)
    workspace = _init(tmp_path)
    config_path = workspace / ".anyagent" / "anyagent.yaml"
    config_path.write_text(
        "\n".join(
            [
                "# yaml-language-server: $schema=./schema/anyagent.schema.json",
                "# keep-me",
                "server:",
                "  port: 9000",
                "",
            ]
        ),
        encoding="utf-8",
    )
    agent_path = workspace / ".anyagent" / "agents" / "main" / "agent.yaml"
    agent_path.write_text(
        "\n".join(
            [
                "# yaml-language-server: $schema=../../schema/agent.schema.json",
                "# keep-me",
                "runtime:",
                "  subagent:",
                "    max_concurrent: 2",
                "tools:",
                "  requested_tool_names:",
                "    - exec",
                "",
            ]
        ),
        encoding="utf-8",
    )

    add_component(AddOptions(workspace=workspace, kind="tool", name="echo"))
    config_text = config_path.read_text(encoding="utf-8")
    assert config_text.splitlines()[0] == "# yaml-language-server: $schema=./schema/anyagent.schema.json"
    assert "# keep-me" in config_text.splitlines()[:3]
    assert _document(config_path)["server"]["port"] == 9000
    loaded = load_effective_config(workspace, environ=environ)
    assert loaded.server.port == 9000
    assert loaded.plugins.roots == ["plugins"]

    agent_text = agent_path.read_text(encoding="utf-8")
    assert "# keep-me" in agent_text.splitlines()[:3]
    document = _document(agent_path)
    assert document["runtime"]["subagent"]["max_concurrent"] == 2
    assert document["tools"]["requested_tool_names"] == ["exec", "app.echo"]
    pack = load_agent_catalog(workspace_dir=workspace).get("main")
    assert pack.spec.runtime.subagent.max_concurrent == 2
    assert pack.spec.tools.requested_tool_names == ["exec", "app.echo"]


def test_generated_tool_loads_and_plugin_skeleton_does_not_register(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _isolate(monkeypatch, tmp_path)
    workspace = _init(tmp_path)
    add_component(AddOptions(workspace=workspace, kind="tool", name="echo"))

    registry = ToolRegistry()

    def factory(manifest, plugin_dir, config):
        return ToolRuntimePluginAPI(
            host_kind="tool_runtime",
            plugin_id=manifest.plugin_id,
            config=config,
            registry=registry,
        )

    loaded, errors = load_plugins_from_roots([workspace / "plugins"], api_factory=factory)
    assert errors == []
    assert [item.manifest.plugin_id for item in loaded] == ["echo"]
    registered = registry.get_tool("app.echo")
    assert registered is not None
    assert asyncio.run(registered.handler({"text": "hi"}, {"agent_id": "main"})) == "app.echo: hi (agent=main)"

    plugin_path = workspace / "plugins" / "echo" / "plugin.py"
    spec = importlib.util.spec_from_file_location("generated_echo", plugin_path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    class _Gateway:
        host_kind = "gateway"

        def __init__(self) -> None:
            self.tools = []

        def registerTool(self, tool, handler) -> None:  # noqa: N802
            self.tools.append((tool, handler))

    gateway = _Gateway()
    module.register(gateway)
    assert gateway.tools[0][0].name == "app.echo"

    class _Other:
        host_kind = "other"

        def registerTool(self, tool, handler) -> None:  # noqa: N802
            raise AssertionError("tool plugins must not register for an unknown host")

    module.register(_Other())

    named = _init(tmp_path, "named-tool")
    add_component(AddOptions(workspace=named, kind="tool", name="app.echo"))
    assert load_agent_catalog(workspace_dir=named).get("main").spec.tools.requested_tool_names == ["app.echo"]
    assert (named / "plugins" / "app.echo" / "plugin.json").is_file()
    manifest = json.loads((named / "plugins" / "app.echo" / "plugin.json").read_text(encoding="utf-8"))
    assert manifest["tools"] == ["app.echo"]

    skeleton = _init(tmp_path, "skeleton")
    add_component(AddOptions(workspace=skeleton, kind="plugin", name="notes"))
    assert load_agent_catalog(workspace_dir=skeleton).get("main").spec.tools.requested_tool_names == []
    empty = ToolRegistry()

    def empty_factory(manifest, plugin_dir, config):
        return ToolRuntimePluginAPI(
            host_kind="tool_runtime",
            plugin_id=manifest.plugin_id,
            config=config,
            registry=empty,
        )

    loaded, errors = load_plugins_from_roots([skeleton / "plugins"], api_factory=empty_factory)
    assert errors == []
    assert loaded[0].manifest.plugin_id == "notes"
    assert loaded[0].manifest.tools == []
    assert empty.get_tool("app.notes") is None
    assert load_effective_config(
        skeleton,
        environ={"SYSTEM_CONFIG_DIR": str(tmp_path / "system-config"), "USER_CONFIG_DIR": str(tmp_path / "user-config")},
    ).plugins.roots == ["plugins"]


def test_add_mcp_and_rejected_input(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _isolate(monkeypatch, tmp_path)
    workspace = _init(tmp_path)
    mcp_path = workspace / ".anyagent" / "agents" / "main" / "mcp.json"
    first = add_component(
        AddOptions(
            workspace=workspace,
            kind="mcp",
            name="docs",
            extra={"url": "https://example.com/mcp", "credential_id": "cred_docs"},
        )
    )
    assert str(mcp_path.resolve()) in first.created
    payload = json.loads(mcp_path.read_text(encoding="utf-8"))
    assert payload["$schema"] == "../../schema/mcp.schema.json"
    assert payload["mcpServers"]["docs"]["auth"] == {"credential_id": "cred_docs"}
    assert "cwd" not in payload["mcpServers"]["docs"]
    payload["_note"] = "keep"
    payload["mcpServers"]["local"] = {"command": "server", "args": ["--stdio"]}
    mcp_path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")

    skipped = add_component(
        AddOptions(
            workspace=workspace,
            kind="mcp",
            name="docs",
            extra={"url": "https://replaced.example/mcp"},
        )
    )
    assert str(mcp_path.resolve()) in skipped.skipped
    kept = json.loads(mcp_path.read_text(encoding="utf-8"))
    assert kept["_note"] == "keep"
    assert kept["mcpServers"]["docs"]["url"] == "https://example.com/mcp"
    before = load_agent_catalog(workspace_dir=workspace).get("main")
    assert before is not None and before.mcp_config is not None
    assert before.mcp_config.mcpServers["docs"].auth is not None
    assert before.mcp_config.mcpServers["docs"].auth.credential_id == "cred_docs"
    assert before.mcp_config.mcpServers["docs"].cwd is None

    add_component(
        AddOptions(
            workspace=workspace,
            kind="mcp",
            name="docs",
            force=True,
            extra={"command": "npx", "args": '["-y", "example-mcp"]'},
        )
    )
    replaced = json.loads(mcp_path.read_text(encoding="utf-8"))
    assert replaced["mcpServers"]["docs"] == {"command": "npx", "args": ["-y", "example-mcp"]}
    assert replaced["mcpServers"]["local"]["command"] == "server"
    assert replaced["_note"] == "keep"

    shlex_workspace = _init(tmp_path, "shlex")
    add_component(
        AddOptions(
            workspace=shlex_workspace,
            kind="mcp",
            name="local",
            extra={"command": "server", "args": "--stdio one"},
        )
    )
    servers = json.loads((shlex_workspace / ".anyagent" / "agents" / "main" / "mcp.json").read_text(encoding="utf-8"))
    assert servers["mcpServers"]["local"]["args"] == ["--stdio", "one"]

    catalog = load_agent_catalog(workspace_dir=workspace)
    main = catalog.get("main")
    assert main is not None and main.mcp_config is not None
    docs = main.mcp_config.mcpServers["docs"]
    assert docs.command == "npx"
    assert docs.args == ["-y", "example-mcp"]
    assert docs.cwd == str(workspace.resolve())
    assert docs.auth is None

    fresh = tmp_path / "fresh"
    with pytest.raises(ScaffoldError, match="requested_tool_names"):
        add_component(AddOptions(workspace=fresh, kind="tool", name="exec"))
    with pytest.raises(ScaffoldError):
        add_component(AddOptions(workspace=fresh, kind="tool", name="core.web_fetch"))
    with pytest.raises(ScaffoldError, match="both url and command"):
        add_component(
            AddOptions(workspace=fresh, kind="mcp", name="docs", extra={"url": "https://example.com", "command": "npx"})
        )
    with pytest.raises(ScaffoldError, match="unsupported extra"):
        add_component(AddOptions(workspace=fresh, kind="skill", name="notes", extra={"nope": "1"}))
    secret = "sk-" + ("a" * 16)
    with pytest.raises(ScaffoldError, match="plaintext secret") as caught:
        add_component(AddOptions(workspace=fresh, kind="mcp", name="docs", extra={"url": secret}))
    assert secret not in str(caught.value)
    with pytest.raises(ScaffoldError, match="secret field"):
        add_component(AddOptions(workspace=fresh, kind="mcp", name="docs", extra={"url": "https://example.com", "api_key": "not-a-value"}))
    assert not fresh.exists()
    leaked = [
        path
        for path in workspace.rglob("*")
        if path.is_file() and secret in path.read_text(encoding="utf-8")
    ]
    assert leaked == []
