from __future__ import annotations

import asyncio
from collections.abc import Set as AbstractSet
from datetime import datetime, timezone
from time import monotonic, time
from typing import Any

from anyagent.storage.models import EventRecord, LeaseLockHandle, RunRecord, SessionRecord
from sqlalchemy import delete, func, insert, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncEngine

from .schema import StorageTables, build_storage_tables


def _ts_s(dt: object) -> float | None:
    ts = getattr(dt, "timestamp", None)
    if callable(ts):
        try:
            return float(ts())
        except Exception:  # noqa: BLE001
            return None
    return None


class SqlAlchemyBackendBase:
    def __init__(self, *, engine: AsyncEngine, schema_name: str | None = None, dialect: str = "postgresql") -> None:
        self._engine = engine
        self._dialect = dialect
        self._tables: StorageTables = build_storage_tables(schema_name=schema_name, dialect=dialect)


class SqlAlchemyRunStore(SqlAlchemyBackendBase):
    @staticmethod
    def _row_to_run(row: dict[str, Any]) -> RunRecord:
        created_at_s = _ts_s(row.get("created_at"))
        kwargs: dict[str, Any] = {
            "response_id": str(row["response_id"]),
            "session_partition_key": str(row["session_partition_key"]),
            "idempotency_key": str(row["idempotency_key"]) if row.get("idempotency_key") is not None else None,
            "stream": bool(row["stream"]),
            "status": str(row["status"]),
            "last_event_seq": int(row.get("last_event_seq") or 0),
            "final_response_json": row.get("final_response_json"),
            "error_json": row.get("error_json"),
        }
        if created_at_s is not None:
            kwargs["created_at_s"] = created_at_s
        return RunRecord(**kwargs)

    async def get_by_idempotency_key(self, key: str) -> RunRecord | None:
        stmt = select(self._tables.runs).where(self._tables.runs.c.idempotency_key == key).limit(1)
        async with self._engine.connect() as conn:
            row = (await conn.execute(stmt)).mappings().first()
        return None if row is None else self._row_to_run(dict(row))

    async def get(self, response_id: str) -> RunRecord | None:
        stmt = select(self._tables.runs).where(self._tables.runs.c.response_id == response_id).limit(1)
        async with self._engine.connect() as conn:
            row = (await conn.execute(stmt)).mappings().first()
        return None if row is None else self._row_to_run(dict(row))

    async def list(
        self,
        *,
        agent_id: str | None = None,
        session_key: str | None = None,
        response_id: str | None = None,
        limit: int = 100,
    ) -> list[RunRecord]:
        stmt = select(self._tables.runs).order_by(self._tables.runs.c.updated_at.desc())
        if response_id:
            stmt = stmt.where(self._tables.runs.c.response_id == response_id)
        if session_key:
            stmt = stmt.where(self._tables.runs.c.session_partition_key.like(f"%::{session_key}"))
        if agent_id:
            stmt = stmt.where(self._tables.runs.c.session_partition_key.like(f"{agent_id}::%"))
        stmt = stmt.limit(max(0, min(1000, int(limit))))
        async with self._engine.connect() as conn:
            rows = (await conn.execute(stmt)).mappings().all()
        return [self._row_to_run(dict(row)) for row in rows]

    async def try_create_started(
        self,
        *,
        response_id: str,
        session_partition_key: str,
        idempotency_key: str,
        stream: bool,
    ) -> tuple[bool, RunRecord]:
        stmt = insert(self._tables.runs).values(
            response_id=response_id,
            session_partition_key=session_partition_key,
            idempotency_key=idempotency_key,
            stream=bool(stream),
            status="started",
            last_event_seq=0,
        )
        async with self._engine.begin() as conn:
            try:
                await conn.execute(stmt)
            except IntegrityError:
                pass
        existing = await self.get_by_idempotency_key(idempotency_key)
        if existing is None:
            return True, RunRecord(
                response_id=response_id,
                session_partition_key=session_partition_key,
                idempotency_key=idempotency_key,
                stream=stream,
                status="started",
            )
        return existing.response_id == response_id, existing

    async def create_started(
        self,
        *,
        response_id: str,
        session_partition_key: str,
        stream: bool,
        idempotency_key: str | None,
    ) -> RunRecord:
        stmt = insert(self._tables.runs).values(
            response_id=response_id,
            session_partition_key=session_partition_key,
            idempotency_key=idempotency_key,
            stream=bool(stream),
            status="started",
            last_event_seq=0,
        )
        async with self._engine.begin() as conn:
            try:
                await conn.execute(stmt)
            except IntegrityError:
                await conn.execute(
                    update(self._tables.runs)
                    .where(self._tables.runs.c.response_id == response_id)
                    .values(updated_at=func.now())
                )
        existing = await self.get(response_id)
        if existing is None:
            raise RuntimeError("failed to create started run record")
        return existing

    async def mark_cancel_requested(self, response_id: str) -> None:
        stmt = (
            update(self._tables.runs)
            .where(self._tables.runs.c.response_id == response_id)
            .where(self._tables.runs.c.ended_at.is_(None))
            .values(
                status="aborted",
                updated_at=func.now(),
            )
        )
        async with self._engine.begin() as conn:
            await conn.execute(stmt)

    async def set_final(
        self,
        *,
        response_id: str,
        status: str,
        final_response_json: dict[str, Any] | None,
        error_json: dict[str, Any] | None,
    ) -> None:
        stmt = (
            update(self._tables.runs)
            .where(self._tables.runs.c.response_id == response_id)
            .values(
                status=status,
                final_response_json=final_response_json,
                error_json=error_json,
                ended_at=func.now(),
                updated_at=func.now(),
            )
        )
        async with self._engine.begin() as conn:
            await conn.execute(stmt)

    async def try_set_final_from_status(
        self,
        *,
        response_id: str,
        current_status: str,
        next_status: str,
        final_response_json: dict[str, Any] | None,
        error_json: dict[str, Any] | None,
    ) -> tuple[bool, RunRecord | None]:
        stmt = (
            update(self._tables.runs)
            .where(self._tables.runs.c.response_id == response_id)
            .where(self._tables.runs.c.status == current_status)
            .values(
                status=next_status,
                final_response_json=final_response_json,
                error_json=error_json,
                ended_at=func.now(),
                updated_at=func.now(),
            )
        )
        async with self._engine.begin() as conn:
            result = await conn.execute(stmt)
        latest = await self.get(response_id)
        return bool(result.rowcount), latest

    async def set_final_with_session_snapshot(
        self,
        *,
        response_id: str,
        status: str,
        final_response_json: dict[str, Any] | None,
        error_json: dict[str, Any] | None,
        session_partition_key: str,
        agent_id: str,
        session_key: str,
        snapshot_json: dict[str, Any],
        expected_snapshot_version: int,
    ) -> tuple[bool, SessionRecord | None]:
        async with self._engine.begin() as conn:
            await conn.execute(
                update(self._tables.runs)
                .where(self._tables.runs.c.response_id == response_id)
                .values(
                    status=status,
                    final_response_json=final_response_json,
                    error_json=error_json,
                    ended_at=func.now(),
                    updated_at=func.now(),
                )
            )

            result = await conn.execute(
                update(self._tables.sessions)
                .where(self._tables.sessions.c.session_partition_key == session_partition_key)
                .where(self._tables.sessions.c.snapshot_version == int(expected_snapshot_version))
                .values(
                    snapshot_json=snapshot_json,
                    snapshot_version=self._tables.sessions.c.snapshot_version + 1,
                    updated_at=func.now(),
                )
            )
            if result.rowcount:
                row = (
                    await conn.execute(
                        select(self._tables.sessions).where(self._tables.sessions.c.session_partition_key == session_partition_key).limit(1)
                    )
                ).mappings().first()
                return True, None if row is None else _row_to_session(dict(row))

            if int(expected_snapshot_version) == 0:
                try:
                    await conn.execute(
                        insert(self._tables.sessions).values(
                            session_partition_key=session_partition_key,
                            agent_id=agent_id,
                            session_key=session_key,
                            snapshot_json=snapshot_json,
                            snapshot_version=0,
                        )
                    )
                    row = (
                        await conn.execute(
                            select(self._tables.sessions).where(self._tables.sessions.c.session_partition_key == session_partition_key).limit(1)
                        )
                    ).mappings().first()
                    return True, None if row is None else _row_to_session(dict(row))
                except IntegrityError:
                    pass

        current = await SqlAlchemySessionStore(
            engine=self._engine,
            schema_name=self._tables.sessions.schema,
            dialect=self._dialect,
        ).get(
            session_partition_key=session_partition_key
        )
        return False, current


