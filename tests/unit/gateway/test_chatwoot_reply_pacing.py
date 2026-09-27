from __future__ import annotations

import asyncio

import httpx
import pytest

from anyagent.gateway.connector_contracts import ConnectorOutboundDelivery, OutboundMessageResult
from anyagent.plugins.builtin.chatwoot_connector.chatwoot import ChatwootOutboundDelivery
from anyagent.plugins.builtin.chatwoot_connector.plugin import (
    _apply_reply_pacing_floor,
    _chatwoot_reply_pacing_window,
    _chatwoot_typing_indicator_enabled,
    _reply_pacing_delay_s,
    _set_typing_indicator,
)


def test_pacing_window_defaults_off_and_parses_env(monkeypatch: pytest.MonkeyPatch) -> None:
    for key in ("CHATWOOT_REPLY_PACING_MIN_S", "CHATWOOT_REPLY_PACING_MAX_S"):
        monkeypatch.delenv(key, raising=False)
    assert _chatwoot_reply_pacing_window() is None

    monkeypatch.setenv("CHATWOOT_REPLY_PACING_MIN_S", "2")
    monkeypatch.setenv("CHATWOOT_REPLY_PACING_MAX_S", "4")
    assert _chatwoot_reply_pacing_window() == (2.0, 4.0)

    monkeypatch.delenv("CHATWOOT_REPLY_PACING_MAX_S")
    assert _chatwoot_reply_pacing_window() == (2.0, 2.0)

    monkeypatch.setenv("CHATWOOT_REPLY_PACING_MAX_S", "1")  # max < min → off
    assert _chatwoot_reply_pacing_window() is None

    monkeypatch.setenv("CHATWOOT_REPLY_PACING_MAX_S", "abc")
    assert _chatwoot_reply_pacing_window() is None


def test_typing_indicator_defaults_off(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("CHATWOOT_TYPING_INDICATOR", raising=False)
    assert _chatwoot_typing_indicator_enabled() is False
    monkeypatch.setenv("CHATWOOT_TYPING_INDICATOR", "true")
    assert _chatwoot_typing_indicator_enabled() is True


def test_pacing_delay_is_a_floor_not_a_delay() -> None:
    window = (2.0, 4.0)
    # instant reply: wait up to the drawn target
    assert _reply_pacing_delay_s(elapsed_s=0.1, window=window, target_s=3.0) == pytest.approx(2.9)
    # partially elapsed: only the remainder
    assert _reply_pacing_delay_s(elapsed_s=2.5, window=window, target_s=3.0) == pytest.approx(0.5)
    # slow model turn: never lengthened
    assert _reply_pacing_delay_s(elapsed_s=10.0, window=window, target_s=3.0) == 0.0
    # off
    assert _reply_pacing_delay_s(elapsed_s=0.0, window=None) == 0.0
    # random draw stays inside the window
    for _ in range(50):
        delay = _reply_pacing_delay_s(elapsed_s=0.0, window=window)
        assert 2.0 <= delay <= 4.0


def test_apply_pacing_floor_sleeps_only_when_needed() -> None:
    slept: list[float] = []

    async def _sleep(seconds: float) -> None:
        slept.append(seconds)

    async def _run() -> None:
        import time

        now = time.monotonic()
        delay = await _apply_reply_pacing_floor(started_at=now, window=(0.5, 0.5), sleep=_sleep)
        assert delay == pytest.approx(0.5, abs=0.05)
        assert len(slept) == 1

        slept.clear()
        delay = await _apply_reply_pacing_floor(started_at=now - 10.0, window=(0.5, 0.5), sleep=_sleep)
        assert delay == 0.0
        assert slept == []

        delay = await _apply_reply_pacing_floor(started_at=now, window=None, sleep=_sleep)
        assert delay == 0.0
        assert slept == []

    asyncio.run(_run())


class _NoTypingOutbound(ConnectorOutboundDelivery):
    async def send_message(self, platform_conversation_id, content, *, content_type="text", metadata=None):  # type: ignore[override]
        return OutboundMessageResult(ok=True)

    async def send_private_note(self, platform_conversation_id, content, *, metadata=None):  # type: ignore[override]
        return OutboundMessageResult(ok=True)


class _TypingOutbound(_NoTypingOutbound):
    def __init__(self) -> None:
        self.calls: list[bool] = []

    async def set_typing(self, platform_conversation_id: str, *, typing: bool) -> bool:
        self.calls.append(typing)
        return True


class _FailingTypingOutbound(_NoTypingOutbound):
    async def set_typing(self, platform_conversation_id: str, *, typing: bool) -> bool:
        raise RuntimeError("chatwoot down")


def test_set_typing_indicator_degrades_to_noop() -> None:
    async def _run() -> None:
        connector_no_cap = type("C", (), {"outbound": _NoTypingOutbound()})()
        assert await _set_typing_indicator(connector_no_cap, "42", typing=True) is False

        typing = _TypingOutbound()
        connector = type("C", (), {"outbound": typing})()
        assert await _set_typing_indicator(connector, "42", typing=True) is True
        assert await _set_typing_indicator(connector, "42", typing=False) is True
        assert typing.calls == [True, False]

        failing = type("C", (), {"outbound": _FailingTypingOutbound()})()
        assert await _set_typing_indicator(failing, "42", typing=True) is False

        assert await _set_typing_indicator(None, "42", typing=True) is False

    asyncio.run(_run())


def test_chatwoot_outbound_set_typing_posts_toggle_typing_status() -> None:
    seen: list[tuple[str, dict]] = []

    def _handler(request: httpx.Request) -> httpx.Response:
        import json

        seen.append((request.url.path, json.loads(request.content.decode("utf-8"))))
        return httpx.Response(200, json={})

    async def _run() -> None:
        async with httpx.AsyncClient(transport=httpx.MockTransport(_handler), base_url="https://cw.example") as client:
            outbound = ChatwootOutboundDelivery(chatwoot_url="https://cw.example", account_id=7, access_token="tok", http_client=client)
            assert await outbound.set_typing("42", typing=True) is True
            assert await outbound.set_typing("42", typing=False) is True

    asyncio.run(_run())
    assert seen == [
        ("/api/v1/accounts/7/conversations/42/toggle_typing_status", {"typing_status": "on"}),
        ("/api/v1/accounts/7/conversations/42/toggle_typing_status", {"typing_status": "off"}),
    ]


def test_chatwoot_outbound_sends_structured_attributes_only_when_present() -> None:
    seen: list[dict] = []

    def _handler(request: httpx.Request) -> httpx.Response:
        import json

        seen.append(json.loads(request.content))
        return httpx.Response(200, json={"id": 1})

    async def _run() -> None:
        async with httpx.AsyncClient(transport=httpx.MockTransport(_handler), base_url="https://cw.example") as client:
            outbound = ChatwootOutboundDelivery(chatwoot_url="https://cw.example", account_id=7, access_token="tok", http_client=client)
            await outbound.send_message("42", "Hello")
            await outbound.send_message("42", "Choose one", content_type="input_select",
                                        metadata={"content_attributes": {"items": [{"title": "A", "value": "a"}]}})

    asyncio.run(_run())
    assert seen[0] == {"content": "Hello", "message_type": "outgoing", "content_type": "text"}
    assert seen[1] == {"content": "Choose one", "message_type": "outgoing", "content_type": "input_select",
                       "private": False, "content_attributes": {"items": [{"title": "A", "value": "a"}]}}
