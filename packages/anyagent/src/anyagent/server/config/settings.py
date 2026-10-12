from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from anyagent.config.schema import CredentialsConfig, StorageConfig
from anyagent.storage.settings import StorageSettings, active_storage_settings, storage_settings_from_config


StorageProfile = Literal["inmemory", "postgres", "postgres-redis", "redis"]
StorageBackend = Literal["inmemory", "external", "redis", "postgres", "postgres-redis"]
SessionLockBackend = Literal["inmemory", "external", "redis"]
ServerStorageMode = Literal["none", "local", "external"]


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


class ServerSettings(BaseModel):
    """Server storage and credential inputs derived from effective config.

    Field aliases stay so callers can pass ``STORAGE_MODE`` and the other
    historical names as explicit keyword arguments. The model does not read
    the process environment.
    """

    model_config = ConfigDict(extra="ignore", populate_by_name=True)

    storage_mode: ServerStorageMode = Field(default="none", alias="STORAGE_MODE")
    storage_profile: StorageProfile | None = Field(default=None, alias="STORAGE_PROFILE")
    event_store_backend: StorageBackend | None = Field(default=None, alias="EVENT_STORE_BACKEND")
    run_store_backend: StorageBackend | None = Field(default=None, alias="RUN_STORE_BACKEND")
    session_store_backend: StorageBackend | None = Field(default=None, alias="SESSION_STORE_BACKEND")
    session_lock_backend: SessionLockBackend | None = Field(default=None, alias="SESSION_LOCK_BACKEND")
    session_lease_ttl_s: float = Field(default=30.0, alias="SESSION_LEASE_TTL_S")

    def resolve(
        self,
        *,
        storage_settings: StorageSettings | None = None,
        storage_mode: ServerStorageMode | None = None,
        storage_profile: StorageProfile | None = None,
        event_store_backend: StorageBackend | None = None,
        run_store_backend: StorageBackend | None = None,
        session_store_backend: StorageBackend | None = None,
        session_lock_backend: SessionLockBackend | None = None,
        session_lease_ttl_s: float | None = None,
    ) -> ResolvedServerStorageSettings:
        resolved_storage = storage_settings or active_storage_settings()
        postgres_configured = resolved_storage.effective_postgres_dsn is not None
        redis_configured = resolved_storage.redis_dsn is not None
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
                warnings.append(
                    "postgres-only storage uses an in-memory session lock; run a single server instance or configure REDIS_DSN"
                )
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

        default_store_backend: StorageBackend = "inmemory" if effective_profile == "inmemory" else effective_profile
        default_lock_backend: SessionLockBackend = "redis" if effective_profile in {"postgres-redis", "redis"} else "inmemory"
        effective_lock_backend = session_lock_backend or self.session_lock_backend or default_lock_backend
        if effective_lock_backend == "redis" and not redis_configured:
            raise RuntimeError("SESSION_LOCK_BACKEND=redis requires REDIS_DSN")

        effective_event_backend = event_store_backend or self.event_store_backend or default_store_backend
        effective_run_backend = run_store_backend or self.run_store_backend or default_store_backend
        effective_session_backend = session_store_backend or self.session_store_backend or default_store_backend

        effective_storage_mode = (
            "none"
            if all(backend == "inmemory" for backend in (effective_event_backend, effective_run_backend, effective_session_backend))
            else "external"
        )
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


def resolve_server_storage(storage: StorageConfig) -> tuple[StorageSettings, ResolvedServerStorageSettings]:
    """Resolve storage from an explicit config section.

    This path does not read the process environment. ``ServerSettings.resolve``
    still falls back to ``active_storage_settings`` when ``storage_settings``
    is omitted, so env-only callers keep working.
    """

    settings = storage_settings_from_config(storage)
    return settings, server_settings_from_config(storage).resolve(storage_settings=settings)


def server_settings_from_config(storage: StorageConfig, _credentials: CredentialsConfig | None = None) -> ServerSettings:
    """Map config storage fields onto the server resolver.

    An unset mode, and the storage-runtime value ``auto``, keep the historical
    server default ``none``. Explicit ``none``, ``local``, and ``external``
    pass through.
    """

    mode = storage.mode
    server_mode: ServerStorageMode = "none" if mode in {None, "auto"} else mode
    return ServerSettings(
        storage_mode=server_mode,
        storage_profile=storage.profile,
        event_store_backend=storage.event_store_backend,
        run_store_backend=storage.run_store_backend,
        session_store_backend=storage.session_store_backend,
        session_lock_backend=storage.session_lock_backend,
        session_lease_ttl_s=storage.session_lease_ttl_s,
    )
