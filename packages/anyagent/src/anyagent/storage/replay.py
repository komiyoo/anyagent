from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator
from dataclasses import dataclass
from typing import Any, Callable

from anyagent.protocol.agent_api_internal import InternalEventItem, InternalEventsListResponse
from anyagent.protocol.sse import encode_sse_block, encode_sse_event

from .contracts import EventStore, RunStore


@dataclass(slots=True, frozen=True)
class InternalEventsCursorOutOfRange(Exception):
    requested_last_seq: int
    max_last_seq: int

    def __str__(self) -> str:
        return f"last_seq out of range (last_seq={self.requested_last_seq}, max={self.max_last_seq})"


class InternalEventsRunNotFound(Exception):
    def __init__(self, response_id: str) -> None:
        self.response_id = response_id
        super().__init__(f"unknown response_id: {response_id}")


def _json_dumps(obj: Any) -> str:
    return json.dumps(obj, ensure_ascii=False, separators=(",", ":"))


@dataclass(slots=True, frozen=True)
class ReplayEvent:
    seq: int
    event: str | None
    data: str


def effective_run_status(run: Any) -> str | None:
    status = getattr(run, "status", None)
    if status != "errored":
        return status if isinstance(status, str) else None

    error_json = getattr(run, "error_json", None)
    if isinstance(error_json, dict) and str(error_json.get("code") or "").strip() == "response_cancelled":
        return "cancelled"
    return "errored"


async def _tail_seq(*, event_store: EventStore, run: Any, response_id: str) -> int:
    if hasattr(event_store, "tail_seq"):
        return int(await event_store.tail_seq(response_id=response_id))  # type: ignore[attr-defined]
    return int(getattr(run, "last_event_seq", 0) or 0)


async def require_run(*, run_store: RunStore, response_id: str) -> Any:
    run = await run_store.get(response_id)
    if run is None:
        raise InternalEventsRunNotFound(response_id)
    return run


async def internal_events_tail_seq(*, event_store: EventStore, run: Any, response_id: str) -> int:
    return await _tail_seq(event_store=event_store, run=run, response_id=response_id)


async def list_internal_events(
    *,
    run_store: RunStore,
    event_store: EventStore,
    response_id: str,
    last_seq: int = 0,
    limit: int = 200,
) -> InternalEventsListResponse:
    run = await require_run(run_store=run_store, response_id=response_id)
    tail_seq = await _tail_seq(event_store=event_store, run=run, response_id=response_id)
    requested_last_seq = max(int(last_seq), 0)
    if requested_last_seq > tail_seq:
        raise InternalEventsCursorOutOfRange(requested_last_seq=requested_last_seq, max_last_seq=tail_seq)

    events = await event_store.list(response_id=response_id, after_seq=requested_last_seq, limit=max(1, min(1000, int(limit))))
    items: list[InternalEventItem] = []
    done = False
    next_last_seq = requested_last_seq
    for ev in events:
        items.append(InternalEventItem(seq=int(ev.seq), event=ev.event, data=str(ev.data)))
        next_last_seq = max(next_last_seq, int(ev.seq))
        if ev.event is None and str(ev.data).strip() == "[DONE]":
            done = True

    if getattr(run, "status", None) in {"completed", "errored"} and next_last_seq >= tail_seq:
        done = True

    return InternalEventsListResponse(
        response_id=response_id,
        requested_last_seq=requested_last_seq,
        next_last_seq=next_last_seq,
        events=items,
        done=done,
        run_status=getattr(run, "status", None),
        effective_run_status=effective_run_status(run),
    )


async def stream_internal_event_blocks(
    *,
    run_store: RunStore,
    event_store: EventStore,
    response_id: str,
    last_seq: int = 0,
    poll_timeout_s: float = 1.0,
) -> AsyncIterator[bytes]:
    run0 = await require_run(run_store=run_store, response_id=response_id)
    requested_last_seq = max(int(last_seq), 0)
    tail_seq = await _tail_seq(event_store=event_store, run=run0, response_id=response_id)

    if requested_last_seq > tail_seq:
        if getattr(run0, "status", None) in {"completed", "errored"}:
            if isinstance(getattr(run0, "final_response_json", None), dict):
                yield encode_sse_event("response.completed", _json_dumps(run0.final_response_json))
            yield encode_sse_event(None, "[DONE]")
            return
        raise InternalEventsCursorOutOfRange(requested_last_seq=requested_last_seq, max_last_seq=tail_seq)

    after_seq = requested_last_seq
    while True:
        events = await event_store.list(response_id=response_id, after_seq=after_seq, limit=200)
        if events:
            for ev in events:
                after_seq = int(ev.seq)
                yield encode_sse_block(event=ev.event, data=str(ev.data), id=str(ev.seq))
                if ev.event is None and str(ev.data).strip() == "[DONE]":
                    return
            continue

        run = await run_store.get(response_id)
        if run is not None and getattr(run, "status", None) in {"completed", "errored"}:
            if isinstance(getattr(run, "final_response_json", None), dict):
                yield encode_sse_event("response.completed", _json_dumps(run.final_response_json))
            yield encode_sse_event(None, "[DONE]")
            return

        if hasattr(event_store, "wait_new"):
            await event_store.wait_new(response_id=response_id, after_seq=after_seq, timeout_s=poll_timeout_s)  # type: ignore[attr-defined]
        else:
            await asyncio.sleep(max(float(poll_timeout_s), 0.05))


