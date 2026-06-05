from __future__ import annotations

import json
from functools import lru_cache
from typing import Any

import httpx
from pydantic import AnyHttpUrl, Field
from pydantic_settings import BaseSettings, SettingsConfigDict

from ._capabilities import ANTHROPIC_CAPS, ProviderCapabilities
from ._translation import ToolNameMapping, VendorRequest, VendorToolCall, VendorTranslation
from ._translating_provider import TranslatingModelProvider


class AnthropicMessagesModelProviderSettings(BaseSettings):
    """
    Anthropic Messages API settings.

    Env:
    - ANTHROPIC_API_KEY
    - ANTHROPIC_BASE_URL (default: https://api.anthropic.com/v1)
    - ANTHROPIC_VERSION (default: 2023-06-01)
    - ANYAGENT_ANTHROPIC_STATE_MAX (default: 1024)
    """

    model_config = SettingsConfigDict(env_file=None, extra="ignore")

    api_key: str = Field(alias="ANTHROPIC_API_KEY")
    base_url: AnyHttpUrl = Field(default="https://api.anthropic.com/v1", alias="ANTHROPIC_BASE_URL")
    anthropic_version: str = Field(default="2023-06-01", alias="ANTHROPIC_VERSION")
    state_max_entries: int = Field(default=1024, ge=1, le=100_000, alias="ANYAGENT_ANTHROPIC_STATE_MAX")


class AnthropicTranslator:
    capabilities: ProviderCapabilities = ANTHROPIC_CAPS

    def build_request(
        self,
        *,
        body: dict[str, Any],
        turns: list[dict[str, Any]],
        names: ToolNameMapping,
        settings: object,
    ) -> VendorRequest:
        if not isinstance(settings, AnthropicMessagesModelProviderSettings):
            raise TypeError("settings must be AnthropicMessagesModelProviderSettings")

        max_tokens = body.get("max_output_tokens")
        max_tokens_i = max_tokens if isinstance(max_tokens, int) and max_tokens >= 1 else 1024
        payload: dict[str, Any] = {
            "model": str(body["model"]).strip(),
            "max_tokens": max_tokens_i,
            "messages": turns,
        }
        system = _system_text_from_body(body)
        if system:
            payload["system"] = system

        tools_req = _to_anthropic_tools(body.get("tools") if isinstance(body.get("tools"), list) else [], names)
        if tools_req:
            payload["tools"] = tools_req
            tool_choice = _to_anthropic_tool_choice(body.get("tool_choice"), names)
            if tool_choice is not None:
                payload["tool_choice"] = tool_choice

        # Pass through workspace extra_params verbatim
        extra_params = body.get("_extra_params")
        if isinstance(extra_params, dict):
            for key, val in extra_params.items():
                if key not in payload:
                    payload[key] = val

        return VendorRequest(
            url_path="/messages",
            headers={
                "x-api-key": settings.api_key,
                "anthropic-version": settings.anthropic_version,
            },
            payload=payload,
        )

    def parse_response(self, *, data: dict[str, Any], names: ToolNameMapping) -> VendorTranslation:
        content = data.get("content")
        if not isinstance(content, list):
            content = []

        text_parts: list[str] = []
        tool_calls: list[VendorToolCall] = []
        for block in content:
            if not isinstance(block, dict):
                continue
            if block.get("type") == "text":
                text = block.get("text")
                if isinstance(text, str) and text:
                    text_parts.append(text)
                continue
            if block.get("type") == "tool_use":
                tool_use_id = block.get("id")
                model_name = block.get("name")
                tool_input = block.get("input")
                if not isinstance(tool_use_id, str) or not isinstance(model_name, str):
                    continue
                tool_calls.append(
                    VendorToolCall(
                        call_id=tool_use_id,
                        name=names.source_name_for_model(model_name),
                        arguments_json=json.dumps(tool_input if isinstance(tool_input, dict) else {}, ensure_ascii=False, separators=(",", ":")),
                    )
                )

        return VendorTranslation(
            text="".join(text_parts).strip(),
            tool_calls=tool_calls,
            raw_assistant_turn={"role": "assistant", "content": content},
        )

    def input_to_turns(self, *, input_: object, names: ToolNameMapping) -> list[dict[str, Any]]:
        _ = names
        if isinstance(input_, str):
            s = input_.strip()
            return [{"role": "user", "content": s}] if s else []

        if not isinstance(input_, list):
            return []

        tool_results: list[dict[str, Any]] = []
        messages: list[dict[str, Any]] = []
        for item in input_:
            if isinstance(item, dict) and item.get("type") == "function_call_output":
                call_id = item.get("call_id")
                output = item.get("output")
                if isinstance(call_id, str) and isinstance(output, str):
                    tool_results.append({"type": "tool_result", "tool_use_id": call_id, "content": output})
                continue
            if isinstance(item, dict) and isinstance(item.get("role"), str):
                role = item.get("role")
                content = item.get("content")
                if role in {"user", "assistant"} and isinstance(content, str) and content.strip():
                    messages.append({"role": role, "content": content.strip()})
                continue

        if tool_results:
            messages.append({"role": "user", "content": tool_results})
        return messages


