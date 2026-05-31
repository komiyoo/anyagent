from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from dataclasses import dataclass
from typing import Any

from fastapi import FastAPI
from fastapi.testclient import TestClient

from anyagent.server.routes.internal_events import create_internal_events_router
from anyagent.storage.models import EventRecord, RunRecord
from anyagent.storage.replay import (
    InternalEventsCursorOutOfRange,
    effective_run_status,
    list_internal_events,
    resolve_nonstream_replay_payload,
    stream_external_response_blocks,
    stream_internal_event_blocks,
    wait_for_final_response_json,
)


@dataclass(slots=True)
class _FakeEventStore:
    events: dict[str, list[EventRecord]]
    wait_calls: int = 0

    async def list(self, *, response_id: str, after_seq: int, limit: int) -> list[EventRecord]:
        items = self.events.get(response_id, [])
        return [item for item in items if item.seq > after_seq][:limit]

    async def tail_seq(self, *, response_id: str) -> int:
        items = self.events.get(response_id, [])
        return items[-1].seq if items else 0

    async def wait_new(self, *, response_id: str, after_seq: int, timeout_s: float) -> None:
        _ = response_id, after_seq, timeout_s
        self.wait_calls += 1
        await asyncio.sleep(0)


@dataclass(slots=True)
class _FakeRunStore:
    runs: dict[str, RunRecord]

    async def get(self, response_id: str) -> RunRecord | None:
        return self.runs.get(response_id)


def test_list_internal_events_marks_cancelled_effective_status() -> None:
    async def _run() -> None:
        run_store = _FakeRunStore(
            runs={
                "resp_1": RunRecord(
                    response_id="resp_1",
                    session_partition_key="main::sess",
                    stream=False,
                    status="errored",
                    error_json={"code": "response_cancelled"},
                    final_response_json={"id": "resp_1", "object": "response", "status": "cancelled"},
                )
            }
        )
        event_store = _FakeEventStore(
            events={
                "resp_1": [
                    EventRecord(response_id="resp_1", seq=1, event="response.completed", data='{"id":"resp_1"}'),
                    EventRecord(response_id="resp_1", seq=2, event=None, data="[DONE]"),
                ]
            }
        )

        payload = await list_internal_events(
            run_store=run_store,
            event_store=event_store,
            response_id="resp_1",
            last_seq=0,
            limit=50,
        )

        assert payload.next_last_seq == 2
        assert payload.done is True
        assert payload.run_status == "errored"
        assert payload.effective_run_status == "cancelled"
        assert [item.event for item in payload.events] == ["response.completed", None]

    asyncio.run(_run())


def test_internal_events_router_lists_persisted_events() -> None:
    run_store = _FakeRunStore(
        runs={
            "resp_router": RunRecord(
                response_id="resp_router",
                session_partition_key="main::sess",
                stream=False,
                status="completed",
                final_response_json={"id": "resp_router", "object": "response", "status": "completed"},
            )
        }
    )
    event_store = _FakeEventStore(
        events={
            "resp_router": [
                EventRecord(response_id="resp_router", seq=1, event="response.created", data='{"id":"resp_router"}'),
                EventRecord(response_id="resp_router", seq=2, event=None, data="[DONE]"),
            ]
        }
    )
    app = FastAPI()
    app.state.storage = type("_Storage", (), {"run_store": run_store, "event_store": event_store})()
    app.include_router(create_internal_events_router(api_key="test-key"))

    with TestClient(app) as client:
        response = client.get(
            "/internal/events/list?response_id=resp_router",
            headers={"authorization": "Bearer test-key"},
        )

    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["next_last_seq"] == 2
    assert [item["event"] for item in payload["events"]] == ["response.created", None]


def test_stream_internal_event_blocks_allows_terminal_cursor_past_tail() -> None:
    async def _run() -> None:
        run = RunRecord(
            response_id="resp_done",
            session_partition_key="main::sess",
            stream=False,
            status="completed",
            final_response_json={"id": "resp_done", "object": "response", "status": "completed"},
        )
        run_store = _FakeRunStore(runs={"resp_done": run})
        event_store = _FakeEventStore(events={"resp_done": []})

        chunks = []
        async for chunk in stream_internal_event_blocks(
            run_store=run_store,
            event_store=event_store,
            response_id="resp_done",
            last_seq=99,
        ):
            chunks.append(chunk.decode("utf-8"))

        text = "".join(chunks)
        assert "event: response.completed" in text
        assert "data: [DONE]" in text

    asyncio.run(_run())


