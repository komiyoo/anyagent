from __future__ import annotations

import hashlib
import os
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, ConfigDict, Field

from .mcp import MCPConfig
from .protocol.sandbox import SandboxPolicy


class AgentPackError(Exception):
    pass


_AGENT_ID_RE = re.compile(r"^[a-zA-Z0-9_.-]{1,64}$")
_ENV_VAR_RE = re.compile(r"\$\{([A-Za-z_][A-Za-z0-9_]*)\}")


class AgentToolPolicy(BaseModel):
    model_config = ConfigDict(extra="ignore")

    allow_tools: list[str] | None = None
    deny_tools: list[str] | None = None


class AgentToolsSpec(BaseModel):
    model_config = ConfigDict(extra="ignore")

    requested_tool_names: list[str]
    policy: AgentToolPolicy | None = None


class AgentSkillsSpec(BaseModel):
    model_config = ConfigDict(extra="ignore")

    default_selected: list[str] | None = None
    disabled_paths: list[str] | None = None


class MultiAgentLimits(BaseModel):
    model_config = ConfigDict(extra="ignore")

    max_depth: int | None = Field(default=None, ge=0)
    max_threads: int | None = Field(default=None, ge=0)
    run_timeout_seconds: int | None = Field(default=None, ge=1)


class MultiAgentSpec(BaseModel):
    model_config = ConfigDict(extra="ignore")

    spawn_allow_agent_ids: list[str] | None = None
    limits: MultiAgentLimits | None = None


class AgentSpec(BaseModel):
    """
    AgentSpec = `<agent_pack_dir>/agent.yaml` 的结构化表示（v0 最小子集）。
    """

    model_config = ConfigDict(extra="ignore")

    exposed: bool
    tools: AgentToolsSpec
    skills: AgentSkillsSpec = Field(default_factory=AgentSkillsSpec)
    sandbox: SandboxPolicy = Field(default_factory=SandboxPolicy)
    multiagent: MultiAgentSpec = Field(default_factory=MultiAgentSpec)


@dataclass(frozen=True)
class AgentPack:
    agent_id: str
    root_dir: Path
    spec: AgentSpec

    agents_md_path: Path
    agents_md_text: str
    agents_md_sha256: str
    workspace_agents_md_path: Path | None = None
    workspace_agents_md_text: str | None = None
    workspace_agents_md_sha256: str | None = None
    mcp_config: MCPConfig | None = None

    @property
    def skills_dir(self) -> Path:
        return self.root_dir / "skills"


@dataclass(frozen=True)
class AgentCatalog:
    packs: dict[str, AgentPack]
    root_dir: Path

    def get(self, agent_id: str) -> AgentPack | None:
        return self.packs.get(agent_id)


def _read_text_with_limit(path: Path, *, max_bytes: int) -> tuple[str, str]:
    raw = path.read_bytes()
    if len(raw) > max_bytes:
        raise AgentPackError(f"file too large: {path} bytes={len(raw)} max={max_bytes}")
    sha256 = hashlib.sha256(raw).hexdigest()
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError as e:
        raise AgentPackError(f"invalid utf-8: {path}: {e}") from e
    return text, sha256


def _load_yaml_object(path: Path) -> dict[str, Any]:
    try:
        raw = path.read_text(encoding="utf-8")
    except FileNotFoundError as e:
        raise AgentPackError(f"missing required file: {path}") from e
    except Exception as e:  # noqa: BLE001
        raise AgentPackError(f"failed to read: {path}: {e}") from e

    try:
        obj = yaml.safe_load(raw)
    except Exception as e:  # noqa: BLE001
        raise AgentPackError(f"invalid yaml: {path}: {e}") from e
    if not isinstance(obj, dict):
        raise AgentPackError(f"agent.yaml must be an object: {path}")
    return obj


def _load_workspace_env(workspace_dir: Path) -> dict[str, str]:
    env: dict[str, str] = {}
    for candidate in (workspace_dir / ".env", workspace_dir / ".env.local"):
        if not candidate.is_file():
            continue
        for raw_line in candidate.read_text(encoding="utf-8").splitlines():
            line = raw_line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, value = line.split("=", 1)
            key = key.strip()
            value = value.strip()
            if key:
                env[key] = value
    return env


def _expand_env_placeholders(value: str, env: dict[str, str]) -> str:
    return _ENV_VAR_RE.sub(lambda match: env.get(match.group(1), ""), value)


