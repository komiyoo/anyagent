from __future__ import annotations

import asyncio
import json
from typing import Any

from fastapi.responses import JSONResponse

from anyagent.gateway.sequencer import KeyedSequencer
from anyagent.server.session_serialization import (
    DistributedSessionSerializationConfig,
    run_distributed_response_with_session_serialization,
    run_with_storage_session_lease,
    should_skip_external_session_lease,
)
from anyagent.storage.inmemory import InMemoryEventStore, InMemoryLeaseLock, InMemoryRunStore, InMemorySessionStore
from anyagent.storage.runtime import StorageRuntime


def _storage(*, mode: str = "external", lease_lock: Any | None = None) -> StorageRuntime:
    return StorageRuntime(
        mode=mode,
        run_store=InMemoryRunStore(),
        event_store=InMemoryEventStore(),
        lease_lock=lease_lock or InMemoryLeaseLock(),
        session_store=InMemorySessionStore(),
    )


class _RejectingLeaseLock:
    async def acquire(self, *, key: str, owner: str, ttl_ms: int, wait_timeout_ms: int):
        return None

    async def renew(self, *, key: str, owner: str, ttl_ms: int) -> bool:
        return False

    async def release(self, *, key: str, owner: str) -> bool:
        return True


def test_should_skip_external_session_lease_only_for_idempotent_stream_leaders() -> None:
    assert should_skip_external_session_lease(
        stream=True,
        idempotency_key="idem",
        idem_created=True,
        idem_response_id="resp_1",
    )
    assert not should_skip_external_session_lease(
        stream=False,
        idempotency_key="idem",
        idem_created=True,
        idem_response_id="resp_1",
    )
    assert not should_skip_external_session_lease(
        stream=True,
        idempotency_key=None,
        idem_created=True,
        idem_response_id="resp_1",
    )


def test_run_with_storage_session_lease_raises_on_busy_external_lock() -> None:
    async def _run() -> None:
        try:
            await run_with_storage_session_lease(
                storage=_storage(lease_lock=_RejectingLeaseLock()),
                session_partition_key="main::sess",
                owner="owner",
                fn=lambda: _json_response({"ok": True}),
                config=DistributedSessionSerializationConfig(renew_interval_s=0.01),
            )
        except RuntimeError as exc:
            assert str(exc) == "lease_lock_unavailable"
        else:
            raise AssertionError("expected RuntimeError")

    asyncio.run(_run())


def test_run_distributed_response_with_session_serialization_returns_busy_response() -> None:
    async def _run() -> None:
        response = await run_distributed_response_with_session_serialization(
            storage=_storage(lease_lock=_RejectingLeaseLock()),
            session_partition_key="main::sess",
            owner="owner",
            stream=False,
            idempotency_key=None,
            idem_created=False,
            idem_response_id=None,
            sequencer=KeyedSequencer(),
            fn=lambda: _json_response({"ok": True}),
            config=DistributedSessionSerializationConfig(renew_interval_s=0.01),
        )
        assert response.status_code == 409
        assert json.loads(response.body)["error"]["code"] == "lease_lock_unavailable"

    asyncio.run(_run())


def test_run_distributed_response_with_session_serialization_runs_without_external_lease_when_skipped() -> None:
    async def _run() -> None:
        response = await run_distributed_response_with_session_serialization(
            storage=_storage(lease_lock=_RejectingLeaseLock()),
            session_partition_key="main::sess",
            owner="owner",
            stream=True,
            idempotency_key="idem",
            idem_created=True,
            idem_response_id="resp_1",
            sequencer=KeyedSequencer(),
            fn=lambda: _json_response({"ok": True}),
            config=DistributedSessionSerializationConfig(renew_interval_s=0.01),
        )
        assert response.status_code == 200
        assert json.loads(response.body) == {"ok": True}

    asyncio.run(_run())


async def _json_response(payload: dict[str, Any]) -> JSONResponse:
    return JSONResponse(payload)
