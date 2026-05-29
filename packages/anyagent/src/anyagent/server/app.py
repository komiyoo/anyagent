import asyncio
import hashlib
import json
import os
import re
import shutil
import subprocess
import tempfile
import uuid
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, AsyncIterator

from fastapi import FastAPI, Header, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse, RedirectResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import ValidationError
import yaml

from anyagent.agent_packs import (
    ANYAGENT_CONFIG_DIR,
    ANYAGENT_SKILLS_SUBDIR,
    AgentCatalog,
    AgentPack,
    AgentSpec,
    load_agent_catalog,
    preferred_agents_root,
)
from anyagent.model_config import (
    ModelConfigError,
    WorkspaceModelsConfig,
    apply_effective_model_to_body,
    load_workspace_models_config,
    model_provider_for_selection,
    resolve_effective_model_selection,
)
from anyagent.mcp import MCPConfig
from anyagent.mcp.auth import CredentialResolver
from anyagent.skills.loader import SkillLoadError, load_skill_package
from anyagent.agent_runtime import (
    SkillInjector,
    build_default_environment_context_values,
    build_prompt_envelope,
    persist_session_snapshot,
    resolve_skill_injection_token_budget,
)
from anyagent.agent_runtime.session_runtime import input_to_transcript_items
from anyagent.agent_runtime.tool_loop import resolve_manifest_with_mcp, run_tool_loop_nonstream, run_tool_loop_stream_live
from anyagent.agent_runtime.model_providers import get_default_model_provider  # re-exported for existing smoke monkeypatches
from anyagent.gateway.sequencer import KeyedSequencer
from anyagent.gateway.session import session_partition_key
from anyagent.mcp.manager import MCPManagerRegistry
from anyagent.observability import emit_observability_event, get_observability_emitter
from anyagent.protocol.credential_vault import AdminCredentialDeleteResponse, AdminCredentialSetRequest
from anyagent.protocol.health import HealthResponse
from anyagent.protocol.agent_api_internal import (
    AdminAgentCreateRequest,
    AdminAgentCreateResponse,
    AdminAgentConfigUpdateRequest,
    AdminAgentSkillsUpdateRequest,
    AdminToolCatalogResponse,
    AdminWorkspaceAgentFile,
    AdminWorkspaceAgentFilesResponse,
    AdminWorkspaceAgentFileUpdateRequest,
    AdminWorkspaceAgentFileUpdateResponse,
    AdminSkillImportRequest,
    AdminSkillImportResponse,
    AdminSkillRegistryInstallRequest,
    AdminSkillUpdateCheckResponse,
    InternalAgentDetailResponse,
    InternalAgentListItem,
    InternalAgentMCPConfig,
    InternalAgentPromptRef,
    InternalAgentsListResponse,
    InternalAgentSkillsConfig,
    InternalAgentToolsConfig,
    InternalPromptBundlePreviewResponse,
    InternalResponsePromptContextResponse,
    InternalToolCatalogItem,
    InternalToolCatalogResponse,
    WorkspaceAgentFileKind,
)
from anyagent.protocol.openai_responses import (
    AnyAgentFunctionToolParam,
    build_minimal_openai_response_json,
    serialize_completed_response_event_data,
)
from anyagent.protocol.observability import ObservabilityLevel
from anyagent.protocol.prompt_context import PromptContextAudit
from anyagent.protocol.responses_optional import AnyAgentResponseError
from anyagent.protocol.sse import SSEBlockDecoder, encode_sse_block
from anyagent.protocol.stage_events import AnyAgentPromptContextEvent, AnyAgentPromptContextRenderedEvent
from anyagent.protocol.tool_runtime import ManifestRequest, PolicyHint, ToolContext
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
from anyagent.server.request_context import resolve_agent_id, resolve_session_key
from anyagent.server.responses_optional import optional_response_payload_from_run
from anyagent.server.session_context import prepare_response_session_context
from anyagent.server.streaming import (
    append_sse_chunk as append_streaming_sse_chunk,
    build_persisted_sse_block_handler,
    build_response_event_appender,
    build_external_response_stream_response,
    persist_sse_run as persist_streaming_sse_run,
)
from anyagent.server.workspace_env import load_workspace_runtime_environment
from anyagent.server.runs import RunRegistry
from anyagent.server.runtime import InProcessToolRuntimeService
from anyagent.server.sandbox import SandboxManager
from anyagent.server.security import (
    CredentialRuntimeConfig,
    InMemoryCredentialStore,
    build_credential_backend_capability_matrix,
    build_credential_resolver_from_config,
)
from anyagent.server.settings import ResolvedServerStorageSettings, ServerSettings
from anyagent.server.storage_backends import (
    EventStore,
    RunStore,
    ServerStorageBundle,
    SessionStore,
    build_server_storage_bundle,
)
from anyagent.server.telemetry_store import (
    InMemoryObservabilityEventSink,
    InMemoryTelemetryEventStore,
    ObservabilityQuery,
    PostgresTelemetryEventStore,
    RunEventTelemetryStore,
    TelemetryStore,
    TelemetryObservabilitySink,
)
from anyagent.storage import build_storage_capability_matrix, resolve_nonstream_replay_payload
from anyagent.storage.settings import StorageSettings
from anyagent.skills import (
    SkillEnablement,
    apply_skills_permissions_to_tool_context,
    resolve_disabled_skill_stable_ids,
)

_SKILL_DIRECTORY_RE = re.compile(r"^[a-zA-Z0-9_.-]{1,64}$")
_SKILL_INSTALL_PACKAGE_RE = re.compile(r"^[A-Za-z0-9_.:/@-]{1,256}$")
_SKILL_INSTALL_NAME_RE = re.compile(r"^[A-Za-z0-9_.-]{1,128}$")
_GITHUB_REPO_RE = re.compile(r"^(?:https://github\.com/)?([A-Za-z0-9_.-]+)/([A-Za-z0-9_.-]+?)(?:\.git)?/?$")
_GITHUB_REF_RE = re.compile(r"^[A-Za-z0-9_./@+-]{1,128}$")
_GITHUB_PATH_RE = re.compile(r"^[A-Za-z0-9_./@+-]{1,256}$")


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


def _parse_cors_origins(value: str | list[str] | tuple[str, ...] | None) -> list[str]:
    if value is None:
        env_value = os.getenv("ANYAGENT_CORS_ORIGINS", "")
        value = env_value
    if isinstance(value, str):
        return [item.strip() for item in value.split(",") if item.strip()]
    return [str(item).strip() for item in value if str(item).strip()]


