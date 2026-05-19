from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
import asyncio

from anyagent.protocol.admin_storage import AdminSandboxRuntimeDiagnostics, AdminSandboxWorkspaceRef
from anyagent.server.sandbox.backends import CommandExecutionResult
from anyagent.storage import SessionWorkspaceRecord

from anyagent.server.sandbox.workspace_events import WorkspaceEventLog
from anyagent.server.sandbox.workspace_service import WorkspaceEventContext, WorkspaceService, WorkspaceServiceConfig


def _build_config() -> WorkspaceServiceConfig:
    return WorkspaceServiceConfig(
        enabled=True,
        backend="local_reference",
        metadata_backend="local_file",
        lease_backend="memory",
        snapshot_backend="local_file",
        sandbox_mode="local-unsafe",
        sandbox_root_dir="/tmp/anyagent-tool-runtime-tests",
        persistence_mode="session_hot_cold",
        workspace_root="/workspace",
        hot_idle_ttl_s=60,
        cold_retention_s=3_600,
        max_snapshot_bytes=1_024 * 1_024,
    )


@dataclass(slots=True)
class _FakeBackend:
    current_record: SessionWorkspaceRecord | None = None
    restored_record: SessionWorkspaceRecord | None = None
    deleted: list[tuple[str, str]] = field(default_factory=list)
    restored_payloads: list[str] = field(default_factory=list)

    async def execute_command(
        self,
        *,
        policy,
        agent_id: str,
        session_key: str,
        cmd: str,
        workdir: str | None,
        timeout_seconds: int,
    ) -> CommandExecutionResult:
        return CommandExecutionResult(
            command=cmd,
            cwd=workdir or "/workspace",
            stdout="ok",
            stderr="",
            exit_code=0,
            duration_ms=1,
            timed_out=False,
        )

    async def get_workspace(self, *, agent_id: str, session_key: str) -> SessionWorkspaceRecord | None:
        return self.current_record

    async def list_workspaces(self) -> list[SessionWorkspaceRecord]:
        return [] if self.current_record is None else [self.current_record]

    async def restore_workspace_from_directory(
        self,
        *,
        policy,
        agent_id: str,
        session_key: str,
        src_dir: str | Path,
        record: SessionWorkspaceRecord,
    ) -> SessionWorkspaceRecord:
        workspace_dir = Path(src_dir)
        self.restored_payloads.append((workspace_dir / "hello.txt").read_text(encoding="utf-8"))
        self.current_record = record.model_copy(
            update={
                "state": "active",
                "workspace_id": "ws-restored",
                "workspace_root": str(workspace_dir),
            }
        )
        self.restored_record = self.current_record
        return self.current_record

    async def hibernate_workspace(self, *, agent_id: str, session_key: str) -> SessionWorkspaceRecord:
        if self.current_record is None:
            raise RuntimeError("workspace not found")
        return self.current_record

    async def delete_workspace(self, *, agent_id: str, session_key: str) -> None:
        self.deleted.append((agent_id, session_key))
        self.current_record = None

    async def get_runtime_diagnostics(
        self,
        *,
        agent_id: str,
        session_key: str,
        record: SessionWorkspaceRecord | None = None,
    ) -> AdminSandboxRuntimeDiagnostics | None:
        if record is None:
            return None
        return AdminSandboxRuntimeDiagnostics(
            provider="test-backend",
            sandbox_id=record.sandbox_id,
            state=record.state,
            reason="UNIT_TEST",
            message="diagnostics attached for unit test",
            image_uri="unit:test",
        )


@dataclass(slots=True)
class _FakeMetadataStore:
    records: dict[str, AdminSandboxWorkspaceRef] = field(default_factory=dict)
    upserted: list[AdminSandboxWorkspaceRef] = field(default_factory=list)

    async def get(self, *, session_partition_key: str) -> AdminSandboxWorkspaceRef | None:
        return self.records.get(session_partition_key)

    async def list(self) -> list[AdminSandboxWorkspaceRef]:
        return list(self.records.values())

    async def upsert(self, *, record: AdminSandboxWorkspaceRef) -> AdminSandboxWorkspaceRef:
        self.records[record.session_partition_key] = record
        self.upserted.append(record)
        return record

    async def delete(self, *, session_partition_key: str) -> bool:
        return self.records.pop(session_partition_key, None) is not None

    async def aclose(self) -> None:
        return None


