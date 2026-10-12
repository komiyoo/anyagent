from __future__ import annotations

from pathlib import Path

import pytest

from anyagent.server.app import create_app


def _write_main_agent(root: Path) -> None:
    agent_dir = root / ".anyagent" / "agents" / "main"
    agent_dir.mkdir(parents=True, exist_ok=True)
    (agent_dir / "AGENTS.md").write_text("You are main.\n", encoding="utf-8")
    (agent_dir / "agent.yaml").write_text(
        "exposed: true\ntools:\n  requested_tool_names: []\nskills:\n  default_selected: []\nsandbox:\n  mode: disabled\n",
        encoding="utf-8",
    )


def _webhook_paths(app) -> list[str]:
    return [route.path for route in app.state.anyagent.gateway_registry.webhook_routes]


def test_builtin_plugins_are_off_by_default(tmp_path: Path) -> None:
    _write_main_agent(tmp_path)
    app = create_app(
        workspace_dir=tmp_path,
        cli_overrides={"server": {"api_key": "user-key", "admin_api_key": "admin-key"}},
    )

    assert _webhook_paths(app) == []
    tools, _version = app.state.anyagent.runtime.list_registered_tools()
    names = {tool.name for tool in tools}
    assert "app.chatwoot.send_message" not in names
    assert "app.lifecycle_echo.echo" not in names


def test_builtin_chatwoot_is_opt_in(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _write_main_agent(tmp_path)
    monkeypatch.setenv("CHATWOOT_WEBHOOK_SECRET", "test-secret")
    monkeypatch.setenv("CHATWOOT_ACCOUNT_ID", "9")
    app = create_app(
        workspace_dir=tmp_path,
        cli_overrides={
            "server": {"api_key": "user-key", "admin_api_key": "admin-key"},
            "plugins": {"builtin": ["chatwoot"]},
        },
    )

    assert any("chatwoot" in path for path in _webhook_paths(app))
    tools, _version = app.state.anyagent.runtime.list_registered_tools()
    names = {tool.name for tool in tools}
    assert "app.chatwoot.send_message" in names
    assert "app.lifecycle_echo.echo" not in names
    connector = app.state.anyagent.gateway_registry.channel_connectors["chatwoot"]
    assert connector.webhook_secret == "test-secret"
    assert connector.outbound._account_id == "9"


def test_unknown_builtin_plugin_fails_load(tmp_path: Path) -> None:
    _write_main_agent(tmp_path)

    with pytest.raises(RuntimeError, match="unknown built-in plugin"):
        create_app(
            workspace_dir=tmp_path,
            cli_overrides={
                "server": {"api_key": "user-key", "admin_api_key": "admin-key"},
                "plugins": {"builtin": ["not-a-plugin"]},
            },
        )


def test_unknown_builtin_plugin_is_skipped_when_fail_open(tmp_path: Path) -> None:
    _write_main_agent(tmp_path)
    app = create_app(
        workspace_dir=tmp_path,
        cli_overrides={
            "server": {"api_key": "user-key", "admin_api_key": "admin-key"},
            "plugins": {"builtin": ["not-a-plugin"], "fail_open": True},
        },
    )

    assert _webhook_paths(app) == []