@dataclass(slots=True)
class AnyAgentServerApp:
    workspace_dir: Path
    catalog: AgentCatalog
    models_config: WorkspaceModelsConfig
    resolved_storage: ResolvedServerStorageSettings
    storage_settings: StorageSettings
    events: EventStore
    credentials: InMemoryCredentialStore
    mcp_credentials: CredentialResolver | None
    sandbox_manager: SandboxManager
    runtime: InProcessToolRuntimeService
    mcp_managers: MCPManagerRegistry
    runs: RunRegistry
    manifest_cache: ManifestCache
    run_store: RunStore
    session_store: SessionStore
    telemetry_store: TelemetryStore
    observability_event_sink: InMemoryObservabilityEventSink
    telemetry_event_store: Any
    telemetry_observability_sink: TelemetryObservabilitySink
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

    def reload_catalog(self) -> None:
        catalog = load_agent_catalog(workspace_dir=self.workspace_dir)
        models_config = load_workspace_models_config(self.workspace_dir)
        if not any(pack.spec.exposed for pack in catalog.packs.values()):
            raise RuntimeError("workspace must define at least one exposed agent")
        self.catalog = catalog
        self.models_config = models_config
        self.runtime.set_catalog(catalog)
        self.manifest_cache = ManifestCache(ttl_seconds=2.0)

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
    cors_origins: str | list[str] | tuple[str, ...] | None = None,
    enable_studio: bool = True,
) -> FastAPI:
    workspace = Path(workspace_dir).expanduser().resolve()
    load_workspace_runtime_environment(workspace)
    server_settings = ServerSettings()
    resolved_storage = server_settings.resolve(
        storage_mode=storage_mode if isinstance(storage_mode, str) else None,
        event_store_backend=event_store_backend if isinstance(event_store_backend, str) else None,
        run_store_backend=run_store_backend if isinstance(run_store_backend, str) else None,
        session_store_backend=session_store_backend if isinstance(session_store_backend, str) else None,
        session_lock_backend=session_lock_backend if isinstance(session_lock_backend, str) else None,
        session_lease_ttl_s=session_lease_ttl_s,
    )
    catalog = load_agent_catalog(workspace_dir=workspace)
    models_config = load_workspace_models_config(workspace)
    if not any(pack.spec.exposed for pack in catalog.packs.values()):
        raise RuntimeError("workspace must define at least one exposed agent")
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
    mcp_credential_store = build_credential_resolver_from_config(
        CredentialRuntimeConfig(
            backend=server_settings.mcp_credential_store_backend,
            file_root=server_settings.mcp_credential_store_file_root,
            workspace_dir=workspace,
            infisical_host=server_settings.infisical_host,
            infisical_universal_auth_client_id=server_settings.infisical_universal_auth_client_id,
            infisical_universal_auth_client_secret=server_settings.infisical_universal_auth_client_secret,
            infisical_project_id=server_settings.infisical_project_id,
            infisical_environment=server_settings.infisical_environment,
            infisical_cache_ttl_seconds=server_settings.infisical_cache_ttl_seconds,
            infisical_credential_root_path=server_settings.infisical_credential_root_path,
            infisical_path_layout=server_settings.infisical_path_layout,
        ),
        fallback_to_memory=False,
    )
    storage_bundle: ServerStorageBundle = build_server_storage_bundle(
        event_store_backend=resolved_storage.event_store_backend,
        run_store_backend=resolved_storage.run_store_backend,
        session_store_backend=resolved_storage.session_store_backend,
    )
    storage_settings = StorageSettings()
    observability_event_sink = InMemoryObservabilityEventSink()
    if resolved_storage.storage_mode == "external" and storage_settings.postgres_dsn is not None:
        telemetry_event_store: Any = PostgresTelemetryEventStore(
            postgres_dsn=str(storage_settings.postgres_dsn),
            postgres_schema=storage_settings.postgres_schema,
            schema_policy=storage_settings.postgres_schema_policy,
        )
    else:
        telemetry_event_store = InMemoryTelemetryEventStore()
    telemetry_observability_sink = TelemetryObservabilitySink(telemetry_events=telemetry_event_store)
    telemetry_store = RunEventTelemetryStore(
        event_store=storage_bundle.event_store,
        run_store=storage_bundle.run_store,
        observability_events=observability_event_sink,
        telemetry_events=telemetry_event_store,
        include_observability_sink_events=False,
    )
    state = AnyAgentServerApp(
        workspace_dir=workspace,
        catalog=catalog,
        models_config=models_config,
        resolved_storage=resolved_storage,
        storage_settings=storage_settings,
        events=storage_bundle.event_store,
        credentials=credential_store,
        mcp_credentials=mcp_credential_store or credential_store,
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
        telemetry_store=telemetry_store,
        observability_event_sink=observability_event_sink,
        telemetry_event_store=telemetry_event_store,
        telemetry_observability_sink=telemetry_observability_sink,
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
        get_observability_emitter().add_sink(state.observability_event_sink)
        get_observability_emitter().add_sink(state.telemetry_observability_sink)
        try:
            yield
        finally:
            get_observability_emitter().remove_sink(state.telemetry_observability_sink)
            get_observability_emitter().remove_sink(state.observability_event_sink)
            await state.mcp_managers.cleanup_all()
            telemetry_closer = getattr(state.telemetry_event_store, "dispose", None)
            if callable(telemetry_closer):
                result = telemetry_closer()
                if asyncio.iscoroutine(result):
                    await result
            for resource in state.storage_resources:
                closer = getattr(resource, "dispose", None) or getattr(resource, "aclose", None) or getattr(resource, "close", None)
                if callable(closer):
                    result = closer()
                    if asyncio.iscoroutine(result):
                        await result

    app = FastAPI(title="anyagent", version="0.1.8", lifespan=_lifespan)
    if enable_studio:
        studio_dir = Path(__file__).resolve().parents[1] / "studio_static"
        if studio_dir.is_dir():
            @app.get("/", include_in_schema=False)
            async def root_studio_redirect() -> RedirectResponse:
                return RedirectResponse(url="/studio/")

            @app.get("/studio", include_in_schema=False)
            async def studio_index() -> FileResponse:
                return FileResponse(studio_dir / "index.html")

            app.mount("/studio", StaticFiles(directory=str(studio_dir), html=True), name="studio")
    parsed_cors_origins = _parse_cors_origins(cors_origins)
    if parsed_cors_origins:
        app.add_middleware(
            CORSMiddleware,
            allow_origins=parsed_cors_origins,
            allow_credentials=False,
            allow_methods=["GET", "POST", "PUT", "DELETE", "OPTIONS"],
            allow_headers=["authorization", "content-type", "idempotency-key", "x-agent-id"],
        )
    app.state.anyagent = state

    @app.get("/healthz")
    async def healthz() -> dict[str, Any]:
        return HealthResponse(
            ok=True,
            workspace=str(state.workspace_dir),
            agent_ids=sorted(state.catalog.packs.keys()),
        ).model_dump(exclude_none=True)

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

    @app.get("/admin/credentials/capabilities")
    async def admin_credential_capabilities(authorization: str | None = Header(default=None)) -> JSONResponse:
        _require_admin_auth(state, authorization)
        matrix = build_credential_backend_capability_matrix()
        return JSONResponse(matrix.model_dump(exclude_none=True))

    @app.get("/admin/storage/health")
    async def admin_storage_health(authorization: str | None = Header(default=None)) -> JSONResponse:
        _require_admin_auth(state, authorization)
        payload = await _build_storage_health_payload(state)
        return JSONResponse(payload)

    @app.get("/admin/tools/catalog")
    async def admin_tools_catalog(authorization: str | None = Header(default=None)) -> JSONResponse:
        _require_admin_auth(state, authorization)
        tools, toolset_version = state.runtime.list_registered_tools()
        resp = AdminToolCatalogResponse(
            toolset_version=toolset_version,
            tools=[
                InternalToolCatalogItem(
                    name=tool.name,
                    description=tool.description,
                    kind=tool.kind,
                    parameters=tool.parameters,
                    reason=tool.category,
                )
                for tool in tools
            ],
        )
        return JSONResponse(resp.model_dump(exclude_none=True))

    @app.post("/admin/workspace/agents")
    async def admin_workspace_agent_create(
        req: Request,
        authorization: str | None = Header(default=None),
    ) -> JSONResponse:
        _require_admin_auth(state, authorization)
        create_req = AdminAgentCreateRequest.model_validate(await req.json())
        _create_agent_pack(state=state, request=create_req)
        try:
            state.reload_catalog()
        except Exception as e:  # noqa: BLE001
            raise HTTPException(status_code=400, detail=f"workspace reload failed: {e}") from e
        pack = state.require_pack(create_req.agent_id, external=False)
        resp = AdminAgentCreateResponse(
            agent=_agent_detail_response(pack, include_prompt=True),
            reloaded_agent_ids=sorted(state.catalog.packs.keys()),
        )
        return JSONResponse(resp.model_dump(exclude_none=True))

    @app.delete("/admin/credentials/{credential_id}")
    async def admin_delete_credential(credential_id: str, authorization: str | None = Header(default=None)) -> JSONResponse:
        _require_admin_auth(state, authorization)
        deleted = await state.credentials.delete(credential_id)
        resp = AdminCredentialDeleteResponse(ok=True, deleted=bool(deleted), credential_id=credential_id)
        return JSONResponse(resp.model_dump())

    @app.get("/admin/workspace/agents/{agent_id}")
    async def admin_workspace_agent_detail(
        agent_id: str,
        include_prompt: bool = False,
        authorization: str | None = Header(default=None),
    ) -> JSONResponse:
        _require_admin_auth(state, authorization)
        pack = state.require_pack(agent_id, external=False)
        return JSONResponse(_agent_detail_response(pack, include_prompt=include_prompt).model_dump(exclude_none=True))

    @app.get("/admin/workspace/agents/{agent_id}/files")
    async def admin_workspace_agent_files(
        agent_id: str,
        authorization: str | None = Header(default=None),
    ) -> JSONResponse:
        _require_admin_auth(state, authorization)
        pack = state.require_pack(agent_id, external=False)
        resp = AdminWorkspaceAgentFilesResponse(
            agent_id=agent_id,
            files=[
                _workspace_agent_file(pack, kind="agents_md"),
                _workspace_agent_file(pack, kind="agent_yaml"),
                _workspace_agent_file(pack, kind="mcp_json"),
            ],
        )
        return JSONResponse(resp.model_dump(exclude_none=True))

    @app.put("/admin/workspace/agents/{agent_id}/files/{kind}")
    async def admin_workspace_agent_file_update(
        agent_id: str,
        kind: WorkspaceAgentFileKind,
        req: Request,
        authorization: str | None = Header(default=None),
    ) -> JSONResponse:
        _require_admin_auth(state, authorization)
        pack = state.require_pack(agent_id, external=False)
        update = AdminWorkspaceAgentFileUpdateRequest.model_validate(await req.json())
        path = _workspace_agent_file_path(pack, kind=kind)
        before = _workspace_agent_file(pack, kind=kind)
        if update.expected_sha256 is not None and update.expected_sha256 != before.sha256:
            raise HTTPException(status_code=409, detail="file changed; refresh before saving")
        _validate_workspace_agent_file_text(kind=kind, text=update.text)
        previous_text = before.text
        previous_exists = before.exists
        _write_workspace_agent_file(path=path, text=update.text)
        try:
            state.reload_catalog()
        except Exception as e:  # noqa: BLE001
            _restore_workspace_agent_file(path=path, text=previous_text, existed=previous_exists)
            raise HTTPException(status_code=400, detail=f"workspace reload failed: {e}") from e
        reloaded_pack = state.require_pack(agent_id, external=False)
        resp = AdminWorkspaceAgentFileUpdateResponse(
            agent_id=agent_id,
            file=_workspace_agent_file(reloaded_pack, kind=kind),
            reloaded_agent_ids=sorted(state.catalog.packs.keys()),
        )
        return JSONResponse(resp.model_dump(exclude_none=True))

    @app.put("/admin/workspace/agents/{agent_id}/skills")
    async def admin_workspace_agent_skills_update(
        agent_id: str,
        req: Request,
        authorization: str | None = Header(default=None),
    ) -> JSONResponse:
        _require_admin_auth(state, authorization)
        pack = state.require_pack(agent_id, external=False)
        update = AdminAgentSkillsUpdateRequest.model_validate(await req.json())
        _update_agent_default_skills(state=state, pack=pack, default_selected=update.default_selected)
        try:
            state.reload_catalog()
        except Exception as e:  # noqa: BLE001
            raise HTTPException(status_code=400, detail=f"workspace reload failed: {e}") from e
        reloaded_pack = state.require_pack(agent_id, external=False)
        resp = AdminAgentCreateResponse(
            agent=_agent_detail_response(reloaded_pack, include_prompt=False),
            reloaded_agent_ids=sorted(state.catalog.packs.keys()),
        )
        return JSONResponse(resp.model_dump(exclude_none=True))

    @app.put("/admin/workspace/agents/{agent_id}/config")
    async def admin_workspace_agent_config_update(
        agent_id: str,
        req: Request,
        authorization: str | None = Header(default=None),
    ) -> JSONResponse:
        _require_admin_auth(state, authorization)
        pack = state.require_pack(agent_id, external=False)
        update = AdminAgentConfigUpdateRequest.model_validate(await req.json())
        agent_yaml_path = pack.root_dir / "agent.yaml"
        previous_text = agent_yaml_path.read_text(encoding="utf-8")
        _update_agent_config(pack=pack, request=update)
        try:
            state.reload_catalog()
        except Exception as e:  # noqa: BLE001
            agent_yaml_path.write_text(previous_text, encoding="utf-8")
            raise HTTPException(status_code=400, detail=f"workspace reload failed: {e}") from e
        reloaded_pack = state.require_pack(agent_id, external=False)
        resp = AdminAgentCreateResponse(
            agent=_agent_detail_response(reloaded_pack, include_prompt=False),
            reloaded_agent_ids=sorted(state.catalog.packs.keys()),
        )
        return JSONResponse(resp.model_dump(exclude_none=True))

    @app.post("/admin/workspace/agents/{agent_id}/skills/import")
    async def admin_workspace_agent_skill_import(
        agent_id: str,
        req: Request,
        authorization: str | None = Header(default=None),
    ) -> JSONResponse:
        _require_admin_auth(state, authorization)
        pack = state.require_pack(agent_id, external=False)
        import_req = AdminSkillImportRequest.model_validate(await req.json())
        skill = _import_agent_local_skill(pack=pack, request=import_req)
        try:
            state.reload_catalog()
        except Exception as e:  # noqa: BLE001
            raise HTTPException(status_code=400, detail=f"workspace reload failed: {e}") from e
        resp = AdminSkillImportResponse(
            agent_id=agent_id,
            stable_id=skill.stable_id,
            name=skill.frontmatter.name,
            path=str(skill.skill_md_path.resolve()),
            sha256=hashlib.sha256(skill.skill_md_path.read_bytes()).hexdigest(),
            reloaded_agent_ids=sorted(state.catalog.packs.keys()),
        )
        return JSONResponse(resp.model_dump(exclude_none=True))

    @app.post("/admin/workspace/agents/{agent_id}/skills/install")
    async def admin_workspace_agent_skill_install(
        agent_id: str,
        req: Request,
        authorization: str | None = Header(default=None),
    ) -> JSONResponse:
        _require_admin_auth(state, authorization)
        pack = state.require_pack(agent_id, external=False)
        install_req = AdminSkillRegistryInstallRequest.model_validate(await req.json())
        skill = _install_agent_local_skill_from_registry(pack=pack, request=install_req)
        try:
            state.reload_catalog()
        except Exception as e:  # noqa: BLE001
            raise HTTPException(status_code=400, detail=f"workspace reload failed: {e}") from e
        resp = AdminSkillImportResponse(
            agent_id=agent_id,
            stable_id=skill.stable_id,
            name=skill.frontmatter.name,
            path=str(skill.skill_md_path.resolve()),
            sha256=hashlib.sha256(skill.skill_md_path.read_bytes()).hexdigest(),
            reloaded_agent_ids=sorted(state.catalog.packs.keys()),
        )
        return JSONResponse(resp.model_dump(exclude_none=True))

    @app.get("/admin/workspace/agents/{agent_id}/skills/{directory_name}/update/check")
    async def admin_workspace_agent_skill_update_check(
        agent_id: str,
        directory_name: str,
        authorization: str | None = Header(default=None),
    ) -> JSONResponse:
        _require_admin_auth(state, authorization)
        pack = state.require_pack(agent_id, external=False)
        resp = _check_agent_local_skill_update(pack=pack, directory_name=directory_name)
        return JSONResponse(resp.model_dump(exclude_none=True))

    @app.post("/admin/workspace/agents/{agent_id}/skills/{directory_name}/update/apply")
    async def admin_workspace_agent_skill_update_apply(
        agent_id: str,
        directory_name: str,
        authorization: str | None = Header(default=None),
    ) -> JSONResponse:
        _require_admin_auth(state, authorization)
        pack = state.require_pack(agent_id, external=False)
        skill_dir = _resolve_agent_skill_dir(pack, directory_name)
        if not (skill_dir / "SKILL.md").is_file():
            raise HTTPException(status_code=404, detail="skill not found")
        metadata = _read_skill_source_metadata(skill_dir)
        install_req = _install_request_from_skill_source_metadata(metadata, overwrite=True)
        if install_req is None:
            raise HTTPException(status_code=400, detail="skill has no updatable channel source metadata")
        install_req = install_req.model_copy(update={"directory_name": directory_name, "overwrite": True})
        skill = _install_agent_local_skill_from_registry(pack=pack, request=install_req)
        try:
            state.reload_catalog()
        except Exception as e:  # noqa: BLE001
            raise HTTPException(status_code=400, detail=f"workspace reload failed: {e}") from e
        resp = AdminSkillImportResponse(
            agent_id=agent_id,
            stable_id=skill.stable_id,
            name=skill.frontmatter.name,
            path=str(skill.skill_md_path.resolve()),
            sha256=hashlib.sha256(skill.skill_md_path.read_bytes()).hexdigest(),
            reloaded_agent_ids=sorted(state.catalog.packs.keys()),
        )
        return JSONResponse(resp.model_dump(exclude_none=True))

    @app.get("/internal/skills/list")
    async def internal_skills_list(agent_id: str = "main", authorization: str | None = Header(default=None)) -> JSONResponse:
        _require_user_auth(state, authorization)
        resp = await state.runtime.list_skills(agent_id=agent_id)
        return JSONResponse(resp.model_dump(exclude_none=True))

    @app.get("/internal/agents")
    async def internal_agents_list(include_unexposed: bool = False, authorization: str | None = Header(default=None)) -> JSONResponse:
        _require_user_auth(state, authorization)
        agents = [
            _agent_list_item(pack)
            for pack in sorted(state.catalog.packs.values(), key=lambda item: item.agent_id)
            if include_unexposed or pack.spec.exposed
        ]
        return JSONResponse(InternalAgentsListResponse(agents=agents).model_dump(exclude_none=True))

    @app.get("/internal/agents/{agent_id}")
    async def internal_agent_detail(
        agent_id: str,
        include_prompt: bool = False,
        authorization: str | None = Header(default=None),
    ) -> JSONResponse:
        _require_user_auth(state, authorization)
        pack = state.require_pack(agent_id, external=True)
        resp = _agent_detail_response(pack, include_prompt=include_prompt)
        return JSONResponse(resp.model_dump(exclude_none=True))

    @app.get("/internal/tools/catalog")
    async def internal_tools_catalog(
        agent_id: str = "main",
        session_key: str = "studio-catalog",
        requested_tool_names: str | None = None,
        authorization: str | None = Header(default=None),
    ) -> JSONResponse:
        _require_user_auth(state, authorization)
        pack = state.require_pack(agent_id, external=True)
        requested = _split_csv(requested_tool_names)
        manifest_req = _build_agent_manifest_request(pack=pack, session_key=session_key, requested_tool_names=requested)
        manifest = await state.runtime.manifest(manifest_req)
        decision_reasons = {
            decision.tool_name: decision.reason
            for decision in (manifest.decisions or [])
            if decision.decision == "allow"
        }
        tools = []
        for tool in manifest.tools:
            wire_tool = tool.model_dump(exclude_none=True, by_alias=True)
            tools.append(
                InternalToolCatalogItem(
                    name=tool.name,
                    description=tool.description,
                    kind=wire_tool.get("x-anyagent-kind") if isinstance(wire_tool.get("x-anyagent-kind"), str) else None,
                    parameters=tool.parameters,
                    reason=decision_reasons.get(tool.name),
                )
            )
        resp = InternalToolCatalogResponse(
            agent_id=agent_id,
            session_key=session_key,
            requested_tool_names=requested,
            toolset_version=manifest.toolset_version,
            tools=tools,
        )
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

    @app.get("/internal/responses/{response_id}/prompt-context")
    async def internal_response_prompt_context(
        response_id: str,
        authorization: str | None = Header(default=None),
    ) -> JSONResponse:
        _require_user_auth(state, authorization)
        last_seq = 0
        rendered_event = None
        audit_event = None
        for _ in range(100):
            page = await state.events.list_events(response_id=response_id, last_seq=last_seq, limit=200)
            page_rendered = page.latest_prompt_context_rendered()
            page_audit = page.latest_prompt_context()
            if page_rendered is not None:
                rendered_event = page_rendered
            if page_audit is not None:
                audit_event = page_audit
            if page.next_last_seq <= last_seq or page.done:
                break
            last_seq = page.next_last_seq
        if rendered_event is not None:
            payload = InternalResponsePromptContextResponse(
                response_id=response_id,
                prompt_cache_key=rendered_event.prompt_cache_key,
                total_chars=rendered_event.total_chars,
                fragments=rendered_event.fragments,
                rendered_event=rendered_event,
                audit_event=audit_event,
                fallback="rendered",
            )
        elif audit_event is not None:
            payload = InternalResponsePromptContextResponse(
                response_id=response_id,
                prompt_cache_key=audit_event.prompt_cache_key,
                audit_event=audit_event,
                fallback="audit",
            )
        else:
            payload = InternalResponsePromptContextResponse(response_id=response_id)
        return JSONResponse(payload.model_dump(exclude_none=True))

    @app.get("/internal/observability/summary")
    async def internal_observability_summary(
        response_id: str,
        authorization: str | None = Header(default=None),
    ) -> JSONResponse:
        _require_user_auth(state, authorization)
        summary = await state.telemetry_store.summary(response_id=response_id)
        return JSONResponse(summary.model_dump(exclude_none=True))

    @app.get("/internal/observability/runs")
    async def internal_observability_runs(
        agent_id: str | None = None,
        session_key: str | None = None,
        response_id: str | None = None,
        created_after_ms: int | None = None,
        created_before_ms: int | None = None,
        limit: int = 100,
        authorization: str | None = Header(default=None),
    ) -> JSONResponse:
        _require_user_auth(state, authorization)
        payload = await state.telemetry_store.runs(
            ObservabilityQuery(
                agent_id=agent_id,
                session_key=session_key,
                response_id=response_id,
                created_after_ms=created_after_ms,
                created_before_ms=created_before_ms,
                limit=limit,
            )
        )
        return JSONResponse(payload.model_dump(exclude_none=True))

    @app.get("/internal/observability/timeline")
    async def internal_observability_timeline(
        agent_id: str | None = None,
        session_key: str | None = None,
        response_id: str | None = None,
        trace_id: str | None = None,
        created_after_ms: int | None = None,
        created_before_ms: int | None = None,
        limit: int = 200,
        authorization: str | None = Header(default=None),
    ) -> JSONResponse:
        _require_user_auth(state, authorization)
        payload = await state.telemetry_store.timeline(
            ObservabilityQuery(
                agent_id=agent_id,
                session_key=session_key,
                response_id=response_id,
                trace_id=trace_id,
                created_after_ms=created_after_ms,
                created_before_ms=created_before_ms,
                limit=limit,
            )
        )
        return JSONResponse(payload.model_dump(exclude_none=True))

    @app.get("/internal/observability/metrics")
    async def internal_observability_metrics(
        agent_id: str | None = None,
        session_key: str | None = None,
        response_id: str | None = None,
        created_after_ms: int | None = None,
        created_before_ms: int | None = None,
        limit: int = 100,
        authorization: str | None = Header(default=None),
    ) -> JSONResponse:
        _require_user_auth(state, authorization)
        payload = await state.telemetry_store.metrics(
            ObservabilityQuery(
                agent_id=agent_id,
                session_key=session_key,
                response_id=response_id,
                created_after_ms=created_after_ms,
                created_before_ms=created_before_ms,
                limit=limit,
            )
        )
        return JSONResponse(payload.model_dump(exclude_none=True))

    @app.get("/internal/observability/tools")
    async def internal_observability_tools(
        agent_id: str | None = None,
        session_key: str | None = None,
        response_id: str | None = None,
        created_after_ms: int | None = None,
        created_before_ms: int | None = None,
        limit: int = 100,
        authorization: str | None = Header(default=None),
    ) -> JSONResponse:
        _require_user_auth(state, authorization)
        payload = await state.telemetry_store.tools(
            ObservabilityQuery(
                agent_id=agent_id,
                session_key=session_key,
                response_id=response_id,
                created_after_ms=created_after_ms,
                created_before_ms=created_before_ms,
                limit=limit,
            )
        )
        return JSONResponse(payload.model_dump(exclude_none=True))

    @app.get("/internal/observability/errors")
    async def internal_observability_errors(
        agent_id: str | None = None,
        session_key: str | None = None,
        response_id: str | None = None,
        trace_id: str | None = None,
        created_after_ms: int | None = None,
        created_before_ms: int | None = None,
        limit: int = 100,
        authorization: str | None = Header(default=None),
    ) -> JSONResponse:
        _require_user_auth(state, authorization)
        payload = await state.telemetry_store.errors(
            ObservabilityQuery(
                agent_id=agent_id,
                session_key=session_key,
                response_id=response_id,
                trace_id=trace_id,
                created_after_ms=created_after_ms,
                created_before_ms=created_before_ms,
                limit=limit,
            )
        )
        return JSONResponse(payload.model_dump(exclude_none=True))

    @app.get("/internal/observability/traces/{trace_id}")
    async def internal_observability_trace(
        trace_id: str,
        limit: int = 500,
        authorization: str | None = Header(default=None),
    ) -> JSONResponse:
        _require_user_auth(state, authorization)
        payload = await state.telemetry_store.trace(trace_id=trace_id, limit=limit)
        return JSONResponse(payload.model_dump(exclude_none=True))

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
        model_selection = resolve_effective_model_selection(workspace_config=state.models_config, pack=pack)
        apply_effective_model_to_body(body=body, selection=model_selection)
        session_key = _resolve_session_key(body=body)
        selected_skills = await _select_skills(state, pack=pack, body=body)
        tool_context = _build_server_tool_context(pack=pack, body=body, selected_skills=selected_skills)
        mcp_manager = None
        if pack.mcp_config is not None:
            mcp_manager = await state.mcp_managers.get_manager(
                agent_id=pack.agent_id,
                mcp_config=pack.mcp_config,
                credential_store=state.mcp_credentials,
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
        model_selection = resolve_effective_model_selection(workspace_config=state.models_config, pack=pack)
        apply_effective_model_to_body(body=body, selection=model_selection)
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
                credential_store=state.mcp_credentials,
            )
        try:
            model_provider = _model_provider_for_selection(model_selection)
        except ModelConfigError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
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

            async def _worker_stream() -> None:
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
                                await queue.put(completed_block)
                                await queue.put(done_block)
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
                                    prompt_audit=prompt_audit,
                                )
                                await queue.put(completed_block)
                                await queue.put(done_block)

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
                payload_status = payload.get("status") if isinstance(payload, dict) and isinstance(payload.get("status"), str) else None
                _emit_server_response_event(
                    "server.response.nonstream.completed" if status_code < 500 else "server.response.nonstream.failed",
                    level="info" if status_code < 500 else "error",
                    response_id=response_id,
                    agent_id=agent_id,
                    session_key=session_key,
                    stream=False,
                    idempotency_key_present=idempotency_key is not None,
                    status_code=status_code,
                    status=payload_status,
                )
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


