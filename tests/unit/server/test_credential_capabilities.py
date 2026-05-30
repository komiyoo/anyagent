from __future__ import annotations

import asyncio
import json
from pathlib import Path

import httpx

from anyagent.server.app import create_app
from anyagent.server.security import FileBackend, build_credential_backend_capability_matrix
from anyagent.tool_runtime import create_tool_runtime_app


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


def test_credential_capability_matrix_documents_resolver_and_admin_modes() -> None:
    matrix = build_credential_backend_capability_matrix()
    resolver_modes = {item.mode: item for item in matrix.resolver_modes}
    admin_modes = {item.mode: item for item in matrix.admin_store_modes}

    assert matrix.environment_variable == "MCP_CREDENTIAL_STORE_BACKEND"
    assert matrix.secret_value_returned is False
    assert {"none", "env", "file", "infisical"} <= set(resolver_modes)
    assert {"memory", "env-write", "file-write", "infisical-write", "db", "vault"} <= set(admin_modes)
    assert resolver_modes["env"].supports_resolve is True
    assert resolver_modes["env"].supports_set is False
    assert admin_modes["file-write"].supports_set is True
    assert admin_modes["infisical-write"].read_only is True
    assert admin_modes["db"].status == "preview"
    assert admin_modes["db"].supports_resolve is True
    assert admin_modes["db"].supports_set is True
    assert admin_modes["vault"].status == "preview"
    assert admin_modes["vault"].supports_resolve is True
    assert admin_modes["vault"].supports_set is True

    payload = matrix.model_dump(mode="json")
    text = json.dumps(payload)
    assert "secretValue" not in text
    assert "client_secret" not in text


def test_core_server_admin_credentials_capabilities_endpoint(tmp_path: Path, monkeypatch) -> None:
    asyncio.run(_run_core_server_admin_credentials_capabilities_endpoint(tmp_path, monkeypatch))


def test_tool_runtime_admin_credentials_capabilities_endpoint(tmp_path: Path) -> None:
    asyncio.run(_run_tool_runtime_admin_credentials_capabilities_endpoint(tmp_path))


async def _run_core_server_admin_credentials_capabilities_endpoint(tmp_path: Path, monkeypatch) -> None:
    _write_main_agent(tmp_path)
    monkeypatch.setenv("MCP_CREDENTIAL_STORE_BACKEND", "file-write")
    monkeypatch.setenv("MCP_CREDENTIAL_STORE_FILE_ROOT", ".anyagent/credentials")
    app = create_app(workspace_dir=tmp_path, api_key="user-key", admin_api_key="admin-key")
    assert isinstance(app.state.anyagent.mcp_credentials, FileBackend)
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as http:
        unauthorized = await http.get("/admin/credentials/capabilities")
        assert unauthorized.status_code == 401

        resp = await http.get("/admin/credentials/capabilities", headers={"Authorization": "Bearer admin-key"})
        assert resp.status_code == 200, resp.text
        payload = resp.json()
        assert payload["secret_value_returned"] is False
        assert {item["mode"] for item in payload["admin_store_modes"]} >= {"memory", "file-write", "infisical-write"}


async def _run_tool_runtime_admin_credentials_capabilities_endpoint(tmp_path: Path) -> None:
    _write_main_agent(tmp_path)
    app = create_tool_runtime_app(workspace_dir=tmp_path, admin_api_key="admin-key")
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as http:
        unauthorized = await http.get("/admin/credentials/capabilities")
        assert unauthorized.status_code == 401

        resp = await http.get("/admin/credentials/capabilities", headers={"Authorization": "Bearer admin-key"})
        assert resp.status_code == 200, resp.text
        payload = resp.json()
        assert payload["environment_variable"] == "MCP_CREDENTIAL_STORE_BACKEND"
        assert {item["mode"] for item in payload["resolver_modes"]} >= {"env", "file", "infisical"}
