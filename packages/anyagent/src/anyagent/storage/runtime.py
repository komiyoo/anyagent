from __future__ import annotations

import inspect
from dataclasses import dataclass
from typing import Any

from .contracts import EventStore, LeaseLock, RunStore, SessionStore


async def _maybe_close(resource: Any) -> None:
    if resource is None:
        return
    for attr in ("aclose", "close"):
        closer = getattr(resource, attr, None)
        if not callable(closer):
            continue
        result = closer()
        if inspect.isawaitable(result):
            await result
        return


@dataclass(slots=True)
class StorageRuntime:
    mode: str
    run_store: RunStore
    event_store: EventStore
    lease_lock: LeaseLock
    session_store: SessionStore
    rollout_writer: Any | None = None
    sql_engine: Any | None = None
    pg_pool: Any | None = None
    redis: Any | None = None

    async def aclose(self) -> None:
        await _maybe_close(self.sql_engine)
        await _maybe_close(self.pg_pool)
        await _maybe_close(self.redis)
