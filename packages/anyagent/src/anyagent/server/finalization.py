from __future__ import annotations

import json
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any

from anyagent.agent_runtime.session_runtime import build_persisted_session_snapshot, persist_session_snapshot
from anyagent.protocol.openai_responses import serialize_completed_response_event_data
from anyagent.protocol.prompt_context import PromptContextAudit
from anyagent.protocol.sse import normalize_response_id


@dataclass(slots=True)
class NonStreamFinalizationState:
    response_id: str | None
    response_json: dict[str, Any] | None
    effective_status: str
    run_status: str
    error_json: dict[str, Any] | None
    last_event_seq: int | None
    resume_last_response_id: str | None


NonStreamEventAppender = Callable[[str | None, str], Awaitable[int | None]]
NonStreamFinalizationHook = Callable[[NonStreamFinalizationState], Awaitable[None]]
FinalizationStateValueResolver = Callable[[NonStreamFinalizationState], str | None]
FinalizationWarningHook = Callable[[str], None]
NonStreamResponseFinalizer = Callable[..., Awaitable[NonStreamFinalizationState]]

_UNSET = object()


def build_session_snapshot_advancer(
    *,
    session_store: Any,
    session_partition_key: str,
    agent_id: str,
    session_key: str,
    previous_snapshot: dict[str, Any] | None,
    previous_snapshot_version: int | None,
    runtime_config: dict[str, Any],
    request_transcript_items: list[dict[str, Any]] | None,
    prompt_audit: PromptContextAudit | dict[str, Any] | None = None,
    response_id_resolver: FinalizationStateValueResolver | None = None,
    warn: FinalizationWarningHook | None = None,
) -> NonStreamFinalizationHook:
    async def _advance(final_state: NonStreamFinalizationState) -> None:
        response_id = response_id_resolver(final_state) if response_id_resolver is not None else final_state.response_id
        if not isinstance(response_id, str) or not response_id.strip():
            return
        try:
            ok, latest = await persist_session_snapshot(
                session_store=session_store,
                session_partition_key=session_partition_key,
                agent_id=agent_id,
                session_key=session_key,
                previous_snapshot=previous_snapshot,
                previous_snapshot_version=previous_snapshot_version,
                runtime_config=runtime_config,
                request_transcript_items=request_transcript_items,
                response_id=response_id,
                effective_status=final_state.effective_status,
                response_json=final_state.response_json,
                last_event_seq=final_state.last_event_seq,
                resume_last_response_id=final_state.resume_last_response_id,
                prompt_audit=prompt_audit,
            )
            if not ok and warn is not None:
                latest_version = getattr(latest, "snapshot_version", None) if latest is not None else None
                warn(
                    "persist session snapshot failed (cas): "
                    f"expected_snapshot_version={previous_snapshot_version} "
                    f"latest_snapshot_version={latest_version}"
                )
        except Exception as exc:  # noqa: BLE001
            if warn is None:
                raise
            warn(f"persist session snapshot failed: {exc}")

    return _advance


def build_run_final_and_session_persister(
    *,
    run_store: Any,
    session_store: Any,
    session_partition_key: str,
    agent_id: str,
    session_key: str,
    previous_snapshot: dict[str, Any] | None,
    previous_snapshot_version: int | None,
    runtime_config: dict[str, Any],
    request_transcript_items: list[dict[str, Any]] | None,
    prompt_audit: PromptContextAudit | dict[str, Any] | None = None,
    response_id_resolver: FinalizationStateValueResolver | None = None,
    warn: FinalizationWarningHook | None = None,
) -> NonStreamFinalizationHook:
    async def _persist(final_state: NonStreamFinalizationState) -> None:
        response_id = response_id_resolver(final_state) if response_id_resolver is not None else final_state.response_id
        if not isinstance(response_id, str) or not response_id.strip():
            return
        try:
            await persist_run_final_and_session(
                run_store=run_store,
                session_store=session_store,
                response_id=response_id,
                effective_status=final_state.effective_status,
                final_response_json=final_state.response_json,
                error_json=final_state.error_json,
                session_partition_key=session_partition_key,
                agent_id=agent_id,
                session_key=session_key,
                previous_snapshot=previous_snapshot,
                previous_snapshot_version=previous_snapshot_version,
                runtime_config=runtime_config,
                request_transcript_items=request_transcript_items,
                prompt_audit=prompt_audit,
                resume_last_response_id=final_state.resume_last_response_id,
                last_event_seq=final_state.last_event_seq,
            )
        except Exception as exc:  # noqa: BLE001
            if warn is None:
                raise
            warn(f"persist run final+session failed: {exc}")

    return _persist


