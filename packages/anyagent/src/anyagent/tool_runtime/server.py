from __future__ import annotations

import os
from contextlib import asynccontextmanager
import logging
from pathlib import Path
from typing import Any

from fastapi import FastAPI, Header, HTTPException, Request
from fastapi.responses import JSONResponse
from pydantic import ValidationError

from anyagent.agent_packs import load_agent_catalog
from anyagent.mcp.auth import CredentialResolver
from anyagent.plugins import load_plugins_from_roots
from anyagent.protocol.admin_storage import (
    AdminSandboxRuntimeDiagnostics,
    AdminSandboxWorkspaceHealthResponse,
    AdminSandboxWorkspaceEventsRequest,
    AdminSandboxWorkspaceListResponse,
    AdminSandboxWorkspaceRef,
    AdminSandboxWorkspaceRequest,
)
from anyagent.protocol.credential_vault import (
    AdminCredentialDeleteResponse,
    AdminCredentialListResponse,
    AdminCredentialRef,
    AdminCredentialSetRequest,
)
from anyagent.protocol.health import HealthResponse
from anyagent.protocol.plugins import LoadedPluginCatalogItem, PluginCatalogResponse, PluginLoadErrorItem, PluginToolRef
from anyagent.protocol.sandbox import FileSystemSandboxPolicy
from anyagent.protocol.stage_events import AnyAgentWorkspaceLifecycleEvent
from anyagent.protocol.tool_runtime import CancelRequest, ExecuteRequest, ManifestRequest
from anyagent.server.runtime.in_process import InProcessToolRuntimeService
from anyagent.server.sandbox import SandboxManager, WorkspaceEventStore, build_workspace_event_store
from anyagent.server.sandbox import (
    WorkspaceAwareSandboxManagerAdapter,
    WorkspaceEventContext,
    WorkspaceRuntimeAssembly,
    WorkspaceService,
    build_workspace_runtime,
)
from anyagent.server.security import (
    CredentialStore,
    ReadOnlyCredentialStoreError,
    build_credential_backend_capability_matrix,
    build_credential_resolver_from_config,
)
from anyagent.server.plugins.capabilities import build_plugin_capability_matrix
from anyagent.server.runtime.workspace_env import load_workspace_runtime_environment
from anyagent.tool_runtime.plugins import ToolRuntimePluginAPI
from anyagent.tool_runtime.settings import ToolRuntimeServerConfig, build_tool_runtime_server_config


logger = logging.getLogger("anyagent.tool_runtime")


