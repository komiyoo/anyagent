"""Build one credential store from ``CredentialsConfig``.

``credentials.writable`` is the only writability switch. Backend names never
carry a ``-write`` suffix.
"""

from __future__ import annotations

import asyncio
import threading
from pathlib import Path
from typing import Any, Mapping

from anyagent.config.agents import DEFAULT_CREDENTIAL_FILE_ROOT
from anyagent.config.schema import CredentialsConfig, plain_secret

from .credential_backends import (
    CredentialStore,
    DatabaseBackend,
    DatabaseBackendConfig,
    EnvBackend,
    FileBackend,
    InfisicalBackend,
    InfisicalBackendConfig,
    ReadOnlyCredentialStore,
    VaultBackend,
    VaultBackendConfig,
)
from .credential_store import InMemoryCredentialStore


def build_credential_store(
    config: CredentialsConfig,
    *,
    workspace_dir: str | Path | None = None,
    environ: Mapping[str, str] | None = None,
) -> CredentialStore | None:
    """Build the configured store.

    ``backend="none"`` returns None. ``environ`` is forwarded only to
    ``EnvBackend``, which reads secret values from it. Every other backend
    receives fields from ``config`` alone. A store with ``writable`` false is
    wrapped so set and delete fail.
    """

    backend = (config.backend or "none").strip().lower()
    if backend in {"", "none"}:
        return None
    store = _build_backend(config, backend, workspace_dir=workspace_dir, environ=environ)
    if not config.writable:
        return ReadOnlyCredentialStore(store, backend=backend)
    return store


def open_process_credential_store(
    config: CredentialsConfig,
    *,
    workspace_dir: str | Path | None = None,
    environ: Mapping[str, str] | None = None,
) -> CredentialStore:
    """Process credential store. ``none`` falls back to an in-memory store."""

    return build_credential_store(config, workspace_dir=workspace_dir, environ=environ) or InMemoryCredentialStore()


def resolve_credential_file_root(
    file_root: str | None = None,
    *,
    workspace_dir: str | Path | None = None,
) -> Path:
    """Resolve a credential file root against the workspace when it is relative."""

    root = Path(str(file_root or DEFAULT_CREDENTIAL_FILE_ROOT)).expanduser()
    if root.is_absolute():
        return root
    if workspace_dir is None:
        return root.resolve()
    return Path(workspace_dir).expanduser().resolve() / root


def run_credential_coro(coro: Any) -> Any:
    """Run a credential coroutine from sync code, including inside a live loop."""

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


def _build_backend(
    config: CredentialsConfig,
    backend: str,
    *,
    workspace_dir: str | Path | None,
    environ: Mapping[str, str] | None,
) -> CredentialStore:
    if backend == "env":
        copied = dict(environ) if environ is not None else None
        return EnvBackend(environ=copied)
    if backend == "file":
        return FileBackend(root=resolve_credential_file_root(config.file.root, workspace_dir=workspace_dir))
    if backend == "infisical":
        return InfisicalBackend(config=_infisical_config(config))
    if backend == "db":
        return DatabaseBackend(config=_database_config(config))
    if backend == "vault":
        return VaultBackend(config=_vault_config(config))
    raise RuntimeError(f"unsupported credential store backend: {backend}")


def _infisical_config(config: CredentialsConfig) -> InfisicalBackendConfig:
    infisical = config.infisical
    token = plain_secret(infisical.token)
    client_id = (infisical.client_id or "").strip()
    client_secret = plain_secret(infisical.client_secret) or ""
    project_id = (infisical.project_id or "").strip()
    environment = (infisical.environment or "").strip()
    if token:
        client_id = client_id or ""
    elif not client_id or not client_secret:
        raise RuntimeError(
            "infisical backend requires INFISICAL_UNIVERSAL_AUTH_CLIENT_ID and INFISICAL_UNIVERSAL_AUTH_CLIENT_SECRET"
        )
    if not project_id or not environment:
        raise RuntimeError("infisical backend requires INFISICAL_PROJECT_ID and INFISICAL_ENVIRONMENT")
    host = (infisical.host or "https://app.infisical.com").strip() or "https://app.infisical.com"
    return InfisicalBackendConfig(
        host=host,
        client_id=client_id,
        client_secret=client_secret,
        project_id=project_id,
        environment=environment,
        credential_root_path=infisical.credential_root_path,
        path_layout=infisical.path_layout,
        cache_ttl_seconds=int(infisical.cache_ttl_seconds),
        token=token,
    )


def _database_config(config: CredentialsConfig) -> DatabaseBackendConfig:
    dsn = plain_secret(config.db.dsn)
    encryption_key = plain_secret(config.db.encryption_key)
    if not dsn:
        raise RuntimeError("db credential backend requires CREDENTIAL_POSTGRES_DSN")
    if not encryption_key:
        raise RuntimeError("db credential backend requires CREDENTIAL_ENCRYPTION_KEY")
    return DatabaseBackendConfig(
        postgres_dsn=dsn,
        encryption_key=encryption_key,
        schema_name=config.db.schema_name or "public",
        create_schema=bool(config.db.create_schema),
    )


def _vault_config(config: CredentialsConfig) -> VaultBackendConfig:
    addr = (config.vault.addr or "").strip()
    token = plain_secret(config.vault.token)
    if not addr or not token:
        raise RuntimeError("vault credential backend requires VAULT_ADDR and VAULT_TOKEN")
    return VaultBackendConfig(
        base_url=addr,
        token=token,
        mount=config.vault.mount,
        root_path=config.vault.credential_root_path,
    )
