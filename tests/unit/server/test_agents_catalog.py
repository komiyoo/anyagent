from __future__ import annotations

import asyncio
import hashlib
from pathlib import Path

import httpx

from anyagent.protocol.agent_api_internal import InternalAgentDetailResponse, InternalAgentsListResponse
from anyagent.server.app import create_app


def _write_agent(
    root: Path,
    agent_id: str,
    *,
    exposed: bool,
    prompt: str,
    sandbox_mode: str = "disabled",
    requested_tool_names: list[str] | None = None,
    spawn_allow_agent_ids: list[str] | None = None,
) -> Path:
    agent_dir = root / ".agents" / "agents" / agent_id
    agent_dir.mkdir(parents=True, exist_ok=True)
    agents_md = agent_dir / "AGENTS.md"
    agents_md.write_text(prompt, encoding="utf-8")
    requested = requested_tool_names or []
    spawn_allowed = spawn_allow_agent_ids or []
    requested_block = ["  requested_tool_names:", *[f"    - {item}" for item in requested]] if requested else ["  requested_tool_names: []"]
    spawn_block = (
        ["  spawn_allow_agent_ids:", *[f"    - {item}" for item in spawn_allowed]]
        if spawn_allowed
        else ["  spawn_allow_agent_ids: []"]
    )
    (agent_dir / "agent.yaml").write_text(
        "\n".join(
            [
                f"exposed: {'true' if exposed else 'false'}",
                "tools:",
                *requested_block,
                "skills:",
                "  default_selected: []",
                "sandbox:",
                f"  mode: {sandbox_mode}",
                "multiagent:",
                *spawn_block,
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    return agents_md


def test_internal_agents_catalog_lists_allowed_agents_and_details(tmp_path: Path) -> None:
    asyncio.run(_run_internal_agents_catalog_lists_allowed_agents_and_details(tmp_path))


async def _run_internal_agents_catalog_lists_allowed_agents_and_details(tmp_path: Path) -> None:
    workspace_prompt = "Workspace 级协作规范。\n"
    (tmp_path / "AGENTS.md").write_text(workspace_prompt, encoding="utf-8")
    main_prompt = "你是 main agent。\n"
    hidden_prompt = "你是 hidden agent。\n"
    main_md = _write_agent(
        tmp_path,
        "main",
        exposed=True,
        prompt=main_prompt,
        sandbox_mode="local-unsafe",
        requested_tool_names=["exec"],
        spawn_allow_agent_ids=["researcher"],
    )
    _write_agent(tmp_path, "hidden", exposed=False, prompt=hidden_prompt)

    app = create_app(workspace_dir=tmp_path, api_key="user-key", admin_api_key="admin-key")
    transport = httpx.ASGITransport(app=app)

    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        listed = await client.get("/internal/agents", headers={"Authorization": "Bearer user-key"})
        assert listed.status_code == 200, listed.text
        list_payload = InternalAgentsListResponse.model_validate(listed.json())
        assert [item.agent_id for item in list_payload.agents] == ["main"]
        assert list_payload.agents[0].requested_tool_names == ["exec"]
        assert list_payload.agents[0].spawn_allow_agent_ids == ["researcher"]

        all_listed = await client.get(
            "/internal/agents",
            params={"include_unexposed": True},
            headers={"Authorization": "Bearer user-key"},
        )
        assert all_listed.status_code == 200, all_listed.text
        all_payload = InternalAgentsListResponse.model_validate(all_listed.json())
        assert [item.agent_id for item in all_payload.agents] == ["hidden", "main"]

        detail = await client.get("/internal/agents/main", headers={"Authorization": "Bearer user-key"})
        assert detail.status_code == 200, detail.text
        detail_payload = InternalAgentDetailResponse.model_validate(detail.json())
        assert detail_payload.agent_id == "main"
        assert detail_payload.agents_md.sha256 == hashlib.sha256(main_md.read_bytes()).hexdigest()
        assert detail_payload.agents_md.preview == "你是 main agent。"
        assert detail_payload.agents_md.text is None
        assert detail_payload.workspace_agents_md is not None
        assert detail_payload.workspace_agents_md.preview == "Workspace 级协作规范。"
        assert detail_payload.tools.requested_tool_names == ["exec"]
        assert detail_payload.sandbox["mode"] == "local-unsafe"
        assert detail_payload.multiagent["spawn_allow_agent_ids"] == ["researcher"]

        prompt_detail = await client.get(
            "/internal/agents/main",
            params={"include_prompt": True},
            headers={"Authorization": "Bearer user-key"},
        )
        assert prompt_detail.status_code == 200, prompt_detail.text
        prompt_payload = InternalAgentDetailResponse.model_validate(prompt_detail.json())
        assert prompt_payload.agents_md.text == main_prompt
        assert prompt_payload.workspace_agents_md is not None
        assert prompt_payload.workspace_agents_md.text == workspace_prompt

        hidden_detail = await client.get("/internal/agents/hidden", headers={"Authorization": "Bearer user-key"})
        assert hidden_detail.status_code == 403, hidden_detail.text
