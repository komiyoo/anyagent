from __future__ import annotations

import hashlib
import json
from collections import deque
from typing import Any

from openai.types.responses.response_function_tool_call import ResponseFunctionToolCall
from pydantic_ai.capabilities import AbstractCapability, Hooks, ProcessHistory
from pydantic_ai.messages import ModelMessage, ModelRequest, ModelResponse, TextPart, ToolCallPart, UserPromptPart
from pydantic_ai.tools import RunContext

from anyagent.agent_runtime.middlewares._token_estimate import estimate_tokens
from anyagent.agent_runtime.middlewares.context_compaction import ContextCompactionMiddleware
from anyagent.agent_runtime.middlewares.loop_detection import LoopDetectionMiddleware, tool_call_signature
from anyagent.agent_runtime.middleware import MiddlewareChain
from anyagent.protocol.stage_events import AnyAgentLoopTerminatedEvent, AnyAgentLoopWarningEvent


def capabilities_from_middleware_chain(
    chain: MiddlewareChain | None,
    *,
    response_id: str,
) -> list[Any]:
    """Map runtime.middlewares onto pydantic-ai Hooks / ProcessHistory. Do not grow the 4-hook API."""

    if chain is None or chain.empty:
        return []
    caps: list[Any] = []
    for middleware in getattr(chain, "_middlewares", []):
        if isinstance(middleware, AbstractCapability):
            caps.append(middleware)
        elif isinstance(middleware, LoopDetectionMiddleware):
            caps.append(_loop_detection_hooks(middleware, response_id=response_id))
        elif isinstance(middleware, ContextCompactionMiddleware):
            caps.append(_compaction_history(middleware))
    return caps


def _loop_detection_hooks(middleware: LoopDetectionMiddleware, *, response_id: str) -> Hooks:
    hooks = Hooks(id="anyagent-loop-detection")
    window: deque[str] = deque(maxlen=middleware.window_size)
    warned: set[str] = set()

    @hooks.on.after_model_request
    async def _after_model_request(ctx: RunContext[Any], request_context: Any, response: ModelResponse) -> ModelResponse:
        _ = request_context
        calls = [part for part in response.parts if isinstance(part, ToolCallPart)]
        if not calls:
            return response
        max_repeat = 0
        max_signature = ""
        for part in calls:
            fake = ResponseFunctionToolCall(
                type="function_call",
                call_id=part.tool_call_id,
                name=part.tool_name,
                arguments=part.args if isinstance(part.args, str) else json.dumps(part.args or {}, ensure_ascii=False),
            )
            signature = tool_call_signature(fake)
            window.append(signature)
            repeat_count = sum(1 for item in window if item == signature)
            if repeat_count > max_repeat:
                max_repeat = repeat_count
                max_signature = signature
        sink = None
        deps = getattr(ctx, "deps", None)
        if deps is not None:
            sink = getattr(deps, "stage_event_sink", None)
        if max_repeat >= middleware.hard_limit:
            if sink is not None:
                await sink(
                    AnyAgentLoopTerminatedEvent(
                        response_id=response_id,
                        tool_signature=max_signature,
                        repeat_count=max_repeat,
                        hard_limit=middleware.hard_limit,
                    )
                )
            return ModelResponse(
                parts=[TextPart(content="Stopped repeating the same tool call. Report the blocker instead of retrying.")],
                model_name=response.model_name,
            )
        if max_repeat >= middleware.warn_threshold:
            key = f"{max_signature}:{max_repeat}"
            if key not in warned:
                warned.add(key)
                if sink is not None:
                    await sink(
                        AnyAgentLoopWarningEvent(
                            response_id=response_id,
                            tool_signature=max_signature,
                            repeat_count=max_repeat,
                            window_size=middleware.window_size,
                        )
                    )
        return response

    return hooks


def _compaction_history(middleware: ContextCompactionMiddleware) -> ProcessHistory:
    async def _processor(ctx: RunContext[Any], messages: list[ModelMessage]) -> list[ModelMessage]:
        _ = ctx
        if len(messages) < 4:
            return messages
        tokens = estimate_tokens([_message_preview(item) for item in messages])
        if tokens < middleware.trigger_tokens:
            return messages
        keep = max(2, min(len(messages), 6))
        old, recent = messages[:-keep], messages[-keep:]
        if not old:
            return messages
        summary = _summarize_messages(old)
        summary_request = ModelRequest(
            parts=[
                UserPromptPart(
                    content=(
                        "Compressed prior conversation and tool context. Use this as continuity state:\n\n"
                        f"{summary}"
                    )
                )
            ]
        )
        return [summary_request, *recent]

    return ProcessHistory(_processor, id="anyagent-context-compaction")


def _message_preview(message: ModelMessage) -> dict[str, Any]:
    if isinstance(message, ModelRequest):
        texts = []
        for part in message.parts:
            content = getattr(part, "content", None)
            if isinstance(content, str):
                texts.append(content)
        return {"role": "user", "content": "\n".join(texts)}
    if isinstance(message, ModelResponse):
        return {"role": "assistant", "content": message.text or ""}
    return {"role": "unknown", "content": str(message)}


def _summarize_messages(messages: list[ModelMessage]) -> str:
    lines = [f"Compacted {len(messages)} older message(s)."]
    tool_names: list[str] = []
    for message in messages[-12:]:
        if not isinstance(message, ModelResponse):
            continue
        for part in message.parts:
            if isinstance(part, ToolCallPart):
                tool_names.append(part.tool_name)
    if tool_names:
        lines.append("Recent compacted tools: " + ", ".join(tool_names[-12:]))
    digest = hashlib.sha256(str(len(messages)).encode()).hexdigest()[:8]
    lines.append(f"Continue from the uncompressed recent messages that follow this summary. ({digest})")
    return "\n".join(lines)
