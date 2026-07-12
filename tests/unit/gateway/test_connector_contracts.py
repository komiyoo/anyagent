"""Connector contracts 和 Chatwoot connector 单元测试。"""

from __future__ import annotations

from types import SimpleNamespace
import hashlib
import hmac
import json

import httpx
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from anyagent.gateway.connector_contracts import (
    ConnectorDescriptor,
    HandoffMetadata,
    HandoffOutputItem,
    HandoffReason,
    HandoffResult,
    OutboundMessageResult,
    PlatformConversationEvent,
    PlatformConversationEventType,
    WebhookAuthError,
    WebhookAuthSuccess,
    chatwoot_session_key,
    intercom_session_key,
    telegram_session_key,
)
from anyagent.gateway.plugins import GatewayRegistry, WebhookRoute
from anyagent.plugins.builtin.chatwoot_connector.chatwoot import (
    ChatwootHandoff,
    ChatwootWebhookAuth,
    build_platform_event_from_webhook,
)
from anyagent.plugins.builtin.chatwoot_connector.plugin import (
    _chatwoot_status_changes_enabled,
    _extract_reply_and_handoff,
    register as chatwoot_register,
)
from anyagent.server.routes.gateway_webhooks import (
    _find_connector_by_webhook,
    _resolve_webhook_secret_ref,
    create_gateway_webhook_router,
)


# ── Session key helpers ───────────────────────────────────────────


def test_chatwoot_session_key_format():
    assert chatwoot_session_key(account_id=1, conversation_id=42) == "chatwoot:1:42"
    assert chatwoot_session_key(account_id="acct_123", conversation_id="conv_456") == "chatwoot:acct_123:conv_456"


def test_telegram_session_key_format():
    assert telegram_session_key(chat_id=123456) == "telegram:123456"
    assert telegram_session_key(chat_id="chat1", topic_id=99) == "telegram:chat1:99"


def test_intercom_session_key_format():
    assert intercom_session_key(conversation_id="conv_abc") == "intercom:conv_abc"


# ── PlatformConversationEvent ──────────────────────────────────────


def test_platform_event_model():
    event = PlatformConversationEvent(
        session_key="chatwoot:1:42",
        event_type=PlatformConversationEventType.ASSIGNED_TO_HUMAN,
        platform="chatwoot",
        platform_conversation_id="42",
    )
    d = event.model_dump(exclude_none=True)
    assert d["session_key"] == "chatwoot:1:42"
    assert d["event_type"] == "assigned_to_human"
    assert d["platform"] == "chatwoot"


def test_platform_event_types():
    assert PlatformConversationEventType.ASSIGNED_TO_HUMAN.value == "assigned_to_human"
    assert PlatformConversationEventType.RESOLVED.value == "resolved"
    assert PlatformConversationEventType.USER_MESSAGE.value == "user_message"
    assert len(PlatformConversationEventType) == 9  # 9 event types


# ── HandoffOutputItem ──────────────────────────────────────────────


def test_handoff_output_item():
    item = HandoffOutputItem(
        reason=HandoffReason.CUSTOMER_REQUEST,
        metadata=HandoffMetadata(suggested_team="sales", summary="Customer requested human"),
    )
    assert item.type == "handoff"
    assert item.reason == HandoffReason.CUSTOMER_REQUEST
    assert item.metadata.suggested_team == "sales"


def test_handoff_output_item_defaults():
    item = HandoffOutputItem()
    assert item.type == "handoff"
    assert item.reason == HandoffReason.OTHER
    assert item.metadata.suggested_team is None


def test_handoff_reasons():
    reasons = list(HandoffReason)
    assert HandoffReason.CUSTOMER_REQUEST in reasons
    assert HandoffReason.CONFIDENCE_LOW in reasons
    assert HandoffReason.SENSITIVE_TOPIC in reasons
    assert HandoffReason.MAX_TURNS_EXCEEDED in reasons
    assert HandoffReason.ESCALATION in reasons
    assert HandoffReason.OTHER in reasons


# ── ConnectorDescriptor ───────────────────────────────────────────


def test_connector_descriptor():
    desc = ConnectorDescriptor(channel="chatwoot", display_name="Chatwoot")
    assert desc.channel == "chatwoot"
    assert desc.display_name == "Chatwoot"
    assert desc.webhook_auth is None


def test_connector_descriptor_empty_channel_raises():
    with pytest.raises(ValueError, match="non-empty"):
        ConnectorDescriptor(channel="")


# ── ChatwootWebhookAuth ────────────────────────────────────────────


