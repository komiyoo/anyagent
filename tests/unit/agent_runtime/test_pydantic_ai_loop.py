from __future__ import annotations

import asyncio
import json
from typing import Any

from openai.types.responses.response import Response
from openai.types.responses.response_function_tool_call import ResponseFunctionToolCall
from pydantic_ai.messages import ModelMessage, ModelRequest, ModelResponse, TextPart, ToolCallPart, UserPromptPart
from pydantic_ai.models import Model, ModelRequestParameters
from pydantic_ai.settings import ModelSettings

from anyagent.agent_runtime.loop import pydantic_ai_model_id
from anyagent.agent_runtime.tool_loop import run_tool_loop_nonstream, run_tool_loop_stream_live
from anyagent.model_config import ModelConfigError
from anyagent.protocol.openai_responses import AnyAgentFunctionToolParam
from anyagent.protocol.sse import parse_sse_events
from anyagent.protocol.tool_runtime import ExecuteMeta, ExecuteResponseCompleted, ManifestResponse, ToolContext


class _ToolRuntime:
    def __init__(self) -> None:
        self.execute_calls: list[dict[str, Any]] = []

    async def manifest(self, req: Any) -> ManifestResponse:
        _ = req
        return ManifestResponse(
            tools=[
                AnyAgentFunctionToolParam(
                    type="function",
                    name="demo.lookup",
                    description="lookup",
                    parameters={"type": "object", "properties": {"query": {"type": "string"}}},
                )
            ],
            toolset_version=1,
        )

    async def execute(self, req: Any) -> ExecuteResponseCompleted:
        self.execute_calls.append(
            {
                "tool_name": req.tool_name,
                "arguments_json": req.arguments_json,
            }
        )
        return ExecuteResponseCompleted(status="completed", output="lookup result", meta=ExecuteMeta())


class _EmptyOutputProvider:
    """Hosted smoke: model completes with empty output (no text, no tools)."""

    def __init__(self) -> None:
        self.calls = 0

    async def create_response(
        self,
        *,
        body: dict[str, Any],
        idempotency_key: str | None = None,
        timeout_s: float = 60.0,
    ) -> Response:
        _ = idempotency_key, timeout_s
        self.calls += 1
        return Response.model_validate(
            {
                "id": "resp_empty_output",
                "object": "response",
                "created_at": 123,
                "model": str(body.get("model") or "gpt-test"),
                "output": [],
                "parallel_tool_calls": False,
                "tool_choice": "auto",
                "tools": list(body.get("tools") or []),
                "status": "completed",
            }
        )


class _UnknownToolCallProvider:
    """Hosted smoke: model returns a function_call for a tool that is not in the manifest."""

    def __init__(self) -> None:
        self.calls = 0

    async def create_response(
        self,
        *,
        body: dict[str, Any],
        idempotency_key: str | None = None,
        timeout_s: float = 60.0,
    ) -> Response:
        _ = idempotency_key, timeout_s
        self.calls += 1
        return Response.model_validate(
            {
                "id": "resp_unknown_tool",
                "object": "response",
                "created_at": 123,
                "model": str(body.get("model") or "gpt-test"),
                "output": [
                    ResponseFunctionToolCall(
                        id="fc_orphan",
                        call_id="call_orphan",
                        name="core_web_search",
                        arguments='{"q": "test"}',
                        type="function_call",
                    ).model_dump(exclude_none=True, by_alias=True),
                ],
                "parallel_tool_calls": False,
                "tool_choice": "auto",
                "tools": list(body.get("tools") or []),
                "status": "completed",
            }
        )


class _RecordingModel(Model):
    """Offline pydantic-ai Model that records instructions and emits one tool call then text."""

    def __init__(self) -> None:
        super().__init__()
        self.instructions: list[str] = []
        self.calls = 0
        self.first_request_messages: list[ModelMessage] = []

    @property
    def model_name(self) -> str:
        return "recording"

    @property
    def system(self) -> str:
        return "test"

    async def request(
        self,
        messages: list[ModelMessage],
        model_settings: ModelSettings | None,
        model_request_parameters: ModelRequestParameters,
    ) -> ModelResponse:
        _ = model_settings, model_request_parameters
        self.calls += 1
        if self.calls == 1:
            self.first_request_messages = list(messages)
        for message in messages:
            instructions = getattr(message, "instructions", None)
            if isinstance(instructions, str) and instructions.strip():
                self.instructions.append(instructions)
        if self.calls == 1:
            return ModelResponse(
                parts=[ToolCallPart(tool_name="demo_lookup", args={"query": "x"}, tool_call_id="call_lookup")],
                model_name=self.model_name,
            )
        return ModelResponse(parts=[TextPart(content="done")], model_name=self.model_name)