def _model_provider_for_selection(selection) -> Any:
    if selection.provider_kind == "openai" and not selection.uses_workspace_provider:
        return get_default_model_provider()
    return model_provider_for_selection(selection)


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


def _text_preview(text: str | None, *, max_chars: int = 240) -> str | None:
    if not isinstance(text, str):
        return None
    compact = " ".join(text.strip().split())
    if not compact:
        return ""
    if len(compact) <= max_chars:
        return compact
    return f"{compact[: max_chars - 1]}…"


def _prompt_ref(*, path: Path | None, sha256: str | None, text: str | None, include_prompt: bool) -> InternalAgentPromptRef | None:
    if path is None or not isinstance(sha256, str) or not sha256:
        return None
    return InternalAgentPromptRef(
        path=str(path),
        sha256=sha256,
        preview=_text_preview(text),
        text=text if include_prompt else None,
    )


def _workspace_agent_file_path(pack: AgentPack, *, kind: WorkspaceAgentFileKind) -> Path:
    if kind == "agents_md":
        return pack.root_dir / "AGENTS.md"
    if kind == "agent_yaml":
        return pack.root_dir / "agent.yaml"
    if kind == "mcp_json":
        return pack.root_dir / "mcp.json"
    raise HTTPException(status_code=404, detail=f"unknown editable file kind: {kind}")


