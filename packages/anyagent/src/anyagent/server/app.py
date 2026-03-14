import asyncio
import json
import uuid
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, AsyncIterator

from fastapi import FastAPI, Header, HTTPException, Request
from fastapi.responses import JSONResponse, StreamingResponse

from anyagent.agent_packs import AgentCatalog, AgentPack, load_agent_catalog
from anyagent.agent_runtime import build_default_environment_context_values, build_prompt_envelope, persist_session_snapshot
from anyagent.agent_runtime.tool_loop import resolve_manifest_with_mcp, run_tool_loop_nonstream, run_tool_loop_stream_live
from anyagent.agent_runtime.model_providers import get_default_model_provider
from anyagent.gateway.sequencer import KeyedSequencer
from anyagent.gateway.session import session_partition_key
from anyagent.mcp.manager import MCPManagerRegistry
from anyagent.protocol.credential_vault import AdminCredentialSetRequest
from anyagent.protocol.agent_api_internal import InternalPromptBundlePreviewResponse
from anyagent.protocol.openai_responses import (
    AnyAgentFunctionToolParam,
    build_minimal_openai_response_json,
    serialize_completed_response_event_data,
)
from anyagent.protocol.prompt_context import PromptContextAudit
from anyagent.protocol.responses_optional import AnyAgentResponseError
from anyagent.protocol.sse import SSEBlockDecoder, encode_sse_block
from anyagent.protocol.stage_events import AnyAgentPromptContextEvent
from anyagent.protocol.tool_runtime import PolicyHint, ToolContext
from anyagent.server.finalization import build_nonstream_response_finalizer
from anyagent.server.idempotency import begin_or_replay_response_run
from anyagent.server.lock_service import SessionLockService, build_session_lock_service, hold_session_lease
from anyagent.server.manifest_cache import ManifestCache, build_manifest_cache_key, extract_requested_tool_names
from anyagent.server.request_validation import (
    ResponsesRequestValidationError,
    ensure_metadata_object,
    ensure_request_body_object,
    parse_function_tools,
)
from anyagent.server.responses_optional import optional_response_payload_from_run
from anyagent.server.session_context import prepare_response_session_context
from anyagent.server.streaming import (
    append_sse_chunk as append_streaming_sse_chunk,
    build_persisted_sse_block_handler,
    build_response_event_appender,
    build_external_response_stream_response,
    persist_sse_run as persist_streaming_sse_run,
)
from anyagent.server.runs import RunRegistry
from anyagent.server.runtime import InProcessToolRuntimeService
from anyagent.server.sandbox import SandboxManager
from anyagent.server.security import InMemoryCredentialStore
from anyagent.server.settings import ResolvedServerStorageSettings, ServerSettings
from anyagent.server.storage_backends import (
    EventStore,
    RunStore,
    ServerStorageBundle,
    SessionStore,
    build_server_storage_bundle,
)
from anyagent.storage import build_storage_capability_matrix, resolve_nonstream_replay_payload
from anyagent.storage.settings import StorageSettings
from anyagent.skills import (
    SkillEnablement,
    apply_skills_permissions_to_tool_context,
    extract_user_texts_from_responses_request,
    resolve_disabled_skill_stable_ids,
    select_skills,
)


@dataclass(slots=True)
class AnyAgentServerApp:
    workspace_dir: Path
    catalog: AgentCatalog
    resolved_storage: ResolvedServerStorageSettings
    storage_settings: StorageSettings
    events: EventStore
    credentials: InMemoryCredentialStore
    sandbox_manager: SandboxManager
    runtime: InProcessToolRuntimeService
    mcp_managers: MCPManagerRegistry
    runs: RunRegistry
    manifest_cache: ManifestCache
    run_store: RunStore
    session_store: SessionStore
    session_sequencer: KeyedSequencer
    session_lock_service: SessionLockService
    session_lease_ttl_s: float
    storage_resources: list[object] = field(default_factory=list)
    api_key: str | None = None
    admin_api_key: str | None = None

    def require_pack(self, agent_id: str, *, external: bool) -> AgentPack:
        pack = self.catalog.get(agent_id)
        if pack is None:
            raise HTTPException(status_code=404, detail=f"unknown agent_id: {agent_id}")
        if external and not pack.spec.exposed:
            raise HTTPException(status_code=403, detail=f"agent is not exposed: {agent_id}")
        return pack

