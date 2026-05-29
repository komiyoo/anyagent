from __future__ import annotations

import asyncio
import json
import time
from pathlib import Path
from typing import Any

from openai.types.responses.response import Response
from openai.types.responses.response_function_tool_call import ResponseFunctionToolCall
from openai.types.responses.response_output_message import ResponseOutputMessage
from openai.types.responses.response_output_text import ResponseOutputText

from anyagent.agent_packs import AgentCatalog, AgentPack, AgentSpec
from anyagent.agent_runtime import SubAgentExecutor
from anyagent.agent_runtime import task_tool_schema
from anyagent.agent_runtime.tool_loop import run_tool_loop_nonstream
from anyagent.protocol.multi_agent import TaskArgs
from anyagent.protocol.openai_responses import AnyAgentFunctionToolParam
from anyagent.protocol.tool_runtime import ManifestResponse, ToolContext


def test_task_args_require_description_prompt_and_agent_id() -> None:
    args = TaskArgs.model_validate(
        {
            "description": "Summarize repository risks",
            "prompt": "Read the TODO list and return the highest-risk items.",
            "agent_id": "reviewer",
        }
    )

    assert args.description == "Summarize repository risks"
    assert args.prompt.startswith("Read the TODO")
    assert args.agent_id == "reviewer"


def test_task_tool_schema_is_strict_function_tool() -> None:
    dumped = task_tool_schema()

    assert dumped["name"] == "task"
    assert dumped["strict"] is True
    assert dumped["parameters"]["additionalProperties"] is False
    assert set(dumped["parameters"]["required"]) == {"description", "prompt", "agent_id"}


def test_subagent_executor_runs_child_agent_loop_with_independent_context() -> None:
    asyncio.run(_run_subagent_executor_runs_child_agent_loop_with_independent_context())


async def _run_subagent_executor_runs_child_agent_loop_with_independent_context() -> None:
    provider = _FinalTextProvider(text="child answer")
    result = await SubAgentExecutor().execute_task(
        catalog=_catalog(),
        parent_pack=_pack("main", allow=["worker"]),
        model_provider=provider,
        tool_runtime=_EmptyToolRuntime(),
        session_key="parent-session",
        parent_body={"model": "gpt-parent"},
        arguments_json={"description": "Delegate", "prompt": "Do the work", "agent_id": "worker"},
    )

    payload = json.loads(result)
    assert payload == {"agent_id": "worker", "output_text": "child answer"}
    assert provider.bodies[0]["input"][-1] == {"role": "user", "content": "Do the work"}
    assert provider.bodies[0]["model"] == "gpt-worker"
    assert "You are worker." in provider.bodies[0]["input"][0]["content"]


def test_tool_loop_dispatches_task_to_system_executor() -> None:
    asyncio.run(_run_tool_loop_dispatches_task_to_system_executor())


async def _run_tool_loop_dispatches_task_to_system_executor() -> None:
    provider = _TaskCallingProvider()
    calls: list[tuple[str, object]] = []

    async def _system_tool(tool_name: str, arguments_json: object) -> str:
        calls.append((tool_name, arguments_json))
        return json.dumps({"agent_id": "worker", "output_text": "delegated answer"})

    status, payload = await run_tool_loop_nonstream(
        model_provider=provider,  # type: ignore[arg-type]
        tool_runtime=_TaskManifestToolRuntime(),  # type: ignore[arg-type]
        agent_id="main",
        session_key="parent-session",
        body={"input": "parent", "model": "gpt-parent"},
        idempotency_key=None,
        tool_context=ToolContext(),
        system_tool_executor=_system_tool,
    )

    assert status == 200
    assert payload["output"][0]["content"][0]["text"] == "parent final"
    assert calls == [
        (
            "task",
            {"description": "Delegate", "prompt": "Do the work", "agent_id": "worker"},
        )
    ]
    assert provider.bodies[1]["input"][0]["type"] == "function_call_output"


