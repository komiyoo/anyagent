from __future__ import annotations

import asyncio
import json
import uuid
from typing import Any, AsyncIterator

from fastapi import APIRouter, Header, HTTPException, Request
from fastapi.responses import JSONResponse, StreamingResponse

from anyagent.agent_runtime import SubAgentExecutor, build_prompt_envelope
from anyagent.agent_runtime.session_runtime import input_to_transcript_items
from anyagent.agent_runtime.tool_loop import resolve_manifest_with_mcp, run_tool_loop_nonstream, run_tool_loop_stream_live
from anyagent.agent_runtime.model_providers import get_default_model_provider
from anyagent.gateway.session import session_partition_key
from anyagent.model_config import (
    ModelConfigError,
    apply_effective_model_to_body,
    model_provider_for_selection,
    resolve_effective_model_selection,
)
from anyagent.observability import emit_observability_event
from anyagent.protocol.openai_responses import build_minimal_openai_response_json
from anyagent.protocol.observability import ObservabilityLevel
from anyagent.protocol.prompt_context import PromptContextAudit
from anyagent.protocol.responses_optional import AnyAgentResponseError
from anyagent.protocol.sse import SSEBlockDecoder, encode_sse_block
from anyagent.protocol.stage_events import AnyAgentModelRequestEvent, AnyAgentPromptContextEvent, AnyAgentPromptContextRenderedEvent
from anyagent.server.app_builders import _dispatch_plugin_hook, _safe_error_message
from anyagent.server.config.request_context import resolve_agent_id, resolve_session_key
from anyagent.server.config.request_validation import (
    ResponsesRequestValidationError,
    ensure_metadata_object,
    ensure_request_body_object,
    parse_function_tools,
)
from anyagent.server.handlers.auth import _require_user_auth
from anyagent.server.handlers.context_providers import _build_context_provider_fragments
from anyagent.server.handlers.middleware import _build_agent_middleware_chain
from anyagent.server.handlers.persistence import _append_sse_chunk, _build_external_response_stream, _update_session_snapshot
from anyagent.server.handlers.sse_blocks import (
    _build_completed_sse_block,
    _build_created_sse_block,
)
from anyagent.server.handlers.tool_context import (
    _build_server_tool_context,
    _select_skills,
    _visible_enabled_skills,
)
from anyagent.server.persistence.manifest_cache import build_manifest_cache_key, extract_requested_tool_names
from anyagent.server.responses.finalization import build_nonstream_response_finalizer
from anyagent.server.responses.idempotency import begin_or_replay_response_run
from anyagent.server.responses.session_context import (
    apply_session_once_context_to_session,
    prepare_response_session_context,
    split_session_once_context_fragments,
)
from anyagent.server.responses.streaming import build_response_event_appender
from anyagent.server.handlers.http_errors import optional_response_payload_from_run
from anyagent.server.runtime.lock_service import hold_session_lease
from anyagent.storage import resolve_nonstream_replay_payload

