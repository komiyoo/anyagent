from __future__ import annotations

import json
from typing import Any

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse, Response

from anyagent.protocol.openai_responses import (
    OpenAIResponseStatus,
    build_minimal_openai_response_json,
    decode_openai_response,
)


def optional_response_status_from_run(run: Any) -> OpenAIResponseStatus:
    effective_status = getattr(run, "effective_status", None)
    if effective_status == "in_progress":
        return "in_progress"
    if effective_status == "completed":
        return "completed"
    if effective_status == "cancelled":
        return "cancelled"
    if effective_status in {"errored", "failed", "timeout"}:
        return "failed"

    status = getattr(run, "status", None)
    if status == "started":
        return "in_progress"
    if status == "completed":
        return "completed"

    error_json = getattr(run, "error_json", None)
    if isinstance(error_json, dict) and str(error_json.get("code") or "").strip() == "response_cancelled":
        return "cancelled"
    return "failed"


def optional_response_payload_from_run(
    run: Any,
    *,
    response_id: str | None = None,
    default_model: str = "unknown",
) -> dict[str, Any]:
    final = getattr(run, "final_response_json", None)
    if isinstance(final, dict) and decode_openai_response(final) is not None:
        return final

    model = final.get("model") if isinstance(final, dict) else None
    created_at_s = _created_at_seconds(run)
    rid = response_id or getattr(run, "response_id", None) or "unknown"
    return build_minimal_openai_response_json(
        response_id=str(rid),
        status=optional_response_status_from_run(run),
        created_at_s=created_at_s,
        model=str(model) if isinstance(model, str) and model.strip() else default_model,
    )


def cancelled_response_error_json() -> dict[str, str]:
    return {
        "type": "cancelled",
        "message": "response cancelled by client request",
        "code": "response_cancelled",
    }


def openai_error_response(
    status_code: int,
    *,
    message: str,
    type_: str,
    code: str | None = None,
    retryable: bool | None = None,
) -> JSONResponse:
    err: dict[str, object] = {"message": message, "type": type_}
    if isinstance(code, str) and code.strip():
        err["code"] = code.strip()
    if retryable is not None:
        err["retryable"] = bool(retryable)
    return JSONResponse(status_code=status_code, content={"error": err})


async def check_bearer_api_key(request: Request, *, api_key: str) -> Response | None:
    auth = request.headers.get("authorization")
    if not auth:
        return openai_error_response(401, message="Missing Authorization header", type_="authentication_error")

    parts = auth.split(None, 1)
    if len(parts) != 2 or parts[0].lower() != "bearer":
        return openai_error_response(401, message="Invalid Authorization header", type_="authentication_error")

    token = parts[1].strip()
    if token != api_key:
        return openai_error_response(401, message="Invalid API key", type_="authentication_error")

    return None


async def append_cancel_terminal_events_best_effort(
    *,
    storage: Any,
    run: Any,
    payload_json: dict[str, Any],
) -> None:
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


def _created_at_seconds(run: Any) -> float | None:
    value_s = getattr(run, "created_at_s", None)
    if isinstance(value_s, (int, float)):
        return float(value_s)
    value_ms = getattr(run, "created_at_ms", None)
    if isinstance(value_ms, (int, float)):
        return float(value_ms) / 1000.0
    return None
