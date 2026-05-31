from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Request

from anyagent.protocol.health import HealthResponse


def create_system_router() -> APIRouter:
    router = APIRouter()

    @router.get("/healthz")
    async def healthz(req: Request) -> dict[str, Any]:
        state = req.app.state.anyagent
        return HealthResponse(
            ok=True,
            workspace=str(state.workspace_dir),
            agent_ids=sorted(state.catalog.packs.keys()),
        ).model_dump(exclude_none=True)

    return router
