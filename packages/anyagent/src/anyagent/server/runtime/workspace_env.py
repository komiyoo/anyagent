"""Project configured runtime environment entries into the process environment."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from anyagent.config.loader import EffectiveConfig, load_effective_config
from anyagent.protocol.tool_runtime import AuthRef
from anyagent.server.security.credential_runtime import build_credential_store, run_credential_coro


@dataclass(frozen=True, slots=True)
class RuntimeEnvHydration:
    """One runtime_env binding. Records never carry the secret value."""

    name: str
    credential_id: str
    applied: bool = False


_LAST: tuple[RuntimeEnvHydration, ...] = ()


def last_runtime_env_hydration() -> tuple[RuntimeEnvHydration, ...]:
    """Bindings applied by the most recent hydration in this process."""

    return _LAST


def runtime_env_bindings(config: EffectiveConfig) -> list[RuntimeEnvHydration]:
    """Configured name/credential_id pairs. ``applied`` is false; values are not resolved."""

    bindings: list[RuntimeEnvHydration] = []
    for entry in config.credentials.runtime_env:
        name = entry.name.strip()
        credential_id = entry.credential_id.strip()
        if name and credential_id:
            bindings.append(RuntimeEnvHydration(name=name, credential_id=credential_id, applied=False))
    return bindings


def load_workspace_runtime_environment(workspace_dir: Path) -> EffectiveConfig:
    """Load config and project ``credentials.runtime_env`` into the process environment.

    When a value is written, config is loaded again so interpolated settings
    see it.
    """

    workspace = Path(workspace_dir).expanduser().resolve()
    config = load_effective_config(workspace)
    records = hydrate_workspace_runtime_environment(config)
    if any(record.applied for record in records):
        config = load_effective_config(workspace, cli_overrides=config.cli_overrides)
    return config


def hydrate_workspace_runtime_environment(config: EffectiveConfig) -> list[RuntimeEnvHydration]:
    """Fill missing env names from the vault. Existing names stay unless ``overwrite`` is set."""

    return list(run_credential_coro(hydrate_workspace_runtime_environment_async(config)))


async def hydrate_workspace_runtime_environment_async(config: EffectiveConfig) -> list[RuntimeEnvHydration]:
    global _LAST

    entries = list(config.credentials.runtime_env)
    if not entries:
        _LAST = ()
        return []
    if (config.credentials.backend or "none").strip().lower() in {"", "none"}:
        raise RuntimeError("workspace runtime_env requires a credential backend")
    store = build_credential_store(config.credentials, workspace_dir=config.workspace_dir)
    if store is None:
        raise RuntimeError("workspace runtime_env requires a credential backend")

    records: list[RuntimeEnvHydration] = []
    for entry in entries:
        target_name = entry.name.strip()
        if not target_name:
            raise RuntimeError("workspace runtime_env entry missing name")
        credential_id = entry.credential_id.strip()
        if not credential_id:
            raise RuntimeError(f"workspace runtime_env {target_name} missing credential_id")
        if target_name in os.environ and not entry.overwrite:
            records.append(RuntimeEnvHydration(name=target_name, credential_id=credential_id, applied=False))
            continue
        scope_context = {"agent_id": entry.agent_id} if entry.agent_id else None
        value = await store.resolve(
            AuthRef(kind=entry.kind or "api_key", ref=credential_id),
            scope_context=scope_context,
        )
        if not isinstance(value, str) or not value:
            raise RuntimeError(f"workspace runtime_env credential not found: {target_name}")
        os.environ[target_name] = value
        records.append(RuntimeEnvHydration(name=target_name, credential_id=credential_id, applied=True))
    _LAST = tuple(records)
    return records
