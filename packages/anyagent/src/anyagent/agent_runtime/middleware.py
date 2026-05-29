from __future__ import annotations

from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass, field
from typing import Any, Protocol

from openai.types.responses.response import Response
from openai.types.responses.response_function_tool_call import ResponseFunctionToolCall
from openai.types.responses.response_input_item_param import FunctionCallOutput

from anyagent.protocol.stage_events import StageEvent


StageEventSink = Callable[[StageEvent], Awaitable[None]]


@dataclass
class MiddlewareContext:
    agent_id: str
    session_key: str | None
    iter_index: int
    response_id: str | None
    canonical_response_id: str | None
    stage_event_sink: StageEventSink | None = None
    metadata: dict[str, Any] | None = None
    model_provider: Any = None
    state: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class BeforeModelResult:
    body: dict[str, Any] | None = None
    stop: bool = False


@dataclass(frozen=True)
class AfterModelResult:
    suppress_calls: bool = False
    stop: bool = False


@dataclass(frozen=True)
class BeforeToolResult:
    skip: bool = False
    override_output: FunctionCallOutput | None = None


@dataclass(frozen=True)
class AfterToolResult:
    result: FunctionCallOutput | None = None


class AgentMiddleware(Protocol):
    async def before_model_call(self, context: MiddlewareContext, body: dict[str, Any]) -> BeforeModelResult: ...

    async def after_model_call(
        self,
        context: MiddlewareContext,
        response: Response,
        calls: list[ResponseFunctionToolCall],
    ) -> AfterModelResult: ...

    async def before_tool_execute(
        self,
        context: MiddlewareContext,
        call: ResponseFunctionToolCall,
    ) -> BeforeToolResult: ...

    async def after_tool_execute(
        self,
        context: MiddlewareContext,
        call: ResponseFunctionToolCall,
        result: FunctionCallOutput | None,
    ) -> AfterToolResult: ...


class BaseMiddleware:
    async def before_model_call(self, context: MiddlewareContext, body: dict[str, Any]) -> BeforeModelResult:
        _ = context, body
        return BeforeModelResult()

    async def after_model_call(
        self,
        context: MiddlewareContext,
        response: Response,
        calls: list[ResponseFunctionToolCall],
    ) -> AfterModelResult:
        _ = context, response, calls
        return AfterModelResult()

    async def before_tool_execute(
        self,
        context: MiddlewareContext,
        call: ResponseFunctionToolCall,
    ) -> BeforeToolResult:
        _ = context, call
        return BeforeToolResult()

    async def after_tool_execute(
        self,
        context: MiddlewareContext,
        call: ResponseFunctionToolCall,
        result: FunctionCallOutput | None,
    ) -> AfterToolResult:
        _ = context, call, result
        return AfterToolResult()


class MiddlewareChain:
    def __init__(self, middlewares: Sequence[AgentMiddleware] | None = None) -> None:
        self._middlewares = list(middlewares or [])

    @property
    def empty(self) -> bool:
        return not self._middlewares

    async def before_model_call(self, context: MiddlewareContext, body: dict[str, Any]) -> BeforeModelResult:
        current = body
        stop = False
        for middleware in self._middlewares:
            result = await middleware.before_model_call(context, current)
            if result.body is not None:
                current = result.body
            stop = stop or result.stop
            if result.stop:
                break
        return BeforeModelResult(body=current, stop=stop)

    async def after_model_call(
        self,
        context: MiddlewareContext,
        response: Response,
        calls: list[ResponseFunctionToolCall],
    ) -> AfterModelResult:
        suppress_calls = False
        stop = False
        for middleware in reversed(self._middlewares):
            result = await middleware.after_model_call(context, response, calls)
            suppress_calls = suppress_calls or result.suppress_calls
            stop = stop or result.stop
            if result.stop:
                break
        return AfterModelResult(suppress_calls=suppress_calls, stop=stop)

    async def before_tool_execute(
        self,
        context: MiddlewareContext,
        call: ResponseFunctionToolCall,
    ) -> BeforeToolResult:
        for middleware in self._middlewares:
            result = await middleware.before_tool_execute(context, call)
            if result.skip or result.override_output is not None:
                return result
        return BeforeToolResult()

    async def after_tool_execute(
        self,
        context: MiddlewareContext,
        call: ResponseFunctionToolCall,
        result: FunctionCallOutput | None,
    ) -> AfterToolResult:
        current = result
        for middleware in reversed(self._middlewares):
            hook_result = await middleware.after_tool_execute(context, call, current)
            if hook_result.result is not None:
                current = hook_result.result
        return AfterToolResult(result=current)

