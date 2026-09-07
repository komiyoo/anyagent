from __future__ import annotations

import json
import logging
import os
import uuid
from collections.abc import AsyncIterator, Iterable
from contextlib import contextmanager
from typing import Any

from pydantic_ai import Agent
from pydantic_ai.exceptions import ModelHTTPError, UserError
from pydantic_ai.usage import UsageLimits

from anyagent.mcp.manager import MCPServerManager
from anyagent.model_config import ModelConfigError
from anyagent.protocol.openai_responses import build_minimal_openai_response_json, validate_tool_choice
from anyagent.protocol.sse import encode_sse_event, normalize_response_id
from anyagent.protocol.tool_manifest_extensions import strip_internal_tool_fields
from anyagent.protocol.tool_runtime import ToolContext
from anyagent.skills.models import SkillPackage
from anyagent.tool_runtime.client import ToolRuntimeClient

from ..middleware import MiddlewareChain, MiddlewareContext
from ..model_providers import (
    ModelProvider,
    ModelProviderInvalidRequestError,
    ModelProviderTransportError,
    ModelProviderUpstreamError,
)
from ..skills_injection import inject_skills_into_responses_body
from ..tool_execution import (
    ManifestRefresher,
    ManifestResolver,
    StageEventSink,
    SystemToolExecutor,
    resolve_manifest_with_mcp,
)
from ..tool_loop_payloads import extract_allowed_function_tool_names
from .hooks import capabilities_from_middleware_chain
from .models import (
    ModelProviderBridgeModel,
    extract_instructions_from_body,
    model_settings_from_body,
    resolve_pydantic_ai_model,
    split_user_prompt_and_history,
)
from .otel import build_instrumentation_capabilities
from .tools import LoopDeps, wrap_manifest_tools

_LOGGER = logging.getLogger(__name__)


def _fresh_uuid4() -> uuid.UUID:
    return uuid.UUID(bytes=os.urandom(16), version=4)


@contextmanager
def _stdlib_uuid4() -> Any:
    """Keep pydantic-ai graph node IDs unique if a test patched uuid.uuid4."""

    current = uuid.uuid4
    uuid.uuid4 = _fresh_uuid4
    try:
        yield
    finally:
        uuid.uuid4 = current


async def _agent_run(agent: Agent[Any, str], *args: Any, **kwargs: Any) -> Any:
    with _stdlib_uuid4():
        return await agent.run(*args, **kwargs)


def _strip_anyagent_request_metadata(body: dict[str, Any]) -> dict[str, Any]:
    provider_body = dict(body)
    provider_body.pop("metadata", None)
    provider_body.pop("tenant_id", None)
    provider_body.pop("agent_id", None)
    provider_body.pop("session_key", None)
    return provider_body


async def _prepare_loop_state(
    *,
    model_provider: ModelProvider | Any,
    tool_runtime: ToolRuntimeClient,
    agent_id: str,
    session_key: str | None,
    body: dict[str, Any],
    canonical_response_id: str | None,
    tool_context: ToolContext | None,
    selected_skills: list[SkillPackage] | None,
    manifest_resolver: ManifestResolver | None,
    mcp_manager: MCPServerManager | None,
    stage_event_sink: StageEventSink | None,
    prompt_envelope_applied: bool,
    middleware_chain: MiddlewareChain | None,
) -> tuple[dict[str, Any], list[dict[str, Any]], int, str, MiddlewareContext]:
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
            stage_event_sink=stage_event_sink,
            stage_response_id=canonical_response_id,
        )
    allowed_tool_names = extract_allowed_function_tool_names(manifest_tools=manifest_tools)
    err = validate_tool_choice(body.get("tool_choice"), allowed_tool_names)
    if err is not None:
        raise ModelProviderInvalidRequestError(err)
    prepared = _strip_anyagent_request_metadata(body)
    prepared["tools"] = strip_internal_tool_fields(manifest_tools)
    if selected_skills and not prompt_envelope_applied:
        prepared, _warnings = inject_skills_into_responses_body(
            body=prepared,
            selected_skills=selected_skills,
            role="developer",
        )
    response_id = canonical_response_id or "resp_anyagent"
    middleware_context = MiddlewareContext(
        agent_id=agent_id,
        session_key=session_key,
        iter_index=0,
        response_id=response_id,
        canonical_response_id=response_id,
        stage_event_sink=stage_event_sink,
        metadata=metadata if isinstance(metadata, dict) else None,
        model_provider=model_provider,
    )
    return prepared, manifest_tools, toolset_version, response_id, middleware_context


