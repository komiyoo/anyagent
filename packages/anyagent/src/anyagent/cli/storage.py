"""`anyagent storage` and `anyagent db`."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

from anyagent.cli.admin_client import admin_client_from_args, add_admin_flags
from anyagent.server.db.migrations import apply_storage_migrations
from anyagent.storage.retention import run_retention_from_args
from anyagent.storage.rollout_replay import ReplayFilters, replay_rollout_records, resolve_rollout_root_dir
from anyagent.storage.settings import active_storage_settings


def register_storage(subparsers: Any, bind: Any) -> None:
    """Register nested storage commands and Alembic db commands."""

    storage = subparsers.add_parser("storage", help="Storage operations.")
    storage_sub = storage.add_subparsers(dest="storage_command", required=True)

    health = storage_sub.add_parser("health", help="Check built-in server storage backends and connectivity.")
    add_admin_flags(health)
    bind(health, ("storage", "health"), cmd_storage_health)

    migrate = storage_sub.add_parser("migrate", help="Apply PostgreSQL storage migrations.")
    migrate.add_argument("--postgres-dsn", default=None, help="Override the configured Postgres DSN.")
    migrate.add_argument("--postgres-schema", default=None, help="Override the configured Postgres schema.")
    migrate.add_argument("--dry-run", action="store_true", help="Only print planned migrations.")
    bind(migrate, ("storage", "migrate"), cmd_storage_migrate)

    replay = storage_sub.add_parser("replay", help="Replay local rollout records from Core storage journals.")
    _add_storage_replay_flags(replay)
    bind(replay, ("storage", "replay"), cmd_storage_replay)

    retention = storage_sub.add_parser("retention", help="Run PostgreSQL storage retention maintenance.")
    _add_storage_retention_flags(retention)
    bind(retention, ("storage", "retention"), cmd_storage_retention)

    db = subparsers.add_parser("db", help="Database migration management (Alembic).")
    db_sub = db.add_subparsers(dest="db_command", required=True)
    db_migrate = db_sub.add_parser("migrate", help="Run all pending Alembic migrations (upgrade head).")
    db_migrate.add_argument("--sql", action="store_true", help="Generate SQL without executing (offline mode).")
    bind(db_migrate, ("db", "migrate"), cmd_db_migrate)
    db_downgrade = db_sub.add_parser("downgrade", help="Downgrade one revision.")
    db_downgrade.add_argument("--revision", default="-1", help="Target revision (default: -1).")
    bind(db_downgrade, ("db", "downgrade"), cmd_db_downgrade)
    db_current = db_sub.add_parser("current", help="Show current migration revision.")
    bind(db_current, ("db", "current"), cmd_db_current)
    db_history = db_sub.add_parser("history", help="Show migration history.")
    bind(db_history, ("db", "history"), cmd_db_history)
    db_stamp = db_sub.add_parser("stamp", help="Stamp database with a revision without running migrations.")
    db_stamp.add_argument("revision", help="Revision to stamp (e.g. 'head', '0001').")
    bind(db_stamp, ("db", "stamp"), cmd_db_stamp)


def _add_storage_replay_flags(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--root-dir", default=None, help="Rollout root directory.")
    parser.add_argument("--workspace-dir", default=None, help="Workspace root used when --root-dir is not set.")
    parser.add_argument("--session-partition-key", default=None, help="Filter by exact session_partition_key.")
    parser.add_argument("--response-id", default=None, help="Filter by exact response_id.")
    parser.add_argument("--kind", action="append", default=None, help="Filter by kind (repeatable).")
    parser.add_argument("--last-seq", type=int, default=0, help="Event replay cursor: only return event_appended with seq > last_seq.")
    parser.add_argument("--limit", type=int, default=200, help="Max records to return (default: 200, max: 5000).")
    parser.add_argument("--format", choices=["json", "jsonl"], default="json", help="Output format.")
    parser.add_argument("--include-fingerprint", action="store_true", help="Include per-record fingerprint in output.")


def _add_storage_retention_flags(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--apply", action="store_true", help="Apply changes (default: plan-only, no writes).")
    parser.add_argument("--dsn", default=None, help="Postgres DSN. Defaults to the configured storage DSN.")
    parser.add_argument("--schema", default=None, help="Postgres schema. Defaults to the configured storage schema.")
    parser.add_argument("--batch-size", type=int, default=500, help="Max rows per batch (default: 500).")
    parser.add_argument("--max-batches", type=int, default=200, help="Max batches per action (default: 200).")
    parser.add_argument("--idempotency-ttl-hours", type=int, default=24, help="TTL for Idempotency-Key (default: 24).")
    parser.add_argument("--events-retention-days", type=int, default=30, help="Retention for events (default: 30).")
    parser.add_argument("--runs-retention-days", type=int, default=180, help="Retention for runs (default: 180).")
    parser.add_argument("--sessions-retention-days", type=int, default=90, help="Retention for sessions (default: 90).")


def cmd_storage_health(args: argparse.Namespace) -> int:
    client = admin_client_from_args(args)
    print(json.dumps(client.storage_health().model_dump(exclude_none=True, by_alias=True), ensure_ascii=False))
    return 0


def cmd_storage_migrate(args: argparse.Namespace) -> int:
    try:
        result = apply_storage_migrations(
            postgres_dsn=args.postgres_dsn,
            postgres_schema=args.postgres_schema,
            dry_run=bool(args.dry_run),
        )
    except RuntimeError as exc:
        print(str(exc), file=sys.stderr)
        return 1
    print(json.dumps(result, ensure_ascii=False))
    return 0


def cmd_storage_replay(args: argparse.Namespace) -> int:
    kinds = {
        item
        for raw in (args.kind or [])
        if isinstance(raw, str)
        for item in [raw.strip()]
        if item
    }
    filters = ReplayFilters(
        session_partition_key=args.session_partition_key.strip()
        if isinstance(args.session_partition_key, str) and args.session_partition_key.strip()
        else None,
        response_id=args.response_id.strip() if isinstance(args.response_id, str) and args.response_id.strip() else None,
        kinds=kinds,
        last_seq=max(0, int(args.last_seq or 0)),
        limit=max(1, min(5000, int(args.limit or 200))),
    )
    root_dir = resolve_rollout_root_dir(root_dir=args.root_dir, workspace_dir=args.workspace_dir)
    result = replay_rollout_records(
        root_dir=root_dir,
        filters=filters,
        include_fingerprint=bool(args.include_fingerprint),
    )
    if args.format == "jsonl":
        print(json.dumps({"summary": result["summary"]}, ensure_ascii=False))
        for row in result["records"]:
            print(json.dumps(row, ensure_ascii=False))
    else:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


def cmd_storage_retention(args: argparse.Namespace) -> int:
    return run_retention_from_args(args)


def _alembic_dir() -> Path:
    return Path(__file__).resolve().parents[1] / "storage" / "alembic"


def _alembic_config() -> Any | None:
    try:
        from alembic.config import Config
    except ImportError:
        print("alembic is required: pip install anyagent[postgres]", file=sys.stderr)
        return None

    settings = active_storage_settings()
    dsn = settings.effective_postgres_dsn
    if dsn is None:
        print("DATABASE_URL or POSTGRES_DSN must be set", file=sys.stderr)
        return None
    effective_dsn = str(dsn)
    if effective_dsn.startswith("postgresql://"):
        effective_dsn = "postgresql+psycopg://" + effective_dsn[len("postgresql://") :]
    cfg = Config()
    cfg.set_main_option("script_location", str(_alembic_dir()))
    cfg.set_main_option("sqlalchemy.url", effective_dsn)
    return cfg


def cmd_db_migrate(args: argparse.Namespace) -> int:
    cfg = _alembic_config()
    if cfg is None:
        return 1
    from alembic import command as alembic_cmd

    if args.sql:
        alembic_cmd.upgrade(cfg, "head", sql=True)
    else:
        alembic_cmd.upgrade(cfg, "head")
        print("migrations applied successfully")
    return 0


def cmd_db_downgrade(args: argparse.Namespace) -> int:
    cfg = _alembic_config()
    if cfg is None:
        return 1
    from alembic import command as alembic_cmd

    alembic_cmd.downgrade(cfg, args.revision)
    print(f"downgraded to {args.revision}")
    return 0


def cmd_db_current(args: argparse.Namespace) -> int:
    _ = args
    cfg = _alembic_config()
    if cfg is None:
        return 1
    from alembic import command as alembic_cmd

    alembic_cmd.current(cfg, verbose=True)
    return 0


def cmd_db_history(args: argparse.Namespace) -> int:
    _ = args
    cfg = _alembic_config()
    if cfg is None:
        return 1
    from alembic import command as alembic_cmd

    alembic_cmd.history(cfg, verbose=True)
    return 0


def cmd_db_stamp(args: argparse.Namespace) -> int:
    cfg = _alembic_config()
    if cfg is None:
        return 1
    from alembic import command as alembic_cmd

    alembic_cmd.stamp(cfg, args.revision)
    print(f"stamped {args.revision}")
    return 0
