from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

from .manager import SandboxManager
from .opensandbox_backend import OpenSandboxWorkspaceBackend
from .workspace_events import WorkspaceEventStore, build_workspace_event_store
from .workspace_persistence import (
    InMemoryWorkspaceLeaseStore,
    LocalFileWorkspaceMetadataStore,
    PostgresWorkspaceMetadataStore,
    WorkspaceLeaseStore,
    WorkspaceMetadataStore,
    build_redis_workspace_lease_store,
)
from .workspace_service import LocalSandboxWorkspaceBackend, WorkspaceService, build_workspace_service_config
from .workspace_snapshots import (
    LocalFileWorkspaceSnapshotStore,
    WorkspaceSnapshotStore,
    build_s3_workspace_snapshot_store,
)


logger = logging.getLogger("anyagent.server.sandbox.workspace_runtime")


@dataclass(frozen=True, slots=True)
class WorkspaceRuntimeConfig:
    allow_sandbox: bool = False
    sandbox_backend: Literal["auto", "local_reference", "opensandbox"] = "auto"
    sandbox_isolation_mode: str = "disabled"
    sandbox_root_dir: str = "/tmp/anyagent-tool-runtime-sandboxes"
    opensandbox_base_url: str | None = None
    opensandbox_api_key: str | None = None
    opensandbox_image: str = "ubuntu:24.04"
    opensandbox_timeout_s: int = 3600
    opensandbox_cpu_limit: str = "1000m"
    opensandbox_memory_limit: str = "1Gi"
    opensandbox_proxy_port: int = 44772
    sandbox_filesystem_persistence_mode: str = "ephemeral"
    sandbox_workspace_root: str = "/workspace"
    sandbox_hot_idle_ttl_s: int = 900
    sandbox_cold_retention_s: int = 7 * 24 * 3600
    sandbox_max_snapshot_bytes: int = 5 * 1024 * 1024 * 1024
    workspace_metadata_backend: Literal["auto", "disabled", "local_file", "postgres"] = "auto"
    workspace_metadata_root_dir: str | None = None
    workspace_lease_backend: Literal["auto", "none", "memory", "redis"] = "auto"
    workspace_lease_namespace: str = "anyagent-tool-runtime"
    workspace_lease_ttl_ms: int = 60_000
    workspace_lease_wait_timeout_ms: int = 2_000
    workspace_snapshot_backend: Literal["auto", "disabled", "local_file", "s3"] = "auto"
    workspace_snapshot_root_dir: str | None = None
    workspace_snapshot_s3_endpoint: str | None = None
    workspace_snapshot_s3_access_key: str | None = None
    workspace_snapshot_s3_secret_key: str | None = None
    workspace_snapshot_s3_bucket: str = "anyagent-workspaces"
    workspace_snapshot_s3_secure: bool = False
    workspace_snapshot_s3_region: str | None = None
    workspace_event_backend: Literal["memory", "jsonl"] = "memory"
    workspace_event_root_dir: str | None = None
    workspace_event_max_buffer: int = 512
    postgres_dsn: Any | None = None
    mysql_dsn: Any | None = None
    redis_dsn: Any | None = None
    sql_backend_dialect: Literal["auto", "postgresql", "mysql"] = "auto"
    postgres_schema: str = "public"


@dataclass(slots=True)
class WorkspaceRuntimeAssembly:
    service: WorkspaceService
    sandbox_manager: SandboxManager | None
    event_store: WorkspaceEventStore
    metadata_backend: str
    lease_backend: str
    snapshot_backend: str


