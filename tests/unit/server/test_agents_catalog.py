from __future__ import annotations

import asyncio
import hashlib
import json
import subprocess
from pathlib import Path

import httpx
from openai.types.responses.response import Response
from openai.types.responses.response_output_message import ResponseOutputMessage
from openai.types.responses.response_output_text import ResponseOutputText

from anyagent.agent_api_client import AnyAgent
from anyagent.observability import emit_observability_event, get_observability_emitter
from anyagent.protocol.observability import NormalizedTelemetryEvent
from anyagent.protocol.agent_api_internal import (
    AdminAgentCreateResponse,
    AdminSkillImportResponse,
    AdminToolCatalogResponse,
    AdminWorkspaceAgentFilesResponse,
    AdminWorkspaceAgentFileUpdateResponse,
    InternalAgentDetailResponse,
    InternalAgentsListResponse,
    InternalObservabilityErrorsResponse,
    InternalObservabilityMetricsResponse,
    InternalObservabilityRunsResponse,
    InternalObservabilityTimelineResponse,
    InternalObservabilityToolsResponse,
    InternalObservabilityTraceResponse,
    InternalToolCatalogResponse,
)
from anyagent.server.app import create_app


class _RecordingProvider:
    def __init__(self) -> None:
        self.seen_bodies: list[dict] = []

    async def create_response(self, *, body: dict, idempotency_key: str | None = None, timeout_s: float = 60.0) -> Response:
        _ = idempotency_key, timeout_s
        self.seen_bodies.append(dict(body))
        return Response.model_validate(
            {
                "id": "resp_recorded",
                "object": "response",
                "created_at": 0,
                "model": str(body.get("model") or "unknown"),
                "output": [
                    ResponseOutputMessage(
                        id="msg_recorded",
                        role="assistant",
                        status="completed",
                        type="message",
                        content=[
                            ResponseOutputText(
                                type="output_text",
                                text="ok",
                                annotations=[],
                            ).model_dump(exclude_none=True, by_alias=True)
                        ],
                    ).model_dump(exclude_none=True, by_alias=True)
                ],
                "parallel_tool_calls": False,
                "tool_choice": "auto",
                "tools": list(body.get("tools") or []),
            }
        )


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


def test_studio_static_is_mounted_by_default_and_can_be_disabled(tmp_path: Path) -> None:
    asyncio.run(_run_studio_static_is_mounted_by_default_and_can_be_disabled(tmp_path))


def test_create_app_allows_exposed_workspace_without_main_agent(tmp_path: Path) -> None:
    _write_agent(tmp_path, "delivery-agent", exposed=True, prompt="Delivery agent\n")
    app = create_app(workspace_dir=tmp_path, api_key="user-key", admin_api_key="admin-key")
    assert sorted(app.state.anyagent.catalog.packs) == ["delivery-agent"]


def test_workspace_model_alias_applies_to_non_main_agent_request(tmp_path: Path, monkeypatch) -> None:
    asyncio.run(_run_workspace_model_alias_applies_to_non_main_agent_request(tmp_path, monkeypatch))


async def _run_workspace_model_alias_applies_to_non_main_agent_request(tmp_path: Path, monkeypatch) -> None:
    _write_agent(tmp_path, "delivery-agent", exposed=True, prompt="Delivery agent\n")
    (tmp_path / "models.yaml").write_text(
        "\n".join(
            [
                "default_model: travel-default",
                "providers:",
                "  openai:",
                "    kind: openai",
                "models:",
                "  travel-default:",
                "    provider: openai",
                "    model: gpt-5.5",
                "",
            ]
        ),
        encoding="utf-8",
    )
    agent_yaml = tmp_path / ".agents" / "agents" / "delivery-agent" / "agent.yaml"
    agent_yaml.write_text(
        agent_yaml.read_text(encoding="utf-8").replace("tools:", "model:\n  default: travel-default\ntools:"),
        encoding="utf-8",
    )
    provider = _RecordingProvider()
    monkeypatch.setattr("anyagent.server.app.get_default_model_provider", lambda: provider)
    app = create_app(workspace_dir=tmp_path, api_key="user-key", admin_api_key="admin-key")
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://testserver") as client:
        resp = await client.post(
            "/v1/responses",
            headers={"authorization": "Bearer user-key"},
            json={"input": "hello", "metadata": {"agent_id": "delivery-agent", "session_key": "s1"}},
        )
        assert resp.status_code == 200, resp.text

    assert provider.seen_bodies
    assert provider.seen_bodies[0]["model"] == "gpt-5.5"


async def _run_studio_static_is_mounted_by_default_and_can_be_disabled(tmp_path: Path) -> None:
    _write_agent(tmp_path, "main", exposed=True, prompt="Main agent\n")
    app = create_app(workspace_dir=tmp_path, api_key="user-key", admin_api_key="admin-key")
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://testserver") as client:
        resp = await client.get("/studio/")
        assert resp.status_code == 200
        assert "AnyAgent Studio" in resp.text
        assert "/studio/assets/" in resp.text
        resp_no_slash = await client.get("/studio")
        assert resp_no_slash.status_code == 200
        assert "AnyAgent Studio" in resp_no_slash.text

    disabled = create_app(
        workspace_dir=tmp_path,
        api_key="user-key",
        admin_api_key="admin-key",
        enable_studio=False,
    )
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=disabled), base_url="http://testserver") as client:
        resp = await client.get("/studio/")
        assert resp.status_code == 404


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

        admin_client = AnyAgent(api_key="admin-key", base_url="http://testserver", http=client)
        hidden_admin = await admin_client.admin.get_agent("hidden", include_prompt=True)
        assert hidden_admin.agent_id == "hidden"
        assert hidden_admin.exposed is False
        assert hidden_admin.agents_md.text == hidden_prompt


