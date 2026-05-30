from __future__ import annotations

import asyncio
from typing import Any

import httpx

from anyagent.agent_runtime.model_providers._capabilities import ProviderCapabilities
from anyagent.agent_runtime.model_providers._translation import ToolNameMapping, VendorRequest, VendorTranslation
from anyagent.agent_runtime.model_providers._translating_provider import TranslatingModelProvider
from anyagent.agent_runtime.model_providers.base import ModelProviderInvalidRequestError


class _NoToolsTranslator:
    capabilities = ProviderCapabilities(supports_tools=False, supports_tool_choice_required=False)

    def build_request(self, *, body: dict[str, Any], turns: list[dict[str, Any]], names: ToolNameMapping, settings: object) -> VendorRequest:
        return VendorRequest(url_path="/messages", payload={})

    def parse_response(self, *, data: dict[str, Any], names: ToolNameMapping) -> VendorTranslation:
        return VendorTranslation(text="ok")

    def input_to_turns(self, *, input_: object, names: ToolNameMapping) -> list[dict[str, Any]]:
        return []


def test_tools_and_required_tool_choice_can_be_explicitly_rejected():
    asyncio.run(_run_rejections())


async def _run_rejections() -> None:
    provider = TranslatingModelProvider(
        client=httpx.AsyncClient(transport=httpx.MockTransport(lambda request: httpx.Response(200, json={}, request=request))),
        settings=object(),
        translator=_NoToolsTranslator(),
        base_url="https://example.test",
        upstream_name="fake",
        state_max_entries=8,
    )

    try:
        await provider.create_response(
            body={"model": "m", "tools": [{"type": "function", "name": "lookup"}], "input": "hi"}
        )
    except ModelProviderInvalidRequestError as e:
        assert "does not support tools" in str(e)
    else:
        raise AssertionError("expected tools rejection")

    try:
        await provider.create_response(body={"model": "m", "tool_choice": "required", "input": "hi"})
    except ModelProviderInvalidRequestError as e:
        assert "tool_choice=required" in str(e)
    else:
        raise AssertionError("expected required tool_choice rejection")
