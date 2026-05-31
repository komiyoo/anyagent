from __future__ import annotations

import json
import threading
from dataclasses import dataclass
from typing import Any, Protocol

from anyagent.observability import ObservabilitySink
from anyagent.protocol.agent_api_internal import (
    InternalAuditEventItem,
    InternalAuditEventsResponse,
    InternalObservabilityErrorItem,
    InternalObservabilityErrorsResponse,
    InternalObservabilityMetricsResponse,
    InternalObservabilityRunItem,
    InternalObservabilityRunsResponse,
    InternalObservabilitySummaryResponse,
    InternalObservabilityTimelineEvent,
    InternalObservabilityTimelineResponse,
    InternalObservabilityToolStats,
    InternalObservabilityToolsResponse,
    InternalObservabilityTraceResponse,
    InternalObservabilityTurnMetric,
)
from anyagent.protocol.observability import NormalizedTelemetryEvent, ObservabilityEvent
from anyagent.protocol.stage_events import AnyAgentPromptContextEvent, StageEvent
from anyagent.server.persistence.storage_backends import EventStore, RunStore


@dataclass(frozen=True, slots=True)
class ObservabilityQuery:
    agent_id: str | None = None
    session_key: str | None = None
    response_id: str | None = None
    trace_id: str | None = None
    credential_id: str | None = None
    created_after_ms: int | None = None
    created_before_ms: int | None = None
    limit: int = 100


class TelemetryStore(Protocol):
    async def ingest(self, event: NormalizedTelemetryEvent) -> None: ...
    async def ingest_many(self, events: list[NormalizedTelemetryEvent]) -> None: ...
    async def ingest_run(self, record: Any) -> None: ...
    async def ingest_stage_event(self, event: StageEvent, *, payload: dict[str, Any] | None = None) -> None: ...
    async def ingest_observability_event(self, event: ObservabilityEvent) -> None: ...
    async def summary(self, *, response_id: str) -> InternalObservabilitySummaryResponse: ...
    async def runs(self, query: ObservabilityQuery) -> InternalObservabilityRunsResponse: ...
    async def timeline(self, query: ObservabilityQuery) -> InternalObservabilityTimelineResponse: ...
    async def metrics(self, query: ObservabilityQuery) -> InternalObservabilityMetricsResponse: ...
    async def tools(self, query: ObservabilityQuery) -> InternalObservabilityToolsResponse: ...
    async def errors(self, query: ObservabilityQuery) -> InternalObservabilityErrorsResponse: ...
    async def audit(self, query: ObservabilityQuery) -> InternalAuditEventsResponse: ...
    async def trace(self, *, trace_id: str, limit: int = 500) -> InternalObservabilityTraceResponse: ...


class InMemoryObservabilityEventSink(ObservabilitySink):
    """Bounded in-process sink that makes server observability logs queryable."""

    def __init__(self, *, max_events: int = 10_000) -> None:
        self._max_events = max(1, max_events)
        self._events: list[ObservabilityEvent] = []
        self._lock = threading.Lock()

    def emit(self, event: ObservabilityEvent) -> None:
        with self._lock:
            self._events.append(event)
            if len(self._events) > self._max_events:
                del self._events[: len(self._events) - self._max_events]

    def list(self) -> list[ObservabilityEvent]:
        with self._lock:
            return list(self._events)


class InMemoryTelemetryEventStore:
    """Bounded in-process normalized telemetry event store."""

    def __init__(self, *, max_events: int = 50_000) -> None:
        self._max_events = max(1, max_events)
        self._events: list[NormalizedTelemetryEvent] = []
        self._lock = threading.Lock()

    async def append(self, event: NormalizedTelemetryEvent) -> None:
        self.append_sync(event)

    def append_sync(self, event: NormalizedTelemetryEvent) -> None:
        with self._lock:
            self._events.append(event)
            if len(self._events) > self._max_events:
                del self._events[: len(self._events) - self._max_events]

    async def extend(self, events: list[NormalizedTelemetryEvent]) -> None:
        if not events:
            return
        with self._lock:
            self._events.extend(events)
            if len(self._events) > self._max_events:
                del self._events[: len(self._events) - self._max_events]

    async def list(self) -> list[NormalizedTelemetryEvent]:
        with self._lock:
            return list(self._events)


