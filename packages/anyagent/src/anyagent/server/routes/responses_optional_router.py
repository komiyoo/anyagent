from __future__ import annotations

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse, Response

from anyagent.protocol.openai_responses import build_minimal_openai_response_json
from anyagent.server.handlers.http_errors import (
    append_cancel_terminal_events_best_effort,
    cancelled_response_error_json,
    check_bearer_api_key,
    openai_error_response,
    optional_response_payload_from_run,
)


def create_optional_responses_router(
    *,
    api_key: str,
    storage_state_attr: str = "storage",
) -> APIRouter:
    router = APIRouter()

    @router.get("/v1/responses/{response_id}")
    async def get_response_by_id(request: Request, response_id: str) -> Response:
        auth_err = await check_bearer_api_key(request, api_key=api_key)
        if auth_err is not None:
            return auth_err
        if not isinstance(response_id, str) or not response_id.strip():
            return openai_error_response(400, message="response_id is required", type_="invalid_request_error")

        storage = getattr(request.app.state, storage_state_attr)
        run = await storage.run_store.get(response_id.strip())
        if run is None:
            return openai_error_response(404, message=f"unknown response_id: {response_id}", type_="invalid_request_error", code="run_not_found")
        return JSONResponse(status_code=200, content=optional_response_payload_from_run(run))

    @router.post("/v1/responses/{response_id}/cancel")
    async def cancel_response_by_id(request: Request, response_id: str) -> Response:
        auth_err = await check_bearer_api_key(request, api_key=api_key)
        if auth_err is not None:
            return auth_err
        if not isinstance(response_id, str) or not response_id.strip():
            return openai_error_response(400, message="response_id is required", type_="invalid_request_error")

        rid = response_id.strip()
        storage = getattr(request.app.state, storage_state_attr)
        run = await storage.run_store.get(rid)
        if run is None:
            return openai_error_response(404, message=f"unknown response_id: {response_id}", type_="invalid_request_error", code="run_not_found")

        payload_json = build_minimal_openai_response_json(
            response_id=run.response_id,
            status="cancelled",
            created_at_s=getattr(run, "created_at_s", None),
        )
        error_json = cancelled_response_error_json()

        transitioned, latest = await storage.run_store.try_set_final_from_status(
            response_id=run.response_id,
            current_status="started",
            next_status="errored",
            final_response_json=payload_json,
            error_json=error_json,
        )
        if not transitioned:
            return JSONResponse(status_code=200, content=optional_response_payload_from_run(latest or run))

        run = latest or run
        try:
            await append_cancel_terminal_events_best_effort(storage=storage, run=run, payload_json=payload_json)
        except Exception:  # noqa: BLE001
            # Best-effort: cancellation terminal state should not fail because event append failed.
            pass
        return JSONResponse(status_code=200, content=payload_json)

    return router
