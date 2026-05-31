from __future__ import annotations

from fastapi import APIRouter, Header, Request
from fastapi.responses import JSONResponse

from anyagent.protocol.agent_api_internal import InternalToolCatalogItem, InternalToolCatalogResponse
from anyagent.protocol.tool_runtime import CancelRequest, ExecuteRequest, ManifestRequest
from anyagent.server.handlers.auth import _require_internal_auth, _require_user_auth
from anyagent.server.handlers.tool_context import _build_agent_manifest_request, _split_csv


def create_internal_tools_router() -> APIRouter:
    router = APIRouter()

    @router.get("/internal/tools/catalog")
    async def internal_tools_catalog(
        req: Request,
        agent_id: str = "main",
        session_key: str = "studio-catalog",
        requested_tool_names: str | None = None,
        authorization: str | None = Header(default=None),
    ) -> JSONResponse:
        state = req.app.state.anyagent
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

    @router.post("/internal/tools/manifest")
    async def internal_tools_manifest(req: Request, authorization: str | None = Header(default=None)) -> JSONResponse:
        state = req.app.state.anyagent
        _require_internal_auth(state, authorization)
        payload = ManifestRequest.model_validate(await req.json())
        resp = await state.runtime.manifest(payload)
        return JSONResponse(resp.model_dump(exclude_none=True, by_alias=True))

    @router.post("/internal/tools/execute")
    async def internal_tools_execute(req: Request, authorization: str | None = Header(default=None)) -> JSONResponse:
        state = req.app.state.anyagent
        _require_internal_auth(state, authorization)
        payload = ExecuteRequest.model_validate(await req.json())
        resp = await state.runtime.execute(payload)
        status_code = 200
        if getattr(resp, "status", None) == "error" and getattr(resp, "error", None) is not None:
            if resp.error.code == "toolset_version_mismatch":
                status_code = 409
        return JSONResponse(resp.model_dump(exclude_none=True), status_code=status_code)

    @router.post("/internal/tools/cancel")
    async def internal_tools_cancel(req: Request, authorization: str | None = Header(default=None)) -> JSONResponse:
        state = req.app.state.anyagent
        _require_internal_auth(state, authorization)
        payload = CancelRequest.model_validate(await req.json())
        resp = await state.runtime.cancel(payload)
        return JSONResponse(resp.model_dump(exclude_none=True))

    return router
