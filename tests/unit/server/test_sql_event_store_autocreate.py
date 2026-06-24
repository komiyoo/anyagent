from __future__ import annotations

import asyncio

from sqlalchemy.exc import IntegrityError

from anyagent.storage.external.sqlalchemy_backend import SqlAlchemyEventStore


class _FakeResult:
    def __init__(self, first_value: object) -> None:
        self._first = first_value

    def first(self):  # noqa: ANN201
        return self._first


class _FakeConn:
    """Replays a scripted sequence of execute() outcomes.

    Each script entry is either a ``.first()`` return value (for SELECTs) or
    an Exception instance to raise (for simulating constraint violations).
    """

    def __init__(self, script: list[object]) -> None:
        self._script = list(script)
        self._i = 0

    async def execute(self, stmt: object, *args: object, **kwargs: object) -> _FakeResult:
        entry = self._script[self._i]
        self._i += 1
        if isinstance(entry, BaseException):
            raise entry
        return _FakeResult(entry)


class _FakeBegin:
    def __init__(self, conn: _FakeConn) -> None:
        self._conn = conn

    async def __aenter__(self) -> _FakeConn:
        return self._conn

    async def __aexit__(self, exc_type: object, exc: object, tb: object) -> bool:
        return False


class _FakeEngine:
    def __init__(self, script: list[object]) -> None:
        self._script = script

    def begin(self) -> _FakeBegin:
        return _FakeBegin(_FakeConn(self._script))


def _store(script: list[object]) -> SqlAlchemyEventStore:
    return SqlAlchemyEventStore(engine=_FakeEngine(script), schema_name="public", dialect="postgresql")


def test_append_autocreates_run_for_orphan_response_id() -> None:
    # SELECT last_event_seq -> None (no run); INSERT run (ok); re-SELECT -> (0,);
    # UPDATE last_event_seq; INSERT event. No run_not_found raised.
    async def _run() -> int:
        store = _store([None, None, (0,), None, None])
        return await store.append(
            response_id="platform::chatwoot:1:42::conversation_resolved",
            session_partition_key="",
            event="platform.conversation.conversation_resolved",
            data="{}",
        )

    assert asyncio.run(_run()) == 1


def test_append_handles_concurrent_integrity_error_without_run_not_found() -> None:
    # A concurrent append inserted the run first: INSERT raises IntegrityError
    # (caught), re-SELECT finds the row -> no run_not_found, seq advances.
    async def _run() -> int:
        store = _store([None, IntegrityError("insert", {}, Exception("dup")), (0,), None, None])
        return await store.append(
            response_id="platform::chatwoot:1:42::conversation_resolved",
            session_partition_key="",
            event="platform.conversation.conversation_resolved",
            data="{}",
        )

    assert asyncio.run(_run()) == 1


def test_append_advances_seq_for_existing_run() -> None:
    # Run already exists with last_event_seq=5 -> seq becomes 6 (no auto-create).
    async def _run() -> int:
        store = _store([(5,), None, None])
        return await store.append(
            response_id="resp_existing",
            session_partition_key="main::s1",
            event="response.completed",
            data="{}",
        )

    assert asyncio.run(_run()) == 6
