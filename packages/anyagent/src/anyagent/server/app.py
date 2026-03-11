from __future__ import annotations

import asyncio
import json
import uuid
from contextlib import asynccontextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any, AsyncIterator

from fastapi import FastAPI, Header, HTTPException, Request
from fastapi.responses import JSONResponse, StreamingResponse

from anyagent.agent_packs import AgentCatalog, AgentPack, load_agent_catalog
from anyagent.agent_runtime.prompt_injection import build_agents_md_injection_text
from anyagent.agent_runtime.session_runtime import (
    apply_runtime_config_to_body,
    apply_session_resume_to_body,
    build_fallback_transcript_items,
    build_initial_session_snapshot,
    build_next_session_snapshot,
    extract_runtime_updates_from_request,
    input_to_transcript_items,
    merge_runtime_config,
)
from anyagent.agent_runtime.tool_loop import resolve_manifest_with_mcp, run_tool_loop_nonstream, run_tool_loop_stream_live
from anyagent.agent_runtime.model_providers import get_default_model_provider
from anyagent.gateway.sequencer import KeyedSequencer
from anyagent.gateway.session import session_partition_key
from anyagent.mcp.manager import MCPManagerRegistry
from anyagent.protocol.credential_vault import AdminCredentialSetRequest
from anyagent.protocol.openai_responses import (
    build_minimal_openai_response_json,
    decode_completed_response_payload,
    inject_text_into_responses_body,
)
from anyagent.protocol.responses_optional import AnyAgentResponseError
from anyagent.protocol.sandbox import SandboxPolicy
from anyagent.protocol.sse import SSEBlockDecoder, encode_sse_block
from anyagent.protocol.stage_events import (
    AnyAgentCommandPlannedEvent,
    AnyAgentCommandResultEvent,
    AnyAgentToolPlannedEvent,
    AnyAgentToolResultEvent,
)
from anyagent.protocol.tool_runtime import PolicyHint, ToolContext
from anyagent.server.lock_service import SessionLockService, build_session_lock_service, hold_session_lease
from anyagent.server.manifest_cache import ManifestCache, build_manifest_cache_key, extract_requested_tool_names
from anyagent.server.runs import RunRegistry
from anyagent.server.runtime import InProcessToolRuntimeService
from anyagent.server.sandbox import SandboxManager
from anyagent.server.security import InMemoryCredentialStore
from anyagent.server.settings import ResolvedServerStorageSettings, ServerSettings
from anyagent.server.storage_backends import EventStore, RunStore, SessionStore, build_event_store, build_run_store, build_session_store
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
    api_key: str | None = None
    admin_api_key: str | None = None

    def require_pack(self, agent_id: str, *, external: bool) -> AgentPack:
        pack = self.catalog.get(agent_id)
        if pack is None:
            raise HTTPException(status_code=404, detail=f"unknown agent_id: {agent_id}")
        if external and not pack.spec.exposed:
            raise HTTPException(status_code=403, detail=f"agent is not exposed: {agent_id}")
        return pack


