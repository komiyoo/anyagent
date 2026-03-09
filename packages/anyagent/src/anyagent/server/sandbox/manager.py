from __future__ import annotations

from pathlib import Path

from anyagent.gateway.session import session_partition_key
from anyagent.protocol.sandbox import SandboxPolicy

from .backends import CommandExecutionResult, LocalUnsafeBackend


class SandboxManager:
    def __init__(self, *, root_dir: str | Path | None = None) -> None:
        self._local_unsafe = LocalUnsafeBackend(root_dir=root_dir)

    async def execute(
        self,
        *,
        policy: SandboxPolicy,
        agent_id: str,
        session_key: str,
        cmd: str,
        workdir: str | None = None,
        timeout_seconds: int = 60,
    ) -> CommandExecutionResult:
        mode = policy.mode
        if mode == "disabled":
            raise RuntimeError("sandbox is disabled")
        if mode not in {"local-unsafe", "external", "opensandbox"}:
            raise RuntimeError(f"unsupported sandbox mode: {mode}")
        if mode == "opensandbox":
            raise RuntimeError(f"sandbox backend not implemented yet: {mode}")
        handle = self._local_unsafe.create_or_get(session_partition_key(agent_id=agent_id, session_key=session_key))
        return await self._local_unsafe.execute(
            sandbox=handle,
            cmd=cmd,
            workdir=workdir,
            timeout_seconds=timeout_seconds,
        )
