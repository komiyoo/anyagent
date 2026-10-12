from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from fastapi import HTTPException

from anyagent.config.agents import AgentCatalog, AgentPack, load_agent_catalog, stat_config_mtimes
from anyagent.config.loader import EffectiveConfig, load_effective_config
from anyagent.gateway.plugins import GatewayRegistry
from anyagent.gateway.sequencer import KeyedSequencer
from anyagent.mcp.auth import CredentialResolver
from anyagent.mcp.manager import MCPManagerRegistry
from anyagent.plugins import LoadedPlugin
from anyagent.server.app_builders import _catalog_has_cold_restart_change
from anyagent.server.config.settings import ResolvedServerStorageSettings
from anyagent.server.persistence.manifest_cache import ManifestCache
from anyagent.server.persistence.alerts import AlertEvaluator, InMemoryAlertStore
from anyagent.server.persistence.evaluations import JsonEvaluationStore
from anyagent.server.persistence.prompt_versions import JsonPromptVersionStore
from anyagent.server.persistence.runs import RunRegistry
from anyagent.server.persistence.storage_backends import EventStore, RunStore, SessionStore
from anyagent.server.persistence.telemetry_store import (
    InMemoryObservabilityEventSink,
    TelemetryObservabilitySink,
    TelemetryStore,
)
from anyagent.server.runtime.in_process import InProcessToolRuntimeService
from anyagent.server.runtime.lock_service import SessionLockService
from anyagent.server.sandbox import SandboxManager
from anyagent.server.security import CredentialStore
from anyagent.storage.settings import StorageSettings


_LOGGER = logging.getLogger(__name__)


@dataclass(slots=True)
class AnyAgentServerApp:
    workspace_dir: Path
    catalog: AgentCatalog
    config: EffectiveConfig
    resolved_storage: ResolvedServerStorageSettings
    storage_settings: StorageSettings
    events: EventStore
    credentials: CredentialStore
    mcp_credentials: CredentialResolver | None
    sandbox_manager: SandboxManager
    runtime: InProcessToolRuntimeService
    mcp_managers: MCPManagerRegistry
    runs: RunRegistry
    manifest_cache: ManifestCache
    run_store: RunStore
    session_store: SessionStore
    telemetry_store: TelemetryStore
    alert_store: InMemoryAlertStore
    alert_evaluator: AlertEvaluator
    evaluation_store: JsonEvaluationStore
    prompt_version_store: JsonPromptVersionStore
    observability_event_sink: InMemoryObservabilityEventSink
    telemetry_event_store: Any
    telemetry_observability_sink: TelemetryObservabilitySink
    session_sequencer: KeyedSequencer
    session_lock_service: SessionLockService
    session_lease_ttl_s: float
    storage_resources: list[object] = field(default_factory=list)
    plugin_roots: list[Path] = field(default_factory=list)
    loaded_plugins: list[LoadedPlugin] = field(default_factory=list)
    loaded_plugin_catalog: list[dict[str, Any]] = field(default_factory=list)
    plugin_errors: list[dict[str, str]] = field(default_factory=list)
    gateway_registry: GatewayRegistry = field(default_factory=GatewayRegistry)
    api_key: str | None = None
    admin_api_key: str | None = None
    session_config_overrides: dict[str, Any] | None = None
    config_mtimes: dict[str, float] = field(default_factory=dict)
    config_reload_lock: asyncio.Lock = field(default_factory=asyncio.Lock)

    def require_pack(self, agent_id: str, *, external: bool) -> AgentPack:
        pack = self.catalog.get(agent_id)
        if pack is None:
            raise HTTPException(status_code=404, detail=f"unknown agent_id: {agent_id}")
        if external and not pack.spec.exposed:
            raise HTTPException(status_code=403, detail=f"agent is not exposed: {agent_id}")
        return pack

    def reload_catalog(self) -> None:
        catalog = load_agent_catalog(workspace_dir=self.workspace_dir, session_config_overrides=self.session_config_overrides)
        config = load_effective_config(self.workspace_dir, cli_overrides=self.config.cli_overrides)
        if not any(pack.spec.exposed for pack in catalog.packs.values()):
            raise RuntimeError("workspace must define at least one exposed agent")
        self.catalog = catalog
        self.config = config
        self.runtime.set_catalog(catalog)
        self.manifest_cache = ManifestCache(ttl_seconds=2.0)
        self.config_mtimes = stat_config_mtimes(self.workspace_dir, self.session_config_overrides)

    async def refresh_config_if_needed(self) -> None:
        latest = stat_config_mtimes(self.workspace_dir, self.session_config_overrides)
        if latest == self.config_mtimes:
            return
        async with self.config_reload_lock:
            latest = stat_config_mtimes(self.workspace_dir, self.session_config_overrides)
            if latest == self.config_mtimes:
                return
            catalog = load_agent_catalog(workspace_dir=self.workspace_dir, session_config_overrides=self.session_config_overrides)
            if not any(pack.spec.exposed for pack in catalog.packs.values()):
                raise RuntimeError("workspace must define at least one exposed agent")
            if _catalog_has_cold_restart_change(self.catalog, catalog):
                _LOGGER.warning("config change touches cold fields; restart required")
                self.config_mtimes = latest
                return
            self.catalog = catalog
            self.config = load_effective_config(self.workspace_dir, cli_overrides=self.config.cli_overrides)
            self.runtime.set_catalog(catalog)
            self.manifest_cache = ManifestCache(ttl_seconds=2.0)
            self.config_mtimes = latest