class PostgresTelemetryEventStore:
    """PostgreSQL-backed normalized telemetry event store."""

    def __init__(self, *, postgres_dsn: str, postgres_schema: str = "public", schema_policy: str = "migrate") -> None:
        try:
            from anyagent.storage.external import create_external_sql_engine, resolve_external_sql_backend_config
            from sqlalchemy import BIGINT, FLOAT, JSON, TEXT, Column, DateTime, MetaData, Table, func
        except Exception as e:  # noqa: BLE001
            raise RuntimeError("postgres telemetry store requires installing anyagent[postgres]") from e

        self._postgres_dsn = postgres_dsn
        self._postgres_schema = postgres_schema.strip() or "public"
        self._schema_policy = schema_policy
        self._init_lock = threading.Lock()
        self._async_init_lock = None
        self._initialized = False
        config = resolve_external_sql_backend_config(
            postgres_dsn=postgres_dsn,
            mysql_dsn=None,
            redis_dsn=None,
            schema_name=self._postgres_schema,
            namespace="anyagent",
            dialect="postgresql",
        )
        self._engine = create_external_sql_engine(config)
        meta = MetaData()
        self._table = Table(
            "telemetry_events",
            meta,
            Column("id", BIGINT, primary_key=True, autoincrement=True),
            Column("source", TEXT, nullable=False),
            Column("event_type", TEXT, nullable=False),
            Column("ts_ms", BIGINT, nullable=True),
            Column("response_id", TEXT, nullable=True),
            Column("agent_id", TEXT, nullable=True),
            Column("session_key", TEXT, nullable=True),
            Column("trace_id", TEXT, nullable=True),
            Column("seq", BIGINT, nullable=True),
            Column("level", TEXT, nullable=True),
            Column("category", TEXT, nullable=True),
            Column("status", TEXT, nullable=True),
            Column("tool_name", TEXT, nullable=True),
            Column("tool_call_id", TEXT, nullable=True),
            Column("duration_ms", FLOAT, nullable=True),
            Column("audit_ref", TEXT, nullable=True),
            Column("message", TEXT, nullable=True),
            Column("payload_json", JSON, nullable=False),
            Column("created_at", DateTime(timezone=True), nullable=False, server_default=func.now()),
            schema=self._postgres_schema,
        )

    async def append(self, event: NormalizedTelemetryEvent) -> None:
        await self._ensure_table_async()
        from sqlalchemy import insert

        async with self._engine.begin() as conn:
            await conn.execute(insert(self._table).values(**_telemetry_row(event)))

    def append_sync(self, event: NormalizedTelemetryEvent) -> None:
        self._ensure_table_sync()
        import psycopg  # type: ignore[import-not-found]
        from psycopg.types.json import Jsonb

        row = _telemetry_row(event)
        row["payload_json"] = Jsonb(row["payload_json"])
        columns = [
            "source",
            "event_type",
            "ts_ms",
            "response_id",
            "agent_id",
            "session_key",
            "trace_id",
            "seq",
            "level",
            "category",
            "status",
            "tool_name",
            "tool_call_id",
            "duration_ms",
            "audit_ref",
            "message",
            "payload_json",
        ]
        placeholders = ", ".join(["%s"] * len(columns))
        quoted_cols = ", ".join(columns)
        with psycopg.connect(self._postgres_dsn, autocommit=True) as conn:
            with conn.cursor() as cur:
                cur.execute(
                    f"INSERT INTO {self._postgres_schema}.telemetry_events ({quoted_cols}) VALUES ({placeholders})",
                    [row.get(column) for column in columns],
                )

    async def extend(self, events: list[NormalizedTelemetryEvent]) -> None:
        if not events:
            return
        await self._ensure_table_async()
        from sqlalchemy import insert

        async with self._engine.begin() as conn:
            await conn.execute(insert(self._table), [_telemetry_row(event) for event in events])

    async def list(self) -> list[NormalizedTelemetryEvent]:
        await self._ensure_table_async()
        from sqlalchemy import select

        stmt = select(self._table).order_by(self._table.c.id.asc()).limit(50_000)
        async with self._engine.connect() as conn:
            rows = (await conn.execute(stmt)).mappings().all()
        return [_telemetry_event_from_row(dict(row)) for row in rows]

    async def dispose(self) -> None:
        await self._engine.dispose()

    async def _ensure_table_async(self) -> None:
        if self._initialized:
            return
        import asyncio

        if self._async_init_lock is None:
            self._async_init_lock = asyncio.Lock()
        async with self._async_init_lock:
            if self._initialized:
                return
            from anyagent.server.db.postgres_schema import ensure_postgres_schema_objects

            await ensure_postgres_schema_objects(
                postgres_dsn=self._postgres_dsn,
                postgres_schema=self._postgres_schema,
                required_tables=["telemetry_events"],
                create_statements=[_postgres_telemetry_events_create_sql(self._postgres_schema)],
                policy=self._schema_policy,
            )
            self._initialized = True

    def _ensure_table_sync(self) -> None:
        if self._initialized:
            return
        with self._init_lock:
            if self._initialized:
                return
            import psycopg  # type: ignore[import-not-found]

            with psycopg.connect(self._postgres_dsn, autocommit=True) as conn:
                with conn.cursor() as cur:
                    if self._schema_policy == "runtime_create":
                        cur.execute(f"CREATE SCHEMA IF NOT EXISTS {self._postgres_schema}")
                        cur.execute(_postgres_telemetry_events_create_sql(self._postgres_schema))
                    else:
                        cur.execute("SELECT to_regclass(%s)", (f"{self._postgres_schema}.telemetry_events",))
                        row = cur.fetchone()
                        if not row or row[0] is None:
                            raise RuntimeError(
                                "postgres telemetry schema is not ready; run `anyagent storage migrate` first "
                                f"(schema={self._postgres_schema}, missing=telemetry_events) "
                                "or set POSTGRES_SCHEMA_POLICY=runtime_create for development fallback"
                            )
            self._initialized = True