@dataclass(slots=True, frozen=True)
class PreparedSessionRequest:
    previous_snapshot: dict[str, Any]
    previous_snapshot_version: int | None
    effective_runtime_config: dict[str, Any]
    request_transcript_items: list[dict[str, Any]]
    effective_body: dict[str, Any]


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
    state = AnyAgentServerApp(
        workspace_dir=workspace,
        catalog=catalog,
        resolved_storage=resolved_storage,
        storage_settings=StorageSettings(),
        events=build_event_store(backend=resolved_storage.event_store_backend),
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
        run_store=build_run_store(backend=resolved_storage.run_store_backend),
        session_store=build_session_store(backend=resolved_storage.session_store_backend),
        session_sequencer=KeyedSequencer(),
        session_lock_service=build_session_lock_service(
            backend=resolved_storage.session_lock_backend,
        ),
        session_lease_ttl_s=resolved_storage.session_lease_ttl_s,
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

    @app.post("/v1/responses", response_model=None)
    async def create_response(req: Request, authorization: str | None = Header(default=None), x_agent_id: str | None = Header(default=None)):
        _require_user_auth(state, authorization)
        body = await req.json()
        if not isinstance(body, dict):
            raise HTTPException(status_code=400, detail="request body must be an object")

        idempotency_key = req.headers.get("idempotency-key")
        agent_id = _resolve_agent_id(body=body, x_agent_id=x_agent_id)
        pack = state.require_pack(agent_id, external=True)
        session_key = _resolve_session_key(body=body)
        session_partition_key_value = session_partition_key(agent_id=agent_id, session_key=session_key)
        if isinstance(idempotency_key, str) and idempotency_key.strip():
            existing = await state.run_store.get_by_idempotency_key(idempotency_key.strip())
            if existing is not None:
                if bool(body.get("stream")):
                    return _build_external_response_stream(state=state, response_id=existing.response_id)
                payload = existing.final_response_json or build_minimal_openai_response_json(
                    response_id=existing.response_id,
                    status=existing.effective_status,  # type: ignore[arg-type]
                    model=str(body.get("model") or "unknown"),
                )
                return JSONResponse(payload)
        response_id = f"resp_{uuid.uuid4().hex}"
        await state.events.mark_started(response_id=response_id)
        await state.run_store.create_started(
            response_id=response_id,
            agent_id=agent_id,
            session_key=session_key,
            stream=bool(body.get("stream")),
            idempotency_key=idempotency_key.strip() if isinstance(idempotency_key, str) and idempotency_key.strip() else None,
        )
        selected_skills = await _select_skills(state, pack=pack, body=body)
        tool_context = _build_server_tool_context(pack=pack, body=body, selected_skills=selected_skills)
        agents_md_text = build_agents_md_injection_text(pack)
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
                metadata=body.get("metadata") if isinstance(body.get("metadata"), dict) else None,
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
                            prepared = await _prepare_session_request(
                                state=state,
                                session_partition_key_value=session_partition_key_value,
                                body=body,
                            )
                            body2 = inject_text_into_responses_body(
                                body=prepared.effective_body,
                                text=agents_md_text,
                                role="developer",
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
                                    manifest_resolver=_resolve_manifest_cached,
                                    manifest_force_refresh=_refresh_manifest_cached,
                                    mcp_manager=mcp_manager,
                                    stage_event_sink=_stage_sink,
                                ):
                                    await _append_sse_chunk(
                                        state,
                                        response_id=response_id,
                                        chunk=chunk,
                                        decoder=decoder,
                                        fallback_model=prepared.effective_body.get("model"),
                                        session_partition_key_value=session_partition_key_value,
                                        agent_id=agent_id,
                                        session_key=session_key,
                                        previous_snapshot=prepared.previous_snapshot,
                                        previous_snapshot_version=prepared.previous_snapshot_version,
                                        runtime_config=prepared.effective_runtime_config,
                                        request_transcript_items=prepared.request_transcript_items,
                                    )
                                    await queue.put(chunk)
                            except asyncio.CancelledError:
                                payload = build_minimal_openai_response_json(
                                    response_id=response_id,
                                    status="cancelled",
                                    model=str(prepared.effective_body.get("model") or "unknown"),
                                )
                                completed_block = _build_completed_sse_block(payload)
                                done_block = encode_sse_block(event=None, data="[DONE]", id=None)
                                await _append_sse_chunk(
                                    state,
                                    response_id=response_id,
                                    chunk=completed_block,
                                    decoder=decoder,
                                    fallback_model=prepared.effective_body.get("model"),
                                    session_partition_key_value=session_partition_key_value,
                                    agent_id=agent_id,
                                    session_key=session_key,
                                    previous_snapshot=prepared.previous_snapshot,
                                    previous_snapshot_version=prepared.previous_snapshot_version,
                                    runtime_config=prepared.effective_runtime_config,
                                    request_transcript_items=prepared.request_transcript_items,
                                )
                                await _append_sse_chunk(
                                    state,
                                    response_id=response_id,
                                    chunk=done_block,
                                    decoder=decoder,
                                    fallback_model=prepared.effective_body.get("model"),
                                    session_partition_key_value=session_partition_key_value,
                                    agent_id=agent_id,
                                    session_key=session_key,
                                    previous_snapshot=prepared.previous_snapshot,
                                    previous_snapshot_version=prepared.previous_snapshot_version,
                                    runtime_config=prepared.effective_runtime_config,
                                    request_transcript_items=prepared.request_transcript_items,
                                )
                                await queue.put(completed_block)
                                await queue.put(done_block)
                                raise
                            except Exception as e:  # noqa: BLE001
                                payload = build_minimal_openai_response_json(
                                    response_id=response_id,
                                    status="failed",
                                    model=str(prepared.effective_body.get("model") or "unknown"),
                                )
                                payload["error"] = {"type": "server_error", "message": str(e)}
                                completed_block = _build_completed_sse_block(payload)
                                done_block = encode_sse_block(event=None, data="[DONE]", id=None)
                                await _append_sse_chunk(
                                    state,
                                    response_id=response_id,
                                    chunk=completed_block,
                                    decoder=decoder,
                                    fallback_model=prepared.effective_body.get("model"),
                                    session_partition_key_value=session_partition_key_value,
                                    agent_id=agent_id,
                                    session_key=session_key,
                                    previous_snapshot=prepared.previous_snapshot,
                                    previous_snapshot_version=prepared.previous_snapshot_version,
                                    runtime_config=prepared.effective_runtime_config,
                                    request_transcript_items=prepared.request_transcript_items,
                                )
                                await _append_sse_chunk(
                                    state,
                                    response_id=response_id,
                                    chunk=done_block,
                                    decoder=decoder,
                                    fallback_model=prepared.effective_body.get("model"),
                                    session_partition_key_value=session_partition_key_value,
                                    agent_id=agent_id,
                                    session_key=session_key,
                                    previous_snapshot=prepared.previous_snapshot,
                                    previous_snapshot_version=prepared.previous_snapshot_version,
                                    runtime_config=prepared.effective_runtime_config,
                                    request_transcript_items=prepared.request_transcript_items,
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
                        prepared = await _prepare_session_request(
                            state=state,
                            session_partition_key_value=session_partition_key_value,
                            body=body,
                        )
                        body2 = inject_text_into_responses_body(
                            body=prepared.effective_body,
                            text=agents_md_text,
                            role="developer",
                        )
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
                            )
                        except asyncio.CancelledError:
                            payload = build_minimal_openai_response_json(
                                response_id=response_id,
                                status="cancelled",
                                model=str(prepared.effective_body.get("model") or "unknown"),
                            )
                            await _append_done_sentinel(state=state, response_id=response_id)
                            await state.events.mark_final(
                                response_id=response_id,
                                run_status="aborted",
                                effective_run_status="cancelled",
                                response_json=payload,
                            )
                            await state.run_store.mark_final(
                                response_id=response_id,
                                status="aborted",
                                effective_status="cancelled",
                                final_response_json=payload,
                            )
                            await _update_session_snapshot(
                                state=state,
                                session_partition_key_value=session_partition_key_value,
                                agent_id=agent_id,
                                session_key=session_key,
                                previous_snapshot=prepared.previous_snapshot,
                                previous_snapshot_version=prepared.previous_snapshot_version,
                                runtime_config=prepared.effective_runtime_config,
                                request_transcript_items=prepared.request_transcript_items,
                                response_id=response_id,
                                effective_status="cancelled",
                                response_json=payload,
                            )
                            return 200, payload
                        except Exception as e:  # noqa: BLE001
                            payload = build_minimal_openai_response_json(
                                response_id=response_id,
                                status="failed",
                                model=str(prepared.effective_body.get("model") or "unknown"),
                            )
                            payload["error"] = {"type": "server_error", "message": str(e)}
                            await _append_done_sentinel(state=state, response_id=response_id)
                            await state.events.mark_final(
                                response_id=response_id,
                                run_status="errored",
                                effective_run_status="failed",
                                response_json=payload,
                                error=AnyAgentResponseError(type="server_error", message=str(e)),
                            )
                            await state.run_store.mark_final(
                                response_id=response_id,
                                status="errored",
                                effective_status="failed",
                                final_response_json=payload,
                                error_json={"type": "server_error", "message": str(e)},
                            )
                            await _update_session_snapshot(
                                state=state,
                                session_partition_key_value=session_partition_key_value,
                                agent_id=agent_id,
                                session_key=session_key,
                                previous_snapshot=prepared.previous_snapshot,
                                previous_snapshot_version=prepared.previous_snapshot_version,
                                runtime_config=prepared.effective_runtime_config,
                                request_transcript_items=prepared.request_transcript_items,
                                response_id=response_id,
                                effective_status="failed",
                                response_json=payload,
                            )
                            return 500, payload

                        if status_code >= 400 or not isinstance(payload, dict) or not isinstance(payload.get("id"), str):
                            return status_code, payload
                        await state.events.append(
                            response_id=response_id,
                            event="response.completed",
                            data=json.dumps(payload, ensure_ascii=False),
                        )
                        await _append_done_sentinel(state=state, response_id=response_id)
                        await state.events.mark_final(
                            response_id=response_id,
                            run_status=_internal_run_status_from_effective(str(payload.get("status") or "completed")),
                            effective_run_status=str(payload.get("status") or "completed"),
                            response_json=payload,
                        )
                        await state.run_store.mark_final(
                            response_id=response_id,
                            status=_internal_run_status_from_effective(str(payload.get("status") or "completed")),
                            effective_status=str(payload.get("status") or "completed"),
                            final_response_json=payload,
                        )
                        await _update_session_snapshot(
                            state=state,
                            session_partition_key_value=session_partition_key_value,
                            agent_id=agent_id,
                            session_key=session_key,
                            previous_snapshot=prepared.previous_snapshot,
                            previous_snapshot_version=prepared.previous_snapshot_version,
                            runtime_config=prepared.effective_runtime_config,
                            request_transcript_items=prepared.request_transcript_items,
                            response_id=response_id,
                            effective_status=str(payload.get("status") or "completed"),
                            response_json=payload,
                        )
                        return status_code, payload

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
        payload = await state.events.get_response(response_id)
        if payload is not None:
            return JSONResponse(payload)
        status, error = await state.events.get_status(response_id)
        if status is None:
            raise HTTPException(status_code=404, detail=f"unknown response_id: {response_id}")
        return JSONResponse(
            build_minimal_openai_response_json(
                response_id=response_id,
                status=status,  # type: ignore[arg-type]
            )
        )

    @app.post("/v1/responses/{response_id}/cancel")
    async def cancel_response(response_id: str, authorization: str | None = Header(default=None)) -> JSONResponse:
        _require_user_auth(state, authorization)
        await state.runtime.cancel_active_for_response(response_id)
        cancelled = await state.runs.cancel(response_id)
        if cancelled:
            await state.events.mark_cancel_requested(response_id=response_id)
            await state.run_store.mark_cancel_requested(response_id)
        status, error = await state.events.get_status(response_id)
        if status is None:
            raise HTTPException(status_code=404, detail=f"unknown response_id: {response_id}")
        payload = build_minimal_openai_response_json(response_id=response_id, status=status)  # type: ignore[arg-type]
        if error is not None:
            payload["error"] = error.model_dump(exclude_none=True)
        return JSONResponse(payload)

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


def _build_completed_sse_block(payload: dict[str, Any]) -> bytes:
    wrapper = {"type": "response.completed", "response": payload}
    return encode_sse_block(event="response.completed", data=json.dumps(wrapper, ensure_ascii=False), id=None)


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
    async def _iter() -> AsyncIterator[bytes]:
        async for item in state.events.stream_events(response_id=response_id, last_seq=0):
            if item.event is None and item.data.strip() == "[DONE]":
                yield encode_sse_block(event=None, data=item.data, id=str(item.seq))
                continue
            if item.event is None:
                continue
            if item.event.startswith("anyagent."):
                continue
            if not (item.event.startswith("response.") or item.event == "error"):
                continue
            yield encode_sse_block(event=item.event, data=item.data, id=str(item.seq))

    return StreamingResponse(_iter(), media_type="text/event-stream")


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
    text = chunk.decode("utf-8", errors="replace")
    for line in text.splitlines():
        for blk in decoder.feed_line(line):
            await _handle_sse_block(
                state=state,
                response_id=response_id,
                event=blk.event,
                data=blk.data,
                fallback_model=fallback_model,
                session_partition_key_value=session_partition_key_value,
                agent_id=agent_id,
                session_key=session_key,
                previous_snapshot=previous_snapshot,
                previous_snapshot_version=previous_snapshot_version,
                runtime_config=runtime_config,
                request_transcript_items=request_transcript_items,
            )


async def _handle_sse_block(
    *,
    state: AnyAgentServerApp,
    response_id: str,
    event: str | None,
    data: str,
    fallback_model: Any,
    session_partition_key_value: str | None = None,
    agent_id: str | None = None,
    session_key: str | None = None,
    previous_snapshot: dict[str, Any] | None = None,
    previous_snapshot_version: int | None = None,
    runtime_config: dict[str, Any] | None = None,
    request_transcript_items: list[dict[str, Any]] | None = None,
) -> None:
    if event is None and data.strip() == "[DONE]":
        return
    await state.events.append(response_id=response_id, event=event, data=data)
    if event == "response.completed":
        maybe = decode_completed_response_payload(data)
        if maybe is None:
            maybe = build_minimal_openai_response_json(
                response_id=response_id,
                status="completed",
                model=str(fallback_model or "unknown"),
            )
        await _append_done_sentinel(state=state, response_id=response_id)
        await state.events.mark_final(
            response_id=response_id,
            run_status=_internal_run_status_from_effective(str(maybe.get("status") or "completed")),
            effective_run_status=str(maybe.get("status") or "completed"),
            response_json=maybe,
        )
        await state.run_store.mark_final(
            response_id=response_id,
            status=_internal_run_status_from_effective(str(maybe.get("status") or "completed")),
            effective_status=str(maybe.get("status") or "completed"),
            final_response_json=maybe,
        )
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
                response_id=response_id,
                effective_status=str(maybe.get("status") or "completed"),
                response_json=maybe,
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
    decoder = SSEBlockDecoder()
    response_id = "resp_anyagent"
    response_json: dict[str, Any] | None = None
    for chunk in chunks:
        text = chunk.decode("utf-8", errors="replace")
        for line in text.splitlines():
            for blk in decoder.feed_line(line):
                if blk.event is None and blk.data.strip() == "[DONE]":
                    continue
                if isinstance(blk.data, str) and blk.data.strip().startswith("{"):
                    try:
                        payload = json.loads(blk.data)
                    except Exception:
                        payload = None
                    if isinstance(payload, dict):
                        if isinstance(payload.get("response_id"), str) and payload["response_id"].strip():
                            response_id = payload["response_id"].strip()
                        resp = payload.get("response")
                        if isinstance(resp, dict) and isinstance(resp.get("id"), str) and resp["id"].strip():
                            response_id = resp["id"].strip()
                        if isinstance(payload.get("id"), str) and payload.get("object") == "response":
                            response_id = payload["id"].strip()
                if blk.event == "response.completed":
                    maybe = decode_completed_response_payload(blk.data)
                    if isinstance(maybe, dict) and isinstance(maybe.get("id"), str):
                        response_id = maybe["id"]
                        response_json = maybe
                seq = await state.events.append(
                    response_id=response_id,
                    event=blk.event,
                    data=blk.data,
                )
                _ = seq
    for blk in decoder.flush():
        if blk.event is not None or blk.data.strip() != "[DONE]":
            await state.events.append(response_id=response_id, event=blk.event, data=blk.data)

    if response_json is None:
        response_json = build_minimal_openai_response_json(
            response_id=response_id,
            status="completed",
            model=str(fallback_model or "unknown"),
        )
    await _append_done_sentinel(state=state, response_id=response_id)
    effective = str(response_json.get("status") or "completed")
    await state.events.mark_final(
        response_id=response_id,
        run_status=_internal_run_status_from_effective(effective),
        effective_run_status=effective,
        response_json=response_json,
    )
    await state.run_store.mark_final(
        response_id=response_id,
        status=_internal_run_status_from_effective(effective),
        effective_status=effective,
        final_response_json=response_json,
    )
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
            response_id=response_id,
            effective_status=effective,
            response_json=response_json,
        )
    return response_id, response_json


