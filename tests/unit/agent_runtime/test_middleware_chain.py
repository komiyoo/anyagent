from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any

from anyagent.agent_packs import AgentPack, AgentSpec
from anyagent.agent_runtime.middleware import (
    AfterModelResult,
    AfterToolResult,
    BaseMiddleware,
    BeforeModelResult,
    BeforeToolResult,
    MiddlewareChain,
    MiddlewareContext,
)
from anyagent.agent_runtime.middlewares import ContextCompactionMiddleware, LoopDetectionMiddleware
from anyagent.server.app import _build_agent_middleware_chain


def test_middleware_chain_orders_hooks_and_accumulates_results() -> None:
    asyncio.run(_run_middleware_chain_orders_hooks_and_accumulates_results())


async def _run_middleware_chain_orders_hooks_and_accumulates_results() -> None:
    events: list[str] = []

    class _First(BaseMiddleware):
        async def before_model_call(self, context: MiddlewareContext, body: dict[str, Any]) -> BeforeModelResult:
            _ = context
            events.append("first.before_model")
            next_body = dict(body)
            next_body["first"] = True
            return BeforeModelResult(body=next_body)

        async def after_model_call(self, context, response, calls):  # type: ignore[no-untyped-def]
            _ = context, response, calls
            events.append("first.after_model")
            return AfterModelResult()

        async def before_tool_execute(self, context, call):  # type: ignore[no-untyped-def]
            _ = context, call
            events.append("first.before_tool")
            return BeforeToolResult()

        async def after_tool_execute(self, context, call, result):  # type: ignore[no-untyped-def]
            _ = context, call
            events.append("first.after_tool")
            return AfterToolResult(result=result)

    class _Second(BaseMiddleware):
        async def before_model_call(self, context: MiddlewareContext, body: dict[str, Any]) -> BeforeModelResult:
            _ = context
            events.append("second.before_model")
            next_body = dict(body)
            next_body["second"] = next_body.get("first") is True
            return BeforeModelResult(body=next_body)

        async def after_model_call(self, context, response, calls):  # type: ignore[no-untyped-def]
            _ = context, response, calls
            events.append("second.after_model")
            return AfterModelResult(suppress_calls=True)

        async def before_tool_execute(self, context, call):  # type: ignore[no-untyped-def]
            _ = context, call
            events.append("second.before_tool")
            return BeforeToolResult()

        async def after_tool_execute(self, context, call, result):  # type: ignore[no-untyped-def]
            _ = context, call
            events.append("second.after_tool")
            return AfterToolResult(result=result)

    chain = MiddlewareChain([_First(), _Second()])
    context = MiddlewareContext(agent_id="main", session_key="s1", iter_index=0, response_id=None, canonical_response_id=None)

    before = await chain.before_model_call(context, {"input": "hi"})
    after = await chain.after_model_call(context, response=None, calls=[])  # type: ignore[arg-type]
    before_tool = await chain.before_tool_execute(context, call=None)  # type: ignore[arg-type]
    after_tool = await chain.after_tool_execute(context, call=None, result=None)  # type: ignore[arg-type]

    assert before.body == {"input": "hi", "first": True, "second": True}
    assert after.suppress_calls is True
    assert before_tool.skip is False
    assert after_tool.result is None
    assert events == [
        "first.before_model",
        "second.before_model",
        "second.after_model",
        "first.after_model",
        "first.before_tool",
        "second.before_tool",
        "second.after_tool",
        "first.after_tool",
    ]


def test_server_builds_builtin_middleware_chain_from_runtime_order() -> None:
    pack = AgentPack(
        agent_id="main",
        root_dir=Path("/tmp/anyagent-test/main"),
        spec=AgentSpec.model_validate(
            {
                "exposed": True,
                "tools": {"requested_tool_names": []},
                "runtime": {
                    "middlewares": ["context_compaction", "loop_detection"],
                    "context_compaction": {"enabled": True},
                    "loop_detection": {"enabled": True},
                },
            }
        ),
        agents_md_path=Path("/tmp/anyagent-test/main/AGENTS.md"),
        agents_md_text="You are main.",
        agents_md_sha256="0" * 64,
    )

    chain = _build_agent_middleware_chain(pack)

    assert chain is not None
    assert [type(item) for item in chain._middlewares] == [ContextCompactionMiddleware, LoopDetectionMiddleware]
