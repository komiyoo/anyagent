from __future__ import annotations

import asyncio
import os
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True, slots=True)
class CommandExecutionResult:
    command: str
    exit_code: int
    stdout: str
    stderr: str
    duration_ms: int
    cwd: str
    timed_out: bool = False


@dataclass(frozen=True, slots=True)
class SandboxHandle:
    session_partition_key: str
    root_dir: Path


class LocalUnsafeBackend:
    def __init__(self, *, root_dir: str | Path | None = None) -> None:
        base = Path(root_dir) if root_dir is not None else Path(tempfile.gettempdir()) / "anyagent-sandboxes"
        self._root_dir = base.expanduser().resolve()
        self._root_dir.mkdir(parents=True, exist_ok=True)

    @property
    def root_dir(self) -> Path:
        return self._root_dir

    def create_or_get(self, session_partition_key: str, root_dir: str | Path | None = None) -> SandboxHandle:
        if root_dir is not None:
            root_dir = Path(root_dir).expanduser().resolve()
        else:
            safe = session_partition_key.replace("/", "_").replace(":", "_")
            root_dir = (self._root_dir / safe).resolve()
        root_dir.mkdir(parents=True, exist_ok=True)
        return SandboxHandle(session_partition_key=session_partition_key, root_dir=root_dir)

    async def execute(
        self,
        *,
        sandbox: SandboxHandle,
        cmd: str,
        workdir: str | None,
        timeout_seconds: int,
        env: dict[str, str] | None = None,
    ) -> CommandExecutionResult:
        cwd = _resolve_workdir(root_dir=sandbox.root_dir, workdir=workdir)
        cwd.mkdir(parents=True, exist_ok=True)

        started = time.monotonic()
        proc = await asyncio.create_subprocess_shell(
            cmd,
            cwd=str(cwd),
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            env=dict(os.environ) if env is None else dict(env),
        )
        timed_out = False
        try:
            stdout_b, stderr_b = await asyncio.wait_for(proc.communicate(), timeout=max(timeout_seconds, 1))
        except asyncio.TimeoutError:
            timed_out = True
            proc.kill()
            stdout_b, stderr_b = await proc.communicate()
        except asyncio.CancelledError:
            proc.kill()
            await proc.communicate()
            raise
        duration_ms = int((time.monotonic() - started) * 1000)
        exit_code = 124 if timed_out else int(proc.returncode or 0)
        return CommandExecutionResult(
            command=cmd,
            exit_code=exit_code,
            stdout=stdout_b.decode("utf-8", errors="replace"),
            stderr=stderr_b.decode("utf-8", errors="replace"),
            duration_ms=duration_ms,
            cwd=str(cwd),
            timed_out=timed_out,
        )


def _resolve_workdir(*, root_dir: Path, workdir: str | None) -> Path:
    if workdir is None or not workdir.strip():
        return root_dir
    raw = workdir.strip()
    candidate = (root_dir / raw).resolve()
    if candidate != root_dir and root_dir not in candidate.parents:
        raise ValueError("workdir must stay within sandbox root")
    return candidate
