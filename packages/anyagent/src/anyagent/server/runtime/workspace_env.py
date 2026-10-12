"""Project configured runtime environment entries into the process environment."""

from __future__ import annotations

import asyncio
import os
import threading
from pathlib import Path
from typing import Any

from anyagent.config.loader import EffectiveConfig, load_effective_config
from anyagent.protocol.tool_runtime import AuthRef
from anyagent.server.security.credential_runtime import build_runtime_env_reader


def load_workspace_runtime_environment(workspace_dir: Path) -> EffectiveConfig:
    """Load config and project ``credentials.runtime_env`` into the process environment.

    When a value is written, config is loaded again so interpolated settings
    see it.
    """

    workspace = Path(workspace_dir).expanduser().resolve()
    config = load_effective_config(workspace)
    if hydrate_workspace_runtime_environment(config):
        config = load_effective_config(workspace, cli_overrides=config.cli_overrides)
    return config


def hydrate_workspace_runtime_environment(config: EffectiveConfig) -> bool:
    """Write runtime env entries. Returns True when the process environment changed."""

    return bool(_run_sync(hydrate_workspace_runtime_environment_async(config)))


async def hydrate_workspace_runtime_environment_async(config: EffectiveConfig) -> bool:
    entries = list(config.credentials.runtime_env)
    if not entries:
        return False
    if config.credentials.backend == "none":
        raise RuntimeError("workspace runtime_env requires a credential backend")
    resolver = build_runtime_env_reader(config)
    if resolver is None:
        raise RuntimeError("workspace runtime_env requires a credential backend")

    wrote = False
    for entry in entries:
        target_name = entry.name.strip()
        if not target_name:
            raise RuntimeError("workspace runtime_env entry missing name")
        if target_name in os.environ and not entry.overwrite:
            continue
        credential_id = entry.credential_id.strip()
        if not credential_id:
            raise RuntimeError(f"workspace runtime_env {target_name} missing credential_id")
        scope_context = {"agent_id": entry.agent_id} if entry.agent_id else None
        value = await resolver.resolve(AuthRef(kind=entry.kind or "api_key", ref=credential_id), scope_context=scope_context)
        if not isinstance(value, str) or not value:
            raise RuntimeError(f"workspace runtime_env credential not found: {target_name}")
        os.environ[target_name] = value
        wrote = True
    return wrote


def _run_sync(coro: Any) -> Any:
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(coro)

    result: dict[str, Any] = {}

    def _runner() -> None:
        try:
            result["value"] = asyncio.run(coro)
        except BaseException as exc:  # noqa: BLE001
            result["error"] = exc

    thread = threading.Thread(target=_runner)
    thread.start()
    thread.join()
    if "error" in result:
        raise result["error"]
    return result.get("value")