def build_nonstream_response_finalizer(
    *,
    response_id: str | None,
    append_event: NonStreamEventAppender | None = None,
    mark_event_final: NonStreamFinalizationHook | None = None,
    persist_run_final: NonStreamFinalizationHook | None = None,
    advance_session: NonStreamFinalizationHook | None = None,
    append_completed_event: bool | None = None,
    append_done_sentinel: bool | None = None,
    resume_last_response_id: str | None = None,
) -> NonStreamResponseFinalizer:
    async def _finalize(
        *,
        response_json: dict[str, Any] | None,
        effective_status: str | None = None,
        error_json: dict[str, Any] | None = None,
        error_event_data: str | None = None,
        resume_last_response_id_override: object = _UNSET,
        append_completed_event_override: object = _UNSET,
        append_done_sentinel_override: object = _UNSET,
    ) -> NonStreamFinalizationState:
        resolved_resume_last_response_id = (
            resume_last_response_id
            if resume_last_response_id_override is _UNSET
            else resume_last_response_id_override
        )
        resolved_append_completed_event = (
            append_completed_event
            if append_completed_event_override is _UNSET
            else append_completed_event_override
        )
        resolved_append_done_sentinel = (
            append_done_sentinel
            if append_done_sentinel_override is _UNSET
            else append_done_sentinel_override
        )
        return await finalize_nonstream_response(
            response_id=response_id,
            response_json=response_json,
            effective_status=effective_status,
            error_json=error_json,
            error_event_data=error_event_data,
            append_event=append_event,
            mark_event_final=mark_event_final,
            persist_run_final=persist_run_final,
            advance_session=advance_session,
            append_completed_event=resolved_append_completed_event,
            append_done_sentinel=resolved_append_done_sentinel,
            resume_last_response_id=resolved_resume_last_response_id,
        )

    return _finalize


def internal_run_status_from_effective(status: str) -> str:
    if status == "cancelled":
        return "aborted"
    if status == "failed":
        return "errored"
    if status == "in_progress":
        return "started"
    return status


def resolve_terminal_status(
    *,
    effective_status: str | None,
    response_json: dict[str, Any] | None,
    error_json: dict[str, Any] | None,
) -> tuple[str, str]:
    resolved_effective_status = effective_status.strip() if isinstance(effective_status, str) and effective_status.strip() else None
    if resolved_effective_status is None and isinstance(response_json, dict):
        response_status = response_json.get("status")
        if isinstance(response_status, str) and response_status.strip():
            resolved_effective_status = response_status.strip()
    if resolved_effective_status is None:
        resolved_effective_status = "failed" if error_json is not None else "completed"
    return resolved_effective_status, internal_run_status_from_effective(resolved_effective_status)


def _clone_json_dict(value: dict[str, Any] | None) -> dict[str, Any] | None:
    if not isinstance(value, dict):
        return None
    try:
        cloned = json.loads(json.dumps(value, ensure_ascii=False))
    except Exception:  # noqa: BLE001
        cloned = dict(value)
    return cloned if isinstance(cloned, dict) else dict(value)


def _looks_like_response_json(value: dict[str, Any] | None) -> bool:
    return bool(
        isinstance(value, dict)
        and value.get("object") == "response"
        and isinstance(value.get("id"), str)
        and value["id"].strip()
    )


def _canonicalize_response_json(
    *,
    response_json: dict[str, Any] | None,
    canonical_response_id: str | None,
) -> dict[str, Any] | None:
    cloned = _clone_json_dict(response_json)
    if cloned is None:
        return None
    if _looks_like_response_json(cloned) and isinstance(canonical_response_id, str) and canonical_response_id.strip():
        normalize_response_id(cloned, canonical_response_id.strip())
    return cloned