@dataclass(slots=True)
class _FakeSnapshotStore:
    deleted_uris: list[str] = field(default_factory=list)
    materialized: list[tuple[str, str]] = field(default_factory=list)

    async def put_directory(
        self,
        *,
        session_partition_key: str,
        generation: int,
        src_dir: str,
        snapshot_digest: str | None,
        snapshot_bytes: int | None,
    ):
        raise AssertionError("put_directory is not used in these unit tests")

    async def delete(self, *, snapshot_uri: str) -> bool:
        self.deleted_uris.append(snapshot_uri)
        return True

    async def materialize_to_directory(self, *, snapshot_uri: str, target_dir: str) -> None:
        target = Path(target_dir)
        target.mkdir(parents=True, exist_ok=True)
        (target / "hello.txt").write_text("restored-from-snapshot", encoding="utf-8")
        self.materialized.append((snapshot_uri, str(target)))

    async def count(self) -> int:
        return 0

    async def aclose(self) -> None:
        return None


def test_prepare_execution_restores_from_snapshot_when_live_workspace_is_missing() -> None:
    backend = _FakeBackend()
    metadata_store = _FakeMetadataStore(
        records={
            "main::sess-1": AdminSandboxWorkspaceRef(
                session_partition_key="main::sess-1",
                workspace_id="ws-hibernated",
                generation=3,
                state="hibernated",
                tenant_id=None,
                sandbox_id="sandbox-old",
                workspace_root="/workspace",
                snapshot_uri="s3://bucket/workspaces/main__sess-1/00000003/workspace.tar.gz",
                snapshot_digest="sha256:test",
                snapshot_bytes=42,
            )
        }
    )
    snapshot_store = _FakeSnapshotStore()
    service = WorkspaceService(
        config=_build_config(),
        backend=backend,
        metadata_store=metadata_store,
        lease_store=None,
        snapshot_store=snapshot_store,
        event_log=WorkspaceEventLog(),
    )

    ref = asyncio.run(
        service.prepare_execution(
            agent_id="main",
            session_key="sess-1",
            event_context=WorkspaceEventContext(
                response_id="resp_workspace_restore_unit",
                trace_id="trace-workspace-restore-unit",
                audit_ref="ws_aud_restore_unit",
                tool_call_id="call_workspace_restore_unit",
                actor="agent:main",
            ),
        )
    )

    assert ref is not None
    assert ref.state == "active"
    assert ref.runtime_diagnostics is not None
    assert ref.runtime_diagnostics.provider == "test-backend"
    assert snapshot_store.materialized[0][0].startswith("s3://bucket/")
    assert backend.restored_payloads == ["restored-from-snapshot"]
    assert metadata_store.records["main::sess-1"].state == "active"
    assert metadata_store.records["main::sess-1"].runtime_diagnostics is not None
    events = asyncio.run(service.list_workspace_events(agent_id="main", session_key="sess-1"))
    assert [item.type for item in events] == [
        "anyagent.sandbox.workspace.restoring",
        "anyagent.sandbox.workspace.restored",
    ]
    assert all(item.trace_id == "trace-workspace-restore-unit" for item in events)
    assert all(item.audit_ref == "ws_aud_restore_unit" for item in events)
    assert events[-1].runtime_diagnostics is not None
    assert events[-1].runtime_diagnostics.provider == "test-backend"


def test_delete_removes_snapshot_artifact_and_metadata_record() -> None:
    metadata_store = _FakeMetadataStore(
        records={
            "main::sess-2": AdminSandboxWorkspaceRef(
                session_partition_key="main::sess-2",
                workspace_id="ws-delete",
                generation=2,
                state="hibernated",
                tenant_id=None,
                sandbox_id="sandbox-delete",
                workspace_root="/workspace",
                snapshot_uri="s3://bucket/workspaces/main__sess-2/00000002/workspace.tar.gz",
                snapshot_digest="sha256:delete",
                snapshot_bytes=24,
            )
        }
    )
    snapshot_store = _FakeSnapshotStore()
    backend = _FakeBackend()
    service = WorkspaceService(
        config=_build_config(),
        backend=backend,
        metadata_store=metadata_store,
        lease_store=None,
        snapshot_store=snapshot_store,
        event_log=WorkspaceEventLog(),
    )

    asyncio.run(service.delete(agent_id="main", session_key="sess-2"))

    assert backend.deleted == [("main", "sess-2")]
    assert snapshot_store.deleted_uris == ["s3://bucket/workspaces/main__sess-2/00000002/workspace.tar.gz"]
    assert "main::sess-2" not in metadata_store.records
