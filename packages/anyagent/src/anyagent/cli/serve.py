"""`anyagent serve` and `anyagent dev`."""

from __future__ import annotations

import argparse
import ipaddress
import json
from pathlib import Path
from typing import Any

import uvicorn

from anyagent.cli.admin_client import local_base_url
from anyagent.cli.workspace import agent_catalog_rows
from anyagent.config.agents import load_agent_catalog
from anyagent.config.loader import load_effective_config
from anyagent.observability import configure_observability
from anyagent.server import create_app

DEV_API_KEY = "anyagent-dev-key"
_STORAGE_PROFILES = ["inmemory", "postgres", "postgres-redis", "redis"]
_STORAGE_MODES = ["none", "external"]
_STORE_BACKENDS = ["inmemory", "external", "postgres", "postgres-redis", "redis"]
_LOCK_BACKENDS = ["inmemory", "external", "redis"]


def studio_bundle_dir() -> Path:
    """In-repo Studio build used when dev mode has no configured studio directory."""

    return Path(__file__).resolve().parents[3] / "studio" / "dist"


def add_serve_arguments(parser: argparse.ArgumentParser) -> None:
    """Register the shared serve/dev flags.

    Unset flags stay out of ``cli_overrides`` so environment-backed defaults
    in the config document keep their precedence.
    """

    parser.add_argument("--workspace", default=".", help="Workspace root containing `.anyagent/`.")
    parser.add_argument("--host", default=None, help="Bind host. Defaults to config server.host.")
    parser.add_argument("--port", type=int, default=None, help="Bind port. Defaults to config server.port.")
    parser.add_argument("--api-key", default=None, help="Bearer token for `/v1/*` and `/internal/*` APIs.")
    parser.add_argument("--admin-key", default=None, help="Bearer token for `/admin/*` APIs.")
    parser.add_argument(
        "--cors-origin",
        action="append",
        default=None,
        help="Allowed browser origin for CORS. May be repeated. Overrides config server.cors_origins.",
    )
    parser.add_argument("--sandbox-root", default=None, help="Optional root dir for local sandbox sessions.")
    parser.add_argument(
        "--studio-dir",
        default=None,
        help="Directory of a built Studio bundle to mount at /studio.",
    )
    parser.add_argument(
        "--no-studio",
        action="store_true",
        help="Do not mount Studio at /studio.",
    )
    parser.add_argument("--quiet", action="store_true", help="Suppress the JSON configuration banner printed on startup.")
    parser.add_argument(
        "--plugin-root",
        action="append",
        default=None,
        help="Plugin root to scan for plugin.json files. May be repeated.",
    )
    parser.add_argument(
        "--plugins-fail-open",
        action="store_true",
        help="Continue serving when one or more plugins fail to load.",
    )
    parser.add_argument("--storage-profile", choices=_STORAGE_PROFILES, default=None, help="Storage profile override.")
    parser.add_argument("--storage-mode", choices=_STORAGE_MODES, default=None, help="Unified server storage mode.")
    parser.add_argument("--event-store-backend", choices=_STORE_BACKENDS, default=None, help="Event Store backend override.")
    parser.add_argument("--run-store-backend", choices=_STORE_BACKENDS, default=None, help="Run Store backend override.")
    parser.add_argument(
        "--session-store-backend",
        choices=_STORE_BACKENDS,
        default=None,
        help="Session Store backend override.",
    )
    parser.add_argument("--session-lock-backend", choices=_LOCK_BACKENDS, default=None, help="Session lease backend.")
    parser.add_argument("--session-lease-ttl-s", type=float, default=None, help="Session lease TTL seconds.")


def register_serve(subparsers: Any, bind: Any) -> None:
    """Register `serve` and `dev` on one argument function and one handler."""

    serve = subparsers.add_parser("serve", help="Start the built-in anyagent server.")
    add_serve_arguments(serve)
    bind(serve, ("serve",), cmd_serve)

    dev = subparsers.add_parser(
        "dev",
        help="Start a local development server. Same flags as serve, with dev defaults when config leaves them empty.",
    )
    add_serve_arguments(dev)
    bind(dev, ("dev",), cmd_serve)


def serve_cli_overrides(args: argparse.Namespace) -> dict[str, Any]:
    """Map flags the user set onto the effective-config override document."""

    server: dict[str, Any] = {}
    if args.host is not None:
        server["host"] = str(args.host)
    if args.port is not None:
        server["port"] = int(args.port)
    if args.api_key:
        server["api_key"] = str(args.api_key)
    if args.admin_key:
        server["admin_api_key"] = str(args.admin_key)
    if args.cors_origin:
        server["cors_origins"] = [str(item) for item in args.cors_origin]
    if args.sandbox_root:
        server["sandbox_root"] = str(args.sandbox_root)
    if args.studio_dir:
        server["studio_dir"] = str(args.studio_dir)
    if args.no_studio:
        server["enable_studio"] = False

    storage: dict[str, Any] = {}
    if args.storage_profile:
        storage["profile"] = args.storage_profile
    if args.storage_mode:
        storage["mode"] = args.storage_mode
    if args.event_store_backend:
        storage["event_store_backend"] = args.event_store_backend
    if args.run_store_backend:
        storage["run_store_backend"] = args.run_store_backend
    if args.session_store_backend:
        storage["session_store_backend"] = args.session_store_backend
    if args.session_lock_backend:
        storage["session_lock_backend"] = args.session_lock_backend
    if args.session_lease_ttl_s is not None:
        storage["session_lease_ttl_s"] = args.session_lease_ttl_s

    plugins: dict[str, Any] = {}
    if args.plugin_root:
        plugins["roots"] = [str(item) for item in args.plugin_root]
    if args.plugins_fail_open:
        plugins["fail_open"] = True

    overrides: dict[str, Any] = {}
    if server:
        overrides["server"] = server
    if storage:
        overrides["storage"] = storage
    if plugins:
        overrides["plugins"] = plugins
    return overrides