def create_responses_router() -> APIRouter:
    router = APIRouter()

    @router.post("/v1/responses", response_model=None)
    async def create_response(req: Request, authorization: str | None = Header(default=None), x_agent_id: str | None = Header(default=None)):
        state = req.app.state.anyagent
        _require_user_auth(state, authorization)
        try:
            body_raw = await req.json()
        except Exception as exc:
            raise HTTPException(status_code=400, detail="invalid JSON body") from exc

        try:
            body = ensure_request_body_object(body_raw, message="request body must be an object")
            metadata = ensure_metadata_object(body, message="metadata must be an object")
            request_tools = parse_function_tools(body.get("tools"))
        except ResponsesRequestValidationError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

        if request_tools is not None:
            body = dict(body)
            body["tools"] = [tool.model_dump(exclude_none=True) for tool in request_tools]

        idempotency_key = req.headers.get("idempotency-key")
        agent_id = _resolve_agent_id(body=body, x_agent_id=x_agent_id)
        pack = state.require_pack(agent_id, external=True)
        model_selection = resolve_effective_model_selection(workspace_config=state.models_config, pack=pack)
        apply_effective_model_to_body(body=body, selection=model_selection, workspace_config=state.models_config)
        session_key = _resolve_session_key(body=body)
        session_partition_key_value = session_partition_key(agent_id=agent_id, session_key=session_key)
        stream_requested = bool(body.get("stream"))
        _emit_server_response_event(
            "server.response.request_received",
            agent_id=agent_id,
            session_key=session_key,
            stream=stream_requested,
            idempotency_key_present=idempotency_key is not None,
        )
        async def _create_started_run(response_id_value: str, idem_value: str | None):
            await state.events.mark_started(response_id=response_id_value)
            return await state.run_store.create_started(
                response_id=response_id_value,
                agent_id=agent_id,
                session_key=session_key,
                stream=stream_requested,
                idempotency_key=idem_value,
            )

        gate = await begin_or_replay_response_run(
            idempotency_key=idempotency_key,
            stream=stream_requested,
            new_response_id_factory=lambda: f"resp_{uuid.uuid4().hex}",
            lookup_existing_run=state.run_store.get_by_idempotency_key,
            create_started_run=_create_started_run,
            build_stream_replay_response=lambda replay_response_id: _build_external_response_stream(state=state, response_id=replay_response_id),
            build_nonstream_replay_response=lambda run, replay_response_id: resolve_nonstream_replay_payload(
                run_store=state.run_store,
                run=run,
                response_id=replay_response_id,
                fallback_payload_factory=lambda replay_run: build_minimal_openai_response_json(
                    response_id=replay_run.response_id,
                    status=replay_run.effective_status,  # type: ignore[arg-type]
                    model=str(body.get("model") or "unknown"),
                ),
            ),
        )
        if gate.response is not None:
            _emit_server_response_event(
                "server.response.replayed",
                response_id=gate.response_id,
                agent_id=agent_id,
                session_key=session_key,
                stream=stream_requested,
                idempotency_key_present=idempotency_key is not None,
            )
            if stream_requested:
                return gate.response
            return JSONResponse(gate.response)
        response_id = gate.response_id
        _emit_server_response_event(
            "server.response.run_started",
            response_id=response_id,
            agent_id=agent_id,
            session_key=session_key,
            stream=stream_requested,
            idempotency_key_present=idempotency_key is not None,
        )
        await _dispatch_plugin_hook(
            state,
            "on_agent_start",
            agent_id=agent_id,
            session_key=session_key,
            response_id=response_id,
            metadata={"stream": stream_requested, "request_metadata": metadata},
        )
        selected_skills = await _select_skills(state, pack=pack, body=body)
        available_skills = _visible_enabled_skills(state, pack=pack)
        tool_context = _build_server_tool_context(pack=pack, body=body, selected_skills=selected_skills)
        context_fragments = await _build_context_provider_fragments(
            pack=pack,
            agent_id=agent_id,
            session_key=session_key,
            body=body,
            metadata=metadata,
            workspace_dir=state.workspace_dir,
            tool_context=tool_context,
            selected_skills=selected_skills,
        )
        session_once_fragments, prompt_context_fragments = split_session_once_context_fragments(context_fragments)
        prompt_envelope = build_prompt_envelope(
            pack=pack,
            selected_skills=selected_skills,
            available_skills=available_skills,
            tool_context=tool_context,
            model=body.get("model") if isinstance(body.get("model"), str) else None,
            context_fragments=prompt_context_fragments,
        )
        prompt_audit = prompt_envelope.audit_metadata()
        mcp_manager = None
        if pack.mcp_config is not None:
            mcp_manager = await state.mcp_managers.get_manager(
                agent_id=pack.agent_id,
                mcp_config=pack.mcp_config,
                credential_store=state.mcp_credentials,
            )
        try:
            model_provider = _model_provider_for_selection(model_selection)
        except ModelConfigError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        middleware_chain = _build_agent_middleware_chain(pack)
        enabled_skill_ids = [skill.stable_id for skill in selected_skills]
        requested_tool_names = extract_requested_tool_names(body.get("tools"))
        manifest_cache_key = build_manifest_cache_key(
            tenant_id=body.get("tenant_id") if isinstance(body.get("tenant_id"), str) else None,
            agent_id=agent_id,
            session_key=session_key,
            enabled_skills=enabled_skill_ids,
            requested_tool_names=requested_tool_names,
            context=tool_context.model_dump(exclude_none=True),
        )

        async def _resolve_manifest_cached() -> tuple[list[dict[str, Any]], int]:
            cached = await state.manifest_cache.get(manifest_cache_key)
            if cached is not None:
                return cached
            resolved = await resolve_manifest_with_mcp(
                tool_runtime=state.runtime,
                mcp_manager=mcp_manager,
                agent_id=agent_id,
                session_key=session_key,
                metadata=metadata,
                request_tools=body.get("tools"),
                tool_context=tool_context,
                enabled_skills=enabled_skill_ids or None,
                stage_event_sink=_stage_sink,
                stage_response_id=response_id,
            )
            await state.manifest_cache.put(manifest_cache_key, resolved)
            return resolved

        async def _refresh_manifest_cached() -> tuple[list[dict[str, Any]], int]:
            await state.manifest_cache.invalidate(manifest_cache_key)
            return await _resolve_manifest_cached()

        async def _stage_sink(event: Any) -> None:
            await state.events.append(
                response_id=event.response_id,
                event=event.type,
                data=event.model_dump_json(exclude_none=True, by_alias=True),
            )

        def _system_tool_executor_for_body(parent_body: dict[str, Any]):
            async def _execute_system_tool(tool_name: str, arguments_json: object) -> str:
                if tool_name != "task":
                    raise ValueError(f"unsupported system tool: {tool_name}")
                parent_depth = 0
                raw_depth = metadata.get("subagent_depth") if isinstance(metadata, dict) else None
                if isinstance(raw_depth, int):
                    parent_depth = max(0, raw_depth)
                return await SubAgentExecutor().execute_task(
                    catalog=state.catalog,
                    parent_pack=pack,
                    model_provider=model_provider,
                    tool_runtime=state.runtime,
                    session_key=session_key,
                    parent_body=parent_body,
                    arguments_json=arguments_json,
                    max_concurrent=pack.spec.runtime.subagent.max_concurrent,
                    max_depth=pack.spec.runtime.subagent.max_depth,
                    run_timeout_seconds=pack.spec.runtime.subagent.run_timeout_seconds,
                    default_context_mode=pack.spec.runtime.subagent.default_context_mode,
                    depth=parent_depth,
                    parent_response_id=response_id,
                    stage_event_sink=_stage_sink,
                )

            return _execute_system_tool

        prompt_context_event = AnyAgentPromptContextEvent.model_validate(
            {
                "response_id": response_id,
                "type": "anyagent.prompt.context",
                **prompt_audit.model_dump(exclude_none=True),
            }
        )
        await _stage_sink(prompt_context_event)
        rendered_fragments = prompt_envelope.rendered_fragments()
        await _stage_sink(
            AnyAgentPromptContextRenderedEvent(
                response_id=response_id,
                prompt_cache_key=prompt_envelope.prompt_cache_key,
                fragments=rendered_fragments,
                total_chars=sum(len(fragment.rendered_text) for fragment in rendered_fragments),
            )
        )
        await state.events.append(
            response_id=response_id,
            event="anyagent.response.request",
            data=json.dumps(
                {
                    "type": "anyagent.response.request",
                    "response_id": response_id,
                    "agent_id": agent_id,
                    "session_key": session_key,
                    "transcript_items": input_to_transcript_items(body.get("input")),
                },
                ensure_ascii=False,
            ),
        )

        if stream_requested:
            created_block = _build_created_sse_block(response_id=response_id, body=body)
            created_payload = {
                "type": "response.created",
                "response": build_minimal_openai_response_json(
                    response_id=response_id,
                    status="in_progress",
                    model=str(body.get("model") or "unknown"),
                    tools=list(body.get("tools") or []) if isinstance(body.get("tools"), list) else None,
                    tool_choice=body.get("tool_choice") if body.get("tool_choice") is not None else "auto",
                ),
            }
            await state.events.append(
                response_id=response_id,
                event="response.created",
                data=json.dumps(created_payload, ensure_ascii=False),
            )
            queue: asyncio.Queue[bytes | None] = asyncio.Queue()

            task = asyncio.create_task(
                run_stream_worker(
                    state=state,
                    response_id=response_id,
                    output_queue=queue,
                    session_partition_key_value=session_partition_key_value,
                    agent_id=agent_id,
                    session_key=session_key,
                    body=body,
                    session_once_fragments=session_once_fragments,
                    prompt_envelope=prompt_envelope,
                    prompt_audit=prompt_audit,
                    model_provider=model_provider,
                    idempotency_key=idempotency_key,
                    tool_context=tool_context,
                    selected_skills=selected_skills,
                    resolve_manifest_cached=_resolve_manifest_cached,
                    refresh_manifest_cached=_refresh_manifest_cached,
                    mcp_manager=mcp_manager,
                    stage_sink=_stage_sink,
                    system_tool_executor_for_body=_system_tool_executor_for_body,
                    middleware_chain=middleware_chain,
                ),
                name=f"anyagent-stream-{response_id}",
            )
            await state.runs.add(response_id=response_id, task=task)

            async def _iter_stream() -> AsyncIterator[bytes]:
                yield created_block
                while True:
                    try:
                        item = await asyncio.wait_for(queue.get(), timeout=0.25)
                    except asyncio.TimeoutError:
                        yield b": keepalive\n\n"
                        continue
                    if item is None:
                        break
                    yield item

            return StreamingResponse(_iter_stream(), status_code=200, media_type="text/event-stream")

        result_box: dict[str, Any] = {}

        task = asyncio.create_task(
            run_nonstream_worker(
                state=state,
                response_id=response_id,
                result_box=result_box,
                session_partition_key_value=session_partition_key_value,
                agent_id=agent_id,
                session_key=session_key,
                body=body,
                session_once_fragments=session_once_fragments,
                prompt_envelope=prompt_envelope,
                prompt_audit=prompt_audit,
                model_provider=model_provider,
                idempotency_key=idempotency_key,
                tool_context=tool_context,
                selected_skills=selected_skills,
                resolve_manifest_cached=_resolve_manifest_cached,
                refresh_manifest_cached=_refresh_manifest_cached,
                mcp_manager=mcp_manager,
                stage_sink=_stage_sink,
                system_tool_executor_for_body=_system_tool_executor_for_body,
                middleware_chain=middleware_chain,
            ),
            name=f"anyagent-run-{response_id}",
        )
        await state.runs.add(response_id=response_id, task=task)
        try:
            await task
        except asyncio.CancelledError:
            pass
        status_code = int(result_box.get("status_code", 500))
        payload = result_box.get("payload")
        return JSONResponse(status_code=status_code, content=payload)

    @router.get("/v1/responses/{response_id}")
    async def retrieve_response(req: Request, response_id: str, authorization: str | None = Header(default=None)) -> JSONResponse:
        state = req.app.state.anyagent
        _require_user_auth(state, authorization)
        run = await state.run_store.get(response_id)
        if run is None:
            raise HTTPException(status_code=404, detail=f"unknown response_id: {response_id}")
        return JSONResponse(optional_response_payload_from_run(run, response_id=response_id))

    @router.post("/v1/responses/{response_id}/cancel")
    async def cancel_response(req: Request, response_id: str, authorization: str | None = Header(default=None)) -> JSONResponse:
        state = req.app.state.anyagent
        _require_user_auth(state, authorization)
        run = await state.run_store.get(response_id)
        if run is None:
            raise HTTPException(status_code=404, detail=f"unknown response_id: {response_id}")
        await state.runtime.cancel_active_for_response(response_id)
        cancelled = await state.runs.cancel(response_id)
        if cancelled:
            await state.events.mark_cancel_requested(response_id=response_id)
            await state.run_store.mark_cancel_requested(response_id)
        latest_run = await state.run_store.get(response_id)
        if latest_run is None:
            latest_run = run
        return JSONResponse(optional_response_payload_from_run(latest_run, response_id=response_id))

    return router