def test_admin_workspace_agent_files_update_and_reload(tmp_path: Path) -> None:
    asyncio.run(_run_admin_workspace_agent_files_update_and_reload(tmp_path))


def test_server_cors_origin_for_studio(tmp_path: Path) -> None:
    asyncio.run(_run_server_cors_origin_for_studio(tmp_path))


def test_admin_import_agent_skill(tmp_path: Path) -> None:
    asyncio.run(_run_admin_import_agent_skill(tmp_path))


def test_admin_install_agent_skill_from_registry(tmp_path: Path, monkeypatch) -> None:
    asyncio.run(_run_admin_install_agent_skill_from_registry(tmp_path, monkeypatch))


def test_admin_install_agent_skill_from_github(tmp_path: Path, monkeypatch) -> None:
    asyncio.run(_run_admin_install_agent_skill_from_github(tmp_path, monkeypatch))


def test_admin_create_agent_pack(tmp_path: Path) -> None:
    asyncio.run(_run_admin_create_agent_pack(tmp_path))


def test_admin_update_agent_default_skills(tmp_path: Path) -> None:
    asyncio.run(_run_admin_update_agent_default_skills(tmp_path))


def test_admin_update_agent_config(tmp_path: Path) -> None:
    asyncio.run(_run_admin_update_agent_config(tmp_path))


def test_internal_tools_catalog(tmp_path: Path) -> None:
    asyncio.run(_run_internal_tools_catalog(tmp_path))


def test_internal_observability_summary(tmp_path: Path) -> None:
    asyncio.run(_run_internal_observability_summary(tmp_path))


def test_internal_observability_runs(tmp_path: Path) -> None:
    asyncio.run(_run_internal_observability_runs(tmp_path))


def test_internal_observability_query_surfaces(tmp_path: Path) -> None:
    asyncio.run(_run_internal_observability_query_surfaces(tmp_path))


def test_postgres_telemetry_store_is_selected_for_external_storage(tmp_path: Path, monkeypatch) -> None:
    asyncio.run(_run_postgres_telemetry_store_is_selected_for_external_storage(tmp_path, monkeypatch))


def test_admin_tools_catalog(tmp_path: Path) -> None:
    asyncio.run(_run_admin_tools_catalog(tmp_path))


async def _run_server_cors_origin_for_studio(tmp_path: Path) -> None:
    _write_agent(
        tmp_path,
        "main",
        exposed=True,
        prompt="old prompt\n",
        sandbox_mode="disabled",
        requested_tool_names=[],
    )

    app = create_app(
        workspace_dir=tmp_path,
        api_key="user-key",
        admin_api_key="admin-key",
        cors_origins=["http://127.0.0.1:5177"],
    )
    transport = httpx.ASGITransport(app=app)

    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as http:
        resp = await http.options(
            "/internal/agents",
            headers={
                "Origin": "http://127.0.0.1:5177",
                "Access-Control-Request-Method": "GET",
                "Access-Control-Request-Headers": "authorization",
            },
        )
        assert resp.status_code == 200, resp.text
        assert resp.headers["access-control-allow-origin"] == "http://127.0.0.1:5177"


async def _run_admin_import_agent_skill(tmp_path: Path) -> None:
    _write_agent(
        tmp_path,
        "main",
        exposed=True,
        prompt="old prompt\n",
        sandbox_mode="disabled",
        requested_tool_names=[],
    )
    app = create_app(workspace_dir=tmp_path, api_key="user-key", admin_api_key="admin-key")
    transport = httpx.ASGITransport(app=app)

    skill_md = """---
name: imported-skill
description: Imported from Studio
---

Use this skill when testing the Studio import flow.
"""

    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as http:
        admin_client = AnyAgent(api_key="admin-key", base_url="http://testserver", http=http)
        user_client = AnyAgent(api_key="user-key", base_url="http://testserver", http=http)
        imported = await admin_client.admin.import_agent_skill(
            "main",
            {"directory_name": "imported-skill", "skill_md": skill_md},
        )
        assert isinstance(imported, AdminSkillImportResponse)
        assert imported.name == "imported-skill"
        assert imported.sha256 == hashlib.sha256(skill_md.encode("utf-8")).hexdigest()
        imported_dir = tmp_path / ".agents" / "agents" / "main" / "skills" / "imported-skill"
        assert (imported_dir / "SKILL.md").is_file()
        source_meta = json.loads((imported_dir / ".anyagent-skill-source.json").read_text(encoding="utf-8"))
        assert source_meta["channel"] == "local_upload"
        assert source_meta["source_ref"] == "imported-skill"
        assert source_meta["source_hash"] == imported.sha256

        skills = await user_client.skills.list(agent_id="main")
        assert any(skill.name == "imported-skill" and skill.scope == "agent" for skill in skills.skills)

        duplicate = await http.post(
            "/admin/workspace/agents/main/skills/import",
            headers={"Authorization": "Bearer admin-key"},
            json={"directory_name": "imported-skill", "skill_md": skill_md},
        )
        assert duplicate.status_code == 409, duplicate.text

        bad_name = await http.post(
            "/admin/workspace/agents/main/skills/import",
            headers={"Authorization": "Bearer admin-key"},
            json={"directory_name": "../escape", "skill_md": skill_md},
        )
        assert bad_name.status_code == 400, bad_name.text

        invalid = await http.post(
            "/admin/workspace/agents/main/skills/import",
            headers={"Authorization": "Bearer admin-key"},
            json={"directory_name": "invalid-skill", "skill_md": "no frontmatter"},
        )
        assert invalid.status_code == 400, invalid.text
        assert not (tmp_path / ".agents" / "agents" / "main" / "skills" / "invalid-skill" / "SKILL.md").exists()


