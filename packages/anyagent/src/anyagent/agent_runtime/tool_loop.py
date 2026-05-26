from __future__ import annotations

import json
import time
from collections.abc import AsyncIterator
from typing import Any, Awaitable, Callable, Iterable

from openai.types.responses.response import Response
from openai.types.responses.response_function_tool_call import ResponseFunctionToolCall
from openai.types.responses.response_input_item_param import FunctionCallOutput
from openai.types.responses.response_stream_event import ResponseStreamEvent

from anyagent.mcp.manager import MCPServerManager
from anyagent.protocol.command_derivation import extract_command_planned_fields, extract_command_result_fields
from anyagent.protocol.openai_responses import AnyAgentFunctionToolParam, parse_tool_arguments_object, validate_tool_choice
from anyagent.protocol.sse import encode_sse_event, normalize_response_id
from anyagent.protocol.stage_events import (
    AnyAgentCommandPlannedEvent,
    AnyAgentCommandResultEvent,
    AnyAgentToolPlannedEvent,
    AnyAgentToolResultEvent,
    StageEvent,
    summarize_command,
    summarize_payload,
)
from anyagent.protocol.tool_manifest_extensions import (
    source_tool_name_for_model_name,
    strip_internal_tool_fields,
    tool_kind_for_tool_name,
)
from anyagent.protocol.tool_runtime import ExecuteRequest, ManifestRequest, ToolContext
from anyagent.skills.models import SkillPackage
from anyagent.tool_runtime.client import ToolRuntimeClient

from .model_providers import (
    BufferedLiveResponseStream,
    ModelProvider,
    ModelProviderInvalidRequestError,
    ModelProviderLiveResponseStream,
    ModelProviderTransportError,
    ModelProviderUpstreamError,
)
from .skills_injection import inject_skills_into_responses_body
from .tool_loop_payloads import build_tool_loop_followup_body, extract_allowed_function_tool_names
from .tool_results import (
    build_completed_tool_result,
    build_error_tool_result,
    build_function_call_output_item,
)


StageEventSink = Callable[[StageEvent], Awaitable[None]]
ManifestRefresher = Callable[[], Awaitable[tuple[list[dict[str, Any]], int]]]
ManifestResolver = Callable[[], Awaitable[tuple[list[dict[str, Any]], int]]]


def _strip_anyagent_request_metadata(body: dict[str, Any]) -> dict[str, Any]:
    provider_body = dict(body)
    provider_body.pop("metadata", None)
    provider_body.pop("tenant_id", None)
    return provider_body


def _is_previous_response_not_found(error: ModelProviderUpstreamError) -> bool:
    body = error.body
    if not isinstance(body, dict):
        return False
    code = body.get("code")
    param = body.get("param")
    message = body.get("message")
    return (
        code == "InvalidParameter.PreviousResponseNotFound"
        or param == "previous_response_id"
        and isinstance(message, str)
        and "not found" in message.lower()
    )


def _build_stateless_tool_followup_body(
    *,
    response: Response,
    next_body: dict[str, Any],
    tool_outputs: list[FunctionCallOutput],
) -> dict[str, Any]:
    fallback_body = dict(next_body)
    fallback_body.pop("previous_response_id", None)
    prior_output = response.model_dump(exclude_none=True, by_alias=True).get("output")
    input_items = list(prior_output) if isinstance(prior_output, list) else []
    input_items.extend(tool_outputs)
    fallback_body["input"] = input_items
    return fallback_body


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
            tool = AnyAgentFunctionToolParam.model_validate(t)
        except Exception as e:  # noqa: BLE001
            raise ValueError(f"invalid tools[{i}]: {e}") from e
        if isinstance(tool.name, str) and tool.name.strip():
            out.append(tool.name.strip())
    return out


async def resolve_manifest(
    *,
    tool_runtime: ToolRuntimeClient,
    agent_id: str,
    session_key: str | None,
    metadata: dict[str, Any] | None,
    request_tools: Any,
    tool_context: ToolContext | None = None,
    enabled_skills: list[str] | None = None,
) -> tuple[list[dict[str, Any]], int]:
    requested_tool_names = _extract_tool_names_from_request(request_tools)
    requested_tools = request_tools if isinstance(request_tools, list) else None

    req = ManifestRequest(
        agent_id=agent_id,
        session_key=session_key,
        enabled_skills=enabled_skills,
        requested_tool_names=requested_tool_names,
        requested_tools=requested_tools,
        context=tool_context or ToolContext(),
    )
    resp = await tool_runtime.manifest(req)
    tools = [t.model_dump(exclude_none=True, by_alias=True) for t in resp.tools]
    return tools, resp.toolset_version