class TelemetryObservabilitySink(ObservabilitySink):
    """Sync bridge from ObservabilityEmitter into a normalized telemetry store."""

    def __init__(self, *, telemetry_events: Any) -> None:
        self._telemetry_events = telemetry_events

    def emit(self, event: ObservabilityEvent) -> None:
        append_sync = getattr(self._telemetry_events, "append_sync", None)
        if callable(append_sync):
            append_sync(normalized_from_observability_event(event))


class RunEventTelemetryStore:
    """Telemetry query facade backed by the Agent API run/event stores."""

    def __init__(
        self,
        *,
        event_store: EventStore,
        run_store: RunStore,
        observability_events: InMemoryObservabilityEventSink,
        telemetry_events: InMemoryTelemetryEventStore | None = None,
        include_observability_sink_events: bool = True,
    ) -> None:
        self._event_store = event_store
        self._run_store = run_store
        self._observability_events = observability_events
        self._telemetry_events = telemetry_events or InMemoryTelemetryEventStore()
        self._include_observability_sink_events = include_observability_sink_events

    async def ingest(self, event: NormalizedTelemetryEvent) -> None:
        await self._telemetry_events.append(event)

    async def ingest_many(self, events: list[NormalizedTelemetryEvent]) -> None:
        await self._telemetry_events.extend(events)

    async def ingest_run(self, record: Any) -> None:
        await self.ingest(normalized_from_run_record(record))

    async def ingest_stage_event(self, event: StageEvent, *, payload: dict[str, Any] | None = None) -> None:
        await self.ingest(normalized_from_stage_event(event, payload=payload))

    async def ingest_observability_event(self, event: ObservabilityEvent) -> None:
        await self.ingest(normalized_from_observability_event(event))

    async def summary(self, *, response_id: str) -> InternalObservabilitySummaryResponse:
        resp = await self._event_store.list_events(response_id=response_id, last_seq=0, limit=10000)
        run_record = await self._run_store.get(response_id)
        typed = resp.typed_events(include_model_events=True)
        payloads = [_json_obj(item.data) for item in resp.events]
        payloads = [payload for payload in payloads if payload is not None]

        prompt_context = resp.latest_prompt_context()
        prompt_payload = next((payload for payload in payloads if payload.get("type") == "anyagent.prompt.context"), {})
        selected_skill_ids = set(prompt_context.selected_skill_ids if prompt_context is not None else [])
        raw_skill_ids = prompt_payload.get("selected_skill_ids")
        if isinstance(raw_skill_ids, list):
            selected_skill_ids.update(item for item in raw_skill_ids if isinstance(item, str) and item.strip())

        input_tokens, output_tokens, cached_tokens = _token_totals(payloads)
        first_token_latency = _first_number(payloads, "first_token_ms", "latency.first_token_ms", "ttft_ms")
        total_latency = _last_number(payloads, "total_latency_ms", "latency.total_ms", "duration_ms", "elapsed_ms")
        response_json = next((payload for payload in payloads if payload.get("object") == "response" or payload.get("id") == response_id), {})
        final_response_json = getattr(run_record, "final_response_json", None)
        if isinstance(final_response_json, dict):
            response_json = final_response_json
        request_payload = next((payload for payload in payloads if payload.get("type") == "anyagent.response.request"), {})
        turn_count, input_chars, output_chars, turn_metrics = _turn_stats(
            [*_input_to_transcript_items(request_payload.get("transcript_items")), *_response_to_transcript_items(response_json)]
        )

        return InternalObservabilitySummaryResponse(
            response_id=response_id,
            agent_id=_agent_id(prompt_context, prompt_payload, run_record),
            session_key=_session_key(prompt_context, prompt_payload, run_record),
            event_count=len(resp.events),
            typed_event_count=len(typed),
            tool_call_count=sum(1 for payload in payloads if str(payload.get("type") or "").startswith("anyagent.tool.")),
            mcp_call_count=sum(1 for payload in payloads if _is_mcp_payload(payload)),
            skill_view_count=len(selected_skill_ids),
            compaction_count=sum(1 for payload in payloads if payload.get("type") == "anyagent.context.compacted"),
            loop_warnings_count=sum(1 for payload in payloads if payload.get("type") == "anyagent.agent.loop_warning"),
            subagent_spawns=sum(1 for payload in payloads if payload.get("type") == "anyagent.subagent.spawned"),
            turn_count=turn_count,
            input_chars=input_chars,
            output_chars=output_chars,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            cached_input_tokens=cached_tokens,
            turns=turn_metrics,
            first_token_latency_ms=first_token_latency,
            total_response_latency_ms=total_latency,
            run_status=resp.run_status or _str_or_none(response_json.get("status") if isinstance(response_json, dict) else None),
            effective_run_status=resp.effective_run_status,
        )

    async def runs(self, query: ObservabilityQuery) -> InternalObservabilityRunsResponse:
        records = await self._filtered_run_records(query)
        return InternalObservabilityRunsResponse(
            agent_id=query.agent_id,
            session_key=query.session_key,
            response_id=query.response_id,
            runs=[_run_item(record) for record in records],
        )

    async def timeline(self, query: ObservabilityQuery) -> InternalObservabilityTimelineResponse:
        events = await self._timeline_events(query)
        return InternalObservabilityTimelineResponse(
            agent_id=query.agent_id,
            session_key=query.session_key,
            response_id=query.response_id,
            trace_id=query.trace_id,
            events=events[: query.limit],
        )

    async def metrics(self, query: ObservabilityQuery) -> InternalObservabilityMetricsResponse:
        records = await self._filtered_run_records(query)
        events = await self._timeline_events(query)
        summaries = []
        for record in records:
            try:
                summaries.append(await self.summary(response_id=str(getattr(record, "response_id", ""))))
            except Exception:  # noqa: BLE001
                continue
        latencies = [item.total_response_latency_ms for item in summaries if item.total_response_latency_ms is not None]
        first_latencies = [item.first_token_latency_ms for item in summaries if item.first_token_latency_ms is not None]
        return InternalObservabilityMetricsResponse(
            agent_id=query.agent_id,
            session_key=query.session_key,
            response_id=query.response_id,
            run_count=len(records),
            event_count=len(events),
            tool_call_count=sum(item.tool_call_count for item in summaries),
            mcp_call_count=sum(item.mcp_call_count for item in summaries),
            error_count=len([item for item in events if item.level == "error" or item.status == "error"]),
            input_tokens=sum(item.input_tokens for item in summaries),
            output_tokens=sum(item.output_tokens for item in summaries),
            cached_input_tokens=sum(item.cached_input_tokens for item in summaries),
            avg_response_latency_ms=(sum(latencies) / len(latencies)) if latencies else None,
            max_response_latency_ms=max(latencies) if latencies else None,
            first_token_latency_ms=min(first_latencies) if first_latencies else None,
        )

    async def tools(self, query: ObservabilityQuery) -> InternalObservabilityToolsResponse:
        events = await self._timeline_events(query)
        stats: dict[str, dict[str, Any]] = {}
        for event in events:
            if not event.tool_name:
                continue
            item = stats.setdefault(
                event.tool_name,
                {"planned": 0, "result": 0, "error": 0, "durations": [], "last_status": None, "audit_refs": []},
            )
            if event.type.endswith(".planned"):
                item["planned"] += 1
            if event.type.endswith(".result"):
                item["result"] += 1
                item["last_status"] = event.status
            if event.status == "error" or event.level == "error":
                item["error"] += 1
            if event.duration_ms is not None:
                item["durations"].append(event.duration_ms)
            if event.audit_ref and event.audit_ref not in item["audit_refs"]:
                item["audit_refs"].append(event.audit_ref)
        tools = [
            InternalObservabilityToolStats(
                tool_name=name,
                planned_count=int(item["planned"]),
                result_count=int(item["result"]),
                error_count=int(item["error"]),
                avg_duration_ms=(sum(item["durations"]) / len(item["durations"])) if item["durations"] else None,
                max_duration_ms=max(item["durations"]) if item["durations"] else None,
                last_status=item["last_status"],
                audit_refs=sorted(item["audit_refs"]),
            )
            for name, item in sorted(stats.items())
        ]
        return InternalObservabilityToolsResponse(
            agent_id=query.agent_id,
            session_key=query.session_key,
            response_id=query.response_id,
            tools=tools,
        )

    async def errors(self, query: ObservabilityQuery) -> InternalObservabilityErrorsResponse:
        items: list[InternalObservabilityErrorItem] = []
        records = await self._filtered_run_records(query)
        for record in records:
            error_json = getattr(record, "error_json", None)
            if isinstance(error_json, dict):
                items.append(
                    InternalObservabilityErrorItem(
                        source="run",
                        type=str(error_json.get("type") or getattr(record, "status", "run.error")),
                        message=_str_or_none(error_json.get("message") or error_json.get("code")),
                        response_id=str(getattr(record, "response_id", "")),
                        agent_id=str(getattr(record, "agent_id", "")),
                        session_key=str(getattr(record, "session_key", "")),
                        ts_ms=int(getattr(record, "updated_at_ms", 0) or 0) or None,
                        payload=error_json,
                    )
                )
        for event in await self._timeline_events(query):
            if event.level != "error" and event.status != "error":
                continue
            items.append(
                InternalObservabilityErrorItem(
                    source=event.source,
                    type=event.type,
                    message=event.message,
                    ts_ms=event.ts_ms,
                    response_id=event.response_id,
                    agent_id=event.agent_id,
                    session_key=event.session_key,
                    trace_id=event.trace_id,
                    tool_name=event.tool_name,
                    tool_call_id=event.tool_call_id,
                    audit_ref=event.audit_ref,
                    retryable=_bool_or_none(event.payload.get("retryable")),
                    payload=event.payload,
                )
            )
        return InternalObservabilityErrorsResponse(
            agent_id=query.agent_id,
            session_key=query.session_key,
            response_id=query.response_id,
            errors=items[: query.limit],
        )

    async def audit(self, query: ObservabilityQuery) -> InternalAuditEventsResponse:
        events = [event for event in await self._timeline_events(query) if _is_audit_event(event)]
        items = [_audit_event_item(event) for event in events]
        if query.credential_id is not None:
            items = [item for item in items if item.credential_id == query.credential_id]
        return InternalAuditEventsResponse(
            credential_id=query.credential_id,
            agent_id=query.agent_id,
            session_key=query.session_key,
            response_id=query.response_id,
            trace_id=query.trace_id,
            events=items[: query.limit],
        )

    async def trace(self, *, trace_id: str, limit: int = 500) -> InternalObservabilityTraceResponse:
        events = await self._timeline_events(ObservabilityQuery(trace_id=trace_id, limit=limit))
        response_ids = sorted({item.response_id for item in events if item.response_id})
        audit_refs = sorted({item.audit_ref for item in events if item.audit_ref})
        return InternalObservabilityTraceResponse(
            trace_id=trace_id,
            response_ids=response_ids,
            audit_refs=audit_refs,
            events=events[:limit],
        )

    async def _filtered_run_records(self, query: ObservabilityQuery) -> list[Any]:
        records = await self._run_store.list(
            agent_id=query.agent_id,
            session_key=query.session_key,
            response_id=query.response_id,
            limit=max(query.limit, 1),
        )
        if query.created_after_ms is not None:
            records = [record for record in records if int(getattr(record, "created_at_ms", 0) or 0) >= query.created_after_ms]
        if query.created_before_ms is not None:
            records = [record for record in records if int(getattr(record, "created_at_ms", 0) or 0) <= query.created_before_ms]
        return records

    async def _timeline_events(self, query: ObservabilityQuery) -> list[InternalObservabilityTimelineEvent]:
        events: list[InternalObservabilityTimelineEvent] = []
        records = await self._filtered_run_records(
            ObservabilityQuery(
                agent_id=query.agent_id,
                session_key=query.session_key,
                response_id=query.response_id,
                created_after_ms=query.created_after_ms,
                created_before_ms=query.created_before_ms,
                limit=query.limit,
            )
        )
        if not records and query.response_id:
            records = [None]
        for record in records:
            response_id = query.response_id if record is None else str(getattr(record, "response_id", ""))
            if not response_id:
                continue
            if record is not None:
                events.append(_run_timeline_event(record))
            page = await self._event_store.list_events(response_id=response_id, last_seq=0, limit=10000)
            prompt_context = page.latest_prompt_context()
            typed_by_seq = {event.seq: event for event in page.typed_events(include_model_events=True) if event.seq is not None}
            for item in page.events:
                payload = _json_obj(item.data) or {}
                events.append(
                    _stage_timeline_event(
                        response_id=response_id,
                        agent_id=_agent_id(prompt_context, payload, record),
                        session_key=_session_key(prompt_context, payload, record),
                        seq=item.seq,
                        event_name=item.event,
                        typed=typed_by_seq.get(item.seq),
                        payload=payload,
                    )
                )
        if self._include_observability_sink_events:
            events.extend(self._observability_timeline_events(query))
        events.extend(await self._ingested_timeline_events(query))
        filtered = [event for event in events if _matches_query(event, query)]
        filtered.sort(key=lambda item: ((item.ts_ms or 0), item.seq or 0, item.type))
        return filtered[: query.limit]

    def _observability_timeline_events(self, query: ObservabilityQuery) -> list[InternalObservabilityTimelineEvent]:
        items: list[InternalObservabilityTimelineEvent] = []
        for event in self._observability_events.list():
            payload = dict(event.payload or {})
            items.append(
                InternalObservabilityTimelineEvent(
                    source="observability",
                    type=event.event,
                    ts_ms=event.ts_ms,
                    response_id=_str_or_none(payload.get("response_id")),
                    agent_id=_str_or_none(payload.get("agent_id")),
                    session_key=_str_or_none(payload.get("session_key")),
                    trace_id=_str_or_none(payload.get("trace_id")),
                    level=event.level,
                    category=event.category,
                    status=_str_or_none(payload.get("status")),
                    tool_name=_str_or_none(payload.get("tool_name")),
                    tool_call_id=_str_or_none(payload.get("tool_call_id")),
                    duration_ms=_num_or_none(payload.get("duration_ms")),
                    audit_ref=_str_or_none(payload.get("audit_ref")),
                    message=_str_or_none(payload.get("message") or payload.get("error_message")),
                    payload=payload,
                )
            )
        return [item for item in items if _matches_query(item, query)]

    async def _ingested_timeline_events(self, query: ObservabilityQuery) -> list[InternalObservabilityTimelineEvent]:
        items = [
            InternalObservabilityTimelineEvent.model_validate(event.model_dump(exclude_none=True))
            for event in await self._telemetry_events.list()
        ]
        return [item for item in items if _matches_query(item, query)]