async def _run_admin_install_agent_skill_from_registry(tmp_path: Path, monkeypatch) -> None:
    _write_agent(
        tmp_path,
        "main",
        exposed=True,
        prompt="old prompt\n",
        sandbox_mode="disabled",
        requested_tool_names=[],
    )

    install_count = {"value": 0}

    def fake_run(cmd, *, cwd, check, text, stdout, stderr, timeout):  # noqa: ANN001
        assert cmd[:5] == ["npx", "--yes", "skills", "add", "demo/package"]
        assert "--channel" in cmd and "skills.sh" in cmd
        assert "--agent" in cmd and "universal" in cmd
        skill_dir = Path(cwd) / ".agents" / "skills" / "demo-skill"
        skill_dir.mkdir(parents=True)
        install_count["value"] += 1
        description = "Installed from registry" if install_count["value"] == 1 else "Installed from registry v2"
        (skill_dir / "SKILL.md").write_text(
            f"""---
name: demo-skill
description: {description}
---

Use this skill for registry install tests.
""",
            encoding="utf-8",
        )
        (skill_dir / "references").mkdir()
        (skill_dir / "references" / "note.md").write_text("kept", encoding="utf-8")
        return subprocess.CompletedProcess(cmd, 0, stdout="installed")

    monkeypatch.setattr("anyagent.server.app.subprocess.run", fake_run)
    app = create_app(workspace_dir=tmp_path, api_key="user-key", admin_api_key="admin-key")
    transport = httpx.ASGITransport(app=app)

    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as http:
        admin_client = AnyAgent(api_key="admin-key", base_url="http://testserver", http=http)
        user_client = AnyAgent(api_key="user-key", base_url="http://testserver", http=http)
        installed = await admin_client.admin.install_agent_skill(
            "main",
            {"channel": "skills.sh", "package": "demo/package", "skill": "demo-skill"},
        )
        assert isinstance(installed, AdminSkillImportResponse)
        assert installed.name == "demo-skill"
        target = tmp_path / ".agents" / "agents" / "main" / "skills" / "demo-skill"
        assert (target / "SKILL.md").is_file()
        assert (target / "references" / "note.md").read_text(encoding="utf-8") == "kept"
        source_meta = json.loads((target / ".anyagent-skill-source.json").read_text(encoding="utf-8"))
        assert source_meta["channel"] == "skills.sh"
        assert source_meta["package"] == "demo/package"
        assert source_meta["skill"] == "demo-skill"
        assert source_meta["source_ref"] == "skills.sh:demo/package:demo-skill"
        assert source_meta["source_hash"]

        skills = await user_client.skills.list(agent_id="main")
        assert any(skill.name == "demo-skill" and skill.scope == "agent" for skill in skills.skills)

        check = await http.get(
            "/admin/workspace/agents/main/skills/demo-skill/update/check",
            headers={"Authorization": "Bearer admin-key"},
        )
        assert check.status_code == 200, check.text
        check_payload = check.json()
        assert check_payload["updatable"] is True
        assert check_payload["update_available"] is True
        assert check_payload["current_hash"] != check_payload["latest_hash"]

        applied = await http.post(
            "/admin/workspace/agents/main/skills/demo-skill/update/apply",
            headers={"Authorization": "Bearer admin-key"},
        )
        assert applied.status_code == 200, applied.text
        assert "registry v2" in (target / "SKILL.md").read_text(encoding="utf-8")

        bad = await http.post(
            "/admin/workspace/agents/main/skills/install",
            headers={"Authorization": "Bearer admin-key"},
            json={"package": "demo/package;rm -rf /", "skill": "demo-skill"},
        )
        assert bad.status_code == 400, bad.text


async def _run_admin_install_agent_skill_from_github(tmp_path: Path, monkeypatch) -> None:
    _write_agent(
        tmp_path,
        "main",
        exposed=True,
        prompt="old prompt\n",
        sandbox_mode="disabled",
        requested_tool_names=[],
    )

    def fake_run(cmd, *, cwd, check, text, stdout, stderr, timeout):  # noqa: ANN001
        assert cmd[:5] == ["git", "clone", "--depth", "1", "--branch"]
        assert "v1.2.3" in cmd
        repo_dir = Path(cmd[-1])
        skill_dir = repo_dir / "skills" / "github-skill"
        skill_dir.mkdir(parents=True)
        (skill_dir / "SKILL.md").write_text(
            """---
name: github-skill
description: Installed from GitHub
---

Use this skill for github install tests.
""",
            encoding="utf-8",
        )
        return subprocess.CompletedProcess(cmd, 0, stdout="cloned")

    monkeypatch.setattr("anyagent.server.app.subprocess.run", fake_run)
    app = create_app(workspace_dir=tmp_path, api_key="user-key", admin_api_key="admin-key")
    transport = httpx.ASGITransport(app=app)

    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as http:
        admin_client = AnyAgent(api_key="admin-key", base_url="http://testserver", http=http)
        user_client = AnyAgent(api_key="user-key", base_url="http://testserver", http=http)
        installed = await admin_client.admin.install_agent_skill(
            "main",
            {
                "channel": "github",
                "package": "demo/repo",
                "skill": "github-skill",
                "github_ref": "v1.2.3",
                "github_path": "skills/github-skill",
            },
        )
        assert installed.name == "github-skill"
        target = tmp_path / ".agents" / "agents" / "main" / "skills" / "github-skill"
        assert (target / "SKILL.md").is_file()
        source_meta = json.loads((target / ".anyagent-skill-source.json").read_text(encoding="utf-8"))
        assert source_meta["channel"] == "github"
        assert source_meta["github_repo"] == "demo/repo"
        assert source_meta["github_ref"] == "v1.2.3"
        assert source_meta["github_path"] == "skills/github-skill"
        assert source_meta["source_ref"] == "github:demo/repo:v1.2.3:skills/github-skill"

        skills = await user_client.skills.list(agent_id="main")
        assert any(skill.name == "github-skill" and skill.scope == "agent" for skill in skills.skills)


