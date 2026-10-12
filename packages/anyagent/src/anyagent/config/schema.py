"""Pydantic models for `.anyagent/anyagent.yaml`.

Workspace-level models use ``extra="forbid"`` so a typo fails with a
path-qualified error. There are no ``*_env`` fields: secret values are
already interpolated strings.
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, SecretStr, field_validator

from anyagent.config.models_kinds import ModelProviderKind


StorageProfile = Literal["inmemory", "postgres", "postgres-redis", "redis"]
StorageMode = Literal["auto", "none", "local", "external"]
StorageBackendName = Literal["inmemory", "external", "redis", "postgres", "postgres-redis"]
SessionLockBackendName = Literal["inmemory", "external", "redis"]
CredentialBackendName = Literal["none", "env", "file", "db", "vault", "infisical"]
SqlDialect = Literal["auto", "postgresql", "mysql"]
SchemaPolicy = Literal["migrate", "runtime_create"]
SandboxBackendName = Literal["auto", "local_reference", "opensandbox"]
WorkspaceMetadataBackend = Literal["auto", "disabled", "local_file", "postgres"]
WorkspaceLeaseBackend = Literal["auto", "none", "memory", "redis"]
WorkspaceSnapshotBackend = Literal["auto", "disabled", "local_file", "s3"]
AlertWebhookFormat = Literal["json", "feishu"]


class _Forbid(BaseModel):
    model_config = ConfigDict(extra="forbid")


def plain_secret(value: str | SecretStr | None) -> str | None:
    """Return a stripped secret, or None when the value is missing or blank."""

    if value is None:
        return None
    raw = value.get_secret_value() if isinstance(value, SecretStr) else value
    text = raw.strip()
    return text or None


class ProviderConfig(_Forbid):
    kind: ModelProviderKind = "openai"
    api_key: str | None = None
    base_url: str | None = None
    anthropic_version: str | None = None


class ModelAliasConfig(_Forbid):
    provider: str
    model: str
    params: dict[str, Any] = Field(default_factory=dict)
    extra_params: dict[str, Any] = Field(default_factory=dict)


class ModelsConfig(_Forbid):
    default: str | None = None
    providers: dict[str, ProviderConfig] = Field(default_factory=dict)
    aliases: dict[str, ModelAliasConfig] = Field(default_factory=dict)


class ServerConfig(_Forbid):
    host: str = "127.0.0.1"
    port: int = 8787
    api_key: str | None = None
    admin_api_key: str | None = None
    agent_api_key: str | None = None
    cors_origins: list[str] = Field(default_factory=list)
    studio_dir: str | None = None
    sandbox_root: str | None = None
    enable_studio: bool = True


class StorageConfig(_Forbid):
    profile: StorageProfile | None = None
    mode: StorageMode | None = None
    event_store_backend: StorageBackendName | None = None
    run_store_backend: StorageBackendName | None = None
    session_store_backend: StorageBackendName | None = None
    session_lock_backend: SessionLockBackendName | None = None
    session_lease_ttl_s: float = 30.0
    postgres_dsn: str | None = None
    postgres_schema: str = "public"
    postgres_schema_policy: SchemaPolicy = "migrate"
    redis_dsn: str | None = None
    mysql_dsn: str | None = None
    sql_backend_dialect: SqlDialect = "auto"
    redis_namespace: str = "anyagent"
    event_store_retention_s: int = 2 * 60 * 60
    replay_event_store_retention_s: int = 60 * 60
    run_store_retention_s: int = 2 * 60 * 60
    session_store_retention_s: int = 24 * 60 * 60
    rollout_root_dir: str | None = None
    rollout_rotate_max_bytes: int = 0
    rollout_rotate_max_age_seconds: int = 0
    rollout_rotate_keep_files: int = 16


class CredentialsFileConfig(_Forbid):
    root: str = ".anyagent/credentials"


class CredentialsDbConfig(_Forbid):
    model_config = ConfigDict(extra="forbid", populate_by_name=True, hide_input_in_errors=True)

    dsn: SecretStr | None = None
    schema_name: str = Field(default="public", alias="schema")
    encryption_key: SecretStr | None = None
    create_schema: bool = False


class CredentialsVaultConfig(_Forbid):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)

    addr: str | None = None
    token: SecretStr | None = None
    mount: str = "secret"
    credential_root_path: str = "anyagent/credentials"


class CredentialsInfisicalConfig(_Forbid):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)

    host: str = "https://app.infisical.com"
    client_id: str | None = None
    client_secret: SecretStr | None = None
    token: SecretStr | None = None
    project_id: str | None = None
    environment: str | None = None
    cache_ttl_seconds: int = 60
    credential_root_path: str = "/anyagent/credentials"
    path_layout: str = "scoped"


class RuntimeEnvEntry(_Forbid):
    name: str
    credential_id: str
    kind: str = "api_key"
    agent_id: str | None = None
    overwrite: bool = False


class CredentialsConfig(_Forbid):
    backend: CredentialBackendName = "none"
    writable: bool = False
    file: CredentialsFileConfig = Field(default_factory=CredentialsFileConfig)
    db: CredentialsDbConfig = Field(default_factory=CredentialsDbConfig)
    vault: CredentialsVaultConfig = Field(default_factory=CredentialsVaultConfig)
    infisical: CredentialsInfisicalConfig = Field(default_factory=CredentialsInfisicalConfig)
    runtime_env: list[RuntimeEnvEntry] = Field(default_factory=list)

    @field_validator("backend", mode="before")
    @classmethod
    def _reject_write_suffix(cls, value: object) -> object:
        if isinstance(value, str):
            raw = value.strip().lower()
            if raw.endswith("-write") or raw.endswith("_write"):
                raise ValueError(
                    f"credential backend {value!r} is not a backend name; "
                    "drop the -write suffix and set credentials.writable: true"
                )
        return value


class OpenSandboxConfig(_Forbid):
    base_url: str | None = None
    api_key: str | None = None
    image: str = "ubuntu:24.04"
    timeout_s: int = 3600
    cpu_limit: str = "1000m"
    memory_limit: str = "1Gi"
    proxy_port: int = 44772


class SandboxConfig(_Forbid):
    mode: str | None = None
    allow: bool = False
    backend: SandboxBackendName = "auto"
    isolation_mode: str = "disabled"
    workspace_root: str = "/workspace"
    filesystem_persistence_mode: str = "ephemeral"
    hot_idle_ttl_s: int = 900
    cold_retention_s: int = 7 * 24 * 3600
    max_snapshot_bytes: int = 5 * 1024 * 1024 * 1024
    opensandbox: OpenSandboxConfig = Field(default_factory=OpenSandboxConfig)
    metadata_backend: WorkspaceMetadataBackend = "auto"
    metadata_root_dir: str | None = None
    lease_backend: WorkspaceLeaseBackend = "auto"
    lease_namespace: str = "anyagent-tool-runtime"
    lease_ttl_ms: int = 60_000
    lease_wait_timeout_ms: int = 2_000
    snapshot_backend: WorkspaceSnapshotBackend = "auto"
    snapshot_root_dir: str | None = None
    snapshot_s3_endpoint: str | None = None
    snapshot_s3_access_key: str | None = None
    snapshot_s3_secret_key: str | None = None
    snapshot_s3_bucket: str = "anyagent-workspaces"
    snapshot_s3_secure: bool = False
    snapshot_s3_region: str | None = None


class ChatwootPluginConfig(_Forbid):
    """Chatwoot connector settings. Defaults interpolate ``CHATWOOT_*``."""

    url: str = "https://app.chatwoot.com"
    account_id: str = "1"
    access_token: str | None = None
    webhook_secret: str | None = None
    credential_kind: str = "secret"
    credential_id: str | None = None
    async_processing: bool = True
    status_changes: bool = True
    skip_when_assigned_to_human: bool = True
    typing_indicator: bool = False
    reply_pacing_min_s: float | None = None
    reply_pacing_max_s: float | None = None

    @field_validator("account_id", mode="before")
    @classmethod
    def _account_id_text(cls, value: object) -> object:
        if value is None:
            return "1"
        return str(value)


class PluginsConfig(_Forbid):
    roots: list[str] = Field(default_factory=list)
    builtin: list[str] = Field(default_factory=list)
    fail_open: bool = False
    chatwoot: ChatwootPluginConfig = Field(default_factory=ChatwootPluginConfig)


class ObservabilityConfig(_Forbid):
    log_format: str = "text"
    log_level: str = "INFO"
    http_url: str | None = None
    http_headers: str | None = None
    replay_stdout: str | None = None
    replay_file: str | None = None


class AlertsConfig(_Forbid):
    webhook_url: str | None = None
    webhook_format: AlertWebhookFormat = "json"
    webhook_headers: str | None = None


class ToolRuntimeConfig(_Forbid):
    base_url: str | None = None
    internal_key: str | None = None
    host: str = "127.0.0.1"
    port: int = 8788
    manifest_cache_ttl_seconds: float = 5.0
    plugin_roots: list[str] = Field(default_factory=list)
    plugins_fail_open: bool = False
    sandbox_root_dir: str = "/tmp/anyagent-tool-runtime-sandboxes"
    workspace_event_backend: str = "memory"
    workspace_event_root_dir: str | None = None
    workspace_event_max_buffer: int = 512


class WorkspaceConfig(_Forbid):
    """Effective `.anyagent/anyagent.yaml` document."""

    models: ModelsConfig = Field(default_factory=ModelsConfig)
    server: ServerConfig = Field(default_factory=ServerConfig)
    storage: StorageConfig = Field(default_factory=StorageConfig)
    credentials: CredentialsConfig = Field(default_factory=CredentialsConfig)
    sandbox: SandboxConfig = Field(default_factory=SandboxConfig)
    plugins: PluginsConfig = Field(default_factory=PluginsConfig)
    observability: ObservabilityConfig = Field(default_factory=ObservabilityConfig)
    alerts: AlertsConfig = Field(default_factory=AlertsConfig)
    tool_runtime: ToolRuntimeConfig = Field(default_factory=ToolRuntimeConfig)
