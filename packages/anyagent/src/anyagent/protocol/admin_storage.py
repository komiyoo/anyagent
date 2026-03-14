from __future__ import annotations

from datetime import datetime
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
    supports_workspace_sessions: bool | None = None
    supports_hibernation: bool | None = None


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


class AdminSandboxWorkspaceRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    agent_id: str = Field(min_length=1)
    session_key: str = Field(min_length=1)


class AdminSandboxWorkspaceEventsRequest(AdminSandboxWorkspaceRequest):
    model_config = ConfigDict(extra="forbid")

    limit: int = Field(default=50, ge=1, le=200)


class AdminSandboxRuntimeDiagnostics(BaseModel):
    """
    控制面可见的沙箱运行时诊断信息。

    这些字段用于 admin / health / audit / tracing，不进入 agent loop，
    也不向模型暴露基础设施端口、代理地址或 provider 原始 metadata。
    """

    model_config = ConfigDict(extra="forbid")

    provider: str
    sandbox_id: str | None = None
    state: str | None = None
    reason: str | None = None
    message: str | None = None
    image_uri: str | None = None
    created_at: datetime | None = None
    expires_at: datetime | None = None
    last_transition_at: datetime | None = None


class AdminSandboxWorkspaceRef(BaseModel):
    model_config = ConfigDict(extra="forbid")

    session_partition_key: str
    workspace_id: str
    state: str
    generation: int = Field(ge=0)
    tenant_id: str | None = None
    sandbox_id: str | None = None
    workspace_root: str | None = None
    snapshot_uri: str | None = None
    snapshot_digest: str | None = None
    snapshot_bytes: int | None = Field(default=None, ge=0)
    last_accessed_at_ms: int | None = Field(default=None, ge=0)
    hot_expires_at_ms: int | None = Field(default=None, ge=0)
    cold_expires_at_ms: int | None = Field(default=None, ge=0)
    failure_code: str | None = None
    failure_message: str | None = None
    runtime_diagnostics: AdminSandboxRuntimeDiagnostics | None = None


class AdminSandboxWorkspaceListResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    workspaces: list[AdminSandboxWorkspaceRef] = Field(default_factory=list)