class SqlAlchemySessionStore(SqlAlchemyBackendBase):
    async def get(self, *, session_partition_key: str) -> SessionRecord | None:
        stmt = select(self._tables.sessions).where(self._tables.sessions.c.session_partition_key == session_partition_key).limit(1)
        async with self._engine.connect() as conn:
            row = (await conn.execute(stmt)).mappings().first()
        return None if row is None else _row_to_session(dict(row))

    async def create_if_absent(
        self,
        *,
        session_partition_key: str,
        agent_id: str,
        session_key: str,
        snapshot_json: dict[str, Any],
    ) -> SessionRecord:
        stmt = insert(self._tables.sessions).values(
            session_partition_key=session_partition_key,
            agent_id=agent_id,
            session_key=session_key,
            snapshot_json=snapshot_json,
            snapshot_version=0,
        )
        async with self._engine.begin() as conn:
            try:
                await conn.execute(stmt)
            except IntegrityError:
                pass
        current = await self.get(session_partition_key=session_partition_key)
        if current is not None:
            return current
        return SessionRecord(
            session_partition_key=session_partition_key,
            agent_id=agent_id,
            session_key=session_key,
            snapshot_json=snapshot_json,
            snapshot_version=0,
        )

    async def update_snapshot_cas(
        self,
        *,
        session_partition_key: str,
        expected_snapshot_version: int,
        snapshot_json: dict[str, Any],
        agent_id: str,
        session_key: str,
    ) -> tuple[bool, SessionRecord | None]:
        stmt = (
            update(self._tables.sessions)
            .where(self._tables.sessions.c.session_partition_key == session_partition_key)
            .where(self._tables.sessions.c.snapshot_version == int(expected_snapshot_version))
            .values(
                snapshot_json=snapshot_json,
                snapshot_version=self._tables.sessions.c.snapshot_version + 1,
                updated_at=func.now(),
            )
        )
        async with self._engine.begin() as conn:
            result = await conn.execute(stmt)
        current = await self.get(session_partition_key=session_partition_key)
        return bool(result.rowcount), current


