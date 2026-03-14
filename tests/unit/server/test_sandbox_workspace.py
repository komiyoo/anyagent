from __future__ import annotations

import asyncio
from pathlib import Path

from anyagent.protocol.sandbox import FileSystemSandboxPolicy, SandboxPolicy
from anyagent.server.sandbox import SandboxManager


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
