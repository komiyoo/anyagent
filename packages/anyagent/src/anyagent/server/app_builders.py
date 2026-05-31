from __future__ import annotations

import asyncio
import logging
import os
from pathlib import Path
from typing import Any

from anyagent.agent_packs import AgentCatalog
from anyagent.plugins import LoadedPlugin, load_plugins_from_roots
from anyagent.plugins.hooks import HookContext
from anyagent.plugins.models import PluginManifest
from anyagent.protocol.observability import ObservabilityLevel
from anyagent.protocol.plugins import PluginToolRef
from anyagent.server.runtime.in_process import InProcessToolRuntimeService
from anyagent.server.sandbox import OpenSandboxWorkspaceBackend
from anyagent.tool_runtime.plugins import ToolRuntimePluginAPI


_LOGGER = logging.getLogger(__name__)


def _build_opensandbox_backend_if_needed(catalog: AgentCatalog) -> OpenSandboxWorkspaceBackend | None:
    if not any(pack.spec.sandbox.mode == "opensandbox" for pack in catalog.packs.values()):
        return None
    return OpenSandboxWorkspaceBackend(
        base_url=(os.getenv("OPENSANDBOX_BASE_URL") or "").strip(),
        api_key=(os.getenv("OPENSANDBOX_API_KEY") or "").strip() or None,
        workspace_root=(os.getenv("SANDBOX_WORKSPACE_ROOT") or "/workspace").strip() or "/workspace",
        image=(os.getenv("OPENSANDBOX_IMAGE") or "ubuntu:24.04").strip() or "ubuntu:24.04",
        sandbox_timeout_s=int(os.getenv("OPENSANDBOX_TIMEOUT_S") or "3600"),
        cpu_limit=(os.getenv("OPENSANDBOX_CPU_LIMIT") or "1000m").strip() or "1000m",
        memory_limit=(os.getenv("OPENSANDBOX_MEMORY_LIMIT") or "1Gi").strip() or "1Gi",
        proxy_port=int(os.getenv("OPENSANDBOX_PROXY_PORT") or "44772"),
    )


def _catalog_has_cold_restart_change(current: AgentCatalog, candidate: AgentCatalog) -> bool:
    if set(current.packs) != set(candidate.packs):
        return False
    for agent_id, current_pack in current.packs.items():
        candidate_pack = candidate.packs[agent_id]
        if current_pack.spec.sandbox != candidate_pack.spec.sandbox:
            return True
    return False


def _safe_error_message(e: Exception) -> str:
    msg = getattr(e, "message", None)
    if isinstance(msg, str) and msg.strip():
        return msg
    return str(e) or type(e).__name__


def _parse_cors_origins(value: str | list[str] | tuple[str, ...] | None) -> list[str]:
    if value is None:
        value = os.getenv("ANYAGENT_CORS_ORIGINS", "")
    if isinstance(value, str):
        return [item.strip() for item in value.split(",") if item.strip()]
    return [str(item).strip() for item in value if str(item).strip()]


def _resolve_plugin_roots(plugin_roots: list[str | Path] | tuple[str | Path, ...] | None, *, workspace: Path) -> list[Path]:
    raw_items: list[str | Path] = []
    if plugin_roots is not None:
        raw_items.extend(plugin_roots)
    else:
        env_value = os.getenv("ANYAGENT_PLUGIN_ROOTS", "")
        raw_items.extend(item.strip() for item in env_value.split(",") if item.strip())

    roots: list[Path] = []
    seen: set[str] = set()
    for raw_item in raw_items:
        path = Path(raw_item).expanduser()
        if not path.is_absolute():
            path = workspace / path
        resolved = path.resolve()
        key = str(resolved)
        if key in seen:
            continue
        seen.add(key)
        roots.append(resolved)
    return roots


