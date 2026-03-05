from __future__ import annotations

import argparse
import sys
import time
from dataclasses import dataclass


@dataclass(frozen=True)
class RetentionPolicy:
    idempotency_ttl_hours: int
    events_retention_days: int
    runs_retention_days: int
    sessions_retention_days: int


def _parse_args(argv: list[str]) -> argparse.Namespace:
    p = argparse.ArgumentParser(description="anyagent Agent API storage retention/TTL maintenance (Postgres).")
    p.add_argument("--apply", action="store_true", help="Apply changes (default: plan-only, no writes).")
    p.add_argument("--dsn", default=None, help="Postgres DSN (default: env POSTGRES_DSN).")
    p.add_argument("--schema", default=None, help='Postgres schema/search_path (default: env POSTGRES_SCHEMA or "public").')
    p.add_argument("--batch-size", type=int, default=500, help="Max rows per batch (default: 500).")
    p.add_argument("--max-batches", type=int, default=200, help="Max batches per action (default: 200).")

    p.add_argument("--idempotency-ttl-hours", type=int, default=24, help="TTL for Idempotency-Key (default: 24).")
    p.add_argument("--events-retention-days", type=int, default=30, help="Retention for events (default: 30).")
    p.add_argument("--runs-retention-days", type=int, default=180, help="Retention for runs (default: 180).")
    p.add_argument("--sessions-retention-days", type=int, default=90, help="Retention for sessions (default: 90).")
    return p.parse_args(argv)


def _require_positive(name: str, value: int) -> int:
    if not isinstance(value, int) or value <= 0:
        raise ValueError(f"{name} must be a positive int")
    return value


def _clamp_batch_size(v: int) -> int:
    if not isinstance(v, int):
        return 500
    return max(1, min(50_000, v))


def _clamp_max_batches(v: int) -> int:
    if not isinstance(v, int):
        return 200
    return max(1, min(10_000, v))


def _connect(*, dsn: str, schema: str):
    import psycopg  # type: ignore[import-not-found]

    conn = psycopg.connect(dsn, autocommit=False)
    with conn.cursor() as cur:
        cur.execute(f'CREATE SCHEMA IF NOT EXISTS "{schema}"')
        cur.execute(f'SET search_path TO "{schema}"')
    conn.commit()
    return conn


def _plan_count_next_batch(cur, *, sql: str, params: tuple[object, ...]) -> int:
    cur.execute(sql, params)
    row = cur.fetchone()
    if not row:
        return 0
    v = row[0]
    return int(v) if isinstance(v, int) else 0


def _apply_batch(cur, *, sql: str, params: tuple[object, ...]) -> int:
    cur.execute(sql, params)
    rc = int(cur.rowcount or 0)
    return max(0, rc)


def _run_plan(*, conn, policy: RetentionPolicy, batch_size: int) -> int:
    with conn.cursor() as cur:
        # 1) Idempotency TTL (release uniqueness constraint after retry window).
        would_clear_idem = _plan_count_next_batch(
            cur,
            sql="""
            SELECT count(*) FROM (
              SELECT 1
                FROM runs
               WHERE idempotency_key IS NOT NULL
                 AND ended_at IS NOT NULL
                 AND ended_at < now() - make_interval(hours => %s)
               ORDER BY ended_at ASC
               LIMIT %s
            ) t
            """,
            params=(policy.idempotency_ttl_hours, batch_size),
        )

        # 2) Events retention (by run ended_at).
        would_delete_events = _plan_count_next_batch(
            cur,
            sql="""
            SELECT count(*) FROM (
              SELECT 1
                FROM events e
                JOIN runs r ON r.response_id = e.response_id
               WHERE r.ended_at IS NOT NULL
                 AND r.ended_at < now() - make_interval(days => %s)
               ORDER BY r.ended_at ASC, e.seq ASC
               LIMIT %s
            ) t
            """,
            params=(policy.events_retention_days, batch_size),
        )

        # 3) Runs retention (terminal only).
        would_delete_runs = _plan_count_next_batch(
            cur,
            sql="""
            SELECT count(*) FROM (
              SELECT 1
                FROM runs
               WHERE ended_at IS NOT NULL
                 AND ended_at < now() - make_interval(days => %s)
               ORDER BY ended_at ASC
               LIMIT %s
            ) t
            """,
            params=(policy.runs_retention_days, batch_size),
        )

        # 4) Sessions retention.
        would_delete_sessions = _plan_count_next_batch(
            cur,
            sql="""
            SELECT count(*) FROM (
              SELECT 1
                FROM sessions
               WHERE updated_at < now() - make_interval(days => %s)
               ORDER BY updated_at ASC
               LIMIT %s
            ) t
            """,
            params=(policy.sessions_retention_days, batch_size),
        )

    print("PLAN (no writes): next-batch impact")
    print(f"- would_clear_idempotency_keys: {would_clear_idem}")
    print(f"- would_delete_events: {would_delete_events}")
    print(f"- would_delete_runs: {would_delete_runs}")
    print(f"- would_delete_sessions: {would_delete_sessions}")
    return 0