def test_chatwoot_webhook_auth_valid_signature():
    auth = ChatwootWebhookAuth()
    secret = "test_hmac_secret"
    timestamp = 1717000000

    body = {
        "timestamp": timestamp,
        "event": "message_created",
        "account": {"id": 1},
        "conversation": {"id": 42},
    }
    body_bytes = json.dumps(body).encode("utf-8")

    # 计算正确的 HMAC
    payload = f"{timestamp}.{json.dumps(body)}"
    signature = hmac.new(secret.encode(), payload.encode(), hashlib.sha256).hexdigest()

    headers = {"x-chatwoot-signature": signature, "x-chatwoot-timestamp": str(timestamp)}

    import asyncio
    result = asyncio.run(auth.verify(headers=headers, raw_body=body_bytes, secret=secret))
    assert result.verified is True
    assert result.platform == "chatwoot"
    assert result.account_id == "1"


def test_chatwoot_webhook_auth_missing_signature():
    auth = ChatwootWebhookAuth()
    body = json.dumps({"timestamp": 1234567890}).encode("utf-8")
    headers: dict[str, str] = {}

    import asyncio
    with pytest.raises(WebhookAuthError, match="missing X-Chatwoot-Signature"):
        asyncio.run(auth.verify(headers=headers, raw_body=body, secret="secret"))


def test_chatwoot_webhook_auth_invalid_signature():
    auth = ChatwootWebhookAuth()
    secret = "test_secret"
    timestamp = 1717000000
    body = json.dumps({"timestamp": timestamp}).encode("utf-8")
    headers = {"x-chatwoot-signature": "invalid_signature_here", "x-chatwoot-timestamp": str(timestamp)}

    import asyncio
    with pytest.raises(WebhookAuthError, match="HMAC signature mismatch"):
        asyncio.run(auth.verify(headers=headers, raw_body=body, secret=secret))


def test_chatwoot_webhook_auth_signature_tampering():
    """验证篡改请求体会导致签名不匹配。"""
    auth = ChatwootWebhookAuth()
    secret = "test_secret"
    timestamp = 1717000000

    original_body = json.dumps({"timestamp": timestamp, "content": "hello"}).encode("utf-8")
    payload = f"{timestamp}.{json.dumps({'timestamp': timestamp, 'content': 'hello'})}"
    correct_sig = hmac.new(secret.encode(), payload.encode(), hashlib.sha256).hexdigest()

    # 使用篡改后的 body
    tampered_body = json.dumps({"timestamp": timestamp, "content": "malicious content"}).encode("utf-8")

    import asyncio
    with pytest.raises(WebhookAuthError, match="HMAC signature mismatch"):
        asyncio.run(auth.verify(
            headers={"x-chatwoot-signature": correct_sig, "x-chatwoot-timestamp": str(timestamp)},
            raw_body=tampered_body,
            secret=secret,
        ))


# ── build_platform_event_from_webhook ─────────────────────────────


def test_build_platform_event_message_created():
    webhook = {
        "event": "message_created",
        "timestamp": 1717000000,
        "account": {"id": "1"},
        "conversation": {"id": "42"},
    }
    event = build_platform_event_from_webhook(account_id="1", webhook_body=webhook)
    assert event.event_type == PlatformConversationEventType.USER_MESSAGE
    assert event.session_key == "chatwoot:1:42"
    assert event.platform == "chatwoot"


def test_build_platform_event_includes_chatwoot_page_context():
    webhook = {
        "event": "webwidget_triggered",
        "timestamp": 1717000000,
        "account": {"id": "1"},
        "conversation": {
            "id": "42",
            "custom_attributes": {
                "lt_entry_url": "https://lyriktrip.com/guides/china",
                "lt_entry_title": "China Travel Guide",
                "lt_entry_path": "/guides/china",
            },
        },
        "event_info": {
            "referer": "https://lyriktrip.com/guides/china?utm_source=test",
            "widget_language": "en",
            "browser_language": "en-US",
        },
    }

    event = build_platform_event_from_webhook(account_id="1", webhook_body=webhook)

    assert event.metadata["chatwoot_page_context"] == {
        "referer": "https://lyriktrip.com/guides/china?utm_source=test",
        "entry_url": "https://lyriktrip.com/guides/china",
        "entry_path": "/guides/china",
        "entry_title": "China Travel Guide",
        "widget_language": "en",
        "browser_language": "en-US",
    }


def test_gateway_webhook_route_logs_chatwoot_page_context(caplog):
    async def _handler(**_kwargs):
        return {
            "ok": True,
            "platform_event": {
                "metadata": {
                    "chatwoot_page_context": {
                        "entry_url": "https://lyriktrip.com/guides/china?codex_probe=chatwoot_page_context",
                        "entry_path": "/guides/china",
                    },
                },
            },
        }

    registry = GatewayRegistry()
    registry.register_webhook_route(
        WebhookRoute(
            path="/gateway/chatwoot/webhook",
            methods=["POST"],
            handler=_handler,
            channel="chatwoot",
        )
    )
    state = SimpleNamespace(gateway_registry=registry)
    app = FastAPI()
    app.include_router(create_gateway_webhook_router(state))

    caplog.set_level("INFO", "anyagent.server.routes.gateway_webhooks")
    response = TestClient(app).post("/gateway/chatwoot/webhook", json={"event": "webwidget_triggered"})

    assert response.status_code == 200
    assert any(
        "gateway webhook received" in record.message
        and "https://lyriktrip.com/guides/china?codex_probe=chatwoot_page_context" in record.message
        for record in caplog.records
    )


