from __future__ import annotations

import asyncio
import json
import logging
from collections.abc import Awaitable, Callable
from typing import Any

from fastapi.responses import JSONResponse, Response, StreamingResponse

from anyagent.agent_runtime import (
    ModelProviderInvalidRequestError,
    ModelProviderTransportError,
    ModelProviderUpstreamError,
)
from anyagent.agent_runtime import run_tool_loop_nonstream as default_run_tool_loop_nonstream
from anyagent.agent_runtime import run_tool_loop_stream_live as default_run_tool_loop_stream_live
from anyagent.protocol.stage_events import AnyAgentModelRequestEvent
from anyagent.protocol.sse import SSEBlockDecoder

from anyagent.server.handlers.http_errors import openai_error_response
from .idempotency import build_distributed_response_stream_response
from .session_serialization import run_with_storage_session_lease
from .streaming import (
    append_sse_chunk,
    build_persisted_sse_block_handler,
    build_response_event_appender,
    encode_forward_stream_block,
)

RunToolLoopNonstreamFn = Callable[..., Awaitable[tuple[int, dict[str, Any]]]]
RunToolLoopStreamLiveFn = Callable[..., Any]
PromptContextAppender = Callable[[str], Awaitable[None]]
PersistedFinalizer = Callable[..., Awaitable[None]]
SessionOnlyAdvancer = Callable[..., Awaitable[None]]
InternalEventWriter = Callable[..., Awaitable[int | None]]
RunFinalPersisterBuilder = Callable[[str], Any]
DisconnectedChecker = Callable[[], Awaitable[bool]]

_logger = logging.getLogger("anyagent.server.responses.response_execution")


async def execute_distributed_nonstream_response(
    *,
    model_provider: Any,
    tool_runtime: Any,
    agent_id: str,
    session_key: str,
    body: dict[str, Any],
    idempotency_key: str | None,
    idem_created: bool,
    idem_response_id: str | None,
    tool_context: Any,
    manifest_resolver: Callable[[], Awaitable[tuple[list[dict[str, Any]], int]]],
    manifest_force_refresh: Callable[[], Awaitable[tuple[list[dict[str, Any]], int]]],
    mcp_manager: Any,
    stage_event_sink: Any,
    append_prompt_context_event: PromptContextAppender,
    append_prompt_context_rendered_event: PromptContextAppender,
    finalize_nonstream_persisted: PersistedFinalizer,
    advance_nonstream_session_only: SessionOnlyAdvancer,
    new_response_id_factory: Callable[[], str],
    prompt_cache_key: str | None = None,
    run_tool_loop_nonstream_fn: RunToolLoopNonstreamFn = default_run_tool_loop_nonstream,
) -> Response:
    response_id_for_run = (
        idem_response_id
        if isinstance(idem_response_id, str) and idem_response_id
        else new_response_id_factory()
    )
    if idempotency_key is not None and idem_created:
        await append_prompt_context_event(response_id_for_run)
        await append_prompt_context_rendered_event(response_id_for_run)

    if stage_event_sink is not None:
        try:
            await stage_event_sink(AnyAgentModelRequestEvent(
                response_id=response_id_for_run,
                applied_body=body,
                prompt_cache_key=prompt_cache_key,
            ))
        except Exception:
            _logger.warning("failed to emit model request event", exc_info=True)

    status_code, resp_json = await run_tool_loop_nonstream_fn(
        model_provider=model_provider,
        tool_runtime=tool_runtime,
        agent_id=agent_id,
        session_key=session_key,
        body=body,
        idempotency_key=idempotency_key if idem_created else None,
        canonical_response_id=response_id_for_run,
        tool_context=tool_context,
        selected_skills=[],
        manifest_resolver=manifest_resolver,
        manifest_force_refresh=manifest_force_refresh,
        mcp_manager=mcp_manager,
        stage_event_sink=stage_event_sink,
    )

    if status_code >= 400 or not isinstance(resp_json, dict):
        if idempotency_key is not None and idem_created and isinstance(idem_response_id, str) and idem_response_id:
            err_json = resp_json if isinstance(resp_json, dict) else {"error": {"message": "upstream_error"}}
            await finalize_nonstream_persisted(
                run_response_id=idem_response_id,
                response_json=None,
                effective_status="failed",
                error_json=err_json.get("error") if isinstance(err_json, dict) else None,
                resume_last_response_id=None,
                error_event_data=json.dumps(err_json, ensure_ascii=False, separators=(",", ":")),
            )
        if isinstance(resp_json, dict):
            return JSONResponse(status_code=status_code, content=resp_json)
        return openai_error_response(status_code, message="Upstream error", type_="upstream_error")

    if idempotency_key is not None and idem_created and isinstance(idem_response_id, str) and idem_response_id:
        await finalize_nonstream_persisted(
            run_response_id=idem_response_id,
            response_json=resp_json,
            effective_status="completed" if status_code < 400 else "failed",
            error_json=resp_json.get("error") if status_code >= 400 else None,
            resume_last_response_id=idem_response_id,
        )
    else:
        await advance_nonstream_session_only(
            run_response_id=resp_json.get("id") if isinstance(resp_json.get("id"), str) else None,
            response_json=resp_json,
            effective_status=None,
            resume_last_response_id=resp_json.get("id") if isinstance(resp_json.get("id"), str) else None,
        )

    return JSONResponse(status_code=status_code, content=resp_json)


