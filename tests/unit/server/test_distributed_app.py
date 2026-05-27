from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

from anyagent.server.distributed_app import create_distributed_agent_app
from anyagent.server.distributed_runtime import DistributedAgentRuntimeConfig
from anyagent.storage.inmemory import InMemoryEventStore, InMemoryLeaseLock, InMemoryRunStore, InMemorySessionStore
from anyagent.storage.runtime import StorageRuntime


def test_create_distributed_agent_app_mounts_core_routes_and_runtime(tmp_path: Path) -> None:
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

    app = create_distributed_agent_app(
        api_key="unit-key",
        runtime_config=DistributedAgentRuntimeConfig(
            workspace_dir=tmp_path,
            tool_runtime_base_url="http://127.0.0.1:8788",
            tool_runtime_internal_key="internal-key",
        ),
        storage_factory=_storage_factory,
        settings={"source": "unit"},
        model_provider_factory=object,
    )

    with TestClient(app) as client:
        assert client.get("/healthz").json() == {"ok": True}
        assert client.get("/readyz").json() == {"ok": True}
        assert app.state.settings == {"source": "unit"}
        assert app.state.workspace_dir == tmp_path.resolve()
        assert sorted(app.state.agent_catalog.packs.keys()) == ["main"]

        unauthenticated = client.get("/v1/responses/resp_missing")
        assert unauthenticated.status_code == 401

        authenticated = client.get("/internal/skills/list", headers={"authorization": "Bearer unit-key"})
        assert authenticated.status_code == 200

    assert closed == ["storage"]


def test_create_distributed_agent_app_rejects_invalid_catalog(tmp_path: Path) -> None:
    _write_workspace(tmp_path, exposed=False)

    async def _storage_factory() -> StorageRuntime:
        return StorageRuntime(
            mode="none",
            run_store=InMemoryRunStore(),
            event_store=InMemoryEventStore(),
            lease_lock=InMemoryLeaseLock(),
            session_store=InMemorySessionStore(),
        )

    app = create_distributed_agent_app(
        api_key="unit-key",
        runtime_config=DistributedAgentRuntimeConfig(
            workspace_dir=tmp_path,
            tool_runtime_base_url="http://127.0.0.1:8788",
            tool_runtime_internal_key="internal-key",
        ),
        storage_factory=_storage_factory,
        model_provider_factory=object,
    )

    try:
        with TestClient(app):
            raise AssertionError("expected lifespan startup failure")
    except RuntimeError as exc:
        assert "default agent_id=main must be exposed=true" in str(exc)


def _write_workspace(root: Path, *, exposed: bool = True) -> None:
    agent_dir = root / ".anyagent" / "agents" / "main"
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
