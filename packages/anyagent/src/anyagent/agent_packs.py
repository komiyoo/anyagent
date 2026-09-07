from __future__ import annotations

import hashlib
import json
import os
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, ConfigDict, Field, model_validator
from pydantic import ValidationError

from .config_merge import ConfigMergeError, deep_merge, validate_workspace_override_denylist
from .env import getenv
from .mcp import MCPConfig
from .protocol.sandbox import SandboxPolicy
from .tool_runtime.cli_profile_spec import BANNED_COMMAND_SHELLS, CliProfileSpec


class AgentPackError(Exception):
    pass


ANYAGENT_CONFIG_DIR = ".anyagent"
ANYAGENT_AGENTS_SUBDIR = "agents"
ANYAGENT_SKILLS_SUBDIR = "skills"
ANYAGENT_SECRETS_FILE = "secrets.yaml"
ANYAGENT_CREDENTIALS_DIR = "credentials"
DEFAULT_CREDENTIAL_FILE_ROOT = f"{ANYAGENT_CONFIG_DIR}/{ANYAGENT_CREDENTIALS_DIR}"
DEFAULT_SYSTEM_CONFIG_DIR = "/etc/anyagent"

_AGENT_ID_RE = re.compile(r"^[a-zA-Z0-9_.-]{1,64}$")
_ENV_VAR_RE = re.compile(r"\$\{([A-Za-z_][A-Za-z0-9_]*)\}")
_SENSITIVE_ENV_KEY_RE = re.compile(r"(SECRET|TOKEN|PASSWORD|AUTH|KEY|CREDENTIAL|COOKIE)", re.IGNORECASE)


class AgentToolPolicy(BaseModel):
    model_config = ConfigDict(extra="ignore")

    allow_tools: list[str] | None = None
    deny_tools: list[str] | None = None


class AgentToolsSpec(BaseModel):
    model_config = ConfigDict(extra="ignore")

    requested_tool_names: list[str]
    policy: AgentToolPolicy | None = None
    cli: list[CliProfileSpec] = Field(default_factory=list)

    @staticmethod
    def _normalize_cli_path(raw: str) -> Path:
        value = raw.strip()
        if not value:
            raise ValueError("cli profile cwd must be non-empty")
        candidate = Path(value)
        if candidate.is_absolute():
            raise ValueError("cli profile cwd must stay within agent workspace")
        normalized = Path()
        for part in candidate.parts:
            if part in {"", "."}:
                continue
            if part == "..":
                raise ValueError("cli profile cwd must not traverse outside agent workspace")
            normalized /= part
        return normalized

    @classmethod
    def _validate_cli_prefix(cls, profile_name: str, prefix: str) -> None:
        stripped = prefix.strip()
        if not stripped:
            raise ValueError(f"cli profile {profile_name} has empty allow_command_prefixes entry")
        parts = stripped.split()
        for part in parts:
            lowered = part.lower()
            if lowered in BANNED_COMMAND_SHELLS:
                raise ValueError(f"cli profile {profile_name} prefix contains banned shell token: {part}")

    @classmethod
    def _validate_cli_env_set(cls, profile_name: str, values: dict[str, str]) -> None:
        for key in values:
            if _SENSITIVE_ENV_KEY_RE.search(key):
                raise ValueError(f"cli profile {profile_name} env.set contains sensitive key: {key}")

    @model_validator(mode="after")
    def _validate_cli_profiles(self) -> "AgentToolsSpec":
        for profile in self.cli:
            if not _AGENT_ID_RE.fullmatch(profile.name):
                raise ValueError(f"cli profile name must match [a-zA-Z0-9_.-]{{1,64}}: {profile.name}")
            self._normalize_cli_path(profile.cwd)
            self._validate_cli_env_set(profile.name, profile.env.set)
            for prefix in profile.allow_command_prefixes:
                self._validate_cli_prefix(profile.name, prefix)
        return self