def _stage_timeline_event(
    *,
    response_id: str,
    agent_id: str | None,
    session_key: str | None,
    seq: int,
    event_name: str | None,
    typed: StageEvent | None,
    payload: dict[str, Any],
) -> InternalObservabilityTimelineEvent:
    event_type = _str_or_none(payload.get("type")) or event_name or "event"
    meta = payload.get("meta") if isinstance(payload.get("meta"), dict) else {}
    error = payload.get("error") if isinstance(payload.get("error"), dict) else {}
    return InternalObservabilityTimelineEvent(
        source="event",
        type=event_type,
        ts_ms=int(getattr(typed, "ts_ms", None) or 0) or _num_int_or_none(payload.get("ts_ms")),
        response_id=response_id,
        agent_id=agent_id,
        session_key=session_key,
        trace_id=_str_or_none(getattr(typed, "trace_id", None) or payload.get("trace_id")),
        seq=seq,
        level="error" if error or payload.get("failure_code") else None,
        category=_category_for_event(event_type),
        status=_str_or_none(payload.get("status")) or ("error" if error else None),
        tool_name=_str_or_none(payload.get("tool_name") or payload.get("source_tool_name")),
        tool_call_id=_str_or_none(payload.get("tool_call_id") or payload.get("source_tool_call_id")),
        duration_ms=_num_or_none(meta.get("duration_ms") or payload.get("duration_ms")),
        audit_ref=_str_or_none(meta.get("audit_ref") or payload.get("audit_ref")),
        message=_str_or_none(error.get("message") or payload.get("failure_message")),
        payload=payload,
    )


