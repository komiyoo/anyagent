from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator

from anyagent.agent_api_client import Events
from anyagent.protocol.sse import SSEBlock


class _FakeEvents(Events):
    def __init__(self, blocks: list[SSEBlock]) -> None:
        super().__init__(base_url="http://testserver", api_key="test-key", http=None)
        self._blocks = blocks

    async def stream(self, response_id: str, *, last_seq: int = 0) -> AsyncIterator[SSEBlock]:
        _ = response_id, last_seq
        for block in self._blocks:
            yield block


def test_stream_typed_decodes_stage_model_event_and_done() -> None:
    async def _run() -> None:
        events = _FakeEvents(
            [
                SSEBlock(
                    id="5",
                    event="anyagent.tool.planned",
                    data='{"response_id":"resp_1","tool_call_id":"call_1","tool_name":"exec","arguments":{"bytes":2,"sha256":"ab","preview":null,"preview_truncated":false},"trace_id":"trace_1","ts_ms":111}',
                ),
                SSEBlock(id="6", event=None, data="[DONE]"),
            ]
        )

        seen = []
        async for item in events.stream_typed("resp_1", include_model_events=False):
            seen.append(item)

        assert [item.type for item in seen] == ["anyagent.tool.planned", "anyagent.done"]
        assert seen[0].seq == 5
        assert seen[0].trace_id == "trace_1"
        assert seen[1].seq == 6

    asyncio.run(_run())


def test_stream_typed_wraps_openai_model_events_and_filters_when_requested() -> None:
    async def _run() -> None:
        blocks = [
            SSEBlock(
                id="8",
                event="response.completed",
                data='{"type":"response.completed","response":{"id":"resp_1","object":"response","status":"completed"}}',
            ),
            SSEBlock(id="9", event=None, data="[DONE]"),
        ]
        events = _FakeEvents(blocks)

        with_model = []
        async for item in events.stream_typed("resp_1", include_model_events=True):
            with_model.append(item.type)

        without_model = []
        async for item in events.stream_typed("resp_1", include_model_events=False):
            without_model.append(item.type)

        assert with_model == ["anyagent.model.stream_event", "anyagent.done"]
        assert without_model == ["anyagent.done"]

    asyncio.run(_run())


def test_stream_typed_decodes_command_result_event_shape() -> None:
    async def _run() -> None:
        events = _FakeEvents(
            [
                SSEBlock(
                    id="11",
                    event="anyagent.command.result",
                    data='{"response_id":"resp_1","source_tool_call_id":"call_1","source_tool_name":"exec","exit_code":7,"duration_ms":42,"stdout":{"bytes":0,"sha256":"stdout","preview":null,"preview_truncated":false},"stderr":{"bytes":4,"sha256":"stderr","preview":"boom","preview_truncated":false},"ts_ms":222}',
                ),
                SSEBlock(id="12", event=None, data="[DONE]"),
            ]
        )

        seen = []
        async for item in events.stream_typed("resp_1", include_model_events=False):
            seen.append(item)

        assert [item.type for item in seen] == ["anyagent.command.result", "anyagent.done"]
        assert seen[0].seq == 11
        assert seen[0].exit_code == 7
        assert seen[0].stderr.preview == "boom"
        assert seen[1].seq == 12

    asyncio.run(_run())


def test_stream_typed_wraps_error_events_and_skips_invalid_payloads() -> None:
    async def _run() -> None:
        events = _FakeEvents(
            [
                SSEBlock(id="bad", event="anyagent.tool.planned", data="not-json"),
                SSEBlock(id="14", event="response.output_text.delta", data='["skip-me"]'),
                SSEBlock(id="15", event="error", data='{"error":{"message":"boom","type":"server_error"}}'),
                SSEBlock(id="16", event=None, data="[DONE]"),
            ]
        )

        seen = []
        async for item in events.stream_typed("resp_1", include_model_events=True):
            seen.append(item)

        assert [item.type for item in seen] == ["anyagent.model.stream_event", "anyagent.done"]
        assert seen[0].seq == 15
        assert seen[0].sse_event == "error"
        assert seen[0].payload == {"error": {"message": "boom", "type": "server_error"}}
        assert seen[1].seq == 16

    asyncio.run(_run())
