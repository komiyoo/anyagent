from __future__ import annotations

import asyncio
import logging
from pathlib import Path
from typing import Any

from dataclasses import dataclass
from typing import Callable

from anyagent.config.agents import AgentCatalog
from anyagent.config.schema import SandboxConfig
from anyagent.gateway.plugins import GatewayPluginAPI, GatewayRegistry, WebhookRoute
from anyagent.plugins import LoadedPlugin, load_plugins_from_roots
from anyagent.plugins.hooks import HookContext
from anyagent.plugins.models import PluginManifest
from anyagent.plugins.api import PluginAPIBase
from anyagent.protocol.observability import ObservabilityLevel
from anyagent.protocol.plugins import PluginToolRef
from anyagent.server.runtime.in_process import InProcessToolRuntimeService
from anyagent.server.sandbox import OpenSandboxWorkspaceBackend
from anyagent.tool_runtime.models import ToolDefinition, ToolHandler
from anyagent.tool_runtime.plugins import ToolRuntimePluginAPI


_LOGGER = logging.getLogger(__name__)


@dataclass(frozen=True)
class _DualHostPluginAPI(PluginAPIBase):
    """Combined host API: Gateway + Tool Runtime 双宿主。

    插件可以在同一个 register(api) 调用中同时注册：
    - 工具（通过 ToolRuntimePluginAPI）
    - 渠道/通道（通过 GatewayPluginAPI 的 registerChannel）
    - Webhook 路由（通过 GatewayPluginAPI 的 registerWebhookRoute）
    """

    tool_runtime_api: ToolRuntimePluginAPI
    gateway_api: GatewayPluginAPI

    def registerChannel(self, connector: Any) -> None:  # noqa: N802
        self.gateway_api.registerChannel(connector)

    def registerTool(  # noqa: N802
        self,
        tool_or_factory: ToolDefinition | Callable[[], tuple[ToolDefinition, ToolHandler]],
        handler: ToolHandler | None = None,
    ) -> None:
        self.tool_runtime_api.registerTool(tool_or_factory, handler)

    def registerWebhookRoute(self, route: Any) -> None:  # noqa: N802
        if isinstance(route, WebhookRoute):
            self.gateway_api.registerWebhookRoute(route)
        else:
            # 允许插件传入 dict/args，框架自动转为 WebhookRoute
            if isinstance(route, dict):
                webhook_route = WebhookRoute(
                    path=route["path"],
                    channel=route.get("channel"),
                    methods=tuple(route.get("methods", ["POST"])),
                    handler=route["handler"],
                )
            else:
                webhook_route = WebhookRoute(
                    path=getattr(route, "path", "/"),
                    channel=getattr(route, "channel", None),
                    methods=tuple(getattr(route, "methods", ["POST"])),
                    handler=getattr(route, "handler", lambda **kw: None),
                )
            self.gateway_api.registerWebhookRoute(webhook_route)