class AgentSkillsSpec(BaseModel):
    model_config = ConfigDict(extra="ignore")

    default_selected: list[str] | None = None
    disabled_paths: list[str] | None = None


class AgentModelSpec(BaseModel):
    model_config = ConfigDict(extra="ignore")

    default: str | None = None
    provider: str = "openai"
    base_url_env: str | None = None
    api_key_env: str | None = None


class MultiAgentLimits(BaseModel):
    model_config = ConfigDict(extra="ignore")

    max_depth: int | None = Field(default=None, ge=0)
    max_threads: int | None = Field(default=None, ge=0)
    run_timeout_seconds: int | None = Field(default=None, ge=1)


class MultiAgentSpec(BaseModel):
    model_config = ConfigDict(extra="ignore")

    spawn_allow_agent_ids: list[str] | None = None
    limits: MultiAgentLimits | None = None


class SubAgentRuntimeSpec(BaseModel):
    model_config = ConfigDict(extra="ignore")

    max_concurrent: int = Field(default=3, ge=1)
    max_depth: int = Field(default=3, ge=0)
    run_timeout_seconds: int = Field(default=900, ge=1)
    default_context_mode: str = "isolated"


class LoopDetectionRuntimeSpec(BaseModel):
    model_config = ConfigDict(extra="ignore")

    enabled: bool = True
    window_size: int = Field(default=20, ge=1)
    warn_threshold: int = Field(default=3, ge=1)
    hard_limit: int = Field(default=5, ge=1)


class ContextCompactionRuntimeSpec(BaseModel):
    model_config = ConfigDict(extra="ignore")

    enabled: bool = False
    max_context_tokens: int = Field(default=128_000, ge=1)
    trigger_ratio: float = Field(default=0.8, gt=0)
    keep_recent_tokens: int = Field(default=20_000, ge=1)


class RuntimeSpec(BaseModel):
    model_config = ConfigDict(extra="ignore")

    middlewares: list[str] | None = None
    context_providers: list[str] | None = None
    subagent: SubAgentRuntimeSpec = Field(default_factory=SubAgentRuntimeSpec)
    loop_detection: LoopDetectionRuntimeSpec = Field(default_factory=LoopDetectionRuntimeSpec)
    context_compaction: ContextCompactionRuntimeSpec = Field(default_factory=ContextCompactionRuntimeSpec)


class AgentSpec(BaseModel):
    """
    AgentSpec = `<agent_pack_dir>/agent.yaml` 的结构化表示（v0 最小子集）。
    """

    model_config = ConfigDict(extra="ignore")

    exposed: bool
    model: AgentModelSpec = Field(default_factory=AgentModelSpec)
    tools: AgentToolsSpec
    skills: AgentSkillsSpec = Field(default_factory=AgentSkillsSpec)
    sandbox: SandboxPolicy = Field(default_factory=SandboxPolicy)
    multiagent: MultiAgentSpec = Field(default_factory=MultiAgentSpec)
    runtime: RuntimeSpec = Field(default_factory=RuntimeSpec)


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


def preferred_config_root(workspace_dir: Path) -> Path:
    return Path(workspace_dir) / ANYAGENT_CONFIG_DIR


def preferred_agents_root(workspace_dir: Path) -> Path:
    return preferred_config_root(workspace_dir) / ANYAGENT_AGENTS_SUBDIR


def resolve_agents_root(workspace_dir: Path) -> Path:
    return preferred_agents_root(workspace_dir)


