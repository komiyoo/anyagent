from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from typing import Literal

from psycopg_pool import AsyncConnectionPool
from redis.asyncio import Redis

from ..settings import Settings
from .inmemory import InMemoryEventStore, InMemoryLeaseLock, InMemoryRunStore
from .postgres import PostgresEventStore, PostgresRunStore
from .redis_lock import RedisLeaseLock


logger = logging.getLogger("anyagent.agent_api.storage")

_SCHEMA_RE = re.compile(r"^[a-zA-Z_][a-zA-Z0-9_]{0,62}$")


StorageModeResolved = Literal["none", "external"]


@dataclass
class StorageRuntime:
    mode: StorageModeResolved
    run_store: object
    event_store: object
    lease_lock: object
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

        run_store = InMemoryRunStore()
        event_store = InMemoryEventStore()
        lease_lock = InMemoryLeaseLock()
        return StorageRuntime(mode="none", run_store=run_store, event_store=event_store, lease_lock=lease_lock)

    # external
    schema = (settings.postgres_schema or "public").strip() or "public"
    if not _SCHEMA_RE.match(schema):
        raise RuntimeError("invalid POSTGRES_SCHEMA (expected [a-zA-Z_][a-zA-Z0-9_]{0,62})")

    async def _configure(conn) -> None:  # type: ignore[no-untyped-def]
        async with conn.cursor() as cur:
            await cur.execute(f'CREATE SCHEMA IF NOT EXISTS "{schema}"')
            await cur.execute(f'SET search_path TO "{schema}"')

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

    logger.info("storage enabled (external)", extra={"postgres_schema": schema, "redis_namespace": settings.redis_namespace})
    return StorageRuntime(
        mode="external",
        run_store=run_store,
        event_store=event_store,
        lease_lock=lease_lock,
        pg_pool=pg_pool,
        redis=redis,
    )
