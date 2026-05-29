from __future__ import annotations

import hashlib
import json
import time
from collections import deque
from typing import Any

from openai.types.responses.response import Response
from openai.types.responses.response_function_tool_call import ResponseFunctionToolCall

from anyagent.agent_runtime.middleware import AfterModelResult, BaseMiddleware, BeforeModelResult, MiddlewareContext
from anyagent.protocol.stage_events import AnyAgentLoopTerminatedEvent, AnyAgentLoopWarningEvent, _safe_json_dumps


class LoopDetectionMiddleware(BaseMiddleware):
    def __init__(self, *, window_size: int = 20, warn_threshold: int = 3, hard_limit: int = 5) -> None:
        self.window_size = max(1, window_size)
        self.warn_threshold = max(1, warn_threshold)
        self.hard_limit = max(self.warn_threshold, hard_limit)

    async def before_model_call(self, context: MiddlewareContext, body: dict[str, Any]) -> BeforeModelResult:
        warning = context.state.pop("loop_detection.warning_text", None)
        if not isinstance(warning, str) or not warning.strip():
            return BeforeModelResult()
        next_body = dict(body)
        existing = next_body.get("input")
        warning_item = {"role": "developer", "content": warning}
        if isinstance(existing, list):
            next_body["input"] = [warning_item, *existing]
        else:
            next_body["input"] = [warning_item, {"role": "user", "content": str(existing or "")}]
        return BeforeModelResult(body=next_body)

    async def after_model_call(
        self,
        context: MiddlewareContext,
        response: Response,
        calls: list[ResponseFunctionToolCall],
    ) -> AfterModelResult:
        _ = response
        if not calls:
            return AfterModelResult()
        window = context.state.get("loop_detection.window")
        if not isinstance(window, deque):
            window = deque(maxlen=self.window_size)
            context.state["loop_detection.window"] = window

        max_repeat = 0
        max_signature = ""
        for call in calls:
            signature = tool_call_signature(call)
            window.append(signature)
            repeat_count = sum(1 for item in window if item == signature)
            if repeat_count > max_repeat:
                max_repeat = repeat_count
                max_signature = signature

        if max_repeat >= self.hard_limit:
            await self._emit_terminated(context=context, signature=max_signature, repeat_count=max_repeat)
            return AfterModelResult(suppress_calls=True, stop=True)

        if max_repeat >= self.warn_threshold:
            warned_key = f"loop_detection.warned.{max_signature}.{max_repeat}"
            if not context.state.get(warned_key):
                context.state[warned_key] = True
                await self._emit_warning(context=context, signature=max_signature, repeat_count=max_repeat)
            context.state["loop_detection.warning_text"] = (
                "You appear to be repeating the same tool call. Re-evaluate the result, change strategy, "
                "or stop and report the blocker instead of retrying identical arguments."
            )
        return AfterModelResult()

    async def _emit_warning(self, *, context: MiddlewareContext, signature: str, repeat_count: int) -> None:
        if context.stage_event_sink is None:
            return
        await context.stage_event_sink(
            AnyAgentLoopWarningEvent(
                response_id=context.canonical_response_id or context.response_id or "resp_anyagent",
                tool_signature=signature,
                repeat_count=repeat_count,
                window_size=self.window_size,
                ts_ms=int(time.time() * 1000),
            )
        )

    async def _emit_terminated(self, *, context: MiddlewareContext, signature: str, repeat_count: int) -> None:
        if context.stage_event_sink is None:
            return
        await context.stage_event_sink(
            AnyAgentLoopTerminatedEvent(
                response_id=context.canonical_response_id or context.response_id or "resp_anyagent",
                tool_signature=signature,
                repeat_count=repeat_count,
                hard_limit=self.hard_limit,
                ts_ms=int(time.time() * 1000),
            )
        )


def tool_call_signature(call: ResponseFunctionToolCall) -> str:
    payload = {"name": call.name, "arguments": _stable_tool_key(call.name, call.arguments)}
    raw = _safe_json_dumps(payload, sort_keys=True)
    return hashlib.sha256(raw.encode("utf-8", errors="replace")).hexdigest()


def _stable_tool_key(name: str, arguments: Any) -> Any:
    try:
        obj = json.loads(arguments) if isinstance(arguments, str) else arguments
    except Exception:  # noqa: BLE001
        obj = arguments
    if not isinstance(obj, dict):
        return obj
    if name.endswith("read_file") or name == "read_file":
        out = dict(obj)
        for key in ("line", "lineno", "start_line", "end_line", "offset"):
            value = out.get(key)
            if isinstance(value, int):
                out[key] = (value // 200) * 200
        return out
    if name.endswith("write_file") or name == "write_file":
        raw = _safe_json_dumps(obj, sort_keys=True)
        return {"sha256": hashlib.sha256(raw.encode("utf-8", errors="replace")).hexdigest()}
    salient = {
        key: obj[key]
        for key in ("path", "file", "url", "query", "q", "command", "cmd", "name", "id")
        if key in obj
    }
    return salient or obj

