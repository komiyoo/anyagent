from __future__ import annotations

import asyncio
import fnmatch
import time
from dataclasses import dataclass
from typing import Any

import jsonschema

from anyagent.agent_packs import AgentCatalog, AgentPack
from anyagent.protocol.agent_api_internal import (
    InternalSkillListItem,
    InternalSkillLoadError,
    InternalSkillsListResponse,
)
from anyagent.protocol.openai_responses import AnyAgentFunctionToolParam
from anyagent.protocol.sandbox import SandboxPolicy
from anyagent.protocol.tool_runtime import (
    CancelRequest,
    CancelResponse,
    ExecuteMeta,
    ExecuteRequest,
    ExecuteResponse,
    ExecuteResponseCancelled,
    ExecuteResponseCompleted,
    ExecuteResponseError,
    ManifestDecision,
    ManifestRequest,
    ManifestResponse,
    PolicyHint,
    ToolContext,
    ToolError,
)
from anyagent.server.sandbox import EXEC_TOOL, SandboxManager, build_exec_handler
from anyagent.skills import (
    SkillEnablement,
    default_skill_roots,
    discover_skills,
    requested_tool_names_for_skill,
    resolve_disabled_skill_stable_ids,
)
from anyagent.skills.discovery import SkillRoot
from anyagent.skills.models import SkillPackage
from anyagent.tool_runtime.registry import ToolRegistry