async def run_stream_worker(
    *,
    state: Any,
    response_id: str,
    output_queue: asyncio.Queue[bytes | None],
    session_partition_key_value: str,
    agent_id: str,
    session_key: str,
    body: dict[str, Any],
    session_once_fragments: list[Any],
    prompt_envelope: Any,
    prompt_audit: PromptContextAudit,
    model_provider: Any,
    idempotency_key: str | None,
    tool_context: Any,
    selected_skills: list[Any],
    resolve_manifest_cached: Any,
    refresh_manifest_cached: Any,
    mcp_manager: Any,
    stage_sink: Any,
    system_tool_executor_for_body: Any,
    middleware_chain: Any,
) -> None:
    stream_terminal_status = "completed"
    try:
        async def _run_stream_serialized() -> None:
            nonlocal stream_terminal_status
            async with hold_session_lease(
                service=state.session_lock_service,
                session_partition_key=session_partition_key_value,
                owner_id=f"run:{response_id}",
                ttl_s=state.session_lease_ttl_s,
            ):
                session_ctx = await prepare_response_session_context(
                    session_store=state.session_store,
                    session_partition_key=session_partition_key_value,
                    agent_id=agent_id,
                    session_key=session_key,
                    body=body,
                )
                session_ctx = apply_session_once_context_to_session(
                    session_ctx=session_ctx,
                    fragments=session_once_fragments,
                )
                body2 = prompt_envelope.apply_to_body(body=session_ctx.effective_body)
                await stage_sink(
                    AnyAgentModelRequestEvent(
                        response_id=response_id,
                        applied_body=body2,
                        prompt_cache_key=prompt_envelope.prompt_cache_key,
                    )
                )
                decoder = SSEBlockDecoder()
                try:
                    async for chunk in run_tool_loop_stream_live(
                        model_provider=model_provider,
                        tool_runtime=state.runtime,
                        agent_id=agent_id,
                        session_key=session_key,
                        body=body2,
                        idempotency_key=idempotency_key,
                        canonical_response_id=response_id,
                        tool_context=tool_context,
                        selected_skills=selected_skills,
                        manifest_resolver=resolve_manifest_cached,
                        manifest_force_refresh=refresh_manifest_cached,
                        mcp_manager=mcp_manager,
                        stage_event_sink=stage_sink,
                        prompt_envelope_applied=True,
                        system_tool_executor=system_tool_executor_for_body(body2),
                        middleware_chain=middleware_chain,
                    ):
                        await _append_sse_chunk(
                            state,
                            response_id=response_id,
                            chunk=chunk,
                            decoder=decoder,
                            fallback_model=session_ctx.effective_body.get("model"),
                            session_partition_key_value=session_partition_key_value,
                            agent_id=agent_id,
                            session_key=session_key,
                            previous_snapshot=session_ctx.previous_snapshot,
                            previous_snapshot_version=session_ctx.previous_snapshot_version,
                            runtime_config=session_ctx.effective_runtime_config,
                            request_transcript_items=session_ctx.request_transcript_items,
                            prompt_audit=prompt_audit,
                        )
                        await output_queue.put(chunk)
                except asyncio.CancelledError:
                    stream_terminal_status = "cancelled"
                    _emit_server_response_event(
                        "server.response.stream.cancelled",
                        response_id=response_id,
                        agent_id=agent_id,
                        session_key=session_key,
                        stream=True,
                        idempotency_key_present=idempotency_key is not None,
                        status="cancelled",
                    )
                    payload = build_minimal_openai_response_json(
                        response_id=response_id,
                        status="cancelled",
                        model=str(session_ctx.effective_body.get("model") or "unknown"),
                    )
                    completed_block = _build_completed_sse_block(payload)
                    done_block = encode_sse_block(event=None, data="[DONE]", id=None)
                    await _append_sse_chunk(
                        state,
                        response_id=response_id,
                        chunk=completed_block,
                        decoder=decoder,
                        fallback_model=session_ctx.effective_body.get("model"),
                        session_partition_key_value=session_partition_key_value,
                        agent_id=agent_id,
                        session_key=session_key,
                        previous_snapshot=session_ctx.previous_snapshot,
                        previous_snapshot_version=session_ctx.previous_snapshot_version,
                        runtime_config=session_ctx.effective_runtime_config,
                        request_transcript_items=session_ctx.request_transcript_items,
                        prompt_audit=prompt_audit,
                    )
                    await _append_sse_chunk(
                        state,
                        response_id=response_id,
                        chunk=done_block,
                        decoder=decoder,
                        fallback_model=session_ctx.effective_body.get("model"),
                        session_partition_key_value=session_partition_key_value,
                        agent_id=agent_id,
                        session_key=session_key,
                        previous_snapshot=session_ctx.previous_snapshot,
                        previous_snapshot_version=session_ctx.previous_snapshot_version,
                        runtime_config=session_ctx.effective_runtime_config,
                        request_transcript_items=session_ctx.request_transcript_items,
                        prompt_audit=prompt_audit,
                    )
                    await output_queue.put(completed_block)
                    await output_queue.put(done_block)
                    raise
                except Exception as e:  # noqa: BLE001
                    stream_terminal_status = "failed"
                    _emit_server_response_event(
                        "server.response.stream.failed",
                        level="error",
                        response_id=response_id,
                        agent_id=agent_id,
                        session_key=session_key,
                        stream=True,
                        idempotency_key_present=idempotency_key is not None,
                        status="failed",
                        error_type=type(e).__name__,
                    )
                    payload = build_minimal_openai_response_json(
                        response_id=response_id,
                        status="failed",
                        model=str(session_ctx.effective_body.get("model") or "unknown"),
                    )
                    payload["error"] = {"type": "server_error", "message": _safe_error_message(e)}
                    completed_block = _build_completed_sse_block(payload)
                    done_block = encode_sse_block(event=None, data="[DONE]", id=None)
                    await _append_sse_chunk(
                        state,
                        response_id=response_id,
                        chunk=completed_block,
                        decoder=decoder,
                        fallback_model=session_ctx.effective_body.get("model"),
                        session_partition_key_value=session_partition_key_value,
                        agent_id=agent_id,
                        session_key=session_key,
                        previous_snapshot=session_ctx.previous_snapshot,
                        previous_snapshot_version=session_ctx.previous_snapshot_version,
                        runtime_config=session_ctx.effective_runtime_config,
                        request_transcript_items=session_ctx.request_transcript_items,
                        prompt_audit=prompt_audit,
                    )
                    await _append_sse_chunk(
                        state,
                        response_id=response_id,
                        chunk=done_block,
                        decoder=decoder,
                        fallback_model=session_ctx.effective_body.get("model"),
                        session_partition_key_value=session_partition_key_value,
                        agent_id=agent_id,
                        session_key=session_key,
                        previous_snapshot=session_ctx.previous_snapshot,
                        previous_snapshot_version=session_ctx.previous_snapshot_version,
                        runtime_config=session_ctx.effective_runtime_config,
                        request_transcript_items=session_ctx.request_transcript_items,
                        prompt_audit=prompt_audit,
                    )
                    await output_queue.put(completed_block)
                    await output_queue.put(done_block)

        await state.session_sequencer.run(session_partition_key_value, _run_stream_serialized)
        if stream_terminal_status == "completed":
            _emit_server_response_event(
                "server.response.stream.completed",
                response_id=response_id,
                agent_id=agent_id,
                session_key=session_key,
                stream=True,
                idempotency_key_present=idempotency_key is not None,
                status="completed",
            )
    finally:
        await _dispatch_plugin_hook(
            state,
            "on_agent_end",
            agent_id=agent_id,
            session_key=session_key,
            response_id=response_id,
            metadata={"stream": True, "status": stream_terminal_status},
        )
        await output_queue.put(None)
        await state.runs.remove(response_id)