def test_pydantic_ai_model_id_fail_fast_unmapped_kind() -> None:
    try:
        pydantic_ai_model_id(provider_kind="no-such-kind", model="gpt-x")
    except ModelConfigError as exc:
        assert "unmapped" in str(exc)
        return
    raise AssertionError("expected ModelConfigError")


def test_pydantic_ai_model_id_fail_fast_missing_model() -> None:
    try:
        pydantic_ai_model_id(provider_kind="openai", model=None)
    except ModelConfigError as exc:
        assert "missing model id" in str(exc)
        return
    raise AssertionError("expected ModelConfigError")


def test_run_tool_loop_nonstream_injects_envelope_and_executes_tool() -> None:
    asyncio.run(_run_tool_loop_nonstream_injects_envelope_and_executes_tool())


async def _run_tool_loop_nonstream_injects_envelope_and_executes_tool() -> None:
    model = _RecordingModel()
    runtime = _ToolRuntime()
    envelope = "# AGENTS.md instructions for agent:main\nYou are the main agent.\n# source: agents/main/AGENTS.md hash=abc"
    status, payload = await run_tool_loop_nonstream(
        model_provider=model,
        tool_runtime=runtime,  # type: ignore[arg-type]
        agent_id="main",
        session_key="sess-1",
        body={
            "model": "gpt-test",
            "input": [
                {"role": "developer", "content": envelope},
                {"role": "user", "content": "hello"},
            ],
        },
        idempotency_key=None,
        tool_context=ToolContext(),
        canonical_response_id="resp_unit_1",
    )
    assert status == 200
    assert payload["id"] == "resp_unit_1"
    assert payload["status"] == "completed"
    assert payload["output"][0]["content"][0]["text"] == "done"
    assert any(envelope in item for item in model.instructions), model.instructions
    assert runtime.execute_calls, "Tool Runtime execute must be called"
    assert runtime.execute_calls[0]["tool_name"] == "demo.lookup"


def _user_prompt_texts(messages: list[ModelMessage]) -> list[str]:
    texts: list[str] = []
    for message in messages:
        if not isinstance(message, ModelRequest):
            continue
        for part in message.parts:
            if isinstance(part, UserPromptPart) and isinstance(part.content, str):
                texts.append(part.content)
    return texts


def _assistant_texts(messages: list[ModelMessage]) -> list[str]:
    texts: list[str] = []
    for message in messages:
        if not isinstance(message, ModelResponse):
            continue
        if isinstance(message.text, str) and message.text:
            texts.append(message.text)
    return texts


def test_run_tool_loop_nonstream_sends_current_user_once() -> None:
    asyncio.run(_run_tool_loop_nonstream_sends_current_user_once())


async def _run_tool_loop_nonstream_sends_current_user_once() -> None:
    model = _RecordingModel()
    runtime = _ToolRuntime()
    envelope = "# AGENTS.md instructions for agent:main\nhash=abc"
    status, payload = await run_tool_loop_nonstream(
        model_provider=model,
        tool_runtime=runtime,  # type: ignore[arg-type]
        agent_id="main",
        session_key="sess-hist",
        body={
            "model": "gpt-test",
            "input": [
                {"role": "developer", "content": envelope},
                {"role": "user", "content": "first turn"},
                {
                    "role": "assistant",
                    "content": [{"type": "output_text", "text": "old reply"}],
                },
                {"role": "user", "content": "second turn"},
            ],
        },
        idempotency_key=None,
        tool_context=ToolContext(),
        canonical_response_id="resp_hist_1",
    )
    assert status == 200, payload
    user_texts = _user_prompt_texts(model.first_request_messages)
    assert user_texts.count("second turn") == 1, user_texts
    assert user_texts.count("first turn") == 1, user_texts
    assert "old reply" in _assistant_texts(model.first_request_messages)
    assert envelope not in user_texts