def test_stream_internal_event_blocks_rejects_non_terminal_cursor_past_tail() -> None:
    async def _run() -> None:
        run_store = _FakeRunStore(
            runs={
                "resp_live": RunRecord(
                    response_id="resp_live",
                    session_partition_key="main::sess",
                    stream=True,
                    status="started",
                    last_event_seq=1,
                )
            }
        )
        event_store = _FakeEventStore(
            events={"resp_live": [EventRecord(response_id="resp_live", seq=1, event="response.created", data='{"id":"resp_live"}')]}
        )

        try:
            async for _chunk in stream_internal_event_blocks(
                run_store=run_store,
                event_store=event_store,
                response_id="resp_live",
                last_seq=99,
            ):
                raise AssertionError("stream should not yield for out-of-range live cursor")
        except InternalEventsCursorOutOfRange as exc:
            assert exc.requested_last_seq == 99
            assert exc.max_last_seq == 1
        else:
            raise AssertionError("expected InternalEventsCursorOutOfRange")

    asyncio.run(_run())


def test_effective_run_status_maps_cancelled_error() -> None:
    run = RunRecord(
        response_id="resp_cancelled",
        session_partition_key="main::sess",
        stream=False,
        status="errored",
        error_json={"code": "response_cancelled"},
    )
    assert effective_run_status(run) == "cancelled"


def test_wait_for_final_response_json_returns_terminal_payload() -> None:
    async def _run() -> None:
        run_store = _FakeRunStore(
            runs={
                "resp_wait": RunRecord(
                    response_id="resp_wait",
                    session_partition_key="main::sess",
                    stream=False,
                    status="completed",
                    final_response_json={"id": "resp_wait", "object": "response", "status": "completed"},
                )
            }
        )
        payload = await wait_for_final_response_json(run_store=run_store, response_id="resp_wait", timeout_s=0.1)
        assert payload == {"id": "resp_wait", "object": "response", "status": "completed"}

    asyncio.run(_run())


def test_stream_external_response_blocks_filters_internal_events_and_falls_back_to_final_response() -> None:
    async def _run() -> None:
        run_store = _FakeRunStore(
            runs={
                "resp_ext": RunRecord(
                    response_id="resp_ext",
                    session_partition_key="main::sess",
                    stream=True,
                    status="completed",
                    final_response_json={"id": "resp_ext", "object": "response", "status": "completed"},
                )
            }
        )
        event_store = _FakeEventStore(
            events={
                "resp_ext": [
                    EventRecord(response_id="resp_ext", seq=1, event="anyagent.tool.planned", data='{"type":"anyagent.tool.planned"}'),
                ]
            }
        )

        chunks = []
        async for chunk in stream_external_response_blocks(
            run_store=run_store,
            event_store=event_store,
            response_id="resp_ext",
        ):
            chunks.append(chunk.decode("utf-8"))

        text = "".join(chunks)
        assert "anyagent.tool.planned" not in text
        assert "event: response.completed" in text
        assert "data: [DONE]" in text

    asyncio.run(_run())


def test_resolve_nonstream_replay_payload_prefers_final_and_can_fallback() -> None:
    async def _run() -> None:
        completed_run = RunRecord(
            response_id="resp_done",
            session_partition_key="main::sess",
            stream=False,
            status="completed",
            final_response_json={"id": "resp_done", "object": "response", "status": "completed"},
        )
        run_store = _FakeRunStore(runs={"resp_done": completed_run})
        payload = await resolve_nonstream_replay_payload(
            run_store=run_store,
            run=completed_run,
            response_id="resp_done",
            fallback_payload_factory=lambda run: {"id": run.response_id, "status": "fallback"},
        )
        assert payload == {"id": "resp_done", "object": "response", "status": "completed"}

        live_run = RunRecord(
            response_id="resp_live",
            session_partition_key="main::sess",
            stream=False,
            status="started",
        )
        run_store_live = _FakeRunStore(runs={"resp_live": live_run})
        payload2 = await resolve_nonstream_replay_payload(
            run_store=run_store_live,
            run=live_run,
            response_id="resp_live",
            wait_timeout_s=0.01,
            fallback_payload_factory=lambda run: {"id": run.response_id, "status": "fallback"},
        )
        assert payload2 == {"id": "resp_live", "status": "fallback"}

    asyncio.run(_run())