async def resolve_manifest_with_mcp(
    *,
    tool_runtime: ToolRuntimeClient,
    mcp_manager: MCPServerManager | None,
    agent_id: str,
    session_key: str | None,
    metadata: dict[str, Any] | None,
    request_tools: Any,
    tool_context: ToolContext | None = None,
    enabled_skills: list[str] | None = None,
) -> tuple[list[dict[str, Any]], int]:
    tr_tools, toolset_version = await resolve_manifest(
        tool_runtime=tool_runtime,
        agent_id=agent_id,
        session_key=session_key,
        metadata=metadata,
        request_tools=request_tools,
        tool_context=tool_context,
        enabled_skills=enabled_skills,
    )
    mcp_tools: list[dict[str, Any]] = []
    if mcp_manager is not None:
        mcp_tools = await mcp_manager.list_all_tools()
    return [*tr_tools, *mcp_tools], toolset_version


async def _emit_tool_planned(
    *,
    sink: StageEventSink | None,
    response_id: str,
    trace_id: str | None,
    tool_call_id: str,
    tool_name: str,
    tool_kind: str | None,
    arguments_json: Any,
) -> None:
    if sink is None:
        return
    ts_ms = int(time.time() * 1000)
    event = AnyAgentToolPlannedEvent(
        response_id=response_id,
        trace_id=trace_id,
        tool_call_id=tool_call_id,
        tool_name=tool_name,
        arguments=summarize_payload(arguments_json),
        ts_ms=ts_ms,
    )
    await sink(event)
    planned = extract_command_planned_fields(tool_name=tool_name, tool_kind=tool_kind, arguments_json=arguments_json)
    if planned is None:
        return
    await sink(
        AnyAgentCommandPlannedEvent(
            response_id=response_id,
            trace_id=trace_id,
            command=summarize_command(planned.command),
            workdir=planned.workdir,
            timeout_ms=planned.timeout_ms,
            source_tool_call_id=tool_call_id,
            source_tool_name=tool_name,
            ts_ms=ts_ms,
        )
    )


async def _emit_tool_result(
    *,
    sink: StageEventSink | None,
    response_id: str,
    trace_id: str | None,
    tool_call_id: str,
    tool_name: str,
    tool_kind: str | None,
    status: str,
    output: Any = None,
    error: dict[str, Any] | None = None,
    duration_ms: int | None = None,
    output_truncated: bool | None = None,
    audit_ref: str | None = None,
) -> None:
    if sink is None:
        return
    ts_ms = int(time.time() * 1000)
    event = AnyAgentToolResultEvent(
        response_id=response_id,
        trace_id=trace_id,
        tool_call_id=tool_call_id,
        tool_name=tool_name,
        status=status,
        output=summarize_payload(output) if output is not None else None,
        error=error,
        meta={
            "duration_ms": duration_ms,
            "output_truncated": output_truncated,
            "audit_ref": audit_ref,
        },
        ts_ms=ts_ms,
    )
    await sink(event)
    command = extract_command_result_fields(tool_name=tool_name, tool_kind=tool_kind, tool_output=output)
    if command is None:
        return
    await sink(
        AnyAgentCommandResultEvent(
            response_id=response_id,
            trace_id=trace_id,
            exit_code=command.exit_code,
            stdout=summarize_payload(command.stdout) if command.stdout is not None else None,
            stderr=summarize_payload(command.stderr) if command.stderr is not None else None,
            duration_ms=duration_ms,
            source_tool_call_id=tool_call_id,
            source_tool_name=tool_name,
            ts_ms=ts_ms,
        )
    )