async def finalize_nonstream_response(
    *,
    response_id: str | None,
    response_json: dict[str, Any] | None,
    effective_status: str | None = None,
    error_json: dict[str, Any] | None = None,
    error_event_data: str | None = None,
    append_event: NonStreamEventAppender | None = None,
    mark_event_final: NonStreamFinalizationHook | None = None,
    persist_run_final: NonStreamFinalizationHook | None = None,
    advance_session: NonStreamFinalizationHook | None = None,
    append_completed_event: bool | None = None,
    append_done_sentinel: bool | None = None,
    resume_last_response_id: str | None = None,
) -> NonStreamFinalizationState:
    normalized_response_id = response_id.strip() if isinstance(response_id, str) and response_id.strip() else None
    normalized_response_json = _canonicalize_response_json(
        response_json=response_json,
        canonical_response_id=normalized_response_id,
    )
    resolved_effective_status, run_status = resolve_terminal_status(
        effective_status=effective_status,
        response_json=normalized_response_json,
        error_json=error_json,
    )
    state = NonStreamFinalizationState(
        response_id=normalized_response_id,
        response_json=normalized_response_json,
        effective_status=resolved_effective_status,
        run_status=run_status,
        error_json=_clone_json_dict(error_json),
        last_event_seq=None,
        resume_last_response_id=(
            resume_last_response_id.strip()
            if isinstance(resume_last_response_id, str) and resume_last_response_id.strip()
            else None
        ),
    )

    if isinstance(error_event_data, str) and error_event_data.strip() and append_event is not None and state.response_id is not None:
        seq = await append_event("error", error_event_data)
        if isinstance(seq, int):
            state.last_event_seq = seq

    should_append_completed = append_completed_event
    if should_append_completed is None:
        should_append_completed = (
            append_event is not None
            and state.response_id is not None
            and state.effective_status == "completed"
            and _looks_like_response_json(state.response_json)
        )
    if should_append_completed and append_event is not None and state.response_id is not None and state.response_json is not None:
        state.response_json, completed_data = serialize_completed_response_event_data(
            state.response_json,
            canonical_response_id=state.response_id,
        )
        seq = await append_event("response.completed", completed_data)
        if isinstance(seq, int):
            state.last_event_seq = seq

    should_append_done = append_done_sentinel
    if should_append_done is None:
        should_append_done = append_event is not None and state.response_id is not None
    if should_append_done and append_event is not None and state.response_id is not None:
        seq = await append_event(None, "[DONE]")
        if isinstance(seq, int):
            state.last_event_seq = seq

    if mark_event_final is not None and state.response_id is not None:
        await mark_event_final(state)
    if persist_run_final is not None and state.response_id is not None:
        await persist_run_final(state)
    if advance_session is not None:
        await advance_session(state)
    return state


async def persist_run_final_and_session(
    *,
    run_store: Any,
    session_store: Any,
    response_id: str,
    effective_status: str,
    final_response_json: dict[str, Any] | None,
    error_json: dict[str, Any] | None,
    session_partition_key: str,
    agent_id: str,
    session_key: str,
    previous_snapshot: dict[str, Any] | None,
    previous_snapshot_version: int | None,
    runtime_config: dict[str, Any],
    request_transcript_items: list[dict[str, Any]] | None,
    prompt_audit: PromptContextAudit | dict[str, Any] | None = None,
    resume_last_response_id: str | None,
    last_event_seq: int | None,
) -> None:
    resolved_effective_status, run_status = resolve_terminal_status(
        effective_status=effective_status,
        response_json=final_response_json,
        error_json=error_json,
    )
    next_snapshot = build_persisted_session_snapshot(
        previous_snapshot=previous_snapshot,
        runtime_config=runtime_config,
        request_transcript_items=request_transcript_items,
        response_id=response_id,
        effective_status=resolved_effective_status,
        response_json=final_response_json,
        last_event_seq=last_event_seq,
        resume_last_response_id=resume_last_response_id,
        prompt_audit=prompt_audit,
    )

    if hasattr(run_store, "set_final_with_session_snapshot"):
        ok, _latest = await run_store.set_final_with_session_snapshot(  # type: ignore[attr-defined]
            response_id=response_id,
            status=run_status,
            final_response_json=final_response_json,
            error_json=error_json,
            session_partition_key=session_partition_key,
            agent_id=agent_id,
            session_key=session_key,
            snapshot_json=next_snapshot,
            expected_snapshot_version=previous_snapshot_version,
        )
        if ok:
            return
        await run_store.set_final(
            response_id=response_id,
            status=run_status,
            final_response_json=final_response_json,
            error_json=error_json,
        )
        return

    await run_store.set_final(
        response_id=response_id,
        status=run_status,
        final_response_json=final_response_json,
        error_json=error_json,
    )
    await persist_session_snapshot(
        session_store=session_store,
        session_partition_key=session_partition_key,
        agent_id=agent_id,
        session_key=session_key,
        previous_snapshot=previous_snapshot,
        previous_snapshot_version=previous_snapshot_version,
        runtime_config=runtime_config,
        request_transcript_items=request_transcript_items,
        response_id=response_id,
        effective_status=resolved_effective_status,
        response_json=final_response_json,
        last_event_seq=last_event_seq,
        resume_last_response_id=resume_last_response_id,
        prompt_audit=prompt_audit,
    )
