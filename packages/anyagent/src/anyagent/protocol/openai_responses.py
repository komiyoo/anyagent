from __future__ import annotations

import json
import time
from typing import TYPE_CHECKING, Any, Literal, TypeAlias

from pydantic import AliasChoices, BaseModel, ConfigDict, Field, TypeAdapter

from .sse import normalize_response_id
from .sse import SSEEvent

# Re-export a few OpenAI SDK param models so callers can validate request shapes
# without duplicating fast-moving schema definitions.
from openai.types.responses.function_tool_param import FunctionToolParam
from openai.types.responses.tool_choice_function_param import ToolChoiceFunctionParam

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

    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    type: Literal["function"] = "function"
    name: str
    description: str | None = None
    parameters: dict[str, Any] = Field(default_factory=dict)
    strict: bool = True
    x_anyagent_kind: Literal["command", "mcp"] | None = Field(
        default=None,
        validation_alias=AliasChoices("x-anyagent-kind", "x_anyagent_kind"),
        serialization_alias="x-anyagent-kind",
    )
    x_anyagent_cli: dict[str, Any] | None = Field(
        default=None,
        validation_alias=AliasChoices("x-anyagent-cli", "x_anyagent_cli"),
        serialization_alias="x-anyagent-cli",
    )
    x_anyagent_source_name: str | None = Field(
        default=None,
        validation_alias=AliasChoices("x-anyagent-source-name", "x_anyagent_source_name"),
        serialization_alias="x-anyagent-source-name",
    )


def validate_tool_choice(tool_choice: Any, allowed_tool_names: set[str]) -> str | None:
    """Validate `tool_choice` against an allowlist and return an error message when invalid."""

    if tool_choice is None:
        return None
    if isinstance(tool_choice, str) and tool_choice in {"auto", "none", "required"}:
        return None
    if isinstance(tool_choice, dict) and tool_choice.get("type") == "function":
        try:
            tc = TypeAdapter(ToolChoiceFunctionParam).validate_python(tool_choice)
        except Exception:  # noqa: BLE001
            return "invalid tool_choice"

        name: str | None
        if isinstance(tc, dict):
            raw_name = tc.get("name")
            name = raw_name if isinstance(raw_name, str) else None
        else:
            raw_name = getattr(tc, "name", None)
            name = raw_name if isinstance(raw_name, str) else None

        if isinstance(name, str) and name in allowed_tool_names:
            return None
        return f"tool_choice function name not allowed: {name}"
    return "invalid tool_choice"


def extract_function_calls_from_response_json(response_json: dict[str, Any]) -> list[dict[str, Any]]:
    """Extract function call items from an OpenAI Responses JSON payload."""

    output = response_json.get("output")
    if not isinstance(output, list):
        return []
    out: list[dict[str, Any]] = []
    for item in output:
        if isinstance(item, dict) and item.get("type") == "function_call":
            out.append(item)
    return out


def parse_tool_arguments_object(arguments_json: Any) -> dict[str, Any]:
    """Parse tool arguments into a JSON object."""

    if isinstance(arguments_json, dict):
        return arguments_json
    if isinstance(arguments_json, str):
        raw = arguments_json.strip()
        if not raw:
            return {}
        try:
            obj = json.loads(raw)
        except Exception as e:  # noqa: BLE001
            raise ValueError(f"invalid tool arguments json: {e}") from e
        if not isinstance(obj, dict):
            raise ValueError("tool arguments must be a JSON object")
        return obj
    raise ValueError("tool arguments must be a JSON object")


def decode_completed_response_payload(data: str) -> dict[str, Any] | None:
    """Decode one `response.completed` data payload into response JSON."""

    try:
        payload = json.loads(data)
    except Exception:  # noqa: BLE001
        return None
    if not isinstance(payload, dict):
        return None
    resp = payload.get("response")
    if isinstance(resp, dict):
        return resp
    if isinstance(payload.get("id"), str):
        return payload
    return None


