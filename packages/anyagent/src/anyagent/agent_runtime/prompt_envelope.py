from __future__ import annotations

import hashlib
import json
from datetime import datetime
import os
from pathlib import Path

from anyagent.agent_packs import AgentPack
from anyagent.protocol.context_fragments import ContextFragment, ContextFragmentRole
from anyagent.protocol.mcp import MCPServerConfig
from anyagent.protocol.prompt_context import (
    PromptContextAudit,
    PromptEnvelope,
    RenderedPromptFragment,
    apply_prompt_envelope_to_body as _apply_prompt_envelope_to_body,
    build_prompt_audit_metadata as _build_prompt_audit_metadata,
    render_prompt_envelope_fragments as _render_prompt_envelope_fragments,
)
from anyagent.protocol.tool_runtime import ToolContext
from anyagent.skills import requested_tool_names_for_skill
from anyagent.skills.models import SkillPackage

_PROMPT_ENVELOPE_PROTOCOL_VERSION = "v0"


def build_workspace_agents_md_fragment(pack: AgentPack, *, role: ContextFragmentRole = "developer") -> ContextFragment | None:
    if not (
        isinstance(pack.workspace_agents_md_text, str)
        and pack.workspace_agents_md_text.strip()
        and isinstance(pack.workspace_agents_md_path, Path)
        and isinstance(pack.workspace_agents_md_sha256, str)
        and pack.workspace_agents_md_sha256.strip()
    ):
        return None
    return ContextFragment(
        kind="agents_instructions",
        role=role,
        cache_class="stable_prefix",
        label="workspace",
        stable_id="agents://workspace",
        source_path=str(pack.workspace_agents_md_path),
        source_hash=pack.workspace_agents_md_sha256,
        scope="workspace",
        body=pack.workspace_agents_md_text.rstrip(),
    )


def build_agents_md_fragment(pack: AgentPack, *, role: ContextFragmentRole = "developer") -> ContextFragment:
    return ContextFragment(
        kind="agents_instructions",
        role=role,
        cache_class="stable_prefix",
        label=f"agent:{pack.agent_id}",
        stable_id=f"agents://{pack.agent_id}",
        source_path=str(pack.agents_md_path),
        source_hash=pack.agents_md_sha256,
        scope="agent-pack",
        body=(pack.agents_md_text or "").rstrip(),
        metadata={"agent_id": pack.agent_id},
    )


def build_agents_instructions_fragment(pack: AgentPack, *, role: ContextFragmentRole = "developer") -> ContextFragment:
    return build_agents_md_fragment(pack, role=role)


def build_skill_fragment(skill: SkillPackage, *, role: ContextFragmentRole = "developer") -> ContextFragment:
    requested_tools = requested_tool_names_for_skill(skill)
    metadata = {"name": skill.frontmatter.name}
    if requested_tools:
        metadata["requested_tools"] = ",".join(requested_tools)
    return ContextFragment(
        kind="skill",
        role=role,
        cache_class="contextual",
        stable_id=skill.stable_id,
        source_path=str(skill.skill_md_path),
        source_hash=_sha256_text(skill.body_markdown),
        scope=skill.scope,
        body=(skill.body_markdown or "").rstrip(),
        metadata=metadata,
    )


def build_environment_context_fragment(*, values: dict[str, object], role: ContextFragmentRole = "developer") -> ContextFragment:
    body_lines: list[str] = []
    for key, value in values.items():
        if value is None:
            continue
        body_lines.append(f"<{key}>{value}</{key}>")
    return ContextFragment(
        kind="environment_context",
        role=role,
        cache_class="contextual",
        stable_id="environment://runtime",
        body="\n".join(["<environment_context>", *body_lines, "</environment_context>"]).rstrip(),
    )


def build_mcp_server_ref_fragments(pack: AgentPack, *, role: ContextFragmentRole = "developer") -> list[ContextFragment]:
    if pack.mcp_config is None:
        return []
    out: list[ContextFragment] = []
    for label, server_cfg in sorted(pack.mcp_config.mcpServers.items()):
        if not server_cfg.enabled:
            continue
        out.append(build_mcp_server_ref_fragment(label=label, server_cfg=server_cfg, role=role))
    return out


def build_mcp_server_ref_fragment(
    *,
    label: str,
    server_cfg: MCPServerConfig,
    role: ContextFragmentRole = "developer",
) -> ContextFragment:
    transport = server_cfg.infer_transport().value
    lines = [
        "<mcp_server_ref>",
        f"<label>{label}</label>",
        f"<transport>{transport}</transport>",
    ]
    if isinstance(server_cfg.url, str) and server_cfg.url.strip():
        lines.append(f"<url>{server_cfg.url.strip()}</url>")
    if isinstance(server_cfg.command, str) and server_cfg.command.strip():
        lines.append(f"<command>{server_cfg.command.strip()}</command>")
    lines.append("</mcp_server_ref>")
    metadata = {"label": label, "transport": transport}
    return ContextFragment(
        kind="mcp_server_ref",
        role=role,
        cache_class="stable_prefix",
        label=label,
        stable_id=f"mcp://{label}",
        scope="agent-pack",
        body="\n".join(lines),
        metadata=metadata,
    )


