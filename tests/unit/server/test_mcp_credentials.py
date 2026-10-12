from __future__ import annotations

import asyncio
import json
from pathlib import Path

from anyagent.protocol.credential_vault import AdminCredentialSetRequest, CredentialScope
from anyagent.protocol.tool_runtime import AuthRef
from anyagent.server.app import create_app


def _write_main_agent(root: Path) -> None:
    agent_dir = root / ".anyagent" / "agents" / "main"
    agent_dir.mkdir(parents=True, exist_ok=True)
    (agent_dir / "AGENTS.md").write_text("You are main.\n", encoding="utf-8")
    (agent_dir / "agent.yaml").write_text(
        "\n".join(
            [
                "exposed: true",
                "tools:",
                "  requested_tool_names: []",
                "skills:",
                "  default_selected: []",
                "sandbox:",
                "  mode: disabled",
            ]
        )
        + "\n",
        encoding="utf-8",
    )


def test_mcp_credentials_default_to_admin_store(tmp_path: Path) -> None:
    async def _run() -> None:
        _write_main_agent(tmp_path)
        app = create_app(
                  workspace_dir=tmp_path,
                  cli_overrides={
                      "server": {
                          "api_key": "user-key",
                          "admin_api_key": "admin-key",
                      },
                  },
              )
        state = app.state.anyagent
        await state.credentials.set(
            AdminCredentialSetRequest(
                credential_id="cred_api",
                kind="bearer_token",
                value="secret",
                scope=CredentialScope(level="agent", agent_id="main"),
                metadata={},
            )
        )

        resolved = await state.mcp_credentials.resolve(
            AuthRef(kind="bearer_token", ref="cred_api"),
            scope_context={"agent_id": "main"},
        )

        assert resolved == "secret"
        assert state.mcp_credentials is state.credentials

    asyncio.run(_run())


def test_mcp_credentials_file_backend_uses_workspace_relative_root(tmp_path: Path, monkeypatch) -> None:
    async def _run() -> None:
        _write_main_agent(tmp_path)
        monkeypatch.setenv("MCP_CREDENTIAL_STORE_BACKEND", "file")
        credential_dir = tmp_path / ".anyagent" / "credentials" / "agents" / "main"
        credential_dir.mkdir(parents=True, exist_ok=True)
        (credential_dir / "cred_api.json").write_text(
            json.dumps(
                {
                    "credential_id": "cred_api",
                    "kind": "bearer_token",
                    "value": "file-secret",
                    "scope": {"level": "agent", "agent_id": "main"},
                }
            ),
            encoding="utf-8",
        )

        app = create_app(
                  workspace_dir=tmp_path,
                  cli_overrides={
                      "server": {
                          "api_key": "user-key",
                          "admin_api_key": "admin-key",
                      },
                  },
              )
        resolved = await app.state.anyagent.mcp_credentials.resolve(
            AuthRef(kind="bearer_token", ref="cred_api"),
            scope_context={"agent_id": "main"},
        )

        assert resolved == "file-secret"
        assert app.state.anyagent.mcp_credentials is app.state.anyagent.credentials

    asyncio.run(_run())
