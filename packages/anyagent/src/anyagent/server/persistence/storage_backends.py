from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from typing import Any, Protocol

from anyagent.gateway.session import session_partition_key as build_session_partition_key
from anyagent.protocol.agent_api_internal import InternalEventItem, InternalEventsListResponse
from anyagent.protocol.responses_optional import AnyAgentResponseError
from anyagent.server.persistence.events import InMemoryEventStore, build_cached_event_store, build_postgres_event_store, build_redis_event_store
from anyagent.server.persistence.run_store import InMemoryRunStore, _local_run_record, build_cached_run_store, build_postgres_run_store, build_redis_run_store
from anyagent.server.persistence.session_store import (
    InMemorySessionStore,
    RedisSessionStore,
    SessionSnapshotVersionConflict,
    _local_session_record,
    build_cached_session_store,
    build_postgres_session_store,
    build_redis_session_store,
)
from anyagent.storage.settings import StorageSettings, active_storage_settings


class EventStore(Protocol):
    async def append(self, *, response_id: str, event: str | None, data: str) -> int: ...
    async def mark_started(self, *, response_id: str) -> None: ...
    async def mark_cancel_requested(self, *, response_id: str) -> None: ...
    async def mark_final(self, *, response_id: str, run_status: str, effective_run_status: str | None = None, response_json=None, error=None) -> None: ...
    async def get_response(self, response_id: str): ...
    async def get_status(self, response_id: str): ...
    async def list_events(self, *, response_id: str, last_seq: int = 0, limit: int = 200): ...
    async def latest_seq(self, response_id: str) -> int: ...
    async def stream_events(self, *, response_id: str, last_seq: int = 0): ...


class RunStore(Protocol):
    async def get(self, response_id: str): ...
    async def get_by_idempotency_key(self, idempotency_key: str): ...
    async def list(
        self,
        *,
        agent_id: str | None = None,
        session_key: str | None = None,
        response_id: str | None = None,
        limit: int = 100,
    ): ...
    async def create_started(self, *, response_id: str, agent_id: str, session_key: str, stream: bool, idempotency_key: str | None): ...
    async def mark_cancel_requested(self, response_id: str) -> None: ...
    async def mark_final(self, *, response_id: str, status: str, effective_status: str, final_response_json, error_json=None) -> None: ...


class SessionStore(Protocol):
    async def get(self, *, session_partition_key: str): ...
    async def upsert(self, *, session_partition_key: str, agent_id: str, session_key: str, snapshot_json, expected_snapshot_version: int | None): ...


@dataclass(slots=True)
class ServerStorageBundle:
    event_store: EventStore
    run_store: RunStore
    session_store: SessionStore
    resources: list[object] = field(default_factory=list)


class _ExternalSqlRunStoreAdapter:
    def __init__(self, *, store: Any) -> None:
        self._store = store

    async def get(self, response_id: str):
        record = await self._store.get(response_id)
        return None if record is None else _local_run_record(record)

    async def get_by_idempotency_key(self, idempotency_key: str):
        record = await self._store.get_by_idempotency_key(idempotency_key)
        return None if record is None else _local_run_record(record)

    async def list(
        self,
        *,
        agent_id: str | None = None,
        session_key: str | None = None,
        response_id: str | None = None,
        limit: int = 100,
    ):
        records = await self._store.list(
            agent_id=agent_id,
            session_key=session_key,
            response_id=response_id,
            limit=limit,
        )
        return [_local_run_record(record) for record in records]

    async def create_started(
        self,
        *,
        response_id: str,
        agent_id: str,
        session_key: str,
        stream: bool,
        idempotency_key: str | None,
    ):
        record = await self._store.create_started(
            response_id=response_id,
            session_partition_key=build_session_partition_key(agent_id=agent_id, session_key=session_key),
            stream=stream,
            idempotency_key=idempotency_key,
        )
        return _local_run_record(record, agent_id=agent_id, session_key=session_key)

    async def mark_cancel_requested(self, response_id: str) -> None:
        await self._store.mark_cancel_requested(response_id)

    async def mark_final(
        self,
        *,
        response_id: str,
        status: str,
        effective_status: str,
        final_response_json,
        error_json=None,
    ) -> None:
        _ = effective_status
        await self._store.set_final(
            response_id=response_id,
            status=status,
            final_response_json=final_response_json,
            error_json=error_json,
        )