def normalized_from_stage_event(event: StageEvent, *, payload: dict[str, Any] | None = None) -> NormalizedTelemetryEvent:
    raw = payload if payload is not None else event.model_dump(exclude_none=True)
    timeline = _stage_timeline_event(
        response_id=event.response_id,
        agent_id=_str_or_none(raw.get("agent_id")),
        session_key=_str_or_none(raw.get("session_key")),
        seq=event.seq or 1,
        event_name=event.type,
        typed=event,
        payload=raw,
    )
    return NormalizedTelemetryEvent.model_validate(timeline.model_dump(exclude_none=True))


def normalized_from_observability_event(event: ObservabilityEvent) -> NormalizedTelemetryEvent:
    payload = dict(event.payload or {})
    return NormalizedTelemetryEvent(
        source="observability" if event.category != "audit" else "audit",
        type=event.event,
        ts_ms=event.ts_ms,
        response_id=_str_or_none(payload.get("response_id")),
        agent_id=_str_or_none(payload.get("agent_id")),
        session_key=_str_or_none(payload.get("session_key")),
        trace_id=_str_or_none(payload.get("trace_id")),
        level=event.level,
        category=event.category,
        status=_str_or_none(payload.get("status")),
        tool_name=_str_or_none(payload.get("tool_name")),
        tool_call_id=_str_or_none(payload.get("tool_call_id")),
        duration_ms=_num_or_none(payload.get("duration_ms")),
        audit_ref=_str_or_none(payload.get("audit_ref")),
        message=_str_or_none(payload.get("message") or payload.get("error_message")),
        payload=payload,
    )