def create_tool_runtime_app(
    *,
    workspace_dir: str | Path = ".",
    internal_key: str | None = None,
    admin_api_key: str | None = None,
    sandbox_root_dir: str | Path | None = None,
    credential_store: CredentialResolver | None = None,
    plugin_roots: list[str | Path] | None = None,
    plugins_fail_open: bool | None = None,
    workspace_event_store: WorkspaceEventStore | None = None,
    workspace_runtime: WorkspaceRuntimeAssembly | None = None,
    config: ToolRuntimeServerConfig | None = None,
) -> FastAPI:
    if config is None:
        load_workspace_runtime_environment(Path(workspace_dir).expanduser().resolve())
        server_config = build_tool_runtime_server_config(
            workspace_dir=workspace_dir,
            internal_key=internal_key,
            admin_api_key=admin_api_key,
            sandbox_root_dir=sandbox_root_dir,
            plugin_roots=plugin_roots,
            plugins_fail_open=plugins_fail_open,
        )
    else:
        server_config = config
    workspace = Path(server_config.workspace_dir).expanduser().resolve()
    load_workspace_runtime_environment(workspace)
    credential_config = server_config.credential
    if credential_config is None:
        from anyagent.server.security.credential_runtime import CredentialRuntimeConfig

        credential_config = CredentialRuntimeConfig(workspace_dir=workspace)
    catalog = load_agent_catalog(workspace_dir=workspace)
    resolved_workspace_service = workspace_runtime.service if workspace_runtime is not None else None
    sandbox_manager = (
        WorkspaceAwareSandboxManagerAdapter(workspace_service=resolved_workspace_service)
        if resolved_workspace_service is not None and resolved_workspace_service.config.enabled
        else SandboxManager(root_dir=server_config.sandbox_root_dir)
    )
    runtime = InProcessToolRuntimeService(
        workspace_dir=str(workspace),
        catalog=catalog,
        sandbox_manager=sandbox_manager,
        credential_store=credential_store or build_credential_resolver_from_config(credential_config),
    )
    resolved_plugin_roots = _resolve_plugin_roots(server_config.plugin_roots, workspace=workspace)
    resolved_workspace_event_store = (
        workspace_runtime.event_store
        if workspace_runtime is not None
        else workspace_event_store or _build_default_workspace_event_store(config=server_config, workspace=workspace)
    )
    loaded_plugins, plugin_errors = _load_tool_runtime_plugins(
        runtime=runtime,
        roots=resolved_plugin_roots,
        fail_open=server_config.plugins_fail_open,
    )
    resolved_internal_key = server_config.internal_key
    resolved_admin_key = server_config.admin_api_key

    @asynccontextmanager
    async def _lifespan(app: FastAPI):
        app.state.anyagent_tool_runtime = runtime
        try:
            yield
        finally:
            if resolved_workspace_service is not None:
                await resolved_workspace_service.aclose()
            else:
                await resolved_workspace_event_store.aclose()

    app = FastAPI(title="anyagent-tool-runtime", version="0.2.0", lifespan=_lifespan)
    app.state.anyagent_tool_runtime = runtime
    app.state.anyagent_tool_runtime_workspace = workspace
    app.state.anyagent_tool_runtime_internal_key = resolved_internal_key
    app.state.anyagent_tool_runtime_admin_key = resolved_admin_key
    app.state.anyagent_tool_runtime_plugin_roots = resolved_plugin_roots
    app.state.anyagent_tool_runtime_loaded_plugins = loaded_plugins
    app.state.anyagent_tool_runtime_plugin_errors = plugin_errors
    app.state.anyagent_tool_runtime_workspace_event_store = resolved_workspace_event_store
    app.state.anyagent_tool_runtime_workspace_service = resolved_workspace_service

    @app.get("/healthz")
    async def healthz() -> dict[str, Any]:
        return HealthResponse(
            ok=True,
            workspace=str(workspace),
            agent_ids=sorted(catalog.packs.keys()),
        ).model_dump(exclude_none=True)

    @app.post("/internal/tools/manifest")
    async def tools_manifest(request: Request, authorization: str | None = Header(default=None)) -> JSONResponse:
        _require_internal_auth(expected=resolved_internal_key, authorization=authorization)
        resp = await runtime.manifest(ManifestRequest.model_validate(await request.json()))
        return JSONResponse(resp.model_dump(exclude_none=True, by_alias=True))

    @app.post("/internal/tools/execute")
    async def tools_execute(request: Request, authorization: str | None = Header(default=None)) -> JSONResponse:
        _require_internal_auth(expected=resolved_internal_key, authorization=authorization)
        resp = await runtime.execute(ExecuteRequest.model_validate(await request.json()))
        status_code = 409 if getattr(getattr(resp, "error", None), "code", None) == "tool_execution_in_progress" else 200
        return JSONResponse(status_code=status_code, content=resp.model_dump(exclude_none=True, by_alias=True))

    @app.post("/internal/tools/cancel")
    async def tools_cancel(request: Request, authorization: str | None = Header(default=None)) -> JSONResponse:
        _require_internal_auth(expected=resolved_internal_key, authorization=authorization)
        resp = await runtime.cancel(CancelRequest.model_validate(await request.json()))
        return JSONResponse(resp.model_dump(exclude_none=True))

    @app.get("/internal/tools/list")
    async def tools_list(authorization: str | None = Header(default=None)) -> JSONResponse:
        _require_internal_auth(expected=resolved_internal_key, authorization=authorization)
        tools, toolset_version = runtime.list_registered_tools()
        return JSONResponse(
            {
                "toolset_version": toolset_version,
                "tools": [tool.model_dump(exclude_none=True, by_alias=True) for tool in tools],
            }
        )

    @app.post("/admin/credentials")
    async def admin_credentials_set(request: Request, authorization: str | None = Header(default=None)) -> JSONResponse:
        _require_admin_auth(expected=resolved_admin_key, authorization=authorization)
        store = _require_credential_store(runtime._credential_store)
        req = AdminCredentialSetRequest.model_validate(await request.json())
        try:
            await store.set(
                credential_id=req.credential_id,
                kind=req.kind,
                value=req.value,
                scope=req.scope,
                metadata=req.metadata,
                expires_at=req.expires_at,
                rotate_before=req.rotate_before,
            )
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        except ReadOnlyCredentialStoreError as exc:
            raise HTTPException(status_code=501, detail=str(exc)) from exc
        ref = AdminCredentialRef(
            credential_id=req.credential_id,
            kind=req.kind,
            scope=req.scope,
            metadata=req.metadata,
            expires_at=req.expires_at,
            rotate_before=req.rotate_before,
        )
        return JSONResponse(ref.model_dump(mode="json", exclude_none=True))

    @app.get("/admin/credentials")
    async def admin_credentials_list(authorization: str | None = Header(default=None)) -> JSONResponse:
        _require_admin_auth(expected=resolved_admin_key, authorization=authorization)
        store = _require_credential_store(runtime._credential_store)
        refs = await store.list_refs()
        response = AdminCredentialListResponse(credentials=[AdminCredentialRef.model_validate(ref) for ref in refs])
        return JSONResponse(response.model_dump(mode="json", exclude_none=True))

    @app.get("/admin/credentials/capabilities")
    async def admin_credentials_capabilities(authorization: str | None = Header(default=None)) -> JSONResponse:
        _require_admin_auth(expected=resolved_admin_key, authorization=authorization)
        matrix = build_credential_backend_capability_matrix()
        return JSONResponse(matrix.model_dump(mode="json", exclude_none=True))

    @app.get("/admin/plugins/catalog")
    async def admin_plugins_catalog(authorization: str | None = Header(default=None)) -> JSONResponse:
        _require_admin_auth(expected=resolved_admin_key, authorization=authorization)
        response = PluginCatalogResponse(
            plugin_roots=[str(root) for root in resolved_plugin_roots],
            loaded=[LoadedPluginCatalogItem.model_validate(item) for item in loaded_plugins],
            errors=[PluginLoadErrorItem.model_validate(item) for item in plugin_errors],
        )
        return JSONResponse(response.model_dump(mode="json", exclude_none=True))

    @app.get("/admin/plugins/capabilities")
    async def admin_plugins_capabilities(authorization: str | None = Header(default=None)) -> JSONResponse:
        _require_admin_auth(expected=resolved_admin_key, authorization=authorization)
        matrix = build_plugin_capability_matrix()
        return JSONResponse(matrix.model_dump(mode="json", exclude_none=True))

    @app.get("/admin/sandbox/health")
    async def admin_sandbox_health(authorization: str | None = Header(default=None)) -> JSONResponse:
        _require_admin_auth(expected=resolved_admin_key, authorization=authorization)
        response = (
            await _workspace_service_health(resolved_workspace_service)
            if resolved_workspace_service is not None
            else await _sandbox_health(runtime=runtime, sandbox_root_dir=server_config.sandbox_root_dir)
        )
        return JSONResponse(response.model_dump(mode="json", exclude_none=True))

    @app.get("/admin/sandbox/workspaces")
    async def admin_sandbox_workspaces(authorization: str | None = Header(default=None)) -> JSONResponse:
        _require_admin_auth(expected=resolved_admin_key, authorization=authorization)
        refs = (
            await resolved_workspace_service.list_refs()
            if resolved_workspace_service is not None
            else [_workspace_ref_from_record(item) for item in await runtime._sandbox_manager.list_workspaces()]
        )
        return JSONResponse(AdminSandboxWorkspaceListResponse(workspaces=refs).model_dump(mode="json", exclude_none=True))

    @app.get("/admin/sandbox/workspace")
    async def admin_sandbox_workspace_get(request: Request, authorization: str | None = Header(default=None)) -> JSONResponse:
        _require_admin_auth(expected=resolved_admin_key, authorization=authorization)
        req = _parse_admin_sandbox_workspace_query(request)
        if resolved_workspace_service is not None:
            ref = await resolved_workspace_service.get_ref(agent_id=req.agent_id, session_key=req.session_key)
        else:
            record = await runtime._sandbox_manager.get_workspace(agent_id=req.agent_id, session_key=req.session_key)
            ref = _workspace_ref_from_record(record) if record is not None else None
        if ref is None:
            raise HTTPException(status_code=404, detail="workspace not found")
        return JSONResponse(ref.model_dump(mode="json", exclude_none=True))

    @app.get("/admin/sandbox/events")
    async def admin_sandbox_events(request: Request, authorization: str | None = Header(default=None)) -> JSONResponse:
        _require_admin_auth(expected=resolved_admin_key, authorization=authorization)
        req = _parse_admin_sandbox_events_query(request)
        events = (
            await resolved_workspace_service.list_workspace_events(
                agent_id=req.agent_id,
                session_key=req.session_key,
                limit=req.limit,
            )
            if resolved_workspace_service is not None
            else await resolved_workspace_event_store.list(
                session_partition_key=_session_partition_key(agent_id=req.agent_id, session_key=req.session_key),
                limit=req.limit,
            )
        )
        return JSONResponse({"events": [item.model_dump(mode="json", exclude_none=True) for item in events]})

    @app.post("/admin/sandbox/workspace/hibernate")
    async def admin_sandbox_workspace_hibernate(request: Request, authorization: str | None = Header(default=None)) -> JSONResponse:
        _require_admin_auth(expected=resolved_admin_key, authorization=authorization)
        req = AdminSandboxWorkspaceRequest.model_validate(await request.json())
        if resolved_workspace_service is not None:
            if not resolved_workspace_service.config.enabled:
                raise HTTPException(status_code=404, detail="sandbox is disabled")
            ref = await resolved_workspace_service.hibernate_ref(
                agent_id=req.agent_id,
                session_key=req.session_key,
                event_context=_workspace_event_context(
                    agent_id=req.agent_id,
                    session_key=req.session_key,
                    actor="admin_api",
                ),
            )
            return JSONResponse(ref.model_dump(mode="json", exclude_none=True))
        policy = runtime.sandbox_policy_for_agent(req.agent_id)
        if policy.mode == "disabled":
            raise HTTPException(status_code=404, detail="sandbox is disabled")
        before = await runtime._sandbox_manager.get_workspace(agent_id=req.agent_id, session_key=req.session_key)
        if before is not None:
            await _append_workspace_event(
                store=resolved_workspace_event_store,
                type_="anyagent.sandbox.workspace.checkpointing",
                record=before,
                actor="admin_api",
            )
        try:
            record = await runtime._sandbox_manager.hibernate(
                policy=policy,
                agent_id=req.agent_id,
                session_key=req.session_key,
            )
        except RuntimeError as exc:
            if before is not None:
                await _append_workspace_event(
                    store=resolved_workspace_event_store,
                    type_="anyagent.sandbox.workspace.checkpoint_failed",
                    record=before,
                    actor="admin_api",
                    failure_code="checkpoint_failed",
                    failure_message=str(exc),
                )
            raise HTTPException(status_code=500, detail=str(exc)) from exc
        await _append_workspace_event(
            store=resolved_workspace_event_store,
            type_="anyagent.sandbox.workspace.checkpointed",
            record=record,
            actor="admin_api",
        )
        await _append_workspace_event(
            store=resolved_workspace_event_store,
            type_="anyagent.sandbox.workspace.hibernated",
            record=record,
            actor="admin_api",
        )
        return JSONResponse(_workspace_ref_from_record(record).model_dump(mode="json", exclude_none=True))

    @app.delete("/admin/sandbox/workspace")
    async def admin_sandbox_workspace_delete(request: Request, authorization: str | None = Header(default=None)) -> JSONResponse:
        _require_admin_auth(expected=resolved_admin_key, authorization=authorization)
        req = _parse_admin_sandbox_workspace_query(request)
        if resolved_workspace_service is not None:
            await resolved_workspace_service.delete(
                agent_id=req.agent_id,
                session_key=req.session_key,
                event_context=_workspace_event_context(
                    agent_id=req.agent_id,
                    session_key=req.session_key,
                    actor="admin_api",
                ),
            )
        else:
            await runtime._sandbox_manager.destroy_workspace(agent_id=req.agent_id, session_key=req.session_key)
        return JSONResponse({"ok": True, "deleted": True})

    @app.delete("/admin/credentials/{credential_id}")
    async def admin_credentials_delete(credential_id: str, authorization: str | None = Header(default=None)) -> JSONResponse:
        _require_admin_auth(expected=resolved_admin_key, authorization=authorization)
        store = _require_credential_store(runtime._credential_store)
        try:
            deleted = await store.delete(credential_id)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        except ReadOnlyCredentialStoreError as exc:
            raise HTTPException(status_code=501, detail=str(exc)) from exc
        resp = AdminCredentialDeleteResponse(ok=True, deleted=deleted, credential_id=credential_id)
        return JSONResponse(resp.model_dump())

    return app