async def _execute_one_tool(
    *,
    model_provider: ModelProvider,
    tool_runtime: ToolRuntimeClient,
    mcp_manager: MCPServerManager | None,
    agent_id: str,
    session_key: str | None,
    response_id: str,
    toolset_version: int,
    manifest_tools: list[dict[str, Any]],
    tool_context: ToolContext,
    manifest_refresher: ManifestRefresher | None,
    call: ResponseFunctionToolCall,
    stage_event_sink: StageEventSink | None,
) -> tuple[FunctionCallOutput | None, list[dict[str, Any]], int]:
    call_id = call.call_id
    tool_name = source_tool_name_for_model_name(manifest_tools, call.name)
    arguments = call.arguments
    if not isinstance(call_id, str) or not isinstance(tool_name, str):
        return None, manifest_tools, toolset_version

    tool_kind = tool_kind_for_tool_name(manifest_tools, tool_name)
    trace_id = tool_context.trace.trace_id if tool_context.trace is not None else None
    parsed_args = arguments
    if isinstance(arguments, str):
        try:
            parsed_args = parse_tool_arguments_object(arguments)
        except Exception:
            parsed_args = arguments

    await _emit_tool_planned(
        sink=stage_event_sink,
        response_id=response_id,
        trace_id=trace_id,
        tool_call_id=call_id,
        tool_name=tool_name,
        tool_kind=tool_kind,
        arguments_json=parsed_args,
    )

    if tool_name.startswith("mcp."):
        if mcp_manager is None:
            tool_result = build_error_tool_result(
                error_type="mcp_error",
                message="mcp manager not configured",
            )
        else:
            try:
                output_text = await mcp_manager.call_tool(
                    tool_name,
                    parse_tool_arguments_object(arguments),
                )
                tool_result = build_completed_tool_result(
                    output=output_text if isinstance(output_text, str) else str(output_text)
                )
            except Exception as e:  # noqa: BLE001
                tool_result = build_error_tool_result(
                    error_type="mcp_error",
                    message=str(e),
                )
    else:
        current_manifest_tools = manifest_tools
        current_toolset_version = toolset_version
        tr = await tool_runtime.execute(
            ExecuteRequest(
                agent_id=agent_id,
                session_key=session_key or "ephemeral",
                response_id=response_id,
                tool_call_id=call_id,
                tool_name=tool_name,
                arguments_json=arguments,
                deadline_ms=30_000,
                toolset_version=current_toolset_version,
                context=tool_context,
            )
        )
        if (
            tr.status == "error"
            and tr.error.code == "toolset_version_mismatch"
            and manifest_refresher is not None
        ):
            current_manifest_tools, current_toolset_version = await manifest_refresher()
            tool_kind = tool_kind_for_tool_name(current_manifest_tools, tool_name)
            tr = await tool_runtime.execute(
                ExecuteRequest(
                    agent_id=agent_id,
                    session_key=session_key or "ephemeral",
                    response_id=response_id,
                    tool_call_id=call_id,
                    tool_name=tool_name,
                    arguments_json=arguments,
                    deadline_ms=30_000,
                    toolset_version=current_toolset_version,
                    context=tool_context,
                )
            )
        if tr.status == "completed":
            tool_result = build_completed_tool_result(output=tr.output)
        else:
            tool_result = {"status": tr.status, "error": tr.error.model_dump()}

        output_value = tr.output if tr.status == "completed" else None
        error_value = tr.error.model_dump() if tr.status != "completed" else None
        await _emit_tool_result(
            sink=stage_event_sink,
            response_id=response_id,
            trace_id=trace_id,
            tool_call_id=call_id,
            tool_name=tool_name,
            tool_kind=tool_kind,
            status=tr.status,
            output=output_value,
            error=error_value,
            duration_ms=tr.meta.duration_ms,
            output_truncated=tr.meta.output_truncated,
            audit_ref=tr.meta.audit_ref,
        )
        return build_function_call_output_item(
            call_id=call_id,
            tool_result=tool_result,
            error_format="json",
        ), current_manifest_tools, current_toolset_version

    if tool_result.get("status") == "completed":
        await _emit_tool_result(
            sink=stage_event_sink,
            response_id=response_id,
            trace_id=trace_id,
            tool_call_id=call_id,
            tool_name=tool_name,
            tool_kind=tool_kind,
            status="completed",
            output=tool_result.get("output"),
        )
    else:
        await _emit_tool_result(
            sink=stage_event_sink,
            response_id=response_id,
            trace_id=trace_id,
            tool_call_id=call_id,
            tool_name=tool_name,
            tool_kind=tool_kind,
            status=str(tool_result.get("status") or "error"),
            error=tool_result.get("error"),
        )
    return build_function_call_output_item(
        call_id=call_id,
        tool_result=tool_result,
        error_format="json",
    ), manifest_tools, toolset_version


