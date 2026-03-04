from __future__ import annotations

import asyncio
import json
import logging
from dataclasses import dataclass
from time import monotonic
from typing import Any

from .models import EventRecord, RunRecord, SessionRecord
from .rollout import RolloutFileWriter


logger = logging.getLogger("anyagent.agent_api.storage.inmemory")


def _json_clone(value: Any) -> Any:
    """Return a JSON-safe deep copy."""
    return json.loads(json.dumps(value, ensure_ascii=False))


@dataclass(frozen=True)
class LeaseLockHandle:
    key: str
    owner: str


class InMemoryLeaseLock:
    def __init__(self) -> None:
        self._lock = asyncio.Lock()
        self._leases: dict[str, tuple[str, float]] = {}

    async def acquire(self, *, key: str, owner: str, ttl_ms: int, wait_timeout_ms: int) -> LeaseLockHandle | None:
        deadline = monotonic() + (wait_timeout_ms / 1000.0)
        ttl_s = ttl_ms / 1000.0
        while True:
            async with self._lock:
                cur = self._leases.get(key)
                now = monotonic()
                if cur is None or cur[1] <= now:
                    self._leases[key] = (owner, now + ttl_s)
                    return LeaseLockHandle(key=key, owner=owner)
            if monotonic() >= deadline:
                return None
            await asyncio.sleep(0.05)

    async def renew(self, *, key: str, owner: str, ttl_ms: int) -> bool:
        ttl_s = ttl_ms / 1000.0
        async with self._lock:
            cur = self._leases.get(key)
            now = monotonic()
            if cur is None or cur[0] != owner or cur[1] <= now:
                return False
            self._leases[key] = (owner, now + ttl_s)
            return True

    async def release(self, *, key: str, owner: str) -> bool:
        async with self._lock:
            cur = self._leases.get(key)
            if cur is None or cur[0] != owner:
                return False
            self._leases.pop(key, None)
            return True


class InMemoryRunStore:
    def __init__(self, *, rollout_writer: RolloutFileWriter | None = None) -> None:
        self._lock = asyncio.Lock()
        self._by_response_id: dict[str, RunRecord] = {}
        self._by_idem: dict[str, str] = {}
        self._rollout_writer = rollout_writer

    async def get_by_idempotency_key(self, key: str) -> RunRecord | None:
        async with self._lock:
            rid = self._by_idem.get(key)
            if rid is None:
                return None
            return self._by_response_id.get(rid)

    async def get(self, response_id: str) -> RunRecord | None:
        async with self._lock:
            return self._by_response_id.get(response_id)

    async def try_create_started(
        self,
        *,
        response_id: str,
        session_partition_key: str,
        idempotency_key: str,
        stream: bool,
    ) -> tuple[bool, RunRecord]:
        persist: tuple[str, str, str | None, bool] | None = None
        async with self._lock:
            existing_rid = self._by_idem.get(idempotency_key)
            if existing_rid is not None and existing_rid in self._by_response_id:
                return False, self._by_response_id[existing_rid]

            rec = RunRecord(
                response_id=response_id,
                session_partition_key=session_partition_key,
                idempotency_key=idempotency_key,
                stream=stream,
                status="started",
                last_event_seq=0,
                final_response_json=None,
                error_json=None,
            )
            self._by_idem[idempotency_key] = response_id
            self._by_response_id[response_id] = rec
            persist = (session_partition_key, response_id, idempotency_key, bool(stream))

        if persist is not None and self._rollout_writer is not None:
            try:
                await self._rollout_writer.append_run_started(
                    session_partition_key=persist[0],
                    response_id=persist[1],
                    idempotency_key=persist[2],
                    stream=persist[3],
                )
            except Exception as e:  # noqa: BLE001
                logger.warning("rollout append_run_started failed: %s", e)
        return True, rec

    async def set_final(
        self,
        *,
        response_id: str,
        status: str,
        final_response_json: dict[str, Any] | None,
        error_json: dict[str, Any] | None,
    ) -> None:
        persist: tuple[str, str, str, dict[str, Any] | None, dict[str, Any] | None] | None = None
        async with self._lock:
            rec = self._by_response_id.get(response_id)
            if rec is None:
                return
            rec.status = status  # type: ignore[assignment]
            rec.final_response_json = _json_clone(final_response_json) if final_response_json is not None else None
            rec.error_json = _json_clone(error_json) if error_json is not None else None
            persist = (
                rec.session_partition_key,
                response_id,
                status,
                rec.final_response_json,
                rec.error_json,
            )

        if persist is not None and self._rollout_writer is not None:
            try:
                await self._rollout_writer.append_run_final(
                    session_partition_key=persist[0],
                    response_id=persist[1],
                    status=persist[2],
                    final_response_json=persist[3],
                    error_json=persist[4],
                )
            except Exception as e:  # noqa: BLE001
                logger.warning("rollout append_run_final failed: %s", e)

    async def set_last_event_seq(self, *, response_id: str, last_event_seq: int) -> None:
        async with self._lock:
            rec = self._by_response_id.get(response_id)
            if rec is None:
                return
            rec.last_event_seq = last_event_seq