def _build_agent(
    *,
    model_provider: Any,
    body: dict[str, Any],
    manifest_tools: list[dict[str, Any]],
    agent_id: str,
    session_key: str | None,
    response_id: str,
    max_iters: int,
    middleware_chain: MiddlewareChain | None,
    tracer_provider: Any | None,
    idempotency_key: str | None = None,
) -> tuple[Agent[Any, str], str | None, list[Any] | None, Any]:
    instructions = extract_instructions_from_body(body)
    user_prompt, history = split_user_prompt_and_history(body)
    model = resolve_pydantic_ai_model(model_provider, body=body)
    if isinstance(model, ModelProviderBridgeModel):
        model._original_body = dict(body)
        model._idempotency_key = idempotency_key
    tools = wrap_manifest_tools(manifest_tools=manifest_tools)
    capabilities: list[Any] = []
    capabilities.extend(capabilities_from_middleware_chain(middleware_chain, response_id=response_id))
    capabilities.extend(
        build_instrumentation_capabilities(
            agent_id=agent_id,
            session_key=session_key,
            response_id=response_id,
            tracer_provider=tracer_provider,
        )
    )
    with _stdlib_uuid4():
        agent = Agent(
            model,
            instructions=instructions or None,
            deps_type=LoopDeps,
            tools=tools,
            model_settings=model_settings_from_body(body),
            capabilities=capabilities or None,
            name=agent_id,
            end_strategy="early",
        )
    _ = max_iters, instructions
    return agent, user_prompt, history, model


def _final_response_id(canonical: str | None, model: Any, fallback: str) -> str:
    if isinstance(canonical, str) and canonical.strip():
        return canonical.strip()
    first = getattr(model, "_first_response_id", None)
    if isinstance(first, str) and first.strip():
        return first.strip()
    return fallback


def _response_payload(
    *,
    response_id: str,
    model: str,
    text: str,
    tools: list[dict[str, Any]],
    tool_choice: Any,
) -> dict[str, Any]:
    payload = build_minimal_openai_response_json(
        response_id=response_id,
        status="completed",
        model=model,
        tools=tools,
        tool_choice=tool_choice if tool_choice is not None else "auto",
        output=[
            {
                "id": f"msg_{response_id}",
                "type": "message",
                "role": "assistant",
                "status": "completed",
                "content": [{"type": "output_text", "text": text, "annotations": []}],
            }
        ],
    )
    normalize_response_id(payload, response_id)
    return payload


def _map_run_error(exc: BaseException, *, followup: bool) -> tuple[int, dict[str, Any]]:
    if isinstance(exc, ModelProviderInvalidRequestError):
        return 400, {"error": {"message": exc.message, "type": "invalid_request_error"}}
    if isinstance(exc, ModelConfigError):
        return 400, {"error": {"message": str(exc), "type": "invalid_request_error"}}
    if isinstance(exc, UserError):
        return 400, {"error": {"message": str(exc), "type": "invalid_request_error"}}
    if isinstance(exc, ModelProviderUpstreamError):
        if followup:
            return 502, {
                "error": {
                    "message": f"tool loop follow-up model call failed: upstream_{exc.status_code}: {exc.message}",
                    "type": "tool_loop_incomplete",
                }
            }
        if isinstance(exc.body, dict):
            return exc.status_code, exc.body
        return exc.status_code, {"error": {"message": exc.message or "upstream_error", "type": "upstream_error"}}
    if isinstance(exc, ModelProviderTransportError):
        if followup:
            return 502, {
                "error": {
                    "message": f"tool loop follow-up model call failed: transport: {exc.message}",
                    "type": "tool_loop_incomplete",
                }
            }
        return 502, {"error": {"message": exc.message, "type": "upstream_error"}}
    if isinstance(exc, ModelHTTPError):
        if followup:
            return 502, {
                "error": {
                    "message": f"tool loop follow-up model call failed: upstream_{exc.status_code}: {exc}",
                    "type": "tool_loop_incomplete",
                }
            }
        if isinstance(exc.body, dict):
            return exc.status_code, exc.body
        return exc.status_code, {"error": {"message": str(exc), "type": "upstream_error"}}
    _LOGGER.warning("pydantic-ai loop failed: %s", exc, exc_info=True)
    return 500, {"error": {"message": str(exc), "type": "server_error"}}


