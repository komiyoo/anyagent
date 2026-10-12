from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Mapping

from anyagent.config.agents import DEFAULT_CREDENTIAL_FILE_ROOT
from anyagent.config.loader import EffectiveConfig
from anyagent.mcp.auth import CredentialResolver

from .credential_backends import (
    CredentialStore,
    DatabaseBackend,
    DatabaseBackendConfig,
    EnvBackend,
    FileBackend,
    InfisicalBackend,
    InfisicalBackendConfig,
    VaultBackend,
    VaultBackendConfig,
)
from .credential_store import InMemoryCredentialStore
from .mcp_credentials import build_mcp_credential_resolver


@dataclass(frozen=True, slots=True)
class CredentialRuntimeConfig:
    backend: str = "none"
    file_root: str = DEFAULT_CREDENTIAL_FILE_ROOT
    workspace_dir: str | Path | None = None
    infisical_host: str = "https://app.infisical.com"
    infisical_universal_auth_client_id: str | None = None
    infisical_universal_auth_client_secret: str | None = None
    infisical_project_id: str | None = None
    infisical_environment: str | None = None
    infisical_cache_ttl_seconds: int = 60
    infisical_credential_root_path: str = "/anyagent/credentials"
    infisical_path_layout: str = "scoped"
    infisical_token: str | None = None
    credential_postgres_dsn: str | None = None
    credential_postgres_schema: str = "public"
    credential_encryption_key: str | None = None
    credential_db_create_schema: bool = False
    vault_addr: str | None = None
    vault_token: str | None = None
    vault_mount: str = "secret"
    vault_credential_root_path: str = "anyagent/credentials"


def build_credential_store_from_config(
    config: CredentialRuntimeConfig,
    *,
    environ: Mapping[str, str] | None = None,
) -> CredentialStore:
    backend = (config.backend or "").strip().lower()
    if backend.endswith("-write"):
        backend = backend.removesuffix("-write")
    if backend.endswith("_write"):
        backend = backend.removesuffix("_write")

    if backend in {"", "env"}:
        return EnvBackend(environ=dict(environ) if environ is not None else None)
    if backend == "file":
        return FileBackend(root=resolve_credential_file_root(config), environ=dict(environ) if environ is not None else None)
    if backend == "infisical":
        return InfisicalBackend(config=_build_infisical_backend_config(config))
    if backend == "db":
        return DatabaseBackend(config=_build_database_backend_config(config))
    if backend == "vault":
        return VaultBackend(config=_build_vault_backend_config(config))
    raise RuntimeError(f"unsupported credential store backend: {config.backend}")


def build_credential_resolver_from_config(
    config: CredentialRuntimeConfig,
    *,
    environ: Mapping[str, str] | None = None,
    fallback_to_memory: bool = True,
) -> CredentialResolver | None:
    backend = (config.backend or "").strip().lower()
    if backend in {
        "env-write",
        "env_write",
        "file-write",
        "file_write",
        "infisical-write",
        "infisical_write",
        "db-write",
        "db_write",
        "vault-write",
        "vault_write",
    }:
        return build_credential_store_from_config(config, environ=environ)

    resolver = build_mcp_credential_resolver(
        backend=backend,
        file_root=str(resolve_credential_file_root(config)),
        environ=dict(environ) if environ is not None else None,
        infisical_host=config.infisical_host,
        infisical_universal_auth_client_id=config.infisical_universal_auth_client_id,
        infisical_universal_auth_client_secret=config.infisical_universal_auth_client_secret,
        infisical_project_id=config.infisical_project_id,
        infisical_environment=config.infisical_environment,
        infisical_cache_ttl_seconds=config.infisical_cache_ttl_seconds,
        infisical_credential_root_path=config.infisical_credential_root_path,
        infisical_path_layout=config.infisical_path_layout,
        infisical_token=config.infisical_token,
    )
    if resolver is not None:
        return resolver
    return InMemoryCredentialStore() if fallback_to_memory else None


def resolve_credential_file_root(config: CredentialRuntimeConfig) -> Path:
    file_root = Path(str(config.file_root or DEFAULT_CREDENTIAL_FILE_ROOT)).expanduser()
    if file_root.is_absolute():
        return file_root
    if config.workspace_dir is None:
        return file_root.resolve()
    return Path(config.workspace_dir).expanduser().resolve() / file_root


def _build_infisical_backend_config(config: CredentialRuntimeConfig) -> InfisicalBackendConfig:
    token = config.infisical_token
    client_id = config.infisical_universal_auth_client_id
    client_secret = config.infisical_universal_auth_client_secret
    project_id = config.infisical_project_id
    environment = config.infisical_environment
    if token:
        # Service Token authentication — client_id/client_secret are optional.
        client_id = client_id or ""
        client_secret = client_secret or ""
    else:
        if not client_id or not client_secret:
            raise RuntimeError("infisical backend requires INFISICAL_UNIVERSAL_AUTH_CLIENT_ID and INFISICAL_UNIVERSAL_AUTH_CLIENT_SECRET")
    if not project_id or not environment:
        raise RuntimeError("infisical backend requires INFISICAL_PROJECT_ID and INFISICAL_ENVIRONMENT")
    return InfisicalBackendConfig(
        host=(config.infisical_host or "https://app.infisical.com").strip() or "https://app.infisical.com",
        client_id=client_id,
        client_secret=client_secret,
        project_id=project_id,
        environment=environment,
        credential_root_path=config.infisical_credential_root_path,
        path_layout=config.infisical_path_layout,
        cache_ttl_seconds=int(config.infisical_cache_ttl_seconds),
        token=token,
    )


