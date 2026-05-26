from __future__ import annotations

import os
import asyncio
import threading
from pathlib import Path
from typing import Any

import yaml

from anyagent.protocol.tool_runtime import AuthRef
from anyagent.server.security.credential_runtime import CredentialRuntimeConfig, build_credential_resolver_from_config


def load_workspace_env_defaults(workspace_dir: Path) -> None:
    for candidate in (workspace_dir / ".env", workspace_dir / ".env.local"):
        if not candidate.is_file():
            continue
        for raw_line in candidate.read_text(encoding="utf-8").splitlines():
            line = raw_line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, value = line.split("=", 1)
            key = key.strip()
            value = value.strip()
            if key and key not in os.environ:
                os.environ[key] = value


async def hydrate_workspace_runtime_environment_async(workspace_dir: Path) -> None:
    payload = _load_workspace_secrets_payload(workspace_dir)
    if payload is None:
        return
    await _hydrate_runtime_env_from_credential_vault(workspace_dir, payload)


def load_workspace_secret_source_defaults(workspace_dir: Path) -> None:
    payload = _load_workspace_secrets_payload(workspace_dir)
    if payload is None:
        return
    mcp_payload = payload.get("mcp_credentials")
    if isinstance(mcp_payload, dict):
        _apply_secret_source_env_defaults(
            mcp_payload,
            mapping={
                "backend": "MCP_CREDENTIAL_STORE_BACKEND",
                "file_root": "MCP_CREDENTIAL_STORE_FILE_ROOT",
                "infisical_host": "INFISICAL_HOST",
                "infisical_host_env": "INFISICAL_HOST",
                "infisical_universal_auth_client_id_env": "INFISICAL_UNIVERSAL_AUTH_CLIENT_ID",
                "infisical_universal_auth_client_secret_env": "INFISICAL_UNIVERSAL_AUTH_CLIENT_SECRET",
                "infisical_project_id_env": "INFISICAL_PROJECT_ID",
                "infisical_environment_env": "INFISICAL_ENVIRONMENT",
                "infisical_credential_root_path": "INFISICAL_CREDENTIAL_ROOT_PATH",
                "infisical_path_layout": "INFISICAL_PATH_LAYOUT",
                "infisical_cache_ttl_seconds": "INFISICAL_CACHE_TTL_SECONDS",
            },
        )


def load_workspace_runtime_environment(workspace_dir: Path) -> None:
    load_workspace_env_defaults(workspace_dir)
    load_workspace_secret_source_defaults(workspace_dir)
    _run_sync(hydrate_workspace_runtime_environment_async(workspace_dir))


def _run_sync(coro):
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


def _load_workspace_secrets_payload(workspace_dir: Path) -> dict[str, Any] | None:
    path = workspace_dir / ".agents" / "secrets.yaml"
    if not path.is_file():
        return None
    try:
        payload = yaml.safe_load(path.read_text(encoding="utf-8"))
    except Exception as exc:  # noqa: BLE001
        raise RuntimeError(f"invalid workspace secrets config: {path}: {exc}") from exc
    if payload is None:
        return None
    if not isinstance(payload, dict):
        raise RuntimeError(f"workspace secrets config must be an object: {path}")
    return payload


async def _hydrate_runtime_env_from_credential_vault(workspace_dir: Path, payload: dict[str, Any]) -> None:
    entries = payload.get("runtime_env")
    if entries is None:
        return
    if not isinstance(entries, list):
        raise RuntimeError("workspace secrets runtime_env must be a list")

    resolver_config = _credential_runtime_config_from_payload(workspace_dir, payload)
    resolver = build_credential_resolver_from_config(resolver_config, fallback_to_memory=False)
    if resolver is None:
        raise RuntimeError("workspace runtime_env requires a credential_vault backend")

    for raw_entry in entries:
        if not isinstance(raw_entry, dict):
            raise RuntimeError("workspace secrets runtime_env entries must be objects")
        target_name = str(raw_entry.get("name") or "").strip()
        if not target_name:
            raise RuntimeError("workspace secrets runtime_env entry missing name")
        if target_name in os.environ and not bool(raw_entry.get("overwrite", False)):
            continue

        credential_id = str(raw_entry.get("credential_id") or "").strip()
        if not credential_id:
            raise RuntimeError(f"workspace runtime_env {target_name} missing credential_id")
        kind = str(raw_entry.get("kind") or "api_key").strip()
        agent_id = str(raw_entry.get("agent_id") or "").strip()
        scope_context = {"agent_id": agent_id} if agent_id else None
        value = await resolver.resolve(AuthRef(kind=kind, ref=credential_id), scope_context=scope_context)
        if not isinstance(value, str) or not value:
            raise RuntimeError(f"workspace runtime_env credential not found: {target_name}")
        os.environ[target_name] = value


def _credential_runtime_config_from_payload(workspace_dir: Path, payload: dict[str, Any]) -> CredentialRuntimeConfig:
    raw = payload.get("credential_vault")
    obj = raw if isinstance(raw, dict) else {}
    return CredentialRuntimeConfig(
        backend=str(obj.get("backend") or "none"),
        file_root=str(obj.get("file_root") or ".agents/credentials"),
        workspace_dir=workspace_dir,
        infisical_host=_config_value(obj, "infisical_host", "infisical_host_env") or "https://app.infisical.com",
        infisical_universal_auth_client_id=_config_value(obj, "infisical_universal_auth_client_id", "infisical_universal_auth_client_id_env"),
        infisical_universal_auth_client_secret=_config_value(
            obj,
            "infisical_universal_auth_client_secret",
            "infisical_universal_auth_client_secret_env",
        ),
        infisical_project_id=_config_value(obj, "infisical_project_id", "infisical_project_id_env"),
        infisical_environment=_config_value(obj, "infisical_environment", "infisical_environment_env"),
        infisical_cache_ttl_seconds=int(obj.get("infisical_cache_ttl_seconds") or 60),
        infisical_credential_root_path=str(obj.get("infisical_credential_root_path") or "/anyagent/credentials"),
        infisical_path_layout=str(obj.get("infisical_path_layout") or "scoped"),
    )


def _config_value(payload: dict[str, Any], value_key: str, env_key: str) -> str | None:
    raw_env_name = payload.get(env_key)
    if raw_env_name is not None:
        value = os.getenv(str(raw_env_name).strip(), "").strip()
        return value or None
    raw_value = payload.get(value_key)
    if raw_value is None:
        return None
    value = str(raw_value).strip()
    return value or None


def _apply_secret_source_env_defaults(payload: dict[str, Any], *, mapping: dict[str, str]) -> None:
    for key, env_name in mapping.items():
        raw = payload.get(key)
        if raw is None:
            continue
        if key.endswith("_env"):
            value = os.getenv(str(raw).strip(), "")
        else:
            value = str(raw).strip()
        if value and env_name not in os.environ:
            os.environ[env_name] = value
