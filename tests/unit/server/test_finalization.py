from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import Any

from anyagent.server.finalization import internal_run_status_from_effective, persist_run_final_and_session


@dataclass(slots=True)
class _SessionRecord:
    session_partition_key: str
    agent_id: str
    session_key: str
    snapshot_json: dict[str, Any]
    snapshot_version: int


class _SessionStore:
    def __init__(self) -> None:
        self.records: dict[str, _SessionRecord] = {}

    async def update_snapshot_cas(
        self,
        *,
        session_partition_key: str,
        expected_snapshot_version: int,
        snapshot_json: dict[str, Any],
        agent_id: str,
        session_key: str,
    ) -> tuple[bool, _SessionRecord | None]:
        current = self.records.get(session_partition_key)
        if current is None:
            current = _SessionRecord(
                session_partition_key=session_partition_key,
                agent_id=agent_id,
                session_key=session_key,
                snapshot_json={},
                snapshot_version=expected_snapshot_version,
            )
        if current.snapshot_version != expected_snapshot_version:
            return False, current
        latest = _SessionRecord(
            session_partition_key=session_partition_key,
            agent_id=agent_id,
            session_key=session_key,
            snapshot_json=snapshot_json,
            snapshot_version=expected_snapshot_version + 1,
        )
        self.records[session_partition_key] = latest
        return True, latest


class _AtomicRunStore:
    def __init__(self, *, atomic_ok: bool) -> None:
        self.atomic_ok = atomic_ok
        self.atomic_calls: list[dict[str, Any]] = []
        self.final_calls: list[dict[str, Any]] = []

    async def set_final_with_session_snapshot(self, **kwargs: Any) -> tuple[bool, None]:
        self.atomic_calls.append(kwargs)
        return self.atomic_ok, None

    async def set_final(self, **kwargs: Any) -> None:
        self.final_calls.append(kwargs)


class _SimpleRunStore:
    def __init__(self) -> None:
        self.final_calls: list[dict[str, Any]] = []

    async def set_final(self, **kwargs: Any) -> None:
        self.final_calls.append(kwargs)


def test_internal_run_status_from_effective_maps_expected_values() -> None:
    assert internal_run_status_from_effective("cancelled") == "aborted"
    assert internal_run_status_from_effective("failed") == "errored"
    assert internal_run_status_from_effective("in_progress") == "started"
    assert internal_run_status_from_effective("completed") == "completed"


def test_persist_run_final_and_session_uses_atomic_path_when_available() -> None:
    async def _run() -> None:
        run_store = _AtomicRunStore(atomic_ok=True)
        session_store = _SessionStore()
        await persist_run_final_and_session(
            run_store=run_store,
            session_store=session_store,
            response_id="resp_1",
            status="completed",
            final_response_json={"id": "resp_1", "object": "response", "status": "completed"},
            error_json=None,
            session_partition_key="main::sess",
            agent_id="main",
            session_key="sess",
            previous_snapshot={"resume_cursor": {"last_response_id": None, "fallback_transcript_items": []}},
            previous_snapshot_version=0,
            runtime_config={"model": "gpt-4.1-mini"},
            request_transcript_items=[{"role": "user", "content": "hello"}],
            resume_last_response_id="resp_1",
            last_event_seq=3,
        )
        assert len(run_store.atomic_calls) == 1
        assert run_store.final_calls == []
        assert session_store.records == {}

    asyncio.run(_run())


def test_persist_run_final_and_session_falls_back_to_run_only_when_atomic_fails() -> None:
    async def _run() -> None:
        run_store = _AtomicRunStore(atomic_ok=False)
        session_store = _SessionStore()
        await persist_run_final_and_session(
            run_store=run_store,
            session_store=session_store,
            response_id="resp_2",
            status="errored",
            final_response_json=None,
            error_json={"type": "server_error", "message": "boom"},
            session_partition_key="main::sess",
            agent_id="main",
            session_key="sess",
            previous_snapshot={"resume_cursor": {"last_response_id": None, "fallback_transcript_items": []}},
            previous_snapshot_version=0,
            runtime_config={"model": "gpt-4.1-mini"},
            request_transcript_items=[],
            resume_last_response_id=None,
            last_event_seq=4,
        )
        assert len(run_store.atomic_calls) == 1
        assert len(run_store.final_calls) == 1
        assert session_store.records == {}

    asyncio.run(_run())


def test_persist_run_final_and_session_updates_session_when_no_atomic_path() -> None:
    async def _run() -> None:
        run_store = _SimpleRunStore()
        session_store = _SessionStore()
        await persist_run_final_and_session(
            run_store=run_store,
            session_store=session_store,
            response_id="resp_3",
            status="completed",
            final_response_json={
                "id": "resp_3",
                "object": "response",
                "status": "completed",
                "output": [
                    {
                        "type": "message",
                        "role": "assistant",
                        "content": [{"type": "output_text", "text": "done"}],
                    }
                ],
            },
            error_json=None,
            session_partition_key="main::sess",
            agent_id="main",
            session_key="sess",
            previous_snapshot={"resume_cursor": {"last_response_id": None, "fallback_transcript_items": []}},
            previous_snapshot_version=0,
            runtime_config={"model": "gpt-4.1-mini"},
            request_transcript_items=[{"role": "user", "content": "hello"}],
            resume_last_response_id="resp_3",
            last_event_seq=5,
        )
        assert len(run_store.final_calls) == 1
        latest = session_store.records["main::sess"]
        assert latest.snapshot_version == 1
        assert latest.snapshot_json["resume_cursor"]["last_response_id"] == "resp_3"

    asyncio.run(_run())
