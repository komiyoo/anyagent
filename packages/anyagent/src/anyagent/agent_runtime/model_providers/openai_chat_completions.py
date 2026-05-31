from __future__ import annotations

import json
from functools import lru_cache
from typing import Any

import httpx
from pydantic import AnyHttpUrl, Field
from pydantic_settings import BaseSettings, SettingsConfigDict

from ._capabilities import OPENAI_FULL, ProviderCapabilities
from ._translation import ToolNameMapping, VendorRequest, VendorToolCall, VendorTranslation
from ._translating_provider import TranslatingModelProvider


class OpenAIChatCompletionsModelProviderSettings(BaseSettings):
    """
    OpenAI Chat Completions API settings.

    Env:
    - OPENAI_API_KEY
    - OPENAI_BASE_URL (default: https://api.openai.com/v1)
    - ANYAGENT_OPENAI_CHAT_STATE_MAX (default: 1024)
    """

    model_config = SettingsConfigDict(env_file=None, extra="ignore")

    api_key: str = Field(alias="OPENAI_API_KEY")
    base_url: AnyHttpUrl = Field(default="https://api.openai.com/v1", alias="OPENAI_BASE_URL")
    state_max_entries: int = Field(default=1024, ge=1, le=100_000, alias="ANYAGENT_OPENAI_CHAT_STATE_MAX")


# --- Translator ---


class OpenAIChatCompletionsTranslator:
    capabilities: ProviderCapabilities = OPENAI_FULL

    def build_request(
        self,
        *,
        body: dict[str, Any],
        turns: list[dict[str, Any]],
        names: ToolNameMapping,
        settings: object,
    ) -> VendorRequest:
        if not isinstance(settings, OpenAIChatCompletionsModelProviderSettings):
            raise TypeError("settings must be OpenAIChatCompletionsModelProviderSettings")

        payload: dict[str, Any] = {
            "model": str(body["model"]).strip(),
            "messages": [],
        }

        # System message from instructions + developer/system items
        system = _system_text_from_body(body)
        if system:
            payload["messages"].append({"role": "system", "content": system})

        payload["messages"].extend(turns)

        # Tools
        tools_req = _to_chat_tools(body.get("tools") if isinstance(body.get("tools"), list) else [], names)
        if tools_req:
            payload["tools"] = tools_req
            tool_choice = _to_chat_tool_choice(body.get("tool_choice"), names)
            if tool_choice is not None:
                payload["tool_choice"] = tool_choice

        # Pass through optional params
        max_tokens = body.get("max_output_tokens")
        if isinstance(max_tokens, int) and max_tokens >= 1:
            payload["max_tokens"] = max_tokens
        temperature = body.get("temperature")
        if temperature is not None:
            payload["temperature"] = temperature
        top_p = body.get("top_p")
        if top_p is not None:
            payload["top_p"] = top_p

        # Pass through extra params that upstream might support
        for key in ("store", "reasoning_effort", "stream"):
            val = body.get(key)
            if val is not None:
                payload[key] = val

        return VendorRequest(
            url_path="/chat/completions",
            headers={"Authorization": f"Bearer {settings.api_key}"},
            payload=payload,
        )

    def parse_response(self, *, data: dict[str, Any], names: ToolNameMapping) -> VendorTranslation:
        choices = data.get("choices")
        if not isinstance(choices, list) or not choices:
            return VendorTranslation()

        message = choices[0].get("message") if isinstance(choices[0], dict) else {}
        if not isinstance(message, dict):
            message = {}

        text = message.get("content") or ""
        tool_calls: list[VendorToolCall] = []
        raw_tool_calls = message.get("tool_calls")
        if isinstance(raw_tool_calls, list):
            for tc in raw_tool_calls:
                if not isinstance(tc, dict):
                    continue
                tc_id = tc.get("id")
                func = tc.get("function")
                if not isinstance(tc_id, str) or not isinstance(func, dict):
                    continue
                model_name = func.get("name")
                arguments = func.get("arguments")
                if not isinstance(model_name, str):
                    continue
                tool_calls.append(
                    VendorToolCall(
                        call_id=tc_id,
                        name=names.source_name_for_model(model_name),
                        arguments_json=arguments if isinstance(arguments, str) else "{}",
                    )
                )

        return VendorTranslation(
            text=text.strip() if isinstance(text, str) else "",
            tool_calls=tool_calls,
            raw_assistant_turn=message,
        )

    def input_to_turns(self, *, input_: object, names: ToolNameMapping) -> list[dict[str, Any]]:
        if isinstance(input_, str):
            s = input_.strip()
            return [{"role": "user", "content": s}] if s else []

        if not isinstance(input_, list):
            return []

        messages: list[dict[str, Any]] = []
        pending_tool_calls: list[dict[str, Any]] = []

        for item in input_:
            if not isinstance(item, dict):
                continue

            item_type = item.get("type")
            role = item.get("role")

            # function_call items -> group into assistant message with tool_calls
            if item_type == "function_call":
                call_id = item.get("call_id")
                fn_name = item.get("name")
                arguments = item.get("arguments")
                if isinstance(call_id, str) and isinstance(fn_name, str):
                    pending_tool_calls.append({
                        "id": call_id,
                        "type": "function",
                        "function": {
                            "name": names.model_name_for_source(fn_name),
                            "arguments": arguments if isinstance(arguments, str) else "{}",
                        },
                    })
                continue

            # function_call_output -> flush pending tool_calls, then add tool message
            if item_type == "function_call_output":
                if pending_tool_calls:
                    messages.append({"role": "assistant", "tool_calls": pending_tool_calls})
                    pending_tool_calls = []
                call_id = item.get("call_id")
                output = item.get("output")
                if isinstance(call_id, str) and isinstance(output, str):
                    messages.append({"role": "tool", "tool_call_id": call_id, "content": output})
                continue

            # Role-based items (skip developer/system - handled in build_request)
            if isinstance(role, str):
                if pending_tool_calls:
                    messages.append({"role": "assistant", "tool_calls": pending_tool_calls})
                    pending_tool_calls = []
                if role in ("developer", "system"):
                    continue
                content = item.get("content")
                if role in ("user", "assistant") and isinstance(content, str) and content.strip():
                    messages.append({"role": role, "content": content.strip()})

        # Flush any remaining pending tool_calls
        if pending_tool_calls:
            messages.append({"role": "assistant", "tool_calls": pending_tool_calls})

        return messages