class SqlAlchemyEventStore(SqlAlchemyBackendBase):
    async def append(self, *, response_id: str, session_partition_key: str, event: str | None, data: str) -> int:
        async with self._engine.begin() as conn:
            row = (
                await conn.execute(
                    select(self._tables.runs.c.last_event_seq)
                    .where(self._tables.runs.c.response_id == response_id)
                    .with_for_update()
                )
            ).first()
            if not row:
                # Auto-create run record for platform/connector events that
                # don't go through the normal response lifecycle.
                try:
                    await conn.execute(
                        insert(self._tables.runs).values(
                            response_id=response_id,
                            session_partition_key=session_partition_key,
                            stream=False,
                            status="completed",
                            last_event_seq=0,
                        )
                    )
                except IntegrityError:
                    pass
                row = (
                    await conn.execute(
                        select(self._tables.runs.c.last_event_seq)
                        .where(self._tables.runs.c.response_id == response_id)
                        .with_for_update()
                    )
                ).first()
                if not row:
                    raise RuntimeError("run_not_found")
            seq = int(row[0] or 0) + 1
            await conn.execute(
                update(self._tables.runs)
                .where(self._tables.runs.c.response_id == response_id)
                .values(last_event_seq=seq, updated_at=func.now())
            )
            await conn.execute(
                insert(self._tables.events).values(
                    response_id=response_id,
                    session_partition_key=session_partition_key,
                    seq=seq,
                    event_type=event or "message",
                    payload_json={"event": event, "data": data},
                )
            )
        return seq

    async def tail_seq(self, *, response_id: str) -> int:
        stmt = select(func.coalesce(func.max(self._tables.events.c.seq), 0)).where(self._tables.events.c.response_id == response_id)
        async with self._engine.connect() as conn:
            row = (await conn.execute(stmt)).first()
        return int(row[0]) if row and row[0] is not None else 0

    async def list(self, *, response_id: str, after_seq: int, limit: int) -> list[EventRecord]:
        stmt = (
            select(self._tables.events)
            .where(self._tables.events.c.response_id == response_id)
            .where(self._tables.events.c.seq > int(after_seq))
            .order_by(self._tables.events.c.seq.asc())
            .limit(max(1, min(1000, int(limit))))
        )
        async with self._engine.connect() as conn:
            rows = (await conn.execute(stmt)).mappings().all()
        out: list[EventRecord] = []
        for row in rows:
            payload = row.get("payload_json")
            if not isinstance(payload, dict):
                payload = {}
            out.append(
                EventRecord(
                    response_id=str(row.get("response_id") or response_id),
                    seq=int(row.get("seq") or 0),
                    event=payload.get("event") if isinstance(payload.get("event"), str) else None,
                    data=str(payload.get("data") or ""),
                )
            )
        return out

    async def prune_replay_events(self, *, before_ms: int, event_types: AbstractSet[str]) -> int:
        if not event_types:
            return 0
        cutoff = datetime.fromtimestamp(max(before_ms, 0) / 1000, tz=timezone.utc)
        stmt = delete(self._tables.events).where(
            self._tables.events.c.event_type.in_(tuple(sorted(event_types))),
            self._tables.events.c.created_at < cutoff,
        )
        async with self._engine.begin() as conn:
            result = await conn.execute(stmt)
        return int(result.rowcount or 0)