def resolve_config_layers(workspace_dir: Path, session_overrides: dict[str, Any] | None = None) -> list[dict[str, Any]]:
    """Resolves system/user/workspace/session config roots in merge order."""
    workspace = Path(workspace_dir).expanduser().resolve()
    system_root = Path(getenv("SYSTEM_CONFIG_DIR", DEFAULT_SYSTEM_CONFIG_DIR) or DEFAULT_SYSTEM_CONFIG_DIR).expanduser()
    user_root = Path(getenv("USER_CONFIG_DIR", str(Path.home() / ANYAGENT_CONFIG_DIR)) or str(Path.home() / ANYAGENT_CONFIG_DIR)).expanduser()
    layers: list[dict[str, Any]] = [
        {"name": "system", "config_dir": system_root, "agents_dir": system_root / ANYAGENT_AGENTS_SUBDIR},
        {"name": "user", "config_dir": user_root, "agents_dir": user_root / ANYAGENT_AGENTS_SUBDIR},
        {
            "name": "workspace",
            "config_dir": preferred_config_root(workspace),
            "agents_dir": preferred_agents_root(workspace),
        },
        {"name": "session", "config": session_overrides or {}, "agents_dir": None},
    ]
    return layers


def stat_config_mtimes(workspace_dir: Path, session_overrides: dict[str, Any] | None = None) -> dict[str, float]:
    """Returns mtimes for layered agent.yaml and mcp.json files."""
    layers = resolve_config_layers(workspace_dir, session_overrides=session_overrides)
    mtimes: dict[str, float] = {}
    for agent_id in _discover_layered_agent_ids(layers):
        for layer in layers:
            agents_dir = layer.get("agents_dir")
            if not isinstance(agents_dir, Path):
                continue
            for filename in ("agent.yaml", "mcp.json"):
                candidate = agents_dir / agent_id / filename
                try:
                    stat = candidate.stat()
                except FileNotFoundError:
                    continue
                mtimes[str(candidate)] = float(stat.st_mtime_ns)
    return mtimes


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


def _load_json_object(path: Path, *, max_bytes: int) -> dict[str, Any]:
    try:
        raw, _ = _read_text_with_limit(path, max_bytes=max_bytes)
    except FileNotFoundError as e:
        raise AgentPackError(f"missing required file: {path}") from e
    try:
        obj = json.loads(raw)
    except Exception as e:  # noqa: BLE001
        raise AgentPackError(f"invalid json: {path}: {e}") from e
    if not isinstance(obj, dict):
        raise AgentPackError(f"json config must be an object: {path}")
    return obj


def _session_agent_override(session_config: dict[str, Any], agent_id: str, kind: str) -> dict[str, Any]:
    agents = session_config.get("agents")
    if not isinstance(agents, dict):
        return {}
    agent_config = agents.get(agent_id)
    if not isinstance(agent_config, dict):
        return {}
    value = agent_config.get(kind)
    return dict(value) if isinstance(value, dict) else {}


def _discover_layered_agent_ids(layers: list[dict[str, Any]]) -> list[str]:
    ids: set[str] = set()
    for layer in layers:
        agents_dir = layer.get("agents_dir")
        if isinstance(agents_dir, Path) and agents_dir.is_dir():
            for child in agents_dir.iterdir():
                if child.is_dir() and not child.name.startswith("."):
                    ids.add(child.name)
            continue
        config = layer.get("config")
        agents = config.get("agents") if isinstance(config, dict) else None
        if isinstance(agents, dict):
            ids.update(str(key) for key in agents.keys())
    return sorted(ids)


def _find_agent_file(layers: list[dict[str, Any]], agent_id: str, filename: str) -> Path | None:
    for layer in reversed(layers):
        agents_dir = layer.get("agents_dir")
        if isinstance(agents_dir, Path):
            candidate = agents_dir / agent_id / filename
            if candidate.is_file():
                return candidate
    return None


def _find_agent_root(layers: list[dict[str, Any]], agent_id: str) -> Path | None:
    for layer in reversed(layers):
        agents_dir = layer.get("agents_dir")
        if isinstance(agents_dir, Path):
            candidate = agents_dir / agent_id
            if candidate.is_dir():
                return candidate
    return None


