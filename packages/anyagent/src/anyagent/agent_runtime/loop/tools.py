from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any

from openai.types.responses.response_function_tool_call import ResponseFunctionToolCall
from pydantic_ai import Tool
from pydantic_ai.tools import RunContext

from anyagent.mcp.manager import MCPServerManager
from anyagent.protocol.tool_manifest_extensions import source_tool_name_for_model_name, strip_internal_tool_fields
from anyagent.protocol.tool_runtime import ToolContext
from anyagent.tool_runtime.client import ToolRuntimeClient

from ..middleware import MiddlewareChain, MiddlewareContext
from ..model_providers import ModelProvider
from ..tool_execution import _execute_one_tool_with_middleware
from ..tool_results import tool_result_to_output_text


@dataclass
class LoopDeps:
    """Per-run state shared with wrapped pydantic-ai tools."""

    tool_runtime: ToolRuntimeClient
    mcp_manager: MCPServerManager | None
    agent_id: str
    session_key: str | None
    response_id: str
    toolset_version: int
    manifest_tools: list[dict[str, Any]]
    tool_context: ToolContext
    manifest_refresher: Any
    system_tool_executor: Any
    stage_event_sink: Any
    model_provider: ModelProvider | Any
    middleware_chain: MiddlewareChain | None
    middleware_context: MiddlewareContext
    execute_calls: list[str] = field(default_factory=list)


def wrap_manifest_tools(*, manifest_tools: list[dict[str, Any]]) -> list[Tool[LoopDeps]]:
    """Wrap each manifest function tool as a pydantic-ai Tool that only calls Tool Runtime execute."""

    tools: list[Tool[LoopDeps]] = []
    for spec in strip_internal_tool_fields(manifest_tools):
        if not isinstance(spec, dict) or spec.get("type") != "function":
            continue
        name = spec.get("name")
        if not isinstance(name, str) or not name.strip():
            continue
        model_name = name.strip()
        description = spec.get("description")
        schema = spec.get("parameters") if isinstance(spec.get("parameters"), dict) else {"type": "object", "properties": {}}
        tools.append(
            Tool.from_schema(
                _bind_tool(model_name, manifest_tools),
                name=model_name,
                description=description if isinstance(description, str) else model_name,
                json_schema=schema,
                takes_ctx=True,
            )
        )
    return tools


def _bind_tool(model_name: str, manifest_tools: list[dict[str, Any]]):
    async def _run(ctx: RunContext[LoopDeps], **kwargs: Any) -> str:
        deps = ctx.deps
        source_name = source_tool_name_for_model_name(deps.manifest_tools or manifest_tools, model_name)
        arguments = json.dumps(kwargs, ensure_ascii=False)
        call = ResponseFunctionToolCall(
            type="function_call",
            call_id=ctx.tool_call_id or f"call_{model_name}",
            name=model_name,
            arguments=arguments,
        )
        deps.execute_calls.append(source_name)
        out, deps.manifest_tools, deps.toolset_version = await _execute_one_tool_with_middleware(
            middleware_chain=deps.middleware_chain,
            middleware_context=deps.middleware_context,
            model_provider=deps.model_provider,
            tool_runtime=deps.tool_runtime,
            mcp_manager=deps.mcp_manager,
            agent_id=deps.agent_id,
            session_key=deps.session_key,
            response_id=deps.response_id,
            toolset_version=deps.toolset_version,
            manifest_tools=deps.manifest_tools,
            tool_context=deps.tool_context,
            manifest_refresher=deps.manifest_refresher,
            system_tool_executor=deps.system_tool_executor,
            call=call,
            stage_event_sink=deps.stage_event_sink,
        )
        if out is None:
            return ""
        if isinstance(out, dict):
            return str(out.get("output") or tool_result_to_output_text(tool_result=out, error_format="json"))
        output = getattr(out, "output", None)
        if isinstance(output, str):
            return output
        return str(out)

    _run.__name__ = model_name
    _run.__qualname__ = model_name
    return _run
