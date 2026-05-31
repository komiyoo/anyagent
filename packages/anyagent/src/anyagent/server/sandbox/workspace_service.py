from __future__ import annotations

import json
import logging
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from pydantic import BaseModel, ConfigDict, Field

from anyagent.protocol.admin_storage import AdminSandboxRuntimeDiagnostics, AdminSandboxWorkspaceRef
from anyagent.protocol.sandbox import FileSystemSandboxPolicy, SandboxPolicy
from anyagent.protocol.stage_events import AnyAgentWorkspaceLifecycleEvent
from anyagent.server.sandbox.backends import CommandExecutionResult, CommandStagedFile
from anyagent.storage import SessionWorkspaceRecord

from .manager import SandboxManager
from .workspace_events import WorkspaceEventStore
from .workspace_persistence import WorkspaceLeaseStore, WorkspaceMetadataStore, hold_workspace_lease
from .workspace_snapshots import WorkspaceSnapshotStore

logger = logging.getLogger("anyagent.server.sandbox.workspace")


class WorkspaceServiceConfig(BaseModel):
    """Workspace service configuration snapshot."""

    model_config = ConfigDict(extra="forbid")

    enabled: bool
    backend: str
    metadata_backend: str
    lease_backend: str
    snapshot_backend: str
    sandbox_mode: str
    sandbox_root_dir: str
    persistence_mode: str
    workspace_root: str
    hot_idle_ttl_s: int = Field(ge=0)
    cold_retention_s: int = Field(ge=1)
    max_snapshot_bytes: int = Field(ge=1)


class WorkspaceServiceHealth(BaseModel):
    """Minimal admin/ops health view."""

    model_config = ConfigDict(extra="forbid")

    enabled: bool
    backend: str
    metadata_backend: str
    lease_backend: str
    snapshot_backend: str
    sandbox_mode: str
    persistence_mode: str
    workspace_root: str
    workspace_count: int = Field(ge=0)
    sandbox_root_dir: str | None = None
    runtime_providers: list[str] = Field(default_factory=list)
    runtime_states: dict[str, int] = Field(default_factory=dict)


class WorkspaceEventContext(BaseModel):
    """Minimal tracing/audit context for workspace lifecycle events."""

    model_config = ConfigDict(extra="forbid")

    response_id: str
    trace_id: str | None = None
    audit_ref: str | None = None
    tool_call_id: str | None = None
    actor: str | None = None


class WorkspaceBackend(Protocol):
    async def execute_command(
        self,
        *,
        policy: SandboxPolicy,
        agent_id: str,
        session_key: str,
        cmd: str,
        workdir: str | None,
        timeout_seconds: int,
        env: dict[str, str] | None = None,
        staged_files: list[CommandStagedFile] | None = None,
    ) -> CommandExecutionResult: ...

    async def get_workspace(self, *, agent_id: str, session_key: str) -> SessionWorkspaceRecord | None: ...

    async def list_workspaces(self) -> list[SessionWorkspaceRecord]: ...

    async def restore_workspace_from_directory(
        self,
        *,
        policy: SandboxPolicy,
        agent_id: str,
        session_key: str,
        src_dir: str | Path,
        record: SessionWorkspaceRecord,
    ) -> SessionWorkspaceRecord: ...

    async def hibernate_workspace(self, *, agent_id: str, session_key: str) -> SessionWorkspaceRecord: ...

    async def delete_workspace(self, *, agent_id: str, session_key: str) -> None: ...

    async def get_runtime_diagnostics(
        self,
        *,
        agent_id: str,
        session_key: str,
        record: SessionWorkspaceRecord | None = None,
    ) -> AdminSandboxRuntimeDiagnostics | None: ...