def _internal_run_status_from_effective(status: str) -> str:
    if status == "cancelled":
        return "aborted"
    if status == "failed":
        return "errored"
    if status == "in_progress":
        return "started"
    return status


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


async def _prepare_session_request(
    *,
    state: AnyAgentServerApp,
    session_partition_key_value: str,
    body: dict[str, Any],
) -> PreparedSessionRequest:
    session_record = await state.session_store.get(session_partition_key=session_partition_key_value)
    previous_snapshot = (
        dict(session_record.snapshot_json)
        if session_record is not None and isinstance(session_record.snapshot_json, dict)
        else None
    )
    previous_snapshot_version = session_record.snapshot_version if session_record is not None else None
    base_runtime_config = (
        previous_snapshot.get("runtime_config")
        if isinstance(previous_snapshot, dict) and isinstance(previous_snapshot.get("runtime_config"), dict)
        else {}
    )
    explicit_runtime_updates = extract_runtime_updates_from_request(body)
    effective_runtime_config = merge_runtime_config(
        base_runtime_config=base_runtime_config if isinstance(base_runtime_config, dict) else {},
        explicit_updates=explicit_runtime_updates,
    )
    if previous_snapshot is None:
        previous_snapshot = build_initial_session_snapshot(runtime_config=effective_runtime_config)
    effective_body = apply_runtime_config_to_body(body=body, runtime_config=effective_runtime_config)
    request_transcript_items = input_to_transcript_items(effective_body.get("input"))
    effective_body, _resume_previous_response_id = apply_session_resume_to_body(
        body=effective_body,
        session_snapshot=previous_snapshot,
    )
    return PreparedSessionRequest(
        previous_snapshot=previous_snapshot,
        previous_snapshot_version=previous_snapshot_version,
        effective_runtime_config=effective_runtime_config,
        request_transcript_items=request_transcript_items,
        effective_body=effective_body,
    )


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
) -> None:
    latest_seq = await state.events.latest_seq(response_id)
    previous = dict(previous_snapshot) if isinstance(previous_snapshot, dict) else build_initial_session_snapshot(runtime_config={})
    resume_last_response_id = response_id if effective_status == "completed" else _read_resume_last_response_id(previous)
    fallback_transcript_items = None
    if effective_status == "completed":
        fallback_transcript_items = build_fallback_transcript_items(
            previous_snapshot=previous,
            request_input=request_transcript_items if isinstance(request_transcript_items, list) else [],
            response_json=response_json,
        )
    next_snapshot = build_next_session_snapshot(
        previous_snapshot=previous,
        runtime_config=runtime_config,
        resume_last_response_id=resume_last_response_id,
        fallback_transcript_items=fallback_transcript_items,
        run_response_id=response_id,
        last_event_seq=latest_seq,
    )
    await state.session_store.upsert(
        session_partition_key=session_partition_key_value,
        agent_id=agent_id,
        session_key=session_key,
        snapshot_json=next_snapshot,
        expected_snapshot_version=previous_snapshot_version,
    )


def _read_resume_last_response_id(snapshot: dict[str, Any]) -> str | None:
    resume = snapshot.get("resume_cursor")
    if not isinstance(resume, dict):
        return None
    value = resume.get("last_response_id")
    if isinstance(value, str) and value.strip():
        return value.strip()
    return None
