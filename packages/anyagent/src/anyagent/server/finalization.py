from __future__ import annotations

from typing import Any

from anyagent.agent_runtime.session_runtime import build_persisted_session_snapshot, persist_session_snapshot


def internal_run_status_from_effective(status: str) -> str:
    if status == "cancelled":
        return "aborted"
    if status == "failed":
        return "errored"
    if status == "in_progress":
        return "started"
    return status


async def persist_run_final_and_session(
    *,
    run_store: Any,
    session_store: Any,
    response_id: str,
    status: str,
    final_response_json: dict[str, Any] | None,
    error_json: dict[str, Any] | None,
    session_partition_key: str,
    agent_id: str,
    session_key: str,
    previous_snapshot: dict[str, Any] | None,
    previous_snapshot_version: int | None,
    runtime_config: dict[str, Any],
    request_transcript_items: list[dict[str, Any]] | None,
    resume_last_response_id: str | None,
    last_event_seq: int | None,
) -> None:
    next_snapshot = build_persisted_session_snapshot(
        previous_snapshot=previous_snapshot,
        runtime_config=runtime_config,
        request_transcript_items=request_transcript_items,
        response_id=response_id,
        effective_status=status,
        response_json=final_response_json,
        last_event_seq=last_event_seq,
        resume_last_response_id=resume_last_response_id,
    )

    if hasattr(run_store, "set_final_with_session_snapshot"):
        ok, _latest = await run_store.set_final_with_session_snapshot(  # type: ignore[attr-defined]
            response_id=response_id,
            status=status,
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
            status=status,
            final_response_json=final_response_json,
            error_json=error_json,
        )
        return

    await run_store.set_final(
        response_id=response_id,
        status=status,
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
        effective_status=status,
        response_json=final_response_json,
        last_event_seq=last_event_seq,
        resume_last_response_id=resume_last_response_id,
    )
