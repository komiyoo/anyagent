from __future__ import annotations

import asyncio
import json
from pathlib import Path

import httpx

from anyagent import AnyAgent
from anyagent.server.app import create_app
from anyagent.tool_runtime import create_tool_runtime_app
from anyagent.types import AdminCredentialSetRequest, HealthResponse, NormalizedTelemetryEvent


def _write_workspace(root: Path) -> None:
    agent_dir = root / ".anyagent" / "agents" / "main"
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


def test_sdk_admin_plugin_catalog_matches_tool_runtime(tmp_path: Path) -> None:
    asyncio.run(_run_sdk_admin_plugin_catalog_matches_tool_runtime(tmp_path))


def test_sdk_tools_explain_composes_agent_skill_and_probe_context(tmp_path: Path) -> None:
    asyncio.run(_run_sdk_tools_explain_composes_agent_skill_and_probe_context(tmp_path))


def test_sdk_admin_skill_update_helpers_match_server(tmp_path: Path, monkeypatch) -> None:
    asyncio.run(_run_sdk_admin_skill_update_helpers_match_server(tmp_path, monkeypatch))


def test_sdk_observability_namespace_matches_server(tmp_path: Path) -> None:
    asyncio.run(_run_sdk_observability_namespace_matches_server(tmp_path))


def test_sdk_response_replay_helpers_match_server(tmp_path: Path) -> None:
    asyncio.run(_run_sdk_response_replay_helpers_match_server(tmp_path))


def test_sdk_create_merges_skill_mentions(tmp_path: Path) -> None:
    asyncio.run(_run_sdk_create_merges_skill_mentions(tmp_path))


def test_sdk_public_types_entrypoint_exports_boundary_models() -> None:
    request = AdminCredentialSetRequest.model_validate(
        {
            "credential_id": "search_api_key",
            "kind": "api_key",
            "value": "secret-value",
            "scope": {"level": "agent", "agent_id": "main"},
        }
    )
    health = HealthResponse.model_validate({"ok": True, "workspace": "/tmp/ws", "agent_ids": ["main"]})

    assert request.scope.agent_id == "main"
    assert health.agent_ids == ["main"]


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
        assert deleted.deleted is True
        assert deleted.credential_id == "search_api_key"

        listed_after = await client.admin.list_credentials()
        assert listed_after.credentials == []


async def _run_sdk_observability_namespace_matches_server(tmp_path: Path) -> None:
    _write_workspace(tmp_path)
    app = create_app(workspace_dir=tmp_path, api_key="user-key", admin_api_key="admin-key")
    response_id = "resp_sdk_observe"
    trace_id = "trace-sdk"
    await app.state.anyagent.run_store.create_started(
        response_id=response_id,
        agent_id="main",
        session_key="sdk",
        stream=False,
        idempotency_key=None,
    )
    await app.state.anyagent.events.mark_started(response_id=response_id)
    await app.state.anyagent.telemetry_store.ingest(
        NormalizedTelemetryEvent(
            source="audit",
            type="tool.policy.denied",
            response_id=response_id,
            agent_id="main",
            session_key="sdk",
            trace_id=trace_id,
            level="warning",
            category="audit",
            status="denied",
            tool_name="exec",
            tool_call_id="call_sdk",
            audit_ref="aud_sdk",
            payload={"policy": "deny"},
        )
    )
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as http:
        client = AnyAgent(api_key="user-key", base_url="http://testserver", http=http)

        runs = await client.observability.runs(agent_id="main", session_key="sdk")
        assert [item.response_id for item in runs.runs] == [response_id]

        timeline = await client.observability.timeline(agent_id="main", trace_id=trace_id)
        assert [item.type for item in timeline.events] == ["tool.policy.denied"]

        tools = await client.observability.tools(agent_id="main")
        assert tools.tools[0].tool_name == "exec"
        assert tools.tools[0].audit_refs == ["aud_sdk"]

        trace = await client.observability.trace(trace_id)
        assert trace.response_ids == [response_id]
        assert trace.audit_refs == ["aud_sdk"]


