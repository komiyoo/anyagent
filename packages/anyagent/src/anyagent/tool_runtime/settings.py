from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Annotated, Any, Literal

from pydantic import AnyUrl, Field, PostgresDsn, RedisDsn, UrlConstraints
from pydantic_settings import BaseSettings, SettingsConfigDict

from anyagent.agent_packs import DEFAULT_CREDENTIAL_FILE_ROOT


MySQLDsn = Annotated[AnyUrl, UrlConstraints(allowed_schemes=["mysql", "mysql+asyncmy", "mysql+aiomysql", "mysql+pymysql"])]


@dataclass(frozen=True, slots=True)
class ToolRuntimeServerConfig:
    workspace_dir: str | Path = "."
    host: str = "127.0.0.1"
    port: int = 8788
    internal_key: str | None = None
    admin_api_key: str | None = None
    sandbox_root_dir: str | Path | None = None
    plugin_roots: tuple[str | Path, ...] | None = None
    plugins_fail_open: bool = False
    workspace_event_backend: str = "memory"
    workspace_event_root_dir: str | None = None
    workspace_event_max_buffer: int = 512
    credential: Any = None
    workspace_runtime: Any = None


class ToolRuntimeSettings(BaseSettings):
    model_config = SettingsConfigDict(env_file=None, extra="ignore")

    workspace_dir: str = Field(default=".", alias="WORKSPACE_DIR")
    host: str = Field(default="127.0.0.1", alias="HOST")
    port: int = Field(default=8788, alias="PORT")

    internal_key: str | None = Field(default=None, alias="TOOL_RUNTIME_INTERNAL_KEY")
    admin_api_key: str | None = Field(default=None, alias="ADMIN_API_KEY")
    sandbox_root_dir: str = Field(default="/tmp/anyagent-tool-runtime-sandboxes", alias="SANDBOX_ROOT_DIR")

    plugin_roots: str = Field(default="", alias="TOOL_RUNTIME_PLUGIN_ROOTS")
    plugins_fail_open: bool = Field(default=False, alias="TOOL_RUNTIME_PLUGINS_FAIL_OPEN")

    allow_sandbox: bool = Field(default=False, alias="ALLOW_SANDBOX")
    sandbox_backend: Literal["auto", "local_reference", "opensandbox"] = Field(default="auto", alias="SANDBOX_BACKEND")
    sandbox_isolation_mode: str = Field(default="disabled", alias="SANDBOX_ISOLATION_MODE")
    opensandbox_base_url: str | None = Field(default=None, alias="OPENSANDBOX_BASE_URL")
    opensandbox_api_key: str | None = Field(default=None, alias="OPENSANDBOX_API_KEY")
    opensandbox_image: str = Field(default="ubuntu:24.04", alias="OPENSANDBOX_IMAGE")
    opensandbox_timeout_s: int = Field(default=3600, alias="OPENSANDBOX_TIMEOUT_S")
    opensandbox_cpu_limit: str = Field(default="1000m", alias="OPENSANDBOX_CPU_LIMIT")
    opensandbox_memory_limit: str = Field(default="1Gi", alias="OPENSANDBOX_MEMORY_LIMIT")
    opensandbox_proxy_port: int = Field(default=44772, alias="OPENSANDBOX_PROXY_PORT")
    sandbox_filesystem_persistence_mode: str = Field(default="ephemeral", alias="SANDBOX_FILESYSTEM_PERSISTENCE_MODE")
    sandbox_workspace_root: str = Field(default="/workspace", alias="SANDBOX_WORKSPACE_ROOT")
    sandbox_hot_idle_ttl_s: int = Field(default=900, alias="SANDBOX_HOT_IDLE_TTL_S")
    sandbox_cold_retention_s: int = Field(default=7 * 24 * 3600, alias="SANDBOX_COLD_RETENTION_S")
    sandbox_max_snapshot_bytes: int = Field(default=5 * 1024 * 1024 * 1024, alias="SANDBOX_MAX_SNAPSHOT_BYTES")
    workspace_metadata_backend: Literal["auto", "disabled", "local_file", "postgres"] = Field(
        default="auto",
        alias="WORKSPACE_METADATA_BACKEND",
    )
    workspace_metadata_root_dir: str | None = Field(default=None, alias="WORKSPACE_METADATA_ROOT_DIR")
    workspace_lease_backend: Literal["auto", "none", "memory", "redis"] = Field(default="auto", alias="WORKSPACE_LEASE_BACKEND")
    workspace_lease_namespace: str = Field(default="anyagent-tool-runtime", alias="WORKSPACE_LEASE_NAMESPACE")
    workspace_lease_ttl_ms: int = Field(default=60_000, alias="WORKSPACE_LEASE_TTL_MS")
    workspace_lease_wait_timeout_ms: int = Field(default=2_000, alias="WORKSPACE_LEASE_WAIT_TIMEOUT_MS")
    workspace_snapshot_backend: Literal["auto", "disabled", "local_file", "s3"] = Field(
        default="auto",
        alias="WORKSPACE_SNAPSHOT_BACKEND",
    )
    workspace_snapshot_root_dir: str | None = Field(default=None, alias="WORKSPACE_SNAPSHOT_ROOT_DIR")
    workspace_snapshot_s3_endpoint: str | None = Field(default=None, alias="WORKSPACE_SNAPSHOT_S3_ENDPOINT")
    workspace_snapshot_s3_access_key: str | None = Field(default=None, alias="WORKSPACE_SNAPSHOT_S3_ACCESS_KEY")
    workspace_snapshot_s3_secret_key: str | None = Field(default=None, alias="WORKSPACE_SNAPSHOT_S3_SECRET_KEY")
    workspace_snapshot_s3_bucket: str = Field(default="anyagent-workspaces", alias="WORKSPACE_SNAPSHOT_S3_BUCKET")
    workspace_snapshot_s3_secure: bool = Field(default=False, alias="WORKSPACE_SNAPSHOT_S3_SECURE")
    workspace_snapshot_s3_region: str | None = Field(default=None, alias="WORKSPACE_SNAPSHOT_S3_REGION")
    workspace_event_backend: str = Field(default="memory", alias="WORKSPACE_EVENT_BACKEND")
    workspace_event_root_dir: str | None = Field(default=None, alias="WORKSPACE_EVENT_ROOT_DIR")
    workspace_event_max_buffer: int = Field(default=512, alias="WORKSPACE_EVENT_MAX_BUFFER")
    postgres_dsn: PostgresDsn | None = Field(default=None, alias="POSTGRES_DSN")
    mysql_dsn: MySQLDsn | None = Field(default=None, alias="MYSQL_DSN")
    redis_dsn: RedisDsn | None = Field(default=None, alias="REDIS_DSN")
    sql_backend_dialect: Literal["auto", "postgresql", "mysql"] = Field(default="auto", alias="SQL_BACKEND_DIALECT")
    postgres_schema: str = Field(default="public", alias="POSTGRES_SCHEMA")

    credential_backend: str = Field(default="none", alias="MCP_CREDENTIAL_STORE_BACKEND")
    credential_file_root: str = Field(default=DEFAULT_CREDENTIAL_FILE_ROOT, alias="MCP_CREDENTIAL_STORE_FILE_ROOT")
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


