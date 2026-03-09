from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


@dataclass(slots=True, frozen=True)
class ResolvedServerStorageSettings:
    storage_mode: Literal["none", "external"]
    event_store_backend: Literal["inmemory", "external", "redis"]
    run_store_backend: Literal["inmemory", "external", "redis"]
    session_store_backend: Literal["inmemory", "external", "redis"]
    session_lock_backend: Literal["inmemory", "external", "redis"]
    session_lease_ttl_s: float


class ServerSettings(BaseSettings):
    model_config = SettingsConfigDict(env_file=None, extra="ignore")

    storage_mode: Literal["none", "external"] = Field(
        default="none",
        alias="STORAGE_MODE",
    )
    event_store_backend: Literal["inmemory", "external", "redis"] | None = Field(
        default=None,
        alias="EVENT_STORE_BACKEND",
    )
    run_store_backend: Literal["inmemory", "external", "redis"] | None = Field(
        default=None,
        alias="RUN_STORE_BACKEND",
    )
    session_store_backend: Literal["inmemory", "external", "redis"] | None = Field(
        default=None,
        alias="SESSION_STORE_BACKEND",
    )
    session_lock_backend: Literal["inmemory", "external", "redis"] | None = Field(
        default=None,
        alias="SESSION_LOCK_BACKEND",
    )
    session_lease_ttl_s: float = Field(
        default=30.0,
        alias="SESSION_LEASE_TTL_S",
    )

    def resolve(
        self,
        *,
        storage_mode: Literal["none", "external"] | None = None,
        event_store_backend: Literal["inmemory", "external", "redis"] | None = None,
        run_store_backend: Literal["inmemory", "external", "redis"] | None = None,
        session_store_backend: Literal["inmemory", "external", "redis"] | None = None,
        session_lock_backend: Literal["inmemory", "external", "redis"] | None = None,
        session_lease_ttl_s: float | None = None,
    ) -> ResolvedServerStorageSettings:
        effective_storage_mode = storage_mode or self.storage_mode
        default_store_backend: Literal["inmemory", "external"] = "inmemory" if effective_storage_mode == "none" else "external"
        default_lock_backend: Literal["inmemory", "external", "redis"] = (
            "inmemory" if effective_storage_mode == "none" else "redis"
        )
        return ResolvedServerStorageSettings(
            storage_mode=effective_storage_mode,
            event_store_backend=event_store_backend or self.event_store_backend or default_store_backend,
            run_store_backend=run_store_backend or self.run_store_backend or default_store_backend,
            session_store_backend=session_store_backend or self.session_store_backend or default_store_backend,
            session_lock_backend=session_lock_backend or self.session_lock_backend or default_lock_backend,
            session_lease_ttl_s=float(
                session_lease_ttl_s if isinstance(session_lease_ttl_s, (int, float)) else self.session_lease_ttl_s
            ),
        )