def create_app(
    *,
    workspace_dir: str | Path,
    api_key: str | None = None,
    admin_api_key: str | None = None,
    storage_mode: str | None = None,
    event_store_backend: str | None = None,
    run_store_backend: str | None = None,
    session_store_backend: str | None = None,
    sandbox_root_dir: str | Path | None = None,
    session_lock_backend: str | None = None,
    session_lease_ttl_s: float | None = None,
) -> FastAPI:
    server_settings = ServerSettings()
    resolved_storage = server_settings.resolve(
        storage_mode=storage_mode if isinstance(storage_mode, str) else None,
        event_store_backend=event_store_backend if isinstance(event_store_backend, str) else None,
        run_store_backend=run_store_backend if isinstance(run_store_backend, str) else None,
        session_store_backend=session_store_backend if isinstance(session_store_backend, str) else None,
        session_lock_backend=session_lock_backend if isinstance(session_lock_backend, str) else None,
        session_lease_ttl_s=session_lease_ttl_s,
    )
    workspace = Path(workspace_dir).expanduser().resolve()
    catalog = load_agent_catalog(workspace_dir=workspace)
    main_pack = catalog.get("main")
    if main_pack is None or not main_pack.spec.exposed:
        raise RuntimeError("workspace must define exposed agent_id=main")
    unsupported_opensandbox = [
        pack.agent_id for pack in catalog.packs.values() if pack.spec.sandbox.mode == "opensandbox"
    ]
    if unsupported_opensandbox:
        raise RuntimeError(
            "opensandbox backend is not implemented in this repository build: "
            + ",".join(sorted(unsupported_opensandbox))
        )

    sandbox_manager = SandboxManager(root_dir=sandbox_root_dir)
    credential_store = InMemoryCredentialStore()
    storage_bundle: ServerStorageBundle = build_server_storage_bundle(
        event_store_backend=resolved_storage.event_store_backend,
        run_store_backend=resolved_storage.run_store_backend,
        session_store_backend=resolved_storage.session_store_backend,
    )
    state = AnyAgentServerApp(
        workspace_dir=workspace,
        catalog=catalog,
        resolved_storage=resolved_storage,
        storage_settings=StorageSettings(),
        events=storage_bundle.event_store,
        credentials=credential_store,
        sandbox_manager=sandbox_manager,
        runtime=InProcessToolRuntimeService(
            workspace_dir=str(workspace),
            catalog=catalog,
            sandbox_manager=sandbox_manager,
            credential_store=credential_store,
        ),
        mcp_managers=MCPManagerRegistry(),
        runs=RunRegistry(),
        manifest_cache=ManifestCache(ttl_seconds=2.0),
        run_store=storage_bundle.run_store,
        session_store=storage_bundle.session_store,
        session_sequencer=KeyedSequencer(),
        session_lock_service=build_session_lock_service(
            backend=resolved_storage.session_lock_backend,
        ),
        session_lease_ttl_s=resolved_storage.session_lease_ttl_s,
        storage_resources=storage_bundle.resources,
        api_key=api_key.strip() if isinstance(api_key, str) and api_key.strip() else None,
        admin_api_key=admin_api_key.strip() if isinstance(admin_api_key, str) and admin_api_key.strip() else None,
    )
    @asynccontextmanager
    async def _lifespan(_app: FastAPI):
        _app.state.anyagent = state
        try:
            yield
        finally:
            await state.mcp_managers.cleanup_all()
            for resource in state.storage_resources:
                closer = getattr(resource, "dispose", None) or getattr(resource, "aclose", None) or getattr(resource, "close", None)
                if callable(closer):
                    result = closer()
                    if asyncio.iscoroutine(result):
                        await result

    app = FastAPI(title="anyagent", version="0.1.0", lifespan=_lifespan)
    app.state.anyagent = state

    @app.get("/healthz")
    async def healthz() -> dict[str, Any]:
        return {"ok": True, "workspace": str(state.workspace_dir), "agent_ids": sorted(state.catalog.packs.keys())}

    @app.post("/admin/credentials")
    async def admin_set_credential(
        req: Request,
        authorization: str | None = Header(default=None),
    ) -> JSONResponse:
        _require_admin_auth(state, authorization)
        body = await req.json()
        model = AdminCredentialSetRequest.model_validate(body)
        ref = await state.credentials.set(model)
        return JSONResponse(ref.model_dump(exclude_none=True))

    @app.get("/admin/credentials")
    async def admin_list_credentials(authorization: str | None = Header(default=None)) -> JSONResponse:
        _require_admin_auth(state, authorization)
        resp = await state.credentials.list()
        return JSONResponse(resp.model_dump(exclude_none=True))

    @app.get("/admin/storage/health")
    async def admin_storage_health(authorization: str | None = Header(default=None)) -> JSONResponse:
        _require_admin_auth(state, authorization)
        payload = await _build_storage_health_payload(state)
        return JSONResponse(payload)

    @app.delete("/admin/credentials/{credential_id}")
    async def admin_delete_credential(credential_id: str, authorization: str | None = Header(default=None)) -> JSONResponse:
        _require_admin_auth(state, authorization)
        resp = await state.credentials.delete(credential_id)
        return JSONResponse(resp)

    @app.get("/internal/skills/list")
    async def internal_skills_list(agent_id: str = "main", authorization: str | None = Header(default=None)) -> JSONResponse:
        _require_user_auth(state, authorization)
        resp = await state.runtime.list_skills(agent_id=agent_id)
        return JSONResponse(resp.model_dump(exclude_none=True))

    @app.post("/internal/tools/manifest")
    async def internal_tools_manifest(req: Request, authorization: str | None = Header(default=None)) -> JSONResponse:
        _require_internal_auth(state, authorization)
        from anyagent.protocol.tool_runtime import ManifestRequest

        payload = ManifestRequest.model_validate(await req.json())
        resp = await state.runtime.manifest(payload)
        return JSONResponse(resp.model_dump(exclude_none=True, by_alias=True))

    @app.post("/internal/tools/execute")
    async def internal_tools_execute(req: Request, authorization: str | None = Header(default=None)) -> JSONResponse:
        _require_internal_auth(state, authorization)
        from anyagent.protocol.tool_runtime import ExecuteRequest

        payload = ExecuteRequest.model_validate(await req.json())
        resp = await state.runtime.execute(payload)
        status_code = 200
        if getattr(resp, "status", None) == "error" and getattr(resp, "error", None) is not None:
            if resp.error.code == "toolset_version_mismatch":
                status_code = 409
        return JSONResponse(resp.model_dump(exclude_none=True), status_code=status_code)

    @app.post("/internal/tools/cancel")
    async def internal_tools_cancel(req: Request, authorization: str | None = Header(default=None)) -> JSONResponse:
        _require_internal_auth(state, authorization)
        from anyagent.protocol.tool_runtime import CancelRequest

        payload = CancelRequest.model_validate(await req.json())
        resp = await state.runtime.cancel(payload)
        return JSONResponse(resp.model_dump(exclude_none=True))

    @app.get("/internal/events/list")
    async def internal_events_list(
        response_id: str,
        last_seq: int = 0,
        limit: int = 200,
        authorization: str | None = Header(default=None),
    ) -> JSONResponse:
        _require_user_auth(state, authorization)
        resp = await state.events.list_events(response_id=response_id, last_seq=last_seq, limit=limit)
        return JSONResponse(resp.model_dump(exclude_none=True))

    @app.get("/internal/events/stream")
    async def internal_events_stream(
        response_id: str,
        last_seq: int = 0,
        authorization: str | None = Header(default=None),
    ) -> StreamingResponse:
        _require_user_auth(state, authorization)

        async def _iter() -> AsyncIterator[bytes]:
            async for item in state.events.stream_events(response_id=response_id, last_seq=last_seq):
                yield encode_sse_block(event=item.event, data=item.data, id=str(item.seq))

        return StreamingResponse(_iter(), media_type="text/event-stream")

    @app.post("/internal/prompt/bundle")
    async def internal_prompt_bundle_preview(
        req: Request,
        authorization: str | None = Header(default=None),
        x_agent_id: str | None = Header(default=None),
    ) -> JSONResponse:
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

        agent_id = _resolve_agent_id(body=body, x_agent_id=x_agent_id)
        pack = state.require_pack(agent_id, external=True)
        session_key = _resolve_session_key(body=body)
        selected_skills = await _select_skills(state, pack=pack, body=body)
        tool_context = _build_server_tool_context(pack=pack, body=body, selected_skills=selected_skills)
        mcp_manager = None
        if pack.mcp_config is not None:
            mcp_manager = await state.mcp_managers.get_manager(
                agent_id=pack.agent_id,
                mcp_config=pack.mcp_config,
                credential_store=state.credentials,
            )
        manifest_tools, _toolset_version = await resolve_manifest_with_mcp(
            tool_runtime=state.runtime,
            mcp_manager=mcp_manager,
            agent_id=agent_id,
            session_key=session_key,
            metadata=metadata,
            request_tools=body.get("tools"),
            tool_context=tool_context,
            enabled_skills=[skill.stable_id for skill in selected_skills] or None,
        )
        prompt_envelope = build_prompt_envelope(
            pack=pack,
            selected_skills=selected_skills,
            tool_context=tool_context,
            model=body.get("model") if isinstance(body.get("model"), str) else None,
            environment_values=_build_prompt_environment_values(state=state, pack=pack),
        )
        session_ctx = await prepare_response_session_context(
            session_store=state.session_store,
            session_partition_key=session_partition_key(agent_id=agent_id, session_key=session_key),
            agent_id=agent_id,
            session_key=session_key,
            body=body,
        )
        effective_body = session_ctx.effective_body
        applied_body = prompt_envelope.apply_to_body(body=effective_body)
        payload = InternalPromptBundlePreviewResponse(
            agent_id=agent_id,
            session_key=session_key,
            model=body.get("model") if isinstance(body.get("model"), str) else None,
            prompt_cache_key=prompt_envelope.prompt_cache_key,
            instruction_role="developer",
            selected_skill_ids=[skill.stable_id for skill in selected_skills],
            manifest_tools=[AnyAgentFunctionToolParam.model_validate(item) for item in manifest_tools if isinstance(item, dict)],
            manifest_tool_names=sorted(
                [
                    item["name"]
                    for item in manifest_tools
                    if isinstance(item, dict) and isinstance(item.get("name"), str) and item["name"].strip()
                ]
            ),
            mcp_servers=sorted(pack.mcp_config.mcpServers) if pack.mcp_config is not None else [],
            tool_context=tool_context.model_dump(exclude_none=True),
            prompt_context=prompt_envelope.audit_metadata(),
            rendered_fragments=prompt_envelope.rendered_fragments(),
            effective_body=effective_body,
            applied_body=applied_body,
        )
        return JSONResponse(payload.model_dump(exclude_none=True))

    @app.post("/v1/responses", response_model=None)
    async def create_response(req: Request, authorization: str | None = Header(default=None), x_agent_id: str | None = Header(default=None)):
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
        session_key = _resolve_session_key(body=body)
        session_partition_key_value = session_partition_key(agent_id=agent_id, session_key=session_key)
        async def _create_started_run(response_id_value: str, idem_value: str | None):
            await state.events.mark_started(response_id=response_id_value)
            return await state.run_store.create_started(
                response_id=response_id_value,
                agent_id=agent_id,
                session_key=session_key,
                stream=bool(body.get("stream")),
                idempotency_key=idem_value,
            )

        gate = await begin_or_replay_response_run(
            idempotency_key=idempotency_key,
            stream=bool(body.get("stream")),
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
            if bool(body.get("stream")):
                return gate.response
            return JSONResponse(gate.response)
        response_id = gate.response_id
        selected_skills = await _select_skills(state, pack=pack, body=body)
        tool_context = _build_server_tool_context(pack=pack, body=body, selected_skills=selected_skills)
        prompt_envelope = build_prompt_envelope(
            pack=pack,
            selected_skills=selected_skills,
            tool_context=tool_context,
            model=body.get("model") if isinstance(body.get("model"), str) else None,
            environment_values=_build_prompt_environment_values(state=state, pack=pack),
        )
        prompt_audit = prompt_envelope.audit_metadata()
        mcp_manager = None
        if pack.mcp_config is not None:
            mcp_manager = await state.mcp_managers.get_manager(
                agent_id=pack.agent_id,
                mcp_config=pack.mcp_config,
                credential_store=state.credentials,
            )
        model_provider = get_default_model_provider()
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

        prompt_context_event = AnyAgentPromptContextEvent.model_validate(
            {
                "response_id": response_id,
                "type": "anyagent.prompt.context",
                **prompt_audit.model_dump(exclude_none=True),
            }
        )
        await _stage_sink(prompt_context_event)

        if bool(body.get("stream")):
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

            async def _worker_stream() -> None:
                try:
                    async def _run_stream_serialized() -> None:
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
                            body2 = prompt_envelope.apply_to_body(body=session_ctx.effective_body)
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
                                    manifest_resolver=_resolve_manifest_cached,
                                    manifest_force_refresh=_refresh_manifest_cached,
                                    mcp_manager=mcp_manager,
                                    stage_event_sink=_stage_sink,
                                    prompt_envelope_applied=True,
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
                                    await queue.put(chunk)
                            except asyncio.CancelledError:
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
                                await queue.put(completed_block)
                                await queue.put(done_block)
                                raise
                            except Exception as e:  # noqa: BLE001
                                payload = build_minimal_openai_response_json(
                                    response_id=response_id,
                                    status="failed",
                                    model=str(session_ctx.effective_body.get("model") or "unknown"),
                                )
                                payload["error"] = {"type": "server_error", "message": str(e)}
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
                                )
                                await queue.put(completed_block)
                                await queue.put(done_block)

                    await state.session_sequencer.run(session_partition_key_value, _run_stream_serialized)
                finally:
                    await queue.put(None)
                    await state.runs.remove(response_id)

            task = asyncio.create_task(_worker_stream(), name=f"anyagent-stream-{response_id}")
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

        async def _worker_nonstream() -> None:
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
                        body2 = prompt_envelope.apply_to_body(body=session_ctx.effective_body)
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
                                manifest_resolver=_resolve_manifest_cached,
                                manifest_force_refresh=_refresh_manifest_cached,
                                mcp_manager=mcp_manager,
                                stage_event_sink=_stage_sink,
                                prompt_envelope_applied=True,
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
                            payload["error"] = {"type": "server_error", "message": str(e)}
                            return await _finalize_nonstream_terminal(
                                payload=payload,
                                response_status_code=500,
                                effective_status="failed",
                                error_json={"type": "server_error", "message": str(e)},
                            )

                        if status_code >= 400 or not isinstance(payload, dict) or not isinstance(payload.get("id"), str):
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
            finally:
                await state.runs.remove(response_id)

        task = asyncio.create_task(_worker_nonstream(), name=f"anyagent-run-{response_id}")
        await state.runs.add(response_id=response_id, task=task)
        try:
            await task
        except asyncio.CancelledError:
            pass
        status_code = int(result_box.get("status_code", 500))
        payload = result_box.get("payload")
        return JSONResponse(status_code=status_code, content=payload)

    @app.get("/v1/responses/{response_id}")
    async def retrieve_response(response_id: str, authorization: str | None = Header(default=None)) -> JSONResponse:
        _require_user_auth(state, authorization)
        run = await state.run_store.get(response_id)
        if run is None:
            raise HTTPException(status_code=404, detail=f"unknown response_id: {response_id}")
        return JSONResponse(optional_response_payload_from_run(run, response_id=response_id))

    @app.post("/v1/responses/{response_id}/cancel")
    async def cancel_response(response_id: str, authorization: str | None = Header(default=None)) -> JSONResponse:
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

    return app


