"""Distributed `agent-api serve` and standalone `tool-runtime serve`."""

from __future__ import annotations

import argparse
import asyncio
from pathlib import Path
from typing import Any

import uvicorn

from anyagent.config.loader import load_effective_config
from anyagent.observability import configure_observability
from anyagent.server import DistributedAgentRuntimeConfig, create_distributed_agent_app
from anyagent.server.runtime.workspace_env import hydrate_workspace_runtime_environment
from anyagent.storage.runtime import create_storage_runtime
from anyagent.storage.settings import storage_settings_from_config
from anyagent.tool_runtime import create_tool_runtime_app_async
from anyagent.tool_runtime.settings import build_tool_runtime_server_config, tool_runtime_settings_from_config


def register_services(subparsers: Any, bind: Any) -> None:
    """Register distributed service commands."""

    agent_api = subparsers.add_parser("agent-api", help="Distributed Agent API operations.")
    agent_api_sub = agent_api.add_subparsers(dest="agent_api_command", required=True)
    agent_api_serve = agent_api_sub.add_parser("serve", help="Start the distributed Agent API service.")
    agent_api_serve.add_argument("--workspace", default=".", help="Workspace root containing `.anyagent/`.")
    agent_api_serve.add_argument("--host", default=None, help="Bind host. Defaults to config server.host.")
    agent_api_serve.add_argument("--port", type=int, default=None, help="Bind port. Defaults to config server.port.")
    agent_api_serve.add_argument("--api-key", default=None, help="Bearer token for Agent API callers.")
    agent_api_serve.add_argument("--tool-runtime-url", default=None, help="Tool Runtime base URL.")
    agent_api_serve.add_argument(
        "--tool-runtime-internal-key",
        default=None,
        help="Bearer token for Agent API -> Tool Runtime calls.",
    )
    agent_api_serve.add_argument(
        "--manifest-cache-ttl-seconds",
        type=float,
        default=None,
        help="Manifest cache TTL seconds.",
    )
    agent_api_serve.add_argument(
        "--disable-keyed-serialization",
        action="store_true",
        help="Disable per-session keyed serialization for local mode.",
    )
    bind(agent_api_serve, ("agent-api", "serve"), cmd_agent_api_serve)

    tool_runtime = subparsers.add_parser("tool-runtime", help="Tool Runtime operations.")
    tool_runtime_sub = tool_runtime.add_subparsers(dest="tool_runtime_command", required=True)
    tool_runtime_serve = tool_runtime_sub.add_parser("serve", help="Start the standalone Tool Runtime service.")
    tool_runtime_serve.add_argument("--workspace", default=".", help="Workspace root containing `.anyagent/`.")
    tool_runtime_serve.add_argument("--host", default=None, help="Bind host. Defaults to config tool_runtime.host.")
    tool_runtime_serve.add_argument("--port", type=int, default=None, help="Bind port. Defaults to config tool_runtime.port.")
    tool_runtime_serve.add_argument("--internal-key", default=None, help="Bearer token for `/internal/tools/*` APIs.")
    tool_runtime_serve.add_argument("--admin-key", default=None, help="Bearer token for Tool Runtime `/admin/*` APIs.")
    tool_runtime_serve.add_argument("--sandbox-root", default=None, help="Optional root dir for local sandbox sessions.")
    tool_runtime_serve.add_argument(
        "--plugin-root",
        action="append",
        default=None,
        help="Plugin root to scan for plugin.json files. May be repeated.",
    )
    tool_runtime_serve.add_argument(
        "--plugins-fail-open",
        action="store_true",
        default=None,
        help="Continue serving when one or more plugin roots fail to load.",
    )
    bind(tool_runtime_serve, ("tool-runtime", "serve"), cmd_tool_runtime_serve)


def _agent_api_overrides(args: argparse.Namespace) -> dict[str, Any]:
    server: dict[str, Any] = {}
    tool_runtime: dict[str, Any] = {}
    if args.host is not None:
        server["host"] = str(args.host)
    if args.port is not None:
        server["port"] = int(args.port)
    if args.api_key:
        server["agent_api_key"] = str(args.api_key)
    if args.tool_runtime_url:
        tool_runtime["base_url"] = str(args.tool_runtime_url)
    if args.tool_runtime_internal_key:
        tool_runtime["internal_key"] = str(args.tool_runtime_internal_key)
    if args.manifest_cache_ttl_seconds is not None:
        tool_runtime["manifest_cache_ttl_seconds"] = float(args.manifest_cache_ttl_seconds)
    overrides: dict[str, Any] = {}
    if server:
        overrides["server"] = server
    if tool_runtime:
        overrides["tool_runtime"] = tool_runtime
    return overrides