# --- Helpers ---


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
            if role in ("developer", "system") and isinstance(content, str) and content.strip():
                parts.append(content.strip())
    return "\n\n".join(parts) if parts else None


def _to_chat_tools(tools: list[object], names: ToolNameMapping) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for tool in tools:
        if not isinstance(tool, dict) or tool.get("type") != "function":
            continue
        name = tool.get("name")
        if not isinstance(name, str) or not name.strip():
            continue
        out.append({
            "type": "function",
            "function": {
                "name": names.model_name_for_source(name.strip()),
                "description": tool.get("description") or "",
                "parameters": tool.get("parameters") if isinstance(tool.get("parameters"), dict) else {"type": "object"},
            },
        })
    return out


def _to_chat_tool_choice(tool_choice: object, names: ToolNameMapping) -> str | dict[str, Any] | None:
    if tool_choice is None or tool_choice == "auto":
        return "auto"
    if tool_choice == "none":
        return "none"
    if tool_choice == "required":
        return "required"
    if isinstance(tool_choice, dict) and tool_choice.get("type") == "function":
        name = tool_choice.get("name")
        if isinstance(name, str) and name.strip():
            return {"type": "function", "function": {"name": names.model_name_for_source(name.strip())}}
    return None


# --- Provider class & factory ---


class OpenAIChatCompletionsModelProvider(TranslatingModelProvider):
    def __init__(self, *, client: httpx.AsyncClient, settings: OpenAIChatCompletionsModelProviderSettings) -> None:
        super().__init__(
            client=client,
            settings=settings,
            translator=OpenAIChatCompletionsTranslator(),
            base_url=str(settings.base_url).rstrip("/"),
            upstream_name="openai_chat",
            state_max_entries=settings.state_max_entries,
            request_id_header="x-request-id",
        )


def create_openai_chat_completions_model_provider(
    *, settings: OpenAIChatCompletionsModelProviderSettings,
) -> OpenAIChatCompletionsModelProvider:
    client = httpx.AsyncClient()
    return OpenAIChatCompletionsModelProvider(client=client, settings=settings)


def get_default_openai_chat_model_provider(
    settings: OpenAIChatCompletionsModelProviderSettings | None = None,
) -> OpenAIChatCompletionsModelProvider:
    if settings is None:
        settings = OpenAIChatCompletionsModelProviderSettings()
    key = (str(settings.base_url).rstrip("/"), settings.api_key, settings.state_max_entries)
    return _cached_default_openai_chat_provider(*key)


@lru_cache(maxsize=8)
def _cached_default_openai_chat_provider(
    base_url: str,
    api_key: str,
    state_max_entries: int,
) -> OpenAIChatCompletionsModelProvider:
    settings = OpenAIChatCompletionsModelProviderSettings(
        OPENAI_BASE_URL=base_url,
        OPENAI_API_KEY=api_key,
        ANYAGENT_OPENAI_CHAT_STATE_MAX=state_max_entries,
    )
    return create_openai_chat_completions_model_provider(settings=settings)