async def wait_for_final_response_json(
    *,
    run_store: RunStore,
    response_id: str,
    timeout_s: float,
    poll_interval_s: float = 0.25,
) -> dict[str, Any] | None:
    deadline = asyncio.get_event_loop().time() + max(float(timeout_s), 0.0)
    while asyncio.get_event_loop().time() < deadline:
        run = await run_store.get(response_id)
        if run is not None and getattr(run, "status", None) in {"completed", "errored"} and isinstance(getattr(run, "final_response_json", None), dict):
            return run.final_response_json
        await asyncio.sleep(max(float(poll_interval_s), 0.01))
    return None


async def resolve_nonstream_replay_payload(
    *,
    run_store: RunStore,
    run: Any,
    response_id: str,
    wait_timeout_s: float = 0.0,
    fallback_payload_factory: Callable[[Any], dict[str, Any] | None] | None = None,
) -> dict[str, Any] | None:
    if isinstance(getattr(run, "final_response_json", None), dict):
        return run.final_response_json

    if float(wait_timeout_s) > 0:
        final = await wait_for_final_response_json(
            run_store=run_store,
            response_id=response_id,
            timeout_s=wait_timeout_s,
        )
        if final is not None:
            return final

    if callable(fallback_payload_factory):
        return fallback_payload_factory(run)
    return None


async def stream_external_response_blocks(
    *,
    run_store: RunStore,
    event_store: Any,
    response_id: str,
    last_seq: int = 0,
    poll_timeout_s: float = 1.0,
    skip_internal_prefixes: tuple[str, ...] = ("anyagent.",),
    fallback_completed_serializer: Callable[[dict[str, Any]], str] | None = None,
    event_filter: Callable[[str | None], bool] | None = None,
) -> AsyncIterator[bytes]:
    after_seq = max(int(last_seq), 0)
    while True:
        events = await _list_replay_events(
            event_store=event_store,
            response_id=response_id,
            after_seq=after_seq,
            limit=200,
        )
        if events:
            for ev in events:
                after_seq = int(ev.seq)
                if isinstance(ev.event, str) and any(ev.event.startswith(prefix) for prefix in skip_internal_prefixes):
                    continue
                if callable(event_filter) and not event_filter(ev.event):
                    continue
                yield encode_sse_block(event=ev.event, data=ev.data, id=str(ev.seq))
                if ev.event is None and ev.data.strip() == "[DONE]":
                    return
            continue

        run = await run_store.get(response_id)
        if run is not None and getattr(run, "status", None) in {"completed", "errored"}:
            if isinstance(getattr(run, "final_response_json", None), dict):
                serializer = fallback_completed_serializer or _json_dumps
                yield encode_sse_event("response.completed", serializer(run.final_response_json))
            yield encode_sse_event(None, "[DONE]")
            return

        await _wait_replay_events(
            event_store=event_store,
            response_id=response_id,
            after_seq=after_seq,
            timeout_s=poll_timeout_s,
        )


async def _list_replay_events(
    *,
    event_store: Any,
    response_id: str,
    after_seq: int,
    limit: int,
) -> list[ReplayEvent]:
    if hasattr(event_store, "list"):
        items = await event_store.list(response_id=response_id, after_seq=after_seq, limit=limit)
        return [ReplayEvent(seq=int(item.seq), event=item.event, data=str(item.data)) for item in items]

    if hasattr(event_store, "list_events"):
        resp = await event_store.list_events(response_id=response_id, last_seq=after_seq, limit=limit)
        return [ReplayEvent(seq=int(item.seq), event=item.event, data=str(item.data)) for item in resp.events]

    raise TypeError("event_store must support list() or list_events()")


async def _wait_replay_events(
    *,
    event_store: Any,
    response_id: str,
    after_seq: int,
    timeout_s: float,
) -> None:
    if hasattr(event_store, "wait_new"):
        await event_store.wait_new(response_id=response_id, after_seq=after_seq, timeout_s=timeout_s)
        return
    await asyncio.sleep(max(float(timeout_s), 0.05))
