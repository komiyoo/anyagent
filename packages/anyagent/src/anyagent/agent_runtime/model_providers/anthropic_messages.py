from __future__ import annotations

import json
import time
from collections import OrderedDict
from dataclasses import dataclass
from functools import lru_cache
from hashlib import sha1
from typing import Any
from uuid import uuid4

import httpx
from pydantic import AnyHttpUrl, Field
from pydantic_settings import BaseSettings, SettingsConfigDict

from openai.types.responses.response import Response
from openai.types.responses.response_completed_event import ResponseCompletedEvent
from openai.types.responses.response_created_event import ResponseCreatedEvent
from openai.types.responses.response_function_tool_call import ResponseFunctionToolCall
from openai.types.responses.response_output_message import ResponseOutputMessage
from openai.types.responses.response_output_text import ResponseOutputText
from openai.types.responses.response_stream_event import ResponseStreamEvent

from .base import (
    BufferedLiveResponseStream,
    ModelProvider,
    ModelProviderInvalidRequestError,
    ModelProviderTransportError,
    ModelProviderUpstreamError,
)


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


@dataclass(slots=True)
class _ConversationState:
    messages: list[dict[str, Any]]


class AnthropicMessagesModelProvider(ModelProvider):
    """
    ModelProvider backed by Anthropic Messages API.

    This provider maintains an in-memory conversation store to emulate OpenAI's
    `previous_response_id` behavior. It is intended for local / single-process usage.
    """

    def __init__(self, *, client: httpx.AsyncClient, settings: AnthropicMessagesModelProviderSettings) -> None:
        self._client = client
        self._settings = settings
        self._state: "OrderedDict[str, _ConversationState]" = OrderedDict()
        self._idem: dict[str, Response] = {}

    async def create_response(
        self,
        *,
        body: dict[str, Any],
        idempotency_key: str | None = None,
        timeout_s: float = 60.0,
    ) -> Response:
        if idempotency_key and idempotency_key in self._idem:
            return self._idem[idempotency_key]

        try:
            resp = await self._create_response_impl(body=body, timeout_s=timeout_s)
        except httpx.TimeoutException as e:
            raise ModelProviderTransportError(str(e)) from e
        except httpx.RequestError as e:
            raise ModelProviderTransportError(str(e)) from e

        if idempotency_key:
            self._idem[idempotency_key] = resp
        return resp

    async def create_response_stream_buffered(
        self,
        *,
        body: dict[str, Any],
        idempotency_key: str | None = None,
        timeout_s: float | None = None,
    ) -> tuple[list[ResponseStreamEvent], Response]:
        resp = await self.create_response(body=body, idempotency_key=idempotency_key, timeout_s=timeout_s or 60.0)
        created = ResponseCreatedEvent(type="response.created", sequence_number=0, response=resp)
        completed = ResponseCompletedEvent(type="response.completed", sequence_number=1, response=resp)
        return [created, completed], resp

    async def create_response_stream_live(
        self,
        *,
        body: dict[str, Any],
        idempotency_key: str | None = None,
        timeout_s: float | None = None,
    ) -> BufferedLiveResponseStream:
        events, completed = await self.create_response_stream_buffered(
            body=body,
            idempotency_key=idempotency_key,
            timeout_s=timeout_s,
        )
        return BufferedLiveResponseStream(events=events, completed=completed)

    async def _create_response_impl(self, *, body: dict[str, Any], timeout_s: float) -> Response:
        model = body.get("model")
        if not isinstance(model, str) or not model.strip():
            raise ModelProviderInvalidRequestError("missing body.model")
        model = model.strip()

        previous_response_id = body.get("previous_response_id")
        prev_id = previous_response_id.strip() if isinstance(previous_response_id, str) and previous_response_id.strip() else None

        tools = body.get("tools") if isinstance(body.get("tools"), list) else []
        tool_choice = body.get("tool_choice")

        tool_name_map = _build_tool_name_map(tools)
        tool_choice_req = _to_anthropic_tool_choice(tool_choice, tool_name_map)
        tools_req = _to_anthropic_tools(tools, tool_name_map)

        system = body.get("instructions")
        system_str = system.strip() if isinstance(system, str) and system.strip() else None

        max_tokens = body.get("max_output_tokens")
        if isinstance(max_tokens, int) and 1 <= max_tokens <= 8192:
            max_tokens_i = max_tokens
        else:
            max_tokens_i = 1024

        input_ = body.get("input")
        if prev_id is None:
            conv = _ConversationState(messages=_input_to_anthropic_messages(input_))
        else:
            prev = self._state.get(prev_id)
            if prev is None:
                raise ModelProviderInvalidRequestError(f"unknown previous_response_id: {prev_id}")
            followup = _input_to_anthropic_messages(input_)
            conv = _ConversationState(messages=[*prev.messages, *followup])

        payload: dict[str, Any] = {
            "model": model,
            "max_tokens": max_tokens_i,
            "messages": conv.messages,
        }
        if system_str is not None:
            payload["system"] = system_str
        if tools_req:
            payload["tools"] = tools_req
            if tool_choice_req is not None:
                payload["tool_choice"] = tool_choice_req

        r = await self._client.post(
            str(self._settings.base_url).rstrip("/") + "/messages",
            headers={
                "x-api-key": self._settings.api_key,
                "anthropic-version": self._settings.anthropic_version,
            },
            json=payload,
            timeout=timeout_s,
        )

        if r.status_code >= 400:
            body_obj: object | None
            try:
                body_obj = r.json()
            except Exception:  # noqa: BLE001
                body_obj = {"error": {"message": r.text}}
            raise ModelProviderUpstreamError(
                status_code=r.status_code,
                body=body_obj,
                raw=r.content,
                request_id=r.headers.get("request-id"),
                message="anthropic upstream error",
            )

        data = r.json()
        if not isinstance(data, dict):
            raise ModelProviderTransportError("unexpected upstream response (not an object)")

        content = data.get("content")
        if not isinstance(content, list):
            raise ModelProviderTransportError("unexpected upstream response (missing content)")

        out_items: list[dict[str, Any]] = []
        text_parts: list[str] = []
        for block in content:
            if not isinstance(block, dict):
                continue
            t = block.get("type")
            if t == "text":
                txt = block.get("text")
                if isinstance(txt, str) and txt:
                    text_parts.append(txt)
                continue
            if t == "tool_use":
                tool_use_id = block.get("id")
                mapped_name = block.get("name")
                tool_input = block.get("input")
                if not isinstance(tool_use_id, str) or not isinstance(mapped_name, str):
                    continue
                orig_name = tool_name_map.get(mapped_name) or mapped_name
                args_json = json.dumps(tool_input if tool_input is not None else {}, ensure_ascii=False, separators=(",", ":"))
                out_items.append(
                    ResponseFunctionToolCall(
                        type="function_call",
                        call_id=tool_use_id,
                        name=orig_name,
                        arguments=args_json,
                    ).model_dump(exclude_none=True, by_alias=True)
                )

        text = "".join(text_parts).strip()
        if text:
            out_items.append(
                ResponseOutputMessage(
                    id=f"msg_{uuid4().hex}",
                    type="message",
                    role="assistant",
                    status="completed",
                    content=[ResponseOutputText(type="output_text", text=text, annotations=[])],
                ).model_dump(exclude_none=True, by_alias=True)
            )

        resp_id = f"resp_{uuid4().hex}"
        created_at = int(time.time())
        tools_resp = tools if isinstance(tools, list) else []
        tool_choice_resp = tool_choice if tool_choice is not None else "auto"
        parallel_tool_calls = body.get("parallel_tool_calls")
        parallel = bool(parallel_tool_calls) if isinstance(parallel_tool_calls, bool) else False

        response_payload: dict[str, Any] = {
            "id": resp_id,
            "object": "response",
            "created_at": created_at,
            "model": model,
            "output": out_items,
            "parallel_tool_calls": parallel,
            "tool_choice": tool_choice_resp,
            "tools": tools_resp,
        }

        resp = Response.model_validate(response_payload)

        # Persist conversation state for `previous_response_id` follow-ups.
        self._remember(resp_id, conv.messages, assistant_content=content)
        return resp

    def _remember(self, response_id: str, messages: list[dict[str, Any]], *, assistant_content: list[dict[str, Any]]) -> None:
        new_messages = [*messages, {"role": "assistant", "content": assistant_content}]
        self._state[response_id] = _ConversationState(messages=new_messages)
        self._state.move_to_end(response_id)
        while len(self._state) > self._settings.state_max_entries:
            self._state.popitem(last=False)