@dataclass(slots=True)
class LocalSandboxWorkspaceBackend:
    """
    Reference backend over Core `SandboxManager`.

    HTTP/admin surfaces depend on the `WorkspaceBackend` protocol, so
    production backends can be swapped without changing service orchestration.
    """

    sandbox_manager: SandboxManager
    policy: SandboxPolicy

    async def execute_command(
        self,
        *,
        policy: SandboxPolicy,
        agent_id: str,
        session_key: str,
        cmd: str,
        workdir: str | None,
        timeout_seconds: int,
        env: dict[str, str] | None = None,
        staged_files: list[CommandStagedFile] | None = None,
    ) -> CommandExecutionResult:
        return await self.sandbox_manager.execute(
            policy=policy,
            agent_id=agent_id,
            session_key=session_key,
            cmd=cmd,
            workdir=workdir,
            timeout_seconds=timeout_seconds,
            env=env,
            staged_files=staged_files,
        )

    async def get_workspace(self, *, agent_id: str, session_key: str) -> SessionWorkspaceRecord | None:
        return await self.sandbox_manager.get_workspace(agent_id=agent_id, session_key=session_key)

    async def list_workspaces(self) -> list[SessionWorkspaceRecord]:
        return await self.sandbox_manager.list_workspaces()

    async def restore_workspace_from_directory(
        self,
        *,
        policy: SandboxPolicy,
        agent_id: str,
        session_key: str,
        src_dir: str | Path,
        record: SessionWorkspaceRecord,
    ) -> SessionWorkspaceRecord:
        return await self.sandbox_manager.restore_workspace_from_directory(
            policy=policy,
            agent_id=agent_id,
            session_key=session_key,
            src_dir=src_dir,
            record=record,
        )

    async def hibernate_workspace(self, *, agent_id: str, session_key: str) -> SessionWorkspaceRecord:
        return await self.sandbox_manager.hibernate(policy=self.policy, agent_id=agent_id, session_key=session_key)

    async def delete_workspace(self, *, agent_id: str, session_key: str) -> None:
        await self.sandbox_manager.destroy_workspace(agent_id=agent_id, session_key=session_key)

    async def get_runtime_diagnostics(
        self,
        *,
        agent_id: str,
        session_key: str,
        record: SessionWorkspaceRecord | None = None,
    ) -> AdminSandboxRuntimeDiagnostics | None:
        return None