def _build_opensandbox_backend_if_needed(
    catalog: AgentCatalog,
    sandbox: SandboxConfig | None = None,
) -> OpenSandboxWorkspaceBackend | None:
    if not any(pack.spec.sandbox.mode == "opensandbox" for pack in catalog.packs.values()):
        return None
    settings = sandbox.opensandbox if sandbox is not None else None
    root = sandbox.workspace_root if sandbox is not None else "/workspace"
    return OpenSandboxWorkspaceBackend(
        base_url=((settings.base_url if settings is not None else None) or "").strip(),
        api_key=((settings.api_key if settings is not None else None) or "").strip() or None,
        workspace_root=(root or "/workspace").strip() or "/workspace",
        image=((settings.image if settings is not None else None) or "ubuntu:24.04").strip() or "ubuntu:24.04",
        sandbox_timeout_s=int(settings.timeout_s if settings is not None else 3600),
        cpu_limit=((settings.cpu_limit if settings is not None else None) or "1000m").strip() or "1000m",
        memory_limit=((settings.memory_limit if settings is not None else None) or "1Gi").strip() or "1Gi",
        proxy_port=int(settings.proxy_port if settings is not None else 44772),
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
        return []
    if isinstance(value, str):
        return [item.strip() for item in value.split(",") if item.strip()]
    return [str(item).strip() for item in value if str(item).strip()]


_BUILTIN_PLUGIN_DIRS = {
    "chatwoot": "chatwoot_connector",
    "chatwoot-connector": "chatwoot_connector",
    "chatwoot_connector": "chatwoot_connector",
    "lifecycle_echo": "lifecycle_echo",
    "lifecycle-echo": "lifecycle_echo",
    "anyagent.lifecycle_echo": "lifecycle_echo",
}


def resolve_builtin_plugin_roots(names: list[str] | None, *, fail_open: bool) -> list[Path]:
    """Resolve opt-in built-in plugin names to their package directories.

    The default list is empty. ``plugins.roots`` that point at the builtin
    package directory still scan every plugin under that directory.
    """

    if not names:
        return []
    try:
        import anyagent.plugins.builtin as builtin_pkg
    except ImportError:
        message = "built-in plugins package is not importable"
        if fail_open:
            _LOGGER.error(message)
            return []
        raise RuntimeError(message) from None
    package_paths = getattr(builtin_pkg, "__path__", None)
    if not package_paths:
        message = "built-in plugins package is not importable"
        if fail_open:
            _LOGGER.error(message)
            return []
        raise RuntimeError(message)
    root = Path(next(iter(package_paths))).resolve()
    resolved: list[Path] = []
    seen: set[str] = set()
    for raw in names:
        name = str(raw).strip()
        if not name:
            continue
        folder = _BUILTIN_PLUGIN_DIRS.get(name)
        if folder is None:
            message = f"unknown built-in plugin {name!r}; expected one of: chatwoot, lifecycle_echo"
            if fail_open:
                _LOGGER.error(message)
                continue
            raise RuntimeError(message)
        path = (root / folder).resolve()
        if not (path / "plugin.json").is_file():
            message = f"built-in plugin {name!r} is missing plugin.json at {path}"
            if fail_open:
                _LOGGER.error(message)
                continue
            raise RuntimeError(message)
        key = str(path)
        if key in seen:
            continue
        seen.add(key)
        resolved.append(path)
    return resolved


def _resolve_plugin_roots(plugin_roots: list[str | Path] | tuple[str | Path, ...] | None, *, workspace: Path) -> list[Path]:
    raw_items: list[str | Path] = []
    if plugin_roots:
        raw_items.extend(plugin_roots)
    else:
        default_root = workspace / "plugins"
        if default_root.is_dir():
            raw_items.append(default_root)

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
    gateway_registry: GatewayRegistry | None = None,
    config_overrides: dict[str, dict[str, Any]] | None = None,
) -> tuple[list[LoadedPlugin], list[dict[str, str]], list[dict[str, Any]]]:
    if not roots:
        return [], [], []

    tools_by_plugin: dict[str, list[Any]] = {}
    gateway_registry = gateway_registry or GatewayRegistry()
    overrides = config_overrides or {}

    def api_factory(manifest: PluginManifest, plugin_dir: Path, config: dict[str, Any]) -> _DualHostPluginAPI:
        merged = dict(config or {})
        override = overrides.get(manifest.plugin_id)
        if override:
            merged.update(override)
        return _build_dual_host_plugin_api(
            runtime=runtime,
            manifest=manifest,
            config=merged,
            tools_by_plugin=tools_by_plugin,
            gateway_registry=gateway_registry,
        )

    loaded, errors = load_plugins_from_roots(roots, api_factory=api_factory)
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
    if gateway_registry.channel_connectors:
        _LOGGER.info(
            "registered channel connectors: %s",
            ", ".join(sorted(gateway_registry.channel_connectors.keys())),
        )
    if gateway_registry.webhook_routes:
        _LOGGER.info(
            "registered webhook routes: %s",
            ", ".join(route.path for route in gateway_registry.webhook_routes),
        )
    return loaded, error_payload, catalog_payload


def _build_dual_host_plugin_api(
    *,
    runtime: InProcessToolRuntimeService,
    manifest: PluginManifest,
    config: dict[str, Any],
    tools_by_plugin: dict[str, list[Any]],
    gateway_registry: GatewayRegistry,
) -> _DualHostPluginAPI:
    """创建双宿主插件 API（Gateway + Tool Runtime）。

    插件可以通过同一个 api 对象同时注册：
    - api.registerTool(...)       → Tool Runtime 注册工具
    - api.registerChannel(...)    → Gateway 注册 connector
    - api.registerWebhookRoute(...) → Gateway 注册 webhook 路由
    """
    registered_tools: list[Any] = []
    tools_by_plugin[manifest.plugin_id] = registered_tools

    tool_runtime_api = ToolRuntimePluginAPI(
        host_kind="tool_runtime",
        plugin_id=manifest.plugin_id,
        config=config,
        registry=runtime._registry,
        registered_tools=registered_tools,
    )

    gateway_api = GatewayPluginAPI(
        host_kind="gateway",
        plugin_id=manifest.plugin_id,
        config=config,
        registry=gateway_registry,
    )

    return _DualHostPluginAPI(
        host_kind="gateway",
        plugin_id=manifest.plugin_id,
        config=config,
        tool_runtime_api=tool_runtime_api,
        gateway_api=gateway_api,
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
