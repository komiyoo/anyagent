from __future__ import annotations

from dataclasses import dataclass
import json
from time import time
from typing import Any

from anyagent.protocol.prompt_context import PromptContextAudit, build_prompt_context_audit
from anyagent.protocol.session_snapshot import (
    PersistedSessionSnapshot,
    SessionLastRun,
    SessionResumeCursor,
    coerce_persisted_session_snapshot,
)


MANAGED_RUNTIME_FIELDS: tuple[str, ...] = (
    "model",
    "temperature",
    "top_p",
    "frequency_penalty",
    "presence_penalty",
    "reasoning",
)


@dataclass(slots=True, frozen=True)
class PreparedSessionRequest:
    previous_snapshot: dict[str, Any]
    previous_snapshot_version: int | None
    effective_runtime_config: dict[str, Any]
    request_transcript_items: list[dict[str, Any]]
    effective_body: dict[str, Any]


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


def input_to_transcript_items(input_value: Any) -> list[dict[str, Any]]:
    """Normalize one Responses `input` payload into fallback transcript items."""

    if isinstance(input_value, str):
        s = input_value.strip()
        if not s:
            return []
        return [{"role": "user", "content": s}]

    if not isinstance(input_value, list):
        return []

    out: list[dict[str, Any]] = []
    for item in input_value:
        normalized = _normalize_transcript_item(item)
        if normalized is not None:
            out.append(normalized)
    return out


def build_initial_session_snapshot(*, runtime_config: dict[str, Any]) -> dict[str, Any]:
    """Build the minimal initial session snapshot for session resume."""

    snapshot = PersistedSessionSnapshot(
        provider="openai_responses",
        runtime_config=_json_clone(runtime_config if isinstance(runtime_config, dict) else {}),
        resume_cursor=SessionResumeCursor(last_response_id=None, fallback_transcript_items=[]),
    )
    return snapshot.model_dump(mode="json", exclude_none=True)


async def prepare_session_request(
    *,
    session_store: Any,
    session_partition_key: str,
    agent_id: str,
    session_key: str,
    body: dict[str, Any],
) -> PreparedSessionRequest:
    session_record = await session_store.get(session_partition_key=session_partition_key)
    if session_record is None:
        init_runtime = extract_runtime_updates_from_request(body)
        init_snapshot = build_initial_session_snapshot(runtime_config=init_runtime)
        session_record = await _create_initial_session_record(
            session_store=session_store,
            session_partition_key=session_partition_key,
            agent_id=agent_id,
            session_key=session_key,
            snapshot_json=init_snapshot,
        )

    previous_snapshot_model = coerce_persisted_session_snapshot(
        session_record.snapshot_json if isinstance(getattr(session_record, "snapshot_json", None), dict) else {}
    )
    previous_snapshot = previous_snapshot_model.model_dump(mode="json", exclude_none=True)
    previous_snapshot_version = int(getattr(session_record, "snapshot_version", 0) or 0)
    explicit_runtime_updates = extract_runtime_updates_from_request(body)
    base_runtime_config = previous_snapshot_model.runtime_config if isinstance(previous_snapshot_model.runtime_config, dict) else {}
    effective_runtime_config = merge_runtime_config(
        base_runtime_config=base_runtime_config if isinstance(base_runtime_config, dict) else {},
        explicit_updates=explicit_runtime_updates,
    )
    effective_body = apply_runtime_config_to_body(body=body, runtime_config=effective_runtime_config)
    request_transcript_items = input_to_transcript_items(effective_body.get("input"))
    effective_body, _ = apply_session_resume_to_body(body=effective_body, session_snapshot=previous_snapshot)
    return PreparedSessionRequest(
        previous_snapshot=previous_snapshot,
        previous_snapshot_version=previous_snapshot_version,
        effective_runtime_config=effective_runtime_config,
        request_transcript_items=request_transcript_items,
        effective_body=effective_body,
    )


def apply_session_resume_to_body(*, body: dict[str, Any], session_snapshot: dict[str, Any]) -> tuple[dict[str, Any], str | None]:
    """Fill `previous_response_id` from session snapshot when caller does not provide it."""

    out = dict(body)
    prev = out.get("previous_response_id")
    if isinstance(prev, str) and prev.strip():
        return out, prev.strip()

    snapshot_model = coerce_persisted_session_snapshot(session_snapshot)
    last_response_id = snapshot_model.resume_cursor.last_response_id
    if isinstance(last_response_id, str) and last_response_id.strip():
        out["previous_response_id"] = last_response_id.strip()
        return out, last_response_id.strip()
    fallback_transcript_items = input_to_transcript_items(snapshot_model.resume_cursor.fallback_transcript_items)
    if fallback_transcript_items:
        request_items = input_to_transcript_items(out.get("input"))
        out["input"] = [*fallback_transcript_items, *request_items]
    return out, None


