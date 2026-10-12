"""`anyagent credential` commands against the Admin API."""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import yaml

from anyagent.cli.admin_client import AdminClient, admin_client_from_args, add_admin_flags
from anyagent.config.env import getenv
from anyagent.protocol.credential_vault import AdminCredentialSetRequest, CredentialScope


def register_credential(subparsers: Any, bind: Any) -> None:
    """Register credential set/list/delete/import."""

    cred = subparsers.add_parser("credential", help="Manage credentials via the built-in Admin API.")
    add_admin_flags(cred)
    cred_sub = cred.add_subparsers(dest="credential_command", required=True)

    cred_set = cred_sub.add_parser("set", help="Set (create/update) a credential (write-only).")
    add_admin_flags(cred_set)
    cred_set.add_argument("--id", dest="credential_id", required=True)
    cred_set.add_argument("--kind", required=True)
    cred_set.add_argument("--value", default=None, help="Plaintext value (avoid shell history).")
    cred_set.add_argument("--value-from-env", default=None, help="Read plaintext value from an environment variable.")
    cred_set.add_argument("--scope", choices=["global", "agent", "session"], default="global")
    cred_set.add_argument("--agent-id", default=None, help="Required when --scope=agent or --scope=session.")
    cred_set.add_argument("--session-key", default=None, help="Required when --scope=session.")
    cred_set.add_argument("--expires-at", default=None, help="Credential expiration timestamp (ISO 8601).")
    cred_set.add_argument("--rotate-before", default=None, help="Credential rotation timestamp (ISO 8601).")
    cred_set.add_argument("--display-name", default=None)
    cred_set.add_argument("--provider", default=None)
    cred_set.add_argument("--env-var-name", default=None, help="Optional metadata.env_var_name for EnvBackend.")
    cred_set.add_argument("--metadata-json", default=None, help="Extra metadata JSON object.")
    bind(cred_set, ("credential", "set"), cmd_credential_set)

    cred_list = cred_sub.add_parser("list", help="List credential references (no plaintext).")
    add_admin_flags(cred_list)
    cred_list.add_argument("--json", action="store_true", help="Print JSON (default).")
    bind(cred_list, ("credential", "list"), cmd_credential_list)

    cred_delete = cred_sub.add_parser("delete", help="Delete a credential by id.")
    add_admin_flags(cred_delete)
    cred_delete.add_argument("--id", dest="credential_id", required=True)
    bind(cred_delete, ("credential", "delete"), cmd_credential_delete)

    cred_import = cred_sub.add_parser("import", help="Import credentials from a YAML file.")
    add_admin_flags(cred_import)
    cred_import.add_argument("--file", required=True, help="YAML file path (credentials.yaml).")
    cred_import.add_argument("--dry-run", action="store_true")
    cred_import.add_argument("--skip-missing", action="store_true", help="Skip items with an empty resolved value.")
    bind(cred_import, ("credential", "import"), cmd_credential_import)


def cmd_credential_set(args: argparse.Namespace) -> int:
    client = admin_client_from_args(args)
    value = _resolve_value(value=args.value, value_from_env=args.value_from_env)
    scope = _parse_scope(level=args.scope, agent_id=args.agent_id, session_key=args.session_key)
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
            expires_at=_parse_datetime_arg(args.expires_at, flag="--expires-at"),
            rotate_before=_parse_datetime_arg(args.rotate_before, flag="--rotate-before"),
        )
    )
    print(json.dumps(ref.model_dump(exclude_none=True), ensure_ascii=False))
    return 0


def cmd_credential_list(args: argparse.Namespace) -> int:
    client = admin_client_from_args(args)
    response = client.list_credentials()
    print(json.dumps(response.model_dump(exclude_none=True), ensure_ascii=False))
    return 0


def cmd_credential_delete(args: argparse.Namespace) -> int:
    client = admin_client_from_args(args)
    response = client.delete_credential(args.credential_id)
    print(json.dumps(response.model_dump(exclude_none=True), ensure_ascii=False))
    return 0


def cmd_credential_import(args: argparse.Namespace) -> int:
    client = admin_client_from_args(args)
    return _import_credentials(client, file_path=args.file, dry_run=bool(args.dry_run), skip_missing=bool(args.skip_missing))