def test_build_platform_event_resolved():
    webhook = {
        "event": "conversation_resolved",
        "timestamp": 1717000000,
        "account": {"id": "1"},
        "conversation": {"id": "42"},
    }
    event = build_platform_event_from_webhook(account_id="1", webhook_body=webhook)
    assert event.event_type == PlatformConversationEventType.RESOLVED


def test_build_platform_event_custom():
    webhook = {
        "event": "unknown_event_type",
        "timestamp": 1717000000,
        "account": {"id": "1"},
        "conversation": {"id": "42"},
    }
    event = build_platform_event_from_webhook(account_id="1", webhook_body=webhook)
    assert event.event_type == PlatformConversationEventType.CUSTOM


# ── OutboundMessageResult ──────────────────────────────────────────


def test_outbound_message_result():
    result = OutboundMessageResult(ok=True, platform_message_id="msg_123")
    assert result.ok is True
    assert result.platform_message_id == "msg_123"


def test_handoff_result():
    result = HandoffResult(ok=True, reason="done", metadata={"toggled": True})
    assert result.ok is True
    assert result.reason == "done"
    assert result.metadata["toggled"] is True


def test_webhook_route_prefers_explicit_channel_binding():
    connector = SimpleNamespace(channel="chatwoot")
    registry = GatewayRegistry(channel_connectors={"chatwoot": connector})
    state = SimpleNamespace(gateway_registry=registry)
    route = WebhookRoute(path="/chatwoot/webhook", channel="chatwoot")

    assert _find_connector_by_webhook(state, route) is connector


def test_resolve_webhook_secret_ref_from_connector_fields():
    connector = SimpleNamespace(
        webhook_secret_credential_id="chatwoot-webhook",
        webhook_secret_kind="hmac_sha256",
    )

    ref = _resolve_webhook_secret_ref(connector)

    assert ref is not None
    assert ref.ref == "chatwoot-webhook"
    assert ref.kind == "hmac_sha256"


def test_resolve_webhook_secret_ref_defaults_kind_to_secret():
    connector = SimpleNamespace(webhook_secret_credential_id="chatwoot-webhook")

    ref = _resolve_webhook_secret_ref(connector)

    assert ref is not None
    assert ref.ref == "chatwoot-webhook"
    assert ref.kind == "secret"


def test_extract_reply_and_handoff_reads_both_outputs():
    payload = {
        "output": [
            {
                "type": "message",
                "content": [
                    {"type": "output_text", "text": "hello from agent"},
                ],
            },
            {
                "type": "handoff",
                "reason": "customer_request",
                "metadata": {"suggested_team": "sales"},
            },
        ]
    }

    reply_text, handoff_item = _extract_reply_and_handoff(payload)

    assert reply_text == "hello from agent"
    assert handoff_item is not None
    assert handoff_item.reason == HandoffReason.CUSTOMER_REQUEST
    assert handoff_item.metadata.suggested_team == "sales"


# ── ChatwootHandoff 会话状态开关 ───────────────────────────────────


async def _run_chatwoot_handoff(**handoff_kwargs) -> tuple[HandoffResult, list[httpx.Request]]:
    requests: list[httpx.Request] = []

    def _handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(200, json={"id": 1})

    async with httpx.AsyncClient(
        transport=httpx.MockTransport(_handler),
        base_url="https://chatwoot.test",
    ) as client:
        handoff = ChatwootHandoff(
            chatwoot_url="https://chatwoot.test",
            account_id=1,
            access_token="token",
            http_client=client,
            **handoff_kwargs,
        )
        result = await handoff.execute_handoff(
            "42",
            HandoffReason.CUSTOMER_REQUEST,
            metadata=HandoffMetadata(suggested_team="7", summary="needs human"),
        )
    return result, requests


def test_chatwoot_handoff_toggles_status_by_default():
    import asyncio

    result, requests = asyncio.run(_run_chatwoot_handoff())

    assert result.ok is True
    assert result.metadata["toggled"] is True
    paths = [request.url.path for request in requests]
    assert "/api/v1/accounts/1/conversations/42/toggle_status" in paths
    assert "/api/v1/accounts/1/conversations/42/assignments" in paths
    assert "/api/v1/accounts/1/conversations/42/messages" in paths


