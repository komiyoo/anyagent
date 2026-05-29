"""Internal replay router — tool-executions, model-request, prompt-context.

Provides the same replay query endpoints as the built-in server for the
distributed agent app path.
"""

from __future__ import annotations

import json
from typing import Any

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse, Response

from anyagent.protocol.agent_api_internal import (
    InternalResponseModelRequestResponse,
    InternalResponsePromptContextResponse,
    InternalResponseToolExecutionsResponse,
)

from .responses_optional import check_bearer_api_key, openai_error_response


def create_internal_replay_router(
    *,
    api_key: str,
    storage_state_attr: str = "storage",
) -> APIRouter:
    router = APIRouter()

    @router.get("/internal/responses/{response_id}/tool-executions")
    async def internal_response_tool_executions(
        request: Request,
        response_id: str,
    ) -> Response:
        auth_err = await check_bearer_api_key(request, api_key=api_key)
        if auth_err is not None:
            return auth_err

        storage = getattr(request.app.state, storage_state_attr)
        detail_events: list[Any] = []
        last_seq = 0
        for _ in range(100):
            page = await storage.event_store.list(
                response_id=response_id, after_seq=last_seq, limit=500,
            )
            for item in page:
                data = _parse_event_data(getattr(item, "data", None))
                if data and data.get("type") == "anyagent.tool.execution.detail":
                    detail_events.append(data)
            if not page or len(page) < 500:
                break
            last_seq = getattr(page[-1], "seq", last_seq + len(page))
        payload = InternalResponseToolExecutionsResponse(
            response_id=response_id,
            tool_executions=detail_events,  # type: ignore[arg-type]
        )
        return JSONResponse(payload.model_dump(exclude_none=True))

    @router.get("/internal/responses/{response_id}/model-request")
    async def internal_response_model_request(
        request: Request,
        response_id: str,
    ) -> Response:
        auth_err = await check_bearer_api_key(request, api_key=api_key)
        if auth_err is not None:
            return auth_err

        storage = getattr(request.app.state, storage_state_attr)
        last_model_request: dict[str, Any] | None = None
        last_seq = 0
        for _ in range(100):
            page = await storage.event_store.list(
                response_id=response_id, after_seq=last_seq, limit=500,
            )
            for item in page:
                data = _parse_event_data(getattr(item, "data", None))
                if data and data.get("type") == "anyagent.model.request":
                    last_model_request = data
            if not page or len(page) < 500:
                break
            last_seq = getattr(page[-1], "seq", last_seq + len(page))
        payload = InternalResponseModelRequestResponse(
            response_id=response_id,
            applied_body=last_model_request.get("applied_body") if last_model_request else None,
            prompt_cache_key=last_model_request.get("prompt_cache_key") if last_model_request else None,
        )
        return JSONResponse(payload.model_dump(exclude_none=True))

    @router.get("/internal/responses/{response_id}/prompt-context")
    async def internal_response_prompt_context(
        request: Request,
        response_id: str,
    ) -> Response:
        auth_err = await check_bearer_api_key(request, api_key=api_key)
        if auth_err is not None:
            return auth_err

        storage = getattr(request.app.state, storage_state_attr)
        rendered_data: dict[str, Any] | None = None
        audit_data: dict[str, Any] | None = None
        last_seq = 0
        for _ in range(100):
            page = await storage.event_store.list(
                response_id=response_id, after_seq=last_seq, limit=500,
            )
            for item in page:
                data = _parse_event_data(getattr(item, "data", None))
                if not data:
                    continue
                evt_type = data.get("type")
                if evt_type == "anyagent.prompt.context.rendered":
                    rendered_data = data
                elif evt_type == "anyagent.prompt.context":
                    audit_data = data
            if not page or len(page) < 500:
                break
            last_seq = getattr(page[-1], "seq", last_seq + len(page))

        if rendered_data is not None:
            payload = InternalResponsePromptContextResponse(
                response_id=response_id,
                prompt_cache_key=rendered_data.get("prompt_cache_key"),
                total_chars=rendered_data.get("total_chars", 0),
                fragments=rendered_data.get("fragments", []),
                fallback="rendered",
            )
        elif audit_data is not None:
            payload = InternalResponsePromptContextResponse(
                response_id=response_id,
                prompt_cache_key=audit_data.get("prompt_cache_key"),
                fallback="audit",
            )
        else:
            payload = InternalResponsePromptContextResponse(response_id=response_id)
        return JSONResponse(payload.model_dump(exclude_none=True))

    return router


def _parse_event_data(raw: Any) -> dict[str, Any] | None:
    if not isinstance(raw, str):
        return None
    try:
        return json.loads(raw)
    except (json.JSONDecodeError, TypeError):
        return None