async def create_tool_runtime_app_async(
    *,
    workspace_dir: str | Path = ".",
    internal_key: str | None = None,
    admin_api_key: str | None = None,
    sandbox_root_dir: str | Path | None = None,
    credential_store: CredentialResolver | None = None,
    plugin_roots: list[str | Path] | None = None,
    plugins_fail_open: bool | None = None,
    workspace_runtime: WorkspaceRuntimeAssembly | None = None,
    config: ToolRuntimeServerConfig | None = None,
) -> FastAPI:
    if config is None:
        load_workspace_runtime_environment(Path(workspace_dir).expanduser().resolve())
        server_config = build_tool_runtime_server_config(
            workspace_dir=workspace_dir,
            internal_key=internal_key,
            admin_api_key=admin_api_key,
            sandbox_root_dir=sandbox_root_dir,
            plugin_roots=plugin_roots,
            plugins_fail_open=plugins_fail_open,
        )
    else:
        server_config = config
    resolved_workspace_runtime = workspace_runtime
    if resolved_workspace_runtime is None and server_config.workspace_runtime is not None:
        resolved_workspace_runtime = await build_workspace_runtime(server_config.workspace_runtime)
    return create_tool_runtime_app(
        credential_store=credential_store,
        workspace_runtime=resolved_workspace_runtime,
        config=server_config,
    )


