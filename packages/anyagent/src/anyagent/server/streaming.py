from __future__ import annotations

import json
from collections.abc import Awaitable, Callable
from typing import Any

from fastapi.responses import StreamingResponse

from anyagent.protocol.openai_responses import (
    ensure_completed_response_event_data,
    normalize_completed_response_event_data,
    build_minimal_openai_response_json,
)
from anyagent.protocol.sse import SSEBlockDecoder, encode_sse_block, encode_sse_event
from anyagent.storage import stream_external_response_blocks

from .finalization import finalize_nonstream_response


AppendEvent = Callable[[str | None, str], Awaitable[int | None]]
PersistFinal = Callable[[Any], Awaitable[None]]
MarkEventFinal = Callable[[Any], Awaitable[None]]
AdvanceSession = Callable[[Any], Awaitable[None]]
PersistBlock = Callable[[str | None, str], Awaitable[None]]


def build_external_response_stream_response(
    *,
    run_store: Any,
    event_store: Any,
    response_id: str,
    media_type: str = "text/event-stream",
    event_filter: Callable[[str | None], bool] | None = None,
) -> StreamingResponse:
    return StreamingResponse(
        stream_external_response_blocks(
            run_store=run_store,
            event_store=event_store,
            response_id=response_id,
            event_filter=event_filter,
        ),
        media_type=media_type,
    )


async def append_sse_chunk(
    *,
    chunk: bytes,
    decoder: SSEBlockDecoder,
    persist_block: PersistBlock,
) -> None:
    text = chunk.decode("utf-8", errors="replace")
    for line in text.splitlines():
        for blk in decoder.feed_line(line):
            await persist_block(blk.event, blk.data)


async def handle_persisted_sse_block(
    *,
    response_id: str,
    event: str | None,
    data: str,
    fallback_model: Any,
    append_event: AppendEvent,
    persist_run_final: PersistFinal,
    mark_event_final: MarkEventFinal | None = None,
    advance_session: AdvanceSession | None = None,
    persist_non_terminal_events: bool = True,
) -> None:
    if event is None and data.strip() == "[DONE]":
        return

    if event != "response.completed":
        if persist_non_terminal_events:
            await append_event(event, data)
        return

    response_json, _ = ensure_completed_response_event_data(
        data,
        response_id=response_id,
        fallback_model=str(fallback_model or "unknown"),
    )
    await finalize_nonstream_response(
        response_id=response_id,
        response_json=response_json,
        effective_status=str(response_json.get("status") or "completed"),
        append_event=append_event,
        mark_event_final=mark_event_final,
        persist_run_final=persist_run_final,
        advance_session=advance_session,
    )


async def persist_sse_run(
    *,
    chunks: list[bytes],
    append_event: AppendEvent,
    persist_run_final: PersistFinal,
    fallback_model: Any,
    response_id_hint: str = "resp_anyagent",
    mark_event_final: MarkEventFinal | None = None,
    advance_session: AdvanceSession | None = None,
) -> tuple[str, dict[str, Any] | None]:
    decoder = SSEBlockDecoder()
    response_id = response_id_hint
    response_json: dict[str, Any] | None = None

    for chunk in chunks:
        text = chunk.decode("utf-8", errors="replace")
        for line in text.splitlines():
            for blk in decoder.feed_line(line):
                if blk.event is None and blk.data.strip() == "[DONE]":
                    continue
                response_id = _response_id_from_data(blk.data, fallback=response_id)
                if blk.event == "response.completed":
                    normalized = normalize_completed_response_event_data(blk.data)
                    if normalized is not None:
                        maybe, data2 = normalized
                        if isinstance(maybe.get("id"), str) and maybe["id"].strip():
                            response_id = maybe["id"].strip()
                            response_json = maybe
                        blk = type(blk)(id=blk.id, event=blk.event, data=data2)
                _ = await append_event(blk.event, blk.data)

    for blk in decoder.flush():
        if blk.event is not None or blk.data.strip() != "[DONE]":
            _ = await append_event(blk.event, blk.data)

    if response_json is None:
        response_json = build_minimal_openai_response_json(
            response_id=response_id,
            status="completed",
            model=str(fallback_model or "unknown"),
        )

    await finalize_nonstream_response(
        response_id=response_id,
        response_json=response_json,
        effective_status=str(response_json.get("status") or "completed"),
        append_event=append_event,
        mark_event_final=mark_event_final,
        persist_run_final=persist_run_final,
        advance_session=advance_session,
        append_completed_event=False,
    )
    return response_id, response_json


def normalize_forward_stream_block(
    *,
    event: str | None,
    data: str,
    canonical_response_id: str,
) -> tuple[str | None, str, dict[str, Any] | None]:
    if event == "response.completed":
        normalized = normalize_completed_response_event_data(
            data,
            canonical_response_id=canonical_response_id,
        )
        if normalized is None:
            return event, data, None
        completed, normalized_data = normalized
        return event, normalized_data, completed
    return event, data, None


def encode_forward_stream_block(*, event: str | None, data: str) -> bytes:
    return encode_sse_event(event, data)


def _response_id_from_data(data: str, *, fallback: str) -> str:
    if not isinstance(data, str) or not data.strip().startswith("{"):
        return fallback
    try:
        payload = json.loads(data)
    except Exception:
        return fallback
    if not isinstance(payload, dict):
        return fallback
    response_id = payload.get("response_id")
    if isinstance(response_id, str) and response_id.strip():
        return response_id.strip()
    resp = payload.get("response")
    if isinstance(resp, dict):
        rid = resp.get("id")
        if isinstance(rid, str) and rid.strip():
            return rid.strip()
    rid = payload.get("id")
    if isinstance(rid, str) and payload.get("object") == "response" and rid.strip():
        return rid.strip()
    return fallback
