from __future__ import annotations

from typing import Any

from anyagent.agent_packs import AgentPack
from anyagent.agent_runtime import (
    SkillInjector,
    build_default_environment_context_values,
    resolve_skill_injection_token_budget,
)
from anyagent.protocol.tool_runtime import ManifestRequest, PolicyHint, ToolContext
from anyagent.skills import SkillEnablement, apply_skills_permissions_to_tool_context, resolve_disabled_skill_stable_ids


def _visible_enabled_skills(state: Any, *, pack: AgentPack) -> list[Any]:
    visible_skills, _errors = state.runtime.visible_skills_for_agent(pack.agent_id)
    disabled = resolve_disabled_skill_stable_ids(
        pack.spec.skills.disabled_paths,
        skills=visible_skills,
        base_dir=pack.root_dir,
    )
    enablement = SkillEnablement(user_disabled_paths=disabled)
    return [skill for skill in visible_skills if enablement.is_enabled(skill)]


def _split_csv(value: str | None) -> list[str]:
    if not isinstance(value, str):
        return []
    return [item.strip() for item in value.split(",") if item.strip()]


def _build_agent_manifest_request(
    *,
    pack: AgentPack,
    session_key: str,
    requested_tool_names: list[str] | None = None,
) -> ManifestRequest:
    context = ToolContext()
    spec_policy = pack.spec.tools.policy
    if spec_policy is not None:
        context.policy = PolicyHint(
            allow_tools=list(spec_policy.allow_tools) if isinstance(spec_policy.allow_tools, list) else None,
            deny_tools=list(spec_policy.deny_tools) if isinstance(spec_policy.deny_tools, list) else None,
        )
    return ManifestRequest(
        agent_id=pack.agent_id,
        session_key=session_key,
        requested_tool_names=list(requested_tool_names or []),
        context=context,
    )


async def _select_skills(state: Any, *, pack: AgentPack, body: dict[str, Any]) -> list[Any]:
    visible_skills = _visible_enabled_skills(state, pack=pack)
    metadata = body.get("metadata") if isinstance(body.get("metadata"), dict) else None
    result = SkillInjector(
        token_budget=resolve_skill_injection_token_budget(metadata=metadata),
    ).select_for_request(
        skills=visible_skills,
        enablement=SkillEnablement(user_disabled_paths=frozenset()),
        body=body,
        metadata=metadata,
        default_selected=pack.spec.skills.default_selected,
    )
    return result.selected_skills


def _build_server_tool_context(*, pack: AgentPack, body: dict[str, Any], selected_skills: list[Any]) -> ToolContext:
    context = _sanitize_caller_tool_context(body)
    policy = _policy_hint_for_pack(pack)
    if policy is not None:
        context = ToolContext.model_validate(
            {
                **context.model_dump(exclude_none=True),
                "policy": policy.model_dump(exclude_none=True),
            }
        )
    if selected_skills:
        context = apply_skills_permissions_to_tool_context(context, skills=selected_skills)
    return context


def _sanitize_caller_tool_context(body: dict[str, Any]) -> ToolContext:
    metadata = body.get("metadata")
    if not isinstance(metadata, dict):
        return ToolContext()
    raw = metadata.get("context")
    if not isinstance(raw, dict):
        return ToolContext()
    clean = {k: v for k, v in raw.items() if k != "policy"}
    return ToolContext.model_validate(clean)


def _policy_hint_for_pack(pack: AgentPack) -> PolicyHint | None:
    spec_policy = pack.spec.tools.policy
    if spec_policy is None:
        return None
    return PolicyHint(
        allow_tools=list(spec_policy.allow_tools) if isinstance(spec_policy.allow_tools, list) else None,
        deny_tools=list(spec_policy.deny_tools) if isinstance(spec_policy.deny_tools, list) else None,
    )


def _build_prompt_environment_values(*, state: Any, pack: AgentPack) -> dict[str, object]:
    return build_default_environment_context_values(
        cwd=state.workspace_dir,
        sandbox_mode=pack.spec.sandbox.mode,
    )