async def _run_sdk_response_replay_helpers_match_server(tmp_path: Path) -> None:
    _write_workspace(tmp_path)
    app = create_app(workspace_dir=tmp_path, api_key="user-key", admin_api_key="admin-key")
    response_id = "resp_sdk_replay"
    await app.state.anyagent.events.mark_started(response_id=response_id)
    await app.state.anyagent.events.append(
        response_id=response_id,
        event="anyagent.context.compacted",
        data='{"type":"anyagent.context.compacted","response_id":"resp_sdk_replay","tokens_before":100,"tokens_after":40,"items_before":10,"items_after":4}',
    )
    await app.state.anyagent.events.append(
        response_id=response_id,
        event="anyagent.agent.loop_warning",
        data='{"type":"anyagent.agent.loop_warning","response_id":"resp_sdk_replay","tool_signature":"exec:{}","repeat_count":2,"window_size":4}',
    )
    await app.state.anyagent.events.append(
        response_id=response_id,
        event="anyagent.subagent.spawned",
        data='{"type":"anyagent.subagent.spawned","response_id":"resp_sdk_replay","parent_response_id":"resp_sdk_replay","child_response_id":"resp_child","agent_id":"researcher","depth":1,"task_description":{"bytes":5,"sha256":"2cf24dba5fb0a30e26e83b2ac5b9e29e1b161e5c1fa7425e73043362938b9824","preview":"hello","preview_truncated":false}}',
    )
    transport = httpx.ASGITransport(app=app)

    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as http:
        client = AnyAgent(api_key="user-key", base_url="http://testserver", http=http)

        prompt_context = await client.events.prompt_context(response_id)
        assert prompt_context.response_id == response_id
        assert prompt_context.fallback == "missing"

        tool_executions = await client.events.tool_executions(response_id)
        assert tool_executions.response_id == response_id
        assert tool_executions.tool_executions == []

        model_request = await client.events.model_request(response_id)
        assert model_request.response_id == response_id
        assert model_request.applied_body is None

        summary = await client.observability.summary(response_id)
        assert summary.compaction_count == 1
        assert summary.loop_warnings_count == 1
        assert summary.subagent_spawns == 1


async def _run_sdk_create_merges_skill_mentions(tmp_path: Path) -> None:
    _write_workspace(tmp_path)
    seen_body: dict[str, object] = {}

    async def handler(request: httpx.Request) -> httpx.Response:
        nonlocal seen_body
        seen_body = dict(json.loads(request.content.decode("utf-8")))
        return httpx.Response(200, json={"id": "resp_skill_mentions", "object": "response", "status": "completed"})

    transport = httpx.MockTransport(handler)
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as http:
        client = AnyAgent(api_key="user-key", base_url="http://testserver", http=http)
        created = await client.create(
            {"model": "test-model", "input": "hello", "metadata": {"skills": ["existing"]}},
            skills=["repo-helper", "existing"],
            x_agent_id="main",
            idempotency_key="idem-1",
        )

    assert created["id"] == "resp_skill_mentions"
    assert seen_body["stream"] is False
    assert seen_body["metadata"] == {"skills": ["existing", "repo-helper"]}


