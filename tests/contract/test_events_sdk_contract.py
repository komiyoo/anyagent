from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator

from anyagent.agent_api_client import Events
from anyagent.protocol.agent_api_internal import InternalEventItem, InternalEventsListResponse
from anyagent.protocol.sse import SSEBlock


class _FakeEvents(Events):
    def __init__(self, blocks: list[SSEBlock], *, list_pages: list[InternalEventsListResponse] | None = None) -> None:
        super().__init__(base_url="http://testserver", api_key="test-key", http=None)
        self._blocks = blocks
        self._list_pages = list(list_pages or [])

    async def stream(self, response_id: str, *, last_seq: int = 0) -> AsyncIterator[SSEBlock]:
        _ = response_id, last_seq
        for block in self._blocks:
            yield block

    async def list(self, response_id: str, *, last_seq: int = 0, limit: int = 200) -> InternalEventsListResponse:
        _ = response_id, last_seq, limit
        if not self._list_pages:
            raise AssertionError("unexpected list() call without prepared pages")
        return self._list_pages.pop(0)


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


def test_stream_typed_decodes_prompt_context_event_shape() -> None:
    async def _run() -> None:
        events = _FakeEvents(
            [
                SSEBlock(
                    id="13",
                    event="anyagent.prompt.context",
                    data='{"response_id":"resp_1","prompt_cache_key":"cache_1","fragments":[{"kind":"agents_instructions","cache_class":"stable_prefix","stable_id":"agents://main","source_path":"/repo/AGENTS.md","source_hash":"abc"},{"kind":"environment_context","cache_class":"contextual","stable_id":"environment://runtime"}],"ts_ms":333}',
                ),
                SSEBlock(id="14", event=None, data="[DONE]"),
            ]
        )

        seen = []
        async for item in events.stream_typed("resp_1", include_model_events=False):
            seen.append(item)

        assert [item.type for item in seen] == ["anyagent.prompt.context", "anyagent.done"]
        assert seen[0].seq == 13
        assert seen[0].prompt_cache_key == "cache_1"
        assert seen[0].fragments[0].kind == "agents_instructions"
        assert seen[0].fragments[1].cache_class == "contextual"
        assert seen[1].seq == 14

    asyncio.run(_run())


def test_stream_typed_decodes_prompt_context_rendered_event_shape() -> None:
    async def _run() -> None:
        events = _FakeEvents(
            [
                SSEBlock(
                    id="15",
                    event="anyagent.prompt.context.rendered",
                    data='{"response_id":"resp_1","prompt_cache_key":"cache_1","fragments":[{"kind":"agents_instructions","role":"developer","cache_class":"stable_prefix","label":"AGENTS.md","stable_id":"agents://main","rendered_text":"Use repo rules."}],"total_chars":15,"ts_ms":444}',
                ),
                SSEBlock(id="16", event=None, data="[DONE]"),
            ]
        )

        seen = []
        async for item in events.stream_typed("resp_1", include_model_events=False):
            seen.append(item)

        assert [item.type for item in seen] == ["anyagent.prompt.context.rendered", "anyagent.done"]
        assert seen[0].seq == 15
        assert seen[0].prompt_cache_key == "cache_1"
        assert seen[0].total_chars == 15
        assert seen[0].fragments[0].rendered_text == "Use repo rules."
        assert seen[1].seq == 16

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


def test_stream_typed_keeps_response_created_and_completed_payloads_when_including_model_events() -> None:
    async def _run() -> None:
        events = _FakeEvents(
            [
                SSEBlock(
                    id="21",
                    event="response.created",
                    data='{"type":"response.created","response":{"id":"resp_21","object":"response","model":"gpt-4o-mini","output":[],"parallel_tool_calls":false,"tool_choice":"auto","tools":[]}}',
                ),
                SSEBlock(
                    id="22",
                    event="response.completed",
                    data='{"type":"response.completed","response":{"id":"resp_21","object":"response","status":"completed","model":"gpt-4o-mini","output":[],"parallel_tool_calls":false,"tool_choice":"auto","tools":[]}}',
                ),
                SSEBlock(id="23", event=None, data="[DONE]"),
            ]
        )

        seen = []
        async for item in events.stream_typed("resp_21", include_model_events=True):
            seen.append(item)

        assert [item.type for item in seen] == [
            "anyagent.model.stream_event",
            "anyagent.model.stream_event",
            "anyagent.done",
        ]
        assert seen[0].seq == 21
        assert seen[0].sse_event == "response.created"
        assert seen[0].payload["response"]["id"] == "resp_21"
        assert seen[1].seq == 22
        assert seen[1].sse_event == "response.completed"
        assert seen[1].payload["response"]["status"] == "completed"
        assert seen[2].seq == 23

    asyncio.run(_run())


