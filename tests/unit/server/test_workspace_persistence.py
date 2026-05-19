from __future__ import annotations

import asyncio
from pathlib import Path

from anyagent.protocol.admin_storage import AdminSandboxRuntimeDiagnostics, AdminSandboxWorkspaceRef
from anyagent.server.sandbox.workspace_persistence import (
    InMemoryWorkspaceLeaseStore,
    LocalFileWorkspaceMetadataStore,
    hold_workspace_lease,
)


def _workspace_ref(*, partition: str, generation: int = 1) -> AdminSandboxWorkspaceRef:
    return AdminSandboxWorkspaceRef(
        session_partition_key=partition,
        workspace_id=f"workspace-{generation}",
        state="hot",
        generation=generation,
        sandbox_id="sandbox-1",
        workspace_root="/workspace",
        snapshot_uri="file:///snapshot",
        snapshot_digest="digest",
        snapshot_bytes=12,
        runtime_diagnostics=AdminSandboxRuntimeDiagnostics(
            provider="local_reference",
            sandbox_id="sandbox-1",
            state="running",
            message="ready",
        ),
    )


def test_local_file_workspace_metadata_store_round_trips_refs(tmp_path: Path) -> None:
    async def _run() -> None:
        store = LocalFileWorkspaceMetadataStore(root_dir=tmp_path / "metadata")
        record = _workspace_ref(partition="tenant/session:one", generation=1)

        assert await store.get(session_partition_key=record.session_partition_key) is None
        assert await store.upsert(record=record) == record

        loaded = await store.get(session_partition_key=record.session_partition_key)
        assert loaded == record
        assert loaded is not None
        assert loaded.runtime_diagnostics is not None
        assert loaded.runtime_diagnostics.provider == "local_reference"
        assert sorted(path.name for path in store.root_dir.glob("*.json")) == ["tenant_session_one.json"]

        updated = record.model_copy(update={"generation": 2, "workspace_id": "workspace-2"})
        await store.upsert(record=updated)
        assert [item.session_partition_key for item in await store.list()] == [record.session_partition_key]
        assert (await store.get(session_partition_key=record.session_partition_key)) == updated

        assert await store.delete(session_partition_key=record.session_partition_key) is True
        assert await store.delete(session_partition_key=record.session_partition_key) is False
        assert await store.list() == []

    asyncio.run(_run())


def test_in_memory_workspace_lease_store_serializes_access() -> None:
    async def _run() -> None:
        store = InMemoryWorkspaceLeaseStore(ttl_ms=1_000, wait_timeout_ms=1)
        first = await store.acquire(key="session-1")
        assert first is not None

        second = await store.acquire(key="session-1")
        assert second is None

        assert await store.release(handle=first) is True
        reacquired = await store.acquire(key="session-1")
        assert reacquired is not None
        assert await store.release(handle=reacquired) is True

    asyncio.run(_run())


def test_hold_workspace_lease_releases_on_exit() -> None:
    async def _run() -> None:
        store = InMemoryWorkspaceLeaseStore(ttl_ms=1_000, wait_timeout_ms=1)
        async with hold_workspace_lease(store=store, key="session-1") as handle:
            assert handle.key == "session-1"
            assert await store.acquire(key="session-1") is None

        reacquired = await store.acquire(key="session-1")
        assert reacquired is not None

    asyncio.run(_run())