async def run_nonstream_worker(
    *,
    state: Any,
    response_id: str,
    result_box: dict[str, Any],
    session_partition_key_value: str,
    agent_id: str,
    session_key: str,
    body: dict[str, Any],
    session_once_fragments: list[Any],
    prompt_envelope: Any,
    prompt_audit: PromptContextAudit,
    model_provider: Any,
    idempotency_key: str | None,
    tool_context: Any,
    selected_skills: list[Any],
    resolve_manifest_cached: Any,
    refresh_manifest_cached: Any,
    mcp_manager: Any,
    stage_sink: Any,
    system_tool_executor_for_body: Any,
    middleware_chain: Any,
) -> None:
    try:
        async def _run_nonstream_serialized() -> tuple[int, Any]:
            async with hold_session_lease(
                service=state.session_lock_service,
                session_partition_key=session_partition_key_value,
                owner_id=f"run:{response_id}",
                ttl_s=state.session_lease_ttl_s,
            ):
                session_ctx = await prepare_response_session_context(
                    session_store=state.session_store,
                    session_partition_key=session_partition_key_value,
                    agent_id=agent_id,
                    session_key=session_key,
                    body=body,
                )
                session_ctx = apply_session_once_context_to_session(
                    session_ctx=session_ctx,
                    fragments=session_once_fragments,
                )
                body2 = prompt_envelope.apply_to_body(body=session_ctx.effective_body)
                await stage_sink(
                    AnyAgentModelRequestEvent(
                        response_id=response_id,
                        applied_body=body2,
                        prompt_cache_key=prompt_envelope.prompt_cache_key,
                    )
                )

                async def _finalize_nonstream_terminal(
                    *,
                    payload: dict[str, Any],
                    response_status_code: int,
                    effective_status: str | None = None,
                    error_json: dict[str, Any] | None = None,
                ) -> tuple[int, Any]:
                    append_event = build_response_event_appender(
                        response_id=response_id,
                        writer=lambda rid, event, data: state.events.append(response_id=rid, event=event, data=data),
                    )

                    async def _mark_event_final(final_state) -> None:
                        err_model = None
                        if isinstance(final_state.error_json, dict):
                            try:
                                err_model = AnyAgentResponseError.model_validate(final_state.error_json)
                            except Exception:  # noqa: BLE001
                                err_model = None
                        await state.events.mark_final(
                            response_id=response_id,
                            run_status=final_state.run_status,
                            effective_run_status=final_state.effective_status,
                            response_json=final_state.response_json,
                            error=err_model,
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
                        await _update_session_snapshot(
                            state=state,
                            session_partition_key_value=session_partition_key_value,
                            agent_id=agent_id,
                            session_key=session_key,
                            previous_snapshot=session_ctx.previous_snapshot,
                            previous_snapshot_version=session_ctx.previous_snapshot_version,
                            runtime_config=session_ctx.effective_runtime_config,
                            request_transcript_items=session_ctx.request_transcript_items,
                            response_id=final_state.response_id or response_id,
                            effective_status=final_state.effective_status,
                            response_json=final_state.response_json,
                            prompt_audit=prompt_audit,
                        )

                    finalize_terminal = build_nonstream_response_finalizer(
                        response_id=response_id,
                        append_event=append_event,
                        mark_event_final=_mark_event_final,
                        persist_run_final=_persist_run_final,
                        advance_session=_advance_session,
                    )
                    final_state = await finalize_terminal(
                        response_json=payload,
                        effective_status=effective_status,
                        error_json=error_json,
                    )
                    return response_status_code, final_state.response_json if final_state.response_json is not None else payload

                try:
                    status_code, payload = await run_tool_loop_nonstream(
                        model_provider=model_provider,
                        tool_runtime=state.runtime,
                        agent_id=agent_id,
                        session_key=session_key,
                        body=body2,
                        idempotency_key=idempotency_key,
                        canonical_response_id=response_id,
                        tool_context=tool_context,
                        selected_skills=selected_skills,
                        manifest_resolver=resolve_manifest_cached,
                        manifest_force_refresh=refresh_manifest_cached,
                        mcp_manager=mcp_manager,
                        stage_event_sink=stage_sink,
                        prompt_envelope_applied=True,
                        system_tool_executor=system_tool_executor_for_body(body2),
                        middleware_chain=middleware_chain,
                    )
                except asyncio.CancelledError:
                    payload = build_minimal_openai_response_json(
                        response_id=response_id,
                        status="cancelled",
                        model=str(session_ctx.effective_body.get("model") or "unknown"),
                    )
                    return await _finalize_nonstream_terminal(
                        payload=payload,
                        response_status_code=200,
                        effective_status="cancelled",
                    )
                except Exception as e:  # noqa: BLE001
                    payload = build_minimal_openai_response_json(
                        response_id=response_id,
                        status="failed",
                        model=str(session_ctx.effective_body.get("model") or "unknown"),
                    )
                    payload["error"] = {"type": "server_error", "message": _safe_error_message(e)}
                    return await _finalize_nonstream_terminal(
                        payload=payload,
                        response_status_code=500,
                        effective_status="failed",
                        error_json={"type": "server_error", "message": _safe_error_message(e)},
                    )

                if status_code >= 400 or not isinstance(payload, dict) or not isinstance(payload.get("id"), str):
                    # Provider/upstream failures (e.g. 429 rate limits) return an
                    # error body without a response ``id``. Finalize the run as
                    # failed so it does not linger in ``in_progress`` and the
                    # error_json is persisted, mirroring the exception path.
                    if status_code >= 400 and isinstance(payload, dict) and not isinstance(payload.get("id"), str):
                        error_json = payload.get("error")
                        return await _finalize_nonstream_terminal(
                            payload=payload,
                            response_status_code=status_code,
                            effective_status="failed",
                            error_json=error_json if isinstance(error_json, dict) else None,
                        )
                    return status_code, payload
                return await _finalize_nonstream_terminal(
                    payload=payload,
                    response_status_code=status_code,
                )

        status_code, payload = await state.session_sequencer.run(
            session_partition_key_value,
            _run_nonstream_serialized,
        )
        result_box["status_code"] = status_code
        result_box["payload"] = payload
        payload_status = payload.get("status") if isinstance(payload, dict) and isinstance(payload.get("status"), str) else None
        _emit_server_response_event(
            "server.response.nonstream.completed" if status_code < 400 else "server.response.nonstream.failed",
            level="info" if status_code < 400 else "error",
            response_id=response_id,
            agent_id=agent_id,
            session_key=session_key,
            stream=False,
            idempotency_key_present=idempotency_key is not None,
            status_code=status_code,
            status=payload_status,
        )
    finally:
        status_code = int(result_box.get("status_code", 500))
        payload = result_box.get("payload")
        payload_status = payload.get("status") if isinstance(payload, dict) and isinstance(payload.get("status"), str) else None
        if payload_status is None:
            payload_status = "completed" if status_code < 400 else "failed"
        await _dispatch_plugin_hook(
            state,
            "on_agent_end",
            agent_id=agent_id,
            session_key=session_key,
            response_id=response_id,
            metadata={"stream": False, "status_code": status_code, "status": payload_status},
        )
        await state.runs.remove(response_id)


def _emit_server_response_event(
    event: str,
    *,
    level: ObservabilityLevel = "info",
    response_id: str | None = None,
    agent_id: str | None = None,
    session_key: str | None = None,
    stream: bool | None = None,
    idempotency_key_present: bool | None = None,
    status_code: int | None = None,
    status: str | None = None,
    error_type: str | None = None,
) -> None:
    payload: dict[str, Any] = {
        "response_id": response_id,
        "agent_id": agent_id,
        "session_key": session_key,
        "stream": stream,
        "idempotency_key_present": idempotency_key_present,
        "status_code": status_code,
        "status": status,
        "error_type": error_type,
    }
    emit_observability_event(
        event,
        category="server",
        level=level,
        payload={key: value for key, value in payload.items() if value is not None},
    )


def _model_provider_for_selection(selection) -> Any:
    if selection.provider_kind == "openai" and not selection.uses_workspace_provider:
        return get_default_model_provider()
    return model_provider_for_selection(selection)


def _resolve_agent_id(*, body: dict[str, Any], x_agent_id: str | None) -> str:
    metadata = body.get("metadata")
    return resolve_agent_id(
        metadata=metadata if isinstance(metadata, dict) else None,
        x_agent_id=x_agent_id,
        model=body.get("model"),
    )


def _resolve_session_key(*, body: dict[str, Any]) -> str:
    metadata = body.get("metadata")
    return resolve_session_key(
        metadata=metadata if isinstance(metadata, dict) else None,
        user=body.get("user"),
    )