def _require_user_auth(state: AnyAgentServerApp, authorization: str | None) -> None:
    _require_bearer(authorization=authorization, expected=state.api_key)


def _require_admin_auth(state: AnyAgentServerApp, authorization: str | None) -> None:
    _require_bearer(authorization=authorization, expected=state.admin_api_key)


def _require_internal_auth(state: AnyAgentServerApp, authorization: str | None) -> None:
    expected = state.admin_api_key or state.api_key
    _require_bearer(authorization=authorization, expected=expected)


def _require_bearer(*, authorization: str | None, expected: str | None) -> None:
    if not expected:
        return
    prefix = "bearer "
    if not isinstance(authorization, str) or not authorization.lower().startswith(prefix):
        raise HTTPException(status_code=401, detail="missing bearer authorization")
    token = authorization[len(prefix) :].strip()
    if token != expected:
        raise HTTPException(status_code=401, detail="invalid api key")


def _resolve_agent_id(*, body: dict[str, Any], x_agent_id: str | None) -> str:
    metadata = body.get("metadata")
    if isinstance(metadata, dict) and isinstance(metadata.get("agent_id"), str) and metadata["agent_id"].strip():
        return metadata["agent_id"].strip()
    if isinstance(x_agent_id, str) and x_agent_id.strip():
        return x_agent_id.strip()
    model = body.get("model")
    if isinstance(model, str) and model.startswith("agent:") and model[6:].strip():
        return model[6:].strip()
    return "main"


