from __future__ import annotations

import argparse
import asyncio
import json
import os
import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import httpx
import uvicorn
import yaml

from anyagent.agent_packs import AgentPackError, load_agent_catalog, preferred_agents_root, preferred_config_root, resolve_agents_root
from anyagent.model_config import WorkspaceModelsConfig, workspace_models_config_path
from anyagent.observability import configure_observability_from_env
from anyagent.protocol.admin_storage import StorageHealthResponse
from anyagent.protocol.credential_vault import (
    AdminCredentialDeleteResponse,
    AdminCredentialListResponse,
    AdminCredentialRef,
    AdminCredentialSetRequest,
    CredentialScope,
)
from anyagent.protocol.plugins import PluginCatalogResponse
from anyagent.protocol.workspace import WorkspaceDoctorFinding, WorkspaceDoctorReport, WorkspaceInitResult
from anyagent.server import DistributedAgentRuntimeConfig, create_app, create_distributed_agent_app
from anyagent.server.migrations import apply_storage_migrations
from anyagent.skills import SkillRoot, default_skill_roots, discover_skills, resolve_disabled_skill_stable_ids
from anyagent.storage.runtime import create_storage_runtime
from anyagent.storage.settings import StorageSettings
from anyagent.storage.retention import run_retention_from_args
from anyagent.storage.rollout_replay import ReplayFilters, replay_rollout_records, resolve_rollout_root_dir
from anyagent.tool_runtime import create_tool_runtime_app_async


