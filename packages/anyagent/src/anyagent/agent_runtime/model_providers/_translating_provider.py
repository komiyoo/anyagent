from __future__ import annotations

import time
from typing import Any
from uuid import uuid4

import httpx

from openai.types.responses.response import Response
from openai.types.responses.response_completed_event import ResponseCompletedEvent
from openai.types.responses.response_created_event import ResponseCreatedEvent
from openai.types.responses.response_function_tool_call import ResponseFunctionToolCall
from openai.types.responses.response_output_message import ResponseOutputMessage
from openai.types.responses.response_output_text import ResponseOutputText
from openai.types.responses.response_stream_event import ResponseStreamEvent

from anyagent.protocol.openai_responses import validate_tool_choice
from anyagent.protocol.tool_manifest_extensions import build_model_tool_name_map, model_tool_name_for_name

from ._conversation_state import ConversationStateStore
from ._translation import ToolNameMapping, VendorTranslator
from .base import BufferedLiveResponseStream, ModelProvider, ModelProviderInvalidRequestError
from .vendor_http import post_json_normalized


class TranslatingModelProvider(ModelProvider):
    def __init__(
        self,
        *,
        client: httpx.AsyncClient,
        settings: object,
        translator: VendorTranslator,
        base_url: str,
        upstream_name: str,
        state_max_entries: int,
        request_id_header: str = "request-id",
    ) -> None:
        self._client = client
        self._settings = settings
        self._translator = translator
        self._base_url = base_url
        self._upstream_name = upstream_name
        self._request_id_header = request_id_header
        self._state = ConversationStateStore(max_entries=state_max_entries)

    async def create_response(
        self,
        *,
        body: dict[str, Any],
        idempotency_key: str | None = None,
        timeout_s: float = 60.0,
    ) -> Response:
        cached = self._state.get_idempotent(idempotency_key)
        if cached is not None:
            return cached
        resp = await self._create_response_impl(body=body, timeout_s=timeout_s)
        self._state.remember_idempotent(idempotency_key, resp)
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

        body2 = self._normalize_body(body)
        tools = body2.get("tools") if isinstance(body2.get("tools"), list) else []
        names = _build_tool_name_mapping(tools, max_len=self._translator.capabilities.tool_name_max_len)

        previous_response_id = body2.get("previous_response_id")
        prev_id = previous_response_id.strip() if isinstance(previous_response_id, str) and previous_response_id.strip() else None
        if prev_id is None:
            turns = self._translator.input_to_turns(input_=body2.get("input"), names=names)
        else:
            prev = self._state.get(prev_id)
            if prev is None:
                import logging
                logging.getLogger(__name__).warning("previous_response_id not in state, using input as-is: %s", prev_id)
                turns = self._translator.input_to_turns(input_=body2.get("input"), names=names)
            else:
                names = names.model_copy(update={"call_id_to_model_name": _scan_call_id_to_model_name(prev.turns, body2.get("input"))})
                turns = [*prev.turns, *self._translator.input_to_turns(input_=body2.get("input"), names=names)]

        req = self._translator.build_request(body=body2, turns=turns, names=names, settings=self._settings)
        data = await post_json_normalized(
            client=self._client,
            base_url=self._base_url,
            url_path=req.url_path,
            headers=req.headers,
            payload=req.payload,
            timeout_s=timeout_s,
            upstream_name=self._upstream_name,
            request_id_header=self._request_id_header,
        )
        translated = self._translator.parse_response(data=data, names=names)
        resp = _build_response(body=body2, model=model.strip(), text=translated.text, tool_calls=translated.tool_calls, usage=data.get("usage"))
        self._state.remember(resp.id, turns, assistant_turn=translated.raw_assistant_turn)
        return resp

    def _normalize_body(self, body: dict[str, Any]) -> dict[str, Any]:
        body2 = dict(body)
        caps = self._translator.capabilities
        tools = body2.get("tools") if isinstance(body2.get("tools"), list) else []
        if tools and not caps.supports_tools:
            raise ModelProviderInvalidRequestError(f"{self._upstream_name} does not support tools")

        tool_choice = body2.get("tool_choice")
        err = validate_tool_choice(tool_choice, _source_tool_names(tools))
        if err is not None:
            raise ModelProviderInvalidRequestError(err)
        if tool_choice == "required" and not caps.supports_tool_choice_required:
            raise ModelProviderInvalidRequestError(f"{self._upstream_name} does not support tool_choice=required")
        if isinstance(tool_choice, dict) and tool_choice.get("type") == "function" and not caps.supports_tool_choice_named:
            raise ModelProviderInvalidRequestError(f"{self._upstream_name} does not support named tool_choice")

        if not caps.supports_temperature:
            body2.pop("temperature", None)
        if not caps.supports_top_p:
            body2.pop("top_p", None)
        cap = caps.max_output_tokens_cap
        if isinstance(cap, int) and cap > 0:
            max_tokens = body2.get("max_output_tokens")
            if isinstance(max_tokens, int) and max_tokens > cap:
                body2["max_output_tokens"] = cap
        return body2