def _input_to_anthropic_messages(input_: object) -> list[dict[str, Any]]:
    if isinstance(input_, str):
        s = input_.strip()
        if not s:
            return []
        return [{"role": "user", "content": s}]

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

        # Best-effort support for OpenAI-like message dicts.
        if isinstance(item, dict) and isinstance(item.get("role"), str):
            role = item.get("role")
            content = item.get("content")
            if role in {"user", "assistant"} and isinstance(content, str) and content.strip():
                messages.append({"role": role, "content": content.strip()})
            continue

    if tool_results:
        messages.append({"role": "user", "content": tool_results})
    return messages


def _build_tool_name_map(tools: list[object]) -> dict[str, str]:
    """
    Anthropic tool names must be [a-zA-Z0-9_-], while anyagent tool names are dot-namespaced.

    Returns a mapping from `anthropic_tool_name` -> `original_tool_name`.
    """
    out: dict[str, str] = {}
    used: set[str] = set()
    for t in tools:
        if not isinstance(t, dict) or t.get("type") != "function":
            continue
        name = t.get("name")
        if not isinstance(name, str) or not name.strip():
            continue
        orig = name.strip()
        mapped = _map_tool_name(orig)
        if mapped in used:
            mapped = f"{mapped[:55]}_{sha1(orig.encode('utf-8')).hexdigest()[:8]}"
        used.add(mapped)
        out[mapped] = orig
    return out