def _with_dev_fallbacks(
    args: argparse.Namespace,
    effective: Any,
    overrides: dict[str, Any],
) -> dict[str, Any]:
    """Fill empty dev-only values without overriding configured settings."""

    server = dict(overrides.get("server") or {})
    changed = False
    if args.api_key is None and not effective.server.api_key:
        server["api_key"] = DEV_API_KEY
        changed = True
    resolved_api_key = server.get("api_key", effective.server.api_key)
    if args.admin_key is None and not effective.server.admin_api_key:
        server["admin_api_key"] = resolved_api_key or DEV_API_KEY
        changed = True
    if not args.no_studio and args.studio_dir is None and not effective.server.studio_dir:
        server["studio_dir"] = str(studio_bundle_dir())
        changed = True
    if not changed:
        return overrides
    updated = dict(overrides)
    updated["server"] = server
    return updated


def cmd_serve(args: argparse.Namespace) -> int:
    """Load config from flags and start the built-in server."""

    workspace = Path(args.workspace).expanduser().resolve()
    dev_mode = tuple(getattr(args, "command_path", ()) or ()) == ("dev",)
    overrides = serve_cli_overrides(args)
    effective = load_effective_config(workspace, cli_overrides=overrides or None)
    if dev_mode:
        filled = _with_dev_fallbacks(args, effective, overrides)
        if filled is not overrides:
            effective = load_effective_config(workspace, cli_overrides=filled)
    _require_api_key_for_public_bind(effective)
    configure_observability(effective.observability)
    app = create_app(workspace_dir=str(workspace), config=effective)
    _print_serve_banner(
        workspace=workspace,
        host=effective.server.host,
        port=int(effective.server.port),
        api_key=effective.server.api_key,
        admin_key=effective.server.admin_api_key,
        enable_studio=bool(effective.server.enable_studio and effective.server.studio_dir),
        quiet=bool(args.quiet),
        app=app,
    )
    uvicorn.run(app, host=effective.server.host, port=int(effective.server.port), log_level="info")
    return 0


def _require_api_key_for_public_bind(effective: Any) -> None:
    """Refuse a non-loopback bind when ``server.api_key`` is empty.

    ``anyagent dev`` fills a development key before this check. Loopback hosts
    (localhost, 127.0.0.0/8, ::1) may start without a key.
    """

    host = str(getattr(effective.server, "host", "") or "").strip()
    if _is_loopback_host(host):
        return
    api_key = getattr(effective.server, "api_key", None)
    if isinstance(api_key, str) and api_key.strip():
        return
    raise SystemExit(
        f"refusing to serve on {host or '(empty host)'}: server.api_key is empty. "
        "Set server.api_key, API_KEY, or --api-key before binding a non-loopback address. "
        "Loopback hosts (127.0.0.1, ::1, localhost) may start without a key. "
        "`anyagent dev` supplies a development key."
    )


def _is_loopback_host(host: str) -> bool:
    text = host.strip().lower()
    if text == "localhost":
        return True
    if text.startswith("[") and text.endswith("]"):
        text = text[1:-1]
    try:
        return ipaddress.ip_address(text).is_loopback
    except ValueError:
        return False


def _print_serve_banner(
    *,
    workspace: Path,
    host: str,
    port: int,
    api_key: str | None,
    admin_key: str | None,
    enable_studio: bool,
    quiet: bool = False,
    app: Any | None = None,
) -> None:
    if quiet:
        return
    base_url = local_base_url(host=host, port=port)
    agents_exposed: list[str] = []
    agents_hidden: list[str] = []
    try:
        catalog = load_agent_catalog(workspace_dir=workspace)
        rows = agent_catalog_rows(catalog)
        agents_exposed = [row["agent_id"] for row in rows if row["exposed"]]
        agents_hidden = [row["agent_id"] for row in rows if not row["exposed"]]
    except Exception:  # noqa: BLE001
        pass
    config: dict[str, Any] = {
        "workspace": str(workspace),
        "host": host,
        "port": port,
        "api": f"{base_url}/v1",
        "openapi": f"{base_url}/openapi.json",
        "studio": f"{base_url}/studio/" if enable_studio else "disabled",
        "api_key": "set" if api_key else "unset",
        "admin_key": "set" if admin_key else "unset",
        "agents_exposed": agents_exposed,
        "agents_hidden": agents_hidden,
    }
    state = getattr(getattr(app, "state", None), "anyagent", None)
    if state is not None:
        resolved = state.resolved_storage
        config["storage"] = {
            "profile": resolved.storage_profile,
            "mode": resolved.storage_mode,
            "backends": {
                "event_store": resolved.event_store_backend,
                "run_store": resolved.run_store_backend,
                "session_store": resolved.session_store_backend,
                "session_lock": resolved.session_lock_backend,
            },
            "postgres_configured": resolved.postgres_configured,
            "redis_configured": resolved.redis_configured,
            "single_instance_only": resolved.single_instance_only,
            "warnings": list(resolved.warnings),
        }
    print(json.dumps(config, ensure_ascii=False, indent=2))
