from __future__ import annotations

import json
from typing import Any

from psycopg.rows import dict_row
from psycopg_pool import AsyncConnectionPool

from .models import EventRecord, RunRecord


class PostgresRunStore:
    def __init__(self, *, pool: AsyncConnectionPool) -> None:
        self._pool = pool

    async def get_by_idempotency_key(self, key: str) -> RunRecord | None:
        async with self._pool.connection() as conn:
            conn.row_factory = dict_row
            async with conn.cursor() as cur:
                await cur.execute(
                    """
                    SELECT response_id, session_partition_key, idempotency_key, stream, status,
                           last_event_seq, final_response_json, error_json
                      FROM runs
                     WHERE idempotency_key = %s
                     LIMIT 1
                    """,
                    (key,),
                )
                row = await cur.fetchone()
        if not row:
            return None
        return RunRecord(
            response_id=str(row["response_id"]),
            session_partition_key=str(row["session_partition_key"]),
            idempotency_key=str(row["idempotency_key"]) if row.get("idempotency_key") is not None else None,
            stream=bool(row["stream"]),
            status=str(row["status"]),
            last_event_seq=int(row.get("last_event_seq") or 0),
            final_response_json=row.get("final_response_json"),
            error_json=row.get("error_json"),
        )

    async def get(self, response_id: str) -> RunRecord | None:
        async with self._pool.connection() as conn:
            conn.row_factory = dict_row
            async with conn.cursor() as cur:
                await cur.execute(
                    """
                    SELECT response_id, session_partition_key, idempotency_key, stream, status,
                           last_event_seq, final_response_json, error_json
                      FROM runs
                     WHERE response_id = %s
                     LIMIT 1
                    """,
                    (response_id,),
                )
                row = await cur.fetchone()
        if not row:
            return None
        return RunRecord(
            response_id=str(row["response_id"]),
            session_partition_key=str(row["session_partition_key"]),
            idempotency_key=str(row["idempotency_key"]) if row.get("idempotency_key") is not None else None,
            stream=bool(row["stream"]),
            status=str(row["status"]),
            last_event_seq=int(row.get("last_event_seq") or 0),
            final_response_json=row.get("final_response_json"),
            error_json=row.get("error_json"),
        )

    async def try_create_started(
        self,
        *,
        response_id: str,
        session_partition_key: str,
        idempotency_key: str,
        stream: bool,
    ) -> tuple[bool, RunRecord]:
        async with self._pool.connection() as conn:
            async with conn.cursor() as cur:
                await cur.execute(
                    """
                    INSERT INTO runs(response_id, session_partition_key, idempotency_key, stream, status)
                    VALUES (%s, %s, %s, %s, %s)
                    ON CONFLICT (idempotency_key) WHERE idempotency_key IS NOT NULL
                    DO NOTHING
                    """,
                    (response_id, session_partition_key, idempotency_key, bool(stream), "started"),
                )
            await conn.commit()

        # Detect insertion by reading back. (Rowcount is unreliable across drivers.)
        existing = await self.get_by_idempotency_key(idempotency_key)
        if existing is None:
            # Should not happen; but treat as created.
            return True, RunRecord(
                response_id=response_id,
                session_partition_key=session_partition_key,
                idempotency_key=idempotency_key,
                stream=stream,
                status="started",
            )
        created = existing.response_id == response_id
        return created, existing

    async def set_final(
        self,
        *,
        response_id: str,
        status: str,
        final_response_json: dict[str, Any] | None,
        error_json: dict[str, Any] | None,
    ) -> None:
        async with self._pool.connection() as conn:
            async with conn.cursor() as cur:
                await cur.execute(
                    """
                    UPDATE runs
                       SET status = %s,
                           final_response_json = %s::jsonb,
                           error_json = %s::jsonb,
                           ended_at = now(),
                           updated_at = now()
                     WHERE response_id = %s
                    """,
                    (
                        status,
                        json.dumps(final_response_json, ensure_ascii=False, separators=(",", ":")) if final_response_json is not None else None,
                        json.dumps(error_json, ensure_ascii=False, separators=(",", ":")) if error_json is not None else None,
                        response_id,
                    ),
                )
            await conn.commit()


class PostgresEventStore:
    def __init__(self, *, pool: AsyncConnectionPool) -> None:
        self._pool = pool

    async def append(self, *, response_id: str, session_partition_key: str, event: str | None, data: str) -> int:
        ev = event or "message"
        payload = {"event": event, "data": data}

        async with self._pool.connection() as conn:
            async with conn.cursor() as cur:
                await cur.execute(
                    """
                    UPDATE runs
                       SET last_event_seq = last_event_seq + 1,
                           updated_at = now()
                     WHERE response_id = %s
                     RETURNING last_event_seq
                    """,
                    (response_id,),
                )
                row = await cur.fetchone()
                if not row or not isinstance(row[0], int):
                    raise RuntimeError("run_not_found")
                seq = int(row[0])
                await cur.execute(
                    """
                    INSERT INTO events(response_id, session_partition_key, seq, event_type, payload_json)
                    VALUES (%s, %s, %s, %s, %s::jsonb)
                    """,
                    (
                        response_id,
                        session_partition_key,
                        seq,
                        ev,
                        json.dumps(payload, ensure_ascii=False, separators=(",", ":")),
                    ),
                )
            await conn.commit()

        return seq

    async def tail_seq(self, *, response_id: str) -> int:
        async with self._pool.connection() as conn:
            async with conn.cursor() as cur:
                await cur.execute("SELECT COALESCE(MAX(seq), 0) FROM events WHERE response_id = %s", (response_id,))
                row = await cur.fetchone()
        if not row:
            return 0
        v = row[0]
        return int(v) if isinstance(v, int) else 0

    async def list(self, *, response_id: str, after_seq: int, limit: int) -> list[EventRecord]:
        lim = max(1, min(1000, int(limit)))
        async with self._pool.connection() as conn:
            conn.row_factory = dict_row
            async with conn.cursor() as cur:
                await cur.execute(
                    """
                    SELECT response_id, seq, payload_json
                      FROM events
                     WHERE response_id = %s AND seq > %s
                     ORDER BY seq ASC
                     LIMIT %s
                    """,
                    (response_id, int(after_seq), lim),
                )
                rows = await cur.fetchall()

        out: list[EventRecord] = []
        for r in rows or []:
            payload = r.get("payload_json")
            if isinstance(payload, str):
                try:
                    payload = json.loads(payload)
                except Exception:  # noqa: BLE001
                    payload = {}
            if not isinstance(payload, dict):
                payload = {}
            out.append(
                EventRecord(
                    response_id=str(r.get("response_id") or response_id),
                    seq=int(r.get("seq") or 0),
                    event=payload.get("event") if isinstance(payload.get("event"), str) else None,
                    data=str(payload.get("data") or ""),
                )
            )
        return out