def _build_database_backend_config(config: CredentialRuntimeConfig) -> DatabaseBackendConfig:
    postgres_dsn = config.credential_postgres_dsn
    schema_name = config.credential_postgres_schema or "public"
    if postgres_dsn is None:
        try:
            from anyagent.storage.settings import active_storage_settings

            settings = active_storage_settings()
            postgres_dsn = str(settings.effective_postgres_dsn) if settings.effective_postgres_dsn is not None else None
            if schema_name == "public":
                schema_name = settings.postgres_schema
        except Exception:
            postgres_dsn = None
    if not postgres_dsn:
        raise RuntimeError("db credential backend requires CREDENTIAL_POSTGRES_DSN or POSTGRES_DSN")
    if not config.credential_encryption_key:
        raise RuntimeError("db credential backend requires CREDENTIAL_ENCRYPTION_KEY")
    return DatabaseBackendConfig(
        postgres_dsn=postgres_dsn,
        encryption_key=config.credential_encryption_key,
        schema_name=schema_name,
        create_schema=bool(config.credential_db_create_schema),
    )


def credential_runtime_config_from_effective(config: EffectiveConfig) -> CredentialRuntimeConfig:
    """Map the credentials section onto the runtime backend config."""

    credentials = config.credentials
    return CredentialRuntimeConfig(
        backend=credentials.backend,
        file_root=credentials.file.root or DEFAULT_CREDENTIAL_FILE_ROOT,
        workspace_dir=config.workspace_dir,
        infisical_host=credentials.infisical.host,
        infisical_universal_auth_client_id=credentials.infisical.client_id,
        infisical_universal_auth_client_secret=credentials.infisical.client_secret,
        infisical_project_id=credentials.infisical.project_id,
        infisical_environment=credentials.infisical.environment,
        infisical_cache_ttl_seconds=credentials.infisical.cache_ttl_seconds,
        infisical_credential_root_path=credentials.infisical.credential_root_path,
        infisical_path_layout=credentials.infisical.path_layout,
        infisical_token=credentials.infisical.token,
        credential_postgres_dsn=credentials.db.dsn,
        credential_postgres_schema=credentials.db.schema_name,
        credential_encryption_key=credentials.db.encryption_key,
        credential_db_create_schema=credentials.db.create_schema,
        vault_addr=credentials.vault.addr,
        vault_token=credentials.vault.token,
        vault_mount=credentials.vault.mount,
        vault_credential_root_path=credentials.vault.credential_root_path,
    )


def build_runtime_env_reader(config: EffectiveConfig) -> CredentialResolver | None:
    """Resolver used to project runtime_env entries. Database and vault use the store."""

    runtime = credential_runtime_config_from_effective(config)
    if config.credentials.backend in {"db", "vault"}:
        return build_credential_store_from_config(runtime)
    return build_credential_resolver_from_config(runtime, fallback_to_memory=False)


def open_server_credential_stores(config: EffectiveConfig) -> tuple[CredentialStore, CredentialResolver]:
    """Return the admin store and the MCP reader.

    ``credentials.writable`` selects one store for both. Otherwise admin writes
    stay in memory and the configured backend is read-only.
    """

    runtime = credential_runtime_config_from_effective(config)
    backend = config.credentials.backend
    if backend == "none":
        memory = InMemoryCredentialStore()
        return memory, memory
    if backend in {"db", "vault"} or config.credentials.writable:
        store = build_credential_store_from_config(runtime)
        if config.credentials.writable:
            return store, store
        return InMemoryCredentialStore(), store
    resolver = build_mcp_credential_resolver(
        backend=backend,
        file_root=str(resolve_credential_file_root(runtime)),
        infisical_host=runtime.infisical_host,
        infisical_universal_auth_client_id=runtime.infisical_universal_auth_client_id,
        infisical_universal_auth_client_secret=runtime.infisical_universal_auth_client_secret,
        infisical_project_id=runtime.infisical_project_id,
        infisical_environment=runtime.infisical_environment,
        infisical_cache_ttl_seconds=runtime.infisical_cache_ttl_seconds,
        infisical_credential_root_path=runtime.infisical_credential_root_path,
        infisical_path_layout=runtime.infisical_path_layout,
        infisical_token=runtime.infisical_token,
    )
    if resolver is None:
        memory = InMemoryCredentialStore()
        return memory, memory
    return InMemoryCredentialStore(), resolver


def _build_vault_backend_config(config: CredentialRuntimeConfig) -> VaultBackendConfig:
    if not config.vault_addr or not config.vault_token:
        raise RuntimeError("vault credential backend requires VAULT_ADDR and VAULT_TOKEN")
    return VaultBackendConfig(
        base_url=config.vault_addr,
        token=config.vault_token,
        mount=config.vault_mount,
        root_path=config.vault_credential_root_path,
    )