@dataclass(frozen=True, slots=True)
class _AdminClient:
    url: str
    key: str

    def _headers(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self.key}"}

    def set_credential(self, req: AdminCredentialSetRequest) -> AdminCredentialRef:
        r = httpx.post(
            f"{self.url}/admin/credentials",
            headers=self._headers(),
            json=req.model_dump(exclude_none=True),
            timeout=15.0,
        )
        _raise_for_status(r)
        return AdminCredentialRef.model_validate(r.json())

    def list_credentials(self) -> AdminCredentialListResponse:
        r = httpx.get(
            f"{self.url}/admin/credentials",
            headers=self._headers(),
            timeout=15.0,
        )
        _raise_for_status(r)
        return AdminCredentialListResponse.model_validate(r.json())

    def delete_credential(self, credential_id: str) -> AdminCredentialDeleteResponse:
        r = httpx.delete(
            f"{self.url}/admin/credentials/{credential_id}",
            headers=self._headers(),
            timeout=15.0,
        )
        _raise_for_status(r)
        return AdminCredentialDeleteResponse.model_validate(r.json())

    def storage_health(self) -> StorageHealthResponse:
        r = httpx.get(
            f"{self.url}/admin/storage/health",
            headers=self._headers(),
            timeout=15.0,
        )
        _raise_for_status(r)
        return StorageHealthResponse.model_validate(r.json())

    def plugin_catalog(self) -> PluginCatalogResponse:
        r = httpx.get(
            f"{self.url}/admin/plugins/catalog",
            headers=self._headers(),
            timeout=15.0,
        )
        _raise_for_status(r)
        return PluginCatalogResponse.model_validate(r.json())


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="anyagent")
    sub = parser.add_subparsers(dest="cmd", required=True)

    init = sub.add_parser("init", help="Create a minimal configurable anyagent workspace.")
    init.add_argument("--workspace", default=".", help="Workspace root to initialize.")
    init.add_argument("--agent-id", default="main", help="Agent id to create (default: main).")
    init.add_argument(
        "--template",
        choices=["basic", "coding-agent", "research-agent", "multi-agent-team"],
        default="basic",
        help="Workspace template to generate (default: basic).",
    )
    init.add_argument("--force", action="store_true", help="Overwrite files created by this command.")
    init.add_argument(
        "--with-example-skill",
        action="store_true",
        help="Create `.anyagent/skills/example-skill/SKILL.md` and select it by default.",
    )

    doctor = sub.add_parser("doctor", help="Validate an anyagent workspace before serving it.")
    doctor.add_argument("--workspace", default=".", help="Workspace root containing `.anyagent/`.")
    doctor.add_argument("--json", action="store_true", help="Print machine-readable JSON.")

    agent = sub.add_parser("agent", help="Inspect local workspace agent packs.")
    agent_sub = agent.add_subparsers(dest="agent_cmd", required=True)
    agent_list = agent_sub.add_parser("list", help="List configured agent packs for a workspace.")
    agent_list.add_argument("--workspace", default=".", help="Workspace root containing `.anyagent/`.")
    agent_list.add_argument("--json", action="store_true", help="Print machine-readable JSON.")

    config = sub.add_parser("config", help="Business workspace configuration operations.")
    config_sub = config.add_subparsers(dest="config_cmd", required=True)
    config_init = config_sub.add_parser("init", help="Initialize workspace model/provider config and an agent pack.")
    config_init.add_argument("--workspace", default=".", help="Business workspace root to initialize.")
    config_init.add_argument("--agent-id", default="main", help="Agent id to create/update (default: main).")
    config_init.add_argument("--model-alias", default="default", help="Model alias stored in workspace-root `models.yaml`.")
    config_init.add_argument("--model", default="gpt-4o-mini", help="Upstream provider model name.")
    config_init.add_argument(
        "--provider",
        default="openai",
        choices=["openai", "anthropic", "gemini"],
        help="Provider kind for the model alias.",
    )
    config_init.add_argument("--provider-name", default=None, help="Provider config key (default: --provider).")
    config_init.add_argument("--api-key-env", default=None, help="Environment variable containing the provider API key.")
    config_init.add_argument("--base-url", default=None, help="Provider base URL literal.")
    config_init.add_argument("--base-url-env", default=None, help="Environment variable containing provider base URL.")
    config_init.add_argument(
        "--tool",
        action="append",
        default=None,
        help="Requested tool name to add to the generated agent.yaml. May be repeated.",
    )
    config_init.add_argument(
        "--with-web-fetch",
        action="store_true",
        help="Add core.web_fetch to requested tools.",
    )
    config_init.add_argument(
        "--with-exec",
        action="store_true",
        help="Add exec to requested tools and default sandbox mode to local-unsafe unless --sandbox-mode is set.",
    )
    config_init.add_argument(
        "--sandbox-mode",
        choices=["disabled", "local-unsafe", "opensandbox", "external"],
        default=None,
        help="Sandbox mode to write to agent.yaml (default: disabled, or local-unsafe with --with-exec).",
    )
    config_init.add_argument("--force", action="store_true", help="Overwrite files created by this command.")

    serve = sub.add_parser("serve", help="Start the built-in anyagent server.")
    serve.add_argument("--workspace", default=".", help="Workspace root containing `.anyagent/`.")
    serve.add_argument("--host", default="127.0.0.1")
    serve.add_argument("--port", type=int, default=8787)
    serve.add_argument("--api-key", default=None, help="Bearer token for `/v1/*` and `/internal/*` APIs.")
    serve.add_argument("--admin-key", default=None, help="Bearer token for `/admin/*` APIs.")
    serve.add_argument(
        "--cors-origin",
        action="append",
        default=None,
        help=(
            "Allowed browser origin for CORS. May be repeated. "
            "Defaults to comma-separated $ANYAGENT_CORS_ORIGINS when unset."
        ),
    )
    serve.add_argument("--sandbox-root", default=None, help="Optional root dir for local sandbox sessions.")
    serve.add_argument("--no-studio", action="store_true", help="Do not mount the bundled Studio at /studio.")
    serve.add_argument(
        "--plugin-root",
        action="append",
        default=None,
        help="Plugin root to scan for plugin.json files. May be repeated. Defaults to comma-separated $ANYAGENT_PLUGIN_ROOTS.",
    )
    serve.add_argument(
        "--plugins-fail-open",
        action="store_true",
        default=False,
        help="Continue serving when one or more plugins fail to load (default: fail closed).",
    )
    serve.add_argument(
        "--storage-mode",
        choices=["none", "external"],
        default=None,
        help="Unified server storage mode (default: $STORAGE_MODE or none).",
    )
    serve.add_argument(
        "--event-store-backend",
        choices=["inmemory", "external", "redis"],
        default=None,
        help="Event Store backend override (default resolved from storage mode).",
    )
    serve.add_argument(
        "--run-store-backend",
        choices=["inmemory", "external", "redis"],
        default=None,
        help="Run Store backend override (default resolved from storage mode).",
    )
    serve.add_argument(
        "--session-store-backend",
        choices=["inmemory", "external", "redis"],
        default=None,
        help="Session Store backend override (default resolved from storage mode).",
    )
    serve.add_argument(
        "--session-lock-backend",
        choices=["inmemory", "external", "redis"],
        default=None,
        help="Session lease backend (default: $SESSION_LOCK_BACKEND or inmemory).",
    )
    serve.add_argument(
        "--session-lease-ttl-s",
        type=float,
        default=None,
        help="Session lease TTL seconds (default: $SESSION_LEASE_TTL_S or 30).",
    )

    dev = sub.add_parser("dev", help="Start a local development server with Studio-friendly defaults.")
    dev.add_argument("--workspace", default=".", help="Workspace root containing `.anyagent/`.")
    dev.add_argument("--host", default="127.0.0.1")
    dev.add_argument("--port", type=int, default=8787)
    dev.add_argument("--api-key", default=None, help="Bearer token for `/v1/*` and `/internal/*` APIs.")
    dev.add_argument("--admin-key", default=None, help="Bearer token for `/admin/*` APIs.")
    dev.add_argument(
        "--cors-origin",
        action="append",
        default=None,
        help="Allowed browser origin for CORS. May be repeated.",
    )
    dev.add_argument("--sandbox-root", default=None, help="Optional root dir for local sandbox sessions.")
    dev.add_argument(
        "--plugin-root",
        action="append",
        default=None,
        help="Plugin root to scan for plugin.json files. May be repeated. Defaults to comma-separated $ANYAGENT_PLUGIN_ROOTS.",
    )
    dev.add_argument(
        "--plugins-fail-open",
        action="store_true",
        default=False,
        help="Continue serving when one or more plugins fail to load (default: fail closed).",
    )
    dev.add_argument(
        "--storage-mode",
        choices=["none", "external"],
        default=None,
        help="Unified server storage mode (default: $STORAGE_MODE or none).",
    )
    dev.add_argument(
        "--event-store-backend",
        choices=["inmemory", "external", "redis"],
        default=None,
        help="Event Store backend override (default resolved from storage mode).",
    )
    dev.add_argument(
        "--run-store-backend",
        choices=["inmemory", "external", "redis"],
        default=None,
        help="Run Store backend override (default resolved from storage mode).",
    )
    dev.add_argument(
        "--session-store-backend",
        choices=["inmemory", "external", "redis"],
        default=None,
        help="Session Store backend override (default resolved from storage mode).",
    )
    dev.add_argument(
        "--session-lock-backend",
        choices=["inmemory", "external", "redis"],
        default=None,
        help="Session lease backend (default: $SESSION_LOCK_BACKEND or inmemory).",
    )
    dev.add_argument(
        "--session-lease-ttl-s",
        type=float,
        default=None,
        help="Session lease TTL seconds (default: $SESSION_LEASE_TTL_S or 30).",
    )

    agent_api = sub.add_parser("agent-api", help="Distributed Agent API operations.")
    agent_api_sub = agent_api.add_subparsers(dest="agent_api_cmd", required=True)
    agent_api_serve = agent_api_sub.add_parser("serve", help="Start the distributed Agent API service.")
    agent_api_serve.add_argument("--workspace", default=".", help="Workspace root containing `.anyagent/`.")
    agent_api_serve.add_argument("--host", default="127.0.0.1")
    agent_api_serve.add_argument("--port", type=int, default=8787)
    agent_api_serve.add_argument(
        "--api-key",
        default=None,
        help="Bearer token for Agent API callers (default: $AGENT_API_KEY).",
    )
    agent_api_serve.add_argument(
        "--tool-runtime-url",
        default=None,
        help="Tool Runtime base URL (default: $TOOL_RUNTIME_BASE_URL or http://127.0.0.1:8788).",
    )
    agent_api_serve.add_argument(
        "--tool-runtime-internal-key",
        default=None,
        help="Bearer token for Agent API -> Tool Runtime calls (default: $TOOL_RUNTIME_INTERNAL_KEY).",
    )
    agent_api_serve.add_argument(
        "--manifest-cache-ttl-seconds",
        type=float,
        default=None,
        help="Manifest cache TTL seconds (default: $MANIFEST_CACHE_TTL_SECONDS or 5).",
    )
    agent_api_serve.add_argument(
        "--disable-keyed-serialization",
        action="store_true",
        help="Disable per-session keyed serialization for local mode.",
    )

    tool_runtime = sub.add_parser("tool-runtime", help="Tool Runtime operations.")
    tool_runtime_sub = tool_runtime.add_subparsers(dest="tool_runtime_cmd", required=True)
    tool_runtime_serve = tool_runtime_sub.add_parser("serve", help="Start the standalone Tool Runtime service.")
    tool_runtime_serve.add_argument("--workspace", default=".", help="Workspace root containing `.anyagent/`.")
    tool_runtime_serve.add_argument("--host", default="127.0.0.1")
    tool_runtime_serve.add_argument("--port", type=int, default=8788)
    tool_runtime_serve.add_argument(
        "--internal-key",
        default=None,
        help="Bearer token for `/internal/tools/*` APIs (default: $TOOL_RUNTIME_INTERNAL_KEY; unset disables auth).",
    )
    tool_runtime_serve.add_argument(
        "--admin-key",
        default=None,
        help="Bearer token for Tool Runtime `/admin/*` APIs (default: $ADMIN_API_KEY; unset disables admin APIs).",
    )
    tool_runtime_serve.add_argument("--sandbox-root", default=None, help="Optional root dir for local sandbox sessions.")
    tool_runtime_serve.add_argument(
        "--plugin-root",
        action="append",
        default=None,
        help="Plugin root to scan for plugin.json files. May be repeated. Defaults to comma-separated $TOOL_RUNTIME_PLUGIN_ROOTS.",
    )
    tool_runtime_serve.add_argument(
        "--plugins-fail-open",
        action="store_true",
        default=None,
        help="Continue serving when one or more plugin roots fail to load (default: fail closed).",
    )

    storage_health = sub.add_parser("storage-health", help="Check built-in server storage backends and connectivity.")
    _add_common_admin_flags(storage_health)

    migrate = sub.add_parser("storage-migrate", help="Apply PostgreSQL storage migrations.")
    migrate.add_argument("--postgres-dsn", default=None, help="Override POSTGRES_DSN.")
    migrate.add_argument("--postgres-schema", default=None, help="Override POSTGRES_SCHEMA.")
    migrate.add_argument("--dry-run", action="store_true", help="Only print planned migrations.")

    storage_replay = sub.add_parser("storage-replay", help="Replay local rollout records from Core storage journals.")
    _add_storage_replay_flags(storage_replay)

    storage_retention = sub.add_parser("storage-retention", help="Run PostgreSQL storage retention maintenance.")
    _add_storage_retention_flags(storage_retention)

    storage = sub.add_parser("storage", help="Storage operations.")
    storage_sub = storage.add_subparsers(dest="storage_cmd", required=True)
    storage_health_nested = storage_sub.add_parser("health", help="Check built-in server storage backends and connectivity.")
    _add_common_admin_flags(storage_health_nested)
    storage_migrate_nested = storage_sub.add_parser("migrate", help="Apply PostgreSQL storage migrations.")
    storage_migrate_nested.add_argument("--postgres-dsn", default=None, help="Override POSTGRES_DSN.")
    storage_migrate_nested.add_argument("--postgres-schema", default=None, help="Override POSTGRES_SCHEMA.")
    storage_migrate_nested.add_argument("--dry-run", action="store_true", help="Only print planned migrations.")
    storage_replay_nested = storage_sub.add_parser("replay", help="Replay local rollout records from Core storage journals.")
    _add_storage_replay_flags(storage_replay_nested)
    storage_retention_nested = storage_sub.add_parser("retention", help="Run PostgreSQL storage retention maintenance.")
    _add_storage_retention_flags(storage_retention_nested)

    db = sub.add_parser("db", help="Database migration management (Alembic).")
    db_sub = db.add_subparsers(dest="db_cmd", required=True)
    db_migrate = db_sub.add_parser("migrate", help="Run all pending Alembic migrations (upgrade head).")
    db_migrate.add_argument("--sql", action="store_true", help="Generate SQL without executing (offline mode).")
    db_downgrade = db_sub.add_parser("downgrade", help="Downgrade one revision.")
    db_downgrade.add_argument("--revision", default="-1", help="Target revision (default: -1).")
    db_current = db_sub.add_parser("current", help="Show current migration revision.")
    db_history = db_sub.add_parser("history", help="Show migration history.")
    db_stamp = db_sub.add_parser("stamp", help="Stamp database with a revision without running migrations.")
    db_stamp.add_argument("revision", help="Revision to stamp (e.g. 'head', '0001').")

    cred = sub.add_parser("credential", help="Manage credentials via built-in Admin API.")
    cred_sub = cred.add_subparsers(dest="cred_cmd", required=True)

    _add_common_admin_flags(cred)

    p_set = cred_sub.add_parser("set", help="Set (create/update) a credential (write-only).")
    _add_common_admin_flags(p_set)
    p_set.add_argument("--id", dest="credential_id", required=True)
    p_set.add_argument("--kind", required=True)
    p_set.add_argument("--value", default=None, help="Plaintext value (avoid shell history).")
    p_set.add_argument("--value-from-env", default=None, help="Read plaintext value from env var.")
    p_set.add_argument("--scope", choices=["global", "agent"], default="global")
    p_set.add_argument("--agent-id", default=None, help="Required when --scope=agent.")
    p_set.add_argument("--display-name", default=None)
    p_set.add_argument("--provider", default=None)
    p_set.add_argument("--env-var-name", default=None, help="Optional: metadata.env_var_name for EnvBackend.")
    p_set.add_argument("--metadata-json", default=None, help="Extra metadata JSON object.")

    p_list = cred_sub.add_parser("list", help="List credential references (no plaintext).")
    _add_common_admin_flags(p_list)
    p_list.add_argument("--json", action="store_true", help="Print JSON (default).")

    p_delete = cred_sub.add_parser("delete", help="Delete a credential by id.")
    _add_common_admin_flags(p_delete)
    p_delete.add_argument("--id", dest="credential_id", required=True)

    p_import = cred_sub.add_parser("import", help="Import credentials from a YAML file.")
    _add_common_admin_flags(p_import)
    p_import.add_argument("--file", required=True, help="YAML file path (credentials.yaml).")
    p_import.add_argument("--dry-run", action="store_true")
    p_import.add_argument("--skip-missing", action="store_true", help="Skip items with empty resolved value.")

    plugin = sub.add_parser("plugin", help="Inspect Tool Runtime plugins via Admin API.")
    plugin_sub = plugin.add_subparsers(dest="plugin_cmd", required=True)
    _add_common_admin_flags(plugin)
    plugin_catalog = plugin_sub.add_parser("catalog", help="List loaded plugins, registered tools, and cite refs.")
    _add_common_admin_flags(plugin_catalog)
    plugin_catalog.add_argument("--json", action="store_true", help="Print JSON (default).")

    args = parser.parse_args(argv)
    if args.cmd == "init":
        return _cmd_init(args)
    if args.cmd == "doctor":
        return _cmd_doctor(args)
    if args.cmd == "agent":
        if args.agent_cmd == "list":
            return _cmd_agent_list(args)
        parser.error("unsupported agent command")
    if args.cmd == "config":
        if args.config_cmd == "init":
            return _cmd_config_init(args)
        parser.error("unsupported config command")
    if args.cmd == "serve":
        return _cmd_serve(args)
    if args.cmd == "dev":
        args.no_studio = False
        if not args.api_key and not os.getenv("ANYAGENT_API_KEY"):
            args.api_key = "anyagent-dev-key"
        if not args.admin_key and not os.getenv("ADMIN_API_KEY"):
            args.admin_key = args.api_key or "anyagent-dev-key"
        return _cmd_serve(args)
    if args.cmd == "agent-api":
        if args.agent_api_cmd == "serve":
            return _cmd_agent_api_serve(args)
        parser.error("unsupported agent-api command")
    if args.cmd == "tool-runtime":
        if args.tool_runtime_cmd == "serve":
            return _cmd_tool_runtime_serve(args)
        parser.error("unsupported tool-runtime command")
    if args.cmd == "storage-health":
        client = _admin_client_from_args(args)
        print(
            json.dumps(
                client.storage_health().model_dump(exclude_none=True, by_alias=True),
                ensure_ascii=False,
            )
        )
        return 0
    if args.cmd == "storage-migrate":
        result = apply_storage_migrations(
            postgres_dsn=args.postgres_dsn,
            postgres_schema=args.postgres_schema,
            dry_run=bool(args.dry_run),
        )
        print(json.dumps(result, ensure_ascii=False))
        return 0
    if args.cmd == "storage-replay":
        return _cmd_storage_replay(args)
    if args.cmd == "storage-retention":
        return run_retention_from_args(args)
    if args.cmd == "storage":
        if args.storage_cmd == "health":
            client = _admin_client_from_args(args)
            print(
                json.dumps(
                    client.storage_health().model_dump(exclude_none=True, by_alias=True),
                    ensure_ascii=False,
                )
            )
            return 0
        if args.storage_cmd == "migrate":
            result = apply_storage_migrations(
                postgres_dsn=args.postgres_dsn,
                postgres_schema=args.postgres_schema,
                dry_run=bool(args.dry_run),
            )
            print(json.dumps(result, ensure_ascii=False))
            return 0
        if args.storage_cmd == "replay":
            return _cmd_storage_replay(args)
        if args.storage_cmd == "retention":
            return run_retention_from_args(args)
        parser.error("unsupported storage command")
    if args.cmd == "db":
        return _cmd_db(args)
    if args.cmd == "plugin":
        if args.plugin_cmd == "catalog":
            client = _admin_client_from_args(args)
            print(json.dumps(client.plugin_catalog().model_dump(exclude_none=True), ensure_ascii=False))
            return 0
        parser.error("unsupported plugin command")
    if args.cmd != "credential":
        parser.error("unsupported command")

    client = _admin_client_from_args(args)

    if args.cred_cmd == "set":
        value = _resolve_value(value=args.value, value_from_env=args.value_from_env)
        scope = _parse_scope(level=args.scope, agent_id=args.agent_id)
        metadata = _build_metadata(
            display_name=args.display_name,
            provider=args.provider,
            env_var_name=args.env_var_name,
            metadata_json=args.metadata_json,
        )
        ref = client.set_credential(
            AdminCredentialSetRequest(
                credential_id=args.credential_id,
                kind=args.kind,
                value=value,
                scope=scope,
                metadata=metadata,
            )
        )
        print(json.dumps(ref.model_dump(exclude_none=True), ensure_ascii=False))
        return 0

    if args.cred_cmd == "list":
        resp = client.list_credentials()
        print(json.dumps(resp.model_dump(exclude_none=True), ensure_ascii=False))
        return 0

    if args.cred_cmd == "delete":
        resp = client.delete_credential(args.credential_id)
        print(json.dumps(resp.model_dump(exclude_none=True), ensure_ascii=False))
        return 0

    if args.cred_cmd == "import":
        return _cmd_import(client, file_path=args.file, dry_run=args.dry_run, skip_missing=args.skip_missing)

    parser.error("unsupported credential command")


