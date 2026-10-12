from __future__ import annotations

from pathlib import Path

from fastapi import HTTPException

from anyagent.config.agents import AgentPack
from anyagent.config.loader import EffectiveConfig
from anyagent.config.models import resolve_effective_model_selection
from anyagent.protocol.agent_api_internal import (
    InternalAgentDetailResponse,
    InternalAgentListItem,
    InternalAgentMCPConfig,
    InternalAgentModelConfig,
    InternalAgentPromptRef,
    InternalAgentSkillsConfig,
    InternalAgentToolsConfig,
)


def _text_preview(text: str | None, *, max_chars: int = 240, limit: int | None = None) -> str | None:
    if limit is not None:
        max_chars = limit
    if not isinstance(text, str):
        return None
    compact = " ".join(text.strip().split())
    if not compact:
        return ""
    if len(compact) <= max_chars:
        return compact
    return f"{compact[: max_chars - 1]}…"


def _prompt_ref(*, path: Path | None, sha256: str | None, text: str | None, include_prompt: bool) -> InternalAgentPromptRef | None:
    if path is None or not isinstance(sha256, str) or not sha256:
        return None
    return InternalAgentPromptRef(
        path=str(path),
        sha256=sha256,
        preview=_text_preview(text),
        text=text if include_prompt else None,
    )


def _mcp_server_labels(pack: AgentPack) -> list[str]:
    if pack.mcp_config is None:
        return []
    return sorted(label for label, cfg in pack.mcp_config.mcpServers.items() if cfg.enabled)


def _resolved_model(pack: AgentPack, config: EffectiveConfig):
    return resolve_effective_model_selection(pack=pack, config=config)


def _agent_list_item(pack: AgentPack, config: EffectiveConfig) -> InternalAgentListItem:
    selection = _resolved_model(pack, config)
    return InternalAgentListItem(
        agent_id=pack.agent_id,
        name=pack.agent_id,
        exposed=pack.spec.exposed,
        root_dir=str(pack.root_dir),
        prompt_sha256=pack.agents_md_sha256,
        workspace_prompt_sha256=pack.workspace_agents_md_sha256,
        sandbox_mode=pack.spec.sandbox.mode,
        model_default=pack.spec.model.default,
        model_provider=selection.provider_name,
        model=selection.model,
        requested_tool_names=list(pack.spec.tools.requested_tool_names),
        default_selected_skill_ids=list(pack.spec.skills.default_selected or []),
        spawn_allow_agent_ids=list(pack.spec.multiagent.spawn_allow_agent_ids or []),
        has_mcp=pack.mcp_config is not None,
        mcp_server_labels=_mcp_server_labels(pack),
    )


def _agent_detail_response(pack: AgentPack, *, include_prompt: bool, config: EffectiveConfig) -> InternalAgentDetailResponse:
    agents_md = _prompt_ref(
        path=pack.agents_md_path,
        sha256=pack.agents_md_sha256,
        text=pack.agents_md_text,
        include_prompt=include_prompt,
    )
    if agents_md is None:
        raise HTTPException(status_code=500, detail=f"agent prompt metadata missing: {pack.agent_id}")
    selection = _resolved_model(pack, config)
    return InternalAgentDetailResponse(
        agent_id=pack.agent_id,
        name=pack.agent_id,
        exposed=pack.spec.exposed,
        root_dir=str(pack.root_dir),
        agents_md=agents_md,
        workspace_agents_md=_prompt_ref(
            path=pack.workspace_agents_md_path,
            sha256=pack.workspace_agents_md_sha256,
            text=pack.workspace_agents_md_text,
            include_prompt=include_prompt,
        ),
        model=InternalAgentModelConfig(
            default=pack.spec.model.default,
            provider=selection.provider_name,
            model=selection.model,
        ),
        tools=InternalAgentToolsConfig(
            requested_tool_names=list(pack.spec.tools.requested_tool_names),
            allow_tools=list(pack.spec.tools.policy.allow_tools) if pack.spec.tools.policy and pack.spec.tools.policy.allow_tools else None,
            deny_tools=list(pack.spec.tools.policy.deny_tools) if pack.spec.tools.policy and pack.spec.tools.policy.deny_tools else None,
        ),
        skills=InternalAgentSkillsConfig(
            default_selected=list(pack.spec.skills.default_selected) if pack.spec.skills.default_selected is not None else None,
            disabled_paths=list(pack.spec.skills.disabled_paths) if pack.spec.skills.disabled_paths is not None else None,
        ),
        sandbox=pack.spec.sandbox.model_dump(exclude_none=True),
        multiagent=pack.spec.multiagent.model_dump(exclude_none=True),
        mcp=InternalAgentMCPConfig(
            configured=pack.mcp_config is not None,
            server_labels=_mcp_server_labels(pack),
        ),
    )
