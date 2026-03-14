from __future__ import annotations

from pathlib import Path

from anyagent.gateway.session import session_partition_key
from anyagent.protocol.sandbox import FileSystemSandboxPolicy, SandboxPolicy
from anyagent.storage import SessionWorkspaceRecord

from .backends import CommandExecutionResult, LocalUnsafeBackend
from .workspace import LocalSessionWorkspaceService


class SandboxManager:
    def __init__(self, *, root_dir: str | Path | None = None) -> None:
        base_root = Path(root_dir) if root_dir is not None else None
        self._local_unsafe = LocalUnsafeBackend(root_dir=base_root)
        self._workspace_service = LocalSessionWorkspaceService(
            root_dir=(base_root or (self._local_unsafe.root_dir / "_workspace_state"))
        )

    @property
    def workspace_service(self) -> LocalSessionWorkspaceService:
        return self._workspace_service

    async def execute(
        self,
        *,
        policy: SandboxPolicy,
        agent_id: str,
        session_key: str,
        cmd: str,
        workdir: str | None = None,
        timeout_seconds: int = 60,
        response_id: str | None = None,
        tool_call_id: str | None = None,
        trace_id: str | None = None,
        audit_ref: str | None = None,
    ) -> CommandExecutionResult:
        mode = policy.mode
        if mode == "disabled":
            raise RuntimeError("sandbox is disabled")
        if mode not in {"local-unsafe", "external", "opensandbox"}:
            raise RuntimeError(f"unsupported sandbox mode: {mode}")
        if mode == "opensandbox":
            raise RuntimeError(f"sandbox backend not implemented yet: {mode}")
        session_pk = session_partition_key(agent_id=agent_id, session_key=session_key)
        filesystem = _effective_filesystem_policy(policy)
        if filesystem.persistence_mode == "session_hot_cold":
            lease = await self._workspace_service.ensure_workspace(
                session_partition_key=session_pk,
                filesystem=filesystem,
            )
            handle = self._local_unsafe.create_or_get(session_pk, root_dir=lease.workspace_dir)
        else:
            handle = self._local_unsafe.create_or_get(session_pk)
        return await self._local_unsafe.execute(
            sandbox=handle,
            cmd=cmd,
            workdir=workdir,
            timeout_seconds=timeout_seconds,
        )

    async def get_workspace(
        self,
        *,
        agent_id: str,
        session_key: str,
    ) -> SessionWorkspaceRecord | None:
        return self._workspace_service.get(
            session_partition_key=session_partition_key(agent_id=agent_id, session_key=session_key)
        )

    async def list_workspaces(self) -> list[SessionWorkspaceRecord]:
        return self._workspace_service.list()

    async def checkpoint(
        self,
        *,
        policy: SandboxPolicy,
        agent_id: str,
        session_key: str,
    ) -> SessionWorkspaceRecord:
        filesystem = _effective_filesystem_policy(policy)
        return await self._workspace_service.checkpoint(
            session_partition_key=session_partition_key(agent_id=agent_id, session_key=session_key),
            filesystem=filesystem,
        )

    async def hibernate(
        self,
        *,
        policy: SandboxPolicy,
        agent_id: str,
        session_key: str,
    ) -> SessionWorkspaceRecord:
        filesystem = _effective_filesystem_policy(policy)
        return await self._workspace_service.hibernate(
            session_partition_key=session_partition_key(agent_id=agent_id, session_key=session_key),
            filesystem=filesystem,
        )

    async def destroy_workspace(
        self,
        *,
        agent_id: str,
        session_key: str,
    ) -> None:
        await self._workspace_service.destroy(
            session_partition_key=session_partition_key(agent_id=agent_id, session_key=session_key)
        )

    async def restore_workspace_from_directory(
        self,
        *,
        policy: SandboxPolicy,
        agent_id: str,
        session_key: str,
        src_dir: str | Path,
        record: SessionWorkspaceRecord,
    ) -> SessionWorkspaceRecord:
        filesystem = _effective_filesystem_policy(policy)
        lease = await self._workspace_service.restore_from_directory(
            session_partition_key=session_partition_key(agent_id=agent_id, session_key=session_key),
            filesystem=filesystem,
            src_dir=src_dir,
            record=record,
        )
        return lease.record


def _effective_filesystem_policy(policy: SandboxPolicy) -> FileSystemSandboxPolicy:
    return policy.filesystem if isinstance(policy.filesystem, FileSystemSandboxPolicy) else FileSystemSandboxPolicy()