class AnthropicMessagesModelProvider(TranslatingModelProvider):
    def __init__(self, *, client: httpx.AsyncClient, settings: AnthropicMessagesModelProviderSettings) -> None:
        super().__init__(
            client=client,
            settings=settings,
            translator=AnthropicTranslator(),
            base_url=str(settings.base_url).rstrip("/"),
            upstream_name="anthropic",
            state_max_entries=settings.state_max_entries,
            request_id_header="request-id",
        )


def _system_text_from_body(body: dict[str, Any]) -> str | None:
    parts: list[str] = []
    instructions = body.get("instructions")
    if isinstance(instructions, str) and instructions.strip():
        parts.append(instructions.strip())
    input_ = body.get("input")
    if isinstance(input_, list):
        for item in input_:
            if not isinstance(item, dict):
                continue
            role = item.get("role")
            content = item.get("content")
            if role in {"developer", "system"} and isinstance(content, str) and content.strip():
                parts.append(content.strip())
    return "\n\n".join(parts) if parts else None


def _to_anthropic_tools(tools: list[object], names: ToolNameMapping) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for tool in tools:
        if not isinstance(tool, dict) or tool.get("type") != "function":
            continue
        name = tool.get("name")
        if not isinstance(name, str) or not name.strip():
            continue
        out.append(
            {
                "name": names.model_name_for_source(name.strip()),
                "description": tool.get("description") or "",
                "input_schema": tool.get("parameters") if isinstance(tool.get("parameters"), dict) else {"type": "object"},
            }
        )
    return out


def _to_anthropic_tool_choice(tool_choice: object, names: ToolNameMapping) -> dict[str, Any] | None:
    if tool_choice is None or tool_choice == "auto":
        return {"type": "auto"}
    if tool_choice == "none":
        return {"type": "none"}
    if tool_choice == "required":
        return {"type": "any"}
    if isinstance(tool_choice, dict) and tool_choice.get("type") == "function":
        name = tool_choice.get("name")
        if isinstance(name, str) and name.strip():
            return {"type": "tool", "name": names.model_name_for_source(name.strip())}
    return None


def create_anthropic_messages_model_provider(
    *, settings: AnthropicMessagesModelProviderSettings
) -> AnthropicMessagesModelProvider:
    client = httpx.AsyncClient()
    return AnthropicMessagesModelProvider(client=client, settings=settings)


def get_default_anthropic_model_provider(
    settings: AnthropicMessagesModelProviderSettings | None = None,
) -> AnthropicMessagesModelProvider:
    if settings is None:
        settings = AnthropicMessagesModelProviderSettings()
    key = (str(settings.base_url).rstrip("/"), settings.api_key, settings.anthropic_version, settings.state_max_entries)
    return _cached_default_provider(*key)


@lru_cache(maxsize=8)
def _cached_default_provider(
    base_url: str,
    api_key: str,
    anthropic_version: str,
    state_max_entries: int,
) -> AnthropicMessagesModelProvider:
    settings = AnthropicMessagesModelProviderSettings(
        ANTHROPIC_BASE_URL=base_url,
        ANTHROPIC_API_KEY=api_key,
        ANTHROPIC_VERSION=anthropic_version,
        ANYAGENT_ANTHROPIC_STATE_MAX=state_max_entries,
    )
    return create_anthropic_messages_model_provider(settings=settings)