class InMemorySessionStore:
    def __init__(self, *, rollout_writer: RolloutFileWriter | None = None) -> None:
        self._lock = asyncio.Lock()
        self._by_partition_key: dict[str, SessionRecord] = {}
        self._rollout_writer = rollout_writer

    async def _get_loaded(self, *, session_partition_key: str) -> SessionRecord | None:
        rec = self._by_partition_key.get(session_partition_key)
        if rec is not None:
            return rec
        if self._rollout_writer is None:
            return None
        try:
            loaded = await self._rollout_writer.load_session_snapshot(session_partition_key=session_partition_key)
        except Exception as e:  # noqa: BLE001
            logger.warning("rollout load_session_snapshot failed: %s", e)
            return None
        if loaded is None:
            return None
        self._by_partition_key[session_partition_key] = loaded
        return loaded

    async def get(self, *, session_partition_key: str) -> SessionRecord | None:
        async with self._lock:
            rec = await self._get_loaded(session_partition_key=session_partition_key)
            if rec is None:
                return None
            return SessionRecord.model_validate(rec.model_dump())

    async def create_if_absent(
        self,
        *,
        session_partition_key: str,
        agent_id: str,
        session_key: str,
        snapshot_json: dict[str, Any],
    ) -> SessionRecord:
        async with self._lock:
            rec = await self._get_loaded(session_partition_key=session_partition_key)
            if rec is not None:
                return SessionRecord.model_validate(rec.model_dump())

            candidate = SessionRecord(
                session_partition_key=session_partition_key,
                agent_id=agent_id,
                session_key=session_key,
                snapshot_json=_json_clone(snapshot_json),
                snapshot_version=0,
            )
            if self._rollout_writer is None:
                self._by_partition_key[session_partition_key] = candidate
                return SessionRecord.model_validate(candidate.model_dump())

            try:
                ok, latest = await self._rollout_writer.append_session_snapshot_upserted(
                    session_partition_key=session_partition_key,
                    agent_id=agent_id,
                    session_key=session_key,
                    snapshot_json=candidate.snapshot_json,
                    expected_snapshot_version=0,
                )
            except Exception as e:  # noqa: BLE001
                logger.warning("rollout append_session_snapshot_upserted failed: %s", e)
                ok = False
                latest = None

            if ok and latest is not None:
                self._by_partition_key[session_partition_key] = latest
                return SessionRecord.model_validate(latest.model_dump())

            # Rollout persistence failed; keep in-memory snapshot to avoid blocking request path.
            self._by_partition_key[session_partition_key] = candidate
            return SessionRecord.model_validate(candidate.model_dump())

    async def update_snapshot_cas(
        self,
        *,
        session_partition_key: str,
        expected_snapshot_version: int,
        snapshot_json: dict[str, Any],
        agent_id: str,
        session_key: str,
    ) -> tuple[bool, SessionRecord | None]:
        async with self._lock:
            current = await self._get_loaded(session_partition_key=session_partition_key)
            if current is None:
                return False, None
            if int(current.snapshot_version) != int(expected_snapshot_version):
                return False, SessionRecord.model_validate(current.model_dump())

            if self._rollout_writer is not None:
                try:
                    ok, latest = await self._rollout_writer.append_session_snapshot_upserted(
                        session_partition_key=session_partition_key,
                        agent_id=agent_id,
                        session_key=session_key,
                        snapshot_json=_json_clone(snapshot_json),
                        expected_snapshot_version=int(expected_snapshot_version),
                    )
                except Exception as e:  # noqa: BLE001
                    logger.warning("rollout append_session_snapshot_upserted failed: %s", e)
                    ok = False
                    latest = None
                if ok and latest is not None:
                    self._by_partition_key[session_partition_key] = latest
                    return True, SessionRecord.model_validate(latest.model_dump())
                if latest is not None:
                    self._by_partition_key[session_partition_key] = latest
                    return False, SessionRecord.model_validate(latest.model_dump())

            # Fallback for in-memory-only mode.
            updated = SessionRecord(
                session_partition_key=session_partition_key,
                agent_id=agent_id,
                session_key=session_key,
                snapshot_json=_json_clone(snapshot_json),
                snapshot_version=int(expected_snapshot_version) + 1,
            )
            self._by_partition_key[session_partition_key] = updated
            return True, SessionRecord.model_validate(updated.model_dump())


