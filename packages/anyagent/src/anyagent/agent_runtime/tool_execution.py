from __future__ import annotations

import json
import time
from typing import Any, Awaitable, Callable

from openai.types.responses.response_function_tool_call import ResponseFunctionToolCall
from openai.types.responses.response_input_item_param import FunctionCallOutput

from anyagent.mcp.manager import MCPServerManager
from anyagent.protocol.command_derivation import extract_command_planned_fields, extract_command_result_fields
from anyagent.protocol.openai_responses import AnyAgentFunctionToolParam, parse_tool_arguments_object
from anyagent.protocol.stage_events import (
    AnyAgentCommandPlannedEvent,
    AnyAgentCommandResultEvent,
    AnyAgentToolExecutionDetailEvent,
    AnyAgentToolPlannedEvent,
    AnyAgentToolResultEvent,
    StageEvent,
    summarize_command,
    summarize_payload,
)
from anyagent.protocol.tool_manifest_extensions import (
    source_tool_name_for_model_name,
    tool_kind_for_tool_name,
    tool_source_for_kind,
)
from anyagent.protocol.tool_runtime import ExecuteRequest, ManifestRequest, ToolContext
from anyagent.resource_quota import channel_for_tool_name, maybe_emit_resource_exhausted
from anyagent.tool_runtime.client import ToolRuntimeClient

from .model_providers import ModelProvider
from .middleware import MiddlewareChain, MiddlewareContext
from .tool_results import (
    build_completed_tool_result,
    build_error_tool_result,
    build_function_call_output_item,
)


StageEventSink = Callable[[StageEvent], Awaitable[None]]
ManifestRefresher = Callable[[], Awaitable[tuple[list[dict[str, Any]], int]]]
ManifestResolver = Callable[[], Awaitable[tuple[list[dict[str, Any]], int]]]
SystemToolExecutor = Callable[[str, object], Awaitable[str]]


async def _execute_one_tool_with_middleware(
    *,
    middleware_chain: MiddlewareChain | None,
    middleware_context: MiddlewareContext,
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
    system_tool_executor: SystemToolExecutor | None,
    call: ResponseFunctionToolCall,
    stage_event_sink: StageEventSink | None,
) -> tuple[FunctionCallOutput | None, list[dict[str, Any]], int]:
    if middleware_chain is not None and not middleware_chain.empty:
        before = await middleware_chain.before_tool_execute(middleware_context, call)
        if before.skip:
            return before.override_output, manifest_tools, toolset_version
    out, manifest_tools, toolset_version = await _execute_one_tool(
        model_provider=model_provider,
        tool_runtime=tool_runtime,
        mcp_manager=mcp_manager,
        agent_id=agent_id,
        session_key=session_key,
        response_id=response_id,
        toolset_version=toolset_version,
        manifest_tools=manifest_tools,
        tool_context=tool_context,
        manifest_refresher=manifest_refresher,
        system_tool_executor=system_tool_executor,
        call=call,
        stage_event_sink=stage_event_sink,
    )
    if middleware_chain is not None and not middleware_chain.empty:
        after = await middleware_chain.after_tool_execute(middleware_context, call, out)
        out = after.result
    return out, manifest_tools, toolset_version


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
    stage_event_sink: StageEventSink | None = None,
    stage_response_id: str | None = None,
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
        mcp_tools = await mcp_manager.list_all_tools(
            session_key=session_key,
            stage_event_sink=stage_event_sink,
            response_id=stage_response_id,
        )
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
        tool_source=tool_source_for_kind(tool_kind),  # type: ignore[arg-type]
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
        tool_source=tool_source_for_kind(tool_kind),  # type: ignore[arg-type]
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