async def run_tool_loop_nonstream(
    *,
    model_provider: ModelProvider,
    tool_runtime: ToolRuntimeClient,
    agent_id: str,
    session_key: str | None,
    body: dict[str, Any],
    idempotency_key: str | None,
    canonical_response_id: str | None = None,
    tool_context: ToolContext | None = None,
    selected_skills: list[SkillPackage] | None = None,
    manifest_resolver: ManifestResolver | None = None,
    manifest_force_refresh: ManifestRefresher | None = None,
    mcp_manager: MCPServerManager | None = None,
    max_iters: int = 8,
    stage_event_sink: StageEventSink | None = None,
    prompt_envelope_applied: bool = False,
) -> tuple[int, dict[str, Any]]:
    metadata = body.get("metadata") if isinstance(body.get("metadata"), dict) else None
    enabled_skills = [s.stable_id for s in (selected_skills or [])]
    if manifest_resolver is not None:
        manifest_tools, toolset_version = await manifest_resolver()
    else:
        manifest_tools, toolset_version = await resolve_manifest_with_mcp(
            tool_runtime=tool_runtime,
            mcp_manager=mcp_manager,
            agent_id=agent_id,
            session_key=session_key,
            metadata=metadata,
            request_tools=body.get("tools"),
            tool_context=tool_context,
            enabled_skills=enabled_skills or None,
        )

    allowed_tool_names = extract_allowed_function_tool_names(manifest_tools=manifest_tools)
    err = validate_tool_choice(body.get("tool_choice"), allowed_tool_names)
    if err is not None:
        return 400, {"error": {"message": err, "type": "invalid_request_error"}}

    body = _strip_anyagent_request_metadata(body)
    body["tools"] = strip_internal_tool_fields(manifest_tools)
    body["stream"] = False
    if selected_skills and not prompt_envelope_applied:
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

    canonical_response_id = canonical_response_id or (
        resp.id if isinstance(resp.id, str) and resp.id.strip() else "resp_anyagent"
    )
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
        emitted_response_id = canonical_response_id or response_id
        async def _refresh_manifest() -> tuple[list[dict[str, Any]], int]:
            if manifest_force_refresh is not None:
                return await manifest_force_refresh()
            return await resolve_manifest_with_mcp(
                tool_runtime=tool_runtime,
                mcp_manager=mcp_manager,
                agent_id=agent_id,
                session_key=session_key,
                metadata=metadata,
                request_tools=body.get("tools"),
                tool_context=tool_context,
                enabled_skills=enabled_skills or None,
            )
        for call in calls:
            out, manifest_tools, toolset_version = await _execute_one_tool(
                model_provider=model_provider,
                tool_runtime=tool_runtime,
                mcp_manager=mcp_manager,
                agent_id=agent_id,
                session_key=session_key,
                response_id=emitted_response_id,
                toolset_version=toolset_version,
                manifest_tools=manifest_tools,
                tool_context=tool_context or ToolContext(),
                manifest_refresher=_refresh_manifest,
                call=call,
                stage_event_sink=stage_event_sink,
            )
            if out is not None:
                tool_outputs.append(out)

        if not tool_outputs:
            break

        next_body = build_tool_loop_followup_body(
            previous_response_id=response_id,
            tool_outputs=tool_outputs,
            manifest_tools=manifest_tools,
            metadata=metadata,
            tool_choice=body.get("tool_choice"),
            stream=False,
            model=body.get("model") if isinstance(body.get("model"), str) else None,
            prompt_cache_key=body.get("prompt_cache_key") if isinstance(body.get("prompt_cache_key"), str) else None,
        )
        next_body = _strip_anyagent_request_metadata(next_body)
        try:
            resp = await model_provider.create_response(body=next_body, idempotency_key=None)
        except ModelProviderInvalidRequestError:
            break
        except ModelProviderUpstreamError as e:
            if not _is_previous_response_not_found(e):
                break
            fallback_body = _build_stateless_tool_followup_body(
                response=resp,
                next_body=next_body,
                tool_outputs=tool_outputs,
            )
            try:
                resp = await model_provider.create_response(body=fallback_body, idempotency_key=None)
            except (ModelProviderInvalidRequestError, ModelProviderUpstreamError, ModelProviderTransportError):
                break
        except ModelProviderTransportError:
            break

    payload = resp.model_dump(exclude_none=True, by_alias=True)
    normalize_response_id(payload, canonical_response_id)
    return 200, payload


