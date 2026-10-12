from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import httpx

from anyagent.config.agents import AgentCatalog, AgentPackError, load_agent_catalog
from anyagent.config.schema import CredentialsConfig
from anyagent.agent_runtime.model_providers import get_default_model_provider
from anyagent.agent_runtime.multiagent import MultiAgentManager
from anyagent.gateway.sequencer import KeyedSequencer
from anyagent.mcp import MCPManagerRegistry
from anyagent.skills import default_skill_roots, discover_skills, load_skills_from_root
from anyagent.skills.models import SkillPackage
from anyagent.tool_runtime import create_tool_runtime_client

from anyagent.server.persistence.manifest_cache import ManifestCache
from anyagent.server.security.credential_runtime import build_credential_store

logger = logging.getLogger("anyagent.server.runtime.distributed_runtime")

StorageRuntimeFactory = Callable[[], Awaitable[Any]]
ModelProviderFactory = Callable[[], Any]


@dataclass(frozen=True, slots=True)
class DistributedAgentRuntimeConfig:
    workspace_dir: str | Path
    tool_runtime_base_url: str
    tool_runtime_internal_key: str
    manifest_cache_ttl_seconds: float = 5.0
    credentials: CredentialsConfig | None = None


@dataclass(slots=True)
class DistributedAgentRuntimeState:
    settings: Any
    sequencer: KeyedSequencer
    http: httpx.AsyncClient
    manifest_cache: ManifestCache
    mcp_registry: MCPManagerRegistry
    openai_provider: Any
    tool_runtime_client: Any
    mcp_credential_store: Any
    multiagent: MultiAgentManager
    storage: Any
    storage_tasks: set[asyncio.Task[object]]
    workspace_dir: Path
    agent_catalog: AgentCatalog
    global_skills: list[SkillPackage]
    global_skill_errors: list[tuple[str, str]]
    agent_skills: dict[str, list[SkillPackage]]
    agent_skill_errors: dict[str, list[tuple[str, str]]]

    def attach_to_app_state(self, app_state: Any) -> None:
        for field_name in self.__dataclass_fields__:
            setattr(app_state, field_name, getattr(self, field_name))


async def create_distributed_agent_runtime(
    *,
    config: DistributedAgentRuntimeConfig,
    storage_factory: StorageRuntimeFactory,
    settings: Any = None,
    model_provider_factory: ModelProviderFactory = get_default_model_provider,
) -> DistributedAgentRuntimeState:
    workspace_dir = Path(config.workspace_dir).expanduser().resolve()
    http = httpx.AsyncClient(timeout=None)
    mcp_registry = MCPManagerRegistry()
    storage: Any | None = None

    try:
        storage = await storage_factory()
        catalog = _load_and_validate_catalog(workspace_dir=workspace_dir)
        global_skills, global_skill_errors, agent_skills, agent_skill_errors = _discover_runtime_skills(
            workspace_dir=workspace_dir,
            catalog=catalog,
        )
        runtime = DistributedAgentRuntimeState(
            settings=settings,
            sequencer=KeyedSequencer(),
            http=http,
            manifest_cache=ManifestCache(ttl_seconds=config.manifest_cache_ttl_seconds),
            mcp_registry=mcp_registry,
            openai_provider=model_provider_factory(),
            tool_runtime_client=create_tool_runtime_client(
                base_url=str(config.tool_runtime_base_url),
                internal_key=config.tool_runtime_internal_key,
                http=http,
            ),
            mcp_credential_store=build_credential_store(
                config.credentials or CredentialsConfig(),
                workspace_dir=workspace_dir,
            ),
            multiagent=MultiAgentManager(),
            storage=storage,
            storage_tasks=set(),
            workspace_dir=workspace_dir,
            agent_catalog=catalog,
            global_skills=global_skills,
            global_skill_errors=global_skill_errors,
            agent_skills=agent_skills,
            agent_skill_errors=agent_skill_errors,
        )
    except Exception:
        if storage is not None:
            try:
                await storage.aclose()
            except Exception:  # noqa: BLE001
                pass
        await mcp_registry.cleanup_all()
        await http.aclose()
        raise

    logger.info(
        "agent packs loaded",
        extra={
            "workspace_dir": str(runtime.workspace_dir),
            "agents_root": str(runtime.agent_catalog.root_dir),
            "agents": sorted(runtime.agent_catalog.packs.keys()),
            "global_skills": len(runtime.global_skills),
            "global_skill_errors": len(runtime.global_skill_errors),
        },
    )
    return runtime


async def close_distributed_agent_runtime(runtime: DistributedAgentRuntimeState) -> None:
    try:
        await runtime.mcp_registry.cleanup_all()
    except Exception:  # noqa: BLE001
        pass
    try:
        await runtime.storage.aclose()
    except Exception:  # noqa: BLE001
        pass
    await runtime.http.aclose()


def _load_and_validate_catalog(*, workspace_dir: Path) -> AgentCatalog:
    try:
        catalog = load_agent_catalog(workspace_dir=workspace_dir)
    except AgentPackError as exc:
        raise RuntimeError(f"agent catalog load failed: {exc}") from exc

    main_pack = catalog.get("main")
    if main_pack is None:
        raise RuntimeError("agent catalog invalid: missing required agent_id=main")
    if not main_pack.spec.exposed:
        raise RuntimeError("agent catalog invalid: default agent_id=main must be exposed=true")
    return catalog


def _discover_runtime_skills(
    *,
    workspace_dir: Path,
    catalog: AgentCatalog,
) -> tuple[list[SkillPackage], list[tuple[str, str]], dict[str, list[SkillPackage]], dict[str, list[tuple[str, str]]]]:
    global_roots = default_skill_roots(workspace_dir=workspace_dir)
    global_skills, global_skill_errors = discover_skills(global_roots)

    agent_skills: dict[str, list[SkillPackage]] = {}
    agent_skill_errors: dict[str, list[tuple[str, str]]] = {}
    for agent_id, pack in catalog.packs.items():
        skills, errors = load_skills_from_root(pack.skills_dir, scope="agent")
        agent_skills[agent_id] = skills
        agent_skill_errors[agent_id] = errors
    return global_skills, global_skill_errors, agent_skills, agent_skill_errors