class InProcessToolRuntimeService:
    def __init__(
        self,
        *,
        workspace_dir: str,
        catalog: AgentCatalog,
        sandbox_manager: SandboxManager,
    ) -> None:
        self._workspace_dir = workspace_dir
        self._catalog = catalog
        self._sandbox_manager = sandbox_manager
        self._registry = ToolRegistry()
        self._active_calls: dict[tuple[str, str], _ActiveToolCall] = {}
        self._active_calls_lock = asyncio.Lock()
        self._idempotent_results: dict[tuple[str, str], ExecuteResponse] = {}
        self._registry.register_tool(
            EXEC_TOOL,
            build_exec_handler(
                sandbox_manager=sandbox_manager,
                sandbox_policy_for_agent=self.sandbox_policy_for_agent,
            ),
        )

    def sandbox_policy_for_agent(self, agent_id: str) -> SandboxPolicy:
        pack = self.require_pack(agent_id)
        return pack.spec.sandbox

    def require_pack(self, agent_id: str) -> AgentPack:
        pack = self._catalog.get(agent_id)
        if pack is None:
            raise KeyError(f"unknown agent_id: {agent_id}")
        return pack

    def visible_skills_for_agent(self, agent_id: str) -> tuple[list[SkillPackage], list[tuple[str, str]]]:
        pack = self.require_pack(agent_id)
        roots = [
            SkillRoot(scope="agent", root=pack.skills_dir),
            *default_skill_roots(workspace_dir=self._workspace_dir),
        ]
        return discover_skills(roots)

    async def list_skills(self, *, agent_id: str) -> InternalSkillsListResponse:
        pack = self.require_pack(agent_id)
        skills, errors = self.visible_skills_for_agent(agent_id)
        disabled_ids = resolve_disabled_skill_stable_ids(
            pack.spec.skills.disabled_paths,
            skills=skills,
            base_dir=pack.root_dir,
        )
        enablement = SkillEnablement(user_disabled_paths=disabled_ids)
        items: list[InternalSkillListItem] = []
        for skill in skills:
            items.append(
                InternalSkillListItem(
                    stable_id=skill.stable_id,
                    name=skill.frontmatter.name,
                    description=skill.frontmatter.description,
                    short_description=skill.frontmatter.metadata.short_description
                    if skill.frontmatter.metadata is not None
                    else None,
                    scope=skill.scope,
                    enabled=enablement.is_enabled(skill),
                    requested_tool_names=requested_tool_names_for_skill(skill),
                )
            )
        return InternalSkillsListResponse(
            agent_id=agent_id,
            disabled_paths=sorted(disabled_ids),
            load_errors=[
                InternalSkillLoadError(scope="agent" if path.startswith(str(pack.skills_dir)) else "global", path=path, reason=reason)
                for path, reason in errors
            ],
            skills=items,
        )

    async def manifest(self, req: ManifestRequest) -> ManifestResponse:
        if not isinstance(req.agent_id, str) or not req.agent_id.strip():
            raise ValueError("manifest requires agent_id")
        pack = self.require_pack(req.agent_id)
        tools = self._allowed_tools_for_request(pack=pack, req=req)
        return ManifestResponse(
            tools=[_tool_definition_to_param(tool) for tool in tools],
            toolset_version=self._registry.toolset_version,
            decisions=[ManifestDecision(tool_name=tool.name, decision="allow", reason="agent_policy") for tool in tools],
        )

    async def execute(self, req: ExecuteRequest) -> ExecuteResponse:
        if req.toolset_version is not None and req.toolset_version != self._registry.toolset_version:
            return ExecuteResponseError(
                status="error",
                error=ToolError(
                    type="conflict_error",
                    code="toolset_version_mismatch",
                    message=(
                        f"toolset version mismatch: got={req.toolset_version} current={self._registry.toolset_version}"
                    ),
                    retryable=True,
                ),
                meta=ExecuteMeta(),
            )
        pack = self.require_pack(req.agent_id)
        visible = {tool.name for tool in self._allowed_tools_for_request(pack=pack, req=ManifestRequest(
            agent_id=req.agent_id,
            session_key=req.session_key,
            requested_tool_names=[req.tool_name],
            context=req.context,
        ))}
        if req.tool_name not in visible:
            return ExecuteResponseError(
                status="error",
                error=ToolError(type="permission_error", code="tool_not_allowed", message=f"tool not allowed: {req.tool_name}"),
                meta=ExecuteMeta(),
            )
        registered = self._registry.get_tool(req.tool_name)
        if registered is None:
            return ExecuteResponseError(
                status="error",
                error=ToolError(type="not_found_error", code="tool_not_found", message=f"unknown tool: {req.tool_name}"),
                meta=ExecuteMeta(),
            )

        arguments = req.arguments_json
        if isinstance(arguments, str):
            import json

            arguments = json.loads(arguments)
        if not isinstance(arguments, dict):
            return ExecuteResponseError(
                status="error",
                error=ToolError(type="invalid_request_error", code="invalid_arguments", message="tool arguments must be object"),
                meta=ExecuteMeta(),
            )
        try:
            jsonschema.validate(arguments, registered.definition.parameters)
        except Exception as e:  # noqa: BLE001
            return ExecuteResponseError(
                status="error",
                error=ToolError(type="invalid_request_error", code="schema_validation_error", message=str(e)),
                meta=ExecuteMeta(),
            )

        started = time.monotonic()
        idem_key = (req.response_id, req.tool_call_id)
        handler_task = asyncio.create_task(
            registered.handler(
                arguments,
                {
                    "agent_id": req.agent_id,
                    "session_key": req.session_key,
                    "response_id": req.response_id,
                    "tool_call_id": req.tool_call_id,
                    "context": req.context.model_dump(exclude_none=True) if isinstance(req.context, ToolContext) else {},
                },
            ),
            name=f"tool-exec:{req.response_id}:{req.tool_call_id}",
        )
        existing = await self._register_or_reuse_active_call(req=req, task=handler_task)
        if existing is not None:
            handler_task.cancel()
            return existing
        try:
            output = await handler_task
        except asyncio.CancelledError:
            duration_ms = int((time.monotonic() - started) * 1000)
            result = ExecuteResponseCancelled(
                status="cancelled",
                error=ToolError(
                    type="cancelled_error",
                    code="tool_cancelled",
                    message=f"tool cancelled: {req.tool_name}",
                ),
                meta=ExecuteMeta(duration_ms=duration_ms),
            )
            await self._cache_result(idem_key=idem_key, result=result)
            return result
        except Exception as e:  # noqa: BLE001
            duration_ms = int((time.monotonic() - started) * 1000)
            result = ExecuteResponseError(
                status="error",
                error=ToolError(type="tool_execution_error", code="tool_failed", message=str(e)),
                meta=ExecuteMeta(duration_ms=duration_ms),
            )
            await self._cache_result(idem_key=idem_key, result=result)
            return result
        finally:
            await self._unregister_active_call(response_id=req.response_id, tool_call_id=req.tool_call_id)
        duration_ms = int((time.monotonic() - started) * 1000)
        result = ExecuteResponseCompleted(status="completed", output=output, meta=ExecuteMeta(duration_ms=duration_ms))
        await self._cache_result(idem_key=idem_key, result=result)
        return result

    async def cancel(self, req: CancelRequest) -> CancelResponse:
        ok = await self._cancel_active_call(response_id=req.response_id, tool_call_id=req.tool_call_id)
        return CancelResponse(ok=ok)

    async def cancel_active_for_response(self, response_id: str) -> bool:
        async with self._active_calls_lock:
            to_cancel = [call.task for key, call in self._active_calls.items() if key[0] == response_id]
        for task in to_cancel:
            task.cancel()
        return bool(to_cancel)

    async def _register_or_reuse_active_call(self, *, req: ExecuteRequest, task: asyncio.Task[str]) -> ExecuteResponse | None:
        async with self._active_calls_lock:
            idem_key = (req.response_id, req.tool_call_id)
            cached = self._idempotent_results.get(idem_key)
            if cached is not None:
                return type(cached).model_validate(cached.model_dump(exclude_none=True))
            if idem_key in self._active_calls:
                return ExecuteResponseError(
                    status="error",
                    error=ToolError(
                        type="conflict_error",
                        code="tool_execution_in_progress",
                        message=f"tool execution already in progress: {req.tool_call_id}",
                        retryable=True,
                    ),
                    meta=ExecuteMeta(),
                )
            self._active_calls[(req.response_id, req.tool_call_id)] = _ActiveToolCall(
                response_id=req.response_id,
                tool_call_id=req.tool_call_id,
                tool_name=req.tool_name,
                task=task,
            )
        return None

    async def _unregister_active_call(self, *, response_id: str, tool_call_id: str) -> None:
        async with self._active_calls_lock:
            self._active_calls.pop((response_id, tool_call_id), None)

    async def _cancel_active_call(self, *, response_id: str, tool_call_id: str) -> bool:
        async with self._active_calls_lock:
            call = self._active_calls.get((response_id, tool_call_id))
        if call is None:
            return False
        call.task.cancel()
        return True

    async def _get_cached_result(self, *, idem_key: tuple[str, str]) -> ExecuteResponse | None:
        async with self._active_calls_lock:
            result = self._idempotent_results.get(idem_key)
        if result is None:
            return None
        return type(result).model_validate(result.model_dump(exclude_none=True))

    async def _cache_result(self, *, idem_key: tuple[str, str], result: ExecuteResponse) -> None:
        async with self._active_calls_lock:
            self._idempotent_results[idem_key] = type(result).model_validate(result.model_dump(exclude_none=True))

    def _allowed_tools_for_request(self, *, pack: AgentPack, req: ManifestRequest) -> list[Any]:
        requested_patterns: list[str] = []
        requested_patterns.extend(pack.spec.tools.requested_tool_names or [])
        requested_patterns.extend(req.requested_tool_names or [])

        visible_skills, _errors = self.visible_skills_for_agent(pack.agent_id)
        if req.enabled_skills:
            skill_by_id = {skill.stable_id: skill for skill in visible_skills}
            for stable_id in req.enabled_skills:
                skill = skill_by_id.get(stable_id)
                if skill is not None:
                    requested_patterns.extend(requested_tool_names_for_skill(skill))

        effective_policy = _merge_policy_hints(_policy_hint_from_pack(pack), req.context.policy)
        allow_patterns = effective_policy.allow_tools if effective_policy is not None else None
        deny_patterns = effective_policy.deny_tools if effective_policy is not None else None

        out = []
        for tool in self._registry.list_tools():
            if tool.name == "exec" and not _exec_enabled_for_agent(pack):
                continue
            if not requested_patterns:
                continue
            if not _matches_any(tool.name, requested_patterns):
                continue
            if deny_patterns and _matches_any(tool.name, deny_patterns):
                continue
            if allow_patterns and not _matches_any(tool.name, allow_patterns):
                continue
            out.append(tool)
        return out