async def _run_sdk_admin_plugin_catalog_matches_tool_runtime(tmp_path: Path) -> None:
    _write_workspace(tmp_path)
    agent_yaml = tmp_path / ".anyagent" / "agents" / "main" / "agent.yaml"
    agent_yaml.write_text(
        """
exposed: true
tools:
  requested_tool_names:
    - demo.echo
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
    plugin_dir = tmp_path / "plugins" / "demo"
    plugin_dir.mkdir(parents=True, exist_ok=True)
    (plugin_dir / "plugin.json").write_text(
        """
{
  "plugin_id": "demo",
  "description": "Demo connector.",
  "channels": ["demo"],
  "entrypoint": "plugin.py:register",
  "docs": ["README.md"],
  "schemas": ["schemas/config.schema.json"],
  "tests": ["tests/smoke.py"]
}
""".lstrip(),
        encoding="utf-8",
    )
    (plugin_dir / "README.md").write_text("# Demo connector\n", encoding="utf-8")
    (plugin_dir / "schemas").mkdir()
    (plugin_dir / "schemas" / "config.schema.json").write_text('{"type":"object"}\n', encoding="utf-8")
    (plugin_dir / "tests").mkdir()
    (plugin_dir / "tests" / "smoke.py").write_text("def test_smoke():\n    assert True\n", encoding="utf-8")
    (plugin_dir / "plugin.py").write_text(
        """
from anyagent.tool_runtime.models import ToolDefinition

async def echo(args, context):
    return args["text"]

def register(api):
    api.registerTool(
        ToolDefinition(
            name="demo.echo",
            description="Echo text.",
            category="channel",
            kind="command",
            parameters={
                "type": "object",
                "additionalProperties": False,
                "required": ["text"],
                "properties": {"text": {"type": "string"}},
            },
        ),
        echo,
    )
""".lstrip(),
        encoding="utf-8",
    )

    app = create_tool_runtime_app(
        workspace_dir=tmp_path,
        internal_key="internal-key",
        admin_api_key="admin-key",
        plugin_roots=["plugins"],
    )
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as http:
        client = AnyAgent(api_key="admin-key", base_url="http://testserver", http=http)
        catalog = await client.admin.plugin_catalog()

        assert catalog.plugin_roots == [str(tmp_path / "plugins")]
        assert catalog.errors == []
        assert len(catalog.loaded) == 1
        loaded = catalog.loaded[0]
        assert loaded.plugin_id == "demo"
        assert loaded.description == "Demo connector."
        assert loaded.channels == ["demo"]
        assert loaded.plugin_dir == str(plugin_dir)
        assert loaded.tools[0].name == "demo.echo"
        assert loaded.tools[0].category == "channel"
        assert loaded.cite == {
            "manifest": str(plugin_dir / "plugin.json"),
            "entrypoint": str(plugin_dir / "plugin.py"),
        }
        assert loaded.docs == [str(plugin_dir / "README.md")]
        assert loaded.schemas == [str(plugin_dir / "schemas" / "config.schema.json")]
        assert loaded.tests == [str(plugin_dir / "tests" / "smoke.py")]


async def _run_sdk_tools_explain_composes_agent_skill_and_probe_context(tmp_path: Path) -> None:
    _write_workspace(tmp_path)
    agent_yaml = tmp_path / ".anyagent" / "agents" / "main" / "agent.yaml"
    agent_yaml.write_text(
        """
exposed: true
tools:
  requested_tool_names:
    - core.web_fetch
skills:
  default_selected:
    - demo-skill
sandbox:
  mode: local-unsafe
multiagent:
  spawn_allow_agent_ids: []
""".strip()
        + "\n",
        encoding="utf-8",
    )
    skill_dir = tmp_path / ".anyagent" / "skills" / "demo-skill"
    skill_dir.mkdir(parents=True, exist_ok=True)
    (skill_dir / "SKILL.md").write_text(
        """
---
name: demo-skill
description: Demo skill
---

Use this skill for command tasks.
""".lstrip(),
        encoding="utf-8",
    )
    (skill_dir / "agents").mkdir(parents=True, exist_ok=True)
    (skill_dir / "agents" / "openai.yaml").write_text(
        """
dependencies:
  tools:
    - transport: core
      value: core.web_search
""".strip()
        + "\n",
        encoding="utf-8",
    )
    app = create_app(workspace_dir=tmp_path, api_key="user-key", admin_api_key="admin-key")
    transport = httpx.ASGITransport(app=app)

    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as http:
        client = AnyAgent(api_key="user-key", base_url="http://testserver", http=http)

        search_explanation = await client.tools.explain("core.web_search", agent_id="main", include_probe=False)
        assert search_explanation.visible is True
        assert search_explanation.visible_without_probe is True
        assert any("demo-skill" in skill_id for skill_id in search_explanation.selected_skill_ids)
        assert search_explanation.requested_patterns == ["core.web_fetch", "core.web_search"]
        assert [source.source for source in search_explanation.request_sources] == ["agent", "skill"]
        assert search_explanation.effective_tool is not None
        assert search_explanation.effective_tool.name == "core.web_search"
        assert "visible_by_default" in search_explanation.notes

        exec_explanation = await client.tools.explain("exec", agent_id="main")
        assert exec_explanation.visible is False
        assert exec_explanation.effective_tool is None
        assert exec_explanation.request_sources[-1].source == "probe"
        assert exec_explanation.requested_patterns == ["core.web_fetch", "core.web_search", "exec"]
        assert "tool_not_visible" in exec_explanation.notes

        missing_explanation = await client.tools.explain("missing.tool", agent_id="main")
        assert missing_explanation.visible is False
        assert missing_explanation.effective_tool is None
        assert "tool_not_visible" in missing_explanation.notes


async def _run_sdk_admin_skill_update_helpers_match_server(tmp_path: Path, monkeypatch) -> None:
    _write_workspace(tmp_path)

    calls: list[list[str]] = []

    def fake_run(cmd: list[str], *, cwd: str, **_: object) -> object:
        calls.append(cmd)
        skill_dir = Path(cwd) / ".anyagent" / "skills" / "demo-skill"
        skill_dir.mkdir(parents=True, exist_ok=True)
        version = "v1" if len(calls) == 1 else "v2"
        (skill_dir / "SKILL.md").write_text(
            f"---\nname: demo-skill\ndescription: Demo skill\n---\n\nregistry {version}\n",
            encoding="utf-8",
        )

        class Completed:
            returncode = 0
            stdout = ""
            stderr = ""

        return Completed()

    monkeypatch.setattr("anyagent.server.handlers.skill_install.subprocess.run", fake_run)
    app = create_app(workspace_dir=tmp_path, api_key="user-key", admin_api_key="admin-key")
    transport = httpx.ASGITransport(app=app)

    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as http:
        client = AnyAgent(api_key="admin-key", base_url="http://testserver", http=http)
        installed = await client.admin.install_agent_skill(
            "main",
            {"channel": "skills.sh", "package": "demo/package", "skill": "demo-skill"},
        )
        assert installed.name == "demo-skill"

        check = await client.admin.check_agent_skill_update("main", "demo-skill")
        assert check.agent_id == "main"
        assert check.directory_name == "demo-skill"
        assert check.updatable is True
        assert check.update_available is True
        assert check.current_hash != check.latest_hash

        applied = await client.admin.apply_agent_skill_update("main", "demo-skill")
        assert applied.name == "demo-skill"
        assert "registry v2" in (tmp_path / ".anyagent" / "agents" / "main" / "skills" / "demo-skill" / "SKILL.md").read_text(
            encoding="utf-8"
        )
