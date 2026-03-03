from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

import httpx
from fastapi import Request

from anyagent.protocol.sse import SSEEvent

from .openai_proxy import _pick_upstream_headers  # noqa: PLC2701
from ..settings import Settings


if TYPE_CHECKING:
    from openai.types.responses.response import Response
    from openai.types.responses.response_stream_event import ResponseStreamEvent


@dataclass(slots=True)
class ResponsesSSEBuffer:
    status_code: int
    raw_events: list[SSEEvent]
    typed_events: list["ResponseStreamEvent"]
    completed: "Response | None"
    raw_text: str


async def create_responses_json(
    *,
    client: httpx.AsyncClient,
    request: Request,
    settings: Settings,
    body: dict[str, Any],
    forward_idempotency_key: bool,
) -> tuple[int, dict[str, Any]]:
    url = str(settings.openai_base_url).rstrip("/") + "/responses"
    headers = _pick_upstream_headers(request, settings)
    if not forward_idempotency_key:
        headers.pop("idempotency-key", None)

    r = await client.post(url, headers=headers, json=body, timeout=60.0)
    try:
        data = r.json()
    except Exception:  # noqa: BLE001
        data = {"error": {"message": r.text, "type": "upstream_error"}}
    return r.status_code, data


def _parse_sse_events(text: str) -> list[tuple[str | None, str]]:
    from anyagent.protocol.sse import parse_sse_events

    return parse_sse_events(text)


def _extract_completed_response(events: list[tuple[str | None, str]]) -> dict[str, Any] | None:
    from anyagent.protocol.sse import extract_completed_response

    return extract_completed_response(events)


async def create_responses_sse_events(
    *,
    client: httpx.AsyncClient,
    request: Request,
    settings: Settings,
    body: dict[str, Any],
    forward_idempotency_key: bool,
) -> tuple[int, list[SSEEvent], dict[str, Any] | None, str]:
    url = str(settings.openai_base_url).rstrip("/") + "/responses"
    headers = _pick_upstream_headers(request, settings)
    if not forward_idempotency_key:
        headers.pop("idempotency-key", None)

    async with client.stream("POST", url, headers=headers, json=body, timeout=None) as r:
        raw = await r.aread()
        text = raw.decode("utf-8", errors="replace")
        events = _parse_sse_events(text)
        completed = _extract_completed_response(events)
        return r.status_code, events, completed, text


async def create_responses_sse_events_typed(
    *,
    client: httpx.AsyncClient,
    request: Request,
    settings: Settings,
    body: dict[str, Any],
    forward_idempotency_key: bool,
) -> ResponsesSSEBuffer:
    """
    Same as `create_responses_sse_events`, but also decodes:
    - completed response -> OpenAI SDK `Response`
    - each SSE block -> OpenAI SDK `ResponseStreamEvent`
    """
    status, events, completed, text = await create_responses_sse_events(
        client=client,
        request=request,
        settings=settings,
        body=body,
        forward_idempotency_key=forward_idempotency_key,
    )
    from anyagent.protocol.openai_responses import (
        decode_openai_response,
        decode_openai_response_stream_events_from_sse,
    )

    return ResponsesSSEBuffer(
        status_code=status,
        raw_events=events,
        typed_events=decode_openai_response_stream_events_from_sse(events),
        completed=decode_openai_response(completed),
        raw_text=text,
    )