async def run_tool_loop_stream_buffered(
    *,
    model_provider: ModelProvider,
    tool_runtime: ToolRuntimeClient,
    agent_id: str,
    session_key: str | None,
    body: dict[str, Any],
    idempotency_key: str | None,
    canonical_response_id: str | None = None,
    tool_context: ToolContext | None = None,
    selected_skills: list[SkillPackage] | None = None,
    manifest_resolver: ManifestResolver | None = None,
    manifest_force_refresh: ManifestRefresher | None = None,
    mcp_manager: MCPServerManager | None = None,
    max_iters: int = 8,
    stage_event_sink: StageEventSink | None = None,
    prompt_envelope_applied: bool = False,
) -> tuple[int, Iterable[bytes]]:
    metadata = body.get("metadata") if isinstance(body.get("metadata"), dict) else None
    enabled_skills = [s.stable_id for s in (selected_skills or [])]
    if manifest_resolver is not None:
        manifest_tools, toolset_version = await manifest_resolver()
    else:
        manifest_tools, toolset_version = await resolve_manifest_with_mcp(
            tool_runtime=tool_runtime,
            mcp_manager=mcp_manager,
            agent_id=agent_id,
            session_key=session_key,
            metadata=metadata,
            request_tools=body.get("tools"),
            tool_context=tool_context,
            enabled_skills=enabled_skills or None,
        )

    allowed_tool_names = extract_allowed_function_tool_names(manifest_tools=manifest_tools)
    err = validate_tool_choice(body.get("tool_choice"), allowed_tool_names)
    if err is not None:
        return 400, [encode_sse_event("error", json.dumps({"error": {"message": err, "type": "invalid_request_error"}}))]

    body = _strip_anyagent_request_metadata(body)
    body["tools"] = strip_internal_tool_fields(manifest_tools)
    body["stream"] = True
    if selected_skills and not prompt_envelope_applied:
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

    canonical_response_id = canonical_response_id or (
        completed0.id if isinstance(completed0.id, str) else "resp_anyagent"
    )
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
        emitted_response_id = canonical_response_id or response_id
        async def _refresh_manifest() -> tuple[list[dict[str, Any]], int]:
            if manifest_force_refresh is not None:
                return await manifest_force_refresh()
            return await resolve_manifest_with_mcp(
                tool_runtime=tool_runtime,
                mcp_manager=mcp_manager,
                agent_id=agent_id,
                session_key=session_key,
                metadata=metadata,
                request_tools=body.get("tools"),
                tool_context=tool_context,
                enabled_skills=enabled_skills or None,
            )
        for call in calls:
            out, manifest_tools, toolset_version = await _execute_one_tool(
                model_provider=model_provider,
                tool_runtime=tool_runtime,
                mcp_manager=mcp_manager,
                agent_id=agent_id,
                session_key=session_key,
                response_id=emitted_response_id,
                toolset_version=toolset_version,
                manifest_tools=manifest_tools,
                tool_context=tool_context or ToolContext(),
                manifest_refresher=_refresh_manifest,
                call=call,
                stage_event_sink=stage_event_sink,
            )
            if out is not None:
                tool_outputs.append(out)

        if not tool_outputs:
            break

        next_body = build_tool_loop_followup_body(
            previous_response_id=response_id,
            tool_outputs=tool_outputs,
            manifest_tools=manifest_tools,
            metadata=metadata,
            tool_choice=body.get("tool_choice"),
            stream=True,
            model=body.get("model") if isinstance(body.get("model"), str) else None,
            prompt_cache_key=body.get("prompt_cache_key") if isinstance(body.get("prompt_cache_key"), str) else None,
        )

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


