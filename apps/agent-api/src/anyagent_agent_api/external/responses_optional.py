from __future__ import annotations

"""Optional `/v1/responses/{id}` query and cancel endpoints."""

import json
from typing import Any

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse, Response

from anyagent.protocol.responses_optional import (
    AnyAgentResponseError,
    AnyAgentResponseStatusPayload,
)

from ..auth import check_api_key
from ..errors import openai_error
from ..settings import Settings
from ..storage.models import RunRecord


def _build_status_payload_from_run(run: RunRecord) -> AnyAgentResponseStatusPayload:
    """Build a minimal response payload from run state when final JSON is unavailable."""

    if run.status == "started":
        return AnyAgentResponseStatusPayload(id=run.response_id, status="in_progress")

    if run.status == "completed":
        return AnyAgentResponseStatusPayload(id=run.response_id, status="completed")

    error_obj = run.error_json if isinstance(run.error_json, dict) else {}
    code = str(error_obj.get("code") or "").strip() or None
    if code == "response_cancelled":
        return AnyAgentResponseStatusPayload(
            id=run.response_id,
            status="cancelled",
            error=AnyAgentResponseError(
                type=str(error_obj.get("type") or "cancelled"),
                message=str(error_obj.get("message") or "response cancelled"),
                code=code,
            ),
        )

    return AnyAgentResponseStatusPayload(
        id=run.response_id,
        status="failed",
        error=AnyAgentResponseError(
            type=str(error_obj.get("type") or "response_error"),
            message=str(error_obj.get("message") or "response failed"),
            code=code,
        ),
    )


def _effective_response_json(run: RunRecord) -> dict[str, Any]:
    """Return final response JSON when present; otherwise synthesize minimal payload."""

    final = run.final_response_json
    if isinstance(final, dict):
        return final
    return _build_status_payload_from_run(run).model_dump(exclude_none=True)


async def _append_cancel_terminal_events_best_effort(
    *,
    request: Request,
    run: RunRecord,
    payload_json: dict[str, Any],
) -> None:
    """Append terminal `response.completed` + `[DONE]` events for best-effort cancel semantics."""

    storage = request.app.state.storage
    seq_completed = await storage.event_store.append(
        response_id=run.response_id,
        session_partition_key=run.session_partition_key,
        event="response.completed",
        data=json.dumps(payload_json, ensure_ascii=False, separators=(",", ":")),
    )
    seq_done = await storage.event_store.append(
        response_id=run.response_id,
        session_partition_key=run.session_partition_key,
        event=None,
        data="[DONE]",
    )
    if hasattr(storage.run_store, "set_last_event_seq"):
        await storage.run_store.set_last_event_seq(response_id=run.response_id, last_event_seq=max(int(seq_completed), int(seq_done)))


def create_optional_responses_router(settings: Settings) -> APIRouter:
    """Create router for optional OpenAI-like response query/cancel endpoints."""

    router = APIRouter()

    @router.get("/v1/responses/{response_id}")
    async def get_response_by_id(request: Request, response_id: str) -> Response:
        """Return final response payload (or minimal in-progress status) by response id."""

        auth_err = await check_api_key(request, settings)
        if auth_err is not None:
            return auth_err
        if not isinstance(response_id, str) or not response_id.strip():
            return openai_error(400, message="response_id is required", type_="invalid_request_error")

        storage = request.app.state.storage
        run = await storage.run_store.get(response_id.strip())
        if run is None:
            return openai_error(404, message=f"unknown response_id: {response_id}", type_="invalid_request_error", code="run_not_found")
        return JSONResponse(status_code=200, content=_effective_response_json(run))

    @router.post("/v1/responses/{response_id}/cancel")
    async def cancel_response_by_id(request: Request, response_id: str) -> Response:
        """Cancel a running response in best-effort mode and return terminal payload."""

        auth_err = await check_api_key(request, settings)
        if auth_err is not None:
            return auth_err
        if not isinstance(response_id, str) or not response_id.strip():
            return openai_error(400, message="response_id is required", type_="invalid_request_error")

        rid = response_id.strip()
        storage = request.app.state.storage
        run = await storage.run_store.get(rid)
        if run is None:
            return openai_error(404, message=f"unknown response_id: {response_id}", type_="invalid_request_error", code="run_not_found")

        if run.status != "started":
            return JSONResponse(status_code=200, content=_effective_response_json(run))

        payload = AnyAgentResponseStatusPayload(
            id=run.response_id,
            status="cancelled",
            error=AnyAgentResponseError(
                type="cancelled",
                message="response cancelled by client request",
                code="response_cancelled",
            ),
        )
        payload_json = payload.model_dump(exclude_none=True)
        error_json = payload.error.model_dump(exclude_none=True) if payload.error is not None else None

        await storage.run_store.set_final(
            response_id=run.response_id,
            status="errored",
            final_response_json=payload_json,
            error_json=error_json,
        )
        try:
            await _append_cancel_terminal_events_best_effort(request=request, run=run, payload_json=payload_json)
        except Exception:  # noqa: BLE001
            # Best-effort: cancellation terminal state should not fail because event append failed.
            pass
        return JSONResponse(status_code=200, content=payload_json)

    return router
