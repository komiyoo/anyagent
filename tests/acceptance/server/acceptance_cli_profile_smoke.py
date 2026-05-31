from __future__ import annotations

import asyncio
import json
import time
from io import StringIO
from pathlib import Path
from unittest.mock import patch

import httpx
from openai.types.responses.response import Response
from openai.types.responses.response_completed_event import ResponseCompletedEvent
from openai.types.responses.response_created_event import ResponseCreatedEvent
from openai.types.responses.response_function_tool_call import ResponseFunctionToolCall
from openai.types.responses.response_output_message import ResponseOutputMessage
from openai.types.responses.response_output_text import ResponseOutputText

from anyagent.cli import main
from anyagent.protocol.workspace import WorkspaceDoctorReport
from anyagent.server.app import create_app


class _CliProfileProvider:
    def __init__(self) -> None:
        self.turn = 0
        self.seen_tools: list[list[dict]] = []

    async def create_response(self, *, body: dict, idempotency_key: str | None = None, timeout_s: float = 60.0) -> Response:
        _ = idempotency_key, timeout_s
        model = str(body.get("model") or "gpt-4o-mini")
        tools = list(body.get("tools") or [])
        self.seen_tools.append(tools)
        if self.turn == 0:
            self.turn += 1
            tool_name = str(tools[0]["name"])
            payload = {
                "id": "resp_cli_profile_turn_1",
                "object": "response",
                "created_at": int(time.time()),
                "model": model,
                "output": [
                    ResponseFunctionToolCall(
                        type="function_call",
                        call_id="call_cli_profile_1",
                        name=tool_name,
                        arguments=json.dumps(
                            {"cmd": "test -n \"$API_TOKEN\" && printf '%s' \"$BASE\"", "workdir": "work"},
                            ensure_ascii=False,
                        ),
                    ).model_dump(exclude_none=True, by_alias=True)
                ],
                "parallel_tool_calls": False,
                "tool_choice": "auto",
                "tools": tools,
            }
            return Response.model_validate(payload)

        payload = {
            "id": "resp_cli_profile_turn_2",
            "object": "response",
            "created_at": int(time.time()),
            "model": model,
            "output": [
                ResponseOutputMessage(
                    id="msg_cli_done",
                    type="message",
                    role="assistant",
                    status="completed",
                    content=[ResponseOutputText(type="output_text", text="done", annotations=[])],
                ).model_dump(exclude_none=True, by_alias=True)
            ],
            "parallel_tool_calls": False,
            "tool_choice": "auto",
            "tools": tools,
            "status": "completed",
        }
        return Response.model_validate(payload)

    async def create_response_stream_buffered(
        self,
        *,
        body: dict,
        idempotency_key: str | None = None,
        timeout_s: float | None = None,
    ) -> tuple[list, Response]:
        response = await self.create_response(body=body, idempotency_key=idempotency_key, timeout_s=timeout_s or 60.0)
        return [
            ResponseCreatedEvent(type="response.created", sequence_number=0, response=response),
            ResponseCompletedEvent(type="response.completed", sequence_number=1, response=response),
        ], response


def _write_workspace(root: Path) -> None:
    agent_dir = root / ".anyagent" / "agents" / "main"
    agent_dir.mkdir(parents=True, exist_ok=True)
    (agent_dir / "AGENTS.md").write_text("你是一个 CLI Profile 测试 agent。\n", encoding="utf-8")
    (agent_dir / "agent.yaml").write_text(
        "\n".join(
            [
                "exposed: true",
                "tools:",
                "  requested_tool_names: []",
                "  cli:",
                "    - name: app.demo",
                "      description: Demo CLI profile",
                "      cwd: repo",
                "      env:",
                "        inherit: none",
                "        set:",
                "          BASE: workspace",
                "      credentials:",
                "        - credential_id: cred_cli_profile",
                "          ref_kind: api_key",
                "          injection_target: env:API_TOKEN",
                "skills:",
                "  default_selected: []",
                "sandbox:",
                "  mode: local-unsafe",
                "multiagent:",
                "  spawn_allow_agent_ids: []",
            ]
        )
        + "\n",
        encoding="utf-8",
    )


def test_cli_profile_acceptance_smoke(tmp_path: Path, monkeypatch) -> None:
    asyncio.run(_run_cli_profile_acceptance_smoke(tmp_path=tmp_path, monkeypatch=monkeypatch))


