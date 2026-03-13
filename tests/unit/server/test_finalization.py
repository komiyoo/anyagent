from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import Any

from anyagent.server.finalization import (
    build_nonstream_response_finalizer,
    finalize_nonstream_response,
    internal_run_status_from_effective,
    persist_run_final_and_session,
    resolve_terminal_status,
)


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


class _Recorder:
    def __init__(self) -> None:
        self.events: list[tuple[str | None, str]] = []
        self.marked: list[dict[str, Any]] = []
        self.persisted: list[dict[str, Any]] = []
        self.advanced: list[dict[str, Any]] = []

    async def append(self, event: str | None, data: str) -> int:
        self.events.append((event, data))
        return len(self.events)

    async def mark(self, state) -> None:
        self.marked.append(
            {
                "response_id": state.response_id,
                "effective_status": state.effective_status,
                "run_status": state.run_status,
                "response_json": state.response_json,
                "error_json": state.error_json,
                "last_event_seq": state.last_event_seq,
            }
        )

    async def persist(self, state) -> None:
        self.persisted.append(
            {
                "response_id": state.response_id,
                "effective_status": state.effective_status,
                "run_status": state.run_status,
                "response_json": state.response_json,
                "error_json": state.error_json,
                "last_event_seq": state.last_event_seq,
            }
        )

    async def advance(self, state) -> None:
        self.advanced.append(
            {
                "response_id": state.response_id,
                "effective_status": state.effective_status,
                "resume_last_response_id": state.resume_last_response_id,
                "last_event_seq": state.last_event_seq,
            }
        )


def test_internal_run_status_from_effective_maps_expected_values() -> None:
    assert internal_run_status_from_effective("cancelled") == "aborted"
    assert internal_run_status_from_effective("failed") == "errored"
    assert internal_run_status_from_effective("in_progress") == "started"
    assert internal_run_status_from_effective("completed") == "completed"


def test_resolve_terminal_status_prefers_effective_status_then_payload_then_error() -> None:
    assert resolve_terminal_status(effective_status="cancelled", response_json=None, error_json=None) == ("cancelled", "aborted")
    assert resolve_terminal_status(
        effective_status=None,
        response_json={"id": "resp_1", "object": "response", "status": "completed"},
        error_json=None,
    ) == ("completed", "completed")
    assert resolve_terminal_status(effective_status=None, response_json=None, error_json={"type": "server_error"}) == ("failed", "errored")


def test_finalize_nonstream_response_appends_completed_and_done_and_runs_hooks() -> None:
    async def _run() -> None:
        rec = _Recorder()
        state = await finalize_nonstream_response(
            response_id="resp_old",
            response_json={"id": "resp_old", "object": "response", "status": "completed", "output": []},
            append_event=rec.append,
            mark_event_final=rec.mark,
            persist_run_final=rec.persist,
            advance_session=rec.advance,
            resume_last_response_id="resp_upstream",
        )
        assert state.response_id == "resp_old"
        assert state.effective_status == "completed"
        assert state.run_status == "completed"
        assert state.last_event_seq == 2
        assert rec.events[0][0] == "response.completed"
        assert rec.events[1] == (None, "[DONE]")
        assert rec.marked[0]["last_event_seq"] == 2
        assert rec.persisted[0]["response_json"]["id"] == "resp_old"
        assert rec.advanced[0]["resume_last_response_id"] == "resp_upstream"

    asyncio.run(_run())


def test_finalize_nonstream_response_appends_error_and_done_without_completed() -> None:
    async def _run() -> None:
        rec = _Recorder()
        state = await finalize_nonstream_response(
            response_id="resp_err",
            response_json=None,
            effective_status="failed",
            error_json={"type": "server_error", "message": "boom"},
            error_event_data='{"error":{"type":"server_error","message":"boom"}}',
            append_event=rec.append,
            persist_run_final=rec.persist,
        )
        assert state.run_status == "errored"
        assert rec.events == [
            ("error", '{"error":{"type":"server_error","message":"boom"}}'),
            (None, "[DONE]"),
        ]
        assert rec.persisted[0]["error_json"] == {"type": "server_error", "message": "boom"}
        assert state.last_event_seq == 2

    asyncio.run(_run())


