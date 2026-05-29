from __future__ import annotations

import asyncio
from pathlib import Path

from anyagent.protocol.sandbox import FileSystemSandboxPolicy, SandboxPolicy
from anyagent.server.sandbox.backends import CommandExecutionResult
from anyagent.server.sandbox import SandboxManager


class _FakeOpenSandboxBackend:
    def __init__(self) -> None:
        self.executed: list[dict] = []
        self.hibernated: list[tuple[str, str]] = []
        self.deleted: list[tuple[str, str]] = []

    async def execute_command(self, **kwargs):
        self.executed.append(dict(kwargs))
        return CommandExecutionResult(
            command=kwargs["cmd"],
            exit_code=0,
            stdout="opensandbox\n",
            stderr="",
            duration_ms=1,
            cwd=kwargs["workdir"] or "/workspace",
        )

    async def get_workspace(self, *, agent_id: str, session_key: str):
        _ = agent_id, session_key
        return None

    async def list_workspaces(self):
        return []

    async def hibernate_workspace(self, *, agent_id: str, session_key: str):
        self.hibernated.append((agent_id, session_key))
        raise RuntimeError("not needed for this route test")

    async def delete_workspace(self, *, agent_id: str, session_key: str) -> None:
        self.deleted.append((agent_id, session_key))

    async def restore_workspace_from_directory(self, **_kwargs):
        raise RuntimeError("not needed for this route test")


def test_local_workspace_service_can_hibernate_and_restore(tmp_path: Path) -> None:
    async def _run() -> None:
        manager = SandboxManager(root_dir=tmp_path / ".sandbox")
        policy = SandboxPolicy(
            mode="local-unsafe",
            filesystem=FileSystemSandboxPolicy(
                persistence_mode="session_hot_cold",
                workspace_root="/workspace",
                hot_idle_ttl_s=60,
                cold_retention_s=3600,
                max_snapshot_bytes=1024 * 1024,
            ),
        )

        first = await manager.execute(
            policy=policy,
            agent_id="main",
            session_key="sess-1",
            cmd="printf 'hello workspace' > hello.txt",
        )
        assert first.exit_code == 0

        before_hibernate = await manager.get_workspace(agent_id="main", session_key="sess-1")
        assert before_hibernate is not None
        assert before_hibernate.state == "active"
        assert before_hibernate.generation == 0

        hibernated = await manager.hibernate(policy=policy, agent_id="main", session_key="sess-1")
        assert hibernated.state == "hibernated"
        assert hibernated.generation == 1
        assert isinstance(hibernated.snapshot_uri, str) and hibernated.snapshot_uri

        second = await manager.execute(
            policy=policy,
            agent_id="main",
            session_key="sess-1",
            cmd="cat hello.txt",
        )
        assert second.exit_code == 0
        assert second.stdout == "hello workspace"

        restored = await manager.get_workspace(agent_id="main", session_key="sess-1")
        assert restored is not None
        assert restored.state == "active"
        assert restored.generation == 1

    asyncio.run(_run())


def test_sandbox_manager_routes_opensandbox_policy_to_backend(tmp_path: Path) -> None:
    async def _run() -> None:
        backend = _FakeOpenSandboxBackend()
        manager = SandboxManager(root_dir=tmp_path / ".sandbox", opensandbox_backend=backend)  # type: ignore[arg-type]
        policy = SandboxPolicy(mode="opensandbox")

        result = await manager.execute(
            policy=policy,
            agent_id="main",
            session_key="sess-open",
            cmd="printf ok",
            workdir="repo",
            timeout_seconds=7,
        )

        assert result.stdout == "opensandbox\n"
        assert backend.executed == [
            {
                "policy": policy,
                "agent_id": "main",
                "session_key": "sess-open",
                "cmd": "printf ok",
                "workdir": "repo",
                "timeout_seconds": 7,
            }
        ]
        await manager.destroy_workspace(agent_id="main", session_key="sess-open")
        assert backend.deleted == [("main", "sess-open")]

    asyncio.run(_run())


def test_workspace_checkpoint_enforces_snapshot_size_limit(tmp_path: Path) -> None:
    async def _run() -> None:
        manager = SandboxManager(root_dir=tmp_path / ".sandbox")
        policy = SandboxPolicy(
            mode="local-unsafe",
            filesystem=FileSystemSandboxPolicy(
                persistence_mode="session_hot_cold",
                max_snapshot_bytes=8,
            ),
        )
        result = await manager.execute(
            policy=policy,
            agent_id="main",
            session_key="sess-2",
            cmd="printf '123456789' > data.txt",
        )
        assert result.exit_code == 0
        try:
            await manager.checkpoint(policy=policy, agent_id="main", session_key="sess-2")
        except RuntimeError as exc:
            assert "max_snapshot_bytes" in str(exc)
            return
        raise AssertionError("checkpoint should fail when snapshot exceeds max_snapshot_bytes")

    asyncio.run(_run())