async def _sandbox_health(
    *,
    runtime: InProcessToolRuntimeService,
    sandbox_root_dir: str | Path | None,
) -> AdminSandboxWorkspaceHealthResponse:
    refs = [_workspace_ref_from_record(item) for item in await runtime._sandbox_manager.list_workspaces()]
    sandbox_modes = sorted({pack.spec.sandbox.mode for pack in runtime._catalog.packs.values()})
    persistence_modes = sorted(
        {
            _effective_filesystem_policy(pack).persistence_mode
            for pack in runtime._catalog.packs.values()
        }
    )
    workspace_roots = sorted(
        {
            str(_effective_filesystem_policy(pack).workspace_root)
            for pack in runtime._catalog.packs.values()
        }
    )
    runtime_states: dict[str, int] = {}
    for ref in refs:
        state = ref.runtime_diagnostics.state if ref.runtime_diagnostics is not None else None
        if state:
            runtime_states[state] = runtime_states.get(state, 0) + 1
    return AdminSandboxWorkspaceHealthResponse(
        enabled=any(mode != "disabled" for mode in sandbox_modes),
        backend="local_unsafe",
        metadata_backend="local_reference",
        lease_backend="none",
        snapshot_backend="local_reference",
        sandbox_mode=",".join(sandbox_modes) if sandbox_modes else "disabled",
        persistence_mode=",".join(persistence_modes) if persistence_modes else "ephemeral",
        workspace_root=",".join(workspace_roots) if workspace_roots else "/workspace",
        workspace_count=len(refs),
        sandbox_root_dir=str(Path(sandbox_root_dir).expanduser().resolve()) if sandbox_root_dir is not None else None,
        runtime_providers=["local_unsafe"] if refs else [],
        runtime_states=runtime_states,
    )


