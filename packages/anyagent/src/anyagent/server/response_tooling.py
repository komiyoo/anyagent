from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import httpx

from anyagent.agent_packs import AgentPack
from anyagent.agent_runtime import (
    build_default_environment_context_values,
    build_prompt_envelope,
    dedupe_strs,
    extract_allowed_function_tool_names,
)
from anyagent.mcp import MCPManagerRegistry, MCPServerManager
from anyagent.protocol.openai_responses import validate_tool_choice
from anyagent.protocol.tool_manifest_extensions import strip_internal_tool_fields
from anyagent.protocol.tool_runtime import PolicyHint, ToolContext
from anyagent.skills import (
    SkillEnablement,
    apply_skills_permissions_to_tool_context,
    dedupe_skills_by_name,
    extract_user_texts_from_responses_request,
    requested_tool_names_for_skills,
    resolve_disabled_skill_stable_ids,
    select_skills,
)
from anyagent.skills.models import SkillPackage
from anyagent.tool_runtime import ToolRuntimeClient, fetch_manifest_tools as default_fetch_manifest_tools

from .manifest_cache import ManifestCache, ManifestCacheKey, build_manifest_cache_key, extract_requested_tool_names
from .request_validation import ResponsesRequestValidationError, parse_function_tools

logger = logging.getLogger("anyagent.server.response_tooling")

FetchManifestToolsFn = Callable[..., Awaitable[tuple[list[dict[str, Any]], int]]]


@dataclass(frozen=True)
class ResponseToolingContext:
    body: dict[str, Any]
    selected_skills: list[SkillPackage]
    skill_decisions: list[Any]
    enabled_skills: list[str]
    requested_tools: list[dict[str, Any]] | None
    requested_tool_names: list[str]
    tool_context: ToolContext
    context: dict[str, Any]
    manifest_cache_key: ManifestCacheKey
    manifest_tools: list[dict[str, Any]]
    toolset_version: int
    system_tools: list[Any]
    mcp_manager: MCPServerManager | None
    prompt_envelope: Any
    prompt_audit: Any
    manifest_resolver: Callable[[], Awaitable[tuple[list[dict[str, Any]], int]]]
    manifest_force_refresh: Callable[[], Awaitable[tuple[list[dict[str, Any]], int]]]


class ResponseToolingContextError(Exception):
    def __init__(
        self,
        status_code: int,
        *,
        message: str,
        type_: str = "invalid_request_error",
    ) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.message = message
        self.type = type_


def _dump_tool_param(tool: Any) -> dict[str, Any]:
    if isinstance(tool, dict):
        return dict(tool)
    if hasattr(tool, "model_dump"):
        return tool.model_dump(exclude_none=True)
    raise TypeError(f"unsupported tool param type: {type(tool).__name__}")