def _read_workspace_agent_file(path: Path) -> tuple[bool, str | None, str | None]:
    if not path.is_file():
        return False, None, None
    raw = path.read_bytes()
    sha256 = hashlib.sha256(raw).hexdigest()
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError as e:
        raise HTTPException(status_code=400, detail=f"invalid utf-8 in workspace file: {path}: {e}") from e
    return True, sha256, text


def _workspace_agent_file(pack: AgentPack, *, kind: WorkspaceAgentFileKind) -> AdminWorkspaceAgentFile:
    path = _workspace_agent_file_path(pack, kind=kind)
    exists, sha256, text = _read_workspace_agent_file(path)
    return AdminWorkspaceAgentFile(
        kind=kind,
        path=str(path),
        exists=exists,
        sha256=sha256,
        text=text,
    )


def _validate_workspace_agent_file_text(*, kind: WorkspaceAgentFileKind, text: str) -> None:
    raw = text.encode("utf-8")
    max_bytes = 64 * 1024 if kind == "agents_md" else 256 * 1024
    if len(raw) > max_bytes:
        raise HTTPException(status_code=413, detail=f"file too large: bytes={len(raw)} max={max_bytes}")
    if kind == "agent_yaml":
        try:
            payload = yaml.safe_load(text)
            if not isinstance(payload, dict):
                raise ValueError("agent.yaml must be an object")
            AgentSpec.model_validate(payload)
        except (ValueError, ValidationError, yaml.YAMLError) as e:
            raise HTTPException(status_code=400, detail=f"invalid agent.yaml: {e}") from e
    elif kind == "mcp_json":
        if not text.strip():
            raise HTTPException(status_code=400, detail="invalid mcp.json: file must be a JSON object")
        try:
            payload = json.loads(text)
            if not isinstance(payload, dict):
                raise ValueError("mcp.json must be an object")
            MCPConfig.model_validate(payload)
        except (ValueError, ValidationError, json.JSONDecodeError) as e:
            raise HTTPException(status_code=400, detail=f"invalid mcp.json: {e}") from e


