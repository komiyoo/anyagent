from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Literal, Protocol

from psycopg_pool import AsyncConnectionPool
from redis.asyncio import Redis

from ..settings import Settings
from .inmemory import InMemoryEventStore, InMemoryLeaseLock, InMemoryRunStore, InMemorySessionStore
from .models import EventRecord, RunRecord, SessionRecord
from .postgres import PostgresEventStore, PostgresRunStore, PostgresSessionStore
from .redis_lock import RedisLeaseLock
from .rollout import RolloutFileWriter


logger = logging.getLogger("anyagent.agent_api.storage")

_SCHEMA_RE = re.compile(r"^[a-zA-Z_][a-zA-Z0-9_]{0,62}$")


StorageModeResolved = Literal["none", "external"]


class LeaseLockHandleProto(Protocol):
    key: str
    owner: str


class LeaseLockProto(Protocol):
    async def acquire(self, *, key: str, owner: str, ttl_ms: int, wait_timeout_ms: int) -> LeaseLockHandleProto | None: ...

    async def renew(self, *, key: str, owner: str, ttl_ms: int) -> bool: ...

    async def release(self, *, key: str, owner: str) -> bool: ...


class RunStoreProto(Protocol):
    async def get_by_idempotency_key(self, key: str) -> RunRecord | None: ...

    async def get(self, response_id: str) -> RunRecord | None: ...

    async def try_create_started(
        self,
        *,
        response_id: str,
        session_partition_key: str,
        idempotency_key: str,
        stream: bool,
    ) -> tuple[bool, RunRecord]: ...

    async def set_final(
        self,
        *,
        response_id: str,
        status: str,
        final_response_json: dict | None,
        error_json: dict | None,
    ) -> None: ...


class RunStoreWithLastEventSeqProto(RunStoreProto, Protocol):
    async def set_last_event_seq(self, *, response_id: str, last_event_seq: int) -> None: ...


class RunStoreWithSessionSnapshotProto(RunStoreProto, Protocol):
    async def set_final_with_session_snapshot(
        self,
        *,
        response_id: str,
        status: str,
        final_response_json: dict | None,
        error_json: dict | None,
        session_partition_key: str,
        agent_id: str,
        session_key: str,
        snapshot_json: dict,
        expected_snapshot_version: int,
    ) -> tuple[bool, SessionRecord | None]: ...


class EventStoreProto(Protocol):
    async def append(self, *, response_id: str, session_partition_key: str, event: str | None, data: str) -> int: ...

    async def list(self, *, response_id: str, after_seq: int, limit: int) -> list[EventRecord]: ...


class EventStoreWithWaitNewProto(EventStoreProto, Protocol):
    async def wait_new(self, *, response_id: str, after_seq: int, timeout_s: float) -> None: ...


class EventStoreWithTailSeqProto(EventStoreProto, Protocol):
    async def tail_seq(self, *, response_id: str) -> int: ...


class SessionStoreProto(Protocol):
    async def get(self, *, session_partition_key: str) -> SessionRecord | None: ...

    async def create_if_absent(
        self,
        *,
        session_partition_key: str,
        agent_id: str,
        session_key: str,
        snapshot_json: dict,
    ) -> SessionRecord: ...

    async def update_snapshot_cas(
        self,
        *,
        session_partition_key: str,
        expected_snapshot_version: int,
        snapshot_json: dict,
        agent_id: str,
        session_key: str,
    ) -> tuple[bool, SessionRecord | None]: ...


@dataclass
class StorageRuntime:
    mode: StorageModeResolved
    run_store: RunStoreProto
    event_store: EventStoreProto
    lease_lock: LeaseLockProto
    session_store: SessionStoreProto
    rollout_writer: RolloutFileWriter | None = None
    pg_pool: AsyncConnectionPool | None = None
    redis: Redis | None = None

    async def aclose(self) -> None:
        if self.pg_pool is not None:
            await self.pg_pool.close()
        if self.redis is not None:
            try:
                await self.redis.aclose()
            except Exception:  # noqa: BLE001
                return