def normalized_from_run_record(record: Any) -> NormalizedTelemetryEvent:
    return NormalizedTelemetryEvent.model_validate(_run_timeline_event(record).model_dump(exclude_none=True))


def _telemetry_row(event: NormalizedTelemetryEvent) -> dict[str, Any]:
    return {
        "source": event.source,
        "event_type": event.type,
        "ts_ms": event.ts_ms,
        "response_id": event.response_id,
        "agent_id": event.agent_id,
        "session_key": event.session_key,
        "trace_id": event.trace_id,
        "seq": event.seq,
        "level": event.level,
        "category": event.category,
        "status": event.status,
        "tool_name": event.tool_name,
        "tool_call_id": event.tool_call_id,
        "duration_ms": event.duration_ms,
        "audit_ref": event.audit_ref,
        "message": event.message,
        "payload_json": event.payload,
    }


def _telemetry_event_from_row(row: dict[str, Any]) -> NormalizedTelemetryEvent:
    return NormalizedTelemetryEvent(
        source=str(row["source"]),
        type=str(row["event_type"]),
        ts_ms=int(row["ts_ms"]) if row.get("ts_ms") is not None else None,
        response_id=_str_or_none(row.get("response_id")),
        agent_id=_str_or_none(row.get("agent_id")),
        session_key=_str_or_none(row.get("session_key")),
        trace_id=_str_or_none(row.get("trace_id")),
        seq=int(row["seq"]) if row.get("seq") is not None else None,
        level=_str_or_none(row.get("level")),
        category=_str_or_none(row.get("category")),
        status=_str_or_none(row.get("status")),
        tool_name=_str_or_none(row.get("tool_name")),
        tool_call_id=_str_or_none(row.get("tool_call_id")),
        duration_ms=_num_or_none(row.get("duration_ms")),
        audit_ref=_str_or_none(row.get("audit_ref")),
        message=_str_or_none(row.get("message")),
        payload=row.get("payload_json") if isinstance(row.get("payload_json"), dict) else {},
    )