async def _run_admin_create_agent_pack(tmp_path: Path) -> None:
    _write_agent(
        tmp_path,
        "main",
        exposed=True,
        prompt="main prompt\n",
        sandbox_mode="disabled",
        requested_tool_names=[],
    )
    app = create_app(workspace_dir=tmp_path, api_key="user-key", admin_api_key="admin-key")
    transport = httpx.ASGITransport(app=app)

    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as http:
        admin_client = AnyAgent(api_key="admin-key", base_url="http://testserver", http=http)
        created = await admin_client.admin.create_agent(
            {
                "agent_id": "sales-agent",
                "instructions": "你是销售助手。\n",
                "requested_tool_names": ["core.web_fetch"],
                "sandbox_mode": "disabled",
                "exposed": True,
            }
        )
        assert isinstance(created, AdminAgentCreateResponse)
        assert created.agent.agent_id == "sales-agent"
        assert created.agent.agents_md.text == "你是销售助手。\n"
        assert "sales-agent" in created.reloaded_agent_ids
        agent_dir = tmp_path / ".agents" / "agents" / "sales-agent"
        assert (agent_dir / "agent.yaml").is_file()
        assert (agent_dir / "AGENTS.md").read_text(encoding="utf-8") == "你是销售助手。\n"
        assert (agent_dir / "mcp.json").read_text(encoding="utf-8") == '{"mcpServers": {}}\n'

        listed = await http.get("/internal/agents", headers={"Authorization": "Bearer user-key"})
        assert listed.status_code == 200, listed.text
        payload = InternalAgentsListResponse.model_validate(listed.json())
        assert [item.agent_id for item in payload.agents] == ["main", "sales-agent"]

        duplicate = await http.post(
            "/admin/workspace/agents",
            headers={"Authorization": "Bearer admin-key"},
            json={"agent_id": "sales-agent", "instructions": "again"},
        )
        assert duplicate.status_code == 409, duplicate.text

        bad = await http.post(
            "/admin/workspace/agents",
            headers={"Authorization": "Bearer admin-key"},
            json={"agent_id": "../escape", "instructions": "bad"},
        )
        assert bad.status_code == 400, bad.text


async def _run_admin_update_agent_default_skills(tmp_path: Path) -> None:
    _write_agent(
        tmp_path,
        "main",
        exposed=True,
        prompt="old prompt\n",
        sandbox_mode="disabled",
        requested_tool_names=[],
    )
    skill_dir = tmp_path / ".agents" / "agents" / "main" / "skills" / "demo-skill"
    skill_dir.mkdir(parents=True)
    (skill_dir / "SKILL.md").write_text(
        """---
name: demo-skill
description: Demo skill
---

Use this skill for selection tests.
""",
        encoding="utf-8",
    )
    app = create_app(workspace_dir=tmp_path, api_key="user-key", admin_api_key="admin-key")
    transport = httpx.ASGITransport(app=app)

    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as http:
        admin_client = AnyAgent(api_key="admin-key", base_url="http://testserver", http=http)
        user_client = AnyAgent(api_key="user-key", base_url="http://testserver", http=http)
        updated = await admin_client.admin.update_agent_skills("main", {"default_selected": ["demo-skill"]})
        assert updated.agent.skills.default_selected == ["demo-skill"]

        skills = await user_client.skills.list(agent_id="main")
        demo = next(skill for skill in skills.skills if skill.name == "demo-skill")
        assert demo.selected is True
        assert "default_selected:\n  - demo-skill\n" in (tmp_path / ".agents" / "agents" / "main" / "agent.yaml").read_text(
            encoding="utf-8"
        )

        bad = await http.put(
            "/admin/workspace/agents/main/skills",
            headers={"Authorization": "Bearer admin-key"},
            json={"default_selected": ["missing-skill"]},
        )
        assert bad.status_code == 400, bad.text


async def _run_admin_update_agent_config(tmp_path: Path) -> None:
    _write_agent(
        tmp_path,
        "main",
        exposed=True,
        prompt="main prompt\n",
        sandbox_mode="disabled",
        requested_tool_names=[],
    )
    _write_agent(
        tmp_path,
        "worker",
        exposed=False,
        prompt="worker prompt\n",
        sandbox_mode="disabled",
        requested_tool_names=[],
    )
    app = create_app(workspace_dir=tmp_path, api_key="user-key", admin_api_key="admin-key")
    transport = httpx.ASGITransport(app=app)

    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as http:
        admin_client = AnyAgent(api_key="admin-key", base_url="http://testserver", http=http)
        user_client = AnyAgent(api_key="user-key", base_url="http://testserver", http=http)

        updated = await admin_client.admin.update_agent_config(
            "worker",
            {
                "exposed": True,
                "requested_tool_names": [" exec ", "core.web_fetch", ""],
                "sandbox_mode": "local-unsafe",
                "spawn_allow_agent_ids": ["main"],
                "disabled_skill_paths": ["skills/alpha/SKILL.md", ""],
            },
        )
        assert updated.agent.agent_id == "worker"
        assert updated.agent.exposed is True
        assert updated.agent.tools.requested_tool_names == ["exec", "core.web_fetch"]
        assert updated.agent.sandbox["mode"] == "local-unsafe"
        assert updated.agent.multiagent["spawn_allow_agent_ids"] == ["main"]
        assert updated.agent.skills.disabled_paths == ["skills/alpha/SKILL.md"]

        worker_yaml = (tmp_path / ".agents" / "agents" / "worker" / "agent.yaml").read_text(encoding="utf-8")
        assert "exposed: true" in worker_yaml
        assert "requested_tool_names:\n  - exec\n  - core.web_fetch\n" in worker_yaml
        assert "mode: local-unsafe" in worker_yaml
        assert "disabled_paths:\n  - skills/alpha/SKILL.md\n" in worker_yaml

        listed = await user_client.agents.list()
        assert [item.agent_id for item in listed.agents] == ["main", "worker"]

        main_yaml_path = tmp_path / ".agents" / "agents" / "main" / "agent.yaml"
        before = main_yaml_path.read_text(encoding="utf-8")
        bad = await http.put(
            "/admin/workspace/agents/worker/config",
            headers={"Authorization": "Bearer admin-key"},
            json={"exposed": False},
        )
        assert bad.status_code == 200, bad.text

        before = main_yaml_path.read_text(encoding="utf-8")
        last_exposed = await http.put(
            "/admin/workspace/agents/main/config",
            headers={"Authorization": "Bearer admin-key"},
            json={"exposed": False},
        )
        assert last_exposed.status_code == 400, last_exposed.text
        assert main_yaml_path.read_text(encoding="utf-8") == before
        main = await user_client.agents.get("main")
        assert main.exposed is True


