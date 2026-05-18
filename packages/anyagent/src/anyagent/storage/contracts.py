from __future__ import annotations

from typing import Protocol

from .models import EventRecord, LeaseLockHandle, RunRecord, SessionRecord, SessionWorkspaceRecord


class LeaseLock(Protocol):
    async def acquire(self, *, key: str, owner: str, ttl_ms: int, wait_timeout_ms: int) -> LeaseLockHandle | None: ...

    async def renew(self, *, key: str, owner: str, ttl_ms: int) -> bool: ...

    async def release(self, *, key: str, owner: str) -> bool: ...


class RunStore(Protocol):
    async def get_by_idempotency_key(self, key: str) -> RunRecord | None: ...

    async def get(self, response_id: str) -> RunRecord | None: ...

    async def list(
        self,
        *,
        agent_id: str | None = None,
        session_key: str | None = None,
        response_id: str | None = None,
        limit: int = 100,
    ) -> list[RunRecord]: ...

    async def try_create_started(
        self,
        *,
        response_id: str,
        session_partition_key: str,
        idempotency_key: str,
        stream: bool,
    ) -> tuple[bool, RunRecord]: ...

    async def set_final(
        self,
        *,
        response_id: str,
        status: str,
        final_response_json: dict | None,
        error_json: dict | None,
    ) -> None: ...

    async def try_set_final_from_status(
        self,
        *,
        response_id: str,
        current_status: str,
        next_status: str,
        final_response_json: dict | None,
        error_json: dict | None,
    ) -> tuple[bool, RunRecord | None]: ...


class RunStoreWithLastEventSeq(RunStore, Protocol):
    async def set_last_event_seq(self, *, response_id: str, last_event_seq: int) -> None: ...


class RunStoreWithSessionSnapshot(RunStore, Protocol):
    async def set_final_with_session_snapshot(
        self,
        *,
        response_id: str,
        status: str,
        final_response_json: dict | None,
        error_json: dict | None,
        session_partition_key: str,
        agent_id: str,
        session_key: str,
        snapshot_json: dict,
        expected_snapshot_version: int,
    ) -> tuple[bool, SessionRecord | None]: ...


class EventStore(Protocol):
    async def append(self, *, response_id: str, session_partition_key: str, event: str | None, data: str) -> int: ...

    async def list(self, *, response_id: str, after_seq: int, limit: int) -> list[EventRecord]: ...


class EventStoreWithWaitNew(EventStore, Protocol):
    async def wait_new(self, *, response_id: str, after_seq: int, timeout_s: float) -> None: ...


class EventStoreWithTailSeq(EventStore, Protocol):
    async def tail_seq(self, *, response_id: str) -> int: ...


class SessionStore(Protocol):
    async def get(self, *, session_partition_key: str) -> SessionRecord | None: ...

    async def create_if_absent(
        self,
        *,
        session_partition_key: str,
        agent_id: str,
        session_key: str,
        snapshot_json: dict,
    ) -> SessionRecord: ...

    async def update_snapshot_cas(
        self,
        *,
        session_partition_key: str,
        expected_snapshot_version: int,
        snapshot_json: dict,
        agent_id: str,
        session_key: str,
    ) -> tuple[bool, SessionRecord | None]: ...


class SessionWorkspaceStore(Protocol):
    async def get(self, *, session_partition_key: str) -> SessionWorkspaceRecord | None: ...

    async def upsert(self, *, record: SessionWorkspaceRecord) -> SessionWorkspaceRecord: ...

    async def delete(self, *, session_partition_key: str) -> bool: ...