async def build_workspace_runtime(config: WorkspaceRuntimeConfig) -> WorkspaceRuntimeAssembly:
    if config.allow_sandbox:
        mode = (config.sandbox_isolation_mode or "").strip().lower()
        if mode not in {"container", "vm", "local_unsafe"}:
            raise RuntimeError(
                "ALLOW_SANDBOX=1 requires SANDBOX_ISOLATION_MODE in {container, vm, local_unsafe} (default is disabled)"
            )
        if mode == "local_unsafe":
            logger.warning("sandbox enabled in UNSAFE local mode; do not use in production")

    resolved_metadata_backend, metadata_store = await build_workspace_metadata_store_from_config(config)
    resolved_lease_backend, lease_store = await build_workspace_lease_store_from_config(config)
    resolved_snapshot_backend, snapshot_store = await build_workspace_snapshot_store_from_config(config)
    service_config = build_workspace_service_config(
        allow_sandbox=config.allow_sandbox,
        sandbox_backend=config.sandbox_backend,
        sandbox_isolation_mode=config.sandbox_isolation_mode,
        sandbox_root_dir=config.sandbox_root_dir,
        sandbox_filesystem_persistence_mode=config.sandbox_filesystem_persistence_mode,
        sandbox_workspace_root=config.sandbox_workspace_root,
        sandbox_hot_idle_ttl_s=config.sandbox_hot_idle_ttl_s,
        sandbox_cold_retention_s=config.sandbox_cold_retention_s,
        sandbox_max_snapshot_bytes=config.sandbox_max_snapshot_bytes,
        metadata_backend=resolved_metadata_backend,
        lease_backend=resolved_lease_backend,
        snapshot_backend=resolved_snapshot_backend,
    )
    event_store = build_workspace_event_store(
        backend=config.workspace_event_backend,
        root_dir=config.workspace_event_root_dir,
        max_events=config.workspace_event_max_buffer,
    )
    service = WorkspaceService(
        config=service_config,
        backend=None,
        metadata_store=metadata_store,
        lease_store=lease_store,
        snapshot_store=snapshot_store,
        event_log=event_store,
    )
    sandbox_manager: SandboxManager | None = None
    if config.allow_sandbox:
        if service_config.backend == "opensandbox":
            service = WorkspaceService(
                config=service_config,
                backend=OpenSandboxWorkspaceBackend(
                    base_url=(config.opensandbox_base_url or "").strip(),
                    api_key=(config.opensandbox_api_key or "").strip() or None,
                    workspace_root=config.sandbox_workspace_root,
                    image=config.opensandbox_image,
                    sandbox_timeout_s=config.opensandbox_timeout_s,
                    cpu_limit=config.opensandbox_cpu_limit,
                    memory_limit=config.opensandbox_memory_limit,
                    proxy_port=config.opensandbox_proxy_port,
                ),
                metadata_store=metadata_store,
                lease_store=lease_store,
                snapshot_store=snapshot_store,
                event_log=event_store,
            )
        else:
            sandbox_manager = SandboxManager(root_dir=config.sandbox_root_dir)
            service = WorkspaceService(
                config=service_config,
                backend=LocalSandboxWorkspaceBackend(
                    sandbox_manager=sandbox_manager,
                    policy=service.sandbox_policy_for_agent("main"),
                ),
                metadata_store=metadata_store,
                lease_store=lease_store,
                snapshot_store=snapshot_store,
                event_log=event_store,
            )
    return WorkspaceRuntimeAssembly(
        service=service,
        sandbox_manager=sandbox_manager,
        event_store=event_store,
        metadata_backend=resolved_metadata_backend,
        lease_backend=resolved_lease_backend,
        snapshot_backend=resolved_snapshot_backend,
    )


