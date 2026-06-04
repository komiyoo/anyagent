from __future__ import annotations

import difflib
import hashlib
import uuid
from pathlib import Path

from fastapi import APIRouter, Header, HTTPException, Request
from fastapi.responses import JSONResponse

from anyagent.agent_runtime import build_prompt_envelope
from anyagent.agent_runtime.tool_loop import resolve_manifest_with_mcp
from anyagent.gateway.session import session_partition_key
from anyagent.model_config import apply_effective_model_to_body, resolve_effective_model_selection
from anyagent.protocol.agent_api_internal import InternalPromptBundlePreviewResponse
from anyagent.protocol.openai_responses import AnyAgentFunctionToolParam
from anyagent.protocol.prompt_versions import (
    PromptVersionCreateRequest,
    PromptVersionDiffResponse,
    PromptVersionResponse,
    PromptVersionRestoreResponse,
    PromptVersionsResponse,
    PromptVersionSnapshot,
    PromptVersionSource,
)
from anyagent.server.config.request_context import resolve_agent_id, resolve_session_key
from anyagent.server.config.request_validation import (
    ResponsesRequestValidationError,
    ensure_metadata_object,
    ensure_request_body_object,
    parse_function_tools,
)
from anyagent.server.handlers.auth import _require_admin_auth, _require_user_auth
from anyagent.server.handlers.context_providers import _build_context_provider_fragments
from anyagent.server.handlers.tool_context import (
    _build_prompt_environment_values,
    _build_server_tool_context,
    _select_skills,
)
from anyagent.server.responses.session_context import prepare_response_session_context


def create_internal_prompt_router() -> APIRouter:
    router = APIRouter()

    @router.post("/internal/prompt/bundle")
    async def internal_prompt_bundle_preview(
        req: Request,
        authorization: str | None = Header(default=None),
        x_agent_id: str | None = Header(default=None),
    ) -> JSONResponse:
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

        agent_id = resolve_agent_id(
            metadata=metadata if isinstance(metadata, dict) else None,
            x_agent_id=x_agent_id,
            model=body.get("model"),
        )
        pack = state.require_pack(agent_id, external=True)
        model_selection = resolve_effective_model_selection(workspace_config=state.models_config, pack=pack)
        apply_effective_model_to_body(body=body, selection=model_selection, workspace_config=state.models_config)
        session_key = resolve_session_key(
            metadata=metadata if isinstance(metadata, dict) else None,
            user=body.get("user"),
        )
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
            context_fragments=await _build_context_provider_fragments(
                pack=pack,
                agent_id=agent_id,
                session_key=session_key,
                body=body,
                metadata=metadata,
                workspace_dir=state.workspace_dir,
                tool_context=tool_context,
                selected_skills=selected_skills,
            ),
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

    @router.get("/internal/prompt/versions")
    async def internal_prompt_versions(
        req: Request,
        agent_id: str,
        limit: int = 100,
        authorization: str | None = Header(default=None),
    ) -> JSONResponse:
        state = req.app.state.anyagent
        _require_user_auth(state, authorization)
        state.require_pack(agent_id, external=False)
        versions = await state.prompt_version_store.list(agent_id=agent_id, limit=limit)
        return JSONResponse(PromptVersionsResponse(agent_id=agent_id, versions=versions).model_dump(exclude_none=True))

    @router.post("/internal/prompt/versions")
    async def internal_prompt_version_create(
        req: Request,
        authorization: str | None = Header(default=None),
    ) -> JSONResponse:
        state = req.app.state.anyagent
        _require_user_auth(state, authorization)
        create_req = PromptVersionCreateRequest.model_validate(await req.json())
        pack = state.require_pack(create_req.agent_id, external=False)
        snapshot = _prompt_version_snapshot(
            workspace_dir=state.workspace_dir,
            agent_id=pack.agent_id,
            agent_root=pack.root_dir,
            label=create_req.label,
        )
        snapshot = await state.prompt_version_store.append(snapshot)
        return JSONResponse(PromptVersionResponse(version=snapshot).model_dump(exclude_none=True))

    @router.get("/internal/prompt/versions/diff")
    async def internal_prompt_version_diff(
        req: Request,
        agent_id: str,
        from_version_id: str,
        to_version_id: str,
        authorization: str | None = Header(default=None),
    ) -> JSONResponse:
        state = req.app.state.anyagent
        _require_user_auth(state, authorization)
        before = await state.prompt_version_store.get(agent_id=agent_id, version_id=from_version_id)
        after = await state.prompt_version_store.get(agent_id=agent_id, version_id=to_version_id)
        if before is None:
            raise HTTPException(status_code=404, detail=f"unknown from_version_id: {from_version_id}")
        if after is None:
            raise HTTPException(status_code=404, detail=f"unknown to_version_id: {to_version_id}")
        payload = PromptVersionDiffResponse(
            agent_id=agent_id,
            from_version_id=from_version_id,
            to_version_id=to_version_id,
            diff=_prompt_version_diff(before, after),
        )
        return JSONResponse(payload.model_dump(exclude_none=True))

    @router.get("/internal/prompt/versions/{version_id}")
    async def internal_prompt_version_get(
        req: Request,
        agent_id: str,
        version_id: str,
        authorization: str | None = Header(default=None),
    ) -> JSONResponse:
        state = req.app.state.anyagent
        _require_user_auth(state, authorization)
        snapshot = await state.prompt_version_store.get(agent_id=agent_id, version_id=version_id)
        if snapshot is None:
            raise HTTPException(status_code=404, detail=f"unknown version_id: {version_id}")
        return JSONResponse(PromptVersionResponse(version=snapshot).model_dump(exclude_none=True))

    @router.post("/internal/prompt/versions/{version_id}/restore")
    async def internal_prompt_version_restore(
        req: Request,
        agent_id: str,
        version_id: str,
        authorization: str | None = Header(default=None),
    ) -> JSONResponse:
        state = req.app.state.anyagent
        _require_admin_auth(state, authorization)
        snapshot = await state.prompt_version_store.get(agent_id=agent_id, version_id=version_id)
        if snapshot is None:
            raise HTTPException(status_code=404, detail=f"unknown version_id: {version_id}")
        restored_paths = _restore_prompt_version_sources(workspace_dir=state.workspace_dir, snapshot=snapshot)
        state.reload_catalog()
        payload = PromptVersionRestoreResponse(agent_id=agent_id, version_id=version_id, restored_paths=restored_paths)
        return JSONResponse(payload.model_dump(exclude_none=True))

    return router