async def run_tool_loop_stream_live(
    *,
    model_provider: ModelProvider,
    tool_runtime: ToolRuntimeClient,
    agent_id: str,
    session_key: str | None,
    body: dict[str, Any],
    idempotency_key: str | None,
    canonical_response_id: str | None = None,
    tool_context: ToolContext | None = None,
    selected_skills: list[SkillPackage] | None = None,
    manifest_resolver: ManifestResolver | None = None,
    manifest_force_refresh: ManifestRefresher | None = None,
    mcp_manager: MCPServerManager | None = None,
    max_iters: int = 8,
    stage_event_sink: StageEventSink | None = None,
    prompt_envelope_applied: bool = False,
) -> AsyncIterator[bytes]:
    metadata = body.get("metadata") if isinstance(body.get("metadata"), dict) else None
    enabled_skills = [s.stable_id for s in (selected_skills or [])]
    if manifest_resolver is not None:
        manifest_tools, toolset_version = await manifest_resolver()
    else:
        manifest_tools, toolset_version = await resolve_manifest_with_mcp(
            tool_runtime=tool_runtime,
            mcp_manager=mcp_manager,
            agent_id=agent_id,
            session_key=session_key,
            metadata=metadata,
            request_tools=body.get("tools"),
            tool_context=tool_context,
            enabled_skills=enabled_skills or None,
        )

    allowed_tool_names = extract_allowed_function_tool_names(manifest_tools=manifest_tools)
    err = validate_tool_choice(body.get("tool_choice"), allowed_tool_names)
    if err is not None:
        raise ModelProviderInvalidRequestError(err)

    current_body = _strip_anyagent_request_metadata(body)
    current_body["tools"] = strip_internal_tool_fields(manifest_tools)
    current_body["stream"] = True
    if selected_skills and not prompt_envelope_applied:
        current_body, _warnings = inject_skills_into_responses_body(
            body=current_body,
            selected_skills=selected_skills,
            role="developer",
        )

    current_idempotency = idempotency_key
    canonical_id = canonical_response_id

    for _iter_index in range(max_iters):
        live_stream = await _open_live_response_stream(
            model_provider=model_provider,
            body=current_body,
            idempotency_key=current_idempotency,
        )

        pending_completed_block: bytes | None = None
        async with live_stream as stream:
            async for ev in stream:
                payload = ev.model_dump(exclude_none=True, by_alias=True)
                if canonical_id is None:
                    ev_response = payload.get("response")
                    if isinstance(ev_response, dict) and isinstance(ev_response.get("id"), str):
                        canonical_id = ev_response["id"]
                normalize_response_id(payload, canonical_id or "resp_anyagent")
                if ev.type == "response.created":
                    continue
                encoded = encode_sse_event(
                    ev.type,
                    json.dumps(payload, ensure_ascii=False, separators=(",", ":")),
                )
                if ev.type == "response.completed":
                    pending_completed_block = encoded
                    continue
                yield encoded

            resp = await stream.wait_completed()

        response_id = resp.id
        if canonical_id is None and isinstance(response_id, str) and response_id.strip():
            canonical_id = response_id

        if not isinstance(response_id, str) or not response_id.strip():
            break

        calls = _extract_function_calls(resp)
        if not calls:
            if pending_completed_block is not None:
                yield pending_completed_block
            yield encode_sse_event(None, "[DONE]")
            return

        tool_outputs: list[FunctionCallOutput] = []
        emitted_response_id = canonical_id or response_id
        async def _refresh_manifest() -> tuple[list[dict[str, Any]], int]:
            if manifest_force_refresh is not None:
                return await manifest_force_refresh()
            return await resolve_manifest_with_mcp(
                tool_runtime=tool_runtime,
                mcp_manager=mcp_manager,
                agent_id=agent_id,
                session_key=session_key,
                metadata=metadata,
                request_tools=body.get("tools"),
                tool_context=tool_context,
                enabled_skills=enabled_skills or None,
            )
        for call in calls:
            out, manifest_tools, toolset_version = await _execute_one_tool(
                model_provider=model_provider,
                tool_runtime=tool_runtime,
                mcp_manager=mcp_manager,
                agent_id=agent_id,
                session_key=session_key,
                response_id=emitted_response_id,
                toolset_version=toolset_version,
                manifest_tools=manifest_tools,
                tool_context=tool_context or ToolContext(),
                manifest_refresher=_refresh_manifest,
                call=call,
                stage_event_sink=stage_event_sink,
            )
            if out is not None:
                tool_outputs.append(out)

        if not tool_outputs:
            if pending_completed_block is not None:
                yield pending_completed_block
            yield encode_sse_event(None, "[DONE]")
            return

        current_body = build_tool_loop_followup_body(
            previous_response_id=response_id,
            tool_outputs=tool_outputs,
            manifest_tools=manifest_tools,
            metadata=metadata,
            tool_choice=body.get("tool_choice"),
            stream=True,
            model=body.get("model") if isinstance(body.get("model"), str) else None,
        )
        current_idempotency = None

    yield encode_sse_event(None, "[DONE]")


async def _open_live_response_stream(
    *,
    model_provider: ModelProvider,
    body: dict[str, Any],
    idempotency_key: str | None,
) -> ModelProviderLiveResponseStream:
    if hasattr(model_provider, "create_response_stream_live"):
        return await model_provider.create_response_stream_live(
            body=body,
            idempotency_key=idempotency_key,
        )
    events, completed = await model_provider.create_response_stream_buffered(
        body=body,
        idempotency_key=idempotency_key,
    )
    return BufferedLiveResponseStream(events=events, completed=completed)