def _postgres_telemetry_events_create_sql(schema: str) -> str:
    return f"""
    CREATE TABLE IF NOT EXISTS {schema}.telemetry_events (
      id BIGSERIAL PRIMARY KEY,
      source TEXT NOT NULL,
      event_type TEXT NOT NULL,
      ts_ms BIGINT NULL,
      response_id TEXT NULL,
      agent_id TEXT NULL,
      session_key TEXT NULL,
      trace_id TEXT NULL,
      seq BIGINT NULL,
      level TEXT NULL,
      category TEXT NULL,
      status TEXT NULL,
      tool_name TEXT NULL,
      tool_call_id TEXT NULL,
      duration_ms DOUBLE PRECISION NULL,
      audit_ref TEXT NULL,
      message TEXT NULL,
      payload_json JSONB NOT NULL DEFAULT '{{}}'::jsonb,
      created_at TIMESTAMPTZ NOT NULL DEFAULT now()
    )
    """


def _run_timeline_event(record: Any) -> InternalObservabilityTimelineEvent:
    payload = {
        "status": getattr(record, "status", None),
        "effective_status": getattr(record, "effective_status", None),
        "stream": getattr(record, "stream", None),
    }
    return InternalObservabilityTimelineEvent(
        source="run",
        type="run." + str(getattr(record, "status", "created")),
        ts_ms=int(getattr(record, "created_at_ms", 0) or 0) or None,
        response_id=str(getattr(record, "response_id", "")),
        agent_id=str(getattr(record, "agent_id", "")),
        session_key=str(getattr(record, "session_key", "")),
        category="run",
        status=str(getattr(record, "effective_status", getattr(record, "status", ""))),
        payload={key: value for key, value in payload.items() if value is not None},
    )


def _run_item(record: Any) -> InternalObservabilityRunItem:
    return InternalObservabilityRunItem(
        response_id=str(getattr(record, "response_id", "")),
        agent_id=str(getattr(record, "agent_id", "")),
        session_key=str(getattr(record, "session_key", "")),
        stream=bool(getattr(record, "stream", False)),
        status=str(getattr(record, "status", "")),
        effective_status=str(getattr(record, "effective_status", getattr(record, "status", ""))),
        created_at_ms=int(getattr(record, "created_at_ms", 0) or 0),
        updated_at_ms=int(getattr(record, "updated_at_ms", 0) or 0),
        ended_at_ms=int(getattr(record, "ended_at_ms")) if getattr(record, "ended_at_ms", None) is not None else None,
    )


def _is_audit_event(event: InternalObservabilityTimelineEvent) -> bool:
    return event.source == "audit" or event.category == "audit"


def _audit_event_item(event: InternalObservabilityTimelineEvent) -> InternalAuditEventItem:
    payload = dict(event.payload or {})
    return InternalAuditEventItem(
        **event.model_dump(exclude_none=True),
        credential_id=_str_or_none(payload.get("credential_id")),
    )


def _matches_query(event: InternalObservabilityTimelineEvent, query: ObservabilityQuery) -> bool:
    if query.agent_id is not None and event.agent_id != query.agent_id:
        return False
    if query.session_key is not None and event.session_key != query.session_key:
        return False
    if query.response_id is not None and event.response_id != query.response_id:
        return False
    if query.trace_id is not None and event.trace_id != query.trace_id:
        return False
    if query.created_after_ms is not None and (event.ts_ms or 0) < query.created_after_ms:
        return False
    if query.created_before_ms is not None and (event.ts_ms or 0) > query.created_before_ms:
        return False
    return True


def _json_obj(raw: Any) -> dict[str, Any] | None:
    if not isinstance(raw, str):
        return None
    try:
        value = json.loads(raw)
    except json.JSONDecodeError:
        return None
    return value if isinstance(value, dict) else None