async def execute_distributed_stream_response(
    *,
    model_provider: Any,
    tool_runtime: Any,
    agent_id: str,
    session_key: str,
    body: dict[str, Any],
    idempotency_key: str | None,
    idem_created: bool,
    idem_response_id: str | None,
    storage: Any,
    storage_tasks: set[asyncio.Task[object]],
    session_partition_key: str,
    tool_context: Any,
    manifest_resolver: Callable[[], Awaitable[tuple[list[dict[str, Any]], int]]],
    manifest_force_refresh: Callable[[], Awaitable[tuple[list[dict[str, Any]], int]]],
    mcp_manager: Any,
    stage_event_sink: Any,
    append_prompt_context_event: PromptContextAppender,
    append_prompt_context_rendered_event: PromptContextAppender,
    internal_event_writer: InternalEventWriter,
    run_final_persister_builder: RunFinalPersisterBuilder,
    new_response_id_factory: Callable[[], str],
    is_disconnected: DisconnectedChecker | None = None,
    prompt_cache_key: str | None = None,
    run_tool_loop_stream_live_fn: RunToolLoopStreamLiveFn = default_run_tool_loop_stream_live,
) -> Response:
    if idempotency_key is not None and idem_created and isinstance(idem_response_id, str) and idem_response_id:
        task = asyncio.create_task(
            _run_idempotent_stream_to_store(
                model_provider=model_provider,
                tool_runtime=tool_runtime,
                agent_id=agent_id,
                session_key=session_key,
                body=body,
                idempotency_key=idempotency_key,
                canonical_response_id=idem_response_id,
                storage=storage,
                session_partition_key=session_partition_key,
                tool_context=tool_context,
                manifest_resolver=manifest_resolver,
                manifest_force_refresh=manifest_force_refresh,
                mcp_manager=mcp_manager,
                stage_event_sink=stage_event_sink,
                append_prompt_context_event=append_prompt_context_event,
                append_prompt_context_rendered_event=append_prompt_context_rendered_event,
                internal_event_writer=internal_event_writer,
                run_final_persister_builder=run_final_persister_builder,
                prompt_cache_key=prompt_cache_key,
                run_tool_loop_stream_live_fn=run_tool_loop_stream_live_fn,
            )
        )
        storage_tasks.add(task)
        task.add_done_callback(lambda completed: storage_tasks.discard(completed))  # type: ignore[arg-type]
        return build_distributed_response_stream_response(storage=storage, response_id=idem_response_id)

    canonical_response_id = new_response_id_factory()
    await append_prompt_context_event(canonical_response_id)
    await append_prompt_context_rendered_event(canonical_response_id)

    if stage_event_sink is not None:
        try:
            await stage_event_sink(AnyAgentModelRequestEvent(
                response_id=canonical_response_id,
                applied_body=body,
                prompt_cache_key=prompt_cache_key,
            ))
        except Exception:
            _logger.warning("failed to emit model request event", exc_info=True)

    async def iter_sse() -> Any:
        try:
            async for chunk in run_tool_loop_stream_live_fn(
                model_provider=model_provider,
                tool_runtime=tool_runtime,
                agent_id=agent_id,
                session_key=session_key,
                body=body,
                idempotency_key=idempotency_key,
                canonical_response_id=canonical_response_id,
                tool_context=tool_context,
                selected_skills=[],
                manifest_resolver=manifest_resolver,
                manifest_force_refresh=manifest_force_refresh,
                mcp_manager=mcp_manager,
                stage_event_sink=stage_event_sink,
            ):
                if is_disconnected is not None and await is_disconnected():
                    return
                yield chunk
        except ModelProviderInvalidRequestError as e:
            yield encode_forward_stream_block(
                event="error",
                data=json.dumps(
                    {"error": {"message": e.message, "type": "invalid_request_error"}},
                    ensure_ascii=False,
                    separators=(",", ":"),
                ),
            )
            yield encode_forward_stream_block(event=None, data="[DONE]")
        except ModelProviderUpstreamError as e:
            payload = e.body if isinstance(e.body, dict) else {"error": {"message": e.message or "upstream_error", "type": "upstream_error"}}
            yield encode_forward_stream_block(event="error", data=json.dumps(payload, ensure_ascii=False, separators=(",", ":")))
            yield encode_forward_stream_block(event=None, data="[DONE]")
        except ModelProviderTransportError as e:
            yield encode_forward_stream_block(
                event="error",
                data=json.dumps(
                    {"error": {"message": e.message, "type": "upstream_error"}},
                    ensure_ascii=False,
                    separators=(",", ":"),
                ),
            )
            yield encode_forward_stream_block(event=None, data="[DONE]")

    return StreamingResponse(iter_sse(), media_type="text/event-stream")


