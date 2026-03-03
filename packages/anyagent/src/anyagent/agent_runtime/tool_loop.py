from __future__ import annotations

import json
from typing import Any, Iterable

from pydantic import TypeAdapter

from openai.types.responses.function_tool_param import FunctionToolParam
from openai.types.responses.response import Response
from openai.types.responses.response_function_tool_call import ResponseFunctionToolCall
from openai.types.responses.response_input_item_param import FunctionCallOutput
from openai.types.responses.response_stream_event import ResponseStreamEvent
from openai.types.responses.tool_choice_function_param import ToolChoiceFunctionParam

from anyagent.protocol.tool_runtime import ExecuteRequest, ManifestRequest, ToolContext
from anyagent.tool_runtime.client import ToolRuntimeClient

from .skills_injection import inject_skills_into_responses_body
from anyagent.skills.models import SkillPackage

from anyagent.protocol.sse import encode_sse_event, normalize_response_id

from .model_providers import (
    ModelProvider,
    ModelProviderInvalidRequestError,
    ModelProviderTransportError,
    ModelProviderUpstreamError,
)


def _extract_function_calls(response: Response) -> list[ResponseFunctionToolCall]:
    out: list[ResponseFunctionToolCall] = []
    for item in response.output:
        if isinstance(item, ResponseFunctionToolCall):
            out.append(item)
    return out


def _extract_tool_names_from_request(tools: Any) -> list[str] | None:
    if tools is None:
        return None
    if not isinstance(tools, list):
        return None
    out: list[str] = []
    for i, t in enumerate(tools):
        try:
            tool = TypeAdapter(FunctionToolParam).validate_python(t)
        except Exception as e:  # noqa: BLE001
            raise ValueError(f"invalid tools[{i}]: {e}") from e
        name = tool.get("name")
        if isinstance(name, str) and name.strip():
            out.append(name.strip())
    return out


def _validate_tool_choice(tool_choice: Any, allowed_tool_names: set[str]) -> str | None:
    if tool_choice is None:
        return None
    if isinstance(tool_choice, str) and tool_choice in {"auto", "none", "required"}:
        return None
    if isinstance(tool_choice, dict) and tool_choice.get("type") == "function":
        try:
            tc = TypeAdapter(ToolChoiceFunctionParam).validate_python(tool_choice)
        except Exception:  # noqa: BLE001
            return "invalid tool_choice"
        name = tc.get("name")
        if isinstance(name, str) and name in allowed_tool_names:
            return None
        return f"tool_choice function name not allowed: {name}"
    return "invalid tool_choice"


async def resolve_manifest(
    *,
    tool_runtime: ToolRuntimeClient,
    agent_id: str,
    session_key: str | None,
    metadata: dict[str, Any] | None,
    request_tools: Any,
    enabled_skills: list[str] | None = None,
) -> tuple[list[dict[str, Any]], int]:
    requested_tool_names = _extract_tool_names_from_request(request_tools)
    requested_tools = request_tools if isinstance(request_tools, list) else None
    context = {}
    if isinstance(metadata, dict) and isinstance(metadata.get("context"), dict):
        context = metadata["context"]

    req = ManifestRequest(
        agent_id=agent_id,
        session_key=session_key,
        enabled_skills=enabled_skills,
        requested_tool_names=requested_tool_names,
        requested_tools=requested_tools,
        context=ToolContext.model_validate(context) if isinstance(context, dict) else ToolContext(),
    )
    resp = await tool_runtime.manifest(req)
    tools = [t.model_dump(exclude_none=True) for t in resp.tools]
    return tools, resp.toolset_version


