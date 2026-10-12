from __future__ import annotations

import io
import os
from contextlib import redirect_stdout
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from anyagent.storage.settings import StorageSettings, active_storage_settings


@dataclass(frozen=True, slots=True)
class StorageMigration:
    version: str
    path: Path


def list_storage_migrations() -> list[StorageMigration]:
    versions_dir = _alembic_dir() / "versions"
    return [StorageMigration(version=path.stem, path=path) for path in sorted(versions_dir.glob("*.py")) if path.name != "__init__.py"]


def apply_storage_migrations(
    *,
    postgres_dsn: str | None = None,
    postgres_schema: str | None = None,
    dry_run: bool = False,
) -> dict[str, list[str] | str]:
    """Compatibility wrapper for the old storage-migrate command.

    PostgreSQL schema changes are owned by Alembic. This function keeps the
    historical CLI/API surface while routing to the Alembic revision graph.
    """

    settings = active_storage_settings()
    effective_schema = postgres_schema or settings.postgres_schema
    planned = [migration.version for migration in list_storage_migrations()]
    if dry_run:
        return {"schema": effective_schema, "planned": planned, "applied": []}

    effective_dsn = postgres_dsn or (str(settings.effective_postgres_dsn) if settings.effective_postgres_dsn is not None else None)
    if effective_dsn is None:
        raise RuntimeError("storage migrations require POSTGRES_DSN or DATABASE_URL")

    before = _current_revision(postgres_dsn=effective_dsn, postgres_schema=effective_schema)
    _run_alembic("upgrade", "head", postgres_dsn=effective_dsn, postgres_schema=effective_schema)
    after = _current_revision(postgres_dsn=effective_dsn, postgres_schema=effective_schema)
    applied = planned if before != after else []
    return {"schema": effective_schema, "planned": planned, "applied": applied}


def _current_revision(*, postgres_dsn: str, postgres_schema: str) -> str:
    out = io.StringIO()
    with redirect_stdout(out):
        _run_alembic("current", postgres_dsn=postgres_dsn, postgres_schema=postgres_schema)
    return out.getvalue().strip()


def _run_alembic(command_name: str, revision: str | None = None, *, postgres_dsn: str, postgres_schema: str) -> None:
    try:
        from alembic import command as alembic_cmd
        from alembic.config import Config
    except ImportError as exc:
        raise RuntimeError("alembic is required: pip install anyagent[postgres]") from exc

    effective_dsn = postgres_dsn
    if effective_dsn.startswith("postgresql://"):
        effective_dsn = "postgresql+psycopg://" + effective_dsn[len("postgresql://") :]

    old_schema = os.environ.get("POSTGRES_SCHEMA")
    os.environ["POSTGRES_SCHEMA"] = postgres_schema
    try:
        cfg = Config()
        cfg.set_main_option("script_location", str(_alembic_dir()))
        cfg.set_main_option("sqlalchemy.url", effective_dsn)
        cmd: Any = getattr(alembic_cmd, command_name)
        if revision is None:
            cmd(cfg)
        else:
            cmd(cfg, revision)
    finally:
        if old_schema is None:
            os.environ.pop("POSTGRES_SCHEMA", None)
        else:
            os.environ["POSTGRES_SCHEMA"] = old_schema


def _alembic_dir() -> Path:
    return Path(__file__).resolve().parents[2] / "storage" / "alembic"
