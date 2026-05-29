from __future__ import annotations

import logging
from uuid import uuid4

from fastapi import APIRouter, Request
from fastapi.responses import Response

from anyagent.agent_packs import AgentCatalog
from anyagent.agent_runtime import run_tool_loop_nonstream, run_tool_loop_stream_live
from anyagent.tool_runtime import fetch_manifest_tools

from .idempotency import begin_distributed_response_run
from .request_context import ResponsesRequestContextError, prepare_responses_request_context
from .request_validation import ResponsesRequestValidationError, ensure_metadata_object, ensure_request_body_object
from .response_execution import execute_distributed_nonstream_response, execute_distributed_stream_response
from .response_persistence import create_distributed_response_persistence_context
from .response_tooling import ResponseToolingContextError, prepare_response_tooling_context
from .responses_optional import check_bearer_api_key, openai_error_response
from .session_context import prepare_response_session_context
from .session_serialization import DistributedSessionSerializationConfig, run_distributed_response_with_session_serialization

logger = logging.getLogger("anyagent.server.distributed_responses")


def create_distributed_responses_router(
    *,
    api_key: str,
    enable_keyed_serialization: bool = True,
    fetch_manifest_tools_fn=fetch_manifest_tools,
    run_tool_loop_nonstream_fn=run_tool_loop_nonstream,
    run_tool_loop_stream_live_fn=run_tool_loop_stream_live,
) -> APIRouter:
    router = APIRouter()

    @router.post("/v1/responses")
    async def v1_responses(request: Request) -> Response:
        auth_err = await check_bearer_api_key(request, api_key=api_key)
        if auth_err is not None:
            return auth_err

        try:
            body_raw = await request.json()
        except Exception:
            return openai_error_response(400, message="Invalid JSON body", type_="invalid_request_error")

        try:
            body = ensure_request_body_object(body_raw, message="Request body must be a JSON object")
            metadata = ensure_metadata_object(body, message="metadata must be an object")
        except ResponsesRequestValidationError as exc:
            return openai_error_response(400, message=str(exc), type_="invalid_request_error")

        catalog: AgentCatalog = request.app.state.agent_catalog
        try:
            request_ctx = prepare_responses_request_context(
                body=body,
                metadata=metadata,
                headers=request.headers,
                catalog=catalog,
                ephemeral_session_key_factory=lambda: f"ephemeral::{uuid4().hex}",
            )
        except ResponsesRequestContextError as exc:
            return openai_error_response(
                exc.status_code,
                message=exc.message,
                type_=exc.type,
                code=exc.code,
                retryable=exc.retryable,
            )

        body = request_ctx.body
        metadata = request_ctx.metadata
        agent_id = request_ctx.agent_id
        pack = request_ctx.pack
        session_key = request_ctx.session_key
        session_partition_key = request_ctx.session_partition_key
        stream = request_ctx.stream
        thread_id = request_ctx.thread_id
        thread_depth = request_ctx.thread_depth
        idempotency_key = request_ctx.idempotency_key

        logger.info(
            "incoming /v1/responses",
            extra={
                "agent_id": agent_id,
                "session_key": session_key,
                "session_partition_key": session_partition_key,
                "thread_id": thread_id,
                "thread_depth": thread_depth,
                "stream": stream,
                "idempotency_key": request.headers.get("idempotency-key"),
            },
        )

        storage = request.app.state.storage
        run_gate = await begin_distributed_response_run(
            idempotency_key=idempotency_key,
            stream=stream,
            session_partition_key=session_partition_key,
            storage=storage,
            new_response_id_factory=lambda: f"resp_anyagent_{uuid4().hex}",
        )
        idem_created = run_gate.created
        idem_response_id = run_gate.response_id
        if run_gate.response is not None:
            return run_gate.response

        session_ctx = await prepare_response_session_context(
            session_store=storage.session_store,
            session_partition_key=session_partition_key,
            agent_id=agent_id,
            session_key=session_key,
            body=body,
        )
        body = session_ctx.effective_body

        def _warn_best_effort(message: str) -> None:
            logger.warning(
                message,
                extra={
                    "agent_id": agent_id,
                    "session_partition_key": session_partition_key,
                },
            )

        try:
            tooling_ctx = await prepare_response_tooling_context(
                body=body,
                metadata=metadata,
                pack=pack,
                agent_id=agent_id,
                session_key=session_key,
                workspace_dir=request.app.state.workspace_dir,
                agent_skills=request.app.state.agent_skills,
                global_skills=request.app.state.global_skills,
                manifest_cache=request.app.state.manifest_cache,
                tool_runtime=request.app.state.tool_runtime_client,
                mcp_registry=request.app.state.mcp_registry,
                mcp_credential_store=request.app.state.mcp_credential_store,
                multiagent=request.app.state.multiagent,
                fetch_manifest_tools_fn=fetch_manifest_tools_fn,
            )
        except ResponseToolingContextError as exc:
            return openai_error_response(exc.status_code, message=exc.message, type_=exc.type)

        body = tooling_ctx.body
        selected_skills = tooling_ctx.selected_skills
        skill_decisions = tooling_ctx.skill_decisions
        tool_context = tooling_ctx.tool_context
        mcp_manager = tooling_ctx.mcp_manager
        prompt_audit = tooling_ctx.prompt_audit
        prompt_rendered_fragments = tooling_ctx.prompt_envelope.rendered_fragments()
        manifest_for_session = tooling_ctx.manifest_resolver
        refresh_manifest_for_session = tooling_ctx.manifest_force_refresh

        persistence_ctx = create_distributed_response_persistence_context(
            storage=storage,
            session_partition_key=session_partition_key,
            agent_id=agent_id,
            session_key=session_key,
            previous_snapshot=session_ctx.previous_snapshot,
            previous_snapshot_version=session_ctx.previous_snapshot_version,
            runtime_config=session_ctx.effective_runtime_config,
            request_transcript_items=session_ctx.request_transcript_items,
            prompt_audit=prompt_audit,
            prompt_rendered_fragments=prompt_rendered_fragments,
            warn=_warn_best_effort,
        )
        if skill_decisions:
            logger.info(
                "skills.selected",
                extra={
                    "agent_id": agent_id,
                    "session_partition_key": session_partition_key,
                    "selected_skills": [skill.frontmatter.name for skill in selected_skills],
                    "decisions": [decision.__dict__ for decision in skill_decisions],
                    "injection_warnings": [],
                },
            )

        async def do_work() -> Response:
            if stream:
                return await execute_distributed_stream_response(
                    model_provider=request.app.state.openai_provider,
                    tool_runtime=request.app.state.tool_runtime_client,
                    agent_id=agent_id,
                    session_key=session_key,
                    body=body,
                    idempotency_key=idempotency_key,
                    idem_created=idem_created,
                    idem_response_id=idem_response_id,
                    storage=storage,
                    storage_tasks=request.app.state.storage_tasks,
                    session_partition_key=session_partition_key,
                    tool_context=tool_context,
                    manifest_resolver=manifest_for_session,
                    manifest_force_refresh=refresh_manifest_for_session,
                    mcp_manager=mcp_manager,
                    stage_event_sink=persistence_ctx.stage_sink_best_effort,
                    append_prompt_context_event=persistence_ctx.append_prompt_context_event_best_effort,
                    append_prompt_context_rendered_event=persistence_ctx.append_prompt_context_rendered_event_best_effort,
                    internal_event_writer=persistence_ctx.append_internal_event_best_effort,
                    run_final_persister_builder=persistence_ctx.build_run_final_persister,
                    new_response_id_factory=lambda: f"resp_anyagent_{uuid4().hex}",
                    is_disconnected=request.is_disconnected,
                    run_tool_loop_stream_live_fn=run_tool_loop_stream_live_fn,
                )

            return await execute_distributed_nonstream_response(
                model_provider=request.app.state.openai_provider,
                tool_runtime=request.app.state.tool_runtime_client,
                agent_id=agent_id,
                session_key=session_key,
                body=body,
                idempotency_key=idempotency_key,
                idem_created=idem_created,
                idem_response_id=idem_response_id,
                tool_context=tool_context,
                manifest_resolver=manifest_for_session,
                manifest_force_refresh=refresh_manifest_for_session,
                mcp_manager=mcp_manager,
                stage_event_sink=persistence_ctx.stage_sink_best_effort,
                append_prompt_context_event=persistence_ctx.append_prompt_context_event_best_effort,
                append_prompt_context_rendered_event=persistence_ctx.append_prompt_context_rendered_event_best_effort,
                finalize_nonstream_persisted=persistence_ctx.finalize_nonstream_persisted,
                advance_nonstream_session_only=persistence_ctx.advance_nonstream_session_only,
                new_response_id_factory=lambda: f"resp_anyagent_{uuid4().hex}",
                run_tool_loop_nonstream_fn=run_tool_loop_nonstream_fn,
            )

        return await run_distributed_response_with_session_serialization(
            storage=storage,
            session_partition_key=session_partition_key,
            owner=idem_response_id if isinstance(idem_response_id, str) and idem_response_id else f"lease_{uuid4().hex}",
            stream=stream,
            idempotency_key=idempotency_key,
            idem_created=idem_created,
            idem_response_id=idem_response_id,
            sequencer=request.app.state.sequencer,
            fn=do_work,
            config=DistributedSessionSerializationConfig(enable_keyed_serialization=enable_keyed_serialization),
        )

    return router