def _resolve_value(*, value: str | None, value_from_env: str | None) -> str:
    """Resolve a credential plaintext from a flag or a named environment variable.

    The variable name is the operator's input. It is not a server setting.
    """

    if value is not None and value_from_env is not None:
        raise SystemExit("provide only one of --value or --value-from-env")
    if value_from_env is not None:
        env_name = value_from_env.strip()
        if not env_name:
            raise SystemExit("--value-from-env must be a non-empty env var name")
        found = getenv(env_name)
        if found is None or not found.strip():
            raise SystemExit(f"env var is empty: {env_name}")
        return found.strip()
    if value is None or not str(value).strip():
        raise SystemExit("--value is required (or use --value-from-env)")
    return str(value).strip()


def _parse_scope(*, level: str, agent_id: str | None, session_key: str | None = None) -> CredentialScope:
    if level == "global":
        return CredentialScope(level="global")
    if level == "agent":
        if not agent_id or not agent_id.strip():
            raise SystemExit("--agent-id is required when --scope=agent")
        return CredentialScope(level="agent", agent_id=agent_id.strip())
    if level == "session":
        if not agent_id or not agent_id.strip():
            raise SystemExit("--agent-id is required when --scope=session")
        if not session_key or not session_key.strip():
            raise SystemExit("--session-key is required when --scope=session")
        return CredentialScope(level="session", agent_id=agent_id.strip(), session_key=session_key.strip())
    raise SystemExit(f"unsupported scope: {level}")


def _parse_datetime_arg(value: str | None, *, flag: str) -> datetime | None:
    if value is None or not str(value).strip():
        return None
    try:
        parsed = datetime.fromisoformat(str(value).strip().replace("Z", "+00:00"))
    except ValueError as exc:
        raise SystemExit(f"{flag} must be an ISO 8601 timestamp") from exc
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


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
        except Exception as exc:
            raise SystemExit(f"--metadata-json must be valid JSON: {exc}") from exc
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


def _import_credentials(client: AdminClient, *, file_path: str, dry_run: bool, skip_missing: bool) -> int:
    text = file_path.strip()
    if not text:
        raise SystemExit("--file must be non-empty")
    path = Path(text)
    try:
        loaded = yaml.safe_load(path.read_text(encoding="utf-8"))
    except OSError as exc:
        print(f"failed to read credentials file: {exc}", file=sys.stderr)
        return 1
    if not isinstance(loaded, dict):
        raise SystemExit("credentials file must be a YAML object")
    items = loaded.get("credentials")
    if not isinstance(items, list):
        raise SystemExit("credentials file must include 'credentials: [...]'")

    ok = 0
    skipped = 0
    for index, raw in enumerate(items):
        if not isinstance(raw, dict):
            raise SystemExit(f"credentials[{index}] must be an object")
        credential_id = raw.get("credential_id")
        kind = raw.get("kind")
        scope_raw = raw.get("scope")
        metadata = raw.get("metadata") or {}
        expires_at = raw.get("expires_at")
        rotate_before = raw.get("rotate_before")
        if not isinstance(credential_id, str) or not credential_id.strip():
            raise SystemExit(f"credentials[{index}].credential_id must be non-empty string")
        if not isinstance(kind, str) or not kind.strip():
            raise SystemExit(f"credentials[{index}].kind must be non-empty string")
        if not isinstance(scope_raw, dict):
            raise SystemExit(f"credentials[{index}].scope must be an object")
        if not isinstance(metadata, dict):
            raise SystemExit(f"credentials[{index}].metadata must be an object (or omitted)")
        scope = CredentialScope.model_validate(scope_raw)
        value = _import_resolve_value(raw, index=index)
        if not value:
            if skip_missing:
                skipped += 1
                continue
            raise SystemExit(f"credentials[{index}] has empty value (use --skip-missing to ignore)")
        request = AdminCredentialSetRequest(
            credential_id=credential_id.strip(),
            kind=kind.strip(),
            value=value,
            scope=scope,
            metadata=dict(metadata),
            expires_at=_parse_datetime_arg(expires_at, flag=f"credentials[{index}].expires_at")
            if isinstance(expires_at, str)
            else None,
            rotate_before=_parse_datetime_arg(rotate_before, flag=f"credentials[{index}].rotate_before")
            if isinstance(rotate_before, str)
            else None,
        )
        if not dry_run:
            client.set_credential(request)
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
    found = getenv(env_name.strip())
    text = default_str if found is None else found
    return text.strip()
