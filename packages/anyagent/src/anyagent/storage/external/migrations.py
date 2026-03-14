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
    # anyagent/storage/external/migrations.py -> anyagent/server/migrations
    return Path(__file__).resolve().parents[2] / "server" / "migrations"


def _apply_postgres_migrations(*, config: ExternalSqlBackendConfig) -> None:
    if config.postgres_dsn is None:
        raise RuntimeError("POSTGRES_DSN is required to run PostgreSQL migrations")

    schema_name = _validate_schema_name(config.schema_name or "public")

    import psycopg  # type: ignore[import-not-found]

    migrations = _load_sql_files(default_postgres_migrations_dir())
    if not migrations:
        return

    with psycopg.connect(str(config.postgres_dsn), autocommit=False) as conn:
        with conn.cursor() as cur:
            cur.execute(f'CREATE SCHEMA IF NOT EXISTS "{schema_name}"')
            cur.execute(f'SET search_path TO "{schema_name}"')

            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS schema_migrations (
                  version     TEXT PRIMARY KEY,
                  applied_at  TIMESTAMPTZ NOT NULL DEFAULT now()
                );
                """
            )
            cur.execute("SELECT version FROM schema_migrations")
            applied = {row[0] for row in cur.fetchall() if isinstance(row[0], str)}

            for version, sql in migrations:
                if version in applied:
                    continue
                cur.execute(_render_postgres_migration_sql(sql=sql, schema_name=schema_name))
                cur.execute("INSERT INTO schema_migrations(version) VALUES (%s)", (version,))

        conn.commit()


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


def _load_sql_files(migrations_dir: Path) -> list[tuple[str, str]]:
    if not migrations_dir.exists():
        return []
    paths = sorted(path for path in migrations_dir.iterdir() if path.is_file() and path.suffix == ".sql")
    out: list[tuple[str, str]] = []
    for path in paths:
        version = path.name.split(".", 1)[0]
        out.append((version, path.read_text(encoding="utf-8")))
    return out


def _render_postgres_migration_sql(*, sql: str, schema_name: str) -> str:
    return sql.replace("{{schema}}", f'"{schema_name}"')
