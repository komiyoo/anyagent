from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


class StorageComponentHealth(BaseModel):
    model_config = ConfigDict(extra="allow")

    type: str
    layers: list[str] = Field(default_factory=list)


class StorageHealthConnectivity(BaseModel):
    model_config = ConfigDict(extra="allow")

    configured: bool
    reachable: bool | None = None
    schema_name: str | None = Field(default=None, alias="schema")
    namespace: str | None = None


class StorageComponentCapabilities(BaseModel):
    model_config = ConfigDict(extra="forbid")

    tier: Literal["reference", "external"]
    long_term_owner: Literal["anyagent", "anyagent-apps"]
    source_of_truth: str
    requires_services: list[str] = Field(default_factory=list)
    restart_recovery: bool
    cross_instance: bool
    supports_replay: bool | None = None
    supports_live_tail: bool | None = None
    supports_idempotency: bool | None = None
    supports_snapshot_cas: bool | None = None
    supports_keyed_serialization: bool | None = None


class StorageRetentionConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    events: int
    runs: int
    sessions: int


class StorageBackendConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    event_store: str
    run_store: str
    session_store: str
    session_lock: str


class StorageHealthResponse(BaseModel):
    model_config = ConfigDict(extra="allow")

    ok: bool
    storage_mode: str
    backends: StorageBackendConfig
    retention_s: StorageRetentionConfig
    stores: dict[str, StorageComponentHealth]
    capabilities: dict[str, StorageComponentCapabilities] = Field(default_factory=dict)
    postgres: StorageHealthConnectivity
    redis: StorageHealthConnectivity
    extra: dict[str, Any] = Field(default_factory=dict)
