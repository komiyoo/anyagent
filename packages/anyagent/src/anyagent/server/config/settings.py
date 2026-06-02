from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

from anyagent.agent_packs import DEFAULT_CREDENTIAL_FILE_ROOT
from anyagent.storage.settings import StorageSettings


StorageProfile = Literal["inmemory", "postgres", "postgres-redis", "redis"]
StorageBackend = Literal["inmemory", "external", "redis", "postgres", "postgres-redis"]
SessionLockBackend = Literal["inmemory", "external", "redis"]


@dataclass(slots=True, frozen=True)
class ResolvedServerStorageSettings:
    storage_mode: Literal["none", "external"]
    storage_profile: StorageProfile
    event_store_backend: StorageBackend
    run_store_backend: StorageBackend
    session_store_backend: StorageBackend
    session_lock_backend: SessionLockBackend
    session_lease_ttl_s: float
    postgres_configured: bool
    redis_configured: bool
    single_instance_only: bool
    warnings: tuple[str, ...] = ()


class ServerSettings(BaseSettings):
    model_config = SettingsConfigDict(env_file=None, extra="ignore")

    storage_mode: Literal["none", "local", "external"] = Field(
        default="none",
        alias="STORAGE_MODE",
    )
    storage_profile: StorageProfile | None = Field(
        default=None,
        alias="STORAGE_PROFILE",
    )
    event_store_backend: StorageBackend | None = Field(
        default=None,
        alias="EVENT_STORE_BACKEND",
    )
    run_store_backend: StorageBackend | None = Field(
        default=None,
        alias="RUN_STORE_BACKEND",
    )
    session_store_backend: StorageBackend | None = Field(
        default=None,
        alias="SESSION_STORE_BACKEND",
    )
    session_lock_backend: SessionLockBackend | None = Field(
        default=None,
        alias="SESSION_LOCK_BACKEND",
    )
    session_lease_ttl_s: float = Field(
        default=30.0,
        alias="SESSION_LEASE_TTL_S",
    )
    mcp_credential_store_backend: str = Field(
        default="none",
        alias="MCP_CREDENTIAL_STORE_BACKEND",
    )
    mcp_credential_store_file_root: str = Field(
        default=DEFAULT_CREDENTIAL_FILE_ROOT,
        alias="MCP_CREDENTIAL_STORE_FILE_ROOT",
    )
    infisical_host: str = Field(default="https://app.infisical.com", alias="INFISICAL_HOST")
    infisical_universal_auth_client_id: str | None = Field(default=None, alias="INFISICAL_UNIVERSAL_AUTH_CLIENT_ID")
    infisical_universal_auth_client_secret: str | None = Field(default=None, alias="INFISICAL_UNIVERSAL_AUTH_CLIENT_SECRET")
    infisical_token: str | None = Field(default=None, alias="INFISICAL_TOKEN")
    infisical_project_id: str | None = Field(default=None, alias="INFISICAL_PROJECT_ID")
    infisical_environment: str | None = Field(default=None, alias="INFISICAL_ENVIRONMENT")
    infisical_cache_ttl_seconds: int = Field(default=60, alias="INFISICAL_CACHE_TTL_SECONDS")
    infisical_credential_root_path: str = Field(default="/anyagent/credentials", alias="INFISICAL_CREDENTIAL_ROOT_PATH")
    infisical_path_layout: str = Field(default="scoped", alias="INFISICAL_PATH_LAYOUT")
    credential_postgres_dsn: str | None = Field(default=None, alias="CREDENTIAL_POSTGRES_DSN")
    credential_postgres_schema: str = Field(default="public", alias="CREDENTIAL_POSTGRES_SCHEMA")
    credential_encryption_key: str | None = Field(default=None, alias="CREDENTIAL_ENCRYPTION_KEY")
    credential_db_create_schema: bool = Field(default=False, alias="CREDENTIAL_DB_CREATE_SCHEMA")
    vault_addr: str | None = Field(default=None, alias="VAULT_ADDR")
    vault_token: str | None = Field(default=None, alias="VAULT_TOKEN")
    vault_mount: str = Field(default="secret", alias="VAULT_MOUNT")
    vault_credential_root_path: str = Field(default="anyagent/credentials", alias="VAULT_CREDENTIAL_ROOT_PATH")

    def resolve(
        self,
        *,
        storage_mode: Literal["none", "local", "external"] | None = None,
        storage_profile: StorageProfile | None = None,
        event_store_backend: StorageBackend | None = None,
        run_store_backend: StorageBackend | None = None,
        session_store_backend: StorageBackend | None = None,
        session_lock_backend: SessionLockBackend | None = None,
        session_lease_ttl_s: float | None = None,
    ) -> ResolvedServerStorageSettings:
        storage_settings = StorageSettings()
        postgres_configured = storage_settings.effective_postgres_dsn is not None
        redis_configured = storage_settings.redis_dsn is not None
        effective_profile = storage_profile or self.storage_profile
        warnings: list[str] = []

        if effective_profile is None:
            effective_storage_mode = storage_mode or self.storage_mode
            if effective_storage_mode in {"none", "local"}:
                effective_profile = "inmemory"
            elif postgres_configured and redis_configured:
                effective_profile = "postgres-redis"
            elif postgres_configured:
                effective_profile = "postgres"
                warnings.append("postgres-only storage uses an in-memory session lock; run a single server instance or configure REDIS_DSN")
            elif redis_configured:
                effective_profile = "redis"
            else:
                raise RuntimeError("STORAGE_MODE=external requires POSTGRES_DSN/DATABASE_URL or REDIS_DSN")
        else:
            effective_storage_mode = "none" if effective_profile == "inmemory" else "external"

        if effective_profile in {"postgres", "postgres-redis"} and not postgres_configured:
            raise RuntimeError(f"storage profile {effective_profile} requires POSTGRES_DSN or DATABASE_URL")
        if effective_profile in {"postgres-redis", "redis"} and not redis_configured:
            raise RuntimeError(f"storage profile {effective_profile} requires REDIS_DSN")

        default_store_backend: StorageBackend
        if effective_profile == "inmemory":
            default_store_backend = "inmemory"
        else:
            default_store_backend = effective_profile

        default_lock_backend: SessionLockBackend = "redis" if effective_profile in {"postgres-redis", "redis"} else "inmemory"
        effective_lock_backend = session_lock_backend or self.session_lock_backend or default_lock_backend
        if effective_lock_backend == "redis" and not redis_configured:
            raise RuntimeError("SESSION_LOCK_BACKEND=redis requires REDIS_DSN")

        effective_event_backend = event_store_backend or self.event_store_backend or default_store_backend
        effective_run_backend = run_store_backend or self.run_store_backend or default_store_backend
        effective_session_backend = session_store_backend or self.session_store_backend or default_store_backend

        effective_storage_mode = "none" if all(
            backend == "inmemory" for backend in (effective_event_backend, effective_run_backend, effective_session_backend)
        ) else "external"
        single_instance_only = effective_storage_mode == "external" and effective_lock_backend == "inmemory"
        return ResolvedServerStorageSettings(
            storage_mode=effective_storage_mode,
            storage_profile=effective_profile,
            event_store_backend=effective_event_backend,
            run_store_backend=effective_run_backend,
            session_store_backend=effective_session_backend,
            session_lock_backend=effective_lock_backend,
            session_lease_ttl_s=float(
                session_lease_ttl_s if isinstance(session_lease_ttl_s, (int, float)) else self.session_lease_ttl_s
            ),
            postgres_configured=postgres_configured,
            redis_configured=redis_configured,
            single_instance_only=single_instance_only,
            warnings=tuple(warnings),
        )