def _build_tool_name_mapping(tools: list[object], *, max_len: int | None) -> ToolNameMapping:
    typed_tools = [tool for tool in tools if isinstance(tool, dict)]
    model_to_source = build_model_tool_name_map(typed_tools, max_len=max_len)
    source_to_model: dict[str, str] = {}
    for tool in typed_tools:
        if tool.get("type") != "function":
            continue
        raw_name = tool.get("name")
        if isinstance(raw_name, str) and raw_name.strip():
            source = raw_name.strip()
            source_to_model[source] = model_tool_name_for_name(source, max_len=max_len)
    for model_name, source_name in model_to_source.items():
        source_to_model[source_name] = model_name
    return ToolNameMapping(model_to_source=model_to_source, source_to_model=source_to_model)


def _scan_call_id_to_model_name(turns: list[dict[str, Any]], input_: object = None) -> dict[str, str]:
    out: dict[str, str] = {}
    for turn in turns:
        _scan_turn_for_tool_calls(turn, out)
    if isinstance(input_, list):
        for item in input_:
            if isinstance(item, dict) and item.get("type") == "function_call":
                call_id = item.get("call_id")
                name = item.get("name")
                if isinstance(call_id, str) and isinstance(name, str):
                    out[call_id] = name
    return out


def _scan_turn_for_tool_calls(turn: dict[str, Any], out: dict[str, str]) -> None:
    # Anthropic format
    content = turn.get("content")
    if isinstance(content, list):
        for block in content:
            if isinstance(block, dict) and block.get("type") == "tool_use":
                call_id = block.get("id")
                name = block.get("name")
                if isinstance(call_id, str) and isinstance(name, str):
                    out[call_id] = name
    # Gemini format
    parts = turn.get("parts")
    if isinstance(parts, list):
        for part in parts:
            if not isinstance(part, dict):
                continue
            fc = part.get("functionCall")
            if isinstance(fc, dict):
                call_id = fc.get("id")
                name = fc.get("name")
                if isinstance(call_id, str) and isinstance(name, str):
                    out[call_id] = name
    # Chat Completions format
    tool_calls = turn.get("tool_calls")
    if isinstance(tool_calls, list):
        for tc in tool_calls:
            if isinstance(tc, dict) and tc.get("type") == "function":
                call_id = tc.get("id")
                func = tc.get("function")
                if isinstance(func, dict):
                    name = func.get("name")
                    if isinstance(call_id, str) and isinstance(name, str):
                        out[call_id] = name


def _source_tool_names(tools: list[object]) -> set[str]:
    out: set[str] = set()
    for tool in tools:
        if isinstance(tool, dict) and tool.get("type") == "function":
            name = tool.get("name")
            if isinstance(name, str) and name.strip():
                out.add(name.strip())
    return out


def _normalize_usage(raw: dict[str, Any]) -> dict[str, Any]:
    """Normalize Chat Completions usage format to Responses API format."""
    input_tokens = raw.get("input_tokens") or raw.get("prompt_tokens") or 0
    output_tokens = raw.get("output_tokens") or raw.get("completion_tokens") or 0
    result: dict[str, Any] = {
        "input_tokens": input_tokens,
        "output_tokens": output_tokens,
        "total_tokens": raw.get("total_tokens") or (input_tokens + output_tokens),
    }
    input_details = raw.get("input_tokens_details") or raw.get("prompt_tokens_details")
    if isinstance(input_details, dict):
        result["input_tokens_details"] = {"cached_tokens": input_details.get("cached_tokens", 0)}
    else:
        result["input_tokens_details"] = {"cached_tokens": 0}
    output_details = raw.get("output_tokens_details") or raw.get("completion_tokens_details")
    if isinstance(output_details, dict):
        result["output_tokens_details"] = {"reasoning_tokens": output_details.get("reasoning_tokens", 0)}
    else:
        result["output_tokens_details"] = {"reasoning_tokens": 0}
    return result


def _build_response(
    *,
    body: dict[str, Any],
    model: str,
    text: str,
    tool_calls: list[Any],
    usage: dict[str, Any] | None = None,
) -> Response:
    out_items: list[dict[str, Any]] = []
    for tool_call in tool_calls:
        out_items.append(
            ResponseFunctionToolCall(
                type="function_call",
                call_id=tool_call.call_id,
                name=tool_call.name,
                arguments=tool_call.arguments_json,
            ).model_dump(exclude_none=True, by_alias=True)
        )

    if text.strip():
        out_items.append(
            ResponseOutputMessage(
                id=f"msg_{uuid4().hex}",
                type="message",
                role="assistant",
                status="completed",
                content=[ResponseOutputText(type="output_text", text=text.strip(), annotations=[])],
            ).model_dump(exclude_none=True, by_alias=True)
        )

    parallel_tool_calls = body.get("parallel_tool_calls")
    payload = {
        "id": f"resp_{uuid4().hex}",
        "object": "response",
        "created_at": int(time.time()),
        "model": model,
        "output": out_items,
        "parallel_tool_calls": bool(parallel_tool_calls) if isinstance(parallel_tool_calls, bool) else False,
        "tool_choice": body.get("tool_choice") if body.get("tool_choice") is not None else "auto",
        "tools": body.get("tools") if isinstance(body.get("tools"), list) else [],
        "status": "completed",
    }
    if isinstance(usage, dict) and usage:
        payload["usage"] = _normalize_usage(usage)
    return Response.model_validate(payload)
