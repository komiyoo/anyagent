from __future__ import annotations

from typing import Any

from fastapi.responses import StreamingResponse

from anyagent.agent_runtime import persist_session_snapshot
from anyagent.protocol.prompt_context import PromptContextAudit
from anyagent.protocol.sse import SSEBlockDecoder
from anyagent.server.responses.streaming import (
    append_sse_chunk as append_streaming_sse_chunk,
    build_external_response_stream_response,
    build_persisted_sse_block_handler,
    build_response_event_appender,
    persist_sse_run as persist_streaming_sse_run,
)


def _build_external_response_stream(*, state: Any, response_id: str) -> StreamingResponse:
    return build_external_response_stream_response(
        run_store=state.run_store,
        event_store=state.events,
        response_id=response_id,
        event_filter=lambda event: event is None or event == "error" or (isinstance(event, str) and event.startswith("response.")),
    )


async def _append_sse_chunk(
    state: Any,
    *,
    response_id: str,
    chunk: bytes,
    decoder: SSEBlockDecoder,
    fallback_model: Any,
    session_partition_key_value: str | None = None,
    agent_id: str | None = None,
    session_key: str | None = None,
    previous_snapshot: dict[str, Any] | None = None,
    previous_snapshot_version: int | None = None,
    runtime_config: dict[str, Any] | None = None,
    request_transcript_items: list[dict[str, Any]] | None = None,
    prompt_audit: PromptContextAudit | dict[str, Any] | None = None,
) -> None:
    append_event = build_response_event_appender(
        response_id=response_id,
        writer=lambda rid, event, data: state.events.append(response_id=rid, event=event, data=data),
    )

    async def _mark_event_final(final_state) -> None:
        await state.events.mark_final(
            response_id=response_id,
            run_status=final_state.run_status,
            effective_run_status=final_state.effective_status,
            response_json=final_state.response_json,
        )

    async def _persist_run_final(final_state) -> None:
        await state.run_store.mark_final(
            response_id=response_id,
            status=final_state.run_status,
            effective_status=final_state.effective_status,
            final_response_json=final_state.response_json,
            error_json=final_state.error_json,
        )

    async def _advance_session(final_state) -> None:
        if (
            isinstance(session_partition_key_value, str)
            and isinstance(agent_id, str)
            and isinstance(session_key, str)
            and isinstance(runtime_config, dict)
        ):
            await _update_session_snapshot(
                state=state,
                session_partition_key_value=session_partition_key_value,
                agent_id=agent_id,
                session_key=session_key,
                previous_snapshot=previous_snapshot,
                previous_snapshot_version=previous_snapshot_version,
                runtime_config=runtime_config,
                request_transcript_items=request_transcript_items,
                response_id=final_state.response_id or response_id,
                effective_status=final_state.effective_status,
                response_json=final_state.response_json,
                prompt_audit=prompt_audit,
            )

    persist_block = build_persisted_sse_block_handler(
        response_id=response_id,
        fallback_model=fallback_model,
        append_event=append_event,
        persist_run_final=_persist_run_final,
        mark_event_final=_mark_event_final,
        advance_session=_advance_session,
    )

    await append_streaming_sse_chunk(
        chunk=chunk,
        decoder=decoder,
        persist_block=persist_block,
    )


async def _persist_sse_run(
    state: Any,
    *,
    chunks: list[bytes],
    fallback_model: Any,
    session_partition_key_value: str | None = None,
    agent_id: str | None = None,
    session_key: str | None = None,
    previous_snapshot: dict[str, Any] | None = None,
    previous_snapshot_version: int | None = None,
    runtime_config: dict[str, Any] | None = None,
    request_transcript_items: list[dict[str, Any]] | None = None,
) -> tuple[str, dict[str, Any] | None]:
    response_id_box = ["resp_anyagent"]
    append_event = build_response_event_appender(
        response_id_resolver=lambda: response_id_box[0],
        writer=lambda rid, event, data: state.events.append(response_id=rid, event=event, data=data),
    )

    async def _persist_run_final(final_state) -> None:
        await state.run_store.mark_final(
            response_id=final_state.response_id or response_id_box[0],
            status=final_state.run_status,
            effective_status=final_state.effective_status,
            final_response_json=final_state.response_json,
            error_json=final_state.error_json,
        )

    async def _mark_event_final(final_state) -> None:
        await state.events.mark_final(
            response_id=final_state.response_id or response_id_box[0],
            run_status=final_state.run_status,
            effective_run_status=final_state.effective_status,
            response_json=final_state.response_json,
        )

    async def _advance_session(final_state) -> None:
        if (
            isinstance(session_partition_key_value, str)
            and isinstance(agent_id, str)
            and isinstance(session_key, str)
            and isinstance(runtime_config, dict)
        ):
            await _update_session_snapshot(
                state=state,
                session_partition_key_value=session_partition_key_value,
                agent_id=agent_id,
                session_key=session_key,
                previous_snapshot=previous_snapshot,
                previous_snapshot_version=previous_snapshot_version,
                runtime_config=runtime_config,
                request_transcript_items=request_transcript_items,
                response_id=final_state.response_id or response_id_box[0],
                effective_status=final_state.effective_status,
                response_json=final_state.response_json,
            )

    response_id, response_json = await persist_streaming_sse_run(
        chunks=chunks,
        append_event=append_event,
        persist_run_final=_persist_run_final,
        fallback_model=fallback_model,
        response_id_hint=response_id_box[0],
        mark_event_final=_mark_event_final,
        advance_session=_advance_session,
    )
    response_id_box[0] = response_id
    return response_id, response_json


async def _update_session_snapshot(
    *,
    state: Any,
    session_partition_key_value: str,
    agent_id: str,
    session_key: str,
    previous_snapshot: dict[str, Any] | None,
    previous_snapshot_version: int | None,
    runtime_config: dict[str, Any],
    request_transcript_items: list[dict[str, Any]] | None,
    response_id: str,
    effective_status: str,
    response_json: dict[str, Any] | None = None,
    prompt_audit: PromptContextAudit | dict[str, Any] | None = None,
) -> None:
    latest_seq = await state.events.latest_seq(response_id)
    await persist_session_snapshot(
        session_store=state.session_store,
        session_partition_key=session_partition_key_value,
        agent_id=agent_id,
        session_key=session_key,
        previous_snapshot=previous_snapshot,
        previous_snapshot_version=previous_snapshot_version,
        runtime_config=runtime_config,
        request_transcript_items=request_transcript_items,
        response_id=response_id,
        effective_status=effective_status,
        response_json=response_json,
        last_event_seq=latest_seq,
        prompt_audit=prompt_audit,
    )
