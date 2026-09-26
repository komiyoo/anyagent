from __future__ import annotations

import asyncio
import hashlib
import hmac
import json
import logging
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


class _SlowChatwootProvider:
    def __init__(self, release: asyncio.Event) -> None:
        self.release = release
        self.started = asyncio.Event()

    async def create_response(
        self,
        *,
        body: dict,
        idempotency_key: str | None = None,
        timeout_s: float = 60.0,
    ) -> Response:
        _ = body, idempotency_key, timeout_s
        self.started.set()
        await self.release.wait()
        return Response.model_validate(
            {
                "id": "resp_chatwoot_async",
                "object": "response",
                "created_at": int(time.time()),
                "model": "gpt-4o-mini",
                "output": [
                    ResponseOutputMessage(
                        id="msg_chatwoot_async",
                        type="message",
                        role="assistant",
                        status="completed",
                        content=[ResponseOutputText(type="output_text", text="Async hello", annotations=[])],
                    ).model_dump(exclude_none=True, by_alias=True),
                ],
                "parallel_tool_calls": False,
                "tool_choice": "auto",
                "tools": [],
                "status": "completed",
            }
        )


def test_chatwoot_connector_webhook_bridges_response_reply_and_handoff(tmp_path: Path, monkeypatch, caplog) -> None:
    asyncio.run(_run_chatwoot_connector_webhook_bridges_response_reply_and_handoff(tmp_path, monkeypatch, caplog))


async def _run_chatwoot_connector_webhook_bridges_response_reply_and_handoff(tmp_path: Path, monkeypatch, caplog) -> None:
    _write_main_agent(tmp_path)
    monkeypatch.setenv("CHATWOOT_WEBHOOK_SECRET", "test-chatwoot-secret")
    monkeypatch.setenv("CHATWOOT_CREDENTIAL_KIND", "webhook_secret")
    monkeypatch.setenv("CHATWOOT_ASYNC_PROCESSING", "false")
    caplog.set_level(logging.INFO)
    provider = _ChatwootFlowProvider()
    monkeypatch.setattr(
        "anyagent.server.routes.responses.get_default_model_provider",
        lambda: provider,
    )

    app = create_app(
        workspace_dir=tmp_path,
        api_key="user-key",
        admin_api_key="admin-key",
        plugin_roots=[REFERENCE_PLUGIN_ROOT],
    )
    state = app.state.anyagent
    connector = state.gateway_registry.channel_connectors["chatwoot"]

    response_requests: list[dict] = []

    @app.middleware("http")
    async def capture_response_request(request, call_next):
        if request.url.path == "/v1/responses":
            response_requests.append(await request.json())
        return await call_next(request)

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
        "id": 1001,
        "timestamp": 1717000000,
        "account": {"id": 1},
        "conversation": {
            "id": 42,
            "custom_attributes": {
                "lt_entry_url": "https://lyriktrip.com/guides/china",
                "lt_entry_title": "China Travel Guide",
                "lt_entry_path": "/guides/china",
                "lt_quick_prompt_id": "page.guides/china.appsINeed",
            },
        },
        "event_info": {
            "referer": "https://lyriktrip.com/guides/china?utm_source=chat",
            "widget_language": "en",
            "browser_language": "en-US",
        },
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
    assert persisted["metadata"]["message_id"] == "1001"
    assert persisted["metadata"]["message_type"] == "incoming"
    assert persisted["metadata"]["chatwoot_page_context"] == {
        "referer": "https://lyriktrip.com/guides/china?utm_source=chat",
        "entry_url": "https://lyriktrip.com/guides/china",
        "entry_path": "/guides/china",
        "entry_title": "China Travel Guide",
        "lt_quick_prompt_id": "page.guides/china.appsINeed",
        "widget_language": "en",
        "browser_language": "en-US",
    }
    page_context = response_requests[0]["metadata"]["context"]["channel"]["ext"]["chatwoot_page_context"]
    assert page_context["lt_quick_prompt_id"] == "page.guides/china.appsINeed"
    assert response_requests[0]["metadata"]["context"]["channel"]["message_id"] == "1001"
    assert provider.bodies
    rendered_input = json.dumps(provider.bodies[0].get("input"), ensure_ascii=False)
    assert "Chatwoot page context" in rendered_input
    assert "https://lyriktrip.com/guides/china" in rendered_input
    assert "China Travel Guide" in rendered_input
    assert any(
        "chatwoot webhook received" in record.message
        and "https://lyriktrip.com/guides/china" in record.message
        for record in caplog.records
    )


