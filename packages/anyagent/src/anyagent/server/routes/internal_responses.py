from __future__ import annotations

import json
from typing import Any

from fastapi import APIRouter, Header, Request
from fastapi.responses import JSONResponse

from anyagent.protocol.agent_api_internal import (
    InternalResponseModelRequestResponse,
    InternalResponsePromptContextResponse,
    InternalResponseToolExecutionsResponse,
)
from anyagent.server.handlers.auth import _require_user_auth


def create_internal_responses_router() -> APIRouter:
    router = APIRouter()

    @router.get("/internal/responses/{response_id}/prompt-context")
    async def internal_response_prompt_context(
        req: Request,
        response_id: str,
        authorization: str | None = Header(default=None),
    ) -> JSONResponse:
        state = req.app.state.anyagent
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

    @router.get("/internal/responses/{response_id}/tool-executions")
    async def internal_response_tool_executions(
        req: Request,
        response_id: str,
        authorization: str | None = Header(default=None),
    ) -> JSONResponse:
        state = req.app.state.anyagent
        _require_user_auth(state, authorization)
        detail_events: list[Any] = []
        last_seq = 0
        for _ in range(100):
            page = await state.events.list_events(response_id=response_id, last_seq=last_seq, limit=500)
            for item in page.events:
                if not isinstance(item.data, str):
                    continue
                try:
                    data = json.loads(item.data)
                except (json.JSONDecodeError, TypeError):
                    continue
                if data.get("type") == "anyagent.tool.execution.detail":
                    detail_events.append(data)
            if page.next_last_seq <= last_seq or page.done:
                break
            last_seq = page.next_last_seq
        payload = InternalResponseToolExecutionsResponse(
            response_id=response_id,
            tool_executions=detail_events,  # type: ignore[arg-type]
        )
        return JSONResponse(payload.model_dump(exclude_none=True))

    @router.get("/internal/responses/{response_id}/model-request")
    async def internal_response_model_request(
        req: Request,
        response_id: str,
        authorization: str | None = Header(default=None),
    ) -> JSONResponse:
        state = req.app.state.anyagent
        _require_user_auth(state, authorization)
        last_model_request: dict[str, Any] | None = None
        last_seq = 0
        for _ in range(100):
            page = await state.events.list_events(response_id=response_id, last_seq=last_seq, limit=500)
            for item in page.events:
                if not isinstance(item.data, str):
                    continue
                try:
                    data = json.loads(item.data)
                except (json.JSONDecodeError, TypeError):
                    continue
                if data.get("type") == "anyagent.model.request":
                    last_model_request = data
            if page.next_last_seq <= last_seq or page.done:
                break
            last_seq = page.next_last_seq
        payload = InternalResponseModelRequestResponse(
            response_id=response_id,
            applied_body=last_model_request.get("applied_body") if last_model_request else None,
            prompt_cache_key=last_model_request.get("prompt_cache_key") if last_model_request else None,
        )
        return JSONResponse(payload.model_dump(exclude_none=True))

    return router