async def run_tool_loop_nonstream(
    *,
    model_provider: ModelProvider | Any,
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
    system_tool_executor: SystemToolExecutor | None = None,
    middleware_chain: MiddlewareChain | None = None,
    tracer_provider: Any | None = None,
) -> tuple[int, dict[str, Any]]:
    try:
        prepared, manifest_tools, toolset_version, response_id, middleware_context = await _prepare_loop_state(
            model_provider=model_provider,
            tool_runtime=tool_runtime,
            agent_id=agent_id,
            session_key=session_key,
            body=body,
            canonical_response_id=canonical_response_id,
            tool_context=tool_context,
            selected_skills=selected_skills,
            manifest_resolver=manifest_resolver,
            mcp_manager=mcp_manager,
            stage_event_sink=stage_event_sink,
            prompt_envelope_applied=prompt_envelope_applied,
            middleware_chain=middleware_chain,
        )
    except ModelProviderInvalidRequestError as e:
        return 400, {"error": {"message": e.message, "type": "invalid_request_error"}}
    except ModelConfigError as e:
        return 400, {"error": {"message": str(e), "type": "invalid_request_error"}}

    prepared["stream"] = False
    try:
        agent, user_prompt, history, pai_model = _build_agent(
            model_provider=model_provider,
            body=prepared,
            manifest_tools=manifest_tools,
            agent_id=agent_id,
            session_key=session_key,
            response_id=response_id,
            max_iters=max_iters,
            middleware_chain=middleware_chain,
            tracer_provider=tracer_provider,
            idempotency_key=idempotency_key,
        )
    except ModelConfigError as e:
        return 400, {"error": {"message": str(e), "type": "invalid_request_error"}}

    deps = LoopDeps(
        tool_runtime=tool_runtime,
        mcp_manager=mcp_manager,
        agent_id=agent_id,
        session_key=session_key,
        response_id=response_id,
        toolset_version=toolset_version,
        manifest_tools=manifest_tools,
        tool_context=tool_context or ToolContext(),
        manifest_refresher=manifest_force_refresh,
        system_tool_executor=system_tool_executor,
        stage_event_sink=stage_event_sink,
        model_provider=model_provider,
        middleware_chain=middleware_chain,
        middleware_context=middleware_context,
    )
    try:
        result = await _agent_run(agent,
            user_prompt,
            deps=deps,
            message_history=history,
            conversation_id=session_key,
            run_id=response_id,
            usage_limits=UsageLimits(request_limit=max(1, max_iters)),
        )
    except Exception as e:  # noqa: BLE001
        followup = getattr(pai_model, "_last_response", None) is not None
        return _map_run_error(e, followup=followup)

    text = result.output if isinstance(result.output, str) else str(result.output)
    model_name = prepared.get("model") if isinstance(prepared.get("model"), str) else "unknown"
    payload = _response_payload(
        response_id=_final_response_id(canonical_response_id, pai_model, response_id),
        model=str(model_name),
        text=text,
        tools=list(prepared.get("tools") or []),
        tool_choice=prepared.get("tool_choice"),
    )
    return 200, payload


async def run_tool_loop_stream_buffered(
    *,
    model_provider: ModelProvider | Any,
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
    system_tool_executor: SystemToolExecutor | None = None,
    middleware_chain: MiddlewareChain | None = None,
    tracer_provider: Any | None = None,
) -> tuple[int, Iterable[bytes]]:
    chunks: list[bytes] = []
    try:
        async for chunk in run_tool_loop_stream_live(
            model_provider=model_provider,
            tool_runtime=tool_runtime,
            agent_id=agent_id,
            session_key=session_key,
            body=body,
            idempotency_key=idempotency_key,
            canonical_response_id=canonical_response_id,
            tool_context=tool_context,
            selected_skills=selected_skills,
            manifest_resolver=manifest_resolver,
            manifest_force_refresh=manifest_force_refresh,
            mcp_manager=mcp_manager,
            max_iters=max_iters,
            stage_event_sink=stage_event_sink,
            prompt_envelope_applied=prompt_envelope_applied,
            system_tool_executor=system_tool_executor,
            middleware_chain=middleware_chain,
            tracer_provider=tracer_provider,
        ):
            chunks.append(chunk)
    except ModelProviderInvalidRequestError as e:
        return 400, [encode_sse_event("error", json.dumps({"error": {"message": e.message, "type": "invalid_request_error"}}))]
    except ModelProviderUpstreamError as e:
        raw = e.raw if isinstance(e.raw, (bytes, bytearray)) else None
        return e.status_code, [raw or json.dumps(e.body or {"error": {"message": "upstream_error"}}).encode("utf-8")]
    except ModelProviderTransportError as e:
        return 502, [json.dumps({"error": {"message": e.message, "type": "upstream_error"}}, ensure_ascii=False).encode("utf-8")]
    return 200, chunks