def test_persist_run_final_and_session_uses_atomic_path_when_available() -> None:
    async def _run() -> None:
        run_store = _AtomicRunStore(atomic_ok=True)
        session_store = _SessionStore()
        await persist_run_final_and_session(
            run_store=run_store,
            session_store=session_store,
            response_id="resp_1",
            effective_status="completed",
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
            effective_status="failed",
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
            effective_status="completed",
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


def test_build_session_snapshot_advancer_updates_snapshot() -> None:
    async def _run() -> None:
        from anyagent.server.finalization import build_session_snapshot_advancer

        session_store = _SessionStore()
        warnings: list[str] = []
        advance = build_session_snapshot_advancer(
            session_store=session_store,
            session_partition_key="main::sess",
            agent_id="main",
            session_key="sess",
            previous_snapshot={"resume_cursor": {"last_response_id": None, "fallback_transcript_items": []}},
            previous_snapshot_version=0,
            runtime_config={"model": "gpt-4.1-mini"},
            request_transcript_items=[{"role": "user", "content": "hello"}],
            warn=warnings.append,
        )
        await advance(
            type(
                "State",
                (),
                {
                    "response_id": "resp_adv",
                    "effective_status": "completed",
                    "response_json": {"id": "resp_adv", "object": "response", "status": "completed"},
                    "last_event_seq": 3,
                    "resume_last_response_id": "resp_adv",
                },
            )()
        )

        record = session_store.records["main::sess"]
        assert record.snapshot_json["resume_cursor"]["last_response_id"] == "resp_adv"
        assert record.snapshot_json["last_run"]["last_event_seq"] == 3
        assert warnings == []

    asyncio.run(_run())


def test_build_session_snapshot_advancer_warns_on_cas_conflict() -> None:
    async def _run() -> None:
        from anyagent.server.finalization import build_session_snapshot_advancer

        session_store = _SessionStore()
        session_store.records["main::sess"] = _SessionRecord(
            session_partition_key="main::sess",
            agent_id="main",
            session_key="sess",
            snapshot_json={},
            snapshot_version=9,
        )
        warnings: list[str] = []
        advance = build_session_snapshot_advancer(
            session_store=session_store,
            session_partition_key="main::sess",
            agent_id="main",
            session_key="sess",
            previous_snapshot={"resume_cursor": {"last_response_id": None, "fallback_transcript_items": []}},
            previous_snapshot_version=0,
            runtime_config={"model": "gpt-4.1-mini"},
            request_transcript_items=[],
            warn=warnings.append,
        )
        await advance(
            type(
                "State",
                (),
                {
                    "response_id": "resp_adv",
                    "effective_status": "completed",
                    "response_json": {"id": "resp_adv", "object": "response", "status": "completed"},
                    "last_event_seq": 3,
                    "resume_last_response_id": "resp_adv",
                },
            )()
        )

        assert warnings
        assert warnings[0].startswith("persist session snapshot failed (cas):")

    asyncio.run(_run())


def test_build_run_final_and_session_persister_updates_run_and_session() -> None:
    async def _run() -> None:
        from anyagent.server.finalization import build_run_final_and_session_persister

        run_store = _SimpleRunStore()
        session_store = _SessionStore()
        warnings: list[str] = []
        persist = build_run_final_and_session_persister(
            run_store=run_store,
            session_store=session_store,
            session_partition_key="main::sess",
            agent_id="main",
            session_key="sess",
            previous_snapshot={"resume_cursor": {"last_response_id": None, "fallback_transcript_items": []}},
            previous_snapshot_version=0,
            runtime_config={"model": "gpt-4.1-mini"},
            request_transcript_items=[],
            warn=warnings.append,
        )
        await persist(
            type(
                "State",
                (),
                {
                    "response_id": "resp_persist",
                    "effective_status": "completed",
                    "response_json": {"id": "resp_persist", "object": "response", "status": "completed"},
                    "error_json": None,
                    "resume_last_response_id": "resp_persist",
                    "last_event_seq": 4,
                },
            )()
        )

        assert run_store.final_calls[0]["response_id"] == "resp_persist"
        assert session_store.records["main::sess"].snapshot_json["resume_cursor"]["last_response_id"] == "resp_persist"
        assert warnings == []

    asyncio.run(_run())


def test_build_nonstream_response_finalizer_binds_defaults_and_overrides() -> None:
    async def _run() -> None:
        rec = _Recorder()
        finalizer = build_nonstream_response_finalizer(
            response_id="resp_bound",
            append_event=rec.append,
            append_completed_event=False,
            append_done_sentinel=False,
            resume_last_response_id="resp_resume",
        )
        state = await finalizer(
            response_json={"id": "resp_bound", "object": "response", "status": "completed"},
            append_completed_event_override=True,
            append_done_sentinel_override=True,
        )
        assert state.response_id == "resp_bound"
        assert state.resume_last_response_id == "resp_resume"
        assert rec.events[0][0] == "response.completed"
        assert rec.events[1] == (None, "[DONE]")

    asyncio.run(_run())