def test_stream_typed_keeps_delta_and_output_item_payloads_with_non_numeric_ids() -> None:
    async def _run() -> None:
        events = _FakeEvents(
            [
                SSEBlock(
                    id="delta-1",
                    event="response.output_text.delta",
                    data='{"type":"response.output_text.delta","sequence_number":1,"item_id":"msg_1","output_index":0,"content_index":0,"delta":"hel","logprobs":[]}',
                ),
                SSEBlock(
                    id="24",
                    event="response.output_item.done",
                    data='{"type":"response.output_item.done","sequence_number":2,"output_index":0,"item":{"id":"msg_1","type":"message","role":"assistant","status":"completed","content":[{"type":"output_text","text":"hello","annotations":[]}]}}',
                ),
                SSEBlock(id="25", event=None, data="[DONE]"),
            ]
        )

        seen = []
        async for item in events.stream_typed("resp_delta_1", include_model_events=True):
            seen.append(item)

        assert [item.type for item in seen] == [
            "anyagent.model.stream_event",
            "anyagent.model.stream_event",
            "anyagent.done",
        ]
        assert seen[0].seq is None
        assert seen[0].sse_event == "response.output_text.delta"
        assert seen[0].payload["delta"] == "hel"
        assert seen[1].seq == 24
        assert seen[1].sse_event == "response.output_item.done"
        assert seen[1].payload["item"]["id"] == "msg_1"
        assert seen[2].seq == 25

    asyncio.run(_run())


def test_stream_typed_wraps_flat_error_payload_shape() -> None:
    async def _run() -> None:
        events = _FakeEvents(
            [
                SSEBlock(
                    id="31",
                    event="error",
                    data='{"type":"error","sequence_number":9,"code":"server_error","message":"boom","param":"input"}',
                ),
                SSEBlock(id="32", event=None, data="[DONE]"),
            ]
        )

        seen = []
        async for item in events.stream_typed("resp_error_1", include_model_events=True):
            seen.append(item)

        assert [item.type for item in seen] == ["anyagent.model.stream_event", "anyagent.done"]
        assert seen[0].seq == 31
        assert seen[0].sse_event == "error"
        assert seen[0].payload["type"] == "error"
        assert seen[0].payload["message"] == "boom"
        assert seen[1].seq == 32

    asyncio.run(_run())


def test_list_typed_decodes_prompt_context_page_shape() -> None:
    async def _run() -> None:
        events = _FakeEvents(
            [],
            list_pages=[
                InternalEventsListResponse(
                    response_id="resp_list_1",
                    requested_last_seq=0,
                    next_last_seq=14,
                    done=True,
                    events=[
                        InternalEventItem(
                            seq=13,
                            event="anyagent.prompt.context",
                            data='{"response_id":"resp_list_1","prompt_cache_key":"cache_1","fragments":[{"kind":"agents_instructions","cache_class":"stable_prefix"},{"kind":"environment_context","cache_class":"contextual"}],"ts_ms":333}',
                        ),
                        InternalEventItem(seq=14, event=None, data="[DONE]"),
                    ],
                )
            ],
        )

        seen = await events.list_typed("resp_list_1", include_model_events=False)

        assert [item.type for item in seen] == ["anyagent.prompt.context", "anyagent.done"]
        assert seen[0].prompt_cache_key == "cache_1"
        assert seen[1].seq == 14

    asyncio.run(_run())