@dataclass(slots=True)
class WorkspaceService:
    config: WorkspaceServiceConfig
    backend: WorkspaceBackend | None = None
    metadata_store: WorkspaceMetadataStore | None = None
    lease_store: WorkspaceLeaseStore | None = None
    snapshot_store: WorkspaceSnapshotStore | None = None
    event_log: WorkspaceEventStore | None = None

    def sandbox_policy_for_agent(self, _agent_id: str) -> SandboxPolicy:
        """Use the global workspace policy; agent-level policy can layer on later."""

        return SandboxPolicy(
            mode=self.config.sandbox_mode,
            filesystem=FileSystemSandboxPolicy(
                persistence_mode=self.config.persistence_mode,
                workspace_root=self.config.workspace_root,
                hot_idle_ttl_s=self.config.hot_idle_ttl_s,
                cold_retention_s=self.config.cold_retention_s,
                max_snapshot_bytes=self.config.max_snapshot_bytes,
            ),
        )

    async def list_refs(self) -> list[AdminSandboxWorkspaceRef]:
        if self.backend is not None:
            records = await self.backend.list_workspaces()
            refs = [
                await self._decorate_ref(
                    AdminSandboxWorkspaceRef.model_validate(item.model_dump()),
                    agent_id=self._agent_id_from_partition_key(item.session_partition_key),
                    session_key=self._session_key_from_partition_key(item.session_partition_key),
                    record=item,
                )
                for item in records
            ]
            if self.metadata_store is not None:
                for ref in refs:
                    await self.metadata_store.upsert(record=ref)
            return refs
        if self.metadata_store is None:
            return []
        return await self.metadata_store.list()

    async def get_ref(self, *, agent_id: str, session_key: str) -> AdminSandboxWorkspaceRef | None:
        session_partition_key = f"{agent_id}::{session_key}"
        if self.backend is not None:
            record = await self.backend.get_workspace(agent_id=agent_id, session_key=session_key)
            if record is not None:
                ref = await self._decorate_ref(
                    AdminSandboxWorkspaceRef.model_validate(record.model_dump()),
                    agent_id=agent_id,
                    session_key=session_key,
                    record=record,
                )
                if self.metadata_store is not None:
                    await self.metadata_store.upsert(record=ref)
                return ref
        if self.metadata_store is None:
            return None
        return await self.metadata_store.get(session_partition_key=session_partition_key)

    async def hibernate_ref(
        self,
        *,
        agent_id: str,
        session_key: str,
        event_context: WorkspaceEventContext | None = None,
    ) -> AdminSandboxWorkspaceRef:
        if self.backend is None:
            raise RuntimeError("workspace service is disabled")
        session_partition_key = f"{agent_id}::{session_key}"
        current = await self.get_ref(agent_id=agent_id, session_key=session_key)
        if current is not None:
            await self._emit_workspace_event(
                type_="anyagent.sandbox.workspace.checkpointing",
                ref=current,
                event_context=event_context,
            )
        if self.lease_store is not None:
            try:
                async with hold_workspace_lease(store=self.lease_store, key=session_partition_key):
                    record = await self.backend.hibernate_workspace(agent_id=agent_id, session_key=session_key)
            except Exception as exc:  # noqa: BLE001
                if current is not None:
                    await self._emit_workspace_event(
                        type_="anyagent.sandbox.workspace.checkpoint_failed",
                        ref=current,
                        event_context=event_context,
                        failure_code="checkpoint_failed",
                        failure_message=str(exc),
                    )
                raise
        else:
            try:
                record = await self.backend.hibernate_workspace(agent_id=agent_id, session_key=session_key)
            except Exception as exc:  # noqa: BLE001
                if current is not None:
                    await self._emit_workspace_event(
                        type_="anyagent.sandbox.workspace.checkpoint_failed",
                        ref=current,
                        event_context=event_context,
                        failure_code="checkpoint_failed",
                        failure_message=str(exc),
                    )
                raise
        ref = await self._decorate_ref(
            AdminSandboxWorkspaceRef.model_validate(record.model_dump()),
            agent_id=agent_id,
            session_key=session_key,
            record=record,
        )
        await self._emit_workspace_event(
            type_="anyagent.sandbox.workspace.checkpointed",
            ref=ref,
            event_context=event_context,
        )
        ref = await self._persist_snapshot_artifact(ref)
        await self._emit_workspace_event(
            type_="anyagent.sandbox.workspace.hibernated",
            ref=ref,
            event_context=event_context,
        )
        if self.metadata_store is not None:
            await self.metadata_store.upsert(record=ref)
        return ref

    async def delete(
        self,
        *,
        agent_id: str,
        session_key: str,
        event_context: WorkspaceEventContext | None = None,
    ) -> None:
        session_partition_key = f"{agent_id}::{session_key}"
        current: AdminSandboxWorkspaceRef | None = None
        if self.metadata_store is not None:
            current = await self.metadata_store.get(session_partition_key=session_partition_key)
        if self.backend is not None:
            if self.lease_store is not None:
                async with hold_workspace_lease(store=self.lease_store, key=session_partition_key):
                    await self.backend.delete_workspace(agent_id=agent_id, session_key=session_key)
            else:
                await self.backend.delete_workspace(agent_id=agent_id, session_key=session_key)
        if current is not None:
            await self._log_workspace_event(
                type_="anyagent.sandbox.workspace.deleted",
                ref=current,
                event_context=event_context,
            )
            if self.snapshot_store is not None and current.snapshot_uri:
                await self.snapshot_store.delete(snapshot_uri=current.snapshot_uri)
        if self.metadata_store is not None:
            await self.metadata_store.delete(session_partition_key=session_partition_key)

    async def sync_from_backend(self, *, agent_id: str, session_key: str) -> AdminSandboxWorkspaceRef | None:
        """Mirror the latest backend workspace metadata after exec completes."""

        if self.backend is None:
            return None
        record = await self.backend.get_workspace(agent_id=agent_id, session_key=session_key)
        if record is None:
            return None
        ref = await self._decorate_ref(
            AdminSandboxWorkspaceRef.model_validate(record.model_dump()),
            agent_id=agent_id,
            session_key=session_key,
            record=record,
        )
        if self.metadata_store is not None:
            existing = await self.metadata_store.get(session_partition_key=f"{agent_id}::{session_key}")
            ref = self._merge_snapshot_fields(existing=existing, current=ref)
            await self.metadata_store.upsert(record=ref)
        return ref

    async def prepare_execution(
        self,
        *,
        agent_id: str,
        session_key: str,
        event_context: WorkspaceEventContext | None = None,
    ) -> AdminSandboxWorkspaceRef | None:
        """
        Ensure the workspace is active before execution.

        If the current instance has no live workspace but metadata/snapshot
        exists, materialize the snapshot and restore it into the backend.
        """

        if self.backend is None:
            return None
        current = await self.backend.get_workspace(agent_id=agent_id, session_key=session_key)
        if current is not None:
            ref = await self._decorate_ref(
                AdminSandboxWorkspaceRef.model_validate(current.model_dump()),
                agent_id=agent_id,
                session_key=session_key,
                record=current,
            )
            if self.metadata_store is not None:
                await self.metadata_store.upsert(record=ref)
            return ref
        if self.metadata_store is None or self.snapshot_store is None:
            return None
        session_partition_key = f"{agent_id}::{session_key}"
        persisted = await self.metadata_store.get(session_partition_key=session_partition_key)
        if persisted is None or not persisted.snapshot_uri:
            return None
        record_payload = persisted.model_dump(exclude={"runtime_diagnostics"})
        record = SessionWorkspaceRecord.model_validate(record_payload)
        await self._emit_workspace_event(
            type_="anyagent.sandbox.workspace.restoring",
            ref=persisted,
            event_context=event_context,
        )
        with tempfile.TemporaryDirectory(prefix="anyagent-workspace-restore-") as td:
            target_dir = Path(td) / "workspace"
            try:
                await self.snapshot_store.materialize_to_directory(
                    snapshot_uri=persisted.snapshot_uri,
                    target_dir=str(target_dir),
                )
                restored = await self.backend.restore_workspace_from_directory(
                    policy=self.sandbox_policy_for_agent(agent_id),
                    agent_id=agent_id,
                    session_key=session_key,
                    src_dir=target_dir,
                    record=record,
                )
            except Exception as exc:  # noqa: BLE001
                await self._emit_workspace_event(
                    type_="anyagent.sandbox.workspace.restore_failed",
                    ref=persisted,
                    event_context=event_context,
                    failure_code="restore_failed",
                    failure_message=str(exc),
                )
                raise
        ref = await self._decorate_ref(
            AdminSandboxWorkspaceRef.model_validate(restored.model_dump()),
            agent_id=agent_id,
            session_key=session_key,
            record=restored,
        )
        await self._emit_workspace_event(
            type_="anyagent.sandbox.workspace.restored",
            ref=ref,
            event_context=event_context,
        )
        if self.metadata_store is not None:
            await self.metadata_store.upsert(record=ref)
        return ref

    async def execute_command(
        self,
        *,
        policy: SandboxPolicy,
        agent_id: str,
        session_key: str,
        cmd: str,
        workdir: str | None,
        timeout_seconds: int,
        env: dict[str, str] | None = None,
        staged_files: list[CommandStagedFile] | None = None,
        event_context: WorkspaceEventContext | None = None,
    ) -> CommandExecutionResult:
        if self.backend is None:
            raise RuntimeError("workspace service is disabled")
        await self.prepare_execution(agent_id=agent_id, session_key=session_key, event_context=event_context)
        result = await self.backend.execute_command(
            policy=policy,
            agent_id=agent_id,
            session_key=session_key,
            cmd=cmd,
            workdir=workdir,
            timeout_seconds=timeout_seconds,
            env=env,
            staged_files=staged_files,
        )
        await self.sync_from_backend(agent_id=agent_id, session_key=session_key)
        return result

    async def health(self) -> WorkspaceServiceHealth:
        count = 0
        refs: list[AdminSandboxWorkspaceRef] = []
        if self.metadata_store is not None:
            refs = await self.metadata_store.list()
            count = len(refs)
        elif self.backend is not None:
            records = await self.backend.list_workspaces()
            refs = [
                await self._decorate_ref(
                    AdminSandboxWorkspaceRef.model_validate(item.model_dump()),
                    agent_id=self._agent_id_from_partition_key(item.session_partition_key),
                    session_key=self._session_key_from_partition_key(item.session_partition_key),
                    record=item,
                )
                for item in records
            ]
            count = len(refs)

        runtime_providers = sorted(
            {
                ref.runtime_diagnostics.provider
                for ref in refs
                if ref.runtime_diagnostics is not None and ref.runtime_diagnostics.provider
            }
        )
        runtime_states: dict[str, int] = {}
        for ref in refs:
            state = ref.runtime_diagnostics.state if ref.runtime_diagnostics is not None else None
            if not state:
                continue
            runtime_states[state] = runtime_states.get(state, 0) + 1
        return WorkspaceServiceHealth(
            enabled=self.config.enabled,
            backend=self.config.backend,
            metadata_backend=self.config.metadata_backend,
            lease_backend=self.config.lease_backend,
            snapshot_backend=self.config.snapshot_backend,
            sandbox_mode=self.config.sandbox_mode,
            persistence_mode=self.config.persistence_mode,
            workspace_root=self.config.workspace_root,
            workspace_count=count,
            sandbox_root_dir=self.config.sandbox_root_dir,
            runtime_providers=runtime_providers,
            runtime_states=runtime_states,
        )

    async def list_workspace_events(
        self,
        *,
        agent_id: str,
        session_key: str,
        limit: int = 50,
    ) -> list[AnyAgentWorkspaceLifecycleEvent]:
        if self.event_log is None:
            return []
        session_partition_key = f"{agent_id}::{session_key}"
        return await self.event_log.list(session_partition_key=session_partition_key, limit=limit)

    async def aclose(self) -> None:
        if self.metadata_store is not None:
            await self.metadata_store.aclose()
        if self.lease_store is not None:
            await self.lease_store.aclose()
        if self.snapshot_store is not None:
            await self.snapshot_store.aclose()
        if self.event_log is not None:
            await self.event_log.aclose()

    async def _persist_snapshot_artifact(self, ref: AdminSandboxWorkspaceRef) -> AdminSandboxWorkspaceRef:
        """
        Mirror the committed backend snapshot into the configured snapshot store.

        Current contract: the backend points `snapshot_uri` at a local committed
        snapshot directory. The snapshot store copies it and rewrites the final
        `snapshot_uri`.
        """

        if self.snapshot_store is None or not ref.snapshot_uri:
            return ref
        artifact = await self.snapshot_store.put_directory(
            session_partition_key=ref.session_partition_key,
            generation=ref.generation,
            src_dir=ref.snapshot_uri,
            snapshot_digest=ref.snapshot_digest,
            snapshot_bytes=ref.snapshot_bytes,
        )
        return ref.model_copy(
            update={
                "snapshot_uri": artifact.snapshot_uri,
                "snapshot_digest": artifact.snapshot_digest,
                "snapshot_bytes": artifact.snapshot_bytes,
            }
        )

    def _merge_snapshot_fields(
        self,
        *,
        existing: AdminSandboxWorkspaceRef | None,
        current: AdminSandboxWorkspaceRef,
    ) -> AdminSandboxWorkspaceRef:
        if existing is None:
            return current
        if not existing.snapshot_uri:
            return current
        if int(existing.generation) > int(current.generation):
            return current
        return current.model_copy(
            update={
                "snapshot_uri": existing.snapshot_uri,
                "snapshot_digest": existing.snapshot_digest,
                "snapshot_bytes": existing.snapshot_bytes,
                "runtime_diagnostics": current.runtime_diagnostics or existing.runtime_diagnostics,
            }
        )

    async def _decorate_ref(
        self,
        ref: AdminSandboxWorkspaceRef,
        *,
        agent_id: str,
        session_key: str,
        record: SessionWorkspaceRecord | None,
    ) -> AdminSandboxWorkspaceRef:
        if self.backend is None:
            return ref
        diagnostics = await self.backend.get_runtime_diagnostics(
            agent_id=agent_id,
            session_key=session_key,
            record=record,
        )
        if diagnostics is None:
            return ref
        return ref.model_copy(update={"runtime_diagnostics": diagnostics})

    async def _emit_workspace_event(
        self,
        *,
        type_: str,
        ref: AdminSandboxWorkspaceRef,
        event_context: WorkspaceEventContext | None,
        failure_code: str | None = None,
        failure_message: str | None = None,
    ) -> None:
        event = AnyAgentWorkspaceLifecycleEvent(
            type=type_,
            response_id=self._response_id_for_event(ref=ref, event_context=event_context),
            trace_id=event_context.trace_id if event_context is not None else None,
            session_partition_key=ref.session_partition_key,
            workspace_id=ref.workspace_id,
            generation=ref.generation,
            sandbox_id=ref.sandbox_id,
            snapshot_uri=ref.snapshot_uri,
            snapshot_bytes=ref.snapshot_bytes,
            audit_ref=event_context.audit_ref if event_context is not None else None,
            failure_code=failure_code,
            failure_message=failure_message,
            runtime_diagnostics=ref.runtime_diagnostics,
            duration_ms=None,
            ts_ms=int(ref.last_accessed_at_ms or 0) or int(time.time() * 1000),
        )
        await self._log_workspace_event(type_=type_, ref=ref, event_context=event_context, event=event)
        if self.event_log is None:
            return
        await self.event_log.append(event)

    async def _log_workspace_event(
        self,
        *,
        type_: str,
        ref: AdminSandboxWorkspaceRef,
        event_context: WorkspaceEventContext | None,
        event: AnyAgentWorkspaceLifecycleEvent | None = None,
    ) -> None:
        payload = {
            "type": type_,
            "response_id": (event.response_id if event is not None else self._response_id_for_event(ref=ref, event_context=event_context)),
            "trace_id": event_context.trace_id if event_context is not None else None,
            "audit_ref": event_context.audit_ref if event_context is not None else None,
            "tool_call_id": event_context.tool_call_id if event_context is not None else None,
            "actor": event_context.actor if event_context is not None else None,
            "session_partition_key": ref.session_partition_key,
            "workspace_id": ref.workspace_id,
            "generation": ref.generation,
            "sandbox_id": ref.sandbox_id,
            "snapshot_uri": ref.snapshot_uri,
            "failure_code": event.failure_code if event is not None else None,
            "failure_message": event.failure_message if event is not None else None,
            "runtime_provider": ref.runtime_diagnostics.provider if ref.runtime_diagnostics is not None else None,
            "runtime_state": ref.runtime_diagnostics.state if ref.runtime_diagnostics is not None else None,
        }
        logger.info("workspace_event %s", json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")))

    def _response_id_for_event(
        self,
        *,
        ref: AdminSandboxWorkspaceRef,
        event_context: WorkspaceEventContext | None,
    ) -> str:
        if event_context is not None and event_context.response_id:
            return event_context.response_id
        return f"workspace:{ref.session_partition_key}"

    def _agent_id_from_partition_key(self, session_partition_key: str) -> str:
        if "::" not in session_partition_key:
            return session_partition_key
        return session_partition_key.split("::", 1)[0]

    def _session_key_from_partition_key(self, session_partition_key: str) -> str:
        if "::" not in session_partition_key:
            return session_partition_key
        return session_partition_key.split("::", 1)[1]


def build_workspace_service_config(
    *,
    allow_sandbox: bool,
    sandbox_backend: str,
    sandbox_isolation_mode: str,
    sandbox_root_dir: str,
    sandbox_filesystem_persistence_mode: str,
    sandbox_workspace_root: str,
    sandbox_hot_idle_ttl_s: int,
    sandbox_cold_retention_s: int,
    sandbox_max_snapshot_bytes: int,
    metadata_backend: str,
    lease_backend: str,
    snapshot_backend: str,
) -> WorkspaceServiceConfig:
    raw_mode = (sandbox_isolation_mode or "").strip().lower()
    raw_backend = (sandbox_backend or "auto").strip().lower()
    if not allow_sandbox:
        backend = "disabled"
        sandbox_mode = "disabled"
    elif raw_backend == "opensandbox":
        backend = "opensandbox"
        sandbox_mode = "opensandbox"
    else:
        sandbox_mode = "local-unsafe" if raw_mode == "local_unsafe" else "external"
        backend = "local_reference"
    return WorkspaceServiceConfig(
        enabled=bool(allow_sandbox),
        backend=backend,
        metadata_backend=metadata_backend,
        lease_backend=lease_backend,
        snapshot_backend=snapshot_backend,
        sandbox_mode=sandbox_mode,
        sandbox_root_dir=str(Path(sandbox_root_dir).expanduser().resolve()),
        persistence_mode=(sandbox_filesystem_persistence_mode or "ephemeral").strip().lower(),
        workspace_root=sandbox_workspace_root,
        hot_idle_ttl_s=int(sandbox_hot_idle_ttl_s),
        cold_retention_s=int(sandbox_cold_retention_s),
        max_snapshot_bytes=int(sandbox_max_snapshot_bytes),
    )


@dataclass(slots=True)
class WorkspaceAwareSandboxManagerAdapter:
    """
    Minimal manager adapter for `build_exec_handler`.

    This keeps `exec` on the Core `EXEC_TOOL` path while routing execution
    through workspace restore / metadata sync orchestration first.
    """

    workspace_service: WorkspaceService

    async def execute(
        self,
        *,
        policy: SandboxPolicy,
        agent_id: str,
        session_key: str,
        cmd: str,
        workdir: str | None = None,
        timeout_seconds: int = 60,
        env: dict[str, str] | None = None,
        staged_files: list[CommandStagedFile] | None = None,
        response_id: str | None = None,
        tool_call_id: str | None = None,
        trace_id: str | None = None,
        audit_ref: str | None = None,
    ) -> CommandExecutionResult:
        return await self.workspace_service.execute_command(
            policy=policy,
            agent_id=agent_id,
            session_key=session_key,
            cmd=cmd,
            workdir=workdir,
            timeout_seconds=timeout_seconds,
            env=env,
            staged_files=staged_files,
            event_context=WorkspaceEventContext(
                response_id=response_id or f"workspace:{agent_id}::{session_key}",
                trace_id=trace_id,
                audit_ref=audit_ref,
                tool_call_id=tool_call_id,
                actor=f"agent:{agent_id}",
            ),
        )
