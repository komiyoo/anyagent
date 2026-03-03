from __future__ import annotations

import asyncio
import json
from typing import Any

from fastapi import APIRouter, Request
from fastapi.responses import Response, StreamingResponse
from pydantic import BaseModel, ConfigDict, Field

from ..auth import check_api_key
from ..errors import openai_error
from ..settings import Settings
from ..sse import encode_sse_event


class InternalEventItem(BaseModel):
    model_config = ConfigDict(extra="forbid")

    seq: int = Field(ge=1)
    event: str | None = None
    data: str


class InternalEventsListResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    response_id: str
    requested_last_seq: int = Field(ge=0)
    next_last_seq: int = Field(ge=0)
    events: list[InternalEventItem] = Field(default_factory=list)
    done: bool
    run_status: str | None = None


def _json_dumps(obj: Any) -> str:
    return json.dumps(obj, ensure_ascii=False, separators=(",", ":"))


def create_internal_events_router(settings: Settings) -> APIRouter:
    router = APIRouter()

    @router.get("/internal/events/list", response_model=InternalEventsListResponse)
    async def internal_events_list(
        request: Request,
        response_id: str,
        last_seq: int = 0,
        limit: int = 200,
    ) -> Response | InternalEventsListResponse:
        auth_err = await check_api_key(request, settings)
        if auth_err is not None:
            return auth_err

        if not isinstance(response_id, str) or not response_id.strip():
            return openai_error(400, message="response_id is required", type_="invalid_request_error")
        if not isinstance(last_seq, int) or last_seq < 0:
            return openai_error(400, message="last_seq must be >= 0", type_="invalid_request_error")
        lim = max(1, min(1000, int(limit)))

        storage = request.app.state.storage
        run = await storage.run_store.get(response_id)
        if run is None:
            return openai_error(404, message=f"unknown response_id: {response_id}", type_="invalid_request_error", code="run_not_found")

        if hasattr(storage.event_store, "tail_seq"):
            tail_seq = int(await storage.event_store.tail_seq(response_id=response_id))
        else:
            tail_seq = int(getattr(run, "last_event_seq", 0) or 0)
        if int(last_seq) > tail_seq:
            return openai_error(
                410,
                message=f"last_seq out of range (last_seq={last_seq}, max={tail_seq})",
                type_="invalid_request_error",
                code="cursor_out_of_range",
            )

        events = await storage.event_store.list(response_id=response_id, after_seq=last_seq, limit=lim)
        items: list[InternalEventItem] = []
        done = False
        next_last_seq = int(last_seq)
        for ev in events:
            items.append(InternalEventItem(seq=int(ev.seq), event=ev.event, data=str(ev.data)))
            next_last_seq = max(next_last_seq, int(ev.seq))
            if ev.event is None and str(ev.data).strip() == "[DONE]":
                done = True

        if run.status in {"completed", "errored"} and next_last_seq >= tail_seq:
            done = True

        return InternalEventsListResponse(
            response_id=response_id,
            requested_last_seq=int(last_seq),
            next_last_seq=next_last_seq,
            events=items,
            done=done,
            run_status=getattr(run, "status", None),
        )

    @router.get("/internal/events/stream")
    async def internal_events_stream(
        request: Request,
        response_id: str,
        last_seq: int = 0,
    ) -> Response:
        auth_err = await check_api_key(request, settings)
        if auth_err is not None:
            return auth_err

        if not isinstance(response_id, str) or not response_id.strip():
            return openai_error(400, message="response_id is required", type_="invalid_request_error")
        if not isinstance(last_seq, int) or last_seq < 0:
            return openai_error(400, message="last_seq must be >= 0", type_="invalid_request_error")

        storage = request.app.state.storage
        run0 = await storage.run_store.get(response_id)
        if run0 is None:
            return openai_error(404, message=f"unknown response_id: {response_id}", type_="invalid_request_error", code="run_not_found")

        if hasattr(storage.event_store, "tail_seq"):
            tail_seq = int(await storage.event_store.tail_seq(response_id=response_id))
        else:
            tail_seq = int(getattr(run0, "last_event_seq", 0) or 0)

        if int(last_seq) > tail_seq:
            if run0.status in {"completed", "errored"}:
                # Cursor points to pruned events; still allow caller to fetch terminal completion once.
                async def _iter_terminal() -> Any:
                    if isinstance(run0.final_response_json, dict):
                        yield encode_sse_event("response.completed", _json_dumps(run0.final_response_json))
                    yield encode_sse_event(None, "[DONE]")

                return StreamingResponse(_iter_terminal(), media_type="text/event-stream")
            return openai_error(
                410,
                message=f"last_seq out of range (last_seq={last_seq}, max={tail_seq})",
                type_="invalid_request_error",
                code="cursor_out_of_range",
            )

        async def _iter() -> Any:
            after_seq = int(last_seq)
            while True:
                events = await storage.event_store.list(response_id=response_id, after_seq=after_seq, limit=200)
                if events:
                    for ev in events:
                        after_seq = int(ev.seq)
                        yield encode_sse_event(ev.event, str(ev.data))
                        if ev.event is None and str(ev.data).strip() == "[DONE]":
                            return
                    continue

                run = await storage.run_store.get(response_id)
                if run is not None and run.status in {"completed", "errored"}:
                    if isinstance(run.final_response_json, dict):
                        yield encode_sse_event("response.completed", _json_dumps(run.final_response_json))
                    yield encode_sse_event(None, "[DONE]")
                    return

                if hasattr(storage.event_store, "wait_new"):
                    await storage.event_store.wait_new(response_id=response_id, after_seq=after_seq, timeout_s=1.0)
                else:
                    await asyncio.sleep(0.25)

        return StreamingResponse(_iter(), media_type="text/event-stream")

    return router