def _run_apply(*, conn, policy: RetentionPolicy, batch_size: int, max_batches: int) -> int:
    total_clear_idem = 0
    total_del_events = 0
    total_del_runs = 0
    total_del_sessions = 0

    started = time.time()

    def _log_progress() -> None:
        elapsed = int(time.time() - started)
        print(
            "progress",
            {
                "elapsed_s": elapsed,
                "cleared_idempotency_keys": total_clear_idem,
                "deleted_events": total_del_events,
                "deleted_runs": total_del_runs,
                "deleted_sessions": total_del_sessions,
            },
        )

    with conn.cursor() as cur:
        # 1) Clear expired Idempotency-Key values.
        for _ in range(max_batches):
            n = _apply_batch(
                cur,
                sql="""
                WITH doomed AS (
                  SELECT response_id
                    FROM runs
                   WHERE idempotency_key IS NOT NULL
                     AND ended_at IS NOT NULL
                     AND ended_at < now() - make_interval(hours => %s)
                   ORDER BY ended_at ASC
                   LIMIT %s
                )
                UPDATE runs r
                   SET idempotency_key = NULL,
                       updated_at = now()
                  FROM doomed d
                 WHERE r.response_id = d.response_id
                """,
                params=(policy.idempotency_ttl_hours, batch_size),
            )
            if n <= 0:
                break
            total_clear_idem += n
            conn.commit()
        _log_progress()

        # 2) Delete old events for terminal runs.
        for _ in range(max_batches):
            n = _apply_batch(
                cur,
                sql="""
                WITH doomed_events AS (
                  SELECT e.response_id, e.seq
                    FROM events e
                    JOIN runs r ON r.response_id = e.response_id
                   WHERE r.ended_at IS NOT NULL
                     AND r.ended_at < now() - make_interval(days => %s)
                   ORDER BY r.ended_at ASC, e.seq ASC
                   LIMIT %s
                )
                DELETE FROM events e
                 USING doomed_events d
                 WHERE e.response_id = d.response_id AND e.seq = d.seq
                """,
                params=(policy.events_retention_days, batch_size),
            )
            if n <= 0:
                break
            total_del_events += n
            conn.commit()
        _log_progress()

        # 3) Delete old runs (and any remaining events).
        for _ in range(max_batches):
            cur.execute(
                """
                WITH doomed AS (
                  SELECT response_id
                    FROM runs
                   WHERE ended_at IS NOT NULL
                     AND ended_at < now() - make_interval(days => %s)
                   ORDER BY ended_at ASC
                   LIMIT %s
                )
                SELECT response_id FROM doomed
                """,
                (policy.runs_retention_days, batch_size),
            )
            doomed_ids = [row[0] for row in cur.fetchall() if isinstance(row[0], str) and row[0]]
            if not doomed_ids:
                break

            cur.execute("DELETE FROM events WHERE response_id = ANY(%s)", (doomed_ids,))
            total_del_events += int(cur.rowcount or 0)
            cur.execute("DELETE FROM runs WHERE response_id = ANY(%s)", (doomed_ids,))
            n = int(cur.rowcount or 0)
            total_del_runs += n
            conn.commit()
        _log_progress()

        # 4) Delete old sessions.
        for _ in range(max_batches):
            n = _apply_batch(
                cur,
                sql="""
                WITH doomed AS (
                  SELECT session_partition_key
                    FROM sessions
                   WHERE updated_at < now() - make_interval(days => %s)
                   ORDER BY updated_at ASC
                   LIMIT %s
                )
                DELETE FROM sessions s
                 USING doomed d
                 WHERE s.session_partition_key = d.session_partition_key
                """,
                params=(policy.sessions_retention_days, batch_size),
            )
            if n <= 0:
                break
            total_del_sessions += n
            conn.commit()
        _log_progress()

    print("DONE")
    return 0


def main(argv: list[str] | None = None) -> int:
    ns = _parse_args(sys.argv[1:] if argv is None else argv)

    try:
        batch_size = _clamp_batch_size(int(ns.batch_size))
        max_batches = _clamp_max_batches(int(ns.max_batches))
        policy = RetentionPolicy(
            idempotency_ttl_hours=_require_positive("idempotency_ttl_hours", int(ns.idempotency_ttl_hours)),
            events_retention_days=_require_positive("events_retention_days", int(ns.events_retention_days)),
            runs_retention_days=_require_positive("runs_retention_days", int(ns.runs_retention_days)),
            sessions_retention_days=_require_positive("sessions_retention_days", int(ns.sessions_retention_days)),
        )
    except Exception as e:  # noqa: BLE001
        print(f"invalid arguments: {e}", file=sys.stderr)
        return 2

    # Avoid depending on agent-api Settings (it requires API keys); use the shared StorageSettings instead.
    from anyagent.storage.settings import StorageSettings

    storage_settings = StorageSettings()
    dsn = str(ns.dsn or storage_settings.postgres_dsn or "")
    schema = str(ns.schema or storage_settings.postgres_schema or "public")
    if not dsn.strip():
        print("POSTGRES_DSN is required", file=sys.stderr)
        return 2

    conn = _connect(dsn=dsn, schema=schema)
    try:
        if not ns.apply:
            return _run_plan(conn=conn, policy=policy, batch_size=batch_size)
        return _run_apply(conn=conn, policy=policy, batch_size=batch_size, max_batches=max_batches)
    finally:
        try:
            conn.close()
        except Exception:  # noqa: BLE001
            pass


if __name__ == "__main__":
    raise SystemExit(main())
