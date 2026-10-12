from __future__ import annotations

import textwrap
from pathlib import Path

import pytest

from anyagent.config.agents import AgentPackError, load_agent_catalog
from anyagent.config.merge import deep_merge


def _write_agent(root: Path, agent_id: str, agent_yaml: str, *, agents_md: str = "# Agent\n") -> None:
    agent_dir = root / "agents" / agent_id
    agent_dir.mkdir(parents=True, exist_ok=True)
    (agent_dir / "agent.yaml").write_text(textwrap.dedent(agent_yaml).strip() + "\n", encoding="utf-8")
    (agent_dir / "AGENTS.md").write_text(agents_md, encoding="utf-8")


def test_deep_merge_recurses_nested_objects_without_mutating_base() -> None:
    base = {"model": {"provider": "openai", "default": "gpt-4.1"}, "tools": {"requested_tool_names": ["a"]}}
    merged = deep_merge(base, {"model": {"default": "gpt-5"}})

    assert merged == {"model": {"provider": "openai", "default": "gpt-5"}, "tools": {"requested_tool_names": ["a"]}}
    assert base["model"]["default"] == "gpt-4.1"


def test_load_agent_catalog_merges_system_user_workspace_and_session_layers(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    system = tmp_path / "system"
    user = tmp_path / "user"
    workspace = tmp_path / "workspace"
    monkeypatch.setenv("SYSTEM_CONFIG_DIR", str(system))
    monkeypatch.setenv("USER_CONFIG_DIR", str(user))

    _write_agent(
        system,
        "main",
        """
        exposed: true
        model:
          provider: openai
          default: system-model
        tools:
          requested_tool_names:
            - system.tool
        skills:
          default_selected:
            - system-skill
        """,
    )
    _write_agent(
        user,
        "main",
        """
        model:
          default: user-model
        skills:
          default_selected:
            - user-skill
        """,
    )
    _write_agent(
        workspace / ".anyagent",
        "main",
        """
        tools:
          requested_tool_names:
            - workspace.tool
        """,
        agents_md="# Workspace agent\n",
    )

    catalog = load_agent_catalog(
        workspace_dir=workspace,
        session_config_overrides={
            "agents": {
                "main": {
                    "agent": {
                        "model": {"default": "session-model"},
                    }
                }
            }
        },
    )

    pack = catalog.get("main")
    assert pack is not None
    assert pack.spec.exposed is True
    assert pack.spec.model.default == "session-model"
    assert pack.spec.tools.requested_tool_names == ["workspace.tool"]
    assert pack.spec.skills.default_selected == ["user-skill"]
    assert pack.agents_md_text == "# Workspace agent\n"


def test_workspace_layer_cannot_override_sensitive_values_from_higher_layers(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    system = tmp_path / "system"
    workspace = tmp_path / "workspace"
    monkeypatch.setenv("SYSTEM_CONFIG_DIR", str(system))
    monkeypatch.setenv("USER_CONFIG_DIR", str(tmp_path / "missing-user"))

    _write_agent(
        system,
        "main",
        """
        exposed: true
        sandbox:
          mode: disabled
        tools:
          requested_tool_names: []
        """,
    )
    _write_agent(
        workspace / ".anyagent",
        "main",
        """
        sandbox:
          mode: local-unsafe
        """,
    )

    with pytest.raises(AgentPackError, match="workspace config cannot override sensitive field sandbox.mode"):
        load_agent_catalog(workspace_dir=workspace)


def test_missing_system_and_user_layers_are_ignored(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    workspace = tmp_path / "workspace"
    monkeypatch.setenv("SYSTEM_CONFIG_DIR", str(tmp_path / "missing-system"))
    monkeypatch.setenv("USER_CONFIG_DIR", str(tmp_path / "missing-user"))
    _write_agent(
        workspace / ".anyagent",
        "main",
        """
        exposed: true
        tools:
          requested_tool_names: []
        sandbox:
          mode: disabled
        """,
    )

    catalog = load_agent_catalog(workspace_dir=workspace)

    assert sorted(catalog.packs) == ["main"]
