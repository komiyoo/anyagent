from __future__ import annotations

from fastapi import APIRouter, Header, Request
from fastapi.responses import JSONResponse

from anyagent.protocol.agent_api_internal import InternalAgentsListResponse
from anyagent.server.handlers.agent_views import _agent_detail_response, _agent_list_item
from anyagent.server.handlers.auth import _require_user_auth


def create_internal_agents_router() -> APIRouter:
    router = APIRouter()

    @router.get("/internal/agents")
    async def internal_agents_list(
        req: Request,
        include_unexposed: bool = False,
        authorization: str | None = Header(default=None),
    ) -> JSONResponse:
        state = req.app.state.anyagent
        _require_user_auth(state, authorization)
        agents = [
            _agent_list_item(pack)
            for pack in sorted(state.catalog.packs.values(), key=lambda item: item.agent_id)
            if include_unexposed or pack.spec.exposed
        ]
        return JSONResponse(InternalAgentsListResponse(agents=agents).model_dump(exclude_none=True))

    @router.get("/internal/agents/{agent_id}")
    async def internal_agent_detail(
        req: Request,
        agent_id: str,
        include_prompt: bool = False,
        authorization: str | None = Header(default=None),
    ) -> JSONResponse:
        state = req.app.state.anyagent
        _require_user_auth(state, authorization)
        pack = state.require_pack(agent_id, external=True)
        resp = _agent_detail_response(pack, include_prompt=include_prompt)
        return JSONResponse(resp.model_dump(exclude_none=True))

    return router