class _ExternalSqlSessionStoreAdapter:
    def __init__(self, *, store: Any) -> None:
        self._store = store

    async def get(self, *, session_partition_key: str):
        record = await self._store.get(session_partition_key=session_partition_key)
        return None if record is None else _local_session_record(record)

    async def upsert(
        self,
        *,
        session_partition_key: str,
        agent_id: str,
        session_key: str,
        snapshot_json,
        expected_snapshot_version: int | None,
    ):
        if expected_snapshot_version is None:
            record = await self._store.create_if_absent(
                session_partition_key=session_partition_key,
                agent_id=agent_id,
                session_key=session_key,
                snapshot_json=snapshot_json,
            )
            return _local_session_record(record)

        ok, latest = await self._store.update_snapshot_cas(
            session_partition_key=session_partition_key,
            expected_snapshot_version=expected_snapshot_version,
            snapshot_json=snapshot_json,
            agent_id=agent_id,
            session_key=session_key,
        )
        if not ok:
            raise SessionSnapshotVersionConflict(
                session_partition_key=session_partition_key,
                expected_snapshot_version=expected_snapshot_version,
                actual_snapshot_version=None if latest is None else latest.snapshot_version,
            )
        if latest is None:
            raise RuntimeError("mysql session store CAS update returned no record")
        return _local_session_record(latest)


