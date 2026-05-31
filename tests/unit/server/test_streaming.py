from __future__ import annotations

import asyncio

from anyagent.protocol.sse import SSEBlockDecoder
from anyagent.server.responses.streaming import (
    append_sse_chunk,
    build_persisted_sse_block_handler,
    build_response_event_appender,
    handle_persisted_sse_block,
    normalize_forward_stream_block,
)


class _Recorder:
    def __init__(self) -> None:
        self.events: list[tuple[str | None, str]] = []
        self.persisted: list[tuple[str, str, dict | None]] = []

    async def append(self, event: str | None, data: str) -> int:
        self.events.append((event, data))
        return len(self.events)

    async def persist(self, state) -> None:
        self.persisted.append((state.response_id or '', state.effective_status, state.response_json))


def test_append_sse_chunk_decodes_blocks_incrementally() -> None:
    async def _run() -> None:
        decoder = SSEBlockDecoder()
        seen: list[tuple[str | None, str]] = []

        async def _persist(event: str | None, data: str) -> None:
            seen.append((event, data))

        await append_sse_chunk(
            chunk=(
                b"event: response.created\n"
                b'data: {"type":"response.created"}\n\n'
                b"event: response.completed\n"
                b'data: {"type":"response.completed","response":{"id":"resp_1","object":"response","status":"completed"}}\n\n'
            ),
            decoder=decoder,
            persist_block=_persist,
        )
        assert seen == [
            ("response.created", '{"type":"response.created"}'),
            ("response.completed", '{"type":"response.completed","response":{"id":"resp_1","object":"response","status":"completed"}}'),
        ]

    asyncio.run(_run())


def test_handle_persisted_sse_block_finalizes_completed_event() -> None:
    async def _run() -> None:
        rec = _Recorder()
        await handle_persisted_sse_block(
            response_id="resp_1",
            event="response.completed",
            data='{"type":"response.completed","response":{"id":"resp_1","object":"response","status":"completed"}}',
            fallback_model="gpt-4.1-mini",
            append_event=rec.append,
            persist_run_final=rec.persist,
        )
        assert rec.events[0][0] == "response.completed"
        assert rec.events[-1] == (None, "[DONE]")
        assert rec.persisted == [("resp_1", "completed", {"id": "resp_1", "object": "response", "status": "completed"})]

    asyncio.run(_run())


def test_build_response_event_appender_supports_dynamic_response_id() -> None:
    async def _run() -> None:
        writes: list[tuple[str, str | None, str]] = []
        seen_after: list[tuple[str, int]] = []
        response_id_box = ["resp_1"]

        async def _write(response_id: str, event: str | None, data: str) -> int:
            writes.append((response_id, event, data))
            return len(writes)

        async def _after(response_id: str, seq: int) -> None:
            seen_after.append((response_id, seq))

        append_event = build_response_event_appender(
            response_id_resolver=lambda: response_id_box[0],
            writer=_write,
            after_append=_after,
        )
        assert await append_event("response.completed", '{"id":"resp_1"}') == 1
        response_id_box[0] = "resp_2"
        assert await append_event(None, "[DONE]") == 2
        assert writes == [
            ("resp_1", "response.completed", '{"id":"resp_1"}'),
            ("resp_2", None, "[DONE]"),
        ]
        assert seen_after == [("resp_1", 1), ("resp_2", 2)]

    asyncio.run(_run())


def test_build_persisted_sse_block_handler_binds_context() -> None:
    async def _run() -> None:
        rec = _Recorder()
        append_event = build_response_event_appender(
            response_id="resp_bound",
            writer=lambda response_id, event, data: rec.append(event, data),
        )
        persist_block = build_persisted_sse_block_handler(
            response_id="resp_bound",
            fallback_model="gpt-4.1-mini",
            append_event=append_event,
            persist_run_final=rec.persist,
        )
        await persist_block(
            "response.completed",
            '{"type":"response.completed","response":{"id":"resp_bound","object":"response","status":"completed"}}',
        )
        assert rec.events[0][0] == "response.completed"
        assert rec.events[-1] == (None, "[DONE]")
        assert rec.persisted == [("resp_bound", "completed", {"id": "resp_bound", "object": "response", "status": "completed"})]

    asyncio.run(_run())


def test_normalize_forward_stream_block_rewrites_completed_response_id() -> None:
    event, data, completed = normalize_forward_stream_block(
        event="response.completed",
        data='{"type":"response.completed","response":{"id":"resp_old","object":"response","status":"completed"}}',
        canonical_response_id="resp_new",
    )
    assert event == "response.completed"
    assert completed == {"id": "resp_new", "object": "response", "status": "completed"}
    assert 'resp_new' in data
