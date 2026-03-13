from __future__ import annotations

from typing import Any

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


def _created_at_seconds(run: Any) -> float | None:
    value_s = getattr(run, "created_at_s", None)
    if isinstance(value_s, (int, float)):
        return float(value_s)
    value_ms = getattr(run, "created_at_ms", None)
    if isinstance(value_ms, (int, float)):
        return float(value_ms) / 1000.0
    return None
