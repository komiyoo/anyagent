from __future__ import annotations

from contextlib import asynccontextmanager
from typing import Any

from fastapi import FastAPI

from anyagent.agent_runtime import run_tool_loop_nonstream, run_tool_loop_stream_live
from anyagent.agent_runtime.model_providers import get_default_model_provider
from anyagent.tool_runtime import fetch_manifest_tools

from .distributed_responses import create_distributed_responses_router
from .distributed_runtime import (
    DistributedAgentRuntimeConfig,
    ModelProviderFactory,
    StorageRuntimeFactory,
    close_distributed_agent_runtime,
    create_distributed_agent_runtime,
)
from .internal_events import create_internal_events_router
from .internal_replay import create_internal_replay_router
from .internal_skills import create_internal_skills_router
from .responses_optional import create_optional_responses_router


def create_distributed_agent_app(
    *,
    api_key: str,
    runtime_config: DistributedAgentRuntimeConfig,
    storage_factory: StorageRuntimeFactory,
    settings: Any = None,
    enable_keyed_serialization: bool = True,
    model_provider_factory: ModelProviderFactory = get_default_model_provider,
    fetch_manifest_tools_fn=fetch_manifest_tools,
    run_tool_loop_nonstream_fn=run_tool_loop_nonstream,
    run_tool_loop_stream_live_fn=run_tool_loop_stream_live,
) -> FastAPI:
    @asynccontextmanager
    async def lifespan(app: FastAPI):
        runtime = await create_distributed_agent_runtime(
            config=runtime_config,
            storage_factory=storage_factory,
            settings=settings,
            model_provider_factory=model_provider_factory,
        )
        runtime.attach_to_app_state(app.state)
        try:
            yield
        finally:
            await close_distributed_agent_runtime(runtime)

    app = FastAPI(lifespan=lifespan)

    @app.get("/healthz")
    async def healthz():
        return {"ok": True}

    @app.get("/readyz")
    async def readyz():
        return {"ok": True}

    app.include_router(
        create_distributed_responses_router(
            api_key=api_key,
            enable_keyed_serialization=enable_keyed_serialization,
            fetch_manifest_tools_fn=fetch_manifest_tools_fn,
            run_tool_loop_nonstream_fn=run_tool_loop_nonstream_fn,
            run_tool_loop_stream_live_fn=run_tool_loop_stream_live_fn,
        )
    )
    app.include_router(create_internal_events_router(api_key=api_key))
    app.include_router(create_internal_skills_router(api_key=api_key))
    app.include_router(create_internal_replay_router(api_key=api_key))
    app.include_router(create_optional_responses_router(api_key=api_key))

    return app