class _ExternalSqlEventStoreAdapter:
    def __init__(self, *, engine: Any, store: Any, dialect: str, schema_name: str | None = None, poll_interval_s: float = 0.05) -> None:
        try:
            from sqlalchemy import BOOLEAN, JSON, TEXT, Column, MetaData, String, Table
        except Exception as e:  # noqa: BLE001
            raise RuntimeError("mysql event store requires installing anyagent[mysql]") from e

        self._engine = engine
        self._store = store
        self._dialect = dialect
        self._schema_name = schema_name
        self._poll_interval_s = max(poll_interval_s, 0.01)
        self._init_lock = asyncio.Lock()
        self._initialized = False
        meta = MetaData()
        response_id_type = String(length=255) if dialect == "mysql" else TEXT
        text_type = String(length=64) if dialect == "mysql" else TEXT
        self._meta_table = Table(
            "event_runs",
            meta,
            Column("response_id", response_id_type, primary_key=True),
            Column("done", BOOLEAN, nullable=False, default=False),
            Column("run_status", text_type, nullable=True),
            Column("effective_run_status", text_type, nullable=True),
            Column("response_json", JSON, nullable=True),
            Column("error_json", JSON, nullable=True),
            schema=schema_name,
        )

    async def append(self, *, response_id: str, event: str | None, data: str) -> int:
        await self._ensure_meta_table()
        return await self._store.append(response_id=response_id, session_partition_key="", event=event, data=data)

    async def mark_started(self, *, response_id: str) -> None:
        await self._ensure_meta_table()
        from sqlalchemy import insert, select, update

        async with self._engine.begin() as conn:
            existing = (await conn.execute(select(self._meta_table.c.response_id).where(self._meta_table.c.response_id == response_id))).first()
            if existing is None:
                await conn.execute(
                    insert(self._meta_table).values(
                        response_id=response_id,
                        done=False,
                        run_status="started",
                        effective_run_status="in_progress",
                    )
                )
            await conn.execute(
                update(self._meta_table)
                .where(self._meta_table.c.response_id == response_id)
                .values(done=False, run_status="started", effective_run_status="in_progress")
            )

    async def mark_cancel_requested(self, *, response_id: str) -> None:
        await self._ensure_meta_table()
        from sqlalchemy import update

        async with self._engine.begin() as conn:
            await conn.execute(
                update(self._meta_table)
                .where(self._meta_table.c.response_id == response_id)
                .where(self._meta_table.c.done.is_(False))
                .values(run_status="aborted", effective_run_status="cancelled")
            )

    async def mark_final(
        self,
        *,
        response_id: str,
        run_status: str,
        effective_run_status: str | None = None,
        response_json: dict[str, Any] | None = None,
        error: AnyAgentResponseError | None = None,
    ) -> None:
        await self._ensure_meta_table()
        error_json = error.model_dump(exclude_none=True) if error is not None else None
        from sqlalchemy import insert, select, update

        async with self._engine.begin() as conn:
            existing = (await conn.execute(select(self._meta_table.c.response_id).where(self._meta_table.c.response_id == response_id))).first()
            if existing is None:
                await conn.execute(
                    insert(self._meta_table).values(
                        response_id=response_id,
                        done=True,
                        run_status=run_status,
                        effective_run_status=effective_run_status or run_status,
                        response_json=response_json,
                        error_json=error_json,
                    )
                )
            await conn.execute(
                update(self._meta_table)
                .where(self._meta_table.c.response_id == response_id)
                .values(
                    done=True,
                    run_status=run_status,
                    effective_run_status=effective_run_status or run_status,
                    response_json=response_json,
                    error_json=error_json,
                )
            )

    async def get_response(self, response_id: str) -> dict[str, Any] | None:
        row = await self._get_meta_row(response_id)
        value = None if row is None else row.get("response_json")
        return value if isinstance(value, dict) else None

    async def get_status(self, response_id: str) -> tuple[str | None, AnyAgentResponseError | None]:
        row = await self._get_meta_row(response_id)
        if row is None:
            return None, None
        error_json = row.get("error_json")
        error = None
        if isinstance(error_json, dict):
            try:
                error = AnyAgentResponseError.model_validate(error_json)
            except Exception:
                error = None
        return row.get("effective_run_status"), error

    async def list_events(self, *, response_id: str, last_seq: int = 0, limit: int = 200):
        await self._ensure_meta_table()
        meta = await self._get_meta_row(response_id)
        rows = await self._store.list(response_id=response_id, after_seq=last_seq, limit=limit)
        items = [InternalEventItem(seq=int(row.seq), event=row.event, data=row.data) for row in rows]
        latest = await self.latest_seq(response_id)
        next_last_seq = max(last_seq, items[-1].seq if items else latest if latest > 0 else last_seq)
        return InternalEventsListResponse(
            response_id=response_id,
            requested_last_seq=max(last_seq, 0),
            next_last_seq=max(next_last_seq, 0),
            events=items,
            done=bool(meta and meta.get("done")),
            run_status=None if meta is None else meta.get("run_status"),
            effective_run_status=None if meta is None else meta.get("effective_run_status"),
        )

    async def latest_seq(self, response_id: str) -> int:
        await self._ensure_meta_table()
        return await self._store.tail_seq(response_id=response_id)

    async def stream_events(self, *, response_id: str, last_seq: int = 0):
        next_seq = max(last_seq, 0)
        while True:
            resp = await self.list_events(response_id=response_id, last_seq=next_seq, limit=200)
            for item in resp.events:
                if item.seq <= next_seq:
                    continue
                yield item
                next_seq = item.seq
            if resp.done:
                return
            await asyncio.sleep(self._poll_interval_s)

    async def _get_meta_row(self, response_id: str) -> dict[str, Any] | None:
        from sqlalchemy import select

        async with self._engine.connect() as conn:
            row = (await conn.execute(select(self._meta_table).where(self._meta_table.c.response_id == response_id).limit(1))).mappings().first()
        return None if row is None else dict(row)

    async def _ensure_meta_table(self) -> None:
        if self._initialized:
            return
        async with self._init_lock:
            if self._initialized:
                return
            async with self._engine.begin() as conn:
                await conn.run_sync(self._meta_table.metadata.create_all)
            self._initialized = True


def build_event_store(*, backend: str, storage_settings: StorageSettings | None = None) -> EventStore:
    if backend == "inmemory":
        return InMemoryEventStore()
    if backend in {"postgres", "postgres-only"}:
        return build_postgres_event_store()
    if backend == "postgres-redis":
        return build_cached_event_store()
    if backend in {"external", "redis"}:
        settings = storage_settings or active_storage_settings()
        if backend == "external" and settings.effective_postgres_dsn is not None:
            if settings.redis_dsn is not None:
                return build_cached_event_store()
            return build_postgres_event_store()
        return build_redis_event_store()
    raise RuntimeError(f"event store backend not implemented: {backend}")


