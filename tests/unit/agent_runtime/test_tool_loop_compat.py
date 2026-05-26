from __future__ import annotations

import asyncio
import json
import time
from typing import Any

from openai.types.responses.response import Response
from openai.types.responses.response_function_tool_call import ResponseFunctionToolCall
from openai.types.responses.response_output_message import ResponseOutputMessage
from openai.types.responses.response_output_text import ResponseOutputText

from anyagent.agent_runtime.model_providers import ModelProviderUpstreamError
from anyagent.agent_runtime.tool_loop import run_tool_loop_nonstream
from anyagent.protocol.openai_responses import AnyAgentFunctionToolParam
from anyagent.protocol.tool_runtime import ExecuteMeta, ExecuteResponseCompleted, ManifestResponse, ToolContext


class _ToolRuntime:
    async def manifest(self, req: Any) -> ManifestResponse:
        _ = req
        return ManifestResponse(
            tools=[
                AnyAgentFunctionToolParam(
                    type="function",
                    name="demo.lookup",
                    description="lookup",
                    parameters={"type": "object", "properties": {}},
                )
            ],
            toolset_version=1,
        )

    async def execute(self, req: Any) -> dict[str, Any]:
        _ = req
        return ExecuteResponseCompleted(status="completed", output="lookup result", meta=ExecuteMeta())


class _Provider:
    def __init__(self) -> None:
        self.bodies: list[dict[str, Any]] = []

    async def create_response(self, *, body: dict[str, Any], idempotency_key: str | None = None, timeout_s: float = 60.0) -> Response:
        _ = idempotency_key, timeout_s
        self.bodies.append(dict(body))
        if len(self.bodies) == 1:
            return Response.model_validate(
                {
                    "id": "resp_first",
                    "object": "response",
                    "created_at": int(time.time()),
                    "model": str(body.get("model") or "gpt-test"),
                    "output": [
                        ResponseFunctionToolCall(
                            type="function_call",
                            call_id="call_lookup",
                            name="demo_lookup",
                            arguments=json.dumps({"query": "x"}),
                        ).model_dump(exclude_none=True, by_alias=True)
                    ],
                    "parallel_tool_calls": False,
                    "tool_choice": "auto",
                    "tools": list(body.get("tools") or []),
                }
            )
        if len(self.bodies) == 2:
            raise ModelProviderUpstreamError(
                status_code=400,
                body={
                    "code": "InvalidParameter.PreviousResponseNotFound",
                    "message": "Previous response with id resp_first not found.",
                    "param": "previous_response_id",
                    "type": "BadRequest",
                },
            )
        return Response.model_validate(
            {
                "id": "resp_final",
                "object": "response",
                "created_at": int(time.time()),
                "model": str(body.get("model") or "gpt-test"),
                "output": [
                    ResponseOutputMessage(
                        id="msg_done",
                        type="message",
                        role="assistant",
                        status="completed",
                        content=[ResponseOutputText(type="output_text", text="done", annotations=[])],
                    ).model_dump(exclude_none=True, by_alias=True)
                ],
                "parallel_tool_calls": False,
                "tool_choice": "auto",
                "tools": list(body.get("tools") or []),
                "status": "completed",
            }
        )


def test_nonstream_tool_loop_retries_previous_response_not_found_stateless() -> None:
    asyncio.run(_run_nonstream_tool_loop_retries_previous_response_not_found_stateless())


async def _run_nonstream_tool_loop_retries_previous_response_not_found_stateless() -> None:
    provider = _Provider()
    status, payload = await run_tool_loop_nonstream(
        model_provider=provider,  # type: ignore[arg-type]
        tool_runtime=_ToolRuntime(),  # type: ignore[arg-type]
        agent_id="main",
        session_key="s1",
        body={"input": "hello", "model": "gpt-test", "metadata": {"agent_id": "main"}},
        idempotency_key=None,
        tool_context=ToolContext(),
    )

    assert status == 200
    assert payload["id"] == "resp_first"
    assert payload["output"][0]["content"][0]["text"] == "done"
    assert len(provider.bodies) == 3
    assert "metadata" not in provider.bodies[0]
    assert provider.bodies[1]["previous_response_id"] == "resp_first"
    assert "metadata" not in provider.bodies[1]
    assert "previous_response_id" not in provider.bodies[2]
    assert [item["type"] for item in provider.bodies[2]["input"]] == ["function_call", "function_call_output"]
