from __future__ import annotations

import argparse
import json
import os
from dataclasses import dataclass
from typing import Any

import httpx
import uvicorn
import yaml

from anyagent.protocol.credential_vault import (
    AdminCredentialListResponse,
    AdminCredentialRef,
    AdminCredentialSetRequest,
    CredentialScope,
)
from anyagent.server import create_app
from anyagent.server.migrations import apply_storage_migrations


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

    def delete_credential(self, credential_id: str) -> dict[str, Any]:
        r = httpx.delete(
            f"{self.url}/admin/credentials/{credential_id}",
            headers=self._headers(),
            timeout=15.0,
        )
        _raise_for_status(r)
        obj = r.json()
        if not isinstance(obj, dict):
            raise ValueError("unexpected delete response (not an object)")
        return obj

    def storage_health(self) -> dict[str, Any]:
        r = httpx.get(
            f"{self.url}/admin/storage/health",
            headers=self._headers(),
            timeout=15.0,
        )
        _raise_for_status(r)
        obj = r.json()
        if not isinstance(obj, dict):
            raise ValueError("unexpected storage health response (not an object)")
        return obj


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="anyagent")
    sub = parser.add_subparsers(dest="cmd", required=True)

    serve = sub.add_parser("serve", help="Start the built-in anyagent server.")
    serve.add_argument("--workspace", default=".", help="Workspace root containing `.agents/`.")
    serve.add_argument("--host", default="127.0.0.1")
    serve.add_argument("--port", type=int, default=8787)
    serve.add_argument("--api-key", default=None, help="Bearer token for `/v1/*` and `/internal/*` APIs.")
    serve.add_argument("--admin-key", default=None, help="Bearer token for `/admin/*` APIs.")
    serve.add_argument("--sandbox-root", default=None, help="Optional root dir for local sandbox sessions.")
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

    storage_health = sub.add_parser("storage-health", help="Check built-in server storage backends and connectivity.")
    _add_common_admin_flags(storage_health)

    migrate = sub.add_parser("storage-migrate", help="Apply PostgreSQL storage migrations.")
    migrate.add_argument("--postgres-dsn", default=None, help="Override POSTGRES_DSN.")
    migrate.add_argument("--postgres-schema", default=None, help="Override POSTGRES_SCHEMA.")
    migrate.add_argument("--dry-run", action="store_true", help="Only print planned migrations.")

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

    args = parser.parse_args(argv)
    if args.cmd == "serve":
        return _cmd_serve(args)
    if args.cmd == "storage-health":
        client = _admin_client_from_args(args)
        print(json.dumps(client.storage_health(), ensure_ascii=False))
        return 0
    if args.cmd == "storage-migrate":
        result = apply_storage_migrations(
            postgres_dsn=args.postgres_dsn,
            postgres_schema=args.postgres_schema,
            dry_run=bool(args.dry_run),
        )
        print(json.dumps(result, ensure_ascii=False))
        return 0
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
        obj = client.delete_credential(args.credential_id)
        print(json.dumps(obj, ensure_ascii=False))
        return 0

    if args.cred_cmd == "import":
        return _cmd_import(client, file_path=args.file, dry_run=args.dry_run, skip_missing=args.skip_missing)

    parser.error("unsupported credential command")


def _cmd_serve(args: argparse.Namespace) -> int:
    api_key = args.api_key or os.getenv("ANYAGENT_API_KEY")
    admin_key = args.admin_key or os.getenv("ADMIN_API_KEY")
    app = create_app(
        workspace_dir=args.workspace,
        api_key=api_key,
        admin_api_key=admin_key,
        sandbox_root_dir=args.sandbox_root,
        storage_mode=args.storage_mode,
        event_store_backend=args.event_store_backend,
        run_store_backend=args.run_store_backend,
        session_store_backend=args.session_store_backend,
        session_lock_backend=args.session_lock_backend,
        session_lease_ttl_s=args.session_lease_ttl_s,
    )
    uvicorn.run(app, host=args.host, port=int(args.port), log_level="info")
    return 0


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