async def _workspace_service_health(service: WorkspaceService) -> AdminSandboxWorkspaceHealthResponse:
    return AdminSandboxWorkspaceHealthResponse.model_validate((await service.health()).model_dump())


def _parse_admin_sandbox_workspace_query(request: Request) -> AdminSandboxWorkspaceRequest:
    try:
        return AdminSandboxWorkspaceRequest.model_validate(dict(request.query_params))
    except ValidationError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


def _parse_admin_sandbox_events_query(request: Request) -> AdminSandboxWorkspaceEventsRequest:
    try:
        return AdminSandboxWorkspaceEventsRequest.model_validate(dict(request.query_params))
    except ValidationError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


_WORKSPACE_EVENT_TYPES = {
    "anyagent.sandbox.workspace.restoring",
    "anyagent.sandbox.workspace.restored",
    "anyagent.sandbox.workspace.checkpointing",
    "anyagent.sandbox.workspace.checkpointed",
    "anyagent.sandbox.workspace.hibernated",
    "anyagent.sandbox.workspace.restore_failed",
    "anyagent.sandbox.workspace.checkpoint_failed",
}


def _workspace_ref_from_record(record: Any) -> AdminSandboxWorkspaceRef:
    ref = AdminSandboxWorkspaceRef.model_validate(record.model_dump())
    return ref.model_copy(
        update={
            "runtime_diagnostics": AdminSandboxRuntimeDiagnostics(
                provider="local_unsafe",
                sandbox_id=record.sandbox_id,
                state=record.state,
            )
        }
    )