def build_run_store(*, backend: str, storage_settings: StorageSettings | None = None) -> RunStore:
    if backend == "inmemory":
        return InMemoryRunStore()
    if backend in {"postgres", "postgres-only"}:
        return build_postgres_run_store()
    if backend == "postgres-redis":
        return build_cached_run_store()
    if backend in {"external", "redis"}:
        settings = storage_settings or active_storage_settings()
        if backend == "external" and settings.effective_postgres_dsn is not None:
            if settings.redis_dsn is not None:
                return build_cached_run_store()
            return build_postgres_run_store()
        return build_redis_run_store()
    raise RuntimeError(f"run store backend not implemented: {backend}")


def build_session_store(*, backend: str, storage_settings: StorageSettings | None = None) -> SessionStore:
    if backend == "inmemory":
        return InMemorySessionStore()
    if backend in {"postgres", "postgres-only"}:
        return build_postgres_session_store()
    if backend == "postgres-redis":
        return build_cached_session_store()
    if backend in {"external", "redis"}:
        settings = storage_settings or active_storage_settings()
        if backend == "external" and settings.effective_postgres_dsn is not None:
            if settings.redis_dsn is not None:
                return build_cached_session_store()
            return build_postgres_session_store()
        return build_redis_session_store()
    raise RuntimeError(f"session store backend not implemented: {backend}")


def build_server_storage_bundle(
    *,
    event_store_backend: str,
    run_store_backend: str,
    session_store_backend: str,
    storage_settings: StorageSettings | None = None,
) -> ServerStorageBundle:
    settings = storage_settings or active_storage_settings()
    sql_backend = _select_sql_backend(settings)
    if sql_backend in {"mysql", "postgresql"} and any(
        backend in {"external", "postgres", "postgres-redis"} for backend in (event_store_backend, run_store_backend, session_store_backend)
    ):
        if sql_backend == "postgresql":
            return ServerStorageBundle(
                event_store=build_event_store(backend=event_store_backend),
                run_store=build_run_store(backend=run_store_backend),
                session_store=build_session_store(backend=session_store_backend),
                resources=[],
            )

        try:
            from anyagent.storage.external import (
                MySQLEventStore,
                MySQLRunStore,
                MySQLSessionStore,
                create_external_sql_engine,
                resolve_external_sql_backend_config,
            )
        except Exception as e:  # noqa: BLE001
            raise RuntimeError("mysql server storage requires installing anyagent[mysql]") from e

        config = resolve_external_sql_backend_config(
            postgres_dsn=settings.effective_postgres_dsn,
            mysql_dsn=settings.mysql_dsn,
            redis_dsn=settings.redis_dsn,
            schema_name=None,
            namespace=settings.redis_namespace,
            dialect=sql_backend,
        )
        engine = create_external_sql_engine(config)
        event_store = (
            _ExternalSqlEventStoreAdapter(engine=engine, store=MySQLEventStore(engine=engine), dialect="mysql")
            if event_store_backend == "external"
            else build_event_store(backend=event_store_backend)
        )
        run_store = (
            _ExternalSqlRunStoreAdapter(store=MySQLRunStore(engine=engine))
            if run_store_backend == "external"
            else build_run_store(backend=run_store_backend)
        )
        session_store = (
            _ExternalSqlSessionStoreAdapter(store=MySQLSessionStore(engine=engine))
            if session_store_backend == "external"
            else build_session_store(backend=session_store_backend)
        )
        return ServerStorageBundle(
            event_store=event_store,
            run_store=run_store,
            session_store=session_store,
            resources=[engine],
        )

    return ServerStorageBundle(
        event_store=build_event_store(backend=event_store_backend),
        run_store=build_run_store(backend=run_store_backend),
        session_store=build_session_store(backend=session_store_backend),
        resources=[],
    )


def _select_sql_backend(settings: StorageSettings) -> str | None:
    dialect = (settings.sql_backend_dialect or "auto").strip().lower()
    if dialect == "postgresql":
        return "postgresql"
    if dialect == "mysql":
        return "mysql"
    if settings.effective_postgres_dsn is not None:
        return "postgresql"
    if settings.mysql_dsn is not None:
        return "mysql"
    return None