def _merged_agent_yaml(layers: list[dict[str, Any]], agent_id: str) -> dict[str, Any]:
    merged: dict[str, Any] = {}
    for layer in layers:
        name = str(layer.get("name") or "")
        agents_dir = layer.get("agents_dir")
        source: Path | None = None
        payload: dict[str, Any] = {}
        if isinstance(agents_dir, Path):
            candidate = agents_dir / agent_id / "agent.yaml"
            if candidate.is_file():
                payload = _load_yaml_object(candidate)
                source = candidate
        else:
            payload = _session_agent_override(layer.get("config", {}), agent_id, "agent")
        if not payload:
            continue
        if name == "workspace":
            try:
                validate_workspace_override_denylist(base=merged, override=payload, source=source or Path("<session>"))
            except ConfigMergeError as e:
                raise AgentPackError(str(e)) from e
        merged = deep_merge(merged, payload)
    return merged


def _merged_mcp_config(layers: list[dict[str, Any]], agent_id: str, *, max_mcp_json_bytes: int) -> dict[str, Any] | None:
    merged: dict[str, Any] = {}
    found = False
    for layer in layers:
        agents_dir = layer.get("agents_dir")
        payload: dict[str, Any] = {}
        if isinstance(agents_dir, Path):
            candidate = agents_dir / agent_id / "mcp.json"
            if candidate.is_file():
                payload = _load_json_object(candidate, max_bytes=max_mcp_json_bytes)
        else:
            payload = _session_agent_override(layer.get("config", {}), agent_id, "mcp")
        if payload:
            merged = deep_merge(merged, payload)
            found = True
    return merged if found else None


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
    session_config_overrides: dict[str, Any] | None = None,
    max_agents_md_bytes: int = 64 * 1024,
    max_mcp_json_bytes: int = 256 * 1024,
) -> AgentCatalog:
    """
    v0：只支持单 root：
    - `<workspace_dir>/.anyagent/agents/`

    要求：
    - 每个 `<agent_id>/` 目录必须包含 `agent.yaml` 与 `AGENTS.md`
    - 解析失败必须 fail-fast（抛出异常）
    """
    workspace_dir = Path(workspace_dir).expanduser().resolve()
    workspace_env = _load_workspace_env(workspace_dir)
    expand_env = dict(workspace_env)
    expand_env.update({key: value for key, value in os.environ.items() if isinstance(value, str)})
    layers = resolve_config_layers(workspace_dir, session_overrides=session_config_overrides)
    root_dir = preferred_agents_root(workspace_dir)
    agent_ids = _discover_layered_agent_ids(layers)
    if not agent_ids:
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
    for agent_id in agent_ids:
        if not _AGENT_ID_RE.match(agent_id):
            raise AgentPackError(f"invalid agent_id directory name: {agent_id} (expected [a-zA-Z0-9_.-]{{1,64}})")

        if agent_id in packs:
            raise AgentPackError(f"duplicate agent_id: {agent_id}")

        child = _find_agent_root(layers, agent_id)
        if child is None:
            child = root_dir / agent_id
        agent_yaml = _find_agent_file(layers, agent_id, "agent.yaml")
        agents_md = _find_agent_file(layers, agent_id, "AGENTS.md")
        if agent_yaml is None:
            raise AgentPackError(f"missing required file: {child / 'agent.yaml'}")
        if agents_md is None:
            raise AgentPackError(f"missing required file: {child / 'AGENTS.md'}")

        try:
            spec = AgentSpec.model_validate(_merged_agent_yaml(layers, agent_id))
        except ValidationError as e:
            raise AgentPackError(str(e)) from e
        agents_md_text, sha256 = _read_text_with_limit(agents_md, max_bytes=max_agents_md_bytes)
        mcp_json_payload = _merged_mcp_config(layers, agent_id, max_mcp_json_bytes=max_mcp_json_bytes)
        mcp_config: MCPConfig | None = None
        if mcp_json_payload is not None:
            try:
                mcp_config = MCPConfig.model_validate(mcp_json_payload)
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
                mcp_json = _find_agent_file(layers, agent_id, "mcp.json") or (child / "mcp.json")
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