def _resolve_session_key(*, body: dict[str, Any]) -> str:
    metadata = body.get("metadata")
    if isinstance(metadata, dict):
        value = metadata.get("session_key")
        if isinstance(value, str) and value.strip():
            return value.strip()
    user = body.get("user")
    if isinstance(user, str) and user.strip():
        return user.strip()
    return f"ephemeral:{uuid.uuid4().hex}"


async def _select_skills(state: AnyAgentServerApp, *, pack: AgentPack, body: dict[str, Any]) -> list[Any]:
    visible_skills, _errors = state.runtime.visible_skills_for_agent(pack.agent_id)
    disabled = resolve_disabled_skill_stable_ids(
        pack.spec.skills.disabled_paths,
        skills=visible_skills,
        base_dir=pack.root_dir,
    )
    enablement = SkillEnablement(user_disabled_paths=disabled)
    selected, _decisions = select_skills(
        skills=visible_skills,
        enablement=enablement,
        metadata=body.get("metadata") if isinstance(body.get("metadata"), dict) else None,
        user_texts=extract_user_texts_from_responses_request(body),
        default_selected=pack.spec.skills.default_selected,
    )
    return selected


def _build_server_tool_context(*, pack: AgentPack, body: dict[str, Any], selected_skills: list[Any]) -> ToolContext:
    context = _sanitize_caller_tool_context(body)
    policy = _policy_hint_for_pack(pack)
    if policy is not None:
        context = ToolContext.model_validate(
            {
                **context.model_dump(exclude_none=True),
                "policy": policy.model_dump(exclude_none=True),
            }
        )
    if selected_skills:
        context = apply_skills_permissions_to_tool_context(context, skills=selected_skills)
    return context