def _map_tool_name(name: str) -> str:
    buf = []
    for ch in name:
        if ch.isalnum() or ch in {"_", "-"}:
            buf.append(ch)
        else:
            buf.append("_")
    s = "".join(buf)
    if len(s) > 55:
        s = s[:55]
    suffix = sha1(name.encode("utf-8")).hexdigest()[:8]
    return f"{s}_{suffix}"


def _to_anthropic_tools(tools: list[object], name_map: dict[str, str]) -> list[dict[str, Any]]:
    inv = {v: k for k, v in name_map.items()}
    out: list[dict[str, Any]] = []
    for t in tools:
        if not isinstance(t, dict) or t.get("type") != "function":
            continue
        name = t.get("name")
        if not isinstance(name, str) or not name.strip():
            continue
        mapped = inv.get(name.strip())
        if not mapped:
            continue
        out.append(
            {
                "name": mapped,
                "description": t.get("description") or "",
                "input_schema": t.get("parameters") if isinstance(t.get("parameters"), dict) else {"type": "object"},
            }
        )
    return out


def _to_anthropic_tool_choice(tool_choice: object, name_map: dict[str, str]) -> dict[str, Any] | None:
    inv = {v: k for k, v in name_map.items()}
    if tool_choice is None or tool_choice == "auto":
        return {"type": "auto"}
    if tool_choice == "none":
        return {"type": "none"}
    if isinstance(tool_choice, dict) and tool_choice.get("type") == "function":
        name = tool_choice.get("name")
        if isinstance(name, str) and name.strip():
            mapped = inv.get(name.strip())
            if mapped:
                return {"type": "tool", "name": mapped}
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
def _cached_default_provider(base_url: str, api_key: str, anthropic_version: str, state_max_entries: int) -> AnthropicMessagesModelProvider:
    settings = AnthropicMessagesModelProviderSettings(
        ANTHROPIC_BASE_URL=base_url,
        ANTHROPIC_API_KEY=api_key,
        ANTHROPIC_VERSION=anthropic_version,
        ANYAGENT_ANTHROPIC_STATE_MAX=state_max_entries,
    )
    return create_anthropic_messages_model_provider(settings=settings)