class _EmptyToolRuntime:
    async def manifest(self, req: Any) -> ManifestResponse:
        _ = req
        return ManifestResponse(tools=[], toolset_version=1)

    async def execute(self, req: Any) -> Any:
        raise AssertionError(f"unexpected tool runtime execute: {req}")


class _TaskManifestToolRuntime(_EmptyToolRuntime):
    async def manifest(self, req: Any) -> ManifestResponse:
        _ = req
        return ManifestResponse(
            tools=[AnyAgentFunctionToolParam(**task_tool_schema())],
            toolset_version=1,
        )


class _FinalTextProvider:
    def __init__(self, *, text: str) -> None:
        self.text = text
        self.bodies: list[dict[str, Any]] = []

    async def create_response(self, *, body: dict[str, Any], idempotency_key: str | None = None, timeout_s: float = 60.0) -> Response:
        _ = idempotency_key, timeout_s
        self.bodies.append(dict(body))
        return _message_response(response_id="resp_child", model=str(body.get("model") or "gpt-test"), text=self.text)


class _TaskCallingProvider:
    def __init__(self) -> None:
        self.bodies: list[dict[str, Any]] = []

    async def create_response(self, *, body: dict[str, Any], idempotency_key: str | None = None, timeout_s: float = 60.0) -> Response:
        _ = idempotency_key, timeout_s
        self.bodies.append(dict(body))
        if len(self.bodies) == 1:
            return Response.model_validate(
                {
                    "id": "resp_parent_1",
                    "object": "response",
                    "created_at": int(time.time()),
                    "model": str(body.get("model") or "gpt-test"),
                    "output": [
                        ResponseFunctionToolCall(
                            type="function_call",
                            call_id="call_task",
                            name="task",
                            arguments=json.dumps(
                                {"description": "Delegate", "prompt": "Do the work", "agent_id": "worker"}
                            ),
                        ).model_dump(exclude_none=True, by_alias=True)
                    ],
                    "parallel_tool_calls": False,
                    "tool_choice": "auto",
                    "tools": list(body.get("tools") or []),
                }
            )
        return _message_response(response_id="resp_parent_2", model=str(body.get("model") or "gpt-test"), text="parent final")


def _message_response(*, response_id: str, model: str, text: str) -> Response:
    return Response.model_validate(
        {
            "id": response_id,
            "object": "response",
            "created_at": int(time.time()),
            "model": model,
            "output": [
                ResponseOutputMessage(
                    id=f"msg_{response_id}",
                    type="message",
                    role="assistant",
                    status="completed",
                    content=[ResponseOutputText(type="output_text", text=text, annotations=[])],
                ).model_dump(exclude_none=True, by_alias=True)
            ],
            "parallel_tool_calls": False,
            "tool_choice": "auto",
            "tools": [],
            "status": "completed",
        }
    )


def _catalog() -> AgentCatalog:
    return AgentCatalog(
        root_dir=Path("/tmp/anyagent-test"),
        packs={
            "main": _pack("main", allow=["worker"]),
            "worker": _pack("worker", model="gpt-worker"),
        },
    )


def _pack(agent_id: str, *, allow: list[str] | None = None, model: str = "gpt-test") -> AgentPack:
    return AgentPack(
        agent_id=agent_id,
        root_dir=Path(f"/tmp/anyagent-test/{agent_id}"),
        spec=AgentSpec.model_validate(
            {
                "exposed": True,
                "model": {"default": model},
                "tools": {"requested_tool_names": []},
                "skills": {"default_selected": [], "disabled_paths": []},
                "sandbox": {"mode": "local-unsafe"},
                "multiagent": {"spawn_allow_agent_ids": allow or []},
            }
        ),
        agents_md_path=Path(f"/tmp/anyagent-test/{agent_id}/AGENTS.md"),
        agents_md_text=f"You are {agent_id}.",
        agents_md_sha256="0" * 64,
    )