class InMemoryEventStore:
    def __init__(self, *, rollout_writer: RolloutFileWriter | None = None) -> None:
        self._lock = asyncio.Lock()
        self._events: dict[str, list[EventRecord]] = {}
        self._notifiers: dict[str, asyncio.Condition] = {}
        self._rollout_writer = rollout_writer

    async def append(
        self,
        *,
        response_id: str,
        session_partition_key: str,
        event: str | None,
        data: str,
    ) -> int:
        persisted: tuple[str, str, int, str | None, str] | None = None
        async with self._lock:
            seq = len(self._events.get(response_id, [])) + 1
            rec = EventRecord(response_id=response_id, seq=seq, event=event, data=data)
            self._events.setdefault(response_id, []).append(rec)
            cond = self._notifiers.get(response_id)
            persisted = (session_partition_key, response_id, seq, event, data)

        if persisted is not None and self._rollout_writer is not None:
            try:
                await self._rollout_writer.append_event_appended(
                    session_partition_key=persisted[0],
                    response_id=persisted[1],
                    seq=persisted[2],
                    event=persisted[3],
                    data=persisted[4],
                )
            except Exception as e:  # noqa: BLE001
                logger.warning("rollout append_event_appended failed: %s", e)

        if cond is not None:
            async with cond:
                cond.notify_all()
        return seq

    async def tail_seq(self, *, response_id: str) -> int:
        async with self._lock:
            return len(self._events.get(response_id, []))

    async def list(self, *, response_id: str, after_seq: int, limit: int) -> list[EventRecord]:
        async with self._lock:
            evs = self._events.get(response_id, [])
            start = max(0, after_seq)
            # seq starts from 1; list index is 0
            out = evs[start : start + max(1, limit)]
            return [EventRecord.model_validate(e.model_dump()) for e in out]

    async def wait_new(self, *, response_id: str, after_seq: int, timeout_s: float) -> None:
        async with self._lock:
            cur_len = len(self._events.get(response_id, []))
            if cur_len > after_seq:
                return
            cond = self._notifiers.get(response_id)
            if cond is None:
                cond = asyncio.Condition()
                self._notifiers[response_id] = cond
        async with cond:
            try:
                await asyncio.wait_for(cond.wait(), timeout=timeout_s)
            except TimeoutError:
                return
