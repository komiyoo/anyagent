from __future__ import annotations

import json
from typing import TYPE_CHECKING, Any, Literal, TypeAlias

from pydantic import BaseModel, ConfigDict, Field

from .sse import SSEEvent

if TYPE_CHECKING:
    from openai.types.responses.response import Response as OpenAIResponse
    from openai.types.responses.response_stream_event import ResponseStreamEvent as OpenAIResponseStreamEvent
else:
    OpenAIResponse: TypeAlias = object
    OpenAIResponseStreamEvent: TypeAlias = object


class AnyAgentFunctionToolParam(BaseModel):
    """
    OpenAI Responses API-compatible function tool schema.

    Note:
    - Tool Runtime / Agent API exchange tools using this shape.
    - Response / stream event shapes should reuse OpenAI SDK schemas instead.
    """

    model_config = ConfigDict(extra="forbid")

    type: Literal["function"] = "function"
    name: str
    description: str | None = None
    parameters: dict[str, Any] = Field(default_factory=dict)
    strict: bool = True

# ---- Stronger types (reuse OpenAI SDK schemas) ----
#
# We deliberately reuse OpenAI official SDK models for response / stream event shapes:
# - `openai.types.responses.response.Response` (alias: `OpenAIResponse`)
# - `openai.types.responses.response_stream_event.ResponseStreamEvent` (alias: `OpenAIResponseStreamEvent`)
#
# This avoids duplicating a fast-moving schema in AnyAgent, while still giving
# downstream callers a strong, discoverable type surface.


def decode_openai_response(payload: object) -> OpenAIResponse | None:
    """
    Decode a JSON-like payload into OpenAI SDK `Response` model.
    Returns None if the payload is not a valid Response.
    """
    from openai.types.responses.response import Response

    try:
        return Response.model_validate(payload)
    except Exception:  # noqa: BLE001
        return None


def decode_openai_response_json(data: str) -> OpenAIResponse | None:
    try:
        payload = json.loads(data)
    except Exception:  # noqa: BLE001
        return None
    return decode_openai_response(payload)


def decode_openai_response_stream_event(payload: object) -> OpenAIResponseStreamEvent | None:
    """
    Decode a JSON-like payload into OpenAI SDK `ResponseStreamEvent` (discriminated union by `type`).
    Returns None if the payload is not a valid stream event.
    """
    from pydantic import TypeAdapter
    from openai.types.responses.response_stream_event import ResponseStreamEvent

    try:
        return TypeAdapter(ResponseStreamEvent).validate_python(payload)
    except Exception:  # noqa: BLE001
        return None


def decode_openai_response_stream_event_json(
    data: str,
) -> OpenAIResponseStreamEvent | None:
    try:
        payload = json.loads(data)
    except Exception:  # noqa: BLE001
        return None
    return decode_openai_response_stream_event(payload)


def dump_openai_response(resp: OpenAIResponse) -> dict[str, Any]:
    """
    Convert OpenAI SDK Response model back into a plain dict (JSON-ready).
    """
    return resp.model_dump(exclude_none=True, by_alias=True)


def decode_openai_response_stream_event_from_sse(
    event: str | None, data: str
) -> OpenAIResponseStreamEvent | None:
    """
    Decode one SSE block (event + data) into a typed `ResponseStreamEvent`.

    Notes:
    - The OpenAI SDK stream event union is discriminated by `payload.type`, not by SSE `event:` line.
    - `[DONE]` (non-JSON) returns None.
    """
    _ = event
    if not isinstance(data, str) or data.strip() == "[DONE]" or not data.strip():
        return None
    return decode_openai_response_stream_event_json(data)


def decode_openai_response_stream_events_from_sse(
    events: list[SSEEvent],
) -> list[OpenAIResponseStreamEvent]:
    """
    Decode a buffered SSE transcript (event,data pairs) into typed OpenAI `ResponseStreamEvent`s.

    `[DONE]` blocks are ignored.
    """
    out: list[OpenAIResponseStreamEvent] = []
    for ev, data in events:
        typed = decode_openai_response_stream_event_from_sse(ev, data)
        if typed is not None:
            out.append(typed)
    return out
