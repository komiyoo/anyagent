from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass
from time import monotonic
from typing import Any

from .models import EventRecord, RunRecord


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
    def __init__(self) -> None:
        self._lock = asyncio.Lock()
        self._by_response_id: dict[str, RunRecord] = {}
        self._by_idem: dict[str, str] = {}

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
            return True, rec

    async def set_final(
        self,
        *,
        response_id: str,
        status: str,
        final_response_json: dict[str, Any] | None,
        error_json: dict[str, Any] | None,
    ) -> None:
        async with self._lock:
            rec = self._by_response_id.get(response_id)
            if rec is None:
                return
            rec.status = status  # type: ignore[assignment]
            rec.final_response_json = json.loads(json.dumps(final_response_json)) if final_response_json is not None else None
            rec.error_json = json.loads(json.dumps(error_json)) if error_json is not None else None

    async def set_last_event_seq(self, *, response_id: str, last_event_seq: int) -> None:
        async with self._lock:
            rec = self._by_response_id.get(response_id)
            if rec is None:
                return
            rec.last_event_seq = last_event_seq


class InMemoryEventStore:
    def __init__(self) -> None:
        self._lock = asyncio.Lock()
        self._events: dict[str, list[EventRecord]] = {}
        self._notifiers: dict[str, asyncio.Condition] = {}

    async def append(
        self,
        *,
        response_id: str,
        session_partition_key: str,
        event: str | None,
        data: str,
    ) -> int:
        _ = session_partition_key
        async with self._lock:
            seq = len(self._events.get(response_id, [])) + 1
            rec = EventRecord(response_id=response_id, seq=seq, event=event, data=data)
            self._events.setdefault(response_id, []).append(rec)
            cond = self._notifiers.get(response_id)
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
