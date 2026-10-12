from __future__ import annotations

import hashlib
import json
import re
import shutil
from pathlib import Path
from typing import Any

import yaml
from fastapi import HTTPException
from pydantic import ValidationError

from anyagent.config.agents import AgentPack, AgentSpec, preferred_agents_root
from anyagent.mcp import MCPConfig
from anyagent.protocol.agent_api_internal import (
    AdminAgentConfigUpdateRequest,
    AdminAgentCreateRequest,
    AdminWorkspaceAgentFile,
    WorkspaceAgentFileKind,
)


_SKILL_DIRECTORY_RE = re.compile(r"^[a-zA-Z0-9_.-]{1,64}$")


def _workspace_agent_file_path(pack: AgentPack, *, kind: WorkspaceAgentFileKind) -> Path:
    if kind == "agents_md":
        return pack.root_dir / "AGENTS.md"
    if kind == "agent_yaml":
        return pack.root_dir / "agent.yaml"
    if kind == "mcp_json":
        return pack.root_dir / "mcp.json"
    raise HTTPException(status_code=404, detail=f"unknown editable file kind: {kind}")


def _read_workspace_agent_file(path: Path) -> tuple[bool, str | None, str | None]:
    if not path.is_file():
        return False, None, None
    raw = path.read_bytes()
    sha256 = hashlib.sha256(raw).hexdigest()
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError as e:
        raise HTTPException(status_code=400, detail=f"invalid utf-8 in workspace file: {path}: {e}") from e
    return True, sha256, text


def _workspace_agent_file(pack: AgentPack, *, kind: WorkspaceAgentFileKind) -> AdminWorkspaceAgentFile:
    path = _workspace_agent_file_path(pack, kind=kind)
    exists, sha256, text = _read_workspace_agent_file(path)
    return AdminWorkspaceAgentFile(
        kind=kind,
        path=str(path),
        exists=exists,
        sha256=sha256,
        text=text,
    )


def _validate_workspace_agent_file_text(*, kind: WorkspaceAgentFileKind, text: str) -> None:
    raw = text.encode("utf-8")
    max_bytes = 64 * 1024 if kind == "agents_md" else 256 * 1024
    if len(raw) > max_bytes:
        raise HTTPException(status_code=413, detail=f"file too large: bytes={len(raw)} max={max_bytes}")
    if kind == "agent_yaml":
        try:
            payload = yaml.safe_load(text)
            if not isinstance(payload, dict):
                raise ValueError("agent.yaml must be an object")
            AgentSpec.model_validate(payload)
        except (ValueError, ValidationError, yaml.YAMLError) as e:
            raise HTTPException(status_code=400, detail=f"invalid agent.yaml: {e}") from e
    elif kind == "mcp_json":
        if not text.strip():
            raise HTTPException(status_code=400, detail="invalid mcp.json: file must be a JSON object")
        try:
            payload = json.loads(text)
            if not isinstance(payload, dict):
                raise ValueError("mcp.json must be an object")
            MCPConfig.model_validate(payload)
        except (ValueError, ValidationError, json.JSONDecodeError) as e:
            raise HTTPException(status_code=400, detail=f"invalid mcp.json: {e}") from e