def build_fallback_transcript_items(
    *,
    previous_snapshot: dict[str, Any],
    request_input: Any,
    response_json: dict[str, Any] | None,
) -> list[dict[str, Any]]:
    """Build next fallback transcript from previous snapshot + current completed turn."""

    previous_items = read_fallback_transcript_items(previous_snapshot)
    request_items = input_to_transcript_items(request_input)
    assistant_items = response_to_transcript_items(response_json)
    return [*previous_items, *request_items, *assistant_items]


def read_resume_last_response_id(snapshot: dict[str, Any]) -> str | None:
    value = coerce_persisted_session_snapshot(snapshot).resume_cursor.last_response_id
    if isinstance(value, str) and value.strip():
        return value.strip()
    return None


async def persist_session_snapshot(
    *,
    session_store: Any,
    session_partition_key: str,
    agent_id: str,
    session_key: str,
    previous_snapshot: dict[str, Any] | None,
    previous_snapshot_version: int | None,
    runtime_config: dict[str, Any],
    request_transcript_items: list[dict[str, Any]] | None,
    response_id: str | None,
    effective_status: str,
    response_json: dict[str, Any] | None,
    last_event_seq: int | None,
    resume_last_response_id: str | None = None,
    prompt_audit: PromptContextAudit | dict[str, Any] | None = None,
) -> tuple[bool, Any | None]:
    next_snapshot = build_persisted_session_snapshot(
        previous_snapshot=previous_snapshot,
        runtime_config=runtime_config,
        request_transcript_items=request_transcript_items,
        response_id=response_id,
        effective_status=effective_status,
        response_json=response_json,
        last_event_seq=last_event_seq,
        resume_last_response_id=resume_last_response_id,
        prompt_audit=prompt_audit,
    )
    return await _update_session_snapshot(
        session_store=session_store,
        session_partition_key=session_partition_key,
        agent_id=agent_id,
        session_key=session_key,
        snapshot_json=next_snapshot,
        expected_snapshot_version=previous_snapshot_version,
    )


def build_persisted_session_snapshot(
    *,
    previous_snapshot: dict[str, Any] | None,
    runtime_config: dict[str, Any],
    request_transcript_items: list[dict[str, Any]] | None,
    response_id: str | None,
    effective_status: str,
    response_json: dict[str, Any] | None,
    last_event_seq: int | None,
    resume_last_response_id: str | None = None,
    prompt_audit: PromptContextAudit | dict[str, Any] | None = None,
) -> dict[str, Any]:
    previous = coerce_persisted_session_snapshot(previous_snapshot if isinstance(previous_snapshot, dict) else None).model_dump(
        mode="json", exclude_none=True
    )
    effective_resume_last_response_id = resume_last_response_id
    if effective_resume_last_response_id is None:
        effective_resume_last_response_id = (
            response_id if effective_status == "completed" and isinstance(response_id, str) and response_id.strip() else read_resume_last_response_id(previous)
        )

    fallback_transcript_items = None
    if effective_status == "completed":
        fallback_transcript_items = build_fallback_transcript_items(
            previous_snapshot=previous,
            request_input=request_transcript_items if isinstance(request_transcript_items, list) else [],
            response_json=response_json,
        )

    return build_next_session_snapshot(
        previous_snapshot=previous,
        runtime_config=runtime_config,
        resume_last_response_id=effective_resume_last_response_id,
        fallback_transcript_items=fallback_transcript_items,
        run_response_id=response_id,
        last_event_seq=last_event_seq,
        prompt_audit=prompt_audit,
    )