def build_tool_runtime_server_config(
    settings: ToolRuntimeSettings | None = None,
    *,
    workspace_dir: str | Path | None = None,
    host: str | None = None,
    port: int | None = None,
    internal_key: str | None = None,
    admin_api_key: str | None = None,
    sandbox_root_dir: str | Path | None = None,
    plugin_roots: list[str | Path] | tuple[str | Path, ...] | None = None,
    plugins_fail_open: bool | None = None,
) -> ToolRuntimeServerConfig:
    src = settings or ToolRuntimeSettings()
    from anyagent.server.security.credential_runtime import CredentialRuntimeConfig
    from anyagent.server.sandbox.workspace_runtime import WorkspaceRuntimeConfig

    resolved_workspace_dir = workspace_dir if workspace_dir is not None else src.workspace_dir
    resolved_sandbox_root_dir = str(sandbox_root_dir if sandbox_root_dir is not None else src.sandbox_root_dir)
    return ToolRuntimeServerConfig(
        workspace_dir=resolved_workspace_dir,
        host=host if host is not None else src.host,
        port=int(port if port is not None else src.port),
        internal_key=_non_empty(internal_key) if internal_key is not None else _non_empty(src.internal_key),
        admin_api_key=_non_empty(admin_api_key) if admin_api_key is not None else _non_empty(src.admin_api_key),
        sandbox_root_dir=resolved_sandbox_root_dir,
        plugin_roots=tuple(plugin_roots) if plugin_roots is not None else _parse_plugin_roots(src.plugin_roots),
        plugins_fail_open=bool(plugins_fail_open) if plugins_fail_open is not None else bool(src.plugins_fail_open),
        workspace_event_backend=src.workspace_event_backend,
        workspace_event_root_dir=src.workspace_event_root_dir,
        workspace_event_max_buffer=int(src.workspace_event_max_buffer),
        credential=CredentialRuntimeConfig(
            backend=src.credential_backend,
            file_root=src.credential_file_root,
            workspace_dir=resolved_workspace_dir,
            infisical_host=src.infisical_host,
            infisical_universal_auth_client_id=src.infisical_universal_auth_client_id,
            infisical_universal_auth_client_secret=src.infisical_universal_auth_client_secret,
            infisical_token=src.infisical_token,
            infisical_project_id=src.infisical_project_id,
            infisical_environment=src.infisical_environment,
            infisical_cache_ttl_seconds=src.infisical_cache_ttl_seconds,
            infisical_credential_root_path=src.infisical_credential_root_path,
            infisical_path_layout=src.infisical_path_layout,
            credential_postgres_dsn=src.credential_postgres_dsn,
            credential_postgres_schema=src.credential_postgres_schema,
            credential_encryption_key=src.credential_encryption_key,
            credential_db_create_schema=src.credential_db_create_schema,
            vault_addr=src.vault_addr,
            vault_token=src.vault_token,
            vault_mount=src.vault_mount,
            vault_credential_root_path=src.vault_credential_root_path,
        ),
        workspace_runtime=WorkspaceRuntimeConfig(
            allow_sandbox=bool(src.allow_sandbox),
            sandbox_backend=src.sandbox_backend,
            sandbox_isolation_mode=src.sandbox_isolation_mode,
            sandbox_root_dir=resolved_sandbox_root_dir,
            opensandbox_base_url=src.opensandbox_base_url,
            opensandbox_api_key=src.opensandbox_api_key,
            opensandbox_image=src.opensandbox_image,
            opensandbox_timeout_s=int(src.opensandbox_timeout_s),
            opensandbox_cpu_limit=src.opensandbox_cpu_limit,
            opensandbox_memory_limit=src.opensandbox_memory_limit,
            opensandbox_proxy_port=int(src.opensandbox_proxy_port),
            sandbox_filesystem_persistence_mode=src.sandbox_filesystem_persistence_mode,
            sandbox_workspace_root=src.sandbox_workspace_root,
            sandbox_hot_idle_ttl_s=int(src.sandbox_hot_idle_ttl_s),
            sandbox_cold_retention_s=int(src.sandbox_cold_retention_s),
            sandbox_max_snapshot_bytes=int(src.sandbox_max_snapshot_bytes),
            workspace_metadata_backend=src.workspace_metadata_backend,
            workspace_metadata_root_dir=src.workspace_metadata_root_dir,
            workspace_lease_backend=src.workspace_lease_backend,
            workspace_lease_namespace=src.workspace_lease_namespace,
            workspace_lease_ttl_ms=int(src.workspace_lease_ttl_ms),
            workspace_lease_wait_timeout_ms=int(src.workspace_lease_wait_timeout_ms),
            workspace_snapshot_backend=src.workspace_snapshot_backend,
            workspace_snapshot_root_dir=src.workspace_snapshot_root_dir,
            workspace_snapshot_s3_endpoint=src.workspace_snapshot_s3_endpoint,
            workspace_snapshot_s3_access_key=src.workspace_snapshot_s3_access_key,
            workspace_snapshot_s3_secret_key=src.workspace_snapshot_s3_secret_key,
            workspace_snapshot_s3_bucket=src.workspace_snapshot_s3_bucket,
            workspace_snapshot_s3_secure=bool(src.workspace_snapshot_s3_secure),
            workspace_snapshot_s3_region=src.workspace_snapshot_s3_region,
            workspace_event_backend=src.workspace_event_backend,
            workspace_event_root_dir=src.workspace_event_root_dir,
            workspace_event_max_buffer=int(src.workspace_event_max_buffer),
            postgres_dsn=src.postgres_dsn,
            mysql_dsn=src.mysql_dsn,
            redis_dsn=src.redis_dsn,
            sql_backend_dialect=src.sql_backend_dialect,
            postgres_schema=src.postgres_schema,
        ),
    )


def _parse_plugin_roots(raw: str) -> tuple[str, ...] | None:
    roots = tuple(item.strip() for item in (raw or "").split(",") if item.strip())
    return roots or None


def _non_empty(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    stripped = value.strip()
    return stripped or None
