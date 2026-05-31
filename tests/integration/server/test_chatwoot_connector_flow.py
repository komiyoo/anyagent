from __future__ import annotations

import asyncio
import hashlib
import hmac
import json
import time
from pathlib import Path

import httpx
from openai.types.responses.response import Response
from openai.types.responses.response_function_tool_call import ResponseFunctionToolCall
from openai.types.responses.response_output_message import ResponseOutputMessage
from openai.types.responses.response_output_text import ResponseOutputText

from anyagent.server.app import create_app


ROOT = Path(__file__).resolve().parents[3]
REFERENCE_PLUGIN_ROOT = ROOT / "packages" / "anyagent" / "src" / "anyagent" / "plugins" / "builtin"


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


class _ChatwootFlowProvider:
    def __init__(self) -> None:
        self.bodies: list[dict] = []

    async def create_response(
        self,
        *,
        body: dict,
        idempotency_key: str | None = None,
        timeout_s: float = 60.0,
    ) -> Response:
        _ = idempotency_key, timeout_s
        self.bodies.append(json.loads(json.dumps(body)))
        if len(self.bodies) == 1:
            payload = {
                "id": "resp_chatwoot_1",
                "object": "response",
                "created_at": int(time.time()),
                "model": str(body.get("model") or "gpt-4o-mini"),
                "output": [
                    ResponseFunctionToolCall(
                        id="fc_chatwoot_handoff",
                        call_id="call_chatwoot_handoff",
                        name="gateway.handoff",
                        arguments=json.dumps(
                            {
                                "reason": "customer_request",
                                "suggested_team": "7",
                                "summary": "Customer requested a human agent.",
                            },
                            ensure_ascii=False,
                        ),
                        type="function_call",
                    ).model_dump(exclude_none=True, by_alias=True)
                ],
                "parallel_tool_calls": False,
                "tool_choice": "auto",
                "tools": list(body.get("tools") or []),
                "status": "completed",
            }
            return Response.model_validate(payload)
        payload = {
            "id": f"resp_chatwoot_{len(self.bodies)}",
            "object": "response",
            "created_at": int(time.time()),
            "model": str(body.get("model") or "gpt-4o-mini"),
            "output": [
                ResponseOutputMessage(
                    id="msg_chatwoot_reply",
                    type="message",
                    role="assistant",
                    status="completed",
                    content=[ResponseOutputText(type="output_text", text="Hello from anyagent", annotations=[])],
                ).model_dump(exclude_none=True, by_alias=True),
            ],
            "parallel_tool_calls": False,
            "tool_choice": "auto",
            "tools": list(body.get("tools") or []),
            "status": "completed",
        }
        return Response.model_validate(payload)


def test_chatwoot_connector_webhook_bridges_response_reply_and_handoff(tmp_path: Path, monkeypatch) -> None:
    asyncio.run(_run_chatwoot_connector_webhook_bridges_response_reply_and_handoff(tmp_path, monkeypatch))


async def _run_chatwoot_connector_webhook_bridges_response_reply_and_handoff(tmp_path: Path, monkeypatch) -> None:
    _write_main_agent(tmp_path)
    monkeypatch.setenv("ANYAGENT_CHATWOOT_WEBHOOK_SECRET", "test-chatwoot-secret")
    monkeypatch.setenv("ANYAGENT_CHATWOOT_CREDENTIAL_KIND", "webhook_secret")
    monkeypatch.setattr(
        "anyagent.server.routes.responses.get_default_model_provider",
        lambda: _ChatwootFlowProvider(),
    )

    app = create_app(
        workspace_dir=tmp_path,
        api_key="user-key",
        admin_api_key="admin-key",
        plugin_roots=[REFERENCE_PLUGIN_ROOT],
    )
    state = app.state.anyagent
    connector = state.gateway_registry.channel_connectors["chatwoot"]

    sent_messages: list[dict] = []
    handoffs: list[dict] = []

    async def _record_send_message(
        platform_conversation_id: str,
        content: str,
        *,
        content_type: str = "text",
        metadata: dict | None = None,
    ):
        sent_messages.append(
            {
                "platform_conversation_id": platform_conversation_id,
                "content": content,
                "content_type": content_type,
                "metadata": metadata,
            }
        )
        return type("SendResult", (), {"ok": True, "platform_message_id": "msg_1"})()

    async def _record_handoff(platform_conversation_id: str, reason, *, metadata=None):
        handoffs.append(
            {
                "platform_conversation_id": platform_conversation_id,
                "reason": getattr(reason, "value", str(reason)),
                "metadata": None if metadata is None else metadata.model_dump(exclude_none=True),
            }
        )
        return type("HandoffResult", (), {"ok": True, "reason": "handoff done"})()

    connector.outbound.send_message = _record_send_message
    connector.handoff.execute_handoff = _record_handoff

    payload = {
        "event": "message_created",
        "message_type": "incoming",
        "timestamp": 1717000000,
        "account": {"id": 1},
        "conversation": {"id": 42},
        "message": {"content": "I need to talk to a person"},
    }
    raw_body = json.dumps(payload).encode("utf-8")
    signature = hmac.new(
        b"test-chatwoot-secret",
        f"{payload['timestamp']}.{raw_body.decode('utf-8')}".encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as http:
        catalog = await http.get("/admin/plugins/catalog", headers={"Authorization": "Bearer admin-key"})
        assert catalog.status_code == 200, catalog.text
        loaded = {item["plugin_id"]: item for item in catalog.json()["loaded"]}
        assert "chatwoot-connector" in loaded

        response = await http.post(
            "/gateway/chatwoot/webhook",
            headers={"x-chatwoot-signature": signature, "x-chatwoot-timestamp": str(payload["timestamp"])},
            content=raw_body,
        )
        assert response.status_code == 200, response.text
        data = response.json()
        assert data["ok"] is True
        assert data["processed"] is True
        assert data["reply_sent"] is True
        assert data["handoff_triggered"] is True
        assert data["handoff_executed"] is True

    assert sent_messages == [
        {
            "platform_conversation_id": "42",
            "content": "Hello from anyagent",
            "content_type": "text",
            "metadata": None,
        }
    ]
    assert handoffs == [
        {
            "platform_conversation_id": "42",
            "reason": "customer_request",
            "metadata": {
                "suggested_team": "7",
                "summary": "Customer requested a human agent.",
            },
        }
    ]

    platform_events = await state.events.list_events(
        response_id="platform::chatwoot:1:42::message_created",
        last_seq=0,
        limit=10,
    )
    assert [item.event for item in platform_events.events] == ["platform.conversation.message_created"]
    persisted = json.loads(platform_events.events[0].data)
    assert persisted["session_key"] == "chatwoot:1:42"
    assert persisted["event_type"] == "user_message"
