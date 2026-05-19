from __future__ import annotations

import asyncio
from pathlib import Path

from anyagent.server.distributed_runtime import (
    DistributedAgentRuntimeConfig,
    close_distributed_agent_runtime,
    create_distributed_agent_runtime,
)
from anyagent.storage.inmemory import InMemoryEventStore, InMemoryLeaseLock, InMemoryRunStore, InMemorySessionStore
from anyagent.storage.runtime import StorageRuntime


def test_create_distributed_agent_runtime_loads_catalog_and_skills(tmp_path: Path) -> None:
    asyncio.run(_run_create_distributed_agent_runtime_loads_catalog_and_skills(tmp_path))


async def _run_create_distributed_agent_runtime_loads_catalog_and_skills(tmp_path: Path) -> None:
    _write_workspace(tmp_path)
    closed: list[str] = []

    class _Storage(StorageRuntime):
        async def aclose(self) -> None:
            closed.append("storage")

    async def _storage_factory() -> StorageRuntime:
        return _Storage(
            mode="none",
            run_store=InMemoryRunStore(),
            event_store=InMemoryEventStore(),
            lease_lock=InMemoryLeaseLock(),
            session_store=InMemorySessionStore(),
        )

    runtime = await create_distributed_agent_runtime(
        config=DistributedAgentRuntimeConfig(
            workspace_dir=tmp_path,
            tool_runtime_base_url="http://127.0.0.1:8788",
            tool_runtime_internal_key="internal-key",
            manifest_cache_ttl_seconds=0.25,
        ),
        storage_factory=_storage_factory,
        settings={"source": "unit"},
        model_provider_factory=object,
    )

    assert runtime.settings == {"source": "unit"}
    assert runtime.workspace_dir == tmp_path.resolve()
    assert sorted(runtime.agent_catalog.packs.keys()) == ["main"]
    assert "demo-skill" in {skill.frontmatter.name for skill in runtime.global_skills}
    assert runtime.agent_skills["main"] == []
    assert runtime.storage_tasks == set()
    assert runtime.tool_runtime_client is not None

    class _AppState:
        pass

    app_state = _AppState()
    runtime.attach_to_app_state(app_state)
    assert app_state.agent_catalog is runtime.agent_catalog
    assert app_state.storage is runtime.storage
    await close_distributed_agent_runtime(runtime)
    assert closed == ["storage"]


def test_create_distributed_agent_runtime_requires_exposed_main(tmp_path: Path) -> None:
    _write_workspace(tmp_path, exposed=False)

    async def _run() -> None:
        try:
            await create_distributed_agent_runtime(
                config=DistributedAgentRuntimeConfig(
                    workspace_dir=tmp_path,
                    tool_runtime_base_url="http://127.0.0.1:8788",
                    tool_runtime_internal_key="internal-key",
                ),
                storage_factory=_storage,
                model_provider_factory=object,
            )
        except RuntimeError as exc:
            assert "default agent_id=main must be exposed=true" in str(exc)
        else:
            raise AssertionError("expected RuntimeError")

    asyncio.run(_run())


async def _storage() -> StorageRuntime:
    return StorageRuntime(
        mode="none",
        run_store=InMemoryRunStore(),
        event_store=InMemoryEventStore(),
        lease_lock=InMemoryLeaseLock(),
        session_store=InMemorySessionStore(),
    )


def _write_workspace(root: Path, *, exposed: bool = True) -> None:
    agent_dir = root / ".agents" / "agents" / "main"
    agent_dir.mkdir(parents=True, exist_ok=True)
    (agent_dir / "AGENTS.md").write_text("You are a test agent.\n", encoding="utf-8")
    (agent_dir / "agent.yaml").write_text(
        f"""
exposed: {"true" if exposed else "false"}
tools:
  requested_tool_names: []
skills:
  default_selected: []
  disabled_paths: []
""".strip()
        + "\n",
        encoding="utf-8",
    )
    skill_dir = root / ".agents" / "skills" / "demo-skill"
    skill_dir.mkdir(parents=True, exist_ok=True)
    (skill_dir / "SKILL.md").write_text(
        """---
name: demo-skill
description: Demo skill
---
Use this skill for demo tasks.
""",
        encoding="utf-8",
    )
