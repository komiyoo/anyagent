from __future__ import annotations

from pathlib import Path

from anyagent.gateway.session import session_partition_key
from anyagent.protocol.sandbox import FileSystemSandboxPolicy, SandboxPolicy
from anyagent.storage import SessionWorkspaceRecord

from .backends import CommandExecutionResult, LocalUnsafeBackend
from .backends import CommandStagedFile
from .opensandbox_backend import OpenSandboxWorkspaceBackend
from .workspace import LocalSessionWorkspaceService


class SandboxManager:
    def __init__(
        self,
        *,
        root_dir: str | Path | None = None,
        opensandbox_backend: OpenSandboxWorkspaceBackend | None = None,
    ) -> None:
        base_root = Path(root_dir) if root_dir is not None else None
        self._local_unsafe = LocalUnsafeBackend(root_dir=base_root)
        self._opensandbox = opensandbox_backend
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
        env: dict[str, str] | None = None,
        staged_files: list[CommandStagedFile] | None = None,
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
            if self._opensandbox is None:
                raise RuntimeError("opensandbox backend is not configured")
            return await self._opensandbox.execute_command(
                policy=policy,
                agent_id=agent_id,
                session_key=session_key,
                cmd=cmd,
                workdir=workdir,
                timeout_seconds=timeout_seconds,
                env=env,
                staged_files=staged_files,
            )
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
            env=env,
            staged_files=staged_files,
        )

    async def get_workspace(
        self,
        *,
        agent_id: str,
        session_key: str,
    ) -> SessionWorkspaceRecord | None:
        if self._opensandbox is not None:
            record = await self._opensandbox.get_workspace(agent_id=agent_id, session_key=session_key)
            if record is not None:
                return record
        return self._workspace_service.get(
            session_partition_key=session_partition_key(agent_id=agent_id, session_key=session_key)
        )

    async def list_workspaces(self) -> list[SessionWorkspaceRecord]:
        local = self._workspace_service.list()
        if self._opensandbox is None:
            return local
        by_key = {record.session_partition_key: record for record in local}
        for record in await self._opensandbox.list_workspaces():
            by_key[record.session_partition_key] = record
        return list(by_key.values())

    async def checkpoint(
        self,
        *,
        policy: SandboxPolicy,
        agent_id: str,
        session_key: str,
    ) -> SessionWorkspaceRecord:
        if policy.mode == "opensandbox":
            if self._opensandbox is None:
                raise RuntimeError("opensandbox backend is not configured")
            return await self._opensandbox.hibernate_workspace(agent_id=agent_id, session_key=session_key)
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
        if policy.mode == "opensandbox":
            if self._opensandbox is None:
                raise RuntimeError("opensandbox backend is not configured")
            return await self._opensandbox.hibernate_workspace(agent_id=agent_id, session_key=session_key)
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
        if self._opensandbox is not None:
            await self._opensandbox.delete_workspace(agent_id=agent_id, session_key=session_key)
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
        if policy.mode == "opensandbox":
            if self._opensandbox is None:
                raise RuntimeError("opensandbox backend is not configured")
            return await self._opensandbox.restore_workspace_from_directory(
                policy=policy,
                agent_id=agent_id,
                session_key=session_key,
                src_dir=src_dir,
                record=record,
            )
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