def cmd_agent_api_serve(args: argparse.Namespace) -> int:
    """Start the distributed Agent API using the effective config."""

    workspace = Path(args.workspace).expanduser().resolve()
    overrides = _agent_api_overrides(args)
    effective = load_effective_config(workspace, cli_overrides=overrides or None)
    if hydrate_workspace_runtime_environment(effective):
        effective = load_effective_config(workspace, cli_overrides=effective.cli_overrides)
    configure_observability(effective.observability)
    api_key = effective.server.agent_api_key
    if not api_key:
        raise SystemExit("agent-api serve requires --api-key or AGENT_API_KEY")
    tool_runtime_internal_key = effective.tool_runtime.internal_key
    if not tool_runtime_internal_key:
        raise SystemExit("agent-api serve requires --tool-runtime-internal-key or TOOL_RUNTIME_INTERNAL_KEY")
    credentials = effective.credentials
    storage_settings = storage_settings_from_config(effective.storage)
    workspace_dir = str(workspace)
    app = create_distributed_agent_app(
        api_key=api_key,
        runtime_config=DistributedAgentRuntimeConfig(
            workspace_dir=workspace_dir,
            tool_runtime_base_url=effective.tool_runtime.base_url or "http://127.0.0.1:8788",
            tool_runtime_internal_key=tool_runtime_internal_key,
            manifest_cache_ttl_seconds=float(effective.tool_runtime.manifest_cache_ttl_seconds),
            mcp_credential_store_backend=credentials.backend,
            mcp_credential_store_file_root=credentials.file.root,
            infisical_host=credentials.infisical.host,
            infisical_universal_auth_client_id=credentials.infisical.client_id,
            infisical_universal_auth_client_secret=credentials.infisical.client_secret,
            infisical_token=credentials.infisical.token,
            infisical_project_id=credentials.infisical.project_id,
            infisical_environment=credentials.infisical.environment,
            infisical_cache_ttl_seconds=int(credentials.infisical.cache_ttl_seconds),
            infisical_credential_root_path=credentials.infisical.credential_root_path,
            infisical_path_layout=credentials.infisical.path_layout,
        ),
        storage_factory=lambda: create_storage_runtime(storage_settings, workspace_dir=workspace_dir),
        settings=storage_settings,
        enable_keyed_serialization=not bool(args.disable_keyed_serialization),
    )
    uvicorn.run(app, host=effective.server.host, port=int(effective.server.port), log_level="info")
    return 0


def _tool_runtime_overrides(args: argparse.Namespace) -> dict[str, Any]:
    server: dict[str, Any] = {}
    tool_runtime: dict[str, Any] = {}
    if args.host is not None:
        tool_runtime["host"] = str(args.host)
    if args.port is not None:
        tool_runtime["port"] = int(args.port)
    if args.internal_key:
        tool_runtime["internal_key"] = str(args.internal_key)
    if args.admin_key:
        server["admin_api_key"] = str(args.admin_key)
    if args.sandbox_root:
        tool_runtime["sandbox_root_dir"] = str(args.sandbox_root)
    if args.plugin_root:
        tool_runtime["plugin_roots"] = [str(item) for item in args.plugin_root]
    if args.plugins_fail_open:
        tool_runtime["plugins_fail_open"] = True
    overrides: dict[str, Any] = {}
    if server:
        overrides["server"] = server
    if tool_runtime:
        overrides["tool_runtime"] = tool_runtime
    return overrides


def cmd_tool_runtime_serve(args: argparse.Namespace) -> int:
    """Start the standalone Tool Runtime using the effective config."""

    workspace = Path(args.workspace).expanduser().resolve()
    overrides = _tool_runtime_overrides(args)
    effective = load_effective_config(workspace, cli_overrides=overrides or None)
    if hydrate_workspace_runtime_environment(effective):
        effective = load_effective_config(workspace, cli_overrides=effective.cli_overrides)
    configure_observability(effective.observability)
    server_config = build_tool_runtime_server_config(
        tool_runtime_settings_from_config(effective),
        workspace_dir=workspace,
        host=effective.tool_runtime.host,
        port=int(effective.tool_runtime.port),
        internal_key=effective.tool_runtime.internal_key,
        admin_api_key=effective.server.admin_api_key,
        sandbox_root_dir=effective.tool_runtime.sandbox_root_dir,
        plugin_roots=list(effective.tool_runtime.plugin_roots),
        plugins_fail_open=bool(effective.tool_runtime.plugins_fail_open),
    )
    app = asyncio.run(create_tool_runtime_app_async(config=server_config))
    uvicorn.run(app, host=str(effective.tool_runtime.host), port=int(effective.tool_runtime.port), log_level="info")
    return 0
