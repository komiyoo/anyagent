from __future__ import annotations

import asyncio
import json
from typing import Any

import httpx

from anyagent.agent_runtime.model_providers._capabilities import ProviderCapabilities
from anyagent.agent_runtime.model_providers._translation import ToolNameMapping, VendorRequest, VendorTranslation
from anyagent.agent_runtime.model_providers._translating_provider import TranslatingModelProvider
from anyagent.agent_runtime.model_providers.base import ModelProviderTransportError, ModelProviderUpstreamError


class _Translator:
    capabilities = ProviderCapabilities(max_output_tokens_cap=5)

    def build_request(self, *, body: dict[str, Any], turns: list[dict[str, Any]], names: ToolNameMapping, settings: object) -> VendorRequest:
        _ = names, settings
        return VendorRequest(url_path="/messages", payload={"body": body, "turns": turns})

    def parse_response(self, *, data: dict[str, Any], names: ToolNameMapping) -> VendorTranslation:
        _ = names
        return VendorTranslation(text=str(data.get("text") or "ok"), raw_assistant_turn={"role": "assistant", "content": data})

    def input_to_turns(self, *, input_: object, names: ToolNameMapping) -> list[dict[str, Any]]:
        _ = names
        return [{"role": "user", "content": input_}] if input_ else []


def test_translating_provider_idempotency_clamp_and_pseudo_stream():
    asyncio.run(_run_idempotency_clamp_and_pseudo_stream())


async def _run_idempotency_clamp_and_pseudo_stream() -> None:
    requests: list[dict[str, Any]] = []

    async def handler(request: httpx.Request) -> httpx.Response:
        requests.append(json.loads(request.content))
        return httpx.Response(200, json={"text": "done"}, request=request)

    provider = TranslatingModelProvider(
        client=httpx.AsyncClient(transport=httpx.MockTransport(handler)),
        settings=object(),
        translator=_Translator(),
        base_url="https://example.test",
        upstream_name="fake",
        state_max_entries=8,
    )

    body = {"model": "m", "input": "hi", "max_output_tokens": 99}
    first = await provider.create_response(body=body, idempotency_key="idem")
    second = await provider.create_response(body=body, idempotency_key="idem")
    events, completed = await provider.create_response_stream_buffered(body=body)

    assert first.id == second.id
    assert completed.output[0].content[0].text == "done"
    assert [event.type for event in events] == ["response.created", "response.completed"]
    assert len(requests) == 2
    assert requests[0]["body"]["max_output_tokens"] == 5


def test_translating_provider_normalizes_upstream_and_transport_errors():
    asyncio.run(_run_normalizes_upstream_and_transport_errors())


async def _run_normalizes_upstream_and_transport_errors() -> None:
    async def upstream_error(request: httpx.Request) -> httpx.Response:
        return httpx.Response(429, json={"error": "limit"}, request=request)

    provider = TranslatingModelProvider(
        client=httpx.AsyncClient(transport=httpx.MockTransport(upstream_error)),
        settings=object(),
        translator=_Translator(),
        base_url="https://example.test",
        upstream_name="fake",
        state_max_entries=8,
    )
    try:
        await provider.create_response(body={"model": "m", "input": "hi"})
    except ModelProviderUpstreamError as e:
        assert e.status_code == 429
    else:
        raise AssertionError("expected upstream error")

    async def timeout(request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("timeout", request=request)

    provider = TranslatingModelProvider(
        client=httpx.AsyncClient(transport=httpx.MockTransport(timeout)),
        settings=object(),
        translator=_Translator(),
        base_url="https://example.test",
        upstream_name="fake",
        state_max_entries=8,
    )
    try:
        await provider.create_response(body={"model": "m", "input": "hi"})
    except ModelProviderTransportError:
        pass
    else:
        raise AssertionError("expected transport error")
