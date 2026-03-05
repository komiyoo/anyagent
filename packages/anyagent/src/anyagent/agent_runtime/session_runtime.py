from __future__ import annotations

import json
from time import time
from typing import Any


MANAGED_RUNTIME_FIELDS: tuple[str, ...] = (
    "model",
    "temperature",
    "top_p",
    "frequency_penalty",
    "presence_penalty",
    "reasoning",
)


def dedupe_strs(values: list[str]) -> list[str]:
    """Return stable-order deduplicated non-empty strings."""

    out: list[str] = []
    seen: set[str] = set()
    for v in values:
        if not isinstance(v, str):
            continue
        s = v.strip()
        if not s or s in seen:
            continue
        seen.add(s)
        out.append(s)
    return out


def _json_clone(value: Any) -> Any:
    """Return a JSON-safe deep clone for request/session payload values."""

    try:
        return json.loads(json.dumps(value, ensure_ascii=False))
    except Exception:  # noqa: BLE001
        return {}


def extract_runtime_updates_from_request(body: dict[str, Any]) -> dict[str, Any]:
    """Extract explicitly provided managed runtime fields from one request body."""

    out: dict[str, Any] = {}
    for key in MANAGED_RUNTIME_FIELDS:
        if key in body:
            out[key] = _json_clone(body.get(key))
    return out


def merge_runtime_config(*, base_runtime_config: dict[str, Any], explicit_updates: dict[str, Any]) -> dict[str, Any]:
    """Merge explicit request updates into session-bound runtime config."""

    merged = _json_clone(base_runtime_config if isinstance(base_runtime_config, dict) else {})
    if not isinstance(merged, dict):
        merged = {}
    for key, value in explicit_updates.items():
        merged[key] = _json_clone(value)
    return merged


def apply_runtime_config_to_body(*, body: dict[str, Any], runtime_config: dict[str, Any]) -> dict[str, Any]:
    """Apply effective runtime config to one OpenAI Responses request body."""

    out = dict(body)
    for key in MANAGED_RUNTIME_FIELDS:
        if isinstance(runtime_config, dict) and key in runtime_config:
            out[key] = _json_clone(runtime_config[key])
        else:
            out.pop(key, None)
    return out


def build_initial_session_snapshot(*, runtime_config: dict[str, Any]) -> dict[str, Any]:
    """Build the minimal initial session snapshot for session resume."""

    return {
        "provider": "openai_responses",
        "runtime_config": _json_clone(runtime_config),
        "resume_cursor": {"last_response_id": None, "fallback_transcript_items": []},
    }


def apply_session_resume_to_body(*, body: dict[str, Any], session_snapshot: dict[str, Any]) -> tuple[dict[str, Any], str | None]:
    """Fill `previous_response_id` from session snapshot when caller does not provide it."""

    out = dict(body)
    prev = out.get("previous_response_id")
    if isinstance(prev, str) and prev.strip():
        return out, prev.strip()

    resume_cursor = session_snapshot.get("resume_cursor")
    if not isinstance(resume_cursor, dict):
        return out, None
    last_response_id = resume_cursor.get("last_response_id")
    if isinstance(last_response_id, str) and last_response_id.strip():
        out["previous_response_id"] = last_response_id.strip()
        return out, last_response_id.strip()
    return out, None


def build_next_session_snapshot(
    *,
    previous_snapshot: dict[str, Any],
    runtime_config: dict[str, Any],
    resume_last_response_id: str | None,
    run_response_id: str | None,
    last_event_seq: int | None,
    updated_at_ms: int | None = None,
) -> dict[str, Any]:
    """Build next session snapshot JSON for CAS update at run-final time."""

    out = _json_clone(previous_snapshot if isinstance(previous_snapshot, dict) else {})
    if not isinstance(out, dict):
        out = {}

    out["provider"] = "openai_responses"
    out["runtime_config"] = _json_clone(runtime_config if isinstance(runtime_config, dict) else {})
    resume = out.get("resume_cursor")
    if not isinstance(resume, dict):
        resume = {}
    if isinstance(resume_last_response_id, str) and resume_last_response_id.strip():
        resume["last_response_id"] = resume_last_response_id.strip()
    out["resume_cursor"] = resume

    now_ms = int(updated_at_ms) if isinstance(updated_at_ms, int) else int(time() * 1000)
    out["last_run"] = {
        "response_id": run_response_id,
        "last_event_seq": int(last_event_seq) if isinstance(last_event_seq, int) else 0,
        "updated_at_ms": now_ms,
    }
    return out