async def _emit_tool_execution_detail(
    *,
    sink: StageEventSink | None,
    response_id: str,
    trace_id: str | None,
    tool_call_id: str,
    tool_name: str,
    tool_kind: str | None,
    arguments_json: str,
    output: str | None = None,
    error: dict[str, Any] | None = None,
    status: str,
    duration_ms: int | None = None,
    output_truncated: bool | None = None,
    audit_ref: str | None = None,
) -> None:
    """Emit full tool execution detail event for historical replay."""
    if sink is None:
        return
    ts_ms = int(time.time() * 1000)
    detail_error = None
    if error is not None:
        detail_error = {
            "type": error.get("type", "tool_error"),
            "message": error.get("message", ""),
            "code": error.get("code"),
            "retryable": error.get("retryable"),
        }
    event = AnyAgentToolExecutionDetailEvent(
        response_id=response_id,
        trace_id=trace_id,
        tool_call_id=tool_call_id,
        tool_name=tool_name,
        arguments_json=arguments_json if isinstance(arguments_json, str) else json.dumps(arguments_json, ensure_ascii=False),
        output=output,
        error=detail_error,  # type: ignore[arg-type]
        status=status,
        duration_ms=duration_ms,
        output_truncated=output_truncated,
        audit_ref=audit_ref,
        tool_source=tool_source_for_kind(tool_kind),  # type: ignore[arg-type]
        ts_ms=ts_ms,
    )
    await sink(event)


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
    system_tool_executor: SystemToolExecutor | None,
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

    if tool_name == "task":
        if system_tool_executor is None:
            tool_result = build_error_tool_result(
                error_type="system_tool_error",
                message="task executor not configured",
            )
        else:
            try:
                output_text = await system_tool_executor(tool_name, parsed_args)
                tool_result = build_completed_tool_result(output=output_text)
            except Exception as e:  # noqa: BLE001
                tool_result = build_error_tool_result(
                    error_type="system_tool_error",
                    message=str(e),
                )
    elif tool_name.startswith("mcp."):
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
                    session_key=session_key,
                )
                tool_result = build_completed_tool_result(
                    output=output_text if isinstance(output_text, str) else str(output_text)
                )
            except Exception as e:  # noqa: BLE001
                maybe_emit_resource_exhausted(
                    channel_for_tool_name(tool_name),
                    message=str(e),
                    error_type="mcp_error",
                )
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
            error_message = tr.error.message if tr.error is not None else None
            error_code = tr.error.code if tr.error is not None else None
            maybe_emit_resource_exhausted(
                channel_for_tool_name(tool_name),
                message=error_message,
                error_type=error_code or "tool_error",
            )

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
        await _emit_tool_execution_detail(
            sink=stage_event_sink,
            response_id=response_id,
            trace_id=trace_id,
            tool_call_id=call_id,
            tool_name=tool_name,
            tool_kind=tool_kind,
            arguments_json=arguments,
            output=output_value if isinstance(output_value, str) else json.dumps(output_value, ensure_ascii=False) if output_value is not None else None,
            error=error_value,
            status=tr.status,
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
        mcp_status = "completed"
        mcp_output = tool_result.get("output")
        mcp_error = None
        await _emit_tool_result(
            sink=stage_event_sink,
            response_id=response_id,
            trace_id=trace_id,
            tool_call_id=call_id,
            tool_name=tool_name,
            tool_kind=tool_kind,
            status="completed",
            output=mcp_output,
        )
    else:
        mcp_status = str(tool_result.get("status") or "error")
        mcp_output = None
        mcp_error = tool_result.get("error")
        await _emit_tool_result(
            sink=stage_event_sink,
            response_id=response_id,
            trace_id=trace_id,
            tool_call_id=call_id,
            tool_name=tool_name,
            tool_kind=tool_kind,
            status=mcp_status,
            error=mcp_error,
        )
    await _emit_tool_execution_detail(
        sink=stage_event_sink,
        response_id=response_id,
        trace_id=trace_id,
        tool_call_id=call_id,
        tool_name=tool_name,
        tool_kind=tool_kind,
        arguments_json=arguments,
        output=mcp_output if isinstance(mcp_output, str) else json.dumps(mcp_output, ensure_ascii=False) if mcp_output is not None else None,
        error=mcp_error,
        status=mcp_status,
    )
    return build_function_call_output_item(
        call_id=call_id,
        tool_result=tool_result,
        error_format="json",
    ), manifest_tools, toolset_version