def _write_workspace_agent_file(*, path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def _restore_workspace_agent_file(*, path: Path, text: str | None, existed: bool) -> None:
    if existed:
        path.write_text(text or "", encoding="utf-8")
    elif path.exists():
        path.unlink()


def _create_agent_pack(*, state: AnyAgentServerApp, request: AdminAgentCreateRequest) -> None:
    agent_id = request.agent_id.strip()
    if not _SKILL_DIRECTORY_RE.fullmatch(agent_id):
        raise HTTPException(status_code=400, detail="invalid agent_id")
    agent_dir = preferred_agents_root(state.workspace_dir) / agent_id
    if agent_dir.exists():
        raise HTTPException(status_code=409, detail="agent already exists")
    aliases = set(state.config.models.aliases)
    stored_model = _compose_model_default(request.model_default, request.model_provider, aliases=aliases)
    spec = AgentSpec.model_validate(
        {
            "exposed": request.exposed,
            "model": {"default": stored_model} if stored_model else {},
            "tools": {"requested_tool_names": request.requested_tool_names},
            "skills": {"default_selected": request.default_selected_skills},
            "sandbox": {"mode": request.sandbox_mode},
            "multiagent": {"spawn_allow_agent_ids": request.spawn_allow_agent_ids},
        }
    )
    agent_dir.mkdir(parents=True)
    try:
        (agent_dir / "agent.yaml").write_text(yaml.safe_dump(spec.model_dump(exclude_none=True), sort_keys=False), encoding="utf-8")
        (agent_dir / "AGENTS.md").write_text(request.instructions, encoding="utf-8")
        (agent_dir / "mcp.json").write_text('{"mcpServers": {}}\n', encoding="utf-8")
        (agent_dir / "skills").mkdir()
    except Exception:
        if agent_dir.exists():
            shutil.rmtree(agent_dir)
        raise


def _update_agent_default_skills(*, state: AnyAgentServerApp, pack: AgentPack, default_selected: list[str]) -> None:
    cleaned = [item.strip() for item in default_selected if isinstance(item, str) and item.strip()]
    visible_skills, _errors = state.runtime.visible_skills_for_agent(pack.agent_id)
    by_name: dict[str, list[Any]] = {}
    by_id = {skill.stable_id: skill for skill in visible_skills}
    for skill in visible_skills:
        by_name.setdefault(skill.frontmatter.name, []).append(skill)
    normalized: list[str] = []
    for item in cleaned:
        if item in by_id:
            normalized.append(by_id[item].frontmatter.name)
            continue
        matches = by_name.get(item) or []
        if len(matches) == 1:
            normalized.append(item)
            continue
        if not matches:
            raise HTTPException(status_code=400, detail=f"unknown skill: {item}")
        raise HTTPException(status_code=400, detail=f"ambiguous skill name: {item}")
    agent_yaml_path = pack.root_dir / "agent.yaml"
    payload = yaml.safe_load(agent_yaml_path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise HTTPException(status_code=400, detail="agent.yaml must be an object")
    skills_payload = payload.get("skills")
    if not isinstance(skills_payload, dict):
        skills_payload = {}
        payload["skills"] = skills_payload
    skills_payload["default_selected"] = normalized
    AgentSpec.model_validate(payload)
    agent_yaml_path.write_text(yaml.safe_dump(payload, sort_keys=False), encoding="utf-8")


def _compose_model_default(
    model_default: str | None,
    model_provider: str | None,
    *,
    aliases: set[str],
) -> str | None:
    """Store an alias as-is. A bare model name keeps a non-openai provider in the string."""

    default = model_default.strip() if isinstance(model_default, str) else None
    default = default or None
    provider = model_provider.strip() if isinstance(model_provider, str) else None
    provider = provider or None
    if default is None:
        return None
    if default in aliases or provider in {None, "", "openai"} or ":" in default:
        return default
    return f"{provider}:{default}"


def _update_agent_config(
    *,
    pack: AgentPack,
    request: AdminAgentConfigUpdateRequest,
    aliases: set[str] | None = None,
) -> None:
    """Update common Studio-facing controls while preserving unknown agent.yaml keys."""

    agent_yaml_path = pack.root_dir / "agent.yaml"
    payload = yaml.safe_load(agent_yaml_path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise HTTPException(status_code=400, detail="agent.yaml must be an object")
    if request.exposed is not None:
        payload["exposed"] = request.exposed
    if request.model_default is not None or request.model_provider is not None:
        current = payload.get("model")
        if isinstance(current, dict):
            current_default = current.get("default")
        elif isinstance(current, str):
            current_default = current
        else:
            current_default = None
        default_value = request.model_default if request.model_default is not None else current_default
        stored = _compose_model_default(
            default_value if isinstance(default_value, str) else None,
            request.model_provider,
            aliases=aliases or set(),
        )
        if stored:
            payload["model"] = {"default": stored}
        else:
            payload.pop("model", None)
    if request.requested_tool_names is not None:
        tools_payload = payload.get("tools")
        if not isinstance(tools_payload, dict):
            tools_payload = {}
            payload["tools"] = tools_payload
        tools_payload["requested_tool_names"] = [
            item.strip() for item in request.requested_tool_names if isinstance(item, str) and item.strip()
        ]
    if request.sandbox_mode is not None:
        sandbox_payload = payload.get("sandbox")
        if not isinstance(sandbox_payload, dict):
            sandbox_payload = {}
            payload["sandbox"] = sandbox_payload
        sandbox_payload["mode"] = request.sandbox_mode
    if request.spawn_allow_agent_ids is not None:
        multiagent_payload = payload.get("multiagent")
        if not isinstance(multiagent_payload, dict):
            multiagent_payload = {}
            payload["multiagent"] = multiagent_payload
        multiagent_payload["spawn_allow_agent_ids"] = [
            item.strip() for item in request.spawn_allow_agent_ids if isinstance(item, str) and item.strip()
        ]
    if request.disabled_skill_paths is not None:
        skills_payload = payload.get("skills")
        if not isinstance(skills_payload, dict):
            skills_payload = {}
            payload["skills"] = skills_payload
        cleaned_disabled = [item.strip() for item in request.disabled_skill_paths if isinstance(item, str) and item.strip()]
        skills_payload["disabled_paths"] = cleaned_disabled
        default_selected = skills_payload.get("default_selected")
        if isinstance(default_selected, list):
            disabled_names = {Path(item).parent.name for item in cleaned_disabled}
            skills_payload["default_selected"] = [
                item
                for item in default_selected
                if not (isinstance(item, str) and (item.strip() in cleaned_disabled or item.strip() in disabled_names))
            ]
    AgentSpec.model_validate(payload)
    agent_yaml_path.write_text(yaml.safe_dump(payload, sort_keys=False), encoding="utf-8")
