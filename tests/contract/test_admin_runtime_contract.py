from __future__ import annotations

import asyncio
from pathlib import Path

import httpx

from anyagent.server import create_app


def test_admin_runtime_contract_covers_core_behavior(tmp_path: Path) -> None:
    asyncio.run(_run_admin_runtime_contract_covers_core_behavior(tmp_path))


async def _run_admin_runtime_contract_covers_core_behavior(tmp_path: Path) -> None:
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
    auth = {"Authorization": "Bearer admin-key"}

    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as http:
        unauthorized = await http.get("/admin/credentials")
        assert unauthorized.status_code == 401

        health = await http.get("/healthz")
        assert health.status_code == 200
        assert health.json()["agent_ids"] == ["main"]

        set_resp = await http.post(
            "/admin/credentials",
            headers=auth,
            json={
                "credential_id": "cred_contract",
                "kind": "api_key",
                "value": "secret-value",
                "scope": {"level": "session", "agent_id": "main", "session_key": "thread-1"},
                "expires_at": "2026-06-30T00:00:00Z",
                "rotate_before": "2026-06-23T00:00:00Z",
            },
        )
        assert set_resp.status_code == 200
        body = set_resp.json()
        assert body["credential_id"] == "cred_contract"
        assert body["scope"] == {"level": "session", "agent_id": "main", "session_key": "thread-1"}
        assert "value" not in body

        list_resp = await http.get("/admin/credentials", headers=auth)
        assert list_resp.status_code == 200
        listed = list_resp.json()["credentials"]
        assert listed[0]["credential_id"] == "cred_contract"
        assert "value" not in listed[0]

        capabilities = await http.get("/admin/credentials/capabilities", headers=auth)
        assert capabilities.status_code == 200
        modes = {item["mode"]: item for item in capabilities.json()["admin_store_modes"]}
        assert modes["db"]["status"] == "preview"
        assert modes["vault"]["status"] == "preview"

        tools = await http.get("/admin/tools/catalog", headers=auth)
        assert tools.status_code == 200
        assert "toolset_version" in tools.json()

        storage_health = await http.get("/admin/storage/health", headers=auth)
        assert storage_health.status_code == 200
        assert storage_health.json()["ok"] is True

        delete_resp = await http.delete("/admin/credentials/cred_contract", headers=auth)
        assert delete_resp.status_code == 200
        assert delete_resp.json() == {"ok": True, "deleted": True, "credential_id": "cred_contract"}


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