def normalize_completed_response_event_data(
    data: str,
    *,
    canonical_response_id: str | None = None,
) -> tuple[dict[str, Any], str] | None:
    completed = decode_completed_response_payload(data)
    if completed is None:
        return None

    try:
        payload = json.loads(data)
    except Exception:  # noqa: BLE001
        payload = {"type": "response.completed", "response": completed}
    if not isinstance(payload, dict):
        payload = {"type": "response.completed", "response": completed}

    if isinstance(canonical_response_id, str) and canonical_response_id.strip():
        canonical = canonical_response_id.strip()
        normalize_response_id(payload, canonical)
        normalize_response_id(completed, canonical)

    return completed, json.dumps(payload, ensure_ascii=False, separators=(",", ":"))


def ensure_completed_response_event_data(
    data: str,
    *,
    response_id: str,
    fallback_model: str = "unknown",
    canonical_response_id: str | None = None,
) -> tuple[dict[str, Any], str]:
    normalized = normalize_completed_response_event_data(
        data,
        canonical_response_id=canonical_response_id,
    )
    if normalized is not None:
        return normalized

    completed = build_minimal_openai_response_json(
        response_id=canonical_response_id.strip() if isinstance(canonical_response_id, str) and canonical_response_id.strip() else response_id,
        status="completed",
        model=fallback_model,
    )
    payload = {"type": "response.completed", "response": completed}
    return completed, json.dumps(payload, ensure_ascii=False, separators=(",", ":"))


def serialize_completed_response_event_data(
    response_json: dict[str, Any],
    *,
    canonical_response_id: str | None = None,
) -> tuple[dict[str, Any], str]:
    payload = json.loads(json.dumps({"type": "response.completed", "response": response_json}, ensure_ascii=False))
    response_copy = payload["response"]
    if isinstance(canonical_response_id, str) and canonical_response_id.strip():
        canonical = canonical_response_id.strip()
        normalize_response_id(payload, canonical)
        normalize_response_id(response_copy, canonical)
    return response_copy, json.dumps(payload, ensure_ascii=False, separators=(",", ":"))


OpenAIResponseStatus: TypeAlias = Literal["completed", "failed", "in_progress", "cancelled", "queued", "incomplete"]


def build_minimal_openai_response_json(
    *,
    response_id: str,
    status: OpenAIResponseStatus,
    created_at_s: float | None = None,
    model: str = "unknown",
    tools: list[dict[str, Any]] | None = None,
    tool_choice: object = "none",
    parallel_tool_calls: bool = False,
    output: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Build a minimal OpenAI `Response` JSON payload for retrieve/cancel compatibility."""

    created_at = float(created_at_s) if isinstance(created_at_s, (int, float)) else float(time.time())
    return {
        "id": str(response_id),
        "object": "response",
        "created_at": created_at,
        "model": str(model),
        "output": list(output) if isinstance(output, list) else [],
        "parallel_tool_calls": bool(parallel_tool_calls),
        "tool_choice": tool_choice,
        "tools": list(tools) if isinstance(tools, list) else [],
        "status": str(status),
    }


def inject_text_into_responses_body(*, body: dict[str, Any], text: str, role: Literal["developer", "system"] = "developer") -> dict[str, Any]:
    """Inject one developer/system message into Responses body input before user content."""

    if not isinstance(text, str) or not text.strip():
        return body

    body2 = dict(body)
    injection_msg = {"role": role, "content": text}
    inp = body2.get("input")

    if isinstance(inp, str):
        body2["input"] = [injection_msg, {"role": "user", "content": inp}]
        return body2

    if inp is None:
        body2["input"] = [injection_msg]
        return body2

    if isinstance(inp, list):
        out = list(inp)
        insert_at = 0
        for i, item in enumerate(out):
            if isinstance(item, dict) and isinstance(item.get("role"), str):
                item_role = item["role"]
                if item_role in {"system", "developer"}:
                    insert_at = i + 1
                    continue
            break
        out.insert(insert_at, injection_msg)
        body2["input"] = out
        return body2

    return body

# ---- Stronger types (reuse OpenAI SDK schemas) ----
#
# We deliberately reuse OpenAI official SDK models for response / stream event shapes:
# - `openai.types.responses.response.Response` (alias: `OpenAIResponse`)
# - `openai.types.responses.response_stream_event.ResponseStreamEvent` (alias: `OpenAIResponseStreamEvent`)
#
# This avoids duplicating a fast-moving schema in anyagent, while still giving
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