async def build_workspace_metadata_store_from_config(
    config: WorkspaceRuntimeConfig,
) -> tuple[str, WorkspaceMetadataStore | None]:
    backend = (config.workspace_metadata_backend or "auto").strip().lower()
    if backend not in {"auto", "disabled", "local_file", "postgres"}:
        raise RuntimeError("invalid WORKSPACE_METADATA_BACKEND")
    if backend == "disabled":
        return "disabled", None
    if backend == "auto":
        backend = "postgres" if config.postgres_dsn is not None else "local_file"

    if backend == "local_file":
        root = (config.workspace_metadata_root_dir or "").strip()
        if root:
            path = Path(root).expanduser().resolve()
        else:
            path = (Path(config.sandbox_root_dir).expanduser().resolve() / "_workspace_metadata").resolve()
        return "local_file", LocalFileWorkspaceMetadataStore(root_dir=path)

    try:
        from anyagent.storage.external import create_external_sql_engine, resolve_external_sql_backend_config
    except ModuleNotFoundError as exc:
        raise RuntimeError("postgres workspace metadata backend requires optional dependency: anyagent[postgres]") from exc

    sql_config = resolve_external_sql_backend_config(
        postgres_dsn=config.postgres_dsn,
        mysql_dsn=config.mysql_dsn,
        redis_dsn=config.redis_dsn,
        schema_name=config.postgres_schema,
        namespace=config.workspace_lease_namespace,
        dialect=config.sql_backend_dialect,
    )
    if sql_config.dialect != "postgresql":
        raise RuntimeError("workspace metadata backend currently only supports PostgreSQL")
    engine = create_external_sql_engine(sql_config)
    store = PostgresWorkspaceMetadataStore(engine=engine, schema_name=config.postgres_schema)
    await store.ensure_schema()
    return "postgres", store


async def build_workspace_lease_store_from_config(config: WorkspaceRuntimeConfig) -> tuple[str, WorkspaceLeaseStore]:
    backend = (config.workspace_lease_backend or "auto").strip().lower()
    if backend not in {"auto", "none", "memory", "redis"}:
        raise RuntimeError("invalid WORKSPACE_LEASE_BACKEND")
    if backend == "auto":
        backend = "redis" if config.redis_dsn is not None else "memory"
    if backend in {"none", "memory"}:
        return "memory", InMemoryWorkspaceLeaseStore(
            ttl_ms=config.workspace_lease_ttl_ms,
            wait_timeout_ms=config.workspace_lease_wait_timeout_ms,
        )
    if config.redis_dsn is None:
        raise RuntimeError("redis workspace lease backend requires REDIS_DSN")
    return "redis", build_redis_workspace_lease_store(
        redis_dsn=str(config.redis_dsn),
        namespace=config.workspace_lease_namespace,
        ttl_ms=config.workspace_lease_ttl_ms,
        wait_timeout_ms=config.workspace_lease_wait_timeout_ms,
    )


async def build_workspace_snapshot_store_from_config(
    config: WorkspaceRuntimeConfig,
) -> tuple[str, WorkspaceSnapshotStore | None]:
    backend = (config.workspace_snapshot_backend or "auto").strip().lower()
    if backend not in {"auto", "disabled", "local_file", "s3"}:
        raise RuntimeError("invalid WORKSPACE_SNAPSHOT_BACKEND")
    if backend == "disabled":
        return "disabled", None
    if backend == "auto":
        backend = "s3" if config.workspace_snapshot_s3_endpoint else ("local_file" if config.allow_sandbox else "disabled")
    if backend == "disabled":
        return "disabled", None

    if backend == "s3":
        endpoint = (config.workspace_snapshot_s3_endpoint or "").strip()
        access_key = (config.workspace_snapshot_s3_access_key or "").strip()
        secret_key = (config.workspace_snapshot_s3_secret_key or "").strip()
        if not endpoint or not access_key or not secret_key:
            raise RuntimeError("s3 snapshot backend requires endpoint/access_key/secret_key")
        return "s3", build_s3_workspace_snapshot_store(
            endpoint=endpoint,
            access_key=access_key,
            secret_key=secret_key,
            secure=bool(config.workspace_snapshot_s3_secure),
            region=config.workspace_snapshot_s3_region,
            bucket=config.workspace_snapshot_s3_bucket,
        )

    root = (config.workspace_snapshot_root_dir or "").strip()
    if root:
        path = Path(root).expanduser().resolve()
    else:
        path = (Path(config.sandbox_root_dir).expanduser().resolve() / "_workspace_snapshots").resolve()
    return "local_file", LocalFileWorkspaceSnapshotStore(root_dir=path)