def _sanitize_caller_tool_context(body: dict[str, Any]) -> ToolContext:
    metadata = body.get("metadata")
    if not isinstance(metadata, dict):
        return ToolContext()
    raw = metadata.get("context")
    if not isinstance(raw, dict):
        return ToolContext()
    clean = {k: v for k, v in raw.items() if k != "policy"}
    return ToolContext.model_validate(clean)


def _policy_hint_for_pack(pack: AgentPack) -> PolicyHint | None:
    spec_policy = pack.spec.tools.policy
    if spec_policy is None:
        return None
    return PolicyHint(
        allow_tools=list(spec_policy.allow_tools) if isinstance(spec_policy.allow_tools, list) else None,
        deny_tools=list(spec_policy.deny_tools) if isinstance(spec_policy.deny_tools, list) else None,
    )


def _build_created_sse_block(*, response_id: str, body: dict[str, Any]) -> bytes:
    payload = {
        "type": "response.created",
        "response": build_minimal_openai_response_json(
            response_id=response_id,
            status="in_progress",
            model=str(body.get("model") or "unknown"),
            tools=list(body.get("tools") or []) if isinstance(body.get("tools"), list) else None,
            tool_choice=body.get("tool_choice") if body.get("tool_choice") is not None else "auto",
        ),
    }
    return encode_sse_block(event="response.created", data=json.dumps(payload, ensure_ascii=False), id=None)


