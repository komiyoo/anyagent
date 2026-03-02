from __future__ import annotations

import json
from typing import Any, Iterable

from anyagent.protocol.tool_runtime import ExecuteRequest, ManifestRequest, ToolContext
from anyagent.tool_runtime.client import ToolRuntimeClient

from .skills_injection import inject_skills_into_responses_body
from anyagent.skills.models import SkillPackage

from .openai_responses_client import OpenAIResponsesClient
from .sse import encode_sse_event, normalize_response_id


def _extract_function_calls(response_json: dict[str, Any]) -> list[dict[str, Any]]:
    output = response_json.get("output")
    if not isinstance(output, list):
        return []
    out: list[dict[str, Any]] = []
    for item in output:
        if isinstance(item, dict) and item.get("type") == "function_call":
            out.append(item)
    return out


def _extract_tool_names_from_request(tools: Any) -> list[str] | None:
    if tools is None:
        return None
    if not isinstance(tools, list):
        return None
    out: list[str] = []
    for t in tools:
        if not isinstance(t, dict):
            continue
        if t.get("type") != "function":
            continue
        fn = t.get("function")
        if not isinstance(fn, dict):
            continue
        name = fn.get("name")
        if isinstance(name, str) and name.strip():
            out.append(name.strip())
    return out


def _validate_tool_choice(tool_choice: Any, allowed_tool_names: set[str]) -> str | None:
    if tool_choice is None:
        return None
    if isinstance(tool_choice, str) and tool_choice in {"auto", "none", "required"}:
        return None
    if isinstance(tool_choice, dict) and tool_choice.get("type") == "function":
        fn = tool_choice.get("function")
        if isinstance(fn, dict) and isinstance(fn.get("name"), str):
            name = fn["name"].strip()
            if name in allowed_tool_names:
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
    return resp.tools, resp.toolset_version


async def run_tool_loop_nonstream(
    *,
    openai: OpenAIResponsesClient,
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

    allowed_tool_names = {
        t.get("function", {}).get("name")
        for t in manifest_tools
        if isinstance(t, dict) and t.get("type") == "function" and isinstance(t.get("function"), dict)
    }
    allowed_tool_names = {n for n in allowed_tool_names if isinstance(n, str)}
    err = _validate_tool_choice(body.get("tool_choice"), allowed_tool_names)
    if err is not None:
        return 400, {"error": {"message": err, "type": "invalid_request_error"}}

    body = dict(body)
    body["tools"] = manifest_tools
    body["stream"] = False
    if selected_skills:
        body, _warnings = inject_skills_into_responses_body(body=body, selected_skills=selected_skills, role="developer")

    status_code, resp_json = await openai.create_json(body=body, idempotency_key=idempotency_key)
    if status_code >= 400 or not isinstance(resp_json, dict):
        return status_code, resp_json if isinstance(resp_json, dict) else {"error": {"message": "upstream_error", "type": "upstream_error"}}

    iters = 0
    while iters < max_iters:
        iters += 1
        response_id = resp_json.get("id")
        if not isinstance(response_id, str) or not response_id:
            break
        calls = _extract_function_calls(resp_json)
        if not calls:
            break

        tool_outputs: list[dict[str, Any]] = []
        for call in calls:
            call_id = call.get("call_id")
            tool_name = call.get("name")
            arguments = call.get("arguments")
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

        status_code, resp_json = await openai.create_json(body=next_body, idempotency_key=None)
        if status_code >= 400 or not isinstance(resp_json, dict):
            break

    return status_code, resp_json


async def run_tool_loop_stream_buffered(
    *,
    openai: OpenAIResponsesClient,
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

    allowed_tool_names = {
        t.get("function", {}).get("name")
        for t in manifest_tools
        if isinstance(t, dict) and t.get("type") == "function" and isinstance(t.get("function"), dict)
    }
    allowed_tool_names = {n for n in allowed_tool_names if isinstance(n, str)}
    err = _validate_tool_choice(body.get("tool_choice"), allowed_tool_names)
    if err is not None:
        return 400, [encode_sse_event("error", json.dumps({"error": {"message": err, "type": "invalid_request_error"}}))]

    body = dict(body)
    body["tools"] = manifest_tools
    body["stream"] = True
    if selected_skills:
        body, _warnings = inject_skills_into_responses_body(body=body, selected_skills=selected_skills, role="developer")

    status_code, events, completed, raw_text = await openai.create_sse_buffer(body=body, idempotency_key=idempotency_key)
    if status_code >= 400 or completed is None:
        return status_code, [raw_text.encode("utf-8")]

    canonical_response_id = completed.get("id") if isinstance(completed.get("id"), str) else "resp_anyagent"
    batches: list[list[tuple[str | None, str]]] = [events]

    iters = 0
    resp_json = completed
    while iters < max_iters:
        iters += 1
        response_id = resp_json.get("id")
        if not isinstance(response_id, str) or not response_id:
            break
        calls = _extract_function_calls(resp_json)
        if not calls:
            break

        tool_outputs: list[dict[str, Any]] = []
        for call in calls:
            call_id = call.get("call_id")
            tool_name = call.get("name")
            arguments = call.get("arguments")
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

        status_code, events, completed, raw_text = await openai.create_sse_buffer(body=next_body, idempotency_key=None)
        if status_code >= 400 or completed is None:
            break
        batches.append(events)
        resp_json = completed

    def iter_bytes() -> Iterable[bytes]:
        for i, batch in enumerate(batches):
            is_last = i == len(batches) - 1
            for ev, data in batch:
                if data.strip() == "[DONE]":
                    continue
                if ev == "response.completed" and not is_last:
                    continue
                if ev is None and not data:
                    continue
                try:
                    payload = json.loads(data)
                except Exception:  # noqa: BLE001
                    yield encode_sse_event(ev, data)
                    continue
                normalize_response_id(payload, canonical_response_id)
                yield encode_sse_event(ev, json.dumps(payload, ensure_ascii=False, separators=(",", ":")))
        yield encode_sse_event(None, "[DONE]")

    return 200, iter_bytes()