async def _run_admin_workspace_agent_files_update_and_reload(tmp_path: Path) -> None:
    _write_agent(
        tmp_path,
        "main",
        exposed=True,
        prompt="old prompt\n",
        sandbox_mode="disabled",
        requested_tool_names=[],
    )

    app = create_app(workspace_dir=tmp_path, api_key="user-key", admin_api_key="admin-key")
    transport = httpx.ASGITransport(app=app)

    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as http:
        admin_client = AnyAgent(api_key="admin-key", base_url="http://testserver", http=http)
        user_client = AnyAgent(api_key="user-key", base_url="http://testserver", http=http)
        files = await admin_client.admin.list_agent_files("main")
        assert isinstance(files, AdminWorkspaceAgentFilesResponse)
        by_kind = {item.kind: item for item in files.files}
        assert by_kind["agents_md"].text == "old prompt\n"
        assert by_kind["agent_yaml"].exists is True
        assert by_kind["mcp_json"].exists is False

        updated = await admin_client.admin.update_agent_file(
            "main",
            "agents_md",
            {"text": "new prompt\n", "expected_sha256": by_kind["agents_md"].sha256},
        )
        assert isinstance(updated, AdminWorkspaceAgentFileUpdateResponse)
        assert updated.file.text == "new prompt\n"
        assert "main" in updated.reloaded_agent_ids

        detail = await user_client.agents.get("main", include_prompt=True)
        assert detail.agents_md.text == "new prompt\n"

        stale = await http.put(
            "/admin/workspace/agents/main/files/agents_md",
            headers={"Authorization": "Bearer admin-key"},
            json={"text": "stale\n", "expected_sha256": by_kind["agents_md"].sha256},
        )
        assert stale.status_code == 409, stale.text

        bad_yaml = await http.put(
            "/admin/workspace/agents/main/files/agent_yaml",
            headers={"Authorization": "Bearer admin-key"},
            json={"text": "not: [valid"},
        )
        assert bad_yaml.status_code == 400, bad_yaml.text

        blank_mcp = await http.put(
            "/admin/workspace/agents/main/files/mcp_json",
            headers={"Authorization": "Bearer admin-key"},
            json={"text": ""},
        )
        assert blank_mcp.status_code == 400, blank_mcp.text
        assert (tmp_path / ".agents" / "main" / "mcp.json").exists() is False

        mcp = await admin_client.admin.update_agent_file(
            "main",
            "mcp_json",
            {"text": '{"mcpServers":{"demo":{"url":"https://example.com/mcp"},"off":{"enabled":false,"url":"https://off.example.com/mcp"}}}\n'},
        )
        assert mcp.file.exists is True
        assert mcp.file.sha256 is not None
        detail_after_mcp = await user_client.agents.get("main")
        assert detail_after_mcp.mcp.configured is True
        assert detail_after_mcp.mcp.server_labels == ["demo"]


async def _run_internal_tools_catalog(tmp_path: Path) -> None:
    _write_agent(
        tmp_path,
        "main",
        exposed=True,
        prompt="main prompt\n",
        sandbox_mode="local-unsafe",
        requested_tool_names=["exec"],
    )
    _write_agent(
        tmp_path,
        "hidden",
        exposed=False,
        prompt="hidden prompt\n",
        sandbox_mode="local-unsafe",
        requested_tool_names=["exec"],
    )
    app = create_app(workspace_dir=tmp_path, api_key="user-key", admin_api_key="admin-key")
    transport = httpx.ASGITransport(app=app)

    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as http:
        user_client = AnyAgent(api_key="user-key", base_url="http://testserver", http=http)
        catalog = await user_client.tools.catalog(agent_id="main", session_key="sess-tools")
        assert isinstance(catalog, InternalToolCatalogResponse)
        assert catalog.agent_id == "main"
        assert catalog.session_key == "sess-tools"
        assert catalog.toolset_version >= 1
        assert [tool.name for tool in catalog.tools] == ["exec"]
        exec_tool = next(tool for tool in catalog.tools if tool.name == "exec")
        assert exec_tool.kind == "command"
        assert catalog.tools[0].parameters is not None

        direct = await http.get(
            "/internal/tools/catalog",
            params={"agent_id": "main", "requested_tool_names": " exec,missing.tool "},
            headers={"Authorization": "Bearer user-key"},
        )
        assert direct.status_code == 200, direct.text
        direct_payload = InternalToolCatalogResponse.model_validate(direct.json())
        assert direct_payload.requested_tool_names == ["exec", "missing.tool"]
        assert [tool.name for tool in direct_payload.tools] == ["exec"]

        hidden = await http.get(
            "/internal/tools/catalog",
            params={"agent_id": "hidden"},
            headers={"Authorization": "Bearer user-key"},
        )
        assert hidden.status_code == 403, hidden.text


