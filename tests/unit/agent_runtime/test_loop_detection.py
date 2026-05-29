from __future__ import annotations

import asyncio
import json

from openai.types.responses.response_function_tool_call import ResponseFunctionToolCall

from anyagent.agent_runtime.middleware import MiddlewareContext
from anyagent.agent_runtime.middlewares.loop_detection import LoopDetectionMiddleware, tool_call_signature


def test_loop_detection_warns_and_terminates_repeated_tool_calls() -> None:
    asyncio.run(_run_loop_detection_warns_and_terminates_repeated_tool_calls())


async def _run_loop_detection_warns_and_terminates_repeated_tool_calls() -> None:
    events = []

    async def _sink(event):
        events.append(event)

    middleware = LoopDetectionMiddleware(window_size=20, warn_threshold=3, hard_limit=5)
    context = MiddlewareContext(
        agent_id="main",
        session_key="s1",
        iter_index=1,
        response_id="resp_1",
        canonical_response_id="resp_parent",
        stage_event_sink=_sink,
    )
    call = _call("read_file", {"path": "README.md", "start_line": 215})

    for _ in range(4):
        result = await middleware.after_model_call(context, response=None, calls=[call])  # type: ignore[arg-type]
        assert result.suppress_calls is False
    result = await middleware.after_model_call(context, response=None, calls=[call])  # type: ignore[arg-type]

    assert result.suppress_calls is True
    assert [event.type for event in events] == [
        "anyagent.agent.loop_warning",
        "anyagent.agent.loop_warning",
        "anyagent.agent.loop_terminated",
    ]
    assert events[-1].repeat_count == 5


def test_loop_detection_read_file_signature_buckets_line_numbers() -> None:
    near = tool_call_signature(_call("read_file", {"path": "README.md", "start_line": 201}))
    same_bucket = tool_call_signature(_call("read_file", {"path": "README.md", "start_line": 399}))
    other_bucket = tool_call_signature(_call("read_file", {"path": "README.md", "start_line": 401}))

    assert near == same_bucket
    assert near != other_bucket


def _call(name: str, arguments: dict) -> ResponseFunctionToolCall:
    return ResponseFunctionToolCall(
        type="function_call",
        call_id="call_1",
        name=name,
        arguments=json.dumps(arguments),
    )

