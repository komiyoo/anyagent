from __future__ import annotations

import inspect
import logging
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .contracts import EventStore, LeaseLock, RunStore, SessionStore, SessionWorkspaceStore
from .inmemory import InMemoryEventStore, InMemoryLeaseLock, InMemoryRunStore, InMemorySessionStore
from .rollout import RolloutFileWriter
from .settings import StorageSettings


logger = logging.getLogger("anyagent.storage.runtime")

_SCHEMA_RE = re.compile(r"^[a-zA-Z_][a-zA-Z0-9_]{0,62}$")


async def _maybe_close(resource: Any) -> None:
    if resource is None:
        return
    for attr in ("aclose", "close"):
        closer = getattr(resource, attr, None)
        if not callable(closer):
            continue
        result = closer()
        if inspect.isawaitable(result):
            await result
        return


@dataclass(slots=True)
class StorageRuntime:
    mode: str
    run_store: RunStore
    event_store: EventStore
    lease_lock: LeaseLock
    session_store: SessionStore
    workspace_store: SessionWorkspaceStore | None = None
    rollout_writer: Any | None = None
    sql_engine: Any | None = None
    pg_pool: Any | None = None
    redis: Any | None = None

    async def aclose(self) -> None:
        await _maybe_close(self.sql_engine)
        await _maybe_close(self.pg_pool)
        await _maybe_close(self.redis)


def resolve_storage_runtime_mode(settings: StorageSettings) -> str:
    mode = (settings.storage_mode or "auto").strip().lower()
    if mode not in {"auto", "none", "external"}:
        raise RuntimeError("invalid STORAGE_MODE (expected auto|none|external)")

    has_sql = settings.postgres_dsn is not None or settings.mysql_dsn is not None
    has_redis = settings.redis_dsn is not None

    if mode == "none":
        return "none"
    if mode == "external":
        if not has_sql:
            raise RuntimeError("STORAGE_MODE=external requires POSTGRES_DSN or MYSQL_DSN")
        return "external"
    if has_sql:
        return "external"
    return "none"


def resolve_rollout_runtime_root(*, workspace_dir: str | Path, rollout_root_dir: str | None) -> Path:
    workspace_root = Path(workspace_dir).expanduser().resolve()
    root = (rollout_root_dir or "").strip()
    if root:
        candidate = Path(root).expanduser()
        if not candidate.is_absolute():
            candidate = workspace_root / candidate
        return candidate.resolve()
    return workspace_root / ".runs" / "rollouts"


async def create_storage_runtime(
    settings: StorageSettings | None = None,
    *,
    workspace_dir: str | Path = ".",
) -> StorageRuntime:
    storage_settings = settings or StorageSettings()
    resolved = resolve_storage_runtime_mode(storage_settings)

    if resolved == "none":
        if storage_settings.postgres_dsn is not None or storage_settings.mysql_dsn is not None or storage_settings.redis_dsn is not None:
            logger.warning(
                "storage disabled due to incomplete config (auto mode); running in in-memory mode",
                extra={
                    "has_postgres_dsn": storage_settings.postgres_dsn is not None,
                    "has_mysql_dsn": storage_settings.mysql_dsn is not None,
                    "has_redis_dsn": storage_settings.redis_dsn is not None,
                },
            )
        else:
            logger.warning("storage disabled (no DSN configured); running in in-memory mode")

        rollout_root = resolve_rollout_runtime_root(
            workspace_dir=workspace_dir,
            rollout_root_dir=storage_settings.rollout_root_dir,
        )
        rollout_writer = RolloutFileWriter(
            root_dir=rollout_root,
            max_file_bytes=int(storage_settings.rollout_rotate_max_bytes or 0),
            max_file_age_seconds=int(storage_settings.rollout_rotate_max_age_seconds or 0),
            max_rotated_files=int(storage_settings.rollout_rotate_keep_files or 16),
        )
        logger.info("rollout file writer enabled", extra={"rollout_root_dir": str(rollout_root)})
        return StorageRuntime(
            mode="none",
            run_store=InMemoryRunStore(rollout_writer=rollout_writer),
            event_store=InMemoryEventStore(rollout_writer=rollout_writer),
            lease_lock=InMemoryLeaseLock(),
            session_store=InMemorySessionStore(rollout_writer=rollout_writer),
            rollout_writer=rollout_writer,
        )

    schema = (storage_settings.postgres_schema or "public").strip() or "public"
    if not _SCHEMA_RE.match(schema):
        raise RuntimeError("invalid POSTGRES_SCHEMA (expected [a-zA-Z_][a-zA-Z0-9_]{0,62})")

    try:
        from .external import (
            MySQLEventStore,
            MySQLRunStore,
            MySQLSessionStore,
            PostgresEventStore,
            PostgresLeaseLock,
            PostgresRunStore,
            PostgresSessionStore,
            create_external_sql_engine,
            resolve_external_sql_backend_config,
        )
    except Exception as e:  # noqa: BLE001
        raise RuntimeError(
            "external storage runtime requires installing anyagent[postgres] or anyagent[mysql]"
        ) from e

    has_redis = storage_settings.redis_dsn is not None
    sql_config = resolve_external_sql_backend_config(
        postgres_dsn=storage_settings.postgres_dsn,
        mysql_dsn=storage_settings.mysql_dsn,
        redis_dsn=storage_settings.redis_dsn,
        schema_name=schema,
        namespace=storage_settings.redis_namespace,
        dialect=storage_settings.sql_backend_dialect,
    )
    sql_engine = create_external_sql_engine(sql_config)
    if sql_config.dialect == "mysql":
        run_store = MySQLRunStore(engine=sql_engine)
        event_store = MySQLEventStore(engine=sql_engine)
        session_store = MySQLSessionStore(engine=sql_engine)
    else:
        run_store = PostgresRunStore(engine=sql_engine, schema_name=schema)
        event_store = PostgresEventStore(engine=sql_engine, schema_name=schema)
        session_store = PostgresSessionStore(engine=sql_engine, schema_name=schema)

    if has_redis:
        from redis.asyncio import Redis
        from .external import RedisLeaseLock
        redis = Redis.from_url(str(storage_settings.redis_dsn))
        lease_lock = RedisLeaseLock(redis=redis, namespace=storage_settings.redis_namespace)
    else:
        redis = None
        if sql_config.dialect == "postgresql":
            lease_lock = PostgresLeaseLock(engine=sql_engine, schema_name=schema)
            logger.info("Redis not configured; using PostgreSQL lease lock")
        else:
            lease_lock = InMemoryLeaseLock()
            logger.info("Redis not configured; using in-memory lease lock (single-node only)")

    logger.info(
        "storage enabled (external)",
        extra={"sql_backend_dialect": sql_config.dialect, "postgres_schema": schema, "has_redis": has_redis},
    )
    return StorageRuntime(
        mode="external",
        run_store=run_store,
        event_store=event_store,
        lease_lock=lease_lock,
        session_store=session_store,
        rollout_writer=None,
        sql_engine=sql_engine,
        redis=redis,
    )