async def _run_cli_profile_acceptance_smoke(*, tmp_path: Path, monkeypatch) -> None:
    _write_workspace(tmp_path)

    doctor_stdout = StringIO()
    with patch("sys.stdout", doctor_stdout):
        doctor_rc = main(["doctor", "--workspace", str(tmp_path), "--json"])
    assert doctor_rc == 0
    doctor_payload = WorkspaceDoctorReport.model_validate_json(doctor_stdout.getvalue())
    assert doctor_payload.ok is True
    assert any(item.code == "cli_profile_local_unsafe_exposed" for item in doctor_payload.findings)

    list_stdout = StringIO()
    with patch("sys.stdout", list_stdout):
        list_rc = main(["agent", "list", "--workspace", str(tmp_path), "--json"])
    assert list_rc == 0
    list_payload = json.loads(list_stdout.getvalue())
    assert list_payload["agents"][0]["agent_id"] == "main"
    assert list_payload["agents"][0]["requested_tool_names"] == []
    assert "cred_cli_profile" not in list_stdout.getvalue()
    assert "cli-secret" not in list_stdout.getvalue()

    provider = _CliProfileProvider()
    monkeypatch.setattr("anyagent.server.routes.responses.get_default_model_provider", lambda: provider)
    app = create_app(
        workspace_dir=tmp_path,
        api_key="user-key",
        admin_api_key="admin-key",
        sandbox_root_dir=tmp_path / ".sandbox",
    )

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        set_resp = await client.post(
            "/admin/credentials",
            headers={"Authorization": "Bearer admin-key"},
            json={
                "credential_id": "cred_cli_profile",
                "kind": "api_key",
                "value": "cli-secret",
                "scope": {"level": "global"},
            },
        )
        assert set_resp.status_code == 200, set_resp.text

        manifest = await client.post(
            "/internal/tools/manifest",
            headers={"Authorization": "Bearer admin-key"},
            json={"agent_id": "main", "session_key": "sess-cli", "requested_tool_names": ["app.demo"]},
        )
        assert manifest.status_code == 200, manifest.text
        manifest_json = manifest.json()
        assert [tool["name"] for tool in manifest_json["tools"]] == ["app.demo"]
        assert manifest_json["tools"][0]["x-anyagent-kind"] == "command"
        assert manifest_json["tools"][0]["x-anyagent-cli"]["credential_targets"] == ["env:API_TOKEN"]
        assert "credential_id" not in json.dumps(manifest_json["tools"][0], ensure_ascii=False)
        assert "cli-secret" not in json.dumps(manifest_json["tools"][0], ensure_ascii=False)

        response = await client.post(
            "/v1/responses",
            headers={"Authorization": "Bearer user-key"},
            json={
                "model": "gpt-4o-mini",
                "input": "run the demo cli profile",
                "metadata": {"session_key": "sess-cli"},
            },
        )
        assert response.status_code == 200, response.text
        payload = response.json()
        assert payload["status"] == "completed"
        response_id = payload["id"]

        events = await client.get(
            "/internal/events/list",
            headers={"Authorization": "Bearer user-key"},
            params={"response_id": response_id, "last_seq": 0, "limit": 50},
        )
        assert events.status_code == 200, events.text
        event_items = events.json()["events"]
        event_names = [item.get("event") for item in event_items]
        assert "anyagent.tool.planned" in event_names
        assert "anyagent.tool.result" in event_names
        assert "anyagent.command.planned" in event_names
        assert "anyagent.command.result" in event_names

        tool_results = [item for item in event_items if item.get("event") == "anyagent.tool.result"]
        assert tool_results, event_items
        raw_tool_payload = tool_results[0]["data"]
        tool_payload = json.loads(raw_tool_payload) if isinstance(raw_tool_payload, str) else raw_tool_payload
        assert tool_payload["tool_name"] == "app.demo"
        assert "profile" in tool_payload["output"]["preview"]
        assert "cli-secret" not in json.dumps(event_items, ensure_ascii=False)

    assert provider.seen_tools, "provider should have received manifest tools"
    first_tools = provider.seen_tools[0]
    assert first_tools[0]["name"] == "app_demo"
    assert "x-anyagent-cli" not in first_tools[0]
    assert "x-anyagent-kind" not in first_tools[0]
