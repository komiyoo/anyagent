from __future__ import annotations

from .capabilities import build_storage_capability_matrix
from .contracts import (
    EventStore,
    EventStoreWithTailSeq,
    EventStoreWithWaitNew,
    LeaseLock,
    RunStore,
    RunStoreWithLastEventSeq,
    RunStoreWithSessionSnapshot,
    SessionStore,
    SessionWorkspaceStore,
)
from .inmemory import InMemoryEventStore, InMemoryLeaseLock, InMemoryRunStore, InMemorySessionStore
from .models import EventRecord, LeaseLockHandle, RunRecord, RunStatus, SessionRecord, SessionWorkspaceRecord, WorkspaceState
from .replay import (
    InternalEventsCursorOutOfRange,
    InternalEventsRunNotFound,
    ReplayEvent,
    effective_run_status,
    internal_events_tail_seq,
    list_internal_events,
    require_run,
    resolve_nonstream_replay_payload,
    stream_external_response_blocks,
    stream_internal_event_blocks,
    wait_for_final_response_json,
)
from .retention import RetentionPolicy, run_retention_from_args
from .rollout import RolloutFileWriter
from .rollout_replay import ReplayFilters, replay_rollout_records, resolve_rollout_root_dir
from .runtime import StorageRuntime, create_storage_runtime, resolve_rollout_runtime_root, resolve_storage_runtime_mode

_EXTERNAL_EXPORTS = {
    "ExternalSqlBackendConfig",
    "MySQLDsn",
    "PostgresEventStore",
    "PostgresLeaseLock",
    "PostgresRunStore",
    "PostgresSessionStore",
    "RedisLeaseLock",
    "SqlBackendDialect",
}

__all__ = [
    "EventRecord",
    "EventStore",
    "EventStoreWithTailSeq",
    "EventStoreWithWaitNew",
    "ExternalSqlBackendConfig",
    "LeaseLock",
    "LeaseLockHandle",
    "MySQLDsn",
    "PostgresEventStore",
    "PostgresLeaseLock",
    "PostgresRunStore",
    "PostgresSessionStore",
    "RedisLeaseLock",
    "SqlBackendDialect",
    "build_storage_capability_matrix",
    "InternalEventsCursorOutOfRange",
    "InternalEventsRunNotFound",
    "InMemoryEventStore",
    "InMemoryLeaseLock",
    "InMemoryRunStore",
    "InMemorySessionStore",
    "ReplayEvent",
    "ReplayFilters",
    "RetentionPolicy",
    "RolloutFileWriter",
    "RunRecord",
    "RunStatus",
    "RunStore",
    "RunStoreWithLastEventSeq",
    "RunStoreWithSessionSnapshot",
    "SessionRecord",
    "SessionStore",
    "SessionWorkspaceRecord",
    "SessionWorkspaceStore",
    "StorageRuntime",
    "WorkspaceState",
    "effective_run_status",
    "internal_events_tail_seq",
    "list_internal_events",
    "require_run",
    "resolve_nonstream_replay_payload",
    "resolve_rollout_runtime_root",
    "replay_rollout_records",
    "resolve_rollout_root_dir",
    "resolve_storage_runtime_mode",
    "run_retention_from_args",
    "stream_external_response_blocks",
    "stream_internal_event_blocks",
    "wait_for_final_response_json",
]


def __getattr__(name: str):
    if name in _EXTERNAL_EXPORTS:
        from . import external

        return getattr(external, name)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    "create_storage_runtime",
