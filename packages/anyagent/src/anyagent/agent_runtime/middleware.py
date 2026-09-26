from __future__ import annotations

import importlib
import re
from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass, field
from typing import Any, Protocol

from openai.types.responses.response import Response
from openai.types.responses.response_function_tool_call import ResponseFunctionToolCall
from openai.types.responses.response_input_item_param import FunctionCallOutput
from pydantic_ai.capabilities import AbstractCapability

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


RuntimeMiddleware = AgentMiddleware | AbstractCapability[Any]


class MiddlewareChain:
    def __init__(self, middlewares: Sequence[RuntimeMiddleware] | None = None) -> None:
        self._middlewares = list(middlewares or [])
        # Native capabilities run through pydantic-ai, which supplies their own
        # RunContext and hook signatures. Never call them through the legacy API.
        self._legacy_middlewares = [m for m in self._middlewares if not isinstance(m, AbstractCapability)]

    @property
    def empty(self) -> bool:
        return not self._middlewares

    async def before_model_call(self, context: MiddlewareContext, body: dict[str, Any]) -> BeforeModelResult:
        current = body
        stop = False
        for middleware in self._legacy_middlewares:
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
        for middleware in reversed(self._legacy_middlewares):
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
        for middleware in self._legacy_middlewares:
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
        for middleware in reversed(self._legacy_middlewares):
            hook_result = await middleware.after_tool_execute(context, call, current)
            if hook_result.result is not None:
                current = hook_result.result
        return AfterToolResult(result=current)


class MiddlewareLoadError(Exception):
    """Raised when an agent middleware cannot be loaded from a class path."""


_MIDDLEWARE_CLASSPATH_RE = re.compile(r"^(?P<module>[A-Za-z_][\w.]*):(?P<attr>[A-Za-z_]\w*)$")

_MIDDLEWARE_HOOK_NAMES = (
    "before_model_call",
    "after_model_call",
    "before_tool_execute",
    "after_tool_execute",
)


def _is_middleware_like(obj: Any) -> bool:
    return all(callable(getattr(obj, name, None)) for name in _MIDDLEWARE_HOOK_NAMES)


def load_middleware_from_classpath(
    classpath: str,
    *,
    kwargs: dict[str, Any] | None = None,
) -> RuntimeMiddleware:
    """Import and instantiate an agent middleware from a ``"module.path:ClassName"`` string.

    This consumes a TRUSTED server-side configuration surface (`agent.yaml`
    `runtime.middlewares` and plugin manifests are controlled by the deployer),
    NOT agent-controllable input. It performs a plain ``importlib.import_module``
    and is unrelated to the sandbox boundary — never feed agent/model output here.
    """

    if not isinstance(classpath, str):
        raise MiddlewareLoadError(f"middleware classpath must be a string, got {type(classpath)!r}")
    match = _MIDDLEWARE_CLASSPATH_RE.match(classpath.strip())
    if match is None:
        raise MiddlewareLoadError(
            f"invalid middleware classpath (expected 'module.path:ClassName'): {classpath!r}"
        )
    module_path = match.group("module")
    attr = match.group("attr")

    try:
        module = importlib.import_module(module_path)
    except Exception as e:  # noqa: BLE001
        raise MiddlewareLoadError(f"cannot import middleware module {module_path!r}: {e}") from e

    try:
        target = getattr(module, attr)
    except AttributeError as e:
        raise MiddlewareLoadError(f"middleware attr {attr!r} not found in module {module_path!r}") from e

    if not isinstance(target, type):
        raise MiddlewareLoadError(f"middleware target {classpath!r} is not a class")

    try:
        instance = target(**(kwargs or {}))
    except Exception as e:  # noqa: BLE001
        raise MiddlewareLoadError(f"failed to instantiate middleware {classpath!r}: {e}") from e

    if not isinstance(instance, AbstractCapability) and not _is_middleware_like(instance):
        raise MiddlewareLoadError(
            f"middleware {classpath!r} does not implement the AgentMiddleware hooks "
            f"({', '.join(_MIDDLEWARE_HOOK_NAMES)}) and is not a pydantic-ai capability"
        )
    return instance