class SqlAlchemyLeaseLock(SqlAlchemyBackendBase):
    async def acquire(self, *, key: str, owner: str, ttl_ms: int, wait_timeout_ms: int) -> LeaseLockHandle | None:
        deadline = monotonic() + (max(0, int(wait_timeout_ms)) / 1000.0)
        ttl_ms = max(1, int(ttl_ms))
        while True:
            now_ms = _now_ms()
            expires_at_ms = now_ms + ttl_ms
            if await self._try_acquire_once(key=key, owner=owner, now_ms=now_ms, expires_at_ms=expires_at_ms):
                return LeaseLockHandle(key=key, owner=owner)
            if monotonic() >= deadline:
                return None
            await asyncio.sleep(0.05)

    async def renew(self, *, key: str, owner: str, ttl_ms: int) -> bool:
        now_ms = _now_ms()
        stmt = (
            update(self._tables.leases)
            .where(self._tables.leases.c.lock_key == key)
            .where(self._tables.leases.c.owner == owner)
            .where(self._tables.leases.c.expires_at_ms > now_ms)
            .values(expires_at_ms=now_ms + max(1, int(ttl_ms)), updated_at=func.now())
        )
        async with self._engine.begin() as conn:
            result = await conn.execute(stmt)
        return bool(result.rowcount)

    async def release(self, *, key: str, owner: str) -> bool:
        stmt = delete(self._tables.leases).where(
            self._tables.leases.c.lock_key == key,
            self._tables.leases.c.owner == owner,
        )
        async with self._engine.begin() as conn:
            result = await conn.execute(stmt)
        return bool(result.rowcount)

    async def _try_acquire_once(self, *, key: str, owner: str, now_ms: int, expires_at_ms: int) -> bool:
        try:
            async with self._engine.begin() as conn:
                await conn.execute(
                    insert(self._tables.leases).values(
                        lock_key=key,
                        owner=owner,
                        expires_at_ms=expires_at_ms,
                    )
                )
            return True
        except IntegrityError:
            pass

        async with self._engine.begin() as conn:
            result = await conn.execute(
                update(self._tables.leases)
                .where(self._tables.leases.c.lock_key == key)
                .where(self._tables.leases.c.expires_at_ms <= now_ms)
                .values(owner=owner, expires_at_ms=expires_at_ms, updated_at=func.now())
            )
            return bool(result.rowcount)


def _row_to_session(row: dict[str, Any]) -> SessionRecord:
    return SessionRecord(
        session_partition_key=str(row["session_partition_key"]),
        agent_id=str(row["agent_id"]),
        session_key=str(row["session_key"]),
        snapshot_json=row.get("snapshot_json") if isinstance(row.get("snapshot_json"), dict) else {},
        snapshot_version=int(row.get("snapshot_version") or 0),
    )


def _now_ms() -> int:
    return int(time() * 1000)
