from __future__ import annotations

import asyncio
from pathlib import Path

import httpx

from anyagent import AnyAgent
from anyagent.server.app import create_app


def _write_workspace(root: Path) -> None:
    agent_dir = root / ".agents" / "agents" / "main"
    agent_dir.mkdir(parents=True, exist_ok=True)
    (agent_dir / "AGENTS.md").write_text("你是一个测试 agent。\n", encoding="utf-8")
    (agent_dir / "agent.yaml").write_text(
        """
exposed: true
tools:
  requested_tool_names: []
skills:
  default_selected: []
sandbox:
  mode: disabled
multiagent:
  spawn_allow_agent_ids: []
""".strip()
        + "\n",
        encoding="utf-8",
    )


def test_sdk_health_and_admin_credentials_match_server(tmp_path: Path) -> None:
    asyncio.run(_run_sdk_health_and_admin_credentials_match_server(tmp_path))


async def _run_sdk_health_and_admin_credentials_match_server(tmp_path: Path) -> None:
    _write_workspace(tmp_path)
    app = create_app(workspace_dir=tmp_path, api_key="user-key", admin_api_key="user-key")
    transport = httpx.ASGITransport(app=app)

    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as http:
        client = AnyAgent(api_key="user-key", base_url="http://testserver", http=http)

        health = await client.health()
        assert health.ok is True
        assert health.workspace == str(tmp_path.resolve())
        assert health.agent_ids == ["main"]

        ref = await client.admin.set_credential(
            {
                "credential_id": "search_api_key",
                "kind": "api_key",
                "value": "secret-value",
                "scope": {"level": "agent", "agent_id": "main"},
                "metadata": {"provider": "search"},
            }
        )
        assert ref.credential_id == "search_api_key"
        assert ref.scope.level == "agent"
        assert ref.scope.agent_id == "main"

        listed = await client.admin.list_credentials()
        assert len(listed.credentials) == 1
        assert listed.credentials[0].credential_id == "search_api_key"

        deleted = await client.admin.delete_credential("search_api_key")
        assert deleted == {"ok": True, "deleted": True, "credential_id": "search_api_key"}

        listed_after = await client.admin.list_credentials()
        assert listed_after.credentials == []