async def _run_internal_observability_summary(tmp_path: Path) -> None:
    _write_agent(
        tmp_path,
        "main",
        exposed=True,
        prompt="main prompt\n",
        sandbox_mode="disabled",
        requested_tool_names=[],
    )
    app = create_app(workspace_dir=tmp_path, api_key="user-key", admin_api_key="admin-key")
    transport = httpx.ASGITransport(app=app)
    response_id = "resp_summary"
    await app.state.anyagent.events.mark_started(response_id=response_id)
    await app.state.anyagent.events.append(
        response_id=response_id,
        event="anyagent.prompt.context",
        data=json.dumps(
            {
                "type": "anyagent.prompt.context",
                "response_id": response_id,
                "agent_id": "main",
                "session_key": "sess",
                "prompt_cache_key": "k",
                "fragment_kinds": ["agents_md"],
                "selected_skill_ids": ["skill-a", "skill-b"],
            }
        ),
    )
    await app.state.anyagent.events.append(
        response_id=response_id,
        event="anyagent.response.request",
        data=json.dumps(
            {
                "type": "anyagent.response.request",
                "response_id": response_id,
                "agent_id": "main",
                "session_key": "sess",
                "transcript_items": [{"role": "user", "content": "hello summary"}],
            }
        ),
    )
    await app.state.anyagent.events.append(
        response_id=response_id,
        event="anyagent.tool.planned",
        data=json.dumps({"type": "anyagent.tool.planned", "response_id": response_id, "tool_name": "exec"}),
    )
    await app.state.anyagent.events.append(
        response_id=response_id,
        event="response.completed",
        data=json.dumps(
            {
                "id": response_id,
                "object": "response",
                "status": "completed",
                "usage": {
                    "input_tokens": 11,
                    "output_tokens": 7,
                    "input_tokens_details": {"cached_tokens": 3},
                },
                "first_token_ms": 42,
                "total_latency_ms": 120,
                "output": [
                    {
                        "type": "message",
                        "role": "assistant",
                        "content": [{"type": "output_text", "text": "summary answer"}],
                    }
                ],
            }
        ),
    )
    await app.state.anyagent.events.mark_final(response_id=response_id, run_status="completed", effective_run_status="completed")
    await app.state.anyagent.run_store.create_started(
        response_id=response_id,
        agent_id="main",
        session_key="sess",
        stream=False,
        idempotency_key=None,
    )
    await app.state.anyagent.run_store.mark_final(
        response_id=response_id,
        status="completed",
        effective_status="completed",
        final_response_json={
            "id": response_id,
            "object": "response",
            "status": "completed",
            "output": [
                {
                    "type": "message",
                    "role": "assistant",
                    "content": [{"type": "output_text", "text": "summary answer"}],
                }
            ],
        },
    )

    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as http:
        resp = await http.get(
            "/internal/observability/summary",
            params={"response_id": response_id},
            headers={"Authorization": "Bearer user-key"},
        )
        assert resp.status_code == 200, resp.text
        payload = resp.json()
        assert payload["agent_id"] == "main"
        assert payload["session_key"] == "sess"
        assert payload["event_count"] == 4
        assert payload["tool_call_count"] == 1
        assert payload["skill_view_count"] == 2
        assert payload["turn_count"] == 1
        assert payload["input_chars"] == len("hello summary")
        assert payload["output_chars"] == len("summary answer")
        assert payload["turns"] == [
            {
                "index": 1,
                "input_chars": len("hello summary"),
                "output_chars": len("summary answer"),
            }
        ]
        assert payload["input_tokens"] == 11
        assert payload["output_tokens"] == 7
        assert payload["cached_input_tokens"] == 3
        assert payload["first_token_latency_ms"] == 42
        assert payload["total_response_latency_ms"] == 120


async def _run_internal_observability_runs(tmp_path: Path) -> None:
    _write_agent(
        tmp_path,
        "main",
        exposed=True,
        prompt="main prompt\n",
        sandbox_mode="disabled",
        requested_tool_names=[],
    )
    app = create_app(workspace_dir=tmp_path, api_key="user-key", admin_api_key="admin-key")
    transport = httpx.ASGITransport(app=app)
    await app.state.anyagent.run_store.create_started(
        response_id="resp_keep",
        agent_id="main",
        session_key="sess-a",
        stream=True,
        idempotency_key=None,
    )
    await app.state.anyagent.run_store.mark_final(
        response_id="resp_keep",
        status="completed",
        effective_status="completed",
        final_response_json={"id": "resp_keep"},
    )
    await app.state.anyagent.run_store.create_started(
        response_id="resp_other_session",
        agent_id="main",
        session_key="sess-b",
        stream=False,
        idempotency_key=None,
    )

    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as http:
        resp = await http.get(
            "/internal/observability/runs",
            params={"agent_id": "main", "session_key": "sess-a"},
            headers={"Authorization": "Bearer user-key"},
        )
        assert resp.status_code == 200, resp.text
        payload = InternalObservabilityRunsResponse.model_validate(resp.json())
        assert payload.agent_id == "main"
        assert payload.session_key == "sess-a"
        assert [item.response_id for item in payload.runs] == ["resp_keep"]
        assert payload.runs[0].status == "completed"
        assert payload.runs[0].effective_status == "completed"
        created_at_ms = payload.runs[0].created_at_ms
        max_created_at_ms = max(item.created_at_ms for item in await app.state.anyagent.run_store.list(agent_id="main"))

        resp = await http.get(
            "/internal/observability/runs",
            params={"agent_id": "main", "created_after_ms": max_created_at_ms + 1},
            headers={"Authorization": "Bearer user-key"},
        )
        assert resp.status_code == 200, resp.text
        assert InternalObservabilityRunsResponse.model_validate(resp.json()).runs == []

        resp = await http.get(
            "/internal/observability/runs",
            params={"agent_id": "main", "created_before_ms": created_at_ms - 1},
            headers={"Authorization": "Bearer user-key"},
        )
        assert resp.status_code == 200, resp.text
        assert InternalObservabilityRunsResponse.model_validate(resp.json()).runs == []