def test_chatwoot_handoff_skips_toggle_status_when_disabled():
    import asyncio

    result, requests = asyncio.run(_run_chatwoot_handoff(status_changes_enabled=False))

    assert result.ok is True
    assert result.metadata["toggled"] is False
    assert result.metadata["status_change_skipped"] is True
    paths = [request.url.path for request in requests]
    # 显式关闭时不发起任何 toggle_status 类请求
    assert all("toggle_status" not in path for path in paths)
    # assignment 与摘要 note 不受影响
    assert "/api/v1/accounts/1/conversations/42/assignments" in paths
    assert "/api/v1/accounts/1/conversations/42/messages" in paths


async def _run_chatwoot_open_conversation(*, response_status: int = 200, **handoff_kwargs) -> tuple[bool, list[httpx.Request]]:
    requests: list[httpx.Request] = []

    def _handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(response_status, json={"id": 1})

    async with httpx.AsyncClient(
        transport=httpx.MockTransport(_handler),
        base_url="https://chatwoot.test",
    ) as client:
        handoff = ChatwootHandoff(
            chatwoot_url="https://chatwoot.test",
            account_id=1,
            access_token="token",
            http_client=client,
            **handoff_kwargs,
        )
        opened = await handoff.open_conversation("42")
    return opened, requests


def test_chatwoot_open_conversation_toggles_status_by_default():
    import asyncio

    opened, requests = asyncio.run(_run_chatwoot_open_conversation())

    assert opened is True
    assert [request.url.path for request in requests] == [
        "/api/v1/accounts/1/conversations/42/toggle_status"
    ]
    assert json.loads(requests[0].content) == {"status": "open"}


def test_chatwoot_open_conversation_noop_when_disabled():
    import asyncio

    opened, requests = asyncio.run(_run_chatwoot_open_conversation(status_changes_enabled=False))

    assert opened is False
    assert requests == []


def test_chatwoot_open_conversation_swallows_api_errors():
    import asyncio

    opened, requests = asyncio.run(_run_chatwoot_open_conversation(response_status=500))

    assert opened is False
    assert len(requests) == 1


def test_chatwoot_status_changes_env_flag_parsing(monkeypatch):
    monkeypatch.delenv("ANYAGENT_CHATWOOT_STATUS_CHANGES", raising=False)
    assert _chatwoot_status_changes_enabled() is True

    for raw in ("false", "0", "no", "off", "False"):
        monkeypatch.setenv("ANYAGENT_CHATWOOT_STATUS_CHANGES", raw)
        assert _chatwoot_status_changes_enabled() is False

    for raw in ("true", "1", "yes", "on", "True", ""):
        monkeypatch.setenv("ANYAGENT_CHATWOOT_STATUS_CHANGES", raw)
        assert _chatwoot_status_changes_enabled() is True


class _RecorderAPI:
    def __init__(self) -> None:
        self.connectors: list = []
        self.tools: list = []

    def registerChannel(self, connector) -> None:  # noqa: N802
        self.connectors.append(connector)

    def registerTool(self, tool, handler=None) -> None:  # noqa: N802
        self.tools.append((tool, handler))

    def registerWebhookRoute(self, route) -> None:  # noqa: N802
        pass


def test_register_enables_status_changes_by_default(monkeypatch):
    monkeypatch.delenv("ANYAGENT_CHATWOOT_STATUS_CHANGES", raising=False)

    api = _RecorderAPI()
    chatwoot_register(api)

    assert api.connectors
    assert api.connectors[0].handoff._status_changes_enabled is True
    handoff_tools = [tool for tool, _ in api.tools if tool.name == "app.chatwoot.handoff"]
    assert handoff_tools
    assert "不改变会话状态" not in handoff_tools[0].description


def test_register_disables_status_changes_when_opted_out(monkeypatch):
    monkeypatch.setenv("ANYAGENT_CHATWOOT_STATUS_CHANGES", "false")

    api = _RecorderAPI()
    chatwoot_register(api)

    assert api.connectors
    assert api.connectors[0].handoff._status_changes_enabled is False
    handoff_tools = [tool for tool, _ in api.tools if tool.name == "app.chatwoot.handoff"]
    assert handoff_tools
    assert "不改变会话状态" in handoff_tools[0].description


def test_register_enables_status_changes_when_opted_in(monkeypatch):
    monkeypatch.setenv("ANYAGENT_CHATWOOT_STATUS_CHANGES", "true")

    api = _RecorderAPI()
    chatwoot_register(api)

    assert api.connectors
    assert api.connectors[0].handoff._status_changes_enabled is True
    handoff_tools = [tool for tool, _ in api.tools if tool.name == "app.chatwoot.handoff"]
    assert handoff_tools
    assert "不改变会话状态" not in handoff_tools[0].description
