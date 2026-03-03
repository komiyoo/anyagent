from __future__ import annotations

import re
from pathlib import Path

from ..settings import Settings


_SCHEMA_RE = re.compile(r"^[a-zA-Z_][a-zA-Z0-9_]{0,62}$")


def _validate_schema_name(schema: str) -> str:
    s = schema.strip()
    if not _SCHEMA_RE.match(s):
        raise ValueError("invalid POSTGRES_SCHEMA (expected [a-zA-Z_][a-zA-Z0-9_]{0,62})")
    return s


def _migrations_dir() -> Path:
    # apps/agent-api/src/anyagent_agent_api/storage/migrate.py -> apps/agent-api
    app_dir = Path(__file__).resolve().parents[3]
    return app_dir / "migrations"


def _load_sql_files() -> list[tuple[str, str]]:
    mig_dir = _migrations_dir()
    if not mig_dir.exists():
        return []
    paths = sorted(p for p in mig_dir.iterdir() if p.is_file() and p.name.endswith(".sql"))
    out: list[tuple[str, str]] = []
    for p in paths:
        version = p.name.split(".", 1)[0]
        text = p.read_text(encoding="utf-8")
        out.append((version, text))
    return out


def apply_postgres_migrations(*, settings: Settings) -> None:
    """
    Apply SQL-first migrations to Postgres.

    Env:
    - POSTGRES_DSN (required)
    - POSTGRES_SCHEMA (optional; default "public")
    """
    if settings.postgres_dsn is None:
        raise RuntimeError("POSTGRES_DSN is required to run migrations")

    schema = _validate_schema_name(settings.postgres_schema or "public")

    # Import lazily: avoid importing DB drivers during normal server startup.
    import psycopg  # type: ignore[import-not-found]

    migrations = _load_sql_files()
    if not migrations:
        return

    with psycopg.connect(str(settings.postgres_dsn), autocommit=False) as conn:
        with conn.cursor() as cur:
            cur.execute(f'CREATE SCHEMA IF NOT EXISTS "{schema}"')
            cur.execute(f'SET search_path TO "{schema}"')

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
                cur.execute(sql)
                cur.execute("INSERT INTO schema_migrations(version) VALUES (%s)", (version,))

        conn.commit()


def main() -> None:
    settings = Settings()
    apply_postgres_migrations(settings=settings)

