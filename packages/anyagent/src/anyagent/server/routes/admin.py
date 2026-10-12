from __future__ import annotations

import hashlib
import json

from fastapi import APIRouter, Header, HTTPException, Request
from fastapi.responses import JSONResponse

from anyagent.protocol.credential_vault import (
    AdminCredentialDeleteResponse,
    AdminCredentialListResponse,
    AdminCredentialRef,
    AdminCredentialSetRequest,
)
from anyagent.protocol.admin_storage import (
    AdminSandboxWorkspaceListResponse,
    AdminSandboxWorkspaceReclaimResponse,
    AdminSandboxWorkspaceSnapshotItem,
    AdminSandboxWorkspaceSnapshotsResponse,
)
from anyagent.protocol.agent_api_internal import (
    AdminAgentCreateRequest,
    AdminAgentCreateResponse,
    AdminAgentConfigUpdateRequest,
    AdminAgentSkillsUpdateRequest,
    AdminMcpServerEnableRequest,
    AdminMcpServerEnableResponse,
    AdminMcpServerTestResponse,
    AdminToolCatalogResponse,
    AdminWorkspaceAgentFilesResponse,
    AdminWorkspaceAgentFileUpdateRequest,
    AdminWorkspaceAgentFileUpdateResponse,
    AdminSkillImportRequest,
    AdminSkillImportResponse,
    AdminSkillRegistryInstallRequest,
    InternalToolCatalogItem,
    WorkspaceAgentFileKind,
)
from anyagent.protocol.plugins import LoadedPluginCatalogItem, PluginCatalogResponse, PluginLoadErrorItem
from anyagent.server.handlers.admin_views import (
    _admin_mcp_servers_response,
    _admin_sandbox_workspace_ref,
    _find_sandbox_workspace_ref,
    _mcp_transport_value,
    _read_agent_mcp_json_payload,
    _split_session_partition_key,
)
from anyagent.server.handlers.agent_files import (
    _create_agent_pack,
    _restore_workspace_agent_file,
    _update_agent_config,
    _update_agent_default_skills,
    _validate_workspace_agent_file_text,
    _workspace_agent_file,
    _workspace_agent_file_path,
    _write_workspace_agent_file,
)
from anyagent.server.handlers.agent_views import _agent_detail_response
from anyagent.server.handlers.auth import _require_admin_auth
from anyagent.server.handlers.skill_install import (
    _check_agent_local_skill_update,
    _import_agent_local_skill,
    _install_agent_local_skill_from_registry,
    _install_request_from_skill_source_metadata,
    _read_skill_source_metadata,
    _resolve_agent_skill_dir,
)
from anyagent.server.handlers.storage_health import _build_storage_health_payload
from anyagent.server.plugins.capabilities import build_plugin_capability_matrix
from anyagent.server.security import (
    InMemoryCredentialStore,
    build_credential_backend_capability_matrix,
    emit_credential_audit_for_store,
)


