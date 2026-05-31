from __future__ import annotations

import asyncio
import re
from pathlib import Path

from .config import ExternalSqlBackendConfig, create_external_sql_engine
from .schema import build_storage_tables

_SCHEMA_RE = re.compile(r"^[a-zA-Z_][a-zA-Z0-9_]{0,62}$")


def apply_external_storage_schema(*, config: ExternalSqlBackendConfig) -> None:
    if config.dialect == "postgresql":
        _apply_postgres_migrations(config=config)
        return
    if config.dialect == "mysql":
        asyncio.run(apply_external_storage_schema_async(config=config))
        return
    raise RuntimeError(f"unsupported sql backend dialect: {config.dialect}")


async def apply_external_storage_schema_async(*, config: ExternalSqlBackendConfig) -> None:
    if config.dialect == "postgresql":
        _apply_postgres_migrations(config=config)
        return
    if config.dialect == "mysql":
        await _apply_mysql_schema_async(config=config)
        return
    raise RuntimeError(f"unsupported sql backend dialect: {config.dialect}")


def default_postgres_migrations_dir() -> Path:
    # PostgreSQL migrations are managed by Alembic; this helper remains for
    # compatibility with older callers that only need a discoverable path.
    return Path(__file__).resolve().parents[1] / "alembic" / "versions"


def _apply_postgres_migrations(*, config: ExternalSqlBackendConfig) -> None:
    if config.postgres_dsn is None:
        raise RuntimeError("POSTGRES_DSN is required to run PostgreSQL migrations")
    from anyagent.server.db.migrations import apply_storage_migrations

    apply_storage_migrations(postgres_dsn=str(config.postgres_dsn), postgres_schema=_validate_schema_name(config.schema_name or "public"))


async def _apply_mysql_schema_async(*, config: ExternalSqlBackendConfig) -> None:
    if config.mysql_dsn is None:
        raise RuntimeError("MYSQL_DSN is required to run MySQL schema initialization")

    engine = create_external_sql_engine(config)
    tables = build_storage_tables(schema_name=None, dialect="mysql")
    try:
        async with engine.begin() as conn:
            await conn.run_sync(tables.metadata.create_all)
    finally:
        await engine.dispose()


def _validate_schema_name(schema_name: str) -> str:
    normalized = schema_name.strip()
    if not _SCHEMA_RE.match(normalized):
        raise ValueError("invalid POSTGRES_SCHEMA (expected [a-zA-Z_][a-zA-Z0-9_]{0,62})")
    return normalized