def _prompt_version_snapshot(
    *,
    workspace_dir: Path,
    agent_id: str,
    agent_root: Path,
    label: str | None,
) -> PromptVersionSnapshot:
    sources = [
        *_source_if_exists(kind="workspace_agents_md", path=workspace_dir / "AGENTS.md"),
        *_source_if_exists(kind="agent_agents_md", path=agent_root / "AGENTS.md"),
        *_source_if_exists(kind="agent_yaml", path=agent_root / "agent.yaml"),
        *_source_if_exists(kind="mcp_json", path=agent_root / "mcp.json"),
    ]
    combined = "\n".join(f"{item.kind}:{item.sha256}:{item.path}" for item in sources)
    return PromptVersionSnapshot(
        version_id=f"pv_{uuid.uuid4().hex[:16]}",
        agent_id=agent_id,
        label=label,
        sources=sources,
        combined_sha256=hashlib.sha256(combined.encode("utf-8", errors="replace")).hexdigest(),
    )


def _source_if_exists(*, kind: str, path: Path) -> list[PromptVersionSource]:
    if not path.is_file():
        return []
    text = path.read_text(encoding="utf-8")
    return [
        PromptVersionSource(
            kind=kind,  # type: ignore[arg-type]
            path=str(path.resolve()),
            sha256=hashlib.sha256(text.encode("utf-8", errors="replace")).hexdigest(),
            text=text,
        )
    ]


def _prompt_version_diff(before: PromptVersionSnapshot, after: PromptVersionSnapshot) -> str:
    before_text = _combined_prompt_version_text(before)
    after_text = _combined_prompt_version_text(after)
    return "".join(
        difflib.unified_diff(
            before_text.splitlines(keepends=True),
            after_text.splitlines(keepends=True),
            fromfile=before.version_id,
            tofile=after.version_id,
        )
    )


def _combined_prompt_version_text(snapshot: PromptVersionSnapshot) -> str:
    chunks: list[str] = []
    for source in sorted(snapshot.sources, key=lambda item: item.kind):
        chunks.append(f"### {source.kind} {source.path}\n")
        chunks.append(source.text)
        if not source.text.endswith("\n"):
            chunks.append("\n")
    return "".join(chunks)


def _restore_prompt_version_sources(*, workspace_dir: Path, snapshot: PromptVersionSnapshot) -> list[str]:
    workspace_root = workspace_dir.expanduser().resolve()
    restored: list[str] = []
    for source in snapshot.sources:
        path = Path(source.path).expanduser().resolve()
        if workspace_root not in [path, *path.parents]:
            raise HTTPException(status_code=400, detail=f"snapshot source outside workspace: {source.path}")
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(source.text, encoding="utf-8")
        restored.append(str(path))
    return restored