def build_next_session_snapshot(
    *,
    previous_snapshot: dict[str, Any],
    runtime_config: dict[str, Any],
    resume_last_response_id: str | None,
    fallback_transcript_items: list[dict[str, Any]] | None = None,
    run_response_id: str | None,
    last_event_seq: int | None,
    updated_at_ms: int | None = None,
    prompt_audit: PromptContextAudit | dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Build next session snapshot JSON for CAS update at run-final time."""

    snapshot_model = coerce_persisted_session_snapshot(previous_snapshot if isinstance(previous_snapshot, dict) else None)
    snapshot_model.provider = "openai_responses"
    snapshot_model.runtime_config = _json_clone(runtime_config if isinstance(runtime_config, dict) else {})
    snapshot_model.resume_cursor.last_response_id = (
        resume_last_response_id.strip() if isinstance(resume_last_response_id, str) and resume_last_response_id.strip() else None
    )
    if isinstance(fallback_transcript_items, list):
        snapshot_model.resume_cursor.fallback_transcript_items = _json_clone(fallback_transcript_items)
    now_ms = int(updated_at_ms) if isinstance(updated_at_ms, int) else int(time() * 1000)
    snapshot_model.last_run = SessionLastRun(
        response_id=run_response_id,
        last_event_seq=int(last_event_seq) if isinstance(last_event_seq, int) else 0,
        updated_at_ms=now_ms,
        prompt_context=_coerce_prompt_audit(prompt_audit),
    )
    return snapshot_model.model_dump(mode="json", exclude_none=True)


def read_fallback_transcript_items(snapshot: dict[str, Any]) -> list[dict[str, Any]]:
    return input_to_transcript_items(coerce_persisted_session_snapshot(snapshot).resume_cursor.fallback_transcript_items)


def _coerce_prompt_audit(prompt_audit: PromptContextAudit | dict[str, Any] | None) -> PromptContextAudit | None:
    if isinstance(prompt_audit, PromptContextAudit):
        return prompt_audit
    if isinstance(prompt_audit, dict) and prompt_audit:
        try:
            if "fragment_count" in prompt_audit or "retained_fragment_count" in prompt_audit:
                return PromptContextAudit.model_validate(prompt_audit)
            return build_prompt_context_audit(
                prompt_cache_key=prompt_audit.get("prompt_cache_key") if isinstance(prompt_audit.get("prompt_cache_key"), str) else None,
                fragments=list(prompt_audit.get("fragments") or []),
            )
        except Exception:  # noqa: BLE001
            return None
    return None


async def _create_initial_session_record(
    *,
    session_store: Any,
    session_partition_key: str,
    agent_id: str,
    session_key: str,
    snapshot_json: dict[str, Any],
) -> Any:
    if hasattr(session_store, "create_if_absent"):
        return await session_store.create_if_absent(
            session_partition_key=session_partition_key,
            agent_id=agent_id,
            session_key=session_key,
            snapshot_json=snapshot_json,
        )
    if hasattr(session_store, "upsert"):
        return await session_store.upsert(
            session_partition_key=session_partition_key,
            agent_id=agent_id,
            session_key=session_key,
            snapshot_json=snapshot_json,
            expected_snapshot_version=None,
        )
    raise TypeError("session_store must support create_if_absent() or upsert()")


async def _update_session_snapshot(
    *,
    session_store: Any,
    session_partition_key: str,
    agent_id: str,
    session_key: str,
    snapshot_json: dict[str, Any],
    expected_snapshot_version: int | None,
) -> tuple[bool, Any | None]:
    if hasattr(session_store, "update_snapshot_cas"):
        return await session_store.update_snapshot_cas(
            session_partition_key=session_partition_key,
            expected_snapshot_version=int(expected_snapshot_version or 0),
            snapshot_json=snapshot_json,
            agent_id=agent_id,
            session_key=session_key,
        )
    if hasattr(session_store, "upsert"):
        record = await session_store.upsert(
            session_partition_key=session_partition_key,
            agent_id=agent_id,
            session_key=session_key,
            snapshot_json=snapshot_json,
            expected_snapshot_version=expected_snapshot_version,
        )
        return True, record
    raise TypeError("session_store must support update_snapshot_cas() or upsert()")


def response_to_transcript_items(response_json: dict[str, Any] | None) -> list[dict[str, Any]]:
    if not isinstance(response_json, dict):
        return []
    output = response_json.get("output")
    if not isinstance(output, list):
        return []

    out: list[dict[str, Any]] = []
    for item in output:
        if not isinstance(item, dict):
            continue
        if item.get("type") != "message":
            continue
        role = item.get("role")
        if role not in {"assistant", "user"}:
            continue
        content = item.get("content")
        text = _extract_message_text(content)
        if text is None:
            continue
        out.append({"role": role, "content": text})
    return out


def _normalize_transcript_item(item: Any) -> dict[str, Any] | None:
    if not isinstance(item, dict):
        return None
    item_type = item.get("type")
    if item_type == "function_call_output":
        call_id = item.get("call_id")
        output = item.get("output")
        if isinstance(call_id, str) and call_id.strip() and isinstance(output, str):
            return {"type": "function_call_output", "call_id": call_id.strip(), "output": output}
        return None
    role = item.get("role")
    if role not in {"user", "assistant", "system", "developer"}:
        return None
    content = item.get("content")
    if isinstance(content, str):
        content = content.strip()
        if not content:
            return None
        return {"role": role, "content": content}
    if isinstance(content, list):
        return {"role": role, "content": _json_clone(content)}
    return None


def _extract_message_text(content: Any) -> str | None:
    if isinstance(content, str):
        s = content.strip()
        return s or None
    if not isinstance(content, list):
        return None
    parts: list[str] = []
    for item in content:
        if not isinstance(item, dict):
            continue
        if item.get("type") != "output_text":
            continue
        text = item.get("text")
        if isinstance(text, str) and text.strip():
            parts.append(text.strip())
    if not parts:
        return None
    return "\n".join(parts)