async def run_tool_loop_nonstream(
    *,
    model_provider: ModelProvider,
    tool_runtime: ToolRuntimeClient,
    agent_id: str,
    session_key: str | None,
    body: dict[str, Any],
    idempotency_key: str | None,
    selected_skills: list[SkillPackage] | None = None,
    max_iters: int = 8,
) -> tuple[int, dict[str, Any]]:
    metadata = body.get("metadata") if isinstance(body.get("metadata"), dict) else None
    enabled_skills = [s.stable_id for s in (selected_skills or [])]
    manifest_tools, toolset_version = await resolve_manifest(
        tool_runtime=tool_runtime,
        agent_id=agent_id,
        session_key=session_key,
        metadata=metadata,
        request_tools=body.get("tools"),
        enabled_skills=enabled_skills or None,
    )

    allowed_tool_names: set[str] = set()
    for t in manifest_tools:
        if not isinstance(t, dict) or t.get("type") != "function":
            continue
        name = t.get("name")
        if isinstance(name, str) and name.strip():
            allowed_tool_names.add(name.strip())
    err = _validate_tool_choice(body.get("tool_choice"), allowed_tool_names)
    if err is not None:
        return 400, {"error": {"message": err, "type": "invalid_request_error"}}

    body = dict(body)
    body["tools"] = manifest_tools
    body["stream"] = False
    if selected_skills:
        body, _warnings = inject_skills_into_responses_body(body=body, selected_skills=selected_skills, role="developer")

    try:
        resp = await model_provider.create_response(body=body, idempotency_key=idempotency_key)
    except ModelProviderInvalidRequestError as e:
        return 400, {"error": {"message": e.message, "type": "invalid_request_error"}}
    except ModelProviderUpstreamError as e:
        if isinstance(e.body, dict):
            return e.status_code, e.body
        return e.status_code, {"error": {"message": e.message or "upstream_error", "type": "upstream_error"}}
    except ModelProviderTransportError as e:
        return 502, {"error": {"message": e.message, "type": "upstream_error"}}

    iters = 0
    while iters < max_iters:
        iters += 1
        response_id = resp.id
        if not isinstance(response_id, str) or not response_id.strip():
            break
        calls = _extract_function_calls(resp)
        if not calls:
            break

        tool_outputs: list[FunctionCallOutput] = []
        for call in calls:
            call_id = call.call_id
            tool_name = call.name
            arguments = call.arguments
            if not isinstance(call_id, str) or not isinstance(tool_name, str):
                continue

            tr = await tool_runtime.execute(
                ExecuteRequest(
                    agent_id=agent_id,
                    session_key=session_key or "ephemeral",
                    response_id=response_id,
                    tool_call_id=call_id,
                    tool_name=tool_name,
                    arguments_json=arguments,
                    deadline_ms=30_000,
                    toolset_version=toolset_version,
                    context=ToolContext(),
                )
            )
            if tr.status == "completed":
                output_str = tr.output
            else:
                output_str = json.dumps({"status": tr.status, "error": tr.error.model_dump()}, ensure_ascii=False)
            tool_outputs.append({"type": "function_call_output", "call_id": call_id, "output": output_str})

        if not tool_outputs:
            break

        next_body: dict[str, Any] = {
            "model": body.get("model"),
            "previous_response_id": response_id,
            "input": tool_outputs,
            "tools": manifest_tools,
            "metadata": metadata,
        }
        if body.get("tool_choice") is not None:
            next_body["tool_choice"] = body.get("tool_choice")

        try:
            resp = await model_provider.create_response(body=next_body, idempotency_key=None)
        except ModelProviderInvalidRequestError:
            break
        except ModelProviderUpstreamError:
            break
        except ModelProviderTransportError:
            break

    return 200, resp.model_dump(exclude_none=True, by_alias=True)