async def _run_internal_observability_query_surfaces(tmp_path: Path) -> None:
    _write_agent(
        tmp_path,
        "main",
        exposed=True,
        prompt="main prompt\n",
        sandbox_mode="disabled",
        requested_tool_names=[],
    )
    app = create_app(workspace_dir=tmp_path, api_key="user-key", admin_api_key="admin-key")
    transport = httpx.ASGITransport(app=app)
    response_id = "resp_observe"
    trace_id = "trace-observe"
    await app.state.anyagent.events.mark_started(response_id=response_id)
    await app.state.anyagent.run_store.create_started(
        response_id=response_id,
        agent_id="main",
        session_key="sess",
        stream=True,
        idempotency_key=None,
    )
    await app.state.anyagent.events.append(
        response_id=response_id,
        event="anyagent.prompt.context",
        data=json.dumps(
            {
                "type": "anyagent.prompt.context",
                "response_id": response_id,
                "agent_id": "main",
                "session_key": "sess",
                "trace_id": trace_id,
                "prompt_cache_key": "k",
                "fragment_kinds": ["agents_md"],
                "selected_skill_ids": [],
            }
        ),
    )
    await app.state.anyagent.events.append(
        response_id=response_id,
        event="anyagent.tool.planned",
        data=json.dumps(
            {
                "type": "anyagent.tool.planned",
                "response_id": response_id,
                "trace_id": trace_id,
                "tool_call_id": "call_1",
                "tool_name": "exec",
                "arguments": {"bytes": 2, "sha256": hashlib.sha256(b"{}").hexdigest()},
            }
        ),
    )
    await app.state.anyagent.events.append(
        response_id=response_id,
        event="anyagent.tool.result",
        data=json.dumps(
            {
                "type": "anyagent.tool.result",
                "response_id": response_id,
                "trace_id": trace_id,
                "tool_call_id": "call_1",
                "tool_name": "exec",
                "status": "error",
                "meta": {"duration_ms": 37, "audit_ref": "aud_1"},
                "error": {"type": "ToolError", "code": "boom", "message": "tool failed", "retryable": False},
            }
        ),
    )
    await app.state.anyagent.events.append(
        response_id=response_id,
        event="response.completed",
        data=json.dumps(
            {
                "id": response_id,
                "object": "response",
                "status": "completed",
                "usage": {"input_tokens": 5, "output_tokens": 3, "input_tokens_details": {"cached_tokens": 1}},
                "first_token_ms": 10,
                "total_latency_ms": 99,
            }
        ),
    )
    await app.state.anyagent.events.mark_final(response_id=response_id, run_status="completed", effective_run_status="completed")
    await app.state.anyagent.run_store.mark_final(
        response_id=response_id,
        status="completed",
        effective_status="completed",
        final_response_json={"id": response_id, "object": "response", "status": "completed"},
    )
    await app.state.anyagent.telemetry_store.ingest(
        NormalizedTelemetryEvent(
            source="workspace",
            type="anyagent.sandbox.workspace.checkpoint_failed",
            response_id=response_id,
            agent_id="main",
            session_key="sess",
            trace_id=trace_id,
            level="error",
            category="workspace",
            status="error",
            audit_ref="aud_workspace",
            message="checkpoint failed",
            payload={"failure_code": "checkpoint_failed"},
        )
    )
    await app.state.anyagent.telemetry_store.ingest_observability_event(
        emit_observability_event(
            "tool.policy.denied",
            category="audit",
            level="warning",
            payload={
                "response_id": response_id,
                "agent_id": "main",
                "session_key": "sess",
                "trace_id": trace_id,
                "status": "denied",
                "tool_name": "exec",
                "tool_call_id": "call_2",
                "audit_ref": "aud_policy",
                "policy": "deny",
            },
        )
    )

    emitter = get_observability_emitter()
    emitter.add_sink(app.state.anyagent.observability_event_sink)
    emitter.add_sink(app.state.anyagent.telemetry_observability_sink)
    try:
        emit_observability_event(
            "credential.audit",
            category="audit",
            level="error",
            payload={
                "response_id": response_id,
                "agent_id": "main",
                "session_key": "sess",
                "trace_id": trace_id,
                "audit_ref": "aud_2",
                "message": "credential denied",
            },
        )
    finally:
        emitter.remove_sink(app.state.anyagent.observability_event_sink)
        emitter.remove_sink(app.state.anyagent.telemetry_observability_sink)

    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as http:
        headers = {"Authorization": "Bearer user-key"}
        resp = await http.get(
            "/internal/observability/timeline",
            params={"agent_id": "main", "session_key": "sess", "trace_id": trace_id},
            headers=headers,
        )
        assert resp.status_code == 200, resp.text
        timeline = InternalObservabilityTimelineResponse.model_validate(resp.json())
        assert timeline.trace_id == trace_id
        assert {item.type for item in timeline.events} >= {
            "anyagent.tool.planned",
            "anyagent.tool.result",
            "credential.audit",
            "anyagent.sandbox.workspace.checkpoint_failed",
            "tool.policy.denied",
        }

        resp = await http.get("/internal/observability/metrics", params={"agent_id": "main"}, headers=headers)
        assert resp.status_code == 200, resp.text
        metrics = InternalObservabilityMetricsResponse.model_validate(resp.json())
        assert metrics.run_count == 1
        assert metrics.tool_call_count == 2
        assert metrics.error_count >= 3
        assert metrics.input_tokens == 5
        assert metrics.output_tokens == 3
        assert metrics.cached_input_tokens == 1
        assert metrics.max_response_latency_ms == 99

        resp = await http.get("/internal/observability/tools", params={"agent_id": "main"}, headers=headers)
        assert resp.status_code == 200, resp.text
        tools = InternalObservabilityToolsResponse.model_validate(resp.json())
        assert len(tools.tools) == 1
        assert tools.tools[0].tool_name == "exec"
        assert tools.tools[0].planned_count == 1
        assert tools.tools[0].result_count == 1
        assert tools.tools[0].error_count == 1
        assert tools.tools[0].avg_duration_ms == 37
        assert tools.tools[0].audit_refs == ["aud_1", "aud_policy"]

        resp = await http.get("/internal/observability/errors", params={"agent_id": "main"}, headers=headers)
        assert resp.status_code == 200, resp.text
        errors = InternalObservabilityErrorsResponse.model_validate(resp.json())
        assert {item.type for item in errors.errors} >= {
            "anyagent.tool.result",
            "credential.audit",
            "anyagent.sandbox.workspace.checkpoint_failed",
        }

        resp = await http.get(f"/internal/observability/traces/{trace_id}", headers=headers)
        assert resp.status_code == 200, resp.text
        trace = InternalObservabilityTraceResponse.model_validate(resp.json())
        assert trace.response_ids == [response_id]
        assert trace.audit_refs == ["aud_1", "aud_2", "aud_policy", "aud_workspace"]