async def prepare_response_tooling_context(
    *,
    body: dict[str, Any],
    metadata: dict[str, Any] | None,
    pack: AgentPack,
    agent_id: str,
    session_key: str,
    workspace_dir: Path,
    agent_skills: dict[str, list[SkillPackage]],
    global_skills: list[SkillPackage],
    manifest_cache: ManifestCache,
    tool_runtime: ToolRuntimeClient,
    mcp_registry: MCPManagerRegistry,
    mcp_credential_store: Any,
    multiagent: Any,
    fetch_manifest_tools_fn: FetchManifestToolsFn = default_fetch_manifest_tools,
) -> ResponseToolingContext:
    all_skills, _duplicate_skills = dedupe_skills_by_name(
        [*agent_skills.get(agent_id, []), *global_skills]
    )
    disabled = resolve_disabled_skill_stable_ids(
        pack.spec.skills.disabled_paths,
        skills=all_skills,
        base_dir=workspace_dir,
    )

    enablement = SkillEnablement(user_disabled_paths=disabled)
    user_texts = extract_user_texts_from_responses_request(body)
    selected_skills, skill_decisions = select_skills(
        skills=all_skills,
        enablement=enablement,
        metadata=metadata if isinstance(metadata, dict) else None,
        user_texts=user_texts,
        default_selected=pack.spec.skills.default_selected,
        allow_implicit_invocation=False,
    )
    enabled_skills = [s.stable_id for s in selected_skills]

    try:
        request_tools = parse_function_tools(body.get("tools"))
    except ResponsesRequestValidationError as e:
        raise ResponseToolingContextError(400, message=str(e), type_="invalid_request_error") from e

    requested_tools = [t.model_dump(exclude_none=True) for t in (request_tools or [])] or None
    requested_from_request = extract_requested_tool_names(requested_tools) or []
    requested_from_agent = pack.spec.tools.requested_tool_names or []
    requested_from_skills = requested_tool_names_for_skills(selected_skills)
    requested_tool_names = dedupe_strs([*requested_from_agent, *requested_from_skills, *requested_from_request])

    raw_context = metadata.get("context") if isinstance(metadata, dict) else None
    raw_context = raw_context if isinstance(raw_context, dict) else {}
    raw_context = dict(raw_context)
    raw_context.pop("policy", None)

    try:
        tool_context = ToolContext.model_validate(raw_context)
    except Exception:  # noqa: BLE001
        tool_context = ToolContext()

    pol = pack.spec.tools.policy
    if pol is not None:
        allow = dedupe_strs(pol.allow_tools or [])
        deny = dedupe_strs(pol.deny_tools or [])
        if allow or deny:
            tool_context = ToolContext.model_validate(
                {
                    **tool_context.model_dump(exclude_none=True),
                    "policy": PolicyHint(
                        allow_tools=allow or None,
                        deny_tools=deny or None,
                    ).model_dump(exclude_none=True),
                }
            )

    tool_context = apply_skills_permissions_to_tool_context(tool_context, skills=selected_skills)
    context = tool_context.model_dump(exclude_none=True)
    manifest_cache_key = build_manifest_cache_key(
        tenant_id=None,
        agent_id=agent_id,
        session_key=session_key,
        enabled_skills=enabled_skills or None,
        requested_tool_names=requested_tool_names,
        context=context,
    )

    mcp_manager: MCPServerManager | None = None
    if pack.mcp_config is not None:
        try:
            mcp_manager = await mcp_registry.get_manager(
                agent_id=agent_id,
                mcp_config=pack.mcp_config,
                credential_store=mcp_credential_store,
            )
        except Exception as e:  # noqa: BLE001
            logger.warning(
                "mcp manager init failed; proceeding without mcp tools",
                extra={"agent_id": agent_id, "error": str(e)},
            )

    async def _load_mcp_tools() -> list[dict[str, Any]]:
        if mcp_manager is None:
            return []
        try:
            return await mcp_manager.list_all_tools()
        except Exception as e:  # noqa: BLE001
            logger.warning(
                "mcp list_all_tools failed; proceeding without mcp tools",
                extra={"agent_id": agent_id, "error": str(e)},
            )
            return []

    cached = await manifest_cache.get(manifest_cache_key)
    if cached is not None:
        manifest_tools, toolset_version = cached
    else:
        try:
            manifest_tools, toolset_version = await fetch_manifest_tools_fn(
                tool_runtime=tool_runtime,
                agent_id=agent_id,
                session_key=session_key,
                enabled_skills=enabled_skills or None,
                requested_tool_names=requested_tool_names,
                requested_tools=requested_tools,
                context=context,
            )
        except httpx.HTTPError as e:
            raise ResponseToolingContextError(
                502,
                message=f"Tool Runtime manifest error: {e}",
                type_="upstream_error",
            ) from e
        except Exception as e:  # noqa: BLE001
            raise ResponseToolingContextError(
                502,
                message=f"Tool Runtime manifest error: {e}",
                type_="upstream_error",
            ) from e

        await manifest_cache.put(manifest_cache_key, (manifest_tools, toolset_version))

    mcp_tools = await _load_mcp_tools()
    if mcp_tools:
        manifest_tools = [*manifest_tools, *mcp_tools]

    system_tools = list(multiagent.system_tools_for_pack(pack))
    if system_tools:
        manifest_tools = [*manifest_tools, *[_dump_tool_param(t) for t in system_tools]]

    allowed_tool_names = extract_allowed_function_tool_names(manifest_tools=manifest_tools)
    err = validate_tool_choice(body.get("tool_choice"), allowed_tool_names)
    if err is not None:
        raise ResponseToolingContextError(400, message=err, type_="invalid_request_error")

    body["tools"] = strip_internal_tool_fields(manifest_tools)

    prompt_envelope = build_prompt_envelope(
        pack=pack,
        selected_skills=selected_skills,
        tool_context=tool_context,
        model=body.get("model") if isinstance(body.get("model"), str) else None,
        environment_values=build_default_environment_context_values(
            cwd=workspace_dir,
            sandbox_mode=pack.spec.sandbox.mode,
        ),
    )
    prompt_audit = prompt_envelope.audit_metadata()
    body = prompt_envelope.apply_to_body(body=body)

    async def _manifest_for_session() -> tuple[list[dict[str, Any]], int]:
        return manifest_tools, toolset_version

    async def _refresh_manifest_for_session() -> tuple[list[dict[str, Any]], int]:
        manifest_tools2, toolset_version2 = await fetch_manifest_tools_fn(
            tool_runtime=tool_runtime,
            agent_id=agent_id,
            session_key=session_key,
            enabled_skills=enabled_skills or None,
            requested_tool_names=requested_tool_names,
            requested_tools=requested_tools,
            context=context,
        )
        await manifest_cache.put(manifest_cache_key, (manifest_tools2, toolset_version2))
        mcp_tools2 = await _load_mcp_tools()
        if mcp_tools2:
            manifest_tools2 = [*manifest_tools2, *mcp_tools2]
        if system_tools:
            manifest_tools2 = [*manifest_tools2, *[_dump_tool_param(t) for t in system_tools]]
        return manifest_tools2, toolset_version2

    return ResponseToolingContext(
        body=body,
        selected_skills=selected_skills,
        skill_decisions=list(skill_decisions),
        enabled_skills=enabled_skills,
        requested_tools=requested_tools,
        requested_tool_names=requested_tool_names,
        tool_context=tool_context,
        context=context,
        manifest_cache_key=manifest_cache_key,
        manifest_tools=manifest_tools,
        toolset_version=toolset_version,
        system_tools=system_tools,
        mcp_manager=mcp_manager,
        prompt_envelope=prompt_envelope,
        prompt_audit=prompt_audit,
        manifest_resolver=_manifest_for_session,
        manifest_force_refresh=_refresh_manifest_for_session,
    )