def _category_for_event(event_type: str) -> str:
    if ".tool." in event_type or event_type.startswith("anyagent.tool."):
        return "tool"
    if ".command." in event_type or event_type.startswith("anyagent.command."):
        return "command"
    if ".workspace." in event_type:
        return "workspace"
    if "mcp" in event_type:
        return "mcp"
    return "runtime"


def _is_mcp_payload(payload: dict[str, Any]) -> bool:
    return (
        "mcp" in str(payload.get("type") or "")
        or isinstance(payload.get("server_label"), str)
        or isinstance(payload.get("mcp_server_label"), str)
    )


def _token_totals(payloads: list[dict[str, Any]]) -> tuple[int, int, int]:
    input_tokens = 0
    output_tokens = 0
    cached_tokens = 0
    for payload in payloads:
        input_tokens += int(_nested_number(payload, "usage.input_tokens", "usage.prompt_tokens", "input_tokens") or 0)
        output_tokens += int(_nested_number(payload, "usage.output_tokens", "usage.completion_tokens", "output_tokens") or 0)
        cached_tokens += int(
            _nested_number(
                payload,
                "usage.input_tokens_details.cached_tokens",
                "usage.prompt_tokens_details.cached_tokens",
                "cached_tokens",
            )
            or 0
        )
    return input_tokens, output_tokens, cached_tokens


def _nested_number(payload: dict[str, Any], *paths: str) -> float | None:
    for path in paths:
        cursor: Any = payload
        for segment in path.split("."):
            cursor = cursor.get(segment) if isinstance(cursor, dict) else None
        if isinstance(cursor, (int, float)):
            return float(cursor)
    return None


def _first_number(payloads: list[dict[str, Any]], *paths: str) -> float | None:
    for payload in payloads:
        value = _nested_number(payload, *paths)
        if value is not None:
            return value
    return None


def _last_number(payloads: list[dict[str, Any]], *paths: str) -> float | None:
    found: float | None = None
    for payload in payloads:
        found = _nested_number(payload, *paths) or found
    return found


def _str_or_none(value: Any) -> str | None:
    return value if isinstance(value, str) and value else None


def _bool_or_none(value: Any) -> bool | None:
    return value if isinstance(value, bool) else None


def _num_or_none(value: Any) -> float | None:
    return float(value) if isinstance(value, (int, float)) and value >= 0 else None


def _num_int_or_none(value: Any) -> int | None:
    return int(value) if isinstance(value, (int, float)) and value >= 0 else None


def _agent_id(prompt_context: AnyAgentPromptContextEvent | None, payload: dict[str, Any], record: Any | None) -> str | None:
    return (
        prompt_context.agent_id
        if prompt_context is not None
        else _str_or_none(payload.get("agent_id")) or (_str_or_none(getattr(record, "agent_id", None)) if record is not None else None)
    )


def _session_key(prompt_context: AnyAgentPromptContextEvent | None, payload: dict[str, Any], record: Any | None) -> str | None:
    return (
        prompt_context.session_key
        if prompt_context is not None
        else _str_or_none(payload.get("session_key")) or (_str_or_none(getattr(record, "session_key", None)) if record is not None else None)
    )


def _text_length(value: Any) -> int:
    if isinstance(value, str):
        return len(value)
    if not isinstance(value, list):
        return 0
    total = 0
    for item in value:
        if isinstance(item, str):
            total += len(item)
        elif isinstance(item, dict) and isinstance(item.get("text"), str):
            total += len(item["text"])
    return total


def _turn_stats(items: list[dict[str, Any]]) -> tuple[int, int, int, list[InternalObservabilityTurnMetric]]:
    turns: list[dict[str, int]] = []
    for item in items:
        role = item.get("role")
        content_len = _text_length(item.get("content"))
        if role == "user":
            turns.append({"input_chars": content_len, "output_chars": 0})
        elif role == "assistant":
            if not turns:
                turns.append({"input_chars": 0, "output_chars": 0})
            turns[-1]["output_chars"] += content_len
    metrics = [
        InternalObservabilityTurnMetric(index=index, input_chars=turn["input_chars"], output_chars=turn["output_chars"])
        for index, turn in enumerate(turns, start=1)
    ]
    return len(metrics), sum(item.input_chars for item in metrics), sum(item.output_chars for item in metrics), metrics


def _input_to_transcript_items(value: Any) -> list[dict[str, Any]]:
    if isinstance(value, list):
        return [item for item in value if isinstance(item, dict)]
    return []


def _response_to_transcript_items(value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, dict):
        return []
    output = value.get("output")
    if not isinstance(output, list):
        return []
    items: list[dict[str, Any]] = []
    for item in output:
        if not isinstance(item, dict) or item.get("type") != "message":
            continue
        items.append({"role": item.get("role"), "content": item.get("content")})
    return items