def _effective_filesystem_policy(pack: Any) -> FileSystemSandboxPolicy:
    filesystem = getattr(pack.spec.sandbox, "filesystem", None)
    return filesystem if isinstance(filesystem, FileSystemSandboxPolicy) else FileSystemSandboxPolicy()


async def _append_workspace_event(
    *,
    store: WorkspaceEventStore,
    type_: str,
    record: Any,
    actor: str | None = None,
    failure_code: str | None = None,
    failure_message: str | None = None,
) -> AnyAgentWorkspaceLifecycleEvent:
    if type_ not in _WORKSPACE_EVENT_TYPES:
        raise ValueError(f"unsupported workspace lifecycle event type: {type_}")
    event = AnyAgentWorkspaceLifecycleEvent(
        type=type_,
        response_id=f"workspace:{record.session_partition_key}",
        session_partition_key=record.session_partition_key,
        workspace_id=record.workspace_id,
        generation=record.generation,
        sandbox_id=record.sandbox_id,
        snapshot_uri=record.snapshot_uri,
        snapshot_bytes=record.snapshot_bytes,
        audit_ref=f"workspace:{record.session_partition_key}:{actor}" if actor else None,
        failure_code=failure_code,
        failure_message=failure_message,
        runtime_diagnostics=AdminSandboxRuntimeDiagnostics(
            provider="local_unsafe",
            sandbox_id=record.sandbox_id,
            state=record.state,
        ),
    )
    return await store.append(event)


def _session_partition_key(*, agent_id: str, session_key: str) -> str:
    return f"{agent_id}::{session_key}"


def _workspace_event_context(*, agent_id: str, session_key: str, actor: str) -> WorkspaceEventContext:
    return WorkspaceEventContext(
        response_id=f"workspace:{_session_partition_key(agent_id=agent_id, session_key=session_key)}",
        audit_ref=f"workspace:{_session_partition_key(agent_id=agent_id, session_key=session_key)}:{actor}",
        actor=actor,
    )


def _resolve_plugin_roots(plugin_roots: tuple[str | Path, ...] | list[str | Path] | None, *, workspace: Path) -> list[Path]:
    raw_items: list[str | Path] = []
    if plugin_roots is not None:
        raw_items.extend(plugin_roots)

    roots: list[Path] = []
    seen: set[str] = set()
    for raw_item in raw_items:
        path = Path(raw_item).expanduser()
        if not path.is_absolute():
            path = workspace / path
        resolved = path.resolve()
        key = str(resolved)
        if key in seen:
            continue
        seen.add(key)
        roots.append(resolved)
    return roots


def _build_default_workspace_event_store(*, config: ToolRuntimeServerConfig, workspace: Path) -> WorkspaceEventStore:
    backend = config.workspace_event_backend
    root_dir = config.workspace_event_root_dir
    max_events = config.workspace_event_max_buffer
    if root_dir is not None and not Path(root_dir).expanduser().is_absolute():
        root_dir = str(workspace / root_dir)
    return build_workspace_event_store(backend=backend, root_dir=root_dir, max_events=max_events)