async def _run_postgres_telemetry_store_is_selected_for_external_storage(tmp_path: Path, monkeypatch) -> None:
    _write_agent(
        tmp_path,
        "main",
        exposed=True,
        prompt="main prompt\n",
        sandbox_mode="disabled",
        requested_tool_names=[],
    )

    class FakePostgresTelemetryEventStore:
        def __init__(self, *, postgres_dsn: str, postgres_schema: str, schema_policy: str) -> None:
            self.postgres_dsn = postgres_dsn
            self.postgres_schema = postgres_schema
            self.schema_policy = schema_policy
            self.events: list[NormalizedTelemetryEvent] = []

        async def append(self, event: NormalizedTelemetryEvent) -> None:
            self.events.append(event)

        def append_sync(self, event: NormalizedTelemetryEvent) -> None:
            self.events.append(event)

        async def extend(self, events: list[NormalizedTelemetryEvent]) -> None:
            self.events.extend(events)

        async def list(self) -> list[NormalizedTelemetryEvent]:
            return list(self.events)

        async def dispose(self) -> None:
            return None

    monkeypatch.setenv("POSTGRES_DSN", "postgresql://user:pass@localhost:5432/anyagent")
    monkeypatch.setenv("POSTGRES_SCHEMA", "anyagent_test")
    monkeypatch.setenv("POSTGRES_SCHEMA_POLICY", "runtime_create")
    monkeypatch.setenv("STORAGE_MODE", "none")
    monkeypatch.setattr("anyagent.server.app.PostgresTelemetryEventStore", FakePostgresTelemetryEventStore)

    app = create_app(
        workspace_dir=tmp_path,
        api_key="user-key",
        admin_api_key="admin-key",
        storage_mode="external",
        event_store_backend="inmemory",
        run_store_backend="inmemory",
        session_store_backend="inmemory",
        session_lock_backend="inmemory",
    )
    store = app.state.anyagent.telemetry_event_store
    assert isinstance(store, FakePostgresTelemetryEventStore)
    assert store.postgres_dsn == "postgresql://user:pass@localhost:5432/anyagent"
    assert store.postgres_schema == "anyagent_test"
    assert store.schema_policy == "runtime_create"

    event = emit_observability_event(
        "credential.audit",
        category="audit",
        level="warning",
        payload={"agent_id": "main", "session_key": "sess", "trace_id": "trace_pg", "audit_ref": "aud_pg"},
    )
    app.state.anyagent.telemetry_observability_sink.emit(event)
    assert [item.audit_ref for item in await store.list()] == ["aud_pg"]


async def _run_admin_tools_catalog(tmp_path: Path) -> None:
    _write_agent(
        tmp_path,
        "main",
        exposed=True,
        prompt="main prompt\n",
        sandbox_mode="disabled",
        requested_tool_names=[],
    )
    app = create_app(workspace_dir=tmp_path, api_key="user-key", admin_api_key="admin-key")
    transport = httpx.ASGITransport(app=app)

    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as http:
        admin_client = AnyAgent(api_key="admin-key", base_url="http://testserver", http=http)
        catalog = await admin_client.admin.tool_catalog()
        assert isinstance(catalog, AdminToolCatalogResponse)
        assert catalog.toolset_version >= 1
        assert [tool.name for tool in catalog.tools] == [
            "admin.credential_set",
            "core.web_fetch",
            "core.web_search",
            "exec",
        ]
        exec_tool = next(tool for tool in catalog.tools if tool.name == "exec")
        assert exec_tool.kind == "command"

        user_catalog = await http.get("/admin/tools/catalog", headers={"Authorization": "Bearer user-key"})
        assert user_catalog.status_code == 401, user_catalog.text