def _matches_any(tool_name: str, patterns: list[str]) -> bool:
    for pattern in patterns:
        if not isinstance(pattern, str) or not pattern.strip():
            continue
        pat = pattern.strip()
        if "*" in pat or "?" in pat or "[" in pat:
            if fnmatch.fnmatchcase(tool_name, pat):
                return True
            continue
        if pat.endswith("."):
            if tool_name.startswith(pat):
                return True
            continue
        if pat.endswith(".*"):
            if tool_name.startswith(pat[:-1]):
                return True
            continue
        if tool_name == pat:
            return True
    return False


def _policy_hint_from_pack(pack: AgentPack) -> PolicyHint | None:
    spec_policy = pack.spec.tools.policy
    if spec_policy is None:
        return None
    return PolicyHint(
        allow_tools=list(spec_policy.allow_tools) if isinstance(spec_policy.allow_tools, list) else None,
        deny_tools=list(spec_policy.deny_tools) if isinstance(spec_policy.deny_tools, list) else None,
    )


def _merge_policy_hints(base: PolicyHint | None, add: PolicyHint | None) -> PolicyHint | None:
    if base is None:
        return add
    if add is None:
        return base
    allow = _dedupe_patterns([*(base.allow_tools or []), *(add.allow_tools or [])])
    deny = _dedupe_patterns([*(base.deny_tools or []), *(add.deny_tools or [])])
    if not allow and not deny:
        return None
    return PolicyHint(allow_tools=allow or None, deny_tools=deny or None)


def _dedupe_patterns(patterns: list[str]) -> list[str]:
    out: list[str] = []
    seen: set[str] = set()
    for pattern in patterns:
        if not isinstance(pattern, str):
            continue
        value = pattern.strip()
        if not value or value in seen:
            continue
        seen.add(value)
        out.append(value)
    return out


def _exec_enabled_for_agent(pack: AgentPack) -> bool:
    if pack.spec.sandbox.mode == "disabled":
        return False
    requested = pack.spec.tools.requested_tool_names or []
    return any(isinstance(name, str) and name.strip() == "exec" for name in requested)


def _tool_definition_to_param(tool: Any) -> AnyAgentFunctionToolParam:
    return AnyAgentFunctionToolParam(
        name=tool.name,
        description=tool.description,
        parameters=tool.parameters,
        x_anyagent_kind=tool.kind,
    )


@dataclass(slots=True)
class _ActiveToolCall:
    response_id: str
    tool_call_id: str
    tool_name: str
    task: asyncio.Task[str]
