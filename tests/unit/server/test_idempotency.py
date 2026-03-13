from __future__ import annotations

import asyncio

from anyagent.server.idempotency import begin_or_replay_response_run


class _Run:
    def __init__(self, response_id: str, session_partition_key: str = "main::sess") -> None:
        self.response_id = response_id
        self.session_partition_key = session_partition_key


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
