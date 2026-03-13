from __future__ import annotations

import asyncio

from anyagent.protocol.sse import SSEBlockDecoder
from anyagent.server.streaming import (
    append_sse_chunk,
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


def test_normalize_forward_stream_block_rewrites_completed_response_id() -> None:
    event, data, completed = normalize_forward_stream_block(
        event="response.completed",
        data='{"type":"response.completed","response":{"id":"resp_old","object":"response","status":"completed"}}',
        canonical_response_id="resp_new",
    )
    assert event == "response.completed"
    assert completed == {"id": "resp_new", "object": "response", "status": "completed"}
    assert 'resp_new' in data