def _load_tool_runtime_plugins(
    *,
    runtime: InProcessToolRuntimeService,
    roots: list[Path],
    fail_open: bool,
) -> tuple[list[dict[str, Any]], list[dict[str, str]]]:
    if not roots:
        return [], []

    tools_by_plugin: dict[str, list[Any]] = {}

    loaded, errors = load_plugins_from_roots(
        roots,
        api_factory=lambda manifest, plugin_dir, config: _build_tool_runtime_plugin_api(
            runtime=runtime,
            manifest_id=manifest.plugin_id,
            config=config,
            tools_by_plugin=tools_by_plugin,
        ),
    )
    loaded_payload = [
        {
            "plugin_id": item.manifest.plugin_id,
            "description": item.manifest.description,
            "channels": list(item.manifest.channels),
            "plugin_dir": str(item.plugin_dir),
            "entrypoint": item.manifest.entrypoint or "plugin.py:register",
            "tools": [
                PluginToolRef(
                    name=tool.name,
                    category=tool.category,
                    kind=tool.kind,
                    description=tool.description,
                ).model_dump(mode="json", exclude_none=True)
                for tool in tools_by_plugin.get(item.manifest.plugin_id, [])
            ],
            "declared_skills": list(item.declared_skills),
            "declared_mcp_servers": list(item.declared_mcp_servers),
            "declared_middlewares": list(item.manifest.middlewares),
            "declared_hooks": sorted(item.manifest.hooks),
            "cite": {
                "manifest": str(item.plugin_dir / "plugin.json"),
                "entrypoint": str(item.plugin_dir / _entrypoint_path(item.manifest.entrypoint or "plugin.py:register")),
            },
            "docs": _resolve_plugin_refs(item.plugin_dir, item.manifest.docs),
            "schemas": _resolve_plugin_refs(item.plugin_dir, item.manifest.schemas),
            "tests": _resolve_plugin_refs(item.plugin_dir, item.manifest.tests),
        }
        for item in loaded
    ]
    error_payload = [{"plugin_dir": plugin_dir, "reason": reason} for plugin_dir, reason in errors]
    for item in error_payload:
        logger.error("plugin load error: %s: %s", item["plugin_dir"], item["reason"])
    if error_payload and not fail_open:
        raise RuntimeError(
            f"plugin load failed ({len(error_payload)} errors); set TOOL_RUNTIME_PLUGINS_FAIL_OPEN=1 to ignore"
        )
    if loaded_payload:
        logger.info("plugins loaded: %s", ", ".join(sorted(item["plugin_id"] for item in loaded_payload)))
    return loaded_payload, error_payload


def _build_tool_runtime_plugin_api(
    *,
    runtime: InProcessToolRuntimeService,
    manifest_id: str,
    config: dict[str, Any],
    tools_by_plugin: dict[str, list[Any]],
) -> ToolRuntimePluginAPI:
    registered_tools: list[Any] = []
    tools_by_plugin[manifest_id] = registered_tools
    return ToolRuntimePluginAPI(
        host_kind="tool_runtime",
        plugin_id=manifest_id,
        config=config,
        registry=runtime._registry,
        registered_tools=registered_tools,
    )


def _entrypoint_path(entrypoint: str) -> Path:
    relpath, _sep, _attr = entrypoint.partition(":")
    return Path(relpath)


def _resolve_plugin_refs(plugin_dir: Path, refs: list[str]) -> list[str]:
    resolved: list[str] = []
    seen: set[str] = set()
    for raw in refs:
        if not isinstance(raw, str) or not raw.strip():
            continue
        value = raw.strip()
        if "://" in value:
            ref = value
        else:
            path = Path(value)
            if path.is_absolute():
                ref = str(path)
            else:
                ref = str(plugin_dir / path)
        if ref in seen:
            continue
        seen.add(ref)
        resolved.append(ref)
    return resolved


def _require_internal_auth(*, expected: str | None, authorization: str | None) -> None:
    if not expected:
        return
    prefix = "bearer "
    if not isinstance(authorization, str) or not authorization.lower().startswith(prefix):
        raise HTTPException(status_code=401, detail="missing bearer authorization")
    token = authorization[len(prefix) :].strip()
    if token != expected:
        raise HTTPException(status_code=401, detail="invalid api key")


def _require_admin_auth(*, expected: str | None, authorization: str | None) -> None:
    if not expected:
        raise HTTPException(status_code=404, detail="admin api disabled")
    _require_internal_auth(expected=expected, authorization=authorization)


def _require_credential_store(store: CredentialResolver | None) -> CredentialStore:
    if not isinstance(store, CredentialStore):
        raise HTTPException(status_code=501, detail="credential store does not support admin operations")
    return store
