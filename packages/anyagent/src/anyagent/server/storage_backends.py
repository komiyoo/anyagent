from __future__ import annotations

from typing import Protocol

from anyagent.server.events import InMemoryEventStore, build_cached_event_store, build_redis_event_store
from anyagent.server.run_store import InMemoryRunStore, build_cached_run_store, build_redis_run_store
from anyagent.server.session_store import (
    InMemorySessionStore,
    RedisSessionStore,
    build_cached_session_store,
    build_redis_session_store,
)
from anyagent.storage.settings import StorageSettings


class EventStore(Protocol):
    async def append(self, *, response_id: str, event: str | None, data: str) -> int: ...
    async def mark_started(self, *, response_id: str) -> None: ...
    async def mark_cancel_requested(self, *, response_id: str) -> None: ...
    async def mark_final(self, *, response_id: str, run_status: str, effective_run_status: str | None = None, response_json=None, error=None) -> None: ...
    async def get_response(self, response_id: str): ...
    async def get_status(self, response_id: str): ...
    async def list_events(self, *, response_id: str, last_seq: int = 0, limit: int = 200): ...
    async def latest_seq(self, response_id: str) -> int: ...
    async def stream_events(self, *, response_id: str, last_seq: int = 0): ...


class RunStore(Protocol):
    async def get(self, response_id: str): ...
    async def get_by_idempotency_key(self, idempotency_key: str): ...
    async def create_started(self, *, response_id: str, agent_id: str, session_key: str, stream: bool, idempotency_key: str | None): ...
    async def mark_cancel_requested(self, response_id: str) -> None: ...
    async def mark_final(self, *, response_id: str, status: str, effective_status: str, final_response_json, error_json=None) -> None: ...


class SessionStore(Protocol):
    async def get(self, *, session_partition_key: str): ...
    async def upsert(self, *, session_partition_key: str, agent_id: str, session_key: str, snapshot_json, expected_snapshot_version: int | None): ...


def build_event_store(*, backend: str) -> EventStore:
    if backend == "inmemory":
        return InMemoryEventStore()
    if backend in {"external", "redis"}:
        settings = StorageSettings()
        if backend == "external" and settings.postgres_dsn is not None:
            return build_cached_event_store()
        return build_redis_event_store()
    raise RuntimeError(f"event store backend not implemented: {backend}")


def build_run_store(*, backend: str) -> RunStore:
    if backend == "inmemory":
        return InMemoryRunStore()
    if backend in {"external", "redis"}:
        settings = StorageSettings()
        if backend == "external" and settings.postgres_dsn is not None:
            return build_cached_run_store()
        return build_redis_run_store()
    raise RuntimeError(f"run store backend not implemented: {backend}")


def build_session_store(*, backend: str) -> SessionStore:
    if backend == "inmemory":
        return InMemorySessionStore()
    if backend in {"external", "redis"}:
        settings = StorageSettings()
        if backend == "external" and settings.postgres_dsn is not None:
            return build_cached_session_store()
        return build_redis_session_store()
    raise RuntimeError(f"session store backend not implemented: {backend}")