def test_chatwoot_connector_opens_pending_conversation_after_reply(tmp_path: Path, monkeypatch) -> None:
    asyncio.run(_run_chatwoot_connector_opens_pending_conversation_after_reply(tmp_path, monkeypatch))


async def _run_chatwoot_connector_opens_pending_conversation_after_reply(tmp_path: Path, monkeypatch) -> None:
    _write_main_agent(tmp_path)
    monkeypatch.setenv("CHATWOOT_WEBHOOK_SECRET", "test-chatwoot-secret")
    monkeypatch.setenv("CHATWOOT_CREDENTIAL_KIND", "webhook_secret")
    monkeypatch.setenv("CHATWOOT_ASYNC_PROCESSING", "false")

    release = asyncio.Event()
    release.set()  # 纯文本回复 provider：立即返回，无 handoff
    provider = _SlowChatwootProvider(release)
    monkeypatch.setattr(
        "anyagent.server.routes.responses.get_default_model_provider",
        lambda: provider,
    )

    app = create_app(
        workspace_dir=tmp_path,
        api_key="user-key",
        admin_api_key="admin-key",
        plugin_roots=[REFERENCE_PLUGIN_ROOT],
    )
    connector = app.state.anyagent.gateway_registry.channel_connectors["chatwoot"]

    sent_messages: list[str] = []
    opened: list[str] = []

    async def _record_send_message(platform_conversation_id: str, content: str, **_kwargs):
        sent_messages.append(platform_conversation_id)
        return type("SendResult", (), {"ok": True, "platform_message_id": "msg_1"})()

    async def _record_open_conversation(platform_conversation_id: str) -> bool:
        opened.append(platform_conversation_id)
        return True

    connector.outbound.send_message = _record_send_message
    connector.handoff.open_conversation = _record_open_conversation

    payload = {
        "event": "message_created",
        "message_type": "incoming",
        "timestamp": 1717000000,
        "account": {"id": 1},
        "conversation": {"id": 42, "status": "pending"},
        "message": {"content": "hi"},
    }
    raw_body = json.dumps(payload).encode("utf-8")
    signature = hmac.new(
        b"test-chatwoot-secret",
        f"{payload['timestamp']}.{raw_body.decode('utf-8')}".encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()

    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://testserver") as http:
        response = await http.post(
            "/gateway/chatwoot/webhook/main",
            headers={"x-chatwoot-signature": signature, "x-chatwoot-timestamp": str(payload["timestamp"])},
            content=raw_body,
        )
        assert response.status_code == 200, response.text
        data = response.json()
        assert data["processed"] is True
        assert data["reply_sent"] is True
        assert data["handoff_triggered"] is False
        assert data["conversation_opened"] is True

    assert sent_messages == ["42"]
    assert opened == ["42"]


async def _run_chatwoot_reply_open_capture(
    tmp_path: Path,
    monkeypatch,
    *,
    conversation: dict,
) -> tuple[list[str], dict]:
    _write_main_agent(tmp_path)
    monkeypatch.setenv("CHATWOOT_WEBHOOK_SECRET", "test-chatwoot-secret")
    monkeypatch.setenv("CHATWOOT_CREDENTIAL_KIND", "webhook_secret")
    monkeypatch.setenv("CHATWOOT_ASYNC_PROCESSING", "false")
    release = asyncio.Event()
    release.set()
    provider = _SlowChatwootProvider(release)
    monkeypatch.setattr(
        "anyagent.server.routes.responses.get_default_model_provider",
        lambda: provider,
    )
    app = create_app(
        workspace_dir=tmp_path,
        api_key="user-key",
        admin_api_key="admin-key",
        plugin_roots=[REFERENCE_PLUGIN_ROOT],
    )
    connector = app.state.anyagent.gateway_registry.channel_connectors["chatwoot"]
    opened: list[str] = []

    async def _record_send_message(platform_conversation_id: str, content: str, **_kwargs):
        return type("SendResult", (), {"ok": True, "platform_message_id": "msg_1"})()

    async def _record_open_conversation(platform_conversation_id: str) -> bool:
        opened.append(platform_conversation_id)
        return True

    connector.outbound.send_message = _record_send_message
    connector.handoff.open_conversation = _record_open_conversation

    payload = {
        "event": "message_created",
        "message_type": "incoming",
        "timestamp": 1717000000,
        "account": {"id": 1},
        "conversation": conversation,
        "content": "hi",
    }
    raw_body, signature = _sign_chatwoot_payload(payload)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://testserver") as http:
        response = await http.post(
            "/gateway/chatwoot/webhook/main",
            headers={"x-chatwoot-signature": signature, "x-chatwoot-timestamp": str(payload["timestamp"])},
            content=raw_body,
        )
        assert response.status_code == 200, response.text
        data = response.json()
    return opened, data


def test_chatwoot_connector_opens_conversation_when_status_missing(tmp_path: Path, monkeypatch) -> None:
    opened, data = asyncio.run(
        _run_chatwoot_reply_open_capture(tmp_path, monkeypatch, conversation={"id": 42})
    )
    assert data["reply_sent"] is True
    assert data["conversation_opened"] is True
    assert opened == ["42"]


def test_chatwoot_connector_reopens_resolved_conversation_after_bot_reply(tmp_path: Path, monkeypatch) -> None:
    opened, data = asyncio.run(
        _run_chatwoot_reply_open_capture(
            tmp_path,
            monkeypatch,
            conversation={"id": 42, "status": "resolved"},
        )
    )
    assert data["reply_sent"] is True
    assert data["conversation_opened"] is True
    assert opened == ["42"]


def test_chatwoot_connector_leaves_already_open_conversation_untouched(tmp_path: Path, monkeypatch) -> None:
    opened, data = asyncio.run(
        _run_chatwoot_reply_open_capture(
            tmp_path,
            monkeypatch,
            conversation={"id": 42, "status": "open"},
        )
    )
    assert data["reply_sent"] is True
    assert data["conversation_opened"] is False
    assert opened == []


def test_chatwoot_connector_webhook_acknowledges_before_background_processing(tmp_path: Path, monkeypatch) -> None:
    asyncio.run(_run_chatwoot_connector_webhook_acknowledges_before_background_processing(tmp_path, monkeypatch))


async def _run_chatwoot_connector_webhook_acknowledges_before_background_processing(
    tmp_path: Path,
    monkeypatch,
) -> None:
    _write_main_agent(tmp_path)
    monkeypatch.setenv("CHATWOOT_WEBHOOK_SECRET", "test-chatwoot-secret")
    monkeypatch.setenv("CHATWOOT_CREDENTIAL_KIND", "webhook_secret")
    monkeypatch.delenv("CHATWOOT_ASYNC_PROCESSING", raising=False)

    release = asyncio.Event()
    provider = _SlowChatwootProvider(release)
    monkeypatch.setattr(
        "anyagent.server.routes.responses.get_default_model_provider",
        lambda: provider,
    )

    app = create_app(
        workspace_dir=tmp_path,
        api_key="user-key",
        admin_api_key="admin-key",
        plugin_roots=[REFERENCE_PLUGIN_ROOT],
    )
    connector = app.state.anyagent.gateway_registry.channel_connectors["chatwoot"]

    sent_messages: list[dict] = []

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
        return type("SendResult", (), {"ok": True, "platform_message_id": "msg_async"})()

    connector.outbound.send_message = _record_send_message

    payload = {
        "event": "message_created",
        "message_type": "incoming",
        "timestamp": 1717000000,
        "account": {"id": 1},
        "conversation": {"id": 42},
        "message": {"content": "hi"},
    }
    raw_body = json.dumps(payload).encode("utf-8")
    signature = hmac.new(
        b"test-chatwoot-secret",
        f"{payload['timestamp']}.{raw_body.decode('utf-8')}".encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()

    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://testserver") as http:
        response = await http.post(
            "/gateway/chatwoot/webhook/main",
            headers={"x-chatwoot-signature": signature, "x-chatwoot-timestamp": str(payload["timestamp"])},
            content=raw_body,
        )
        assert response.status_code == 200, response.text
        data = response.json()
        assert data == {
            "ok": True,
            "event": "message_created",
            "accepted": True,
            "processed": False,
            "reason": "processing_async",
        }
        assert sent_messages == []

        await asyncio.wait_for(provider.started.wait(), timeout=1.0)
        release.set()
        for _ in range(20):
            if sent_messages:
                break
            await asyncio.sleep(0.05)

    assert sent_messages == [
        {
            "platform_conversation_id": "42",
            "content": "Async hello",
            "content_type": "text",
            "metadata": None,
        }
    ]


def test_chatwoot_connector_applies_pacing_floor_and_typing_indicator(tmp_path: Path, monkeypatch) -> None:
    asyncio.run(_run_chatwoot_connector_applies_pacing_floor_and_typing_indicator(tmp_path, monkeypatch))


async def _run_chatwoot_connector_applies_pacing_floor_and_typing_indicator(tmp_path: Path, monkeypatch) -> None:
    _write_main_agent(tmp_path)
    monkeypatch.setenv("CHATWOOT_WEBHOOK_SECRET", "test-chatwoot-secret")
    monkeypatch.setenv("CHATWOOT_CREDENTIAL_KIND", "webhook_secret")
    monkeypatch.setenv("CHATWOOT_ASYNC_PROCESSING", "false")
    monkeypatch.setenv("CHATWOOT_TYPING_INDICATOR", "true")
    monkeypatch.setenv("CHATWOOT_REPLY_PACING_MIN_S", "0.3")
    monkeypatch.setenv("CHATWOOT_REPLY_PACING_MAX_S", "0.3")
    release = asyncio.Event()
    release.set()
    provider = _SlowChatwootProvider(release)
    monkeypatch.setattr(
        "anyagent.server.routes.responses.get_default_model_provider",
        lambda: provider,
    )

    app = create_app(
        workspace_dir=tmp_path,
        api_key="user-key",
        admin_api_key="admin-key",
        plugin_roots=[REFERENCE_PLUGIN_ROOT],
    )
    connector = app.state.anyagent.gateway_registry.channel_connectors["chatwoot"]
    timeline: list[tuple[str, float]] = []

    async def _record_send_message(platform_conversation_id: str, content: str, **_kwargs):
        timeline.append(("send", time.monotonic()))
        return type("SendResult", (), {"ok": True, "platform_message_id": "msg_1"})()

    async def _record_typing(platform_conversation_id: str, *, typing: bool) -> bool:
        timeline.append((f"typing_{'on' if typing else 'off'}", time.monotonic()))
        return True

    connector.outbound.send_message = _record_send_message
    connector.outbound.set_typing = _record_typing

    payload = {
        "event": "message_created",
        "message_type": "incoming",
        "timestamp": 1717000000,
        "account": {"id": 1},
        "conversation": {"id": 42, "status": "open"},
        "content": "hi",
    }
    raw_body, signature = _sign_chatwoot_payload(payload)

    started = time.monotonic()
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://testserver") as http:
        response = await http.post(
            "/gateway/chatwoot/webhook/main",
            headers={"x-chatwoot-signature": signature, "x-chatwoot-timestamp": str(payload["timestamp"])},
            content=raw_body,
        )
        assert response.status_code == 200, response.text
        data = response.json()
        assert data["reply_sent"] is True
        assert data["pacing_delay_s"] > 0

    assert [name for name, _ in timeline] == ["typing_on", "typing_off", "send"]
    send_at = next(at for name, at in timeline if name == "send")
    assert send_at - started >= 0.3


def _sign_chatwoot_payload(payload: dict, secret: bytes = b"test-chatwoot-secret") -> tuple[bytes, str]:
    raw_body = json.dumps(payload).encode("utf-8")
    signature = hmac.new(
        secret,
        f"{payload['timestamp']}.{raw_body.decode('utf-8')}".encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()
    return raw_body, signature


def test_chatwoot_connector_skips_reply_when_assigned_to_human(tmp_path: Path, monkeypatch) -> None:
    asyncio.run(_run_chatwoot_connector_skips_reply_when_assigned_to_human(tmp_path, monkeypatch))


async def _run_chatwoot_connector_skips_reply_when_assigned_to_human(tmp_path: Path, monkeypatch) -> None:
    _write_main_agent(tmp_path)
    monkeypatch.setenv("CHATWOOT_WEBHOOK_SECRET", "test-chatwoot-secret")
    monkeypatch.setenv("CHATWOOT_CREDENTIAL_KIND", "webhook_secret")
    monkeypatch.setenv("CHATWOOT_ASYNC_PROCESSING", "false")
    provider = _ChatwootFlowProvider()
    monkeypatch.setattr(
        "anyagent.server.routes.responses.get_default_model_provider",
        lambda: provider,
    )

    app = create_app(
        workspace_dir=tmp_path,
        api_key="user-key",
        admin_api_key="admin-key",
        plugin_roots=[REFERENCE_PLUGIN_ROOT],
    )
    connector = app.state.anyagent.gateway_registry.channel_connectors["chatwoot"]
    sent_messages: list[str] = []

    async def _record_send_message(platform_conversation_id: str, content: str, **_kwargs):
        sent_messages.append(platform_conversation_id)
        return type("SendResult", (), {"ok": True, "platform_message_id": "msg_1"})()

    connector.outbound.send_message = _record_send_message

    payload = {
        "event": "message_created",
        "message_type": "incoming",
        "timestamp": 1717000000,
        "account": {"id": 1},
        "conversation": {
            "id": 68,
            "status": "open",
            "meta": {
                "assignee_type": "User",
                "assignee": {"id": 153044, "name": "LyrikTrip CS", "type": "user"},
            },
        },
        "content": "hi from visitor",
    }
    raw_body, signature = _sign_chatwoot_payload(payload)

    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://testserver") as http:
        response = await http.post(
            "/gateway/chatwoot/webhook/main",
            headers={"x-chatwoot-signature": signature, "x-chatwoot-timestamp": str(payload["timestamp"])},
            content=raw_body,
        )
        assert response.status_code == 200, response.text
        data = response.json()
        assert data["ok"] is True
        assert data["skipped"] is True
        assert data["reason"] == "assigned_to_human"

    assert sent_messages == []
    assert provider.bodies == []


def test_chatwoot_connector_skips_reply_when_live_assignee_is_human(tmp_path: Path, monkeypatch) -> None:
    asyncio.run(_run_chatwoot_connector_skips_reply_when_live_assignee_is_human(tmp_path, monkeypatch))


async def _run_chatwoot_connector_skips_reply_when_live_assignee_is_human(tmp_path: Path, monkeypatch) -> None:
    _write_main_agent(tmp_path)
    monkeypatch.setenv("CHATWOOT_WEBHOOK_SECRET", "test-chatwoot-secret")
    monkeypatch.setenv("CHATWOOT_CREDENTIAL_KIND", "webhook_secret")
    monkeypatch.setenv("CHATWOOT_ASYNC_PROCESSING", "false")
    provider = _ChatwootFlowProvider()
    monkeypatch.setattr(
        "anyagent.server.routes.responses.get_default_model_provider",
        lambda: provider,
    )

    app = create_app(
        workspace_dir=tmp_path,
        api_key="user-key",
        admin_api_key="admin-key",
        plugin_roots=[REFERENCE_PLUGIN_ROOT],
    )
    connector = app.state.anyagent.gateway_registry.channel_connectors["chatwoot"]
    sent_messages: list[str] = []

    async def _record_send_message(platform_conversation_id: str, content: str, **_kwargs):
        sent_messages.append(platform_conversation_id)
        return type("SendResult", (), {"ok": True, "platform_message_id": "msg_1"})()

    async def _live_assigned(_platform_conversation_id: str) -> dict:
        return {
            "id": 68,
            "status": "open",
            "meta": {
                "assignee_type": "User",
                "assignee": {"id": 153044, "name": "LyrikTrip CS", "role": "administrator"},
            },
        }

    connector.outbound.send_message = _record_send_message
    connector.handoff.get_conversation = _live_assigned

    payload = {
        "event": "message_created",
        "message_type": "incoming",
        "timestamp": 1717000000,
        "account": {"id": 1},
        "conversation": {"id": 68, "status": "open"},
        "content": "hi from visitor",
    }
    raw_body, signature = _sign_chatwoot_payload(payload)

    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://testserver") as http:
        response = await http.post(
            "/gateway/chatwoot/webhook/main",
            headers={"x-chatwoot-signature": signature, "x-chatwoot-timestamp": str(payload["timestamp"])},
            content=raw_body,
        )
        assert response.status_code == 200, response.text
        data = response.json()
        assert data["ok"] is True
        assert data["skipped"] is True
        assert data["reason"] == "assigned_to_human"

    assert sent_messages == []
    assert provider.bodies == []


def test_chatwoot_connector_replies_when_assigned_skip_disabled(tmp_path: Path, monkeypatch) -> None:
    asyncio.run(_run_chatwoot_connector_replies_when_assigned_skip_disabled(tmp_path, monkeypatch))


async def _run_chatwoot_connector_replies_when_assigned_skip_disabled(tmp_path: Path, monkeypatch) -> None:
    _write_main_agent(tmp_path)
    monkeypatch.setenv("CHATWOOT_WEBHOOK_SECRET", "test-chatwoot-secret")
    monkeypatch.setenv("CHATWOOT_CREDENTIAL_KIND", "webhook_secret")
    monkeypatch.setenv("CHATWOOT_ASYNC_PROCESSING", "false")
    monkeypatch.setenv("CHATWOOT_SKIP_WHEN_ASSIGNED_TO_HUMAN", "false")
    release = asyncio.Event()
    release.set()
    provider = _SlowChatwootProvider(release)
    monkeypatch.setattr(
        "anyagent.server.routes.responses.get_default_model_provider",
        lambda: provider,
    )

    app = create_app(
        workspace_dir=tmp_path,
        api_key="user-key",
        admin_api_key="admin-key",
        plugin_roots=[REFERENCE_PLUGIN_ROOT],
    )
    connector = app.state.anyagent.gateway_registry.channel_connectors["chatwoot"]
    sent_messages: list[str] = []

    async def _record_send_message(platform_conversation_id: str, content: str, **_kwargs):
        sent_messages.append(platform_conversation_id)
        return type("SendResult", (), {"ok": True, "platform_message_id": "msg_1"})()

    connector.outbound.send_message = _record_send_message

    payload = {
        "event": "message_created",
        "message_type": "incoming",
        "timestamp": 1717000000,
        "account": {"id": 1},
        "conversation": {
            "id": 68,
            "status": "open",
            "meta": {
                "assignee_type": "User",
                "assignee": {"id": 153044, "name": "LyrikTrip CS", "type": "user"},
            },
        },
        "content": "hi from visitor",
    }
    raw_body, signature = _sign_chatwoot_payload(payload)

    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://testserver") as http:
        response = await http.post(
            "/gateway/chatwoot/webhook/main",
            headers={"x-chatwoot-signature": signature, "x-chatwoot-timestamp": str(payload["timestamp"])},
            content=raw_body,
        )
        assert response.status_code == 200, response.text
        data = response.json()
        assert data["ok"] is True
        assert data["processed"] is True
        assert data["reply_sent"] is True
        assert data.get("skipped") is not True

    assert sent_messages == ["68"]


def test_chatwoot_connector_drops_reply_if_assigned_during_agent_run(tmp_path: Path, monkeypatch) -> None:
    asyncio.run(_run_chatwoot_connector_drops_reply_if_assigned_during_agent_run(tmp_path, monkeypatch))


async def _run_chatwoot_connector_drops_reply_if_assigned_during_agent_run(tmp_path: Path, monkeypatch) -> None:
    _write_main_agent(tmp_path)
    monkeypatch.setenv("CHATWOOT_WEBHOOK_SECRET", "test-chatwoot-secret")
    monkeypatch.setenv("CHATWOOT_CREDENTIAL_KIND", "webhook_secret")
    monkeypatch.setenv("CHATWOOT_ASYNC_PROCESSING", "false")
    release = asyncio.Event()
    release.set()
    provider = _SlowChatwootProvider(release)
    monkeypatch.setattr(
        "anyagent.server.routes.responses.get_default_model_provider",
        lambda: provider,
    )

    app = create_app(
        workspace_dir=tmp_path,
        api_key="user-key",
        admin_api_key="admin-key",
        plugin_roots=[REFERENCE_PLUGIN_ROOT],
    )
    connector = app.state.anyagent.gateway_registry.channel_connectors["chatwoot"]
    sent_messages: list[str] = []
    lookups = {"count": 0}

    async def _record_send_message(platform_conversation_id: str, content: str, **_kwargs):
        sent_messages.append(platform_conversation_id)
        return type("SendResult", (), {"ok": True, "platform_message_id": "msg_1"})()

    async def _live_assignee(_platform_conversation_id: str) -> dict:
        lookups["count"] += 1
        if lookups["count"] == 1:
            return {"id": 68, "status": "open"}
        return {
            "id": 68,
            "status": "open",
            "meta": {
                "assignee_type": "User",
                "assignee": {"id": 153044, "name": "LyrikTrip CS", "role": "administrator"},
            },
        }

    connector.outbound.send_message = _record_send_message
    connector.handoff.get_conversation = _live_assignee

    payload = {
        "event": "message_created",
        "message_type": "incoming",
        "timestamp": 1717000000,
        "account": {"id": 1},
        "conversation": {"id": 68, "status": "open"},
        "content": "hi from visitor",
    }
    raw_body, signature = _sign_chatwoot_payload(payload)

    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://testserver") as http:
        response = await http.post(
            "/gateway/chatwoot/webhook/main",
            headers={"x-chatwoot-signature": signature, "x-chatwoot-timestamp": str(payload["timestamp"])},
            content=raw_body,
        )
        assert response.status_code == 200, response.text
        data = response.json()
        assert data["ok"] is True
        assert data["skipped"] is True
        assert data["reply_sent"] is False
        assert data["reason"] == "assigned_to_human"

    assert sent_messages == []
    assert lookups["count"] >= 2