def test_run_tool_loop_stream_live_ends_with_done() -> None:
    asyncio.run(_run_tool_loop_stream_live_ends_with_done())


async def _run_tool_loop_stream_live_ends_with_done() -> None:
    model = _RecordingModel()
    runtime = _ToolRuntime()
    chunks: list[bytes] = []
    async for chunk in run_tool_loop_stream_live(
        model_provider=model,
        tool_runtime=runtime,  # type: ignore[arg-type]
        agent_id="main",
        session_key="sess-stream",
        body={"model": "gpt-test", "input": "hello"},
        idempotency_key=None,
        tool_context=ToolContext(),
        canonical_response_id="resp_unit_stream",
    ):
        chunks.append(chunk)
    text = b"".join(chunks).decode("utf-8")
    events = parse_sse_events(text)
    assert any(data == "[DONE]" for event, data in events if event is None), events
    assert "response.completed" in [event for event, _ in events]
    assert runtime.execute_calls
    assert runtime.execute_calls[0]["tool_name"] == "demo.lookup"


def test_run_tool_loop_nonstream_unmapped_handle_fails_fast() -> None:
    asyncio.run(_run_tool_loop_nonstream_unmapped_handle_fails_fast())


async def _run_tool_loop_nonstream_unmapped_handle_fails_fast() -> None:
    from anyagent.agent_runtime.loop import PydanticAIModelHandle
    from anyagent.model_config import EffectiveModelSelection

    handle = PydanticAIModelHandle(
        selection=EffectiveModelSelection(provider_name="missing", provider_kind="openai", model=None),
    )
    runtime = _ToolRuntime()
    status, payload = await run_tool_loop_nonstream(
        model_provider=handle,
        tool_runtime=runtime,  # type: ignore[arg-type]
        agent_id="main",
        session_key="s",
        body={"input": "hello"},
        idempotency_key=None,
        tool_context=ToolContext(),
    )
    assert status == 400
    assert payload["error"]["type"] == "invalid_request_error"
    assert "missing model id" in payload["error"]["message"]
    assert runtime.execute_calls == []


def test_run_tool_loop_nonstream_empty_output_is_completed_200() -> None:
    asyncio.run(_run_tool_loop_nonstream_empty_output_is_completed_200())


async def _run_tool_loop_nonstream_empty_output_is_completed_200() -> None:
    provider = _EmptyOutputProvider()
    runtime = _ToolRuntime()
    status, payload = await run_tool_loop_nonstream(
        model_provider=provider,  # type: ignore[arg-type]
        tool_runtime=runtime,  # type: ignore[arg-type]
        agent_id="main",
        session_key="sess-empty",
        body={"model": "gpt-test", "input": "hello"},
        idempotency_key=None,
        tool_context=ToolContext(),
        canonical_response_id="resp_empty_canonical",
    )
    assert status == 200, payload
    assert payload.get("status") == "completed"
    assert payload.get("output") == []
    assert payload.get("id") == "resp_empty_canonical"
    assert provider.calls == 1
    assert runtime.execute_calls == []


def test_run_tool_loop_nonstream_unknown_tool_call_is_completed_200() -> None:
    asyncio.run(_run_tool_loop_nonstream_unknown_tool_call_is_completed_200())


async def _run_tool_loop_nonstream_unknown_tool_call_is_completed_200() -> None:
    provider = _UnknownToolCallProvider()
    runtime = _ToolRuntime()
    status, payload = await run_tool_loop_nonstream(
        model_provider=provider,  # type: ignore[arg-type]
        tool_runtime=runtime,  # type: ignore[arg-type]
        agent_id="main",
        session_key="sess-unknown",
        body={"model": "gpt-test", "input": "search something"},
        idempotency_key=None,
        tool_context=ToolContext(),
        canonical_response_id="resp_unknown_canonical",
    )
    assert status == 200, payload
    output = payload.get("output") or []
    types = [item.get("type") for item in output if isinstance(item, dict)]
    assert "function_call" in types, payload
    assert payload.get("id") == "resp_unknown_canonical"
    assert not any(
        isinstance(item, dict) and item.get("type") == "message" and item.get("content")
        for item in output
    )