async def run_tool_loop_stream_live(
    *,
    model_provider: ModelProvider | Any,
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
    system_tool_executor: SystemToolExecutor | None = None,
    middleware_chain: MiddlewareChain | None = None,
    tracer_provider: Any | None = None,
) -> AsyncIterator[bytes]:
    try:
        prepared, manifest_tools, toolset_version, response_id, middleware_context = await _prepare_loop_state(
            model_provider=model_provider,
            tool_runtime=tool_runtime,
            agent_id=agent_id,
            session_key=session_key,
            body=body,
            canonical_response_id=canonical_response_id,
            tool_context=tool_context,
            selected_skills=selected_skills,
            manifest_resolver=manifest_resolver,
            mcp_manager=mcp_manager,
            stage_event_sink=stage_event_sink,
            prompt_envelope_applied=prompt_envelope_applied,
            middleware_chain=middleware_chain,
        )
    except ModelProviderInvalidRequestError:
        raise
    prepared["stream"] = True
    agent, user_prompt, history, pai_model = _build_agent(
        model_provider=model_provider,
        body=prepared,
        manifest_tools=manifest_tools,
        agent_id=agent_id,
        session_key=session_key,
        response_id=response_id,
        max_iters=max_iters,
        middleware_chain=middleware_chain,
        tracer_provider=tracer_provider,
        idempotency_key=idempotency_key,
    )
    deps = LoopDeps(
        tool_runtime=tool_runtime,
        mcp_manager=mcp_manager,
        agent_id=agent_id,
        session_key=session_key,
        response_id=response_id,
        toolset_version=toolset_version,
        manifest_tools=manifest_tools,
        tool_context=tool_context or ToolContext(),
        manifest_refresher=manifest_force_refresh,
        system_tool_executor=system_tool_executor,
        stage_event_sink=stage_event_sink,
        model_provider=model_provider,
        middleware_chain=middleware_chain,
        middleware_context=middleware_context,
    )
    try:
        result = await _agent_run(agent,
            user_prompt,
            deps=deps,
            message_history=history,
            conversation_id=session_key,
            run_id=response_id,
            usage_limits=UsageLimits(request_limit=max(1, max_iters)),
        )
    except Exception as e:  # noqa: BLE001
        status, payload = _map_run_error(e, followup=False)
        if status >= 400:
            if isinstance(e, (ModelProviderInvalidRequestError, ModelProviderUpstreamError, ModelProviderTransportError)):
                raise
            yield encode_sse_event(
                "error",
                json.dumps(payload, ensure_ascii=False),
            )
            yield encode_sse_event(None, "[DONE]")
            return
        raise
    text = result.output if isinstance(result.output, str) else str(result.output)
    model_name = prepared.get("model") if isinstance(prepared.get("model"), str) else "unknown"
    response_id = _final_response_id(canonical_response_id, pai_model, response_id)
    payload = _response_payload(
        response_id=response_id,
        model=str(model_name),
        text=text,
        tools=list(prepared.get("tools") or []),
        tool_choice=prepared.get("tool_choice"),
    )
    if text:
        delta = {
            "type": "response.output_text.delta",
            "sequence_number": 1,
            "item_id": f"msg_{response_id}",
            "output_index": 0,
            "content_index": 0,
            "delta": text,
            "logprobs": [],
        }
        normalize_response_id(delta, response_id)
        yield encode_sse_event("response.output_text.delta", json.dumps(delta, ensure_ascii=False, separators=(",", ":")))
    completed = {"type": "response.completed", "sequence_number": 2, "response": payload}
    normalize_response_id(completed, response_id)
    yield encode_sse_event("response.completed", json.dumps(completed, ensure_ascii=False, separators=(",", ":")))
    yield encode_sse_event(None, "[DONE]")
