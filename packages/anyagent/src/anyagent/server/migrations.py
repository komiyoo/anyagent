from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from anyagent.storage.settings import StorageSettings


@dataclass(frozen=True, slots=True)
class StorageMigration:
    version: str
    path: Path


def list_storage_migrations() -> list[StorageMigration]:
    migrations_dir = Path(__file__).with_name("migrations")
    out: list[StorageMigration] = []
    for path in sorted(migrations_dir.glob("*.sql")):
        out.append(StorageMigration(version=path.stem, path=path))
    return out


def apply_storage_migrations(
    *,
    postgres_dsn: str | None = None,
    postgres_schema: str | None = None,
    dry_run: bool = False,
) -> dict[str, list[str] | str]:
    settings = StorageSettings()
    effective_dsn = postgres_dsn or (str(settings.postgres_dsn) if settings.postgres_dsn is not None else None)
    if effective_dsn is None:
        raise RuntimeError("storage migrations require POSTGRES_DSN")
    effective_schema = postgres_schema or settings.postgres_schema

    migrations = list_storage_migrations()
    planned = [m.version for m in migrations]
    if dry_run:
        return {"schema": effective_schema, "planned": planned, "applied": []}

    from psycopg import Connection

    applied: list[str] = []
    with Connection.connect(effective_dsn) as conn:
        with conn.cursor() as cur:
            cur.execute(f"CREATE SCHEMA IF NOT EXISTS {effective_schema}")
            cur.execute(
                f"""
                CREATE TABLE IF NOT EXISTS {effective_schema}.schema_migrations (
                  version TEXT PRIMARY KEY,
                  applied_at TIMESTAMPTZ NOT NULL DEFAULT now()
                )
                """
            )
            cur.execute(f"SELECT version FROM {effective_schema}.schema_migrations ORDER BY version")
            existing = {str(row[0]) for row in cur.fetchall()}

            for migration in migrations:
                if migration.version in existing:
                    continue
                sql = migration.path.read_text(encoding="utf-8").replace("{{schema}}", effective_schema)
                cur.execute(sql)
                cur.execute(
                    f"INSERT INTO {effective_schema}.schema_migrations(version) VALUES (%s)",
                    (migration.version,),
                )
                applied.append(migration.version)
        conn.commit()

    return {"schema": effective_schema, "planned": planned, "applied": applied}