async def _run_idempotent_stream_to_store(
    *,
    model_provider: Any,
    tool_runtime: Any,
    agent_id: str,
    session_key: str,
    body: dict[str, Any],
    idempotency_key: str,
    canonical_response_id: str,
    storage: Any,
    session_partition_key: str,
    tool_context: Any,
    manifest_resolver: Callable[[], Awaitable[tuple[list[dict[str, Any]], int]]],
    manifest_force_refresh: Callable[[], Awaitable[tuple[list[dict[str, Any]], int]]],
    mcp_manager: Any,
    stage_event_sink: Any,
    append_prompt_context_event: PromptContextAppender,
    append_prompt_context_rendered_event: PromptContextAppender,
    internal_event_writer: InternalEventWriter,
    run_final_persister_builder: RunFinalPersisterBuilder,
    prompt_cache_key: str | None = None,
    run_tool_loop_stream_live_fn: RunToolLoopStreamLiveFn = default_run_tool_loop_stream_live,
) -> None:
    await append_prompt_context_event(canonical_response_id)
    await append_prompt_context_rendered_event(canonical_response_id)

    if stage_event_sink is not None:
        try:
            await stage_event_sink(AnyAgentModelRequestEvent(
                response_id=canonical_response_id,
                applied_body=body,
                prompt_cache_key=prompt_cache_key,
            ))
        except Exception:
            _logger.warning("failed to emit model request event", exc_info=True)

    append_event = build_response_event_appender(
        response_id=canonical_response_id,
        writer=lambda rid, event, data: internal_event_writer(
            response_id=rid,
            event=event,
            data=data,
        ),
    )

    persist_stream_run_final = run_final_persister_builder(canonical_response_id)
    finalize_stream_terminal = build_persisted_sse_block_handler(
        response_id=canonical_response_id,
        fallback_model=body.get("model"),
        append_event=append_event,
        persist_run_final=persist_stream_run_final,
        persist_non_terminal_events=True,
    )

    async def _run_inner() -> None:
        decoder = SSEBlockDecoder()
        async for chunk in run_tool_loop_stream_live_fn(
            model_provider=model_provider,
            tool_runtime=tool_runtime,
            agent_id=agent_id,
            session_key=session_key,
            body=body,
            idempotency_key=idempotency_key,
            canonical_response_id=canonical_response_id,
            tool_context=tool_context,
            selected_skills=[],
            manifest_resolver=manifest_resolver,
            manifest_force_refresh=manifest_force_refresh,
            mcp_manager=mcp_manager,
            stage_event_sink=stage_event_sink,
        ):
            await append_sse_chunk(
                chunk=chunk,
                decoder=decoder,
                persist_block=finalize_stream_terminal,
            )

    try:
        await run_with_storage_session_lease(
            storage=storage,
            session_partition_key=session_partition_key,
            owner=canonical_response_id,
            fn=_run_inner,
        )
    except Exception as e:  # noqa: BLE001
        await _persist_stream_failure(
            response_id=canonical_response_id,
            append_event=append_event,
            persist_run_final=persist_stream_run_final,
            error_json={"type": "storage_error", "message": str(e)},
            error_event_data=str(e),
        )


async def _persist_stream_failure(
    *,
    response_id: str,
    append_event: Any,
    persist_run_final: Any,
    error_json: dict[str, Any],
    error_event_data: str,
) -> None:
    from .finalization import build_nonstream_response_finalizer

    finalize_stream_terminal = build_nonstream_response_finalizer(
        response_id=response_id,
        append_event=append_event,
        persist_run_final=persist_run_final,
        resume_last_response_id=response_id,
    )
    await finalize_stream_terminal(
        response_json=None,
        effective_status="failed",
        error_json=error_json,
        error_event_data=error_event_data,
        append_completed_event_override=False,
    )
