from __future__ import annotations

import asyncio
import json

from fastapi.responses import JSONResponse

from anyagent.server.idempotency import begin_distributed_response_run, begin_or_replay_response_run
from anyagent.storage.inmemory import InMemoryEventStore, InMemoryLeaseLock, InMemoryRunStore, InMemorySessionStore
from anyagent.storage.runtime import StorageRuntime


class _Run:
    def __init__(self, response_id: str, session_partition_key: str = "main::sess") -> None:
        self.response_id = response_id
        self.session_partition_key = session_partition_key


def _storage() -> StorageRuntime:
    return StorageRuntime(
        mode="none",
        run_store=InMemoryRunStore(),
        event_store=InMemoryEventStore(),
        lease_lock=InMemoryLeaseLock(),
        session_store=InMemorySessionStore(),
    )


def test_begin_or_replay_response_run_creates_new_run_without_idempotency_key() -> None:
    async def _run() -> None:
        calls: list[tuple[str, str | None]] = []

        async def _create_started(response_id: str, idem: str | None):
            calls.append((response_id, idem))
            return _Run(response_id)

        result = await begin_or_replay_response_run(
            idempotency_key=None,
            stream=False,
            new_response_id_factory=lambda: "resp_new",
            create_started_run=_create_started,
        )

        assert result.created is True
        assert result.response_id == "resp_new"
        assert calls == [("resp_new", None)]

    asyncio.run(_run())


def test_begin_or_replay_response_run_replays_existing_nonstream_run() -> None:
    async def _run() -> None:
        async def _lookup_existing(idem: str):
            assert idem == "idem-1"
            return _Run("resp_existing")

        async def _build_nonstream(run, response_id: str):
            assert run.response_id == "resp_existing"
            assert response_id == "resp_existing"
            return {"id": response_id, "status": "completed"}

        result = await begin_or_replay_response_run(
            idempotency_key="idem-1",
            stream=False,
            new_response_id_factory=lambda: "resp_unused",
            lookup_existing_run=_lookup_existing,
            build_nonstream_replay_response=_build_nonstream,
        )

        assert result.created is False
        assert result.response_id == "resp_existing"
        assert result.response == {"id": "resp_existing", "status": "completed"}

    asyncio.run(_run())


def test_begin_or_replay_response_run_returns_conflict_response_from_validator() -> None:
    async def _run() -> None:
        async def _try_create_started(response_id: str, idem: str):
            assert response_id == "resp_candidate"
            assert idem == "idem-2"
            return False, _Run("resp_existing", session_partition_key="other::sess")

        result = await begin_or_replay_response_run(
            idempotency_key="idem-2",
            stream=True,
            new_response_id_factory=lambda: "resp_candidate",
            try_create_started_run=_try_create_started,
            validate_run=lambda run: {"error": f"mismatch:{run.session_partition_key}"},
            build_stream_replay_response=lambda response_id: response_id,
        )

        assert result.created is False
        assert result.response_id == "resp_existing"
        assert result.response == {"error": "mismatch:other::sess"}

    asyncio.run(_run())


def test_begin_or_replay_response_run_replays_existing_stream_run() -> None:
    async def _run() -> None:
        async def _try_create_started(response_id: str, idem: str):
            assert response_id == "resp_candidate"
            assert idem == "idem-stream"
            return False, _Run("resp_existing_stream")

        result = await begin_or_replay_response_run(
            idempotency_key="idem-stream",
            stream=True,
            new_response_id_factory=lambda: "resp_candidate",
            try_create_started_run=_try_create_started,
            build_stream_replay_response=lambda response_id: f"stream:{response_id}",
        )

        assert result.created is False
        assert result.response_id == "resp_existing_stream"
        assert result.response == "stream:resp_existing_stream"

    asyncio.run(_run())


def test_begin_distributed_response_run_creates_and_replays_nonstream_payload() -> None:
    async def _run() -> None:
        storage = _storage()
        first = await begin_distributed_response_run(
            idempotency_key="idem-dist",
            stream=False,
            session_partition_key="main::sess",
            storage=storage,
            new_response_id_factory=lambda: "resp_dist",
            nonstream_wait_timeout_s=0.0,
        )
        assert first.created is True
        assert first.response_id == "resp_dist"
        assert first.response is None

        await storage.run_store.set_final(
            response_id="resp_dist",
            status="completed",
            final_response_json={"id": "resp_dist", "status": "completed"},
            error_json=None,
        )

        replay = await begin_distributed_response_run(
            idempotency_key="idem-dist",
            stream=False,
            session_partition_key="main::sess",
            storage=storage,
            new_response_id_factory=lambda: "resp_unused",
            nonstream_wait_timeout_s=0.0,
        )
        assert replay.created is False
        assert replay.response_id == "resp_dist"
        assert isinstance(replay.response, JSONResponse)
        assert json.loads(replay.response.body) == {"id": "resp_dist", "status": "completed"}

    asyncio.run(_run())


def test_begin_distributed_response_run_conflicts_on_session_mismatch() -> None:
    async def _run() -> None:
        storage = _storage()
        await begin_distributed_response_run(
            idempotency_key="idem-conflict",
            stream=False,
            session_partition_key="main::sess",
            storage=storage,
            new_response_id_factory=lambda: "resp_conflict",
            nonstream_wait_timeout_s=0.0,
        )

        replay = await begin_distributed_response_run(
            idempotency_key="idem-conflict",
            stream=False,
            session_partition_key="other::sess",
            storage=storage,
            new_response_id_factory=lambda: "resp_unused",
            nonstream_wait_timeout_s=0.0,
        )
        assert replay.created is False
        assert replay.response is not None
        assert replay.response.status_code == 409
        assert json.loads(replay.response.body)["error"]["code"] == "idempotency_key_conflict"

    asyncio.run(_run())


def test_begin_distributed_response_run_times_out_in_progress_nonstream() -> None:
    async def _run() -> None:
        storage = _storage()
        await begin_distributed_response_run(
            idempotency_key="idem-wait",
            stream=False,
            session_partition_key="main::sess",
            storage=storage,
            new_response_id_factory=lambda: "resp_waiting",
            nonstream_wait_timeout_s=0.0,
        )

        replay = await begin_distributed_response_run(
            idempotency_key="idem-wait",
            stream=False,
            session_partition_key="main::sess",
            storage=storage,
            new_response_id_factory=lambda: "resp_unused",
            nonstream_wait_timeout_s=0.0,
        )
        assert replay.created is False
        assert replay.response is not None
        assert replay.response.status_code == 504

    asyncio.run(_run())