def _resolve_mode(settings: Settings) -> StorageModeResolved:
    mode = (settings.storage_mode or "auto").strip().lower()
    if mode not in {"auto", "none", "external"}:
        raise RuntimeError("invalid STORAGE_MODE (expected auto|none|external)")

    has_pg = settings.postgres_dsn is not None
    has_redis = settings.redis_dsn is not None

    if mode == "none":
        return "none"
    if mode == "external":
        if not has_pg or not has_redis:
            raise RuntimeError("STORAGE_MODE=external requires both POSTGRES_DSN and REDIS_DSN")
        return "external"

    # auto
    if has_pg and has_redis:
        return "external"
    return "none"


async def create_storage_runtime(settings: Settings) -> StorageRuntime:
    resolved = _resolve_mode(settings)

    if resolved == "none":
        if settings.postgres_dsn is not None or settings.redis_dsn is not None:
            logger.warning(
                "storage disabled due to incomplete config (auto mode); running in in-memory mode",
                extra={"has_postgres_dsn": settings.postgres_dsn is not None, "has_redis_dsn": settings.redis_dsn is not None},
            )
        else:
            logger.warning("storage disabled (no DSN configured); running in in-memory mode")

        workspace_root = Path(settings.workspace_dir).expanduser().resolve()
        rollout_root = (settings.rollout_root_dir or "").strip()
        if rollout_root:
            rr = Path(rollout_root).expanduser()
            if not rr.is_absolute():
                rr = (workspace_root / rr).resolve()
        else:
            rr = workspace_root / ".runs" / "rollouts"

        rollout_writer = RolloutFileWriter(
            root_dir=rr,
            max_file_bytes=int(getattr(settings, "rollout_rotate_max_bytes", 0) or 0),
            max_file_age_seconds=int(getattr(settings, "rollout_rotate_max_age_seconds", 0) or 0),
            max_rotated_files=int(getattr(settings, "rollout_rotate_keep_files", 16) or 16),
        )
        run_store = InMemoryRunStore(rollout_writer=rollout_writer)
        event_store = InMemoryEventStore(rollout_writer=rollout_writer)
        lease_lock = InMemoryLeaseLock()
        session_store = InMemorySessionStore(rollout_writer=rollout_writer)
        logger.info("rollout file writer enabled", extra={"rollout_root_dir": str(rr)})
        return StorageRuntime(
            mode="none",
            run_store=run_store,
            event_store=event_store,
            lease_lock=lease_lock,
            session_store=session_store,
            rollout_writer=rollout_writer,
        )

    # external
    schema = (settings.postgres_schema or "public").strip() or "public"
    if not _SCHEMA_RE.match(schema):
        raise RuntimeError("invalid POSTGRES_SCHEMA (expected [a-zA-Z_][a-zA-Z0-9_]{0,62})")

    async def _configure(conn) -> None:  # type: ignore[no-untyped-def]
        async with conn.cursor() as cur:
            await cur.execute(f'CREATE SCHEMA IF NOT EXISTS "{schema}"')
            await cur.execute(f'SET search_path TO "{schema}"')
        # psycopg_pool requires configure hook to leave connection idle (not INTRANS).
        await conn.commit()

    pg_pool = AsyncConnectionPool(
        conninfo=str(settings.postgres_dsn),
        open=False,
        kwargs={"autocommit": False},
        configure=_configure,
        max_size=10,
    )
    await pg_pool.open()

    redis = Redis.from_url(str(settings.redis_dsn))
    run_store = PostgresRunStore(pool=pg_pool)
    event_store = PostgresEventStore(pool=pg_pool)
    lease_lock = RedisLeaseLock(redis=redis, namespace=settings.redis_namespace)
    session_store = PostgresSessionStore(pool=pg_pool)

    logger.info("storage enabled (external)", extra={"postgres_schema": schema, "redis_namespace": settings.redis_namespace})
    return StorageRuntime(
        mode="external",
        run_store=run_store,
        event_store=event_store,
        lease_lock=lease_lock,
        session_store=session_store,
        rollout_writer=None,
        pg_pool=pg_pool,
        redis=redis,
    )