def create_admin_router() -> APIRouter:
    router = APIRouter()

    @router.post("/admin/credentials")
    async def admin_set_credential(
        req: Request,
        authorization: str | None = Header(default=None),
    ) -> JSONResponse:
        state = req.app.state.anyagent
        _require_admin_auth(state, authorization)
        body = await req.json()
        model = AdminCredentialSetRequest.model_validate(body)
        if isinstance(state.credentials, InMemoryCredentialStore):
            ref = await state.credentials.set(model)
        else:
            await state.credentials.set(
                credential_id=model.credential_id,
                kind=model.kind,
                value=model.value,
                scope=model.scope,
                metadata=model.metadata,
                expires_at=model.expires_at,
                rotate_before=model.rotate_before,
            )
            ref = AdminCredentialRef(
                credential_id=model.credential_id,
                kind=model.kind,
                scope=model.scope,
                metadata=model.metadata,
                expires_at=model.expires_at,
                rotate_before=model.rotate_before,
            )
            await emit_credential_audit_for_store(
                state.credentials,
                operation="set",
                credential_id=model.credential_id,
                kind=model.kind,
                scope=model.scope,
            )
        return JSONResponse(ref.model_dump(mode="json", exclude_none=True))

    @router.get("/admin/credentials")
    async def admin_list_credentials(
        req: Request,authorization: str | None = Header(default=None)) -> JSONResponse:
        state = req.app.state.anyagent
        _require_admin_auth(state, authorization)
        if isinstance(state.credentials, InMemoryCredentialStore):
            resp = await state.credentials.list()
        else:
            refs = await state.credentials.list_refs()
            resp = AdminCredentialListResponse(credentials=[AdminCredentialRef.model_validate(ref) for ref in refs])
        return JSONResponse(resp.model_dump(mode="json", exclude_none=True))

    @router.get("/admin/credentials/capabilities")
    async def admin_credential_capabilities(
        req: Request,authorization: str | None = Header(default=None)) -> JSONResponse:
        state = req.app.state.anyagent
        _require_admin_auth(state, authorization)
        matrix = build_credential_backend_capability_matrix()
        return JSONResponse(matrix.model_dump(exclude_none=True))

    @router.get("/admin/plugins/catalog")
    async def admin_plugins_catalog(
        req: Request,authorization: str | None = Header(default=None)) -> JSONResponse:
        state = req.app.state.anyagent
        _require_admin_auth(state, authorization)
        response = PluginCatalogResponse(
            plugin_roots=[str(root) for root in state.plugin_roots],
            loaded=[LoadedPluginCatalogItem.model_validate(item) for item in state.loaded_plugin_catalog],
            errors=[PluginLoadErrorItem.model_validate(item) for item in state.plugin_errors],
        )
        return JSONResponse(response.model_dump(mode="json", exclude_none=True))

    @router.get("/admin/plugins/capabilities")
    async def admin_plugins_capabilities(
        req: Request,authorization: str | None = Header(default=None)) -> JSONResponse:
        state = req.app.state.anyagent
        _require_admin_auth(state, authorization)
        matrix = build_plugin_capability_matrix()
        return JSONResponse(matrix.model_dump(mode="json", exclude_none=True))

    @router.get("/admin/storage/health")
    async def admin_storage_health(
        req: Request,authorization: str | None = Header(default=None)) -> JSONResponse:
        state = req.app.state.anyagent
        _require_admin_auth(state, authorization)
        payload = await _build_storage_health_payload(state)
        return JSONResponse(payload)

    @router.get("/admin/tools/catalog")
    async def admin_tools_catalog(
        req: Request,authorization: str | None = Header(default=None)) -> JSONResponse:
        state = req.app.state.anyagent
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

    @router.get("/admin/sandboxes")
    async def admin_sandboxes(
        req: Request,authorization: str | None = Header(default=None)) -> JSONResponse:
        state = req.app.state.anyagent
        _require_admin_auth(state, authorization)
        records = await state.sandbox_manager.list_workspaces()
        resp = AdminSandboxWorkspaceListResponse(
            workspaces=[_admin_sandbox_workspace_ref(record) for record in records]
        )
        return JSONResponse(resp.model_dump(exclude_none=True))

    @router.get("/admin/sandboxes/workspaces/{workspace_id}/snapshots")
    async def admin_sandbox_workspace_snapshots(
        req: Request,
        workspace_id: str,
        authorization: str | None = Header(default=None),
    ) -> JSONResponse:
        state = req.app.state.anyagent
        _require_admin_auth(state, authorization)
        ref = await _find_sandbox_workspace_ref(state, workspace_id=workspace_id)
        snapshots = [
            AdminSandboxWorkspaceSnapshotItem.model_validate(item)
            for item in state.sandbox_manager.workspace_service.list_snapshots(
                session_partition_key=ref.session_partition_key
            )
        ]
        if not snapshots and ref.snapshot_uri:
            snapshots = [
                AdminSandboxWorkspaceSnapshotItem(
                    workspace_id=ref.workspace_id,
                    session_partition_key=ref.session_partition_key,
                    generation=ref.generation,
                    snapshot_uri=ref.snapshot_uri,
                    snapshot_digest=ref.snapshot_digest,
                    snapshot_bytes=ref.snapshot_bytes,
                )
            ]
        resp = AdminSandboxWorkspaceSnapshotsResponse(
            workspace_id=ref.workspace_id,
            session_partition_key=ref.session_partition_key,
            snapshots=snapshots,
        )
        return JSONResponse(resp.model_dump(exclude_none=True))

    @router.post("/admin/sandboxes/workspaces/{workspace_id}/reclaim")
    async def admin_sandbox_workspace_reclaim(
        req: Request,
        workspace_id: str,
        authorization: str | None = Header(default=None),
    ) -> JSONResponse:
        state = req.app.state.anyagent
        _require_admin_auth(state, authorization)
        ref = await _find_sandbox_workspace_ref(state, workspace_id=workspace_id)
        agent_id, session_key = _split_session_partition_key(ref.session_partition_key)
        await state.sandbox_manager.destroy_workspace(agent_id=agent_id, session_key=session_key)
        resp = AdminSandboxWorkspaceReclaimResponse(
            ok=True,
            workspace_id=ref.workspace_id,
            session_partition_key=ref.session_partition_key,
            reclaimed=True,
        )
        return JSONResponse(resp.model_dump(exclude_none=True))

    @router.post("/admin/workspace/agents")
    async def admin_workspace_agent_create(
        req: Request,
        authorization: str | None = Header(default=None),
    ) -> JSONResponse:
        state = req.app.state.anyagent
        _require_admin_auth(state, authorization)
        create_req = AdminAgentCreateRequest.model_validate(await req.json())
        _create_agent_pack(state=state, request=create_req)
        try:
            state.reload_catalog()
        except Exception as e:  # noqa: BLE001
            raise HTTPException(status_code=400, detail=f"workspace reload failed: {e}") from e
        pack = state.require_pack(create_req.agent_id, external=False)
        resp = AdminAgentCreateResponse(
            agent=_agent_detail_response(pack, include_prompt=True, config=state.config),
            reloaded_agent_ids=sorted(state.catalog.packs.keys()),
        )
        return JSONResponse(resp.model_dump(exclude_none=True))

    @router.delete("/admin/credentials/{credential_id}")
    async def admin_delete_credential(
        req: Request,credential_id: str, authorization: str | None = Header(default=None)) -> JSONResponse:
        state = req.app.state.anyagent
        _require_admin_auth(state, authorization)
        refs = await state.credentials.list_refs() if not isinstance(state.credentials, InMemoryCredentialStore) else []
        deleted = await state.credentials.delete(credential_id)
        if not isinstance(state.credentials, InMemoryCredentialStore):
            matching_refs = [AdminCredentialRef.model_validate(ref) for ref in refs if ref.get("credential_id") == credential_id]
            if matching_refs:
                for ref in matching_refs:
                    await emit_credential_audit_for_store(
                        state.credentials,
                        operation="delete",
                        credential_id=credential_id,
                        kind=ref.kind,
                        scope=ref.scope,
                        deleted=bool(deleted),
                    )
            else:
                await emit_credential_audit_for_store(state.credentials, operation="delete", credential_id=credential_id, deleted=bool(deleted))
        resp = AdminCredentialDeleteResponse(ok=True, deleted=bool(deleted), credential_id=credential_id)
        return JSONResponse(resp.model_dump())

    @router.get("/admin/workspace/agents/{agent_id}")
    async def admin_workspace_agent_detail(
        req: Request,
        agent_id: str,
        include_prompt: bool = False,
        authorization: str | None = Header(default=None),
    ) -> JSONResponse:
        state = req.app.state.anyagent
        _require_admin_auth(state, authorization)
        pack = state.require_pack(agent_id, external=False)
        return JSONResponse(_agent_detail_response(pack, include_prompt=include_prompt, config=state.config).model_dump(exclude_none=True))

    @router.get("/admin/workspace/agents/{agent_id}/files")
    async def admin_workspace_agent_files(
        req: Request,
        agent_id: str,
        authorization: str | None = Header(default=None),
    ) -> JSONResponse:
        state = req.app.state.anyagent
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

    @router.put("/admin/workspace/agents/{agent_id}/files/{kind}")
    async def admin_workspace_agent_file_update(
        agent_id: str,
        kind: WorkspaceAgentFileKind,
        req: Request,
        authorization: str | None = Header(default=None),
    ) -> JSONResponse:
        state = req.app.state.anyagent
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

    @router.get("/admin/workspace/agents/{agent_id}/mcp/servers")
    async def admin_workspace_agent_mcp_servers(
        req: Request,
        agent_id: str,
        authorization: str | None = Header(default=None),
    ) -> JSONResponse:
        state = req.app.state.anyagent
        _require_admin_auth(state, authorization)
        pack = state.require_pack(agent_id, external=False)
        return JSONResponse(_admin_mcp_servers_response(pack).model_dump(exclude_none=True))

    @router.put("/admin/workspace/agents/{agent_id}/mcp/servers/{server_label}/enabled")
    async def admin_workspace_agent_mcp_server_enabled(
        agent_id: str,
        server_label: str,
        req: Request,
        authorization: str | None = Header(default=None),
    ) -> JSONResponse:
        state = req.app.state.anyagent
        _require_admin_auth(state, authorization)
        pack = state.require_pack(agent_id, external=False)
        update = AdminMcpServerEnableRequest.model_validate(await req.json())
        before = _workspace_agent_file(pack, kind="mcp_json")
        path = _workspace_agent_file_path(pack, kind="mcp_json")
        payload = _read_agent_mcp_json_payload(pack)
        effective_config = pack.mcp_config
        effective_servers = {} if effective_config is None else effective_config.mcpServers
        current_server = effective_servers.get(server_label)
        if current_server is None:
            raise HTTPException(status_code=404, detail=f"unknown mcp server: {server_label}")
        servers = payload.setdefault("mcpServers", {})
        if not isinstance(servers, dict):
            raise HTTPException(status_code=400, detail="invalid mcp.json: mcpServers must be an object")
        next_server = current_server.model_dump(mode="json", exclude_none=True)
        next_server["enabled"] = bool(update.enabled)
        servers[server_label] = next_server
        next_text = json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
        previous_text = before.text
        previous_exists = before.exists
        _validate_workspace_agent_file_text(kind="mcp_json", text=next_text)
        _write_workspace_agent_file(path=path, text=next_text)
        try:
            state.reload_catalog()
            await state.mcp_managers.cleanup_agent(agent_id)
        except Exception as e:  # noqa: BLE001
            _restore_workspace_agent_file(path=path, text=previous_text, existed=previous_exists)
            raise HTTPException(status_code=400, detail=f"workspace reload failed: {e}") from e
        reloaded_pack = state.require_pack(agent_id, external=False)
        response = AdminMcpServerEnableResponse(
            agent_id=agent_id,
            server_label=server_label,
            enabled=bool(update.enabled),
            file=_workspace_agent_file(reloaded_pack, kind="mcp_json"),
            servers=_admin_mcp_servers_response(reloaded_pack),
            reloaded_agent_ids=sorted(state.catalog.packs.keys()),
        )
        return JSONResponse(response.model_dump(exclude_none=True))

    @router.post("/admin/workspace/agents/{agent_id}/mcp/servers/{server_label}/test")
    async def admin_workspace_agent_mcp_server_test(
        req: Request,
        agent_id: str,
        server_label: str,
        session_key: str | None = None,
        authorization: str | None = Header(default=None),
    ) -> JSONResponse:
        state = req.app.state.anyagent
        _require_admin_auth(state, authorization)
        pack = state.require_pack(agent_id, external=False)
        cfg = None if pack.mcp_config is None else pack.mcp_config.mcpServers.get(server_label)
        if cfg is None:
            raise HTTPException(status_code=404, detail=f"unknown mcp server: {server_label}")
        transport = _mcp_transport_value(cfg)
        if not cfg.enabled:
            response = AdminMcpServerTestResponse(
                agent_id=agent_id,
                server_label=server_label,
                ok=False,
                status="skipped",
                message="mcp server is disabled",
                transport=transport,
            )
            return JSONResponse(response.model_dump(exclude_none=True))
        assert pack.mcp_config is not None
        manager = await state.mcp_managers.get_manager(
            agent_id=agent_id,
            mcp_config=pack.mcp_config,
            credential_store=state.mcp_credentials,
        )
        try:
            server, tool_count = await manager.test_server_connection(server_label, session_key=session_key)
            transport = _mcp_transport_value(server.config) or transport
            response = AdminMcpServerTestResponse(
                agent_id=agent_id,
                server_label=server_label,
                ok=True,
                status="ready",
                transport=transport,
                tool_count=tool_count,
            )
        except Exception as e:  # noqa: BLE001
            response = AdminMcpServerTestResponse(
                agent_id=agent_id,
                server_label=server_label,
                ok=False,
                status="failed",
                message=str(e),
                transport=transport,
            )
        return JSONResponse(response.model_dump(exclude_none=True))

    @router.put("/admin/workspace/agents/{agent_id}/skills")
    async def admin_workspace_agent_skills_update(
        agent_id: str,
        req: Request,
        authorization: str | None = Header(default=None),
    ) -> JSONResponse:
        state = req.app.state.anyagent
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
            agent=_agent_detail_response(reloaded_pack, include_prompt=False, config=state.config),
            reloaded_agent_ids=sorted(state.catalog.packs.keys()),
        )
        return JSONResponse(resp.model_dump(exclude_none=True))

    @router.put("/admin/workspace/agents/{agent_id}/config")
    async def admin_workspace_agent_config_update(
        agent_id: str,
        req: Request,
        authorization: str | None = Header(default=None),
    ) -> JSONResponse:
        state = req.app.state.anyagent
        _require_admin_auth(state, authorization)
        pack = state.require_pack(agent_id, external=False)
        update = AdminAgentConfigUpdateRequest.model_validate(await req.json())
        agent_yaml_path = pack.root_dir / "agent.yaml"
        previous_text = agent_yaml_path.read_text(encoding="utf-8")
        _update_agent_config(pack=pack, request=update, aliases=set(state.config.models.aliases))
        try:
            state.reload_catalog()
        except Exception as e:  # noqa: BLE001
            agent_yaml_path.write_text(previous_text, encoding="utf-8")
            raise HTTPException(status_code=400, detail=f"workspace reload failed: {e}") from e
        reloaded_pack = state.require_pack(agent_id, external=False)
        resp = AdminAgentCreateResponse(
            agent=_agent_detail_response(reloaded_pack, include_prompt=False, config=state.config),
            reloaded_agent_ids=sorted(state.catalog.packs.keys()),
        )
        return JSONResponse(resp.model_dump(exclude_none=True))

    @router.post("/admin/workspace/agents/{agent_id}/skills/import")
    async def admin_workspace_agent_skill_import(
        agent_id: str,
        req: Request,
        authorization: str | None = Header(default=None),
    ) -> JSONResponse:
        state = req.app.state.anyagent
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

    @router.post("/admin/workspace/agents/{agent_id}/skills/install")
    async def admin_workspace_agent_skill_install(
        agent_id: str,
        req: Request,
        authorization: str | None = Header(default=None),
    ) -> JSONResponse:
        state = req.app.state.anyagent
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

    @router.get("/admin/workspace/agents/{agent_id}/skills/{directory_name}/update/check")
    async def admin_workspace_agent_skill_update_check(
        req: Request,
        agent_id: str,
        directory_name: str,
        authorization: str | None = Header(default=None),
    ) -> JSONResponse:
        state = req.app.state.anyagent
        _require_admin_auth(state, authorization)
        pack = state.require_pack(agent_id, external=False)
        resp = _check_agent_local_skill_update(pack=pack, directory_name=directory_name)
        return JSONResponse(resp.model_dump(exclude_none=True))

    @router.post("/admin/workspace/agents/{agent_id}/skills/{directory_name}/update/apply")
    async def admin_workspace_agent_skill_update_apply(
        req: Request,
        agent_id: str,
        directory_name: str,
        authorization: str | None = Header(default=None),
    ) -> JSONResponse:
        state = req.app.state.anyagent
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

    return router
