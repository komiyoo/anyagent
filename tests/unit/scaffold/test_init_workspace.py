from __future__ import annotations

import json
from pathlib import Path

import pytest
import yaml

from anyagent.config import load_agent_catalog, load_effective_config
from anyagent.config.models import resolve_effective_model_selection
from anyagent.scaffold import InitOptions, ScaffoldError, export_config_schemas, init_workspace
from anyagent.scaffold.files import TEMPLATE_ROOT
from anyagent.skills.loader import load_skill_package


def _isolate(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> dict[str, str]:
    system = tmp_path / "system-config"
    user = tmp_path / "user-config"
    system.mkdir()
    user.mkdir()
    monkeypatch.setenv("SYSTEM_CONFIG_DIR", str(system))
    monkeypatch.setenv("USER_CONFIG_DIR", str(user))
    return {"SYSTEM_CONFIG_DIR": str(system), "USER_CONFIG_DIR": str(user)}


def _load(workspace: Path, environ: dict[str, str]):
    return load_effective_config(workspace, environ=environ)


def _document(path: Path) -> dict:
    loaded = yaml.safe_load(path.read_text(encoding="utf-8"))
    assert loaded is None or isinstance(loaded, dict)
    return loaded or {}


def test_public_options_do_not_share_mutable_defaults(tmp_path: Path) -> None:
    from anyagent.scaffold import AddOptions

    first = InitOptions(workspace=tmp_path / "a")
    second = InitOptions(workspace=tmp_path / "b")
    assert first.template == "basic"
    assert first.agent_id == "main"
    assert first.provider == "openai"
    assert first.model is None
    assert first.force is False
    first.tools.append("exec")
    assert second.tools == []

    added = AddOptions(workspace=tmp_path / "a", kind="tool", name="echo")
    other = AddOptions(workspace=tmp_path / "b", kind="skill", name="notes")
    added.extra["url"] = "https://example.com"
    assert other.extra == {}


def test_templates_are_packaged_beside_the_module() -> None:
    expected = [
        "workspace/AGENTS.md.tmpl",
        "workspace/gitignore",
        "workspace/env.example.tmpl",
        "agents/basic.md.tmpl",
        "agents/coding.md.tmpl",
        "agents/research.md.tmpl",
        "agents/coordinator.md.tmpl",
        "agents/default-main.md.tmpl",
        "agents/added.md.tmpl",
        "skills/example-skill.md.tmpl",
        "skills/added.md.tmpl",
        "plugins/tool/plugin.json.tmpl",
        "plugins/tool/plugin.py.tmpl",
        "plugins/tool/README.md.tmpl",
        "plugins/plugin/plugin.json.tmpl",
        "plugins/plugin/plugin.py.tmpl",
        "plugins/plugin/README.md.tmpl",
    ]
    for relative in expected:
        assert (TEMPLATE_ROOT / relative).is_file(), relative


def test_basic_init_is_minimal_and_loads(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    environ = _isolate(monkeypatch, tmp_path)
    workspace = tmp_path / "ws"
    result = init_workspace(InitOptions(workspace=workspace))

    assert result.ok is True
    assert result.agent_id == "main"
    assert result.next == f"anyagent doctor --workspace {workspace.resolve()}"
    assert result.created
    assert all(Path(path).is_absolute() for path in result.created)

    config_text = (workspace / ".anyagent" / "anyagent.yaml").read_text(encoding="utf-8")
    assert config_text.splitlines()[0] == "# yaml-language-server: $schema=./schema/anyagent.schema.json"
    assert "models:" not in config_text
    agent_text = (workspace / ".anyagent" / "agents" / "main" / "agent.yaml").read_text(encoding="utf-8")
    assert agent_text.splitlines()[0] == "# yaml-language-server: $schema=../../schema/agent.schema.json"
    assert _document(workspace / ".anyagent" / "agents" / "main" / "agent.yaml") == {}

    assert not (workspace / ".anyagent" / "agents" / "main" / "mcp.json").exists()
    assert not (workspace / "plugins").exists()
    assert not (workspace / ".anyagent" / "skills").exists()
    assert list(workspace.rglob(".gitkeep")) == []
    assert "Main Agent" in (workspace / ".anyagent" / "agents" / "main" / "AGENTS.md").read_text(encoding="utf-8")
    assert "anyagent init --template basic" in (workspace / "AGENTS.md").read_text(encoding="utf-8")

    schemas = export_config_schemas()
    assert set(schemas) == {"anyagent.yaml", "agent.yaml", "mcp.json"}
    assert "models" in schemas["anyagent.yaml"]["properties"]
    assert "exposed" in schemas["agent.yaml"]["properties"]
    assert "mcpServers" in schemas["mcp.json"]["properties"]
    for key, filename in (
        ("anyagent.yaml", "anyagent.schema.json"),
        ("agent.yaml", "agent.schema.json"),
        ("mcp.json", "mcp.schema.json"),
    ):
        written = json.loads((workspace / ".anyagent" / "schema" / filename).read_text(encoding="utf-8"))
        assert written == schemas[key]

    loaded = _load(workspace, environ)
    assert loaded.models.default == "fast"
    catalog = load_agent_catalog(workspace_dir=workspace)
    pack = catalog.get("main")
    assert pack is not None
    assert pack.builtin is False
    assert pack.spec.exposed is True
    assert pack.spec.tools.requested_tool_names == []
    assert pack.mcp_config is None

    gitignore = (workspace / ".gitignore").read_text(encoding="utf-8")
    assert ".env\n" in gitignore
    assert ".env.example" not in gitignore
    example = (workspace / ".env.example").read_text(encoding="utf-8")
    assert "OPENAI_API_KEY=" in example
    assert "ANTHROPIC_API_KEY=" not in example


def test_model_selection_is_written_only_when_it_differs(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    environ = _isolate(monkeypatch, tmp_path)

    default_model = tmp_path / "default-model"
    init_workspace(InitOptions(workspace=default_model, provider="openai", model="gpt-4o-mini"))
    assert "models:" not in (default_model / ".anyagent" / "anyagent.yaml").read_text(encoding="utf-8")

    named = tmp_path / "named"
    init_workspace(InitOptions(workspace=named, provider="openai", model="gpt-4o"))
    assert _document(named / ".anyagent" / "anyagent.yaml")["models"]["default"] == "openai:gpt-4o"
    selection = resolve_effective_model_selection(
        pack=load_agent_catalog(workspace_dir=named).get("main"),
        config=_load(named, environ),
    )
    assert selection.model == "gpt-4o"
    assert selection.provider_kind == "openai"

    anthropic = tmp_path / "anthropic"
    init_workspace(InitOptions(workspace=anthropic, provider="anthropic", model="claude-x"))
    assert _document(anthropic / ".anyagent" / "anyagent.yaml")["models"]["default"] == "anthropic:claude-x"
    selection = resolve_effective_model_selection(
        pack=load_agent_catalog(workspace_dir=anthropic).get("main"),
        config=_load(anthropic, environ),
    )
    assert selection.model == "claude-x"
    assert selection.provider_kind == "anthropic"
    assert "ANTHROPIC_API_KEY=" in (anthropic / ".env.example").read_text(encoding="utf-8")

    alias = tmp_path / "alias"
    init_workspace(InitOptions(workspace=alias, provider="claude", model="claude-x"))
    assert _document(alias / ".anyagent" / "anyagent.yaml")["models"]["default"] == "anthropic:claude-x"

    bare_provider = tmp_path / "bare"
    init_workspace(InitOptions(workspace=bare_provider, provider="anthropic"))
    text = (bare_provider / ".anyagent" / "anyagent.yaml").read_text(encoding="utf-8")
    assert text.splitlines()[0].startswith("# yaml-language-server:")
    assert "Replace models.default" in text
    assert _document(bare_provider / ".anyagent" / "anyagent.yaml")["models"]["default"] == "anthropic:"
    selection = resolve_effective_model_selection(
        pack=load_agent_catalog(workspace_dir=bare_provider).get("main"),
        config=_load(bare_provider, environ),
    )
    assert selection.provider_kind == "anthropic"
    assert selection.model is None


def test_base_url_and_custom_provider(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    environ = _isolate(monkeypatch, tmp_path)
    custom = tmp_path / "custom-url"
    init_workspace(InitOptions(workspace=custom, base_url="https://example.test/v1"))
    document = _document(custom / ".anyagent" / "anyagent.yaml")
    assert "default" not in document["models"]
    assert document["models"]["providers"]["openai"] == {"base_url": "https://example.test/v1"}
    assert "api_key" not in (custom / ".anyagent" / "anyagent.yaml").read_text(encoding="utf-8")
    loaded = _load(custom, environ)
    assert loaded.models.providers["openai"].base_url == "https://example.test/v1"
    assert loaded.models.default == "fast"

    same = tmp_path / "same-url"
    init_workspace(InitOptions(workspace=same, base_url="https://api.openai.com/v1/"))
    assert "models:" not in (same / ".anyagent" / "anyagent.yaml").read_text(encoding="utf-8")

    acme = tmp_path / "acme"
    init_workspace(InitOptions(workspace=acme, provider="acme", model="my-model"))
    text = (acme / ".anyagent" / "anyagent.yaml").read_text(encoding="utf-8")
    assert "${OPENAI_API_KEY}" in text
    document = _document(acme / ".anyagent" / "anyagent.yaml")
    assert document["models"]["default"] == "acme:my-model"
    assert document["models"]["providers"]["acme"]["kind"] == "openai"
    selection = resolve_effective_model_selection(
        pack=load_agent_catalog(workspace_dir=acme).get("main"),
        config=_load(acme, environ),
    )
    assert selection.provider_name == "acme"
    assert selection.provider_kind == "openai"
    assert selection.model == "my-model"
    assert "OPENAI_API_KEY=" in (acme / ".env.example").read_text(encoding="utf-8")

    gemini = tmp_path / "gemini"
    init_workspace(InitOptions(workspace=gemini, provider="gemini", model="gemini-2"))
    example = (gemini / ".env.example").read_text(encoding="utf-8")
    assert "GOOGLE_API_KEY=" in example
    assert "GEMINI_API_KEY=" in example


def test_template_behavior(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _isolate(monkeypatch, tmp_path)

    coding = tmp_path / "coding"
    init_workspace(InitOptions(workspace=coding, template="coding-agent"))
    pack = load_agent_catalog(workspace_dir=coding).get("main")
    assert pack is not None
    assert pack.spec.tools.requested_tool_names == ["exec"]
    assert pack.spec.sandbox.mode == "local-unsafe"
    instructions = pack.agents_md_text
    assert "Use `exec` for local verification" in instructions
    assert not (coding / ".anyagent" / "skills").exists()

    research = tmp_path / "research"
    init_workspace(InitOptions(workspace=research, template="research-agent"))
    pack = load_agent_catalog(workspace_dir=research).get("main")
    assert pack is not None
    assert pack.spec.tools.requested_tool_names == ["core.web_fetch"]
    assert pack.spec.sandbox.mode == "disabled"
    assert "sandbox:" not in (research / ".anyagent" / "agents" / "main" / "agent.yaml").read_text(encoding="utf-8")
    assert "primary sources" in pack.agents_md_text

    team = tmp_path / "team"
    init_workspace(InitOptions(workspace=team, template="multi-agent-team", with_example_skill=True))
    catalog = load_agent_catalog(workspace_dir=team)
    assert set(catalog.packs) == {"main", "researcher", "coder"}
    assert catalog.get("main").spec.multiagent.spawn_allow_agent_ids == ["researcher", "coder"]
    assert catalog.get("researcher").spec.tools.requested_tool_names == ["core.web_fetch"]
    assert catalog.get("coder").spec.tools.requested_tool_names == ["exec"]
    assert catalog.get("coder").spec.sandbox.mode == "local-unsafe"
    assert catalog.get("main").spec.skills.default_selected == ["example-skill"]
    assert catalog.get("coder").spec.skills.default_selected == ["example-skill"]
    skill = load_skill_package(team / ".anyagent" / "skills" / "example-skill", scope="repo")
    assert skill.frontmatter.name == "example-skill"
    assert "researcher" in catalog.get("main").agents_md_text
    assert "coder" in catalog.get("main").agents_md_text

    nested = tmp_path / "nested"
    init_workspace(
        InitOptions(workspace=nested, template="multi-agent-team", agent_id="researcher", with_example_skill=True)
    )
    catalog = load_agent_catalog(workspace_dir=nested)
    assert set(catalog.packs) == {"researcher", "researcher-helper", "coder-helper", "main"}
    assert catalog.get("researcher").spec.multiagent.spawn_allow_agent_ids == ["researcher-helper", "coder-helper"]
    assert catalog.get("main").spec.multiagent.spawn_allow_agent_ids == ["researcher"]
    assert catalog.get("main").spec.tools.requested_tool_names == []
    assert catalog.get("main").spec.skills.default_selected is None
    assert catalog.get("researcher").spec.skills.default_selected == ["example-skill"]
    assert "researcher-helper" in catalog.get("researcher").agents_md_text

    renamed = tmp_path / "renamed"
    init_workspace(InitOptions(workspace=renamed, agent_id="support", with_example_skill=True))
    catalog = load_agent_catalog(workspace_dir=renamed)
    assert catalog.get("main").spec.multiagent.spawn_allow_agent_ids == ["support"]
    assert catalog.get("main").spec.sandbox.mode == "disabled"
    assert catalog.get("support").spec.skills.default_selected == ["example-skill"]
    assert "Main Agent" in catalog.get("support").agents_md_text
    assert "`support`" in catalog.get("main").agents_md_text


def test_primary_flags_do_not_change_child_agents(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _isolate(monkeypatch, tmp_path)
    workspace = tmp_path / "ws"
    init_workspace(
        InitOptions(
            workspace=workspace,
            template="multi-agent-team",
            with_exec=True,
            tools=["exec", " exec "],
        )
    )
    catalog = load_agent_catalog(workspace_dir=workspace)
    assert catalog.get("main").spec.tools.requested_tool_names == ["exec"]
    assert catalog.get("main").spec.sandbox.mode == "local-unsafe"
    assert catalog.get("researcher").spec.tools.requested_tool_names == ["core.web_fetch"]
    assert catalog.get("researcher").spec.sandbox.mode == "disabled"

    basic = tmp_path / "basic"
    init_workspace(InitOptions(workspace=basic, with_exec=True, with_web_fetch=True, tools=["exec"]))
    pack = load_agent_catalog(workspace_dir=basic).get("main")
    assert pack is not None
    assert pack.spec.tools.requested_tool_names == ["exec", "core.web_fetch"]
    assert pack.spec.sandbox.mode == "local-unsafe"

    pinned = tmp_path / "pinned"
    init_workspace(InitOptions(workspace=pinned, with_exec=True, sandbox_mode="disabled"))
    pack = load_agent_catalog(workspace_dir=pinned).get("main")
    assert pack is not None
    assert pack.spec.tools.requested_tool_names == ["exec"]
    assert pack.spec.sandbox.mode == "disabled"
    assert "sandbox:" not in (pinned / ".anyagent" / "agents" / "main" / "agent.yaml").read_text(encoding="utf-8")


def test_invalid_init_writes_nothing_and_force_restores(tmp_path: Path) -> None:
    missing = tmp_path / "missing"
    with pytest.raises(ScaffoldError):
        init_workspace(InitOptions(workspace=missing, template="nope"))
    with pytest.raises(ScaffoldError):
        init_workspace(InitOptions(workspace=missing, sandbox_mode="nope"))
    with pytest.raises(ScaffoldError):
        init_workspace(InitOptions(workspace=missing, agent_id=".."))
    assert not missing.exists()

    workspace = tmp_path / "ws"
    first = init_workspace(InitOptions(workspace=workspace))
    second = init_workspace(InitOptions(workspace=workspace, force=True))
    assert second.created == []
    assert set(second.skipped) == set(first.created)
    assert second.ok is True

    agents = workspace / "AGENTS.md"
    agents.write_text("# edited\n", encoding="utf-8")
    kept = init_workspace(InitOptions(workspace=workspace))
    assert agents.read_text(encoding="utf-8") == "# edited\n"
    assert str(agents.resolve()) in kept.skipped

    restored = init_workspace(InitOptions(workspace=workspace, force=True))
    assert "anyagent init --template basic" in agents.read_text(encoding="utf-8")
    assert str(agents.resolve()) in restored.created