def test_latest_prompt_context_scans_paginated_list_pages() -> None:
    async def _run() -> None:
        events = _FakeEvents(
            [],
            list_pages=[
                InternalEventsListResponse(
                    response_id="resp_list_scan",
                    requested_last_seq=0,
                    next_last_seq=2,
                    done=False,
                    events=[
                        InternalEventItem(seq=1, event="response.created", data='{"type":"response.created","response":{"id":"resp_list_scan","object":"response","output":[],"parallel_tool_calls":false,"tool_choice":"auto","tools":[]}}'),
                        InternalEventItem(seq=2, event="anyagent.prompt.context", data='{"response_id":"resp_list_scan","prompt_cache_key":"cache_a","fragments":[{"kind":"agents_instructions","cache_class":"stable_prefix"}],"ts_ms":111}'),
                    ],
                ),
                InternalEventsListResponse(
                    response_id="resp_list_scan",
                    requested_last_seq=2,
                    next_last_seq=5,
                    done=True,
                    events=[
                        InternalEventItem(seq=3, event="anyagent.tool.planned", data='{"response_id":"resp_list_scan","tool_call_id":"call_1","tool_name":"exec","arguments":{"bytes":2,"sha256":"ab","preview":null,"preview_truncated":false},"ts_ms":222}'),
                        InternalEventItem(seq=4, event="anyagent.prompt.context", data='{"response_id":"resp_list_scan","prompt_cache_key":"cache_b","fragments":[{"kind":"environment_context","cache_class":"contextual"}],"ts_ms":333}'),
                        InternalEventItem(seq=5, event=None, data="[DONE]"),
                    ],
                ),
            ],
        )

        prompt_context = await events.latest_prompt_context("resp_list_scan")

        assert prompt_context is not None
        assert prompt_context.seq == 4
        assert prompt_context.prompt_cache_key == "cache_b"
        assert prompt_context.fragments[0].kind == "environment_context"

    asyncio.run(_run())


def test_replay_summary_aggregates_prompt_context_and_page_counts() -> None:
    async def _run() -> None:
        events = _FakeEvents(
            [],
            list_pages=[
                InternalEventsListResponse(
                    response_id="resp_replay_summary",
                    requested_last_seq=0,
                    next_last_seq=2,
                    done=False,
                    events=[
                        InternalEventItem(seq=1, event="response.created", data='{"type":"response.created","response":{"id":"resp_replay_summary","object":"response","output":[],"parallel_tool_calls":false,"tool_choice":"auto","tools":[]}}'),
                        InternalEventItem(seq=2, event="anyagent.prompt.context", data='{"response_id":"resp_replay_summary","prompt_cache_key":"cache_a","fragments":[{"kind":"agents_instructions","cache_class":"stable_prefix"}],"fragment_count":1,"retained_fragment_count":1,"stable_prefix_count":1,"contextual_count":0,"dynamic_count":0,"fragment_kinds":["agents_instructions"],"compacted":false,"ts_ms":111}'),
                    ],
                ),
                InternalEventsListResponse(
                    response_id="resp_replay_summary",
                    requested_last_seq=2,
                    next_last_seq=4,
                    done=True,
                    effective_run_status="completed",
                    events=[
                        InternalEventItem(seq=3, event="anyagent.prompt.context", data='{"response_id":"resp_replay_summary","prompt_cache_key":"cache_b","fragments":[{"kind":"environment_context","cache_class":"contextual"}],"fragment_count":1,"retained_fragment_count":1,"stable_prefix_count":0,"contextual_count":1,"dynamic_count":0,"fragment_kinds":["environment_context"],"compacted":false,"ts_ms":222}'),
                        InternalEventItem(seq=4, event=None, data="[DONE]"),
                    ],
                ),
            ],
        )

        summary = await events.replay_summary("resp_replay_summary")

        assert summary.response_id == "resp_replay_summary"
        assert summary.scanned_pages == 2
        assert summary.page_event_count == 4
        assert summary.typed_event_count == 3
        assert summary.done is True
        assert summary.effective_run_status == "completed"
        assert summary.prompt_context is not None
        assert summary.prompt_context.prompt_cache_key == "cache_b"
        assert summary.prompt_context.fragment_kinds == ["environment_context"]

    asyncio.run(_run())