def build_sandbox_guidance_fragment(pack: AgentPack, *, role: ContextFragmentRole = "developer") -> ContextFragment | None:
    if not _sandbox_exec_enabled(pack):
        return None
    filesystem = pack.spec.sandbox.filesystem
    workspace_root = filesystem.workspace_root if filesystem is not None else "/workspace"
    persistence_mode = filesystem.persistence_mode if filesystem is not None else "ephemeral"
    lines = [
        "<sandbox_guidance>",
        f"<mode>{pack.spec.sandbox.mode}</mode>",
        f"<workspace_root>{workspace_root}</workspace_root>",
        f"<persistence_mode>{persistence_mode}</persistence_mode>",
        "<exec_tool>exec</exec_tool>",
        "Use the exec tool to run shell commands inside the sandbox.",
        f"Write files under {workspace_root} when you want the session workspace to retain them.",
        "The sandbox does not expose host credentials, private internal services, or raw secret values.",
        "</sandbox_guidance>",
    ]
    return ContextFragment(
        kind="sandbox_guidance",
        role=role,
        cache_class="stable_prefix",
        label="sandbox",
        stable_id=f"sandbox://{pack.agent_id}",
        scope="agent-pack",
        body="\n".join(lines),
        metadata={
            "mode": pack.spec.sandbox.mode,
            "workspace_root": workspace_root,
            "persistence_mode": persistence_mode,
            "tool": "exec",
        },
    )


def build_default_environment_context_values(*, cwd: Path | str | None, sandbox_mode: str | None) -> dict[str, object]:
    shell_value = os.environ.get("SHELL") or ""
    shell_name = Path(shell_value).name if shell_value else None
    now = datetime.now().astimezone()
    tz_name = os.environ.get("TZ") or now.tzname() or str(now.tzinfo) or None
    values: dict[str, object] = {
        "cwd": str(cwd) if cwd is not None else None,
        "shell": shell_name,
        "current_date": now.date().isoformat(),
        "timezone": tz_name,
    }
    if isinstance(sandbox_mode, str) and sandbox_mode.strip():
        values["sandbox_mode"] = sandbox_mode.strip()
    return values


def build_prompt_envelope(
    *,
    pack: AgentPack,
    selected_skills: list[SkillPackage] | None,
    tool_context: ToolContext | None = None,
    model: str | None = None,
    environment_values: dict[str, object] | None = None,
    context_fragments: list[ContextFragment] | None = None,
    instruction_role: ContextFragmentRole = "developer",
) -> PromptEnvelope:
    fragments: list[ContextFragment] = []
    workspace_fragment = build_workspace_agents_md_fragment(pack, role=instruction_role)
    if workspace_fragment is not None:
        fragments.append(workspace_fragment)
    fragments.append(build_agents_md_fragment(pack, role=instruction_role))
    fragments.extend(build_mcp_server_ref_fragments(pack, role=instruction_role))
    sandbox_fragment = build_sandbox_guidance_fragment(pack, role=instruction_role)
    if sandbox_fragment is not None:
        fragments.append(sandbox_fragment)
    for skill in selected_skills or []:
        fragments.append(build_skill_fragment(skill, role=instruction_role))
    fragments.extend(context_fragments or [])
    if environment_values:
        fragments.append(build_environment_context_fragment(values=environment_values, role=instruction_role))
    return PromptEnvelope(
        prompt_cache_key=build_prompt_cache_key(
            pack=pack,
            selected_skills=selected_skills or [],
            tool_context=tool_context,
            model=model,
            fragments=fragments,
        ),
        fragments=tuple(fragments),
    )


def apply_prompt_envelope_to_body(*, body: dict, envelope: PromptEnvelope) -> dict:
    return _apply_prompt_envelope_to_body(body=body, envelope=envelope)


def build_prompt_cache_key(
    *,
    pack: AgentPack,
    selected_skills: list[SkillPackage],
    tool_context: ToolContext | None,
    model: str | None,
    fragments: list[ContextFragment],
) -> str:
    policy = None
    if tool_context is not None and tool_context.policy is not None:
        policy = tool_context.policy.model_dump(exclude_none=True)
    payload = {
        "protocol_version": _PROMPT_ENVELOPE_PROTOCOL_VERSION,
        "model": model.strip() if isinstance(model, str) and model.strip() else None,
        "agent_id": pack.agent_id,
        "agents_md_sha256": pack.agents_md_sha256,
        "sandbox": pack.spec.sandbox.model_dump(exclude_none=True),
        "tool_policy": policy,
        "requested_tool_names": list(pack.spec.tools.requested_tool_names or []),
        "selected_skills": [
            {
                "stable_id": skill.stable_id,
                "path": str(skill.skill_md_path),
                "sha256": _sha256_text(skill.body_markdown),
                "requested_tool_names": requested_tool_names_for_skill(skill),
            }
            for skill in selected_skills
        ],
        "fragments": [
            {
                "kind": fragment.kind,
                "cache_class": fragment.cache_class,
                "stable_id": fragment.stable_id,
                "source_path": fragment.source_path,
                "source_hash": fragment.source_hash,
                "scope": fragment.scope,
                "metadata": dict(fragment.metadata),
            }
            for fragment in fragments
            if fragment.cache_class == "stable_prefix"
        ],
        "mcp_servers": sorted(label for label, cfg in pack.mcp_config.mcpServers.items() if cfg.enabled)
        if pack.mcp_config is not None
        else [],
    }
    dumped = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(dumped.encode("utf-8")).hexdigest()


def _sha256_text(text: str) -> str:
    return hashlib.sha256((text or "").encode("utf-8")).hexdigest()


def build_prompt_audit_metadata(*, envelope: PromptEnvelope) -> PromptContextAudit:
    return _build_prompt_audit_metadata(envelope=envelope)


def render_prompt_envelope_fragments(*, envelope: PromptEnvelope) -> list[RenderedPromptFragment]:
    return _render_prompt_envelope_fragments(envelope=envelope)


def _sandbox_exec_enabled(pack: AgentPack) -> bool:
    if pack.spec.sandbox.mode == "disabled":
        return False
    requested = pack.spec.tools.requested_tool_names or []
    return any(isinstance(item, str) and item.strip() == "exec" for item in requested)
