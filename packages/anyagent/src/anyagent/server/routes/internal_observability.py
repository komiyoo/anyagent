from __future__ import annotations

from fastapi import APIRouter, Header, HTTPException, Request
from fastapi.responses import JSONResponse

from anyagent.protocol.alerts import AlertEventsResponse
from anyagent.protocol.agent_api_internal import InternalSessionDetailResponse, InternalSessionsListResponse
from anyagent.server.handlers.auth import _require_user_auth
from anyagent.server.handlers.sessions import _internal_run_item, _summarize_session_runs
from anyagent.server.persistence.telemetry_store import ObservabilityQuery


def create_internal_observability_router() -> APIRouter:
    router = APIRouter()

    @router.get("/internal/observability/summary")
    async def internal_observability_summary(
        req: Request,
        response_id: str,
        authorization: str | None = Header(default=None),
    ) -> JSONResponse:
        state = req.app.state.anyagent
        _require_user_auth(state, authorization)
        summary = await state.telemetry_store.summary(response_id=response_id)
        return JSONResponse(summary.model_dump(exclude_none=True))

    @router.get("/internal/sessions")
    async def internal_sessions_list(
        req: Request,
        agent_id: str | None = None,
        session_key: str | None = None,
        cursor_updated_before_ms: int | None = None,
        limit: int = 100,
        authorization: str | None = Header(default=None),
    ) -> JSONResponse:
        state = req.app.state.anyagent
        _require_user_auth(state, authorization)
        page_size = max(1, min(int(limit), 500))
        scan_limit = max(page_size * 20, 100)
        records = await state.run_store.list(
            agent_id=agent_id,
            session_key=session_key,
            limit=scan_limit,
        )
        summaries = _summarize_session_runs(records)
        if cursor_updated_before_ms is not None:
            summaries = [item for item in summaries if item.updated_at_ms < cursor_updated_before_ms]
        summaries = summaries[: page_size + 1]
        page = summaries[:page_size]
        for item in page:
            session_record = await state.session_store.get(session_partition_key=item.session_partition_key)
            if session_record is not None:
                item.snapshot_version = int(getattr(session_record, "snapshot_version", 0) or 0)
        next_cursor = page[-1].updated_at_ms if len(summaries) > page_size and page else None
        payload = InternalSessionsListResponse(
            agent_id=agent_id,
            session_key=session_key,
            cursor_updated_before_ms=cursor_updated_before_ms,
            next_cursor_updated_before_ms=next_cursor,
            sessions=page,
        )
        return JSONResponse(payload.model_dump(exclude_none=True))

    @router.get("/internal/sessions/{session_key}")
    async def internal_session_detail(
        req: Request,
        session_key: str,
        agent_id: str | None = None,
        limit: int = 100,
        authorization: str | None = Header(default=None),
    ) -> JSONResponse:
        state = req.app.state.anyagent
        _require_user_auth(state, authorization)
        page_size = max(1, min(int(limit), 500))
        scan_limit = max(page_size * 20, 100)
        records = await state.run_store.list(agent_id=agent_id, session_key=session_key, limit=scan_limit)
        if not records:
            raise HTTPException(status_code=404, detail=f"session not found: {session_key}")
        agent_ids = sorted({str(getattr(record, "agent_id", "")) for record in records if str(getattr(record, "agent_id", ""))})
        if agent_id is None and len(agent_ids) > 1:
            raise HTTPException(status_code=400, detail="agent_id is required when session_key is shared by multiple agents")
        effective_agent_id = agent_id or agent_ids[0]
        records = [record for record in records if str(getattr(record, "agent_id", "")) == effective_agent_id]
        summaries = _summarize_session_runs(records)
        if not summaries:
            raise HTTPException(status_code=404, detail=f"session not found: {session_key}")
        summary = summaries[0]
        session_record = await state.session_store.get(session_partition_key=summary.session_partition_key)
        snapshot_version = None if session_record is None else int(getattr(session_record, "snapshot_version", 0) or 0)
        summary.snapshot_version = snapshot_version
        ordered_records = sorted(
            records,
            key=lambda record: (
                int(getattr(record, "updated_at_ms", 0) or 0),
                1
                if str(getattr(record, "effective_status", getattr(record, "status", "")) or "")
                in {"in_progress", "queued", "started"}
                else 0,
                int(getattr(record, "created_at_ms", 0) or 0),
                str(getattr(record, "response_id", "") or ""),
            ),
            reverse=True,
        )
        payload = InternalSessionDetailResponse(
            agent_id=effective_agent_id,
            session_key=session_key,
            session_partition_key=summary.session_partition_key,
            summary=summary,
            runs=[_internal_run_item(record) for record in ordered_records[:page_size]],
            snapshot_version=snapshot_version,
            snapshot_json=None if session_record is None else getattr(session_record, "snapshot_json", None),
        )
        return JSONResponse(payload.model_dump(exclude_none=True))

    @router.get("/internal/observability/runs")
    async def internal_observability_runs(
        req: Request,
        agent_id: str | None = None,
        session_key: str | None = None,
        response_id: str | None = None,
        created_after_ms: int | None = None,
        created_before_ms: int | None = None,
        limit: int = 100,
        authorization: str | None = Header(default=None),
    ) -> JSONResponse:
        state = req.app.state.anyagent
        _require_user_auth(state, authorization)
        payload = await state.telemetry_store.runs(
            ObservabilityQuery(
                agent_id=agent_id,
                session_key=session_key,
                response_id=response_id,
                created_after_ms=created_after_ms,
                created_before_ms=created_before_ms,
                limit=limit,
            )
        )
        return JSONResponse(payload.model_dump(exclude_none=True))

    @router.get("/internal/observability/timeline")
    async def internal_observability_timeline(
        req: Request,
        agent_id: str | None = None,
        session_key: str | None = None,
        response_id: str | None = None,
        trace_id: str | None = None,
        created_after_ms: int | None = None,
        created_before_ms: int | None = None,
        limit: int = 200,
        authorization: str | None = Header(default=None),
    ) -> JSONResponse:
        state = req.app.state.anyagent
        _require_user_auth(state, authorization)
        payload = await state.telemetry_store.timeline(
            ObservabilityQuery(
                agent_id=agent_id,
                session_key=session_key,
                response_id=response_id,
                trace_id=trace_id,
                created_after_ms=created_after_ms,
                created_before_ms=created_before_ms,
                limit=limit,
            )
        )
        return JSONResponse(payload.model_dump(exclude_none=True))

    @router.get("/internal/observability/metrics")
    async def internal_observability_metrics(
        req: Request,
        agent_id: str | None = None,
        session_key: str | None = None,
        response_id: str | None = None,
        created_after_ms: int | None = None,
        created_before_ms: int | None = None,
        limit: int = 100,
        authorization: str | None = Header(default=None),
    ) -> JSONResponse:
        state = req.app.state.anyagent
        _require_user_auth(state, authorization)
        payload = await state.telemetry_store.metrics(
            ObservabilityQuery(
                agent_id=agent_id,
                session_key=session_key,
                response_id=response_id,
                created_after_ms=created_after_ms,
                created_before_ms=created_before_ms,
                limit=limit,
            )
        )
        return JSONResponse(payload.model_dump(exclude_none=True))

    @router.get("/internal/observability/tools")
    async def internal_observability_tools(
        req: Request,
        agent_id: str | None = None,
        session_key: str | None = None,
        response_id: str | None = None,
        created_after_ms: int | None = None,
        created_before_ms: int | None = None,
        limit: int = 100,
        authorization: str | None = Header(default=None),
    ) -> JSONResponse:
        state = req.app.state.anyagent
        _require_user_auth(state, authorization)
        payload = await state.telemetry_store.tools(
            ObservabilityQuery(
                agent_id=agent_id,
                session_key=session_key,
                response_id=response_id,
                created_after_ms=created_after_ms,
                created_before_ms=created_before_ms,
                limit=limit,
            )
        )
        return JSONResponse(payload.model_dump(exclude_none=True))

    @router.get("/internal/observability/errors")
    async def internal_observability_errors(
        req: Request,
        agent_id: str | None = None,
        session_key: str | None = None,
        response_id: str | None = None,
        trace_id: str | None = None,
        created_after_ms: int | None = None,
        created_before_ms: int | None = None,
        limit: int = 100,
        authorization: str | None = Header(default=None),
    ) -> JSONResponse:
        state = req.app.state.anyagent
        _require_user_auth(state, authorization)
        payload = await state.telemetry_store.errors(
            ObservabilityQuery(
                agent_id=agent_id,
                session_key=session_key,
                response_id=response_id,
                trace_id=trace_id,
                created_after_ms=created_after_ms,
                created_before_ms=created_before_ms,
                limit=limit,
            )
        )
        return JSONResponse(payload.model_dump(exclude_none=True))

    @router.get("/internal/observability/traces/{trace_id}")
    async def internal_observability_trace(
        req: Request,
        trace_id: str,
        limit: int = 500,
        authorization: str | None = Header(default=None),
    ) -> JSONResponse:
        state = req.app.state.anyagent
        _require_user_auth(state, authorization)
        payload = await state.telemetry_store.trace(trace_id=trace_id, limit=limit)
        return JSONResponse(payload.model_dump(exclude_none=True))

    @router.get("/internal/observability/alerts")
    async def internal_observability_alerts(
        req: Request,
        agent_id: str | None = None,
        session_key: str | None = None,
        response_id: str | None = None,
        trace_id: str | None = None,
        created_after_ms: int | None = None,
        created_before_ms: int | None = None,
        limit: int = 100,
        authorization: str | None = Header(default=None),
    ) -> JSONResponse:
        state = req.app.state.anyagent
        _require_user_auth(state, authorization)
        query = ObservabilityQuery(
            agent_id=agent_id,
            session_key=session_key,
            response_id=response_id,
            trace_id=trace_id,
            created_after_ms=created_after_ms,
            created_before_ms=created_before_ms,
            limit=limit,
        )
        await state.alert_evaluator.evaluate_once(query)
        alerts = await state.alert_store.list_events(query)
        payload = AlertEventsResponse(
            agent_id=agent_id,
            session_key=session_key,
            response_id=response_id,
            trace_id=trace_id,
            alerts=alerts,
        )
        return JSONResponse(payload.model_dump(exclude_none=True))

    @router.get("/internal/audit/events")
    async def internal_audit_events(
        req: Request,
        credential_id: str | None = None,
        agent_id: str | None = None,
        session_key: str | None = None,
        response_id: str | None = None,
        trace_id: str | None = None,
        created_after_ms: int | None = None,
        created_before_ms: int | None = None,
        limit: int = 100,
        authorization: str | None = Header(default=None),
    ) -> JSONResponse:
        state = req.app.state.anyagent
        _require_user_auth(state, authorization)
        payload = await state.telemetry_store.audit(
            ObservabilityQuery(
                credential_id=credential_id,
                agent_id=agent_id,
                session_key=session_key,
                response_id=response_id,
                trace_id=trace_id,
                created_after_ms=created_after_ms,
                created_before_ms=created_before_ms,
                limit=limit,
            )
        )
        return JSONResponse(payload.model_dump(exclude_none=True))

    return router
