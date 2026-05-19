from __future__ import annotations

from fastapi import APIRouter, Request
from fastapi.responses import Response, StreamingResponse

from anyagent.protocol.agent_api_internal import InternalEventsListResponse
from anyagent.storage import (
    InternalEventsCursorOutOfRange,
    InternalEventsRunNotFound,
    internal_events_tail_seq,
    list_internal_events,
    require_run,
    stream_internal_event_blocks,
)

from .responses_optional import check_bearer_api_key, openai_error_response


def create_internal_events_router(
    *,
    api_key: str,
    storage_state_attr: str = "storage",
) -> APIRouter:
    router = APIRouter()

    @router.get("/internal/events/list", response_model=InternalEventsListResponse)
    async def internal_events_list(
        request: Request,
        response_id: str,
        last_seq: int = 0,
        limit: int = 200,
    ) -> Response | InternalEventsListResponse:
        auth_err = await check_bearer_api_key(request, api_key=api_key)
        if auth_err is not None:
            return auth_err

        if not isinstance(response_id, str) or not response_id.strip():
            return openai_error_response(400, message="response_id is required", type_="invalid_request_error")
        if not isinstance(last_seq, int) or last_seq < 0:
            return openai_error_response(400, message="last_seq must be >= 0", type_="invalid_request_error")

        storage = getattr(request.app.state, storage_state_attr)
        try:
            return await list_internal_events(
                run_store=storage.run_store,
                event_store=storage.event_store,
                response_id=response_id,
                last_seq=last_seq,
                limit=limit,
            )
        except InternalEventsRunNotFound as exc:
            return openai_error_response(404, message=str(exc), type_="invalid_request_error", code="run_not_found")
        except InternalEventsCursorOutOfRange as exc:
            return openai_error_response(410, message=str(exc), type_="invalid_request_error", code="cursor_out_of_range")

    @router.get("/internal/events/stream")
    async def internal_events_stream(
        request: Request,
        response_id: str,
        last_seq: int = 0,
    ) -> Response:
        auth_err = await check_bearer_api_key(request, api_key=api_key)
        if auth_err is not None:
            return auth_err

        if not isinstance(response_id, str) or not response_id.strip():
            return openai_error_response(400, message="response_id is required", type_="invalid_request_error")
        if not isinstance(last_seq, int) or last_seq < 0:
            return openai_error_response(400, message="last_seq must be >= 0", type_="invalid_request_error")

        storage = getattr(request.app.state, storage_state_attr)
        try:
            run = await require_run(run_store=storage.run_store, response_id=response_id)
            tail_seq = await internal_events_tail_seq(
                event_store=storage.event_store,
                run=run,
                response_id=response_id,
            )
            if int(last_seq) > tail_seq and getattr(run, "status", None) not in {"completed", "errored"}:
                raise InternalEventsCursorOutOfRange(requested_last_seq=int(last_seq), max_last_seq=tail_seq)
            iterator = stream_internal_event_blocks(
                run_store=storage.run_store,
                event_store=storage.event_store,
                response_id=response_id,
                last_seq=last_seq,
            )
            return StreamingResponse(iterator, media_type="text/event-stream")
        except InternalEventsRunNotFound as exc:
            return openai_error_response(404, message=str(exc), type_="invalid_request_error", code="run_not_found")
        except InternalEventsCursorOutOfRange as exc:
            return openai_error_response(410, message=str(exc), type_="invalid_request_error", code="cursor_out_of_range")

    return router
