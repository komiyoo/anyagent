from __future__ import annotations

import asyncio
import json
from pathlib import Path

import httpx
from openai.types.responses.response import Response
from openai.types.responses.response_output_message import ResponseOutputMessage
from openai.types.responses.response_output_text import ResponseOutputText

from anyagent.server.app import create_app


ROOT = Path(__file__).resolve().parents[3]
REFERENCE_PLUGIN_ROOT = ROOT / "packages" / "anyagent" / "src" / "anyagent" / "plugins" / "builtin"


class _RecordingProvider:
    async def create_response(self, *, body: dict, idempotency_key: str | None = None, timeout_s: float = 60.0) -> Response:
        _ = idempotency_key, timeout_s
        return Response.model_validate(
            {
                "id": "resp_plugin_lifecycle",
                "object": "response",
                "created_at": 0,
                "model": str(body.get("model") or "unknown"),
                "output": [
                    ResponseOutputMessage(
                        id="msg_plugin_lifecycle",
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


def _write_main_agent(root: Path) -> None:
    agent_dir = root / ".anyagent" / "agents" / "main"
    agent_dir.mkdir(parents=True, exist_ok=True)
    (agent_dir / "AGENTS.md").write_text("You are main.\n", encoding="utf-8")
    (agent_dir / "agent.yaml").write_text(
        "\n".join(
            [
                "exposed: true",
                "tools:",
                "  requested_tool_names:",
                "    - app.lifecycle_echo.echo",
                "skills:",
                "  default_selected: []",
                "sandbox:",
                "  mode: disabled",
            ]
        )
        + "\n",
        encoding="utf-8",
    )


def test_gateway_loads_reference_plugin_catalog_tool_and_hooks(tmp_path: Path, monkeypatch) -> None:
    asyncio.run(_run_gateway_loads_reference_plugin_catalog_tool_and_hooks(tmp_path, monkeypatch))


async def _run_gateway_loads_reference_plugin_catalog_tool_and_hooks(tmp_path: Path, monkeypatch) -> None:
    _write_main_agent(tmp_path)
    events_file = tmp_path / "plugin-events.jsonl"
    monkeypatch.setenv("ANYAGENT_LIFECYCLE_ECHO_EVENTS_FILE", str(events_file))
    monkeypatch.setattr("anyagent.server.routes.responses.get_default_model_provider", lambda: _RecordingProvider())

    app = create_app(
        workspace_dir=tmp_path,
        api_key="user-key",
        admin_api_key="admin-key",
        plugin_roots=[REFERENCE_PLUGIN_ROOT],
    )
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as http:
        catalog = await http.get("/admin/plugins/catalog", headers={"Authorization": "Bearer admin-key"})
        assert catalog.status_code == 200, catalog.text
        payload = catalog.json()
        loaded = {item["plugin_id"]: item for item in payload["loaded"]}
        item = loaded["anyagent.lifecycle_echo"]
        assert item["declared_hooks"] == ["on_agent_end", "on_agent_start"]
        assert item["declared_skills"] == []
        assert [tool["name"] for tool in item["tools"]] == ["app.lifecycle_echo.echo"]

        capabilities = await http.get("/admin/plugins/capabilities", headers={"Authorization": "Bearer admin-key"})
        assert capabilities.status_code == 200, capabilities.text
        caps = {(item["host"], item["capability"]): item for item in capabilities.json()["capabilities"]}
        assert caps[("gateway", "hooks")]["status"] == "preview"
        assert caps[("tool_runtime", "tools")]["status"] == "stable"

        response = await http.post(
            "/v1/responses",
            headers={"Authorization": "Bearer user-key"},
            json={"input": "hello", "metadata": {"agent_id": "main", "session_key": "s1"}},
        )
        assert response.status_code == 200, response.text

    events = [json.loads(line) for line in events_file.read_text(encoding="utf-8").splitlines()]
    assert [event["event"] for event in events] == ["on_agent_start", "on_agent_end"]
    assert {event["agent_id"] for event in events} == {"main"}
    assert {event["session_key"] for event in events} == {"s1"}
    assert events[1]["metadata"]["status"] == "completed"