def _add_storage_replay_flags(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--root-dir", default=None, help="Rollout root directory (default: env ROLLOUT_ROOT_DIR or WORKSPACE_DIR/.runs/rollouts).")
    parser.add_argument("--workspace-dir", default=None, help="Workspace root used when --root-dir is not set (default: env WORKSPACE_DIR or cwd).")
    parser.add_argument("--session-partition-key", default=None, help="Filter by exact session_partition_key.")
    parser.add_argument("--response-id", default=None, help="Filter by exact response_id.")
    parser.add_argument("--kind", action="append", default=None, help="Filter by kind (repeatable).")
    parser.add_argument("--last-seq", type=int, default=0, help="Event replay cursor: only return event_appended with seq > last_seq.")
    parser.add_argument("--limit", type=int, default=200, help="Max records to return (default: 200, max: 5000).")
    parser.add_argument("--format", choices=["json", "jsonl"], default="json", help="Output format.")
    parser.add_argument("--include-fingerprint", action="store_true", help="Include per-record fingerprint in output.")


def _add_storage_retention_flags(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--apply", action="store_true", help="Apply changes (default: plan-only, no writes).")
    parser.add_argument("--dsn", default=None, help="Postgres DSN (default: env POSTGRES_DSN).")
    parser.add_argument("--schema", default=None, help='Postgres schema/search_path (default: env POSTGRES_SCHEMA or "public").')
    parser.add_argument("--batch-size", type=int, default=500, help="Max rows per batch (default: 500).")
    parser.add_argument("--max-batches", type=int, default=200, help="Max batches per action (default: 200).")
    parser.add_argument("--idempotency-ttl-hours", type=int, default=24, help="TTL for Idempotency-Key (default: 24).")
    parser.add_argument("--events-retention-days", type=int, default=30, help="Retention for events (default: 30).")
    parser.add_argument("--runs-retention-days", type=int, default=180, help="Retention for runs (default: 180).")
    parser.add_argument("--sessions-retention-days", type=int, default=90, help="Retention for sessions (default: 90).")


def _cmd_db(args: argparse.Namespace) -> int:
    """Database migration management via Alembic."""
    import sys
    from pathlib import Path

    alembic_dir = Path(__file__).resolve().parent / "storage" / "alembic"

    try:
        from alembic.config import Config
        from alembic import command as alembic_cmd
    except ImportError:
        print("alembic is required: pip install anyagent[postgres]", file=sys.stderr)
        return 1

    settings = StorageSettings()
    dsn = settings.effective_postgres_dsn
    if dsn is None:
        print("DATABASE_URL or POSTGRES_DSN must be set", file=sys.stderr)
        return 1

    effective_dsn = str(dsn)
    if effective_dsn.startswith("postgresql://"):
        effective_dsn = "postgresql+psycopg://" + effective_dsn[len("postgresql://"):]

    cfg = Config()
    cfg.set_main_option("script_location", str(alembic_dir))
    cfg.set_main_option("sqlalchemy.url", effective_dsn)

    if args.db_cmd == "migrate":
        if args.sql:
            alembic_cmd.upgrade(cfg, "head", sql=True)
        else:
            alembic_cmd.upgrade(cfg, "head")
        print("migrations applied successfully")
    elif args.db_cmd == "downgrade":
        alembic_cmd.downgrade(cfg, args.revision)
        print(f"downgraded to {args.revision}")
    elif args.db_cmd == "current":
        alembic_cmd.current(cfg, verbose=True)
    elif args.db_cmd == "history":
        alembic_cmd.history(cfg, verbose=True)
    elif args.db_cmd == "stamp":
        alembic_cmd.stamp(cfg, args.revision)
        print(f"stamped {args.revision}")
    return 0


def _cmd_storage_replay(args: argparse.Namespace) -> int:
    kinds = {
        s
        for raw in (args.kind or [])
        if isinstance(raw, str)
        for s in [raw.strip()]
        if s
    }
    filters = ReplayFilters(
        session_partition_key=args.session_partition_key.strip()
        if isinstance(args.session_partition_key, str) and args.session_partition_key.strip()
        else None,
        response_id=args.response_id.strip() if isinstance(args.response_id, str) and args.response_id.strip() else None,
        kinds=kinds,
        last_seq=max(0, int(args.last_seq or 0)),
        limit=max(1, min(5000, int(args.limit or 200))),
    )
    root_dir = resolve_rollout_root_dir(root_dir=args.root_dir, workspace_dir=args.workspace_dir)
    result = replay_rollout_records(
        root_dir=root_dir,
        filters=filters,
        include_fingerprint=bool(args.include_fingerprint),
    )
    if args.format == "jsonl":
        print(json.dumps({"summary": result["summary"]}, ensure_ascii=False))
        for row in result["records"]:
            print(json.dumps(row, ensure_ascii=False))
    else:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


def _cmd_serve(args: argparse.Namespace) -> int:
    configure_observability_from_env()
    workspace = Path(args.workspace).expanduser().resolve()
    api_key = args.api_key or os.getenv("ANYAGENT_API_KEY")
    admin_key = args.admin_key or os.getenv("ADMIN_API_KEY")
    enable_studio = not bool(args.no_studio)
    app = create_app(
        workspace_dir=str(workspace),
        api_key=api_key,
        admin_api_key=admin_key,
        sandbox_root_dir=args.sandbox_root,
        storage_mode=args.storage_mode,
        event_store_backend=args.event_store_backend,
        run_store_backend=args.run_store_backend,
        session_store_backend=args.session_store_backend,
        session_lock_backend=args.session_lock_backend,
        session_lease_ttl_s=args.session_lease_ttl_s,
        cors_origins=args.cors_origin,
        enable_studio=enable_studio,
        session_config_overrides={},
        plugin_roots=args.plugin_root,
        plugins_fail_open=args.plugins_fail_open,
    )
    _print_serve_banner(
        workspace=workspace,
        host=str(args.host),
        port=int(args.port),
        api_key=api_key,
        admin_key=admin_key,
        enable_studio=enable_studio,
    )
    uvicorn.run(app, host=args.host, port=int(args.port), log_level="info")
    return 0


def _cmd_agent_list(args: argparse.Namespace) -> int:
    workspace = Path(args.workspace).expanduser().resolve()
    catalog = load_agent_catalog(workspace_dir=workspace)
    agents = _agent_catalog_rows(catalog)
    payload = {
        "workspace": str(workspace),
        "agents_root": str(catalog.root_dir),
        "agents": agents,
    }
    if bool(args.json):
        print(json.dumps(payload, ensure_ascii=False))
        return 0
    print(f"workspace: {workspace}")
    print(f"agents_root: {catalog.root_dir}")
    for agent in agents:
        tools = ", ".join(agent["requested_tool_names"]) or "-"
        spawn = ", ".join(agent["spawn_allow_agent_ids"]) or "-"
        model = agent["model_default"] or "-"
        print(
            f"- {agent['agent_id']} "
            f"exposed={agent['exposed']} "
            f"sandbox={agent['sandbox_mode']} "
            f"model={model} "
            f"tools={tools} "
            f"spawn={spawn}"
        )
    return 0


def _print_serve_banner(
    *,
    workspace: Path,
    host: str,
    port: int,
    api_key: str | None,
    admin_key: str | None,
    enable_studio: bool,
) -> None:
    base_url = _format_local_base_url(host=host, port=port)
    print("anyagent serve")
    print(f"workspace: {workspace}")
    print(f"api: {base_url}/v1")
    print(f"openapi: {base_url}/openapi.json")
    if enable_studio:
        print(f"studio: {base_url}/studio/")
    else:
        print("studio: disabled")
    print(f"api_key: {'set' if api_key else 'unset'}")
    print(f"admin_key: {'set' if admin_key else 'unset'}")
    try:
        catalog = load_agent_catalog(workspace_dir=workspace)
    except Exception as exc:  # noqa: BLE001
        print(f"agents: unavailable ({exc})")
        return
    rows = _agent_catalog_rows(catalog)
    exposed = [row["agent_id"] for row in rows if row["exposed"]]
    hidden = [row["agent_id"] for row in rows if not row["exposed"]]
    print(f"agents: {', '.join(exposed) if exposed else '-'}")
    if hidden:
        print(f"hidden_agents: {', '.join(hidden)}")


def _format_local_base_url(*, host: str, port: int) -> str:
    display_host = "127.0.0.1" if host in {"0.0.0.0", "::"} else host
    if ":" in display_host and not display_host.startswith("["):
        display_host = f"[{display_host}]"
    return f"http://{display_host}:{port}"


def _agent_catalog_rows(catalog: Any) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for pack in sorted(catalog.packs.values(), key=lambda item: item.agent_id):
        rows.append(
            {
                "agent_id": pack.agent_id,
                "exposed": bool(pack.spec.exposed),
                "sandbox_mode": pack.spec.sandbox.mode,
                "model_default": pack.spec.model.default,
                "requested_tool_names": list(pack.spec.tools.requested_tool_names),
                "default_selected_skills": list(pack.spec.skills.default_selected or []),
                "spawn_allow_agent_ids": list(pack.spec.multiagent.spawn_allow_agent_ids or []),
                "path": str(pack.root_dir),
            }
        )
    return rows


def _cmd_tool_runtime_serve(args: argparse.Namespace) -> int:
    configure_observability_from_env()
    app = asyncio.run(create_tool_runtime_app_async(
        workspace_dir=args.workspace,
        internal_key=args.internal_key,
        admin_api_key=args.admin_key,
        sandbox_root_dir=args.sandbox_root,
        plugin_roots=args.plugin_root,
        plugins_fail_open=args.plugins_fail_open,
    ))
    uvicorn.run(app, host=args.host, port=int(args.port), log_level="info")
    return 0


def _cmd_agent_api_serve(args: argparse.Namespace) -> int:
    configure_observability_from_env()
    workspace_dir = str(args.workspace)
    api_key = args.api_key or os.getenv("AGENT_API_KEY")
    if not api_key:
        raise RuntimeError("agent-api serve requires --api-key or AGENT_API_KEY")
    tool_runtime_internal_key = args.tool_runtime_internal_key or os.getenv("TOOL_RUNTIME_INTERNAL_KEY")
    if not tool_runtime_internal_key:
        raise RuntimeError("agent-api serve requires --tool-runtime-internal-key or TOOL_RUNTIME_INTERNAL_KEY")

    storage_settings = StorageSettings()
    app = create_distributed_agent_app(
        api_key=api_key,
        runtime_config=DistributedAgentRuntimeConfig(
            workspace_dir=workspace_dir,
            tool_runtime_base_url=args.tool_runtime_url
            or os.getenv("TOOL_RUNTIME_BASE_URL")
            or "http://127.0.0.1:8788",
            tool_runtime_internal_key=tool_runtime_internal_key,
            manifest_cache_ttl_seconds=float(
                args.manifest_cache_ttl_seconds
                if isinstance(args.manifest_cache_ttl_seconds, (int, float))
                else os.getenv("MANIFEST_CACHE_TTL_SECONDS", "5")
            ),
            mcp_credential_store_backend=os.getenv("MCP_CREDENTIAL_STORE_BACKEND", "none"),
            mcp_credential_store_file_root=os.getenv("MCP_CREDENTIAL_STORE_FILE_ROOT", "/data/credentials"),
            infisical_host=os.getenv("INFISICAL_HOST", "https://app.infisical.com"),
            infisical_universal_auth_client_id=os.getenv("INFISICAL_UNIVERSAL_AUTH_CLIENT_ID"),
            infisical_universal_auth_client_secret=os.getenv("INFISICAL_UNIVERSAL_AUTH_CLIENT_SECRET"),
            infisical_project_id=os.getenv("INFISICAL_PROJECT_ID"),
            infisical_environment=os.getenv("INFISICAL_ENVIRONMENT"),
            infisical_cache_ttl_seconds=int(os.getenv("INFISICAL_CACHE_TTL_SECONDS", "60")),
            infisical_credential_root_path=os.getenv("INFISICAL_CREDENTIAL_ROOT_PATH", "/anyagent/credentials"),
            infisical_path_layout=os.getenv("INFISICAL_PATH_LAYOUT", "scoped"),
        ),
        storage_factory=lambda: create_storage_runtime(storage_settings, workspace_dir=workspace_dir),
        settings=storage_settings,
        enable_keyed_serialization=not bool(args.disable_keyed_serialization),
    )
    uvicorn.run(app, host=args.host, port=int(args.port), log_level="info")
    return 0


def _cmd_init(args: argparse.Namespace) -> int:
    workspace = Path(args.workspace).expanduser().resolve()
    agent_id = _validate_init_agent_id(str(args.agent_id))
    template = str(args.template or "basic")
    force = bool(args.force)
    created: list[str] = []
    skipped: list[str] = []

    selected_skills = ["example-skill"] if bool(args.with_example_skill) else []
    _write_file(
        workspace / "AGENTS.md",
        _workspace_instructions_for_template(template),
        force=force,
        created=created,
        skipped=skipped,
    )
    _write_file(
        workspace / ".gitignore",
        _DEFAULT_WORKSPACE_GITIGNORE,
        force=force,
        created=created,
        skipped=skipped,
    )
    for spec in _init_agent_specs(template=template, primary_agent_id=agent_id, selected_skills=selected_skills):
        agent_dir = preferred_agents_root(workspace) / spec["agent_id"]
        _write_file(
            agent_dir / "agent.yaml",
            _render_agent_yaml(
                selected_skills=list(spec["selected_skills"]),
                requested_tool_names=list(spec["requested_tool_names"]),
                sandbox_mode=str(spec["sandbox_mode"]),
                spawn_allow_agent_ids=list(spec["spawn_allow_agent_ids"]),
                model_default=None,
            ),
            force=force,
            created=created,
            skipped=skipped,
        )
        _write_file(
            agent_dir / "AGENTS.md",
            str(spec["instructions"]),
            force=force,
            created=created,
            skipped=skipped,
        )
        _write_file(
            agent_dir / "mcp.json",
            _DEFAULT_MCP_JSON,
            force=force,
            created=created,
            skipped=skipped,
        )
    if agent_id != "main":
        main_spec = _default_main_agent_spec(primary_agent_id=agent_id)
        main_dir = preferred_agents_root(workspace) / "main"
        _write_file(
            main_dir / "agent.yaml",
            _render_agent_yaml(
                selected_skills=list(main_spec["selected_skills"]),
                requested_tool_names=list(main_spec["requested_tool_names"]),
                sandbox_mode=str(main_spec["sandbox_mode"]),
                spawn_allow_agent_ids=list(main_spec["spawn_allow_agent_ids"]),
                model_default=None,
            ),
            force=force,
            created=created,
            skipped=skipped,
        )
        _write_file(main_dir / "AGENTS.md", str(main_spec["instructions"]), force=force, created=created, skipped=skipped)
        _write_file(main_dir / "mcp.json", _DEFAULT_MCP_JSON, force=force, created=created, skipped=skipped)
    _write_file(
        preferred_config_root(workspace) / "skills" / ".gitkeep",
        "",
        force=force,
        created=created,
        skipped=skipped,
    )
    if bool(args.with_example_skill) or template in {"coding-agent", "research-agent", "multi-agent-team"}:
        _write_file(
            preferred_config_root(workspace) / "skills" / "example-skill" / "SKILL.md",
            _DEFAULT_EXAMPLE_SKILL,
            force=force,
            created=created,
            skipped=skipped,
        )
    _write_demo_plugin_files(workspace=workspace, force=force, created=created, skipped=skipped)

    payload = {
        "ok": True,
        "workspace": str(workspace),
        "agent_id": agent_id,
        "created": created,
        "skipped": skipped,
        "next": f"anyagent doctor --workspace {workspace}",
    }
    result = WorkspaceInitResult.model_validate(payload)
    print(result.model_dump_json(exclude_none=True))
    return 0


def _cmd_config_init(args: argparse.Namespace) -> int:
    workspace = Path(args.workspace).expanduser().resolve()
    agent_id = _validate_init_agent_id(str(args.agent_id))
    model_alias = _validate_config_key(str(args.model_alias), "--model-alias")
    provider_name = _validate_config_key(str(args.provider_name or args.provider), "--provider-name")
    provider_kind = str(args.provider)
    model_name = str(args.model or "").strip()
    if not model_name:
        raise SystemExit("--model must be non-empty")

    force = bool(args.force)
    created: list[str] = []
    skipped: list[str] = []
    requested_tool_names = _resolve_requested_tool_names(args)
    sandbox_mode = str(args.sandbox_mode or ("local-unsafe" if bool(args.with_exec) else "disabled"))
    models_yaml = _render_models_yaml(
        model_alias=model_alias,
        provider_name=provider_name,
        provider_kind=provider_kind,
        model=model_name,
        api_key_env=str(args.api_key_env).strip() if args.api_key_env else None,
        base_url=str(args.base_url).strip() if args.base_url else None,
        base_url_env=str(args.base_url_env).strip() if args.base_url_env else None,
    )
    _write_file(
        workspace_models_config_path(workspace),
        models_yaml,
        force=force,
        created=created,
        skipped=skipped,
    )
    _write_file(
        workspace / "AGENTS.md",
        _workspace_instructions_for_template("business-workspace"),
        force=force,
        created=created,
        skipped=skipped,
    )
    _write_file(
        workspace / ".gitignore",
        _DEFAULT_WORKSPACE_GITIGNORE,
        force=force,
        created=created,
        skipped=skipped,
    )
    agent_dir = preferred_agents_root(workspace) / agent_id
    _write_file(
        agent_dir / "agent.yaml",
        _render_agent_yaml(
            selected_skills=[],
            requested_tool_names=requested_tool_names,
            sandbox_mode=sandbox_mode,
            spawn_allow_agent_ids=[],
            model_default=model_alias,
        ),
        force=force,
        created=created,
        skipped=skipped,
    )
    _write_file(agent_dir / "AGENTS.md", _BASIC_AGENT_INSTRUCTIONS, force=force, created=created, skipped=skipped)
    _write_file(agent_dir / "mcp.json", _DEFAULT_MCP_JSON, force=force, created=created, skipped=skipped)
    if agent_id != "main":
        main_spec = _default_main_agent_spec(primary_agent_id=agent_id)
        main_dir = preferred_agents_root(workspace) / "main"
        _write_file(
            main_dir / "agent.yaml",
            _render_agent_yaml(
                selected_skills=list(main_spec["selected_skills"]),
                requested_tool_names=requested_tool_names,
                sandbox_mode=sandbox_mode,
                spawn_allow_agent_ids=list(main_spec["spawn_allow_agent_ids"]),
                model_default=model_alias,
            ),
            force=force,
            created=created,
            skipped=skipped,
        )
        _write_file(main_dir / "AGENTS.md", str(main_spec["instructions"]), force=force, created=created, skipped=skipped)
        _write_file(main_dir / "mcp.json", _DEFAULT_MCP_JSON, force=force, created=created, skipped=skipped)
    _write_file(preferred_config_root(workspace) / "skills" / ".gitkeep", "", force=force, created=created, skipped=skipped)
    _write_demo_plugin_files(workspace=workspace, force=force, created=created, skipped=skipped)

    config = WorkspaceModelsConfig.model_validate(yaml.safe_load(models_yaml))
    payload = {
        "ok": True,
        "workspace": str(workspace),
        "agent_id": agent_id,
        "models_config": str(workspace_models_config_path(workspace)),
        "default_model": config.default_model,
        "created": created,
        "skipped": skipped,
        "next": f"anyagent doctor --workspace {workspace}",
    }
    print(json.dumps(payload, ensure_ascii=False))
    return 0


def _cmd_doctor(args: argparse.Namespace) -> int:
    workspace = Path(args.workspace).expanduser().resolve()
    findings = _doctor_workspace(workspace)
    ok = not any(item.level == "error" for item in findings)
    payload = WorkspaceDoctorReport(ok=ok, workspace=str(workspace), findings=findings)
    if bool(args.json):
        print(payload.model_dump_json(exclude_none=True))
    else:
        print(f"anyagent doctor: {'ok' if ok else 'failed'}")
        print(f"workspace: {workspace}")
        for item in payload.findings:
            print(f"[{item.level}] {item.code}: {item.message}")
    return 0 if ok else 1


def _doctor_workspace(workspace: Path) -> list[WorkspaceDoctorFinding]:
    findings: list[WorkspaceDoctorFinding] = []

    def add(level: str, code: str, message: str) -> None:
        findings.append(WorkspaceDoctorFinding.model_validate({"level": level, "code": code, "message": message}))

    root = resolve_agents_root(workspace)
    if not root.is_dir():
        add("error", "missing_agent_root", f"missing agent packs root: {root}")
        return findings

    try:
        catalog = load_agent_catalog(workspace_dir=workspace)
    except AgentPackError as e:
        add("error", "agent_catalog_invalid", str(e))
        return findings
    except Exception as e:  # noqa: BLE001
        add("error", "agent_catalog_error", str(e))
        return findings

    if not catalog.packs:
        add("error", "no_agents", f"no agent packs found under: {root}")
        return findings

    main = catalog.get("main")
    if main is None:
        add("warning", "missing_main_agent", "no agent_id=main pack found; create one for the default `anyagent serve` entrypoint")
    elif not main.spec.exposed:
        add("error", "main_not_exposed", "agent_id=main exists but exposed=false; `anyagent serve` requires exposed main")

    for pack in catalog.packs.values():
        add("info", "agent_loaded", f"agent {pack.agent_id}: exposed={pack.spec.exposed} sandbox={pack.spec.sandbox.mode}")
        if not pack.spec.tools.requested_tool_names:
            add("warning", "agent_no_tools", f"agent {pack.agent_id} requests no tools")
        if pack.spec.sandbox.mode == "opensandbox":
            add("error", "opensandbox_unavailable", f"agent {pack.agent_id} uses opensandbox, which this build does not implement")

        skills, skill_errors = discover_skills(
            [SkillRoot(scope="agent", root=pack.skills_dir), *default_skill_roots(workspace_dir=workspace)]
        )
        for path, reason in skill_errors:
            add("warning", "skill_load_error", f"{path}: {reason}")
        disabled_ids = resolve_disabled_skill_stable_ids(
            pack.spec.skills.disabled_paths,
            skills=skills,
            base_dir=pack.root_dir,
        )
        visible_skill_names = {skill.frontmatter.name for skill in skills if skill.stable_id not in disabled_ids}
        for name in pack.spec.skills.default_selected or []:
            if isinstance(name, str) and name.startswith("skill://"):
                continue
            if name not in visible_skill_names:
                add("warning", "skill_not_found", f"agent {pack.agent_id} selects missing skill: {name}")

        if pack.mcp_config is not None:
            for label, server in sorted(pack.mcp_config.mcpServers.items()):
                transport = server.infer_transport().value
                add("info", "mcp_server_loaded", f"agent {pack.agent_id} mcp {label}: transport={transport}")
                if server.command:
                    command = server.command.strip()
                    if os.sep not in command and shutil.which(command) is None:
                        add("warning", "mcp_command_missing", f"agent {pack.agent_id} mcp {label} command not found: {command}")
                    if server.cwd and not Path(server.cwd).expanduser().exists():
                        add("warning", "mcp_cwd_missing", f"agent {pack.agent_id} mcp {label} cwd missing: {server.cwd}")

    if not findings:
        add("info", "workspace_ok", "workspace is valid")
    return findings


def _validate_init_agent_id(agent_id: str) -> str:
    value = agent_id.strip()
    if not value:
        raise SystemExit("--agent-id must be non-empty")
    if len(value) > 64 or any(ch not in "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_.-" for ch in value):
        raise SystemExit("--agent-id must match [a-zA-Z0-9_.-]{1,64}")
    return value


def _validate_config_key(value: str, flag: str) -> str:
    value = value.strip()
    if not value:
        raise SystemExit(f"{flag} must be non-empty")
    if len(value) > 128 or any(ch not in "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_.-" for ch in value):
        raise SystemExit(f"{flag} must match [a-zA-Z0-9_.-]{{1,128}}")
    return value


def _resolve_requested_tool_names(args: argparse.Namespace) -> list[str]:
    requested: list[str] = []
    for tool in args.tool or []:
        value = str(tool).strip()
        if value and value not in requested:
            requested.append(value)
    if bool(args.with_web_fetch) and "core.web_fetch" not in requested:
        requested.append("core.web_fetch")
    if bool(args.with_exec) and "exec" not in requested:
        requested.append("exec")
    return requested


def _write_file(path: Path, text: str, *, force: bool, created: list[str], skipped: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists() and not force:
        skipped.append(str(path))
        return
    path.write_text(text, encoding="utf-8")
    created.append(str(path))


def _write_demo_plugin_files(*, workspace: Path, force: bool, created: list[str], skipped: list[str]) -> None:
    plugin_dir = workspace / "plugins" / "demo"
    for rel, text in _DEMO_PLUGIN_FILES.items():
        _write_file(plugin_dir / rel, text, force=force, created=created, skipped=skipped)


def _render_agent_yaml(
    *,
    selected_skills: list[str],
    requested_tool_names: list[str] | None = None,
    sandbox_mode: str = "disabled",
    spawn_allow_agent_ids: list[str] | None = None,
    model_default: str | None = None,
) -> str:
    skills_block = (
        "  default_selected: []\n"
        if not selected_skills
        else "  default_selected:\n" + "".join(f"    - {name}\n" for name in selected_skills)
    )
    tools = list(requested_tool_names or [])
    tools_block = (
        "  requested_tool_names: []\n"
        if not tools
        else "  requested_tool_names:\n" + "".join(f"    - {name}\n" for name in tools)
    )
    spawn_ids = list(spawn_allow_agent_ids or [])
    spawn_block = (
        "  spawn_allow_agent_ids: []\n"
        if not spawn_ids
        else "  spawn_allow_agent_ids:\n" + "".join(f"    - {agent_id}\n" for agent_id in spawn_ids)
    )
    model_block = (
        ""
        if not model_default
        else "# Model alias from workspace-root models.yaml. Request body `model` can still override it.\n"
        f"model:\n  default: {model_default}\n"
    )
    return (
        "# AnyAgent agent pack configuration.\n"
        "# This file controls what the server may expose to the model. AGENTS.md gives behavior instructions,\n"
        "# but tool access, sandbox mode, selected skills, and child-agent boundaries are enforced here.\n"
        "exposed: true\n"
        "# exposed=true means external callers may select this agent via metadata.agent_id / x-agent-id.\n"
        "# Set false for worker agents that should only be spawned by another agent.\n"
        f"{model_block}"
        "tools:\n"
        "  # requested_tool_names is the default tool allowlist request for this agent.\n"
        "  # Tools must also be registered by Core / MCP / Tool Runtime plugins before they become visible.\n"
        "  # Plugin demo note: generated plugins/demo registers app.demo.echo, but it stays inactive until\n"
        "  # you start standalone Tool Runtime with --plugin-root plugins and add app.demo.echo below.\n"
        f"{tools_block}"
        "skills:\n"
        "  # default_selected names workspace or agent-local skills selected for every run of this agent.\n"
        "  # Skills can add instructions and may request additional tools via their agents/openai.yaml metadata.\n"
        f"{skills_block}"
        "sandbox:\n"
        "  # disabled: no command execution. local-unsafe: local development only. opensandbox/external: production isolation.\n"
        f"  mode: {sandbox_mode}\n"
        "multiagent:\n"
        "  # Child agents this agent is allowed to spawn. Keep empty unless you intentionally build a multi-agent flow.\n"
        f"{spawn_block}"
    )


def _render_models_yaml(
    *,
    model_alias: str,
    provider_name: str,
    provider_kind: str,
    model: str,
    api_key_env: str | None,
    base_url: str | None,
    base_url_env: str | None,
) -> str:
    provider: dict[str, str] = {"kind": provider_kind}
    if api_key_env:
        provider["api_key_env"] = api_key_env
    elif provider_kind == "anthropic":
        provider["api_key_env"] = "ANTHROPIC_API_KEY"
    elif provider_kind == "gemini":
        provider["api_key_env"] = "GOOGLE_API_KEY"
    else:
        provider["api_key_env"] = "OPENAI_API_KEY"
    if base_url:
        provider["base_url"] = base_url
    if base_url_env:
        provider["base_url_env"] = base_url_env
    provider_lines = [
        "# Workspace model/provider catalog.",
        "# Agent packs reference models by alias through `.anyagent/agents/<agent_id>/agent.yaml`:",
        f"#   model.default: {model_alias}",
        "# Keep credentials in environment variables or a secret manager; do not commit plaintext keys.",
        f"default_model: {_yaml_scalar(model_alias)}",
        "",
        "providers:",
        f"  {provider_name}:",
        f"    # kind selects the provider adapter: openai | anthropic | gemini.",
        f"    kind: {_yaml_scalar(provider['kind'])}",
    ]
    if "api_key_env" in provider:
        provider_lines.extend(
            [
                "    # api_key_env names the environment variable read at runtime.",
                f"    api_key_env: {_yaml_scalar(provider['api_key_env'])}",
            ]
        )
    if "base_url" in provider:
        provider_lines.extend(
            [
                "    # Optional literal provider base URL. Prefer base_url_env for per-environment overrides.",
                f"    base_url: {_yaml_scalar(provider['base_url'])}",
            ]
        )
    if "base_url_env" in provider:
        provider_lines.extend(
            [
                "    # Optional env var for OpenAI-compatible or proxy base URL.",
                f"    base_url_env: {_yaml_scalar(provider['base_url_env'])}",
            ]
        )
    provider_lines.extend(
        [
            "",
            "models:",
            f"  {model_alias}:",
            "    # provider points to one entry under providers.",
            f"    provider: {_yaml_scalar(provider_name)}",
            "    # model is the upstream provider model name sent to the model API.",
            f"    model: {_yaml_scalar(model)}",
            "",
        ]
    )
    return "\n".join(provider_lines)


def _yaml_scalar(value: str) -> str:
    return json.dumps(value, ensure_ascii=False)


def _workspace_instructions_for_template(template: str) -> str:
    return f"""# Workspace Instructions

This workspace was generated by `anyagent init --template {template}`.

- Agent behavior lives in `.anyagent/agents/<agent_id>/AGENTS.md`.
- Tool, skill, sandbox, MCP, and multi-agent boundaries live in `agent.yaml` and `mcp.json`.
- Do not store plaintext credentials in repository files; use the Admin Credential API.
"""


_DEFAULT_WORKSPACE_GITIGNORE = """.venv/
.env
.env.local
.env.*.local
.run/
.runs/
.pip/
__pycache__/
*.py[cod]
"""


def _init_agent_specs(*, template: str, primary_agent_id: str, selected_skills: list[str]) -> list[dict[str, object]]:
    if template == "coding-agent":
        return [
            {
                "agent_id": primary_agent_id,
                "selected_skills": selected_skills,
                "requested_tool_names": ["exec"],
                "sandbox_mode": "local-unsafe",
                "spawn_allow_agent_ids": [],
                "instructions": _CODING_AGENT_INSTRUCTIONS,
            }
        ]
    if template == "research-agent":
        return [
            {
                "agent_id": primary_agent_id,
                "selected_skills": selected_skills,
                "requested_tool_names": ["core.web_fetch"],
                "sandbox_mode": "disabled",
                "spawn_allow_agent_ids": [],
                "instructions": _RESEARCH_AGENT_INSTRUCTIONS,
            }
        ]
    if template == "multi-agent-team":
        coordinator = primary_agent_id
        child_ids = ["researcher", "coder"] if coordinator not in {"researcher", "coder"} else ["researcher-helper", "coder-helper"]
        return [
            {
                "agent_id": coordinator,
                "selected_skills": selected_skills,
                "requested_tool_names": [],
                "sandbox_mode": "disabled",
                "spawn_allow_agent_ids": child_ids,
                "instructions": _COORDINATOR_AGENT_INSTRUCTIONS.format(researcher=child_ids[0], coder=child_ids[1]),
            },
            {
                "agent_id": child_ids[0],
                "selected_skills": selected_skills,
                "requested_tool_names": ["core.web_fetch"],
                "sandbox_mode": "disabled",
                "spawn_allow_agent_ids": [],
                "instructions": _RESEARCH_AGENT_INSTRUCTIONS,
            },
            {
                "agent_id": child_ids[1],
                "selected_skills": selected_skills,
                "requested_tool_names": ["exec"],
                "sandbox_mode": "local-unsafe",
                "spawn_allow_agent_ids": [],
                "instructions": _CODING_AGENT_INSTRUCTIONS,
            },
        ]
    return [
        {
            "agent_id": primary_agent_id,
            "selected_skills": selected_skills,
            "requested_tool_names": [],
            "sandbox_mode": "disabled",
            "spawn_allow_agent_ids": [],
            "instructions": _BASIC_AGENT_INSTRUCTIONS,
        }
    ]


def _default_main_agent_spec(*, primary_agent_id: str) -> dict[str, object]:
    return {
        "agent_id": "main",
        "selected_skills": [],
        "requested_tool_names": [],
        "sandbox_mode": "disabled",
        "spawn_allow_agent_ids": [primary_agent_id],
        "instructions": _DEFAULT_MAIN_AGENT_INSTRUCTIONS.format(primary_agent_id=primary_agent_id),
    }


_BASIC_AGENT_INSTRUCTIONS = """# Main Agent

You are the default anyagent assistant for this workspace.

- Follow the user's request directly.
- Use configured skills when they apply.
- Use configured MCP tools only through their exposed tool names.
- Do not treat AGENTS.md as a permission source; tool access is controlled by agent.yaml and the server.
"""


_DEFAULT_MAIN_AGENT_INSTRUCTIONS = """# Main Agent

You are the default entrypoint for this workspace.

- Use `{primary_agent_id}` as the primary business agent when the user request belongs to that configured workflow.
- Keep default-entrypoint behavior thin; business-specific behavior belongs in `.anyagent/agents/{primary_agent_id}/AGENTS.md`.
- Use configured skills when they apply.
- Use configured MCP tools only through their exposed tool names.
- Do not treat AGENTS.md as a permission source; tool access is controlled by agent.yaml and the server.
"""


_CODING_AGENT_INSTRUCTIONS = """# Coding Agent

You are a coding-focused anyagent assistant.

- Inspect the relevant files before proposing code changes.
- Prefer small, reviewable edits that match the existing project style.
- Use `exec` for local verification when available.
- Report changed files and verification results clearly.
- Do not read or print secrets from the environment.
"""


_RESEARCH_AGENT_INSTRUCTIONS = """# Research Agent

You are a research-focused anyagent assistant.

- Break broad questions into concrete search and synthesis steps.
- Prefer primary sources and cite stable facts when possible.
- Keep raw source excerpts short and summarize in your own words.
- Distinguish verified facts from assumptions.
"""


_COORDINATOR_AGENT_INSTRUCTIONS = """# Coordinator Agent

You coordinate work across specialized agents.

- Use `{researcher}` for discovery, source gathering, and factual synthesis.
- Use `{coder}` for implementation-oriented work and verification.
- Keep parent context separate from child agent contexts.
- Summarize decisions and handoff points explicitly.
"""


_DEFAULT_MCP_JSON = """{
  "_comment": "AnyAgent MCP configuration. Keep this file free of plaintext secrets; use auth.credential_id and the Admin Credential API. Add servers under mcpServers when needed.",
  "_example_streamable_http_server": {
    "enabled": false,
    "url": "https://example.com/mcp",
    "transport": "streamable_http",
    "auth": {
      "credential_id": "cred_example_mcp",
      "ref_kind": "bearer_token",
      "injection": "header:Authorization",
      "format": "Bearer {value}"
    },
    "tool_filter": {
      "allowed_tool_names": ["example.tool_name"]
    }
  },
  "_example_stdio_server": {
    "enabled": false,
    "command": "npx",
    "args": ["-y", "example-mcp-server"],
    "cwd": "."
  },
  "mcpServers": {}
}
"""


_DEFAULT_EXAMPLE_SKILL = """---
name: example-skill
description: Minimal example skill generated by `anyagent init`.
metadata:
  short-description: Example skill
---

# Example Skill

Use this skill when the user asks for a simple demonstration of workspace-local skills.
"""


_DEMO_PLUGIN_FILES = {
    "plugin.json": """{
  "_comment": "Demo plugin manifest. This file is valid JSON, so comments are stored in _comment fields and ignored by AnyAgent.",
  "plugin_id": "demo",
  "_plugin_id_comment": "Stable plugin id. Keep it short and unique under this workspace.",
  "description": "Inactive demo Tool Runtime plugin generated by anyagent init.",
  "_channels_comment": "Logical channel labels for discovery only; this demo registers an app.* tool, not a chat channel connector.",
  "channels": ["demo"],
  "_entrypoint_comment": "Relative Python entrypoint loaded as file.py:function. The function receives an AnyAgent plugin API.",
  "entrypoint": "plugin.py:register",
  "_refs_comment": "docs/schemas/tests are returned by plugin catalog so agents and humans can trace this plugin back to its sources.",
  "docs": ["README.md"],
  "schemas": ["schemas/config.schema.json"],
  "tests": ["tests/smoke.py"]
}
""",
    "plugin.py": '''"""Demo AnyAgent Tool Runtime plugin.

This file is generated as a learning scaffold. It is intentionally inactive by
default:

1. `anyagent serve` does not load workspace plugins automatically yet.
2. Even when a standalone Tool Runtime loads this plugin, the tool is invisible
   until an agent requests `app.demo.echo` in `.anyagent/agents/<agent_id>/agent.yaml`.

To try it locally:

    anyagent tool-runtime serve --workspace . --plugin-root plugins --internal-key dev-internal --admin-key anyagent-dev-key
    anyagent agent-api serve --workspace . --api-key anyagent-dev-key --tool-runtime-internal-key dev-internal

Then add `app.demo.echo` to an agent's `tools.requested_tool_names`.
"""

from anyagent.tool_runtime.models import ToolDefinition


async def echo(args, context):
    """Return the provided text with small execution metadata.

    Handlers receive validated JSON arguments plus a context dict containing
    agent_id/session_key/response_id/tool_call_id and trace/audit metadata. Do
    not read plaintext secrets from files or env here; declare credentials on
    ToolDefinition.credentials and read injected values from context["_credentials"].
    """

    text = args["text"]
    agent_id = context.get("agent_id", "unknown-agent")
    session_key = context.get("session_key", "unknown-session")
    return f"[demo plugin] {text} (agent={agent_id}, session={session_key})"


def register(api):
    """Register plugin capabilities for the current host.

    `api.host_kind` lets one plugin support multiple hosts in the future. This
    demo only registers a Tool Runtime tool.
    """

    if api.host_kind != "tool_runtime":
        return

    api.registerTool(
        ToolDefinition(
            name="app.demo.echo",
            description="Echo text through the generated demo plugin.",
            category="app",
            kind="command",
            parameters={
                "type": "object",
                "additionalProperties": False,
                "required": ["text"],
                "properties": {
                    "text": {
                        "type": "string",
                        "description": "Text to echo back from the demo plugin.",
                    }
                },
            },
        ),
        echo,
    )
''',
    "README.md": """# Demo AnyAgent Plugin

This plugin is generated as a safe, inactive example.

It registers one Tool Runtime tool:

- `app.demo.echo`

The tool is not visible to agents by default. Two things must happen before a
model can call it:

1. Start a standalone Tool Runtime with this plugin root:

   ```bash
   anyagent tool-runtime serve \\
     --workspace . \\
     --plugin-root plugins \\
     --internal-key dev-internal \\
     --admin-key anyagent-dev-key
   ```

2. Add the tool name to the target agent:

   ```yaml
   tools:
     requested_tool_names:
       - app.demo.echo
   ```

Then start the Agent API against that Tool Runtime:

```bash
anyagent agent-api serve \\
  --workspace . \\
  --api-key anyagent-dev-key \\
  --tool-runtime-internal-key dev-internal
```

Useful checks:

```bash
anyagent plugin catalog --admin-url http://127.0.0.1:8788 --admin-key anyagent-dev-key
```

```python
from anyagent import AnyAgent

client = AnyAgent(base_url="http://127.0.0.1:8787", api_key="anyagent-dev-key")
explain = await client.tools.explain("app.demo.echo", agent_id="main")
print(explain.visible, explain.notes)
```
""",
    "schemas/config.schema.json": """{
  "$comment": "Optional config.json schema for this plugin. The generated demo has no configurable fields; add properties here before adding plugins/demo/config.json.",
  "type": "object",
  "additionalProperties": false,
  "properties": {}
}
""",
    "tests/smoke.py": '''"""Smoke test for the generated demo plugin.

Run from the workspace root after installing anyagent:

    python plugins/demo/tests/smoke.py
"""

from pathlib import Path
import importlib.util


def test_registers_demo_tool():
    plugin_path = Path(__file__).resolve().parents[1] / "plugin.py"
    spec = importlib.util.spec_from_file_location("demo_plugin_smoke", plugin_path)
    module = importlib.util.module_from_spec(spec)
    assert spec is not None and spec.loader is not None
    spec.loader.exec_module(module)

    class Api:
        host_kind = "tool_runtime"

        def __init__(self):
            self.tools = []

        def registerTool(self, tool, handler):
            self.tools.append((tool, handler))

    api = Api()
    module.register(api)
    assert api.tools[0][0].name == "app.demo.echo"


if __name__ == "__main__":
    test_registers_demo_tool()
    print("ok: demo plugin smoke")
''',
}


def _add_common_admin_flags(p: argparse.ArgumentParser) -> None:
    p.add_argument(
        "--admin-url",
        default=None,
        help="Admin API base URL (default: $ADMIN_URL or http://127.0.0.1:8787).",
    )
    p.add_argument("--admin-key", default=None, help="Admin API key (default: $ADMIN_API_KEY).")


def _admin_client_from_args(args: argparse.Namespace) -> _AdminClient:
    url = args.admin_url or os.getenv("ADMIN_URL") or "http://127.0.0.1:8787"
    key = args.admin_key or os.getenv("ADMIN_API_KEY") or ""
    if not key.strip():
        raise SystemExit("ADMIN_API_KEY is required (use --admin-key or env var)")
    return _AdminClient(url=url.rstrip("/"), key=key.strip())


def _resolve_value(*, value: str | None, value_from_env: str | None) -> str:
    if value is not None and value_from_env is not None:
        raise SystemExit("provide only one of --value or --value-from-env")
    if value_from_env is not None:
        env_name = value_from_env.strip()
        if not env_name:
            raise SystemExit("--value-from-env must be a non-empty env var name")
        v = os.getenv(env_name)
        if v is None or not v.strip():
            raise SystemExit(f"env var is empty: {env_name}")
        return v.strip()
    if value is None or not str(value).strip():
        raise SystemExit("--value is required (or use --value-from-env)")
    return str(value).strip()


def _parse_scope(*, level: str, agent_id: str | None) -> CredentialScope:
    if level == "global":
        return CredentialScope(level="global")
    if level == "agent":
        if not agent_id or not agent_id.strip():
            raise SystemExit("--agent-id is required when --scope=agent")
        return CredentialScope(level="agent", agent_id=agent_id.strip())
    raise SystemExit(f"unsupported scope: {level}")


def _build_metadata(
    *,
    display_name: str | None,
    provider: str | None,
    env_var_name: str | None,
    metadata_json: str | None,
) -> dict[str, Any]:
    metadata: dict[str, Any] = {}
    if metadata_json:
        try:
            obj = json.loads(metadata_json)
        except Exception as e:
            raise SystemExit(f"--metadata-json must be valid JSON: {e}") from e
        if not isinstance(obj, dict):
            raise SystemExit("--metadata-json must decode to an object")
        metadata.update(obj)

    if display_name:
        metadata["display_name"] = display_name
    if provider:
        metadata["provider"] = provider
    if env_var_name:
        metadata["env_var_name"] = env_var_name
    return metadata


def _cmd_import(client: _AdminClient, *, file_path: str, dry_run: bool, skip_missing: bool) -> int:
    p = file_path.strip()
    if not p:
        raise SystemExit("--file must be non-empty")
    with open(p, "r", encoding="utf-8") as f:
        doc = yaml.safe_load(f)

    if not isinstance(doc, dict):
        raise SystemExit("credentials file must be a YAML object")
    items = doc.get("credentials")
    if not isinstance(items, list):
        raise SystemExit("credentials file must include 'credentials: [...]'")

    ok = 0
    skipped = 0
    for i, raw in enumerate(items):
        if not isinstance(raw, dict):
            raise SystemExit(f"credentials[{i}] must be an object")

        credential_id = raw.get("credential_id")
        kind = raw.get("kind")
        scope_raw = raw.get("scope")
        metadata = raw.get("metadata") or {}

        if not isinstance(credential_id, str) or not credential_id.strip():
            raise SystemExit(f"credentials[{i}].credential_id must be non-empty string")
        if not isinstance(kind, str) or not kind.strip():
            raise SystemExit(f"credentials[{i}].kind must be non-empty string")
        if not isinstance(scope_raw, dict):
            raise SystemExit(f"credentials[{i}].scope must be an object")
        if not isinstance(metadata, dict):
            raise SystemExit(f"credentials[{i}].metadata must be an object (or omitted)")

        scope = CredentialScope.model_validate(scope_raw)

        value = _import_resolve_value(raw, index=i)
        if not value:
            if skip_missing:
                skipped += 1
                continue
            raise SystemExit(f"credentials[{i}] has empty value (use --skip-missing to ignore)")

        req = AdminCredentialSetRequest(
            credential_id=credential_id.strip(),
            kind=kind.strip(),
            value=value,
            scope=scope,
            metadata=dict(metadata),
        )
        if not dry_run:
            client.set_credential(req)
        ok += 1

    print(json.dumps({"ok": True, "set": ok, "skipped": skipped, "dry_run": dry_run}, ensure_ascii=False))
    return 0


def _import_resolve_value(raw: dict[str, Any], *, index: int) -> str:
    direct = raw.get("value")
    if direct is not None:
        return str(direct).strip()

    env_name = raw.get("value_from_env")
    default_value = raw.get("default_value")
    default_str = "" if default_value is None else str(default_value).strip()

    if env_name is None:
        return default_str
    if not isinstance(env_name, str) or not env_name.strip():
        raise SystemExit(f"credentials[{index}].value_from_env must be string")
    v = os.getenv(env_name.strip(), default_str).strip()
    return v


def _raise_for_status(r: httpx.Response) -> None:
    if 200 <= r.status_code < 300:
        return
    text = r.text
    if len(text) > 2000:
        text = text[:2000] + "...(truncated)"
    raise SystemExit(f"HTTP {r.status_code}: {text}")


if __name__ == "__main__":
    raise SystemExit(main())