def _write_workspace_agent_file(*, path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def _restore_workspace_agent_file(*, path: Path, text: str | None, existed: bool) -> None:
    if existed:
        path.write_text(text or "", encoding="utf-8")
    elif path.exists():
        path.unlink()


def _create_agent_pack(*, state: AnyAgentServerApp, request: AdminAgentCreateRequest) -> None:
    agent_id = request.agent_id.strip()
    if not _SKILL_DIRECTORY_RE.fullmatch(agent_id):
        raise HTTPException(status_code=400, detail="invalid agent_id")
    agent_dir = preferred_agents_root(state.workspace_dir) / agent_id
    if agent_dir.exists():
        raise HTTPException(status_code=409, detail="agent already exists")
    spec = AgentSpec.model_validate(
        {
            "exposed": request.exposed,
            "model": {
                "default": request.model_default,
                "provider": request.model_provider,
                "base_url_env": request.model_base_url_env,
                "api_key_env": request.model_api_key_env,
            },
            "tools": {"requested_tool_names": request.requested_tool_names},
            "skills": {"default_selected": request.default_selected_skills},
            "sandbox": {"mode": request.sandbox_mode},
            "multiagent": {"spawn_allow_agent_ids": request.spawn_allow_agent_ids},
        }
    )
    agent_dir.mkdir(parents=True)
    try:
        (agent_dir / "agent.yaml").write_text(yaml.safe_dump(spec.model_dump(exclude_none=True), sort_keys=False), encoding="utf-8")
        (agent_dir / "AGENTS.md").write_text(request.instructions, encoding="utf-8")
        (agent_dir / "mcp.json").write_text('{"mcpServers": {}}\n', encoding="utf-8")
        (agent_dir / "skills").mkdir()
    except Exception:
        if agent_dir.exists():
            shutil.rmtree(agent_dir)
        raise


def _update_agent_default_skills(*, state: AnyAgentServerApp, pack: AgentPack, default_selected: list[str]) -> None:
    cleaned = [item.strip() for item in default_selected if isinstance(item, str) and item.strip()]
    visible_skills, _errors = state.runtime.visible_skills_for_agent(pack.agent_id)
    by_name: dict[str, list[Any]] = {}
    by_id = {skill.stable_id: skill for skill in visible_skills}
    for skill in visible_skills:
        by_name.setdefault(skill.frontmatter.name, []).append(skill)
    normalized: list[str] = []
    for item in cleaned:
        if item in by_id:
            normalized.append(by_id[item].frontmatter.name)
            continue
        matches = by_name.get(item) or []
        if len(matches) == 1:
            normalized.append(item)
            continue
        if not matches:
            raise HTTPException(status_code=400, detail=f"unknown skill: {item}")
        raise HTTPException(status_code=400, detail=f"ambiguous skill name: {item}")
    agent_yaml_path = pack.root_dir / "agent.yaml"
    payload = yaml.safe_load(agent_yaml_path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise HTTPException(status_code=400, detail="agent.yaml must be an object")
    skills_payload = payload.get("skills")
    if not isinstance(skills_payload, dict):
        skills_payload = {}
        payload["skills"] = skills_payload
    skills_payload["default_selected"] = normalized
    AgentSpec.model_validate(payload)
    agent_yaml_path.write_text(yaml.safe_dump(payload, sort_keys=False), encoding="utf-8")


def _update_agent_config(*, pack: AgentPack, request: AdminAgentConfigUpdateRequest) -> None:
    """Update common Studio-facing controls while preserving unknown agent.yaml keys."""

    agent_yaml_path = pack.root_dir / "agent.yaml"
    payload = yaml.safe_load(agent_yaml_path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise HTTPException(status_code=400, detail="agent.yaml must be an object")
    if request.exposed is not None:
        payload["exposed"] = request.exposed
    if any(
        value is not None
        for value in (request.model_default, request.model_provider, request.model_base_url_env, request.model_api_key_env)
    ):
        model_payload = payload.get("model")
        if not isinstance(model_payload, dict):
            model_payload = {}
            payload["model"] = model_payload
        if request.model_default is not None:
            model_payload["default"] = request.model_default.strip() or None
        if request.model_provider is not None:
            model_payload["provider"] = request.model_provider.strip() or "openai"
        if request.model_base_url_env is not None:
            model_payload["base_url_env"] = request.model_base_url_env.strip() or None
        if request.model_api_key_env is not None:
            model_payload["api_key_env"] = request.model_api_key_env.strip() or None
    if request.requested_tool_names is not None:
        tools_payload = payload.get("tools")
        if not isinstance(tools_payload, dict):
            tools_payload = {}
            payload["tools"] = tools_payload
        tools_payload["requested_tool_names"] = [
            item.strip() for item in request.requested_tool_names if isinstance(item, str) and item.strip()
        ]
    if request.sandbox_mode is not None:
        sandbox_payload = payload.get("sandbox")
        if not isinstance(sandbox_payload, dict):
            sandbox_payload = {}
            payload["sandbox"] = sandbox_payload
        sandbox_payload["mode"] = request.sandbox_mode
    if request.spawn_allow_agent_ids is not None:
        multiagent_payload = payload.get("multiagent")
        if not isinstance(multiagent_payload, dict):
            multiagent_payload = {}
            payload["multiagent"] = multiagent_payload
        multiagent_payload["spawn_allow_agent_ids"] = [
            item.strip() for item in request.spawn_allow_agent_ids if isinstance(item, str) and item.strip()
        ]
    if request.disabled_skill_paths is not None:
        skills_payload = payload.get("skills")
        if not isinstance(skills_payload, dict):
            skills_payload = {}
            payload["skills"] = skills_payload
        cleaned_disabled = [item.strip() for item in request.disabled_skill_paths if isinstance(item, str) and item.strip()]
        skills_payload["disabled_paths"] = cleaned_disabled
        default_selected = skills_payload.get("default_selected")
        if isinstance(default_selected, list):
            disabled_names = {Path(item).parent.name for item in cleaned_disabled}
            skills_payload["default_selected"] = [
                item
                for item in default_selected
                if not (isinstance(item, str) and (item.strip() in cleaned_disabled or item.strip() in disabled_names))
            ]
    AgentSpec.model_validate(payload)
    agent_yaml_path.write_text(yaml.safe_dump(payload, sort_keys=False), encoding="utf-8")


def _resolve_agent_skill_dir(pack: AgentPack, directory_name: str) -> Path:
    directory_name = directory_name.strip()
    if not _SKILL_DIRECTORY_RE.fullmatch(directory_name):
        raise HTTPException(status_code=400, detail="invalid skill directory_name")
    skill_dir = (pack.skills_dir / directory_name).resolve()
    root = pack.skills_dir.resolve()
    if root != skill_dir and root not in skill_dir.parents:
        raise HTTPException(status_code=400, detail="skill directory escapes agent skills root")
    return skill_dir


def _copy_skill_dir_into_agent(
    *,
    pack: AgentPack,
    source_dir: Path,
    directory_name: str,
    overwrite: bool,
    source_metadata: dict[str, Any] | None = None,
):
    skill_dir = _resolve_agent_skill_dir(pack, directory_name)
    skill_md_path = skill_dir / "SKILL.md"
    if skill_dir.exists() and not overwrite:
        raise HTTPException(status_code=409, detail="skill already exists; set overwrite=true to replace")
    previous_dir = None
    if skill_dir.exists():
        previous_dir = Path(tempfile.mkdtemp(prefix="anyagent-skill-backup-")) / skill_dir.name
        shutil.copytree(skill_dir, previous_dir)
        shutil.rmtree(skill_dir)
    skill_dir.parent.mkdir(parents=True, exist_ok=True)
    shutil.copytree(source_dir, skill_dir)
    try:
        skill = load_skill_package(skill_dir, scope="agent")
        if source_metadata is not None:
            metadata = {
                **source_metadata,
                "installed_at": datetime.now(timezone.utc).isoformat(),
                "source_hash": hashlib.sha256((skill_dir / "SKILL.md").read_bytes()).hexdigest(),
            }
            (skill_dir / ".anyagent-skill-source.json").write_text(
                json.dumps(metadata, indent=2, sort_keys=True) + "\n",
                encoding="utf-8",
            )
        return skill
    except SkillLoadError as e:
        if skill_dir.exists():
            shutil.rmtree(skill_dir)
        if previous_dir is not None:
            shutil.copytree(previous_dir, skill_dir)
        raise HTTPException(status_code=400, detail=f"invalid skill: {e}") from e


def _import_agent_local_skill(*, pack: AgentPack, request: AdminSkillImportRequest):
    raw = request.skill_md.encode("utf-8")
    if len(raw) > 256 * 1024:
        raise HTTPException(status_code=413, detail=f"skill too large: bytes={len(raw)} max={256 * 1024}")
    directory_name = request.directory_name.strip()
    _resolve_agent_skill_dir(pack, directory_name)
    with tempfile.TemporaryDirectory(prefix="anyagent-skill-import-") as tmp:
        source_dir = Path(tmp) / directory_name
        source_dir.mkdir(parents=True)
        (source_dir / "SKILL.md").write_text(request.skill_md, encoding="utf-8")
        return _copy_skill_dir_into_agent(
            pack=pack,
            source_dir=source_dir,
            directory_name=directory_name,
            overwrite=request.overwrite,
            source_metadata={
                "channel": "local_upload",
                "source_ref": directory_name,
                "skill": directory_name,
            },
        )


def _read_skill_source_metadata(skill_dir: Path) -> dict[str, Any]:
    metadata_path = skill_dir / ".anyagent-skill-source.json"
    if not metadata_path.is_file():
        return {}
    try:
        payload = json.loads(metadata_path.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        return {}
    return payload if isinstance(payload, dict) else {}


def _install_request_from_skill_source_metadata(metadata: dict[str, Any], *, overwrite: bool) -> AdminSkillRegistryInstallRequest | None:
    channel = metadata.get("channel")
    if channel not in {"skills.sh", "registry", "github"}:
        return None
    skill = metadata.get("skill")
    if not isinstance(skill, str) or not skill.strip():
        return None
    package = metadata.get("package")
    if not isinstance(package, str) or not package.strip():
        package = metadata.get("github_repo") if channel == "github" else None
    if not isinstance(package, str) or not package.strip():
        return None
    return AdminSkillRegistryInstallRequest(
        channel=channel,
        package=package,
        skill=skill,
        directory_name=None,
        github_repo=metadata.get("github_repo") if isinstance(metadata.get("github_repo"), str) else None,
        github_ref=metadata.get("github_ref") if isinstance(metadata.get("github_ref"), str) else None,
        github_path=metadata.get("github_path") if isinstance(metadata.get("github_path"), str) else None,
        overwrite=overwrite,
    )


def _check_agent_local_skill_update(*, pack: AgentPack, directory_name: str) -> AdminSkillUpdateCheckResponse:
    skill_dir = _resolve_agent_skill_dir(pack, directory_name)
    if not (skill_dir / "SKILL.md").is_file():
        raise HTTPException(status_code=404, detail="skill not found")
    metadata = _read_skill_source_metadata(skill_dir)
    current_hash = hashlib.sha256((skill_dir / "SKILL.md").read_bytes()).hexdigest()
    install_req = _install_request_from_skill_source_metadata(metadata, overwrite=True)
    if install_req is None:
        return AdminSkillUpdateCheckResponse(
            agent_id=pack.agent_id,
            directory_name=directory_name,
            channel=str(metadata.get("channel")) if isinstance(metadata.get("channel"), str) else None,
            source_ref=str(metadata.get("source_ref")) if isinstance(metadata.get("source_ref"), str) else None,
            current_hash=current_hash,
            updatable=False,
            reason="skill has no updatable channel source metadata",
        )
    with tempfile.TemporaryDirectory(prefix="anyagent-skill-check-") as tmp:
        temp_pack = AgentPack(
            agent_id=pack.agent_id,
            root_dir=Path(tmp),
            spec=pack.spec,
            agents_md_path=pack.agents_md_path,
            agents_md_text=pack.agents_md_text,
            agents_md_sha256=pack.agents_md_sha256,
            workspace_agents_md_path=pack.workspace_agents_md_path,
            workspace_agents_md_text=pack.workspace_agents_md_text,
            workspace_agents_md_sha256=pack.workspace_agents_md_sha256,
            mcp_config=pack.mcp_config,
        )
        latest = _install_agent_local_skill_from_registry(pack=temp_pack, request=install_req)
        latest_hash = hashlib.sha256(latest.skill_md_path.read_bytes()).hexdigest()
    return AdminSkillUpdateCheckResponse(
        agent_id=pack.agent_id,
        directory_name=directory_name,
        channel=install_req.channel,
        source_ref=str(metadata.get("source_ref")) if isinstance(metadata.get("source_ref"), str) else None,
        current_hash=current_hash,
        latest_hash=latest_hash,
        update_available=current_hash != latest_hash,
        updatable=True,
    )


def _github_repo_url(repo: str) -> tuple[str, str]:
    match = _GITHUB_REPO_RE.fullmatch(repo.strip())
    if not match:
        raise HTTPException(status_code=400, detail="invalid github_repo")
    owner, name = match.groups()
    return f"https://github.com/{owner}/{name}.git", f"{owner}/{name}"


def _resolve_github_skill_source(repo_root: Path, github_path: str | None, skill_name: str) -> Path:
    raw_path = (github_path or skill_name).strip()
    if not _GITHUB_PATH_RE.fullmatch(raw_path) or raw_path.startswith("/") or ".." in Path(raw_path).parts:
        raise HTTPException(status_code=400, detail="invalid github_path")
    candidate = (repo_root / raw_path).resolve()
    root = repo_root.resolve()
    if root != candidate and root not in candidate.parents:
        raise HTTPException(status_code=400, detail="github_path escapes repository")
    if candidate.is_file() and candidate.name == "SKILL.md":
        candidate = candidate.parent
    if not (candidate / "SKILL.md").is_file():
        raise HTTPException(status_code=400, detail="github_path must point to a skill directory or SKILL.md")
    return candidate


def _install_agent_local_skill_from_github(*, pack: AgentPack, request: AdminSkillRegistryInstallRequest):
    repo = request.github_repo or request.package
    repo_url, repo_ref = _github_repo_url(repo)
    skill_name = request.skill.strip()
    directory_name = (request.directory_name or skill_name).strip()
    ref = (request.github_ref or "main").strip()
    if not _SKILL_INSTALL_NAME_RE.fullmatch(skill_name):
        raise HTTPException(status_code=400, detail="invalid skill")
    if not _GITHUB_REF_RE.fullmatch(ref):
        raise HTTPException(status_code=400, detail="invalid github_ref")
    _resolve_agent_skill_dir(pack, directory_name)
    with tempfile.TemporaryDirectory(prefix="anyagent-skill-github-") as tmp:
        repo_dir = Path(tmp) / "repo"
        result = subprocess.run(
            ["git", "clone", "--depth", "1", "--branch", ref, repo_url, str(repo_dir)],
            cwd=tmp,
            check=False,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            timeout=120,
        )
        if result.returncode != 0:
            raise HTTPException(status_code=400, detail=f"github skill clone failed: {_text_preview(result.stdout, limit=800)}")
        source_dir = _resolve_github_skill_source(repo_dir, request.github_path, skill_name)
        return _copy_skill_dir_into_agent(
            pack=pack,
            source_dir=source_dir,
            directory_name=directory_name,
            overwrite=request.overwrite,
            source_metadata={
                "channel": "github",
                "package": repo_ref,
                "skill": skill_name,
                "source_ref": f"github:{repo_ref}:{ref}:{request.github_path or skill_name}",
                "github_repo": repo_ref,
                "github_ref": ref,
                "github_path": request.github_path or skill_name,
            },
        )


def _install_agent_local_skill_from_registry(*, pack: AgentPack, request: AdminSkillRegistryInstallRequest):
    if request.channel == "github":
        return _install_agent_local_skill_from_github(pack=pack, request=request)
    package = request.package.strip()
    skill_name = request.skill.strip()
    directory_name = (request.directory_name or skill_name).strip()
    if not _SKILL_INSTALL_PACKAGE_RE.fullmatch(package):
        raise HTTPException(status_code=400, detail="invalid package")
    if not _SKILL_INSTALL_NAME_RE.fullmatch(skill_name):
        raise HTTPException(status_code=400, detail="invalid skill")
    _resolve_agent_skill_dir(pack, directory_name)
    with tempfile.TemporaryDirectory(prefix="anyagent-skills-install-") as tmp:
        result = subprocess.run(
            [
                "npx",
                "--yes",
                "skills",
                "add",
                package,
                "--channel",
                request.channel,
                "--skill",
                skill_name,
                "--agent",
                "universal",
                "--copy",
                "-y",
            ],
            cwd=tmp,
            check=False,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            timeout=120,
        )
        if result.returncode != 0:
            raise HTTPException(status_code=400, detail=f"skills install failed: {_text_preview(result.stdout, limit=800)}")
        installed_dir = Path(tmp) / ANYAGENT_CONFIG_DIR / ANYAGENT_SKILLS_SUBDIR / skill_name
        if not installed_dir.is_dir():
            raise HTTPException(status_code=400, detail="skills install did not produce expected skill directory")
        return _copy_skill_dir_into_agent(
            pack=pack,
            source_dir=installed_dir,
            directory_name=directory_name,
            overwrite=request.overwrite,
            source_metadata={
                "channel": request.channel,
                "package": package,
                "skill": skill_name,
                "source_ref": f"{request.channel}:{package}:{skill_name}",
            },
        )


def _mcp_server_labels(pack: AgentPack) -> list[str]:
    if pack.mcp_config is None:
        return []
    return sorted(label for label, cfg in pack.mcp_config.mcpServers.items() if cfg.enabled)


def _agent_list_item(pack: AgentPack) -> InternalAgentListItem:
    return InternalAgentListItem(
        agent_id=pack.agent_id,
        name=pack.agent_id,
        exposed=pack.spec.exposed,
        root_dir=str(pack.root_dir),
        prompt_sha256=pack.agents_md_sha256,
        workspace_prompt_sha256=pack.workspace_agents_md_sha256,
        sandbox_mode=pack.spec.sandbox.mode,
        model_default=pack.spec.model.default,
        model_provider=pack.spec.model.provider,
        model_base_url_env=pack.spec.model.base_url_env,
        model_api_key_env=pack.spec.model.api_key_env,
        requested_tool_names=list(pack.spec.tools.requested_tool_names),
        default_selected_skill_ids=list(pack.spec.skills.default_selected or []),
        spawn_allow_agent_ids=list(pack.spec.multiagent.spawn_allow_agent_ids or []),
        has_mcp=pack.mcp_config is not None,
        mcp_server_labels=_mcp_server_labels(pack),
    )


def _agent_detail_response(pack: AgentPack, *, include_prompt: bool) -> InternalAgentDetailResponse:
    agents_md = _prompt_ref(
        path=pack.agents_md_path,
        sha256=pack.agents_md_sha256,
        text=pack.agents_md_text,
        include_prompt=include_prompt,
    )
    if agents_md is None:
        raise HTTPException(status_code=500, detail=f"agent prompt metadata missing: {pack.agent_id}")
    return InternalAgentDetailResponse(
        agent_id=pack.agent_id,
        name=pack.agent_id,
        exposed=pack.spec.exposed,
        root_dir=str(pack.root_dir),
        agents_md=agents_md,
        workspace_agents_md=_prompt_ref(
            path=pack.workspace_agents_md_path,
            sha256=pack.workspace_agents_md_sha256,
            text=pack.workspace_agents_md_text,
            include_prompt=include_prompt,
        ),
        model=pack.spec.model.model_dump(exclude_none=True),
        tools=InternalAgentToolsConfig(
            requested_tool_names=list(pack.spec.tools.requested_tool_names),
            allow_tools=list(pack.spec.tools.policy.allow_tools) if pack.spec.tools.policy and pack.spec.tools.policy.allow_tools else None,
            deny_tools=list(pack.spec.tools.policy.deny_tools) if pack.spec.tools.policy and pack.spec.tools.policy.deny_tools else None,
        ),
        skills=InternalAgentSkillsConfig(
            default_selected=list(pack.spec.skills.default_selected) if pack.spec.skills.default_selected is not None else None,
            disabled_paths=list(pack.spec.skills.disabled_paths) if pack.spec.skills.disabled_paths is not None else None,
        ),
        sandbox=pack.spec.sandbox.model_dump(exclude_none=True),
        multiagent=pack.spec.multiagent.model_dump(exclude_none=True),
        mcp=InternalAgentMCPConfig(
            configured=pack.mcp_config is not None,
            server_labels=_mcp_server_labels(pack),
        ),
    )


def _split_csv(value: str | None) -> list[str]:
    if not isinstance(value, str):
        return []
    return [item.strip() for item in value.split(",") if item.strip()]


def _build_agent_manifest_request(
    *,
    pack: AgentPack,
    session_key: str,
    requested_tool_names: list[str] | None = None,
) -> ManifestRequest:
    context = ToolContext()
    spec_policy = pack.spec.tools.policy
    if spec_policy is not None:
        context.policy = PolicyHint(
            allow_tools=list(spec_policy.allow_tools) if isinstance(spec_policy.allow_tools, list) else None,
            deny_tools=list(spec_policy.deny_tools) if isinstance(spec_policy.deny_tools, list) else None,
        )
    return ManifestRequest(
        agent_id=pack.agent_id,
        session_key=session_key,
        requested_tool_names=list(requested_tool_names or []),
        context=context,
    )


async def _select_skills(state: AnyAgentServerApp, *, pack: AgentPack, body: dict[str, Any]) -> list[Any]:
    visible_skills, _errors = state.runtime.visible_skills_for_agent(pack.agent_id)
    metadata = body.get("metadata") if isinstance(body.get("metadata"), dict) else None
    disabled = resolve_disabled_skill_stable_ids(
        pack.spec.skills.disabled_paths,
        skills=visible_skills,
        base_dir=pack.root_dir,
    )
    enablement = SkillEnablement(user_disabled_paths=disabled)
    result = SkillInjector(
        token_budget=resolve_skill_injection_token_budget(metadata=metadata),
    ).select_for_request(
        skills=visible_skills,
        enablement=enablement,
        body=body,
        metadata=metadata,
        default_selected=pack.spec.skills.default_selected,
    )
    return result.selected_skills


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
    uses_postgres = (
        _uses_backend(state.events, "Postgres")
        or _uses_backend(state.run_store, "Postgres")
        or _uses_backend(state.session_store, "Postgres")
        or _uses_backend(state.telemetry_event_store, "Postgres")
    )
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
        "telemetry_store": _describe_runtime_component(state.telemetry_store),
        "telemetry_events": _describe_runtime_component(state.telemetry_event_store),
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
