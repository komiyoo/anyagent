from __future__ import annotations

import asyncio
import json
import shutil
import tarfile
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol

from pydantic import BaseModel, ConfigDict, Field


def _safe_partition_key(session_partition_key: str) -> str:
    return session_partition_key.replace("/", "_").replace(":", "_")


class WorkspaceSnapshotArtifact(BaseModel):
    model_config = ConfigDict(extra="forbid")

    snapshot_uri: str
    snapshot_digest: str | None = None
    snapshot_bytes: int | None = Field(default=None, ge=0)


class WorkspaceSnapshotStore(Protocol):
    async def put_directory(
        self,
        *,
        session_partition_key: str,
        generation: int,
        src_dir: str,
        snapshot_digest: str | None,
        snapshot_bytes: int | None,
    ) -> WorkspaceSnapshotArtifact: ...

    async def delete(self, *, snapshot_uri: str) -> bool: ...

    async def materialize_to_directory(self, *, snapshot_uri: str, target_dir: str) -> None: ...

    async def count(self) -> int: ...

    async def aclose(self) -> None: ...


@dataclass(slots=True)
class LocalFileWorkspaceSnapshotStore:
    """
    Local reference snapshot store.

    The sandbox backend creates a committed snapshot. This store copies it into
    an independent location and writes a manifest so cross-instance recovery can
    be tested without object storage.
    """

    root_dir: Path

    def __post_init__(self) -> None:
        self.root_dir.mkdir(parents=True, exist_ok=True)

    async def put_directory(
        self,
        *,
        session_partition_key: str,
        generation: int,
        src_dir: str,
        snapshot_digest: str | None,
        snapshot_bytes: int | None,
    ) -> WorkspaceSnapshotArtifact:
        src = Path(src_dir).expanduser().resolve()
        target = self.root_dir / _safe_partition_key(session_partition_key) / f"{int(generation):08d}" / "workspace"
        manifest = target.parent / "manifest.json"
        if target.exists():
            shutil.rmtree(target)
        target.parent.mkdir(parents=True, exist_ok=True)
        if src.exists():
            shutil.copytree(src, target)
        else:
            target.mkdir(parents=True, exist_ok=True)
        manifest.write_text(
            json.dumps(
                {
                    "session_partition_key": session_partition_key,
                    "generation": int(generation),
                    "snapshot_digest": snapshot_digest,
                    "snapshot_bytes": snapshot_bytes,
                    "workspace_dir": str(target),
                },
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )
        return WorkspaceSnapshotArtifact(
            snapshot_uri=str(target),
            snapshot_digest=snapshot_digest,
            snapshot_bytes=snapshot_bytes,
        )

    async def delete(self, *, snapshot_uri: str) -> bool:
        path = Path(snapshot_uri).expanduser().resolve()
        root = self.root_dir.resolve()
        if path != root and root not in path.parents:
            return False
        if not path.exists():
            return False
        shutil.rmtree(path.parent)
        return True

    async def materialize_to_directory(self, *, snapshot_uri: str, target_dir: str) -> None:
        src = Path(snapshot_uri).expanduser().resolve()
        dst = Path(target_dir).expanduser().resolve()
        if dst.exists():
            shutil.rmtree(dst)
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copytree(src, dst)

    async def count(self) -> int:
        return sum(1 for _ in self.root_dir.glob("**/manifest.json"))

    async def aclose(self) -> None:
        return None


@dataclass(slots=True)
class S3WorkspaceSnapshotStore:
    """
    S3-compatible snapshot store.

    Uses the optional `minio` SDK. Import is intentionally lazy so the default
    anyagent install remains light unless `anyagent[s3]` is selected.
    """

    client: Any
    bucket: str
    region: str | None = None

    async def put_directory(
        self,
        *,
        session_partition_key: str,
        generation: int,
        src_dir: str,
        snapshot_digest: str | None,
        snapshot_bytes: int | None,
    ) -> WorkspaceSnapshotArtifact:
        prefix = self._prefix(session_partition_key=session_partition_key, generation=generation)
        object_name = f"{prefix}/workspace.tar.gz"
        manifest_name = f"{prefix}/manifest.json"
        archive_path = self._build_archive(src_dir=src_dir)
        manifest = {
            "session_partition_key": session_partition_key,
            "generation": int(generation),
            "snapshot_digest": snapshot_digest,
            "snapshot_bytes": snapshot_bytes,
            "archive": object_name,
        }
        try:
            await self._ensure_bucket()
            await self._fput_object(object_name=object_name, file_path=archive_path, content_type="application/gzip")
            await self._put_text(
                object_name=manifest_name,
                text=json.dumps(manifest, ensure_ascii=False, indent=2),
                content_type="application/json",
            )
        finally:
            archive_path.unlink(missing_ok=True)
        return WorkspaceSnapshotArtifact(
            snapshot_uri=f"s3://{self.bucket}/{object_name}",
            snapshot_digest=snapshot_digest,
            snapshot_bytes=snapshot_bytes,
        )

    async def delete(self, *, snapshot_uri: str) -> bool:
        parsed = _parse_s3_uri(snapshot_uri)
        if parsed is None:
            return False
        bucket, object_name = parsed
        if bucket != self.bucket:
            return False
        prefix = object_name.rsplit("/", 1)[0]
        removed = False
        for candidate in (f"{prefix}/workspace.tar.gz", f"{prefix}/manifest.json"):
            try:
                await self._remove_object(candidate)
                removed = True
            except Exception:  # noqa: BLE001
                continue
        return removed

    async def materialize_to_directory(self, *, snapshot_uri: str, target_dir: str) -> None:
        parsed = _parse_s3_uri(snapshot_uri)
        if parsed is None:
            raise RuntimeError(f"invalid s3 snapshot uri: {snapshot_uri}")
        bucket, object_name = parsed
        archive_path = Path(tempfile.mkstemp(prefix="anyagent-snapshot-", suffix=".tar.gz")[1])
        archive_path.unlink(missing_ok=True)
        dst = Path(target_dir).expanduser().resolve()
        if dst.exists():
            shutil.rmtree(dst)
        dst.parent.mkdir(parents=True, exist_ok=True)

        def _download() -> None:
            self.client.fget_object(bucket, object_name, str(archive_path))

        try:
            await asyncio.to_thread(_download)
            with tarfile.open(archive_path, mode="r:gz") as tar:
                tar.extractall(path=dst.parent, filter="data")
            extracted = dst.parent / "workspace"
            if extracted != dst:
                if dst.exists():
                    shutil.rmtree(dst)
                extracted.rename(dst)
        finally:
            archive_path.unlink(missing_ok=True)

    async def count(self) -> int:
        def _list_count() -> int:
            return sum(1 for item in self.client.list_objects(self.bucket, recursive=True) if item.object_name.endswith("/manifest.json"))

        return await asyncio.to_thread(_list_count)

    async def aclose(self) -> None:
        return None

    def _prefix(self, *, session_partition_key: str, generation: int) -> str:
        return f"{_safe_partition_key(session_partition_key)}/{int(generation):08d}"

    def _build_archive(self, *, src_dir: str) -> Path:
        src = Path(src_dir).expanduser().resolve()
        _fd, raw = tempfile.mkstemp(prefix="anyagent-workspace-", suffix=".tar.gz")
        archive_path = Path(raw)
        archive_path.unlink(missing_ok=True)
        with tarfile.open(archive_path, mode="w:gz") as tar:
            tar.add(src, arcname="workspace")
        return archive_path

    async def _ensure_bucket(self) -> None:
        def _ensure() -> None:
            if not self.client.bucket_exists(self.bucket):
                if self.region:
                    self.client.make_bucket(self.bucket, location=self.region)
                else:
                    self.client.make_bucket(self.bucket)

        await asyncio.to_thread(_ensure)

    async def _fput_object(self, *, object_name: str, file_path: Path, content_type: str) -> None:
        await asyncio.to_thread(
            self.client.fput_object,
            self.bucket,
            object_name,
            str(file_path),
            content_type=content_type,
        )

    async def _put_text(self, *, object_name: str, text: str, content_type: str) -> None:
        payload = text.encode("utf-8")

        def _put() -> None:
            import io

            self.client.put_object(
                self.bucket,
                object_name,
                data=io.BytesIO(payload),
                length=len(payload),
                content_type=content_type,
            )

        await asyncio.to_thread(_put)

    async def _remove_object(self, object_name: str) -> None:
        await asyncio.to_thread(self.client.remove_object, self.bucket, object_name)


def _parse_s3_uri(uri: str) -> tuple[str, str] | None:
    if not isinstance(uri, str) or not uri.startswith("s3://"):
        return None
    rest = uri[len("s3://") :]
    if "/" not in rest:
        return None
    bucket, object_name = rest.split("/", 1)
    if not bucket or not object_name:
        return None
    return bucket, object_name


def build_s3_workspace_snapshot_store(
    *,
    endpoint: str,
    access_key: str,
    secret_key: str,
    bucket: str,
    secure: bool = False,
    region: str | None = None,
) -> S3WorkspaceSnapshotStore:
    try:
        from minio import Minio
    except ModuleNotFoundError as exc:
        raise RuntimeError("s3 workspace snapshot backend requires optional dependency: anyagent[s3]") from exc

    client = Minio(
        endpoint,
        access_key=access_key,
        secret_key=secret_key,
        secure=bool(secure),
        region=region,
    )
    return S3WorkspaceSnapshotStore(client=client, bucket=bucket, region=region)