def _load_gateway_plugins(
    *,
    runtime: InProcessToolRuntimeService,
    roots: list[Path],
    fail_open: bool,
) -> tuple[list[LoadedPlugin], list[dict[str, str]], list[dict[str, Any]]]:
    if not roots:
        return [], [], []

    tools_by_plugin: dict[str, list[Any]] = {}
    loaded, errors = load_plugins_from_roots(
        roots,
        api_factory=lambda manifest, plugin_dir, config: _build_gateway_plugin_api(
            runtime=runtime,
            manifest=manifest,
            config=config,
            tools_by_plugin=tools_by_plugin,
        ),
    )
    error_payload = [{"plugin_dir": plugin_dir, "reason": reason} for plugin_dir, reason in errors]
    for item in error_payload:
        _LOGGER.error("plugin load error: %s: %s", item["plugin_dir"], item["reason"])
    if error_payload and not fail_open:
        raise RuntimeError(f"plugin load failed ({len(error_payload)} errors); set --plugins-fail-open to ignore")

    catalog_payload = [
        _loaded_plugin_catalog_item(item=item, tools=tools_by_plugin.get(item.manifest.plugin_id, []))
        for item in loaded
    ]
    if catalog_payload:
        _LOGGER.info("gateway plugins loaded: %s", ", ".join(sorted(item["plugin_id"] for item in catalog_payload)))
    return loaded, error_payload, catalog_payload


def _build_gateway_plugin_api(
    *,
    runtime: InProcessToolRuntimeService,
    manifest: PluginManifest,
    config: dict[str, Any],
    tools_by_plugin: dict[str, list[Any]],
) -> ToolRuntimePluginAPI:
    registered_tools: list[Any] = []
    tools_by_plugin[manifest.plugin_id] = registered_tools
    return ToolRuntimePluginAPI(
        host_kind="gateway",
        plugin_id=manifest.plugin_id,
        config=config,
        registry=runtime._registry,
        registered_tools=registered_tools,
    )


def _loaded_plugin_catalog_item(*, item: LoadedPlugin, tools: list[Any]) -> dict[str, Any]:
    entrypoint = item.manifest.entrypoint or "plugin.py:register"
    return {
        "plugin_id": item.manifest.plugin_id,
        "description": item.manifest.description,
        "channels": list(item.manifest.channels),
        "plugin_dir": str(item.plugin_dir),
        "entrypoint": entrypoint,
        "tools": [
            PluginToolRef(
                name=tool.name,
                category=tool.category,
                kind=tool.kind,
                description=tool.description,
            ).model_dump(mode="json", exclude_none=True)
            for tool in tools
        ],
        "declared_skills": list(item.declared_skills),
        "declared_mcp_servers": list(item.declared_mcp_servers),
        "declared_middlewares": list(item.manifest.middlewares),
        "declared_hooks": sorted(item.manifest.hooks),
        "cite": {
            "manifest": str(item.plugin_dir / "plugin.json"),
            "entrypoint": str(item.plugin_dir / _entrypoint_path(entrypoint)),
        },
        "docs": _resolve_plugin_refs(item.plugin_dir, item.manifest.docs),
        "schemas": _resolve_plugin_refs(item.plugin_dir, item.manifest.schemas),
        "tests": _resolve_plugin_refs(item.plugin_dir, item.manifest.tests),
    }


def _entrypoint_path(entrypoint: str) -> Path:
    relpath, _sep, _attr = entrypoint.partition(":")
    return Path(relpath)


def _resolve_plugin_refs(plugin_dir: Path, refs: list[str]) -> list[str]:
    resolved: list[str] = []
    seen: set[str] = set()
    for raw in refs:
        if not isinstance(raw, str) or not raw.strip():
            continue
        value = raw.strip()
        if "://" in value:
            ref = value
        else:
            path = Path(value)
            ref = str(path if path.is_absolute() else plugin_dir / path)
        if ref in seen:
            continue
        seen.add(ref)
        resolved.append(ref)
    return resolved


async def _dispatch_plugin_hook(
    state: Any,
    name: str,
    *,
    agent_id: str,
    session_key: str | None,
    response_id: str,
    metadata: dict[str, Any] | None = None,
) -> None:
    if not state.loaded_plugins:
        return
    context = HookContext(agent_id=agent_id, session_key=session_key, response_id=response_id, metadata=metadata)
    for plugin in state.loaded_plugins:
        hook = plugin.hooks.get(name)
        if hook is None:
            continue
        try:
            result = hook(context)
            if asyncio.iscoroutine(result):
                await result
        except Exception as exc:  # noqa: BLE001
            _LOGGER.warning("plugin hook failed: plugin_id=%s hook=%s error=%s", plugin.manifest.plugin_id, name, exc)