def load_agent_catalog(
    *,
    workspace_dir: Path,
    max_agents_md_bytes: int = 64 * 1024,
    max_mcp_json_bytes: int = 256 * 1024,
) -> AgentCatalog:
    """
    v0：只支持单 root：
    - `<workspace_dir>/.agents/agents/`

    要求：
    - 每个 `<agent_id>/` 目录必须包含 `agent.yaml` 与 `AGENTS.md`
    - 解析失败必须 fail-fast（抛出异常）
    """
    workspace_dir = Path(workspace_dir).expanduser().resolve()
    workspace_env = _load_workspace_env(workspace_dir)
    expand_env = dict(workspace_env)
    expand_env.update({key: value for key, value in os.environ.items() if isinstance(value, str)})
    root_dir = workspace_dir / ".agents" / "agents"
    if not root_dir.is_dir():
        raise AgentPackError(f"missing agent packs root: {root_dir}")

    workspace_agents_md = workspace_dir / "AGENTS.md"
    workspace_agents_md_path: Path | None = None
    workspace_agents_md_text: str | None = None
    workspace_agents_md_sha256: str | None = None
    if workspace_agents_md.is_file():
        workspace_agents_md_text, workspace_agents_md_sha256 = _read_text_with_limit(
            workspace_agents_md,
            max_bytes=max_agents_md_bytes,
        )
        workspace_agents_md_path = workspace_agents_md

    packs: dict[str, AgentPack] = {}
    for child in sorted(root_dir.iterdir(), key=lambda p: p.name):
        if not child.is_dir():
            continue
        if child.name.startswith("."):
            continue

        agent_id = child.name
        if not _AGENT_ID_RE.match(agent_id):
            raise AgentPackError(f"invalid agent_id directory name: {agent_id} (expected [a-zA-Z0-9_.-]{{1,64}})")

        if agent_id in packs:
            raise AgentPackError(f"duplicate agent_id: {agent_id}")

        agent_yaml = child / "agent.yaml"
        agents_md = child / "AGENTS.md"
        if not agent_yaml.is_file():
            raise AgentPackError(f"missing required file: {agent_yaml}")
        if not agents_md.is_file():
            raise AgentPackError(f"missing required file: {agents_md}")

        spec = AgentSpec.model_validate(_load_yaml_object(agent_yaml))
        agents_md_text, sha256 = _read_text_with_limit(agents_md, max_bytes=max_agents_md_bytes)
        mcp_json = child / "mcp.json"
        mcp_config: MCPConfig | None = None
        if mcp_json.is_file():
            mcp_raw, _ = _read_text_with_limit(mcp_json, max_bytes=max_mcp_json_bytes)
            try:
                mcp_config = MCPConfig.model_validate_json(mcp_raw)
                for server_cfg in mcp_config.mcpServers.values():
                    if server_cfg.command and not server_cfg.cwd:
                        server_cfg.cwd = str(workspace_dir)
                    if isinstance(server_cfg.command, str):
                        server_cfg.command = _expand_env_placeholders(server_cfg.command, expand_env)
                    if isinstance(server_cfg.args, list):
                        server_cfg.args = [
                            _expand_env_placeholders(item, expand_env) if isinstance(item, str) else item
                            for item in server_cfg.args
                        ]
                    if isinstance(server_cfg.cwd, str):
                        server_cfg.cwd = _expand_env_placeholders(server_cfg.cwd, expand_env)
                    if isinstance(server_cfg.env, dict):
                        server_cfg.env = {
                            key: _expand_env_placeholders(value, expand_env) if isinstance(value, str) else value
                            for key, value in server_cfg.env.items()
                        }
            except Exception as e:  # noqa: BLE001
                raise AgentPackError(f"invalid mcp.json: {mcp_json}: {e}") from e

        packs[agent_id] = AgentPack(
            agent_id=agent_id,
            root_dir=child,
            spec=spec,
            agents_md_path=agents_md,
            agents_md_text=agents_md_text,
            agents_md_sha256=sha256,
            workspace_agents_md_path=workspace_agents_md_path,
            workspace_agents_md_text=workspace_agents_md_text,
            workspace_agents_md_sha256=workspace_agents_md_sha256,
            mcp_config=mcp_config,
        )

    return AgentCatalog(packs=packs, root_dir=root_dir)
