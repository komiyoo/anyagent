from __future__ import annotations

import asyncio
import sys
from pathlib import Path

from anyagent.server.sandbox.workspace_snapshots import (
    LocalFileWorkspaceSnapshotStore,
    build_s3_workspace_snapshot_store,
)


def test_local_file_workspace_snapshot_store_round_trips_directory(tmp_path: Path) -> None:
    async def _run() -> None:
        source = tmp_path / "source"
        source.mkdir()
        (source / "hello.txt").write_text("snapshot-ok", encoding="utf-8")
        store = LocalFileWorkspaceSnapshotStore(root_dir=tmp_path / "snapshots")

        artifact = await store.put_directory(
            session_partition_key="main::sess",
            generation=2,
            src_dir=str(source),
            snapshot_digest="digest",
            snapshot_bytes=11,
        )
        assert artifact.snapshot_digest == "digest"
        assert artifact.snapshot_bytes == 11
        snapshot_path = Path(artifact.snapshot_uri)
        assert snapshot_path.is_dir()
        assert (snapshot_path.parent / "manifest.json").is_file()
        assert await store.count() == 1

        target = tmp_path / "target"
        await store.materialize_to_directory(snapshot_uri=artifact.snapshot_uri, target_dir=str(target))
        assert (target / "hello.txt").read_text(encoding="utf-8") == "snapshot-ok"

        assert await store.delete(snapshot_uri=artifact.snapshot_uri) is True
        assert await store.count() == 0

    asyncio.run(_run())


def test_s3_workspace_snapshot_builder_reports_missing_extra(monkeypatch) -> None:
    monkeypatch.setitem(sys.modules, "minio", None)
    try:
        build_s3_workspace_snapshot_store(
            endpoint="127.0.0.1:9000",
            access_key="access",
            secret_key="secret",
            bucket="bucket",
        )
    except RuntimeError as exc:
        assert "anyagent[s3]" in str(exc)
        return
    raise AssertionError("expected missing optional dependency error")
