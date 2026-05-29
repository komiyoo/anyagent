from __future__ import annotations

import asyncio
import time

from openai.types.responses.response import Response
from openai.types.responses.response_output_message import ResponseOutputMessage
from openai.types.responses.response_output_text import ResponseOutputText

from anyagent.agent_runtime.middleware import MiddlewareContext
from anyagent.agent_runtime.middlewares.context_compaction import ContextCompactionMiddleware


def test_context_compaction_compacts_stateless_input_without_splitting_tool_pairs() -> None:
    asyncio.run(_run_context_compaction_compacts_stateless_input_without_splitting_tool_pairs())


async def _run_context_compaction_compacts_stateless_input_without_splitting_tool_pairs() -> None:
    events = []

    async def _sink(event):
        events.append(event)

    middleware = ContextCompactionMiddleware(max_context_tokens=100, trigger_ratio=0.5, keep_recent_tokens=20)
    provider = _SummaryProvider()
    context = MiddlewareContext(
        agent_id="main",
        session_key="s1",
        iter_index=2,
        response_id="resp_1",
        canonical_response_id="resp_parent",
        stage_event_sink=_sink,
        model_provider=provider,
    )
    body = {
        "input": [
            {"role": "user", "content": "old " * 200},
            {"type": "function_call", "call_id": "call_1", "name": "read_file", "arguments": "{}"},
            {"type": "function_call_output", "call_id": "call_1", "output": "result"},
            {"role": "user", "content": "recent"},
        ]
    }

    result = await middleware.before_model_call(context, body)

    assert result.body is not None
    compacted_items = result.body["input"]
    assert compacted_items[0]["role"] == "developer"
    assert compacted_items[1]["type"] == "function_call"
    assert compacted_items[2]["type"] == "function_call_output"
    assert compacted_items[1]["call_id"] == compacted_items[2]["call_id"]
    assert events[0].type == "anyagent.context.compacted"
    assert events[0].items_before == 4
    assert events[0].items_after == 4
    assert provider.bodies[0]["stream"] is False
    assert "model summary" in compacted_items[0]["content"]


def test_context_compaction_skips_stateful_followup() -> None:
    asyncio.run(_run_context_compaction_skips_stateful_followup())


async def _run_context_compaction_skips_stateful_followup() -> None:
    events = []

    async def _sink(event):
        events.append(event)

    middleware = ContextCompactionMiddleware(max_context_tokens=10, trigger_ratio=0.5, keep_recent_tokens=1)
    context = MiddlewareContext(
        agent_id="main",
        session_key="s1",
        iter_index=1,
        response_id="resp_1",
        canonical_response_id="resp_parent",
        stage_event_sink=_sink,
    )

    result = await middleware.before_model_call(
        context,
        {"previous_response_id": "resp_1", "input": [{"role": "user", "content": "x" * 100}]},
    )

    assert result.body is None
    assert events[0].skipped is True
    assert events[0].reason == "stateful"


class _SummaryProvider:
    def __init__(self) -> None:
        self.bodies = []

    async def create_response(self, *, body, idempotency_key=None, timeout_s=60.0):  # type: ignore[no-untyped-def]
        _ = idempotency_key, timeout_s
        self.bodies.append(dict(body))
        return Response.model_validate(
            {
                "id": "resp_summary",
                "object": "response",
                "created_at": int(time.time()),
                "model": str(body.get("model") or "gpt-test"),
                "output": [
                    ResponseOutputMessage(
                        id="msg_summary",
                        type="message",
                        role="assistant",
                        status="completed",
                        content=[ResponseOutputText(type="output_text", text="model summary", annotations=[])],
                    ).model_dump(exclude_none=True, by_alias=True)
                ],
                "parallel_tool_calls": False,
                "tool_choice": "auto",
                "tools": [],
                "status": "completed",
            }
        )