async def run_tool_loop_stream_buffered(
    *,
    model_provider: ModelProvider,
    tool_runtime: ToolRuntimeClient,
    agent_id: str,
    session_key: str | None,
    body: dict[str, Any],
    idempotency_key: str | None,
    selected_skills: list[SkillPackage] | None = None,
    max_iters: int = 8,
) -> tuple[int, Iterable[bytes]]:
    """
    v0：stream=true 的 tool loop 以“缓冲上游 SSE -> 回放”方式实现，避免破坏 OpenAI SDK 兼容。
    """
    metadata = body.get("metadata") if isinstance(body.get("metadata"), dict) else None
    enabled_skills = [s.stable_id for s in (selected_skills or [])]
    manifest_tools, toolset_version = await resolve_manifest(
        tool_runtime=tool_runtime,
        agent_id=agent_id,
        session_key=session_key,
        metadata=metadata,
        request_tools=body.get("tools"),
        enabled_skills=enabled_skills or None,
    )

    allowed_tool_names: set[str] = set()
    for t in manifest_tools:
        if not isinstance(t, dict) or t.get("type") != "function":
            continue
        name = t.get("name")
        if isinstance(name, str) and name.strip():
            allowed_tool_names.add(name.strip())
    err = _validate_tool_choice(body.get("tool_choice"), allowed_tool_names)
    if err is not None:
        return 400, [encode_sse_event("error", json.dumps({"error": {"message": err, "type": "invalid_request_error"}}))]

    body = dict(body)
    body["tools"] = manifest_tools
    body["stream"] = True
    if selected_skills:
        body, _warnings = inject_skills_into_responses_body(body=body, selected_skills=selected_skills, role="developer")

    try:
        events0, completed0 = await model_provider.create_response_stream_buffered(body=body, idempotency_key=idempotency_key)
    except ModelProviderUpstreamError as e:
        raw = e.raw if isinstance(e.raw, (bytes, bytearray)) else None
        return e.status_code, [raw or json.dumps(e.body or {"error": {"message": "upstream_error"}}).encode("utf-8")]
    except ModelProviderInvalidRequestError as e:
        return 400, [json.dumps({"error": {"message": e.message, "type": "invalid_request_error"}}, ensure_ascii=False).encode("utf-8")]
    except ModelProviderTransportError as e:
        return 502, [json.dumps({"error": {"message": e.message, "type": "upstream_error"}}, ensure_ascii=False).encode("utf-8")]

    canonical_response_id = completed0.id if isinstance(completed0.id, str) else "resp_anyagent"
    batches: list[list[ResponseStreamEvent]] = [events0]

    iters = 0
    resp = completed0
    while iters < max_iters:
        iters += 1
        response_id = resp.id
        if not isinstance(response_id, str) or not response_id.strip():
            break
        calls = _extract_function_calls(resp)
        if not calls:
            break

        tool_outputs: list[FunctionCallOutput] = []
        for call in calls:
            call_id = call.call_id
            tool_name = call.name
            arguments = call.arguments
            if not isinstance(call_id, str) or not isinstance(tool_name, str):
                continue

            tr = await tool_runtime.execute(
                ExecuteRequest(
                    agent_id=agent_id,
                    session_key=session_key or "ephemeral",
                    response_id=response_id,
                    tool_call_id=call_id,
                    tool_name=tool_name,
                    arguments_json=arguments,
                    deadline_ms=30_000,
                    toolset_version=toolset_version,
                    context=ToolContext(),
                )
            )
            if tr.status == "completed":
                output_str = tr.output
            else:
                output_str = json.dumps({"status": tr.status, "error": tr.error.model_dump()}, ensure_ascii=False)
            tool_outputs.append({"type": "function_call_output", "call_id": call_id, "output": output_str})

        if not tool_outputs:
            break

        next_body: dict[str, Any] = {
            "model": body.get("model"),
            "previous_response_id": response_id,
            "input": tool_outputs,
            "tools": manifest_tools,
            "metadata": metadata,
            "stream": True,
        }
        if body.get("tool_choice") is not None:
            next_body["tool_choice"] = body.get("tool_choice")

        try:
            events_i, completed_i = await model_provider.create_response_stream_buffered(body=next_body, idempotency_key=None)
        except ModelProviderUpstreamError:
            break
        except ModelProviderInvalidRequestError:
            break
        except ModelProviderTransportError:
            break

        batches.append(events_i)
        resp = completed_i

    def iter_bytes() -> Iterable[bytes]:
        for i, batch in enumerate(batches):
            is_last = i == len(batches) - 1
            for ev in batch:
                if ev.type == "response.completed" and not is_last:
                    continue
                payload = ev.model_dump(exclude_none=True, by_alias=True)
                normalize_response_id(payload, canonical_response_id)
                yield encode_sse_event(
                    ev.type, json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
                )
        yield encode_sse_event(None, "[DONE]")

    return 200, iter_bytes()