def _build_prompt_environment_values(*, state: AnyAgentServerApp, pack: AgentPack) -> dict[str, object]:
    return build_default_environment_context_values(
        cwd=state.workspace_dir,
        sandbox_mode=pack.spec.sandbox.mode,
    )


def _build_completed_sse_block(payload: dict[str, Any]) -> bytes:
    _response_json, data = serialize_completed_response_event_data(payload)
    return encode_sse_block(event="response.completed", data=data, id=None)


async def _append_done_sentinel(*, state: AnyAgentServerApp, response_id: str) -> None:
    await state.events.append(response_id=response_id, event=None, data="[DONE]")


def _strip_response_created_blocks(blocks: list[bytes]) -> list[bytes]:
    out: list[bytes] = []
    for block in blocks:
        text = block.decode("utf-8", errors="replace")
        if text.startswith("event: response.created"):
            continue
        out.append(block)
    return out


def _build_external_response_stream(*, state: AnyAgentServerApp, response_id: str) -> StreamingResponse:
    return build_external_response_stream_response(
        run_store=state.run_store,
        event_store=state.events,
        response_id=response_id,
        event_filter=lambda event: event is None or event == "error" or (isinstance(event, str) and event.startswith("response.")),
    )


async def _append_sse_chunk(
    state: AnyAgentServerApp,
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
    state: AnyAgentServerApp,
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

async def _build_storage_health_payload(state: AnyAgentServerApp) -> dict[str, Any]:
    uses_postgres = _uses_backend(state.events, "Postgres") or _uses_backend(state.run_store, "Postgres") or _uses_backend(state.session_store, "Postgres")
    uses_redis = (
        _uses_backend(state.events, "Redis")
        or _uses_backend(state.run_store, "Redis")
        or _uses_backend(state.session_store, "Redis")
        or _uses_backend(state.session_lock_service, "Redis")
        or _uses_backend(state.session_lock_service, "External")
    )

    postgres_status = await _check_postgres_connection(str(state.storage_settings.postgres_dsn)) if uses_postgres and state.storage_settings.postgres_dsn is not None else None
    redis_status = await _check_redis_connection(str(state.storage_settings.redis_dsn)) if uses_redis and state.storage_settings.redis_dsn is not None else None

    stores = {
        "events": _describe_runtime_component(state.events),
        "run_store": _describe_runtime_component(state.run_store),
        "session_store": _describe_runtime_component(state.session_store),
        "session_lock_service": _describe_runtime_component(state.session_lock_service),
    }
    ok = True
    if uses_postgres:
        ok = ok and bool(postgres_status)
    if uses_redis:
        ok = ok and bool(redis_status)

    return {
        "ok": ok,
        "storage_mode": state.resolved_storage.storage_mode,
        "backends": {
            "event_store": state.resolved_storage.event_store_backend,
            "run_store": state.resolved_storage.run_store_backend,
            "session_store": state.resolved_storage.session_store_backend,
            "session_lock": state.resolved_storage.session_lock_backend,
        },
        "retention_s": {
            "events": state.storage_settings.event_store_retention_s,
            "runs": state.storage_settings.run_store_retention_s,
            "sessions": state.storage_settings.session_store_retention_s,
        },
        "stores": stores,
        "capabilities": build_storage_capability_matrix(
            event_store=state.events,
            run_store=state.run_store,
            session_store=state.session_store,
            session_lock_service=state.session_lock_service,
            workspace_store=state.sandbox_manager.workspace_service,
        ),
        "postgres": {
            "configured": state.storage_settings.postgres_dsn is not None,
            "schema": state.storage_settings.postgres_schema,
            "schema_policy": state.storage_settings.postgres_schema_policy,
            "reachable": postgres_status,
        },
        "redis": {
            "configured": state.storage_settings.redis_dsn is not None,
            "namespace": state.storage_settings.redis_namespace,
            "reachable": redis_status,
        },
    }


def _describe_runtime_component(component: Any) -> dict[str, Any]:
    info = {"type": component.__class__.__name__}
    layers: list[str] = []
    for attr in ("_primary", "_cache", "_client"):
        value = getattr(component, attr, None)
        if value is not None:
            layers.append(value.__class__.__name__)
    if layers:
        info["layers"] = layers
    return info


def _uses_backend(component: Any, token: str) -> bool:
    if token in component.__class__.__name__:
        return True
    for attr in ("_primary", "_cache", "_client"):
        value = getattr(component, attr, None)
        if value is not None and token in value.__class__.__name__:
            return True
    return False


async def _check_postgres_connection(postgres_dsn: str) -> bool:
    try:
        from psycopg import AsyncConnection

        async with await AsyncConnection.connect(postgres_dsn) as conn:
            async with conn.cursor() as cur:
                await cur.execute("SELECT 1")
                row = await cur.fetchone()
        return bool(row and row[0] == 1)
    except Exception:
        return False


async def _check_redis_connection(redis_dsn: str) -> bool:
    try:
        from redis import asyncio as redis_asyncio  # type: ignore[import-not-found]

        client = redis_asyncio.from_url(redis_dsn, encoding="utf-8", decode_responses=True)
        try:
            pong = await client.ping()
            return bool(pong)
        finally:
            await client.aclose()
    except Exception:
        return False


async def _update_session_snapshot(
    *,
    state: AnyAgentServerApp,
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
