from __future__ import annotations

import json
from typing import Any

from fastapi import Request
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


def _created_at_seconds(run: Any) -> float | None:
    value_s = getattr(run, "created_at_s", None)
    if isinstance(value_s, (int, float)):
        return float(value_s)
    value_ms = getattr(run, "created_at_ms", None)
    if isinstance(value_ms, (int, float)):
        return float(value_ms) / 1000.0
    return None
