from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from typing import Any

import httpx
from fastapi import FastAPI, Request
from fastapi.responses import Response

from .auth import check_api_key
from .errors import openai_error
from .keyed_sequencer import KeyedSequencer
from .openai_proxy import proxy_responses
from .settings import Settings


logger = logging.getLogger("anyagent.agent_api")


def _get_agent_id(request: Request, metadata: dict[str, Any] | None) -> str:
    v = (metadata or {}).get("agent_id")
    if isinstance(v, str) and v.strip():
        return v.strip()

    h = request.headers.get("x-agent-id")
    if h and h.strip():
        return h.strip()

    return "main"


def _get_session_key(metadata: dict[str, Any] | None) -> str | None:
    v = (metadata or {}).get("session_key")
    if isinstance(v, str) and v.strip():
        return v.strip()
    return None


def create_app(settings: Settings) -> FastAPI:
    @asynccontextmanager
    async def lifespan(app: FastAPI):
        app.state.settings = settings
        app.state.sequencer = KeyedSequencer()
        app.state.http = httpx.AsyncClient(timeout=None)
        try:
            yield
        finally:
            await app.state.http.aclose()

    app = FastAPI(lifespan=lifespan)

    @app.get("/healthz")
    async def healthz():
        return {"ok": True}

    @app.get("/readyz")
    async def readyz():
        return {"ok": True}

    @app.post("/v1/responses")
    async def v1_responses(request: Request) -> Response:
        auth_err = await check_api_key(request, settings)
        if auth_err is not None:
            return auth_err

        try:
            body = await request.json()
        except Exception:
            return openai_error(400, message="Invalid JSON body", type_="invalid_request_error")

        if not isinstance(body, dict):
            return openai_error(400, message="Request body must be a JSON object", type_="invalid_request_error")

        metadata = body.get("metadata")
        if metadata is not None and not isinstance(metadata, dict):
            return openai_error(400, message="metadata must be an object", type_="invalid_request_error")

        agent_id = _get_agent_id(request, metadata)
        session_key = _get_session_key(metadata)
        session_partition_key = f"{agent_id}::{session_key or 'ephemeral'}"
        stream = bool(body.get("stream") is True)

        logger.info(
            "incoming /v1/responses",
            extra={
                "agent_id": agent_id,
                "session_key": session_key,
                "session_partition_key": session_partition_key,
                "stream": stream,
                "idempotency_key": request.headers.get("idempotency-key"),
            },
        )

        async def do_work() -> Response:
            return await proxy_responses(
                client=request.app.state.http,
                request=request,
                settings=settings,
                body=body,
            )

        if settings.enable_keyed_serialization:
            return await request.app.state.sequencer.run(session_partition_key, do_work)
        return await do_work()

    return app
