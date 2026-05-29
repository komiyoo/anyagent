from __future__ import annotations

import logging
import os
import textwrap
from pathlib import Path

from fastapi.testclient import TestClient

from anyagent.server.app import create_app


def _write_agent(workspace: Path, agent_yaml: str) -> Path:
    agent_dir = workspace / ".anyagent" / "agents" / "main"
    agent_dir.mkdir(parents=True, exist_ok=True)
    (agent_dir / "AGENTS.md").write_text("# Main\n", encoding="utf-8")
    agent_yaml_path = agent_dir / "agent.yaml"
    agent_yaml_path.write_text(textwrap.dedent(agent_yaml).strip() + "\n", encoding="utf-8")
    return agent_yaml_path


def test_request_reloads_hot_agent_config_change(tmp_path: Path) -> None:
    agent_yaml = _write_agent(
        tmp_path,
        """
        exposed: true
        model:
          default: before
        tools:
          requested_tool_names: []
        sandbox:
          mode: disabled
        """,
    )
    app = create_app(workspace_dir=tmp_path, api_key="user-key", admin_api_key="admin-key")
    state = app.state.anyagent

    agent_yaml.write_text(
        textwrap.dedent(
            """
            exposed: true
            model:
              default: after
            tools:
              requested_tool_names: []
            sandbox:
              mode: disabled
            """
        ).strip()
        + "\n",
        encoding="utf-8",
    )
    os.utime(agent_yaml, None)

    with TestClient(app) as client:
        assert client.get("/healthz").status_code == 200

    assert state.catalog.get("main").spec.model.default == "after"


def test_request_warns_and_keeps_current_catalog_for_cold_change(tmp_path: Path, caplog) -> None:
    agent_yaml = _write_agent(
        tmp_path,
        """
        exposed: true
        tools:
          requested_tool_names: []
        sandbox:
          mode: disabled
        """,
    )
    app = create_app(workspace_dir=tmp_path, api_key="user-key", admin_api_key="admin-key")
    state = app.state.anyagent

    agent_yaml.write_text(
        textwrap.dedent(
            """
            exposed: true
            tools:
              requested_tool_names: []
            sandbox:
              mode: local-unsafe
            """
        ).strip()
        + "\n",
        encoding="utf-8",
    )
    os.utime(agent_yaml, None)

    caplog.set_level(logging.WARNING)
    with TestClient(app) as client:
        assert client.get("/healthz").status_code == 200

    assert state.catalog.get("main").spec.sandbox.mode == "disabled"
    assert "restart required" in caplog.text
