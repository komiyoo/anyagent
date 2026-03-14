from __future__ import annotations

import hashlib
import json
import shutil
import time
from dataclasses import dataclass
from pathlib import Path

from anyagent.protocol.sandbox import FileSystemSandboxPolicy
from anyagent.storage import SessionWorkspaceRecord


def _now_ms() -> int:
    return int(time.time() * 1000)


def _safe_session_key(session_partition_key: str) -> str:
    return session_partition_key.replace("/", "_").replace(":", "_")


def _copy_dir(*, src: Path, dst: Path) -> None:
    if dst.exists():
        shutil.rmtree(dst)
    dst.parent.mkdir(parents=True, exist_ok=True)
    if src.exists():
        shutil.copytree(src, dst)
    else:
        dst.mkdir(parents=True, exist_ok=True)


def _dir_digest(path: Path) -> tuple[int, str]:
    digest = hashlib.sha256()
    total = 0
    if not path.exists():
        digest.update(b"<empty>")
        return 0, digest.hexdigest()
    for entry in sorted(path.rglob("*")):
        rel = entry.relative_to(path).as_posix().encode("utf-8", errors="replace")
        digest.update(rel)
        if entry.is_file():
            digest.update(b":f:")
            with entry.open("rb") as fh:
                while True:
                    chunk = fh.read(1024 * 1024)
                    if not chunk:
                        break
                    total += len(chunk)
                    digest.update(chunk)
        elif entry.is_dir():
            digest.update(b":d:")
    return total, digest.hexdigest()


@dataclass(frozen=True, slots=True)
class WorkspaceLease:
    record: SessionWorkspaceRecord
    workspace_dir: Path


class LocalSessionWorkspaceService:
    """
    Reference local workspace lifecycle for built-in server and tests.

    Layout:
    - <root>/<safe>/live/workspace         active workspace
    - <root>/<safe>/snapshots/<gen>/...    cold snapshots
    - <root>/<safe>/workspace.json         metadata
    """

    def __init__(self, *, root_dir: str | Path) -> None:
        self._root_dir = Path(root_dir).expanduser().resolve()
        self._root_dir.mkdir(parents=True, exist_ok=True)

    async def ensure_workspace(
        self,
        *,
        session_partition_key: str,
        filesystem: FileSystemSandboxPolicy,
    ) -> WorkspaceLease:
        state_dir = self._state_dir(session_partition_key)
        meta = self._read_record(state_dir)
        workspace_dir = self._active_workspace_dir(state_dir)
        now_ms = _now_ms()
        hot_ttl_s = filesystem.hot_idle_ttl_s if filesystem.hot_idle_ttl_s is not None else 900
        hot_expires_at_ms = now_ms + max(int(hot_ttl_s), 0) * 1000

        if meta is None:
            workspace_dir.mkdir(parents=True, exist_ok=True)
            record = SessionWorkspaceRecord(
                session_partition_key=session_partition_key,
                workspace_id=f"ws_{hashlib.sha256(session_partition_key.encode('utf-8', errors='replace')).hexdigest()[:16]}",
                state="active",
                generation=0,
                sandbox_id=f"local:{_safe_session_key(session_partition_key)}",
                workspace_root=str(filesystem.workspace_root),
                last_accessed_at_ms=now_ms,
                hot_expires_at_ms=hot_expires_at_ms,
                cold_expires_at_ms=self._cold_expiry(now_ms=now_ms, filesystem=filesystem),
            )
            self._write_record(state_dir, record)
            return WorkspaceLease(record=record, workspace_dir=workspace_dir)

        record = meta
        if record.state == "hibernated":
            snapshot_dir = self._snapshot_workspace_dir(state_dir, generation=record.generation)
            _copy_dir(src=snapshot_dir, dst=workspace_dir)
            record = record.model_copy(
                update={
                    "state": "active",
                    "sandbox_id": f"local:{_safe_session_key(session_partition_key)}",
                    "last_accessed_at_ms": now_ms,
                    "hot_expires_at_ms": hot_expires_at_ms,
                }
            )
            self._write_record(state_dir, record)
            return WorkspaceLease(record=record, workspace_dir=workspace_dir)

        if not workspace_dir.exists():
            workspace_dir.mkdir(parents=True, exist_ok=True)
        record = record.model_copy(
            update={
                "state": "active",
                "sandbox_id": f"local:{_safe_session_key(session_partition_key)}",
                "last_accessed_at_ms": now_ms,
                "hot_expires_at_ms": hot_expires_at_ms,
            }
        )
        self._write_record(state_dir, record)
        return WorkspaceLease(record=record, workspace_dir=workspace_dir)

    async def checkpoint(
        self,
        *,
        session_partition_key: str,
        filesystem: FileSystemSandboxPolicy,
    ) -> SessionWorkspaceRecord:
        state_dir = self._state_dir(session_partition_key)
        record = self._require_record(state_dir, session_partition_key=session_partition_key)
        workspace_dir = self._active_workspace_dir(state_dir)
        generation = int(record.generation) + 1
        snapshot_dir = self._snapshot_workspace_dir(state_dir, generation=generation)
        _copy_dir(src=workspace_dir, dst=snapshot_dir)
        snapshot_bytes, digest = _dir_digest(snapshot_dir)
        limit = filesystem.max_snapshot_bytes
        if limit is not None and snapshot_bytes > int(limit):
            if snapshot_dir.exists():
                shutil.rmtree(snapshot_dir)
            raise RuntimeError(
                f"workspace snapshot exceeds max_snapshot_bytes: bytes={snapshot_bytes} limit={int(limit)}"
            )
        updated = record.model_copy(
            update={
                "state": "active",
                "generation": generation,
                "snapshot_uri": str(snapshot_dir),
                "snapshot_digest": digest,
                "snapshot_bytes": snapshot_bytes,
                "cold_expires_at_ms": self._cold_expiry(now_ms=_now_ms(), filesystem=filesystem),
                "failure_code": None,
                "failure_message": None,
            }
        )
        self._write_record(state_dir, updated)
        self._write_manifest(state_dir=state_dir, record=updated)
        return updated

    async def hibernate(
        self,
        *,
        session_partition_key: str,
        filesystem: FileSystemSandboxPolicy,
    ) -> SessionWorkspaceRecord:
        updated = await self.checkpoint(session_partition_key=session_partition_key, filesystem=filesystem)
        workspace_dir = self._active_workspace_dir(self._state_dir(session_partition_key))
        if workspace_dir.exists():
            shutil.rmtree(workspace_dir)
        updated = updated.model_copy(update={"state": "hibernated", "sandbox_id": None})
        self._write_record(self._state_dir(session_partition_key), updated)
        return updated

    async def destroy(self, *, session_partition_key: str) -> None:
        state_dir = self._state_dir(session_partition_key)
        if state_dir.exists():
            shutil.rmtree(state_dir)

    async def restore_from_directory(
        self,
        *,
        session_partition_key: str,
        filesystem: FileSystemSandboxPolicy,
        src_dir: str | Path,
        record: SessionWorkspaceRecord,
    ) -> WorkspaceLease:
        """
        从外部 materialized 快照恢复 active workspace。

        用于：
        - 新实例只有 metadata/snapshot store，没有旧 sandbox 本地状态
        - apps 层先从 snapshot store 取回目录，再导入 sandbox backend
        """

        state_dir = self._state_dir(session_partition_key)
        workspace_dir = self._active_workspace_dir(state_dir)
        src = Path(src_dir).expanduser().resolve()
        _copy_dir(src=src, dst=workspace_dir)
        now_ms = _now_ms()
        hot_ttl_s = filesystem.hot_idle_ttl_s if filesystem.hot_idle_ttl_s is not None else 900
        updated = record.model_copy(
            update={
                "state": "active",
                "sandbox_id": f"local:{_safe_session_key(session_partition_key)}",
                "workspace_root": str(filesystem.workspace_root),
                "last_accessed_at_ms": now_ms,
                "hot_expires_at_ms": now_ms + max(int(hot_ttl_s), 0) * 1000,
            }
        )
        self._write_record(state_dir, updated)
        return WorkspaceLease(record=updated, workspace_dir=workspace_dir)

    def get(self, *, session_partition_key: str) -> SessionWorkspaceRecord | None:
        return self._read_record(self._state_dir(session_partition_key))

    def list(self) -> list[SessionWorkspaceRecord]:
        out: list[SessionWorkspaceRecord] = []
        for child in sorted(self._root_dir.iterdir()) if self._root_dir.exists() else []:
            if not child.is_dir():
                continue
            record = self._read_record(child)
            if record is not None:
                out.append(record)
        return out

    def _cold_expiry(self, *, now_ms: int, filesystem: FileSystemSandboxPolicy) -> int | None:
        if filesystem.cold_retention_s is None:
            return None
        return now_ms + int(filesystem.cold_retention_s) * 1000

    def _state_dir(self, session_partition_key: str) -> Path:
        return self._root_dir / _safe_session_key(session_partition_key)

    def _active_workspace_dir(self, state_dir: Path) -> Path:
        return state_dir / "live" / "workspace"

    def _snapshot_workspace_dir(self, state_dir: Path, *, generation: int) -> Path:
        return state_dir / "snapshots" / f"{generation:08d}" / "workspace"

    def _record_path(self, state_dir: Path) -> Path:
        return state_dir / "workspace.json"

    def _manifest_path(self, state_dir: Path) -> Path:
        return state_dir / "manifest.json"

    def _read_record(self, state_dir: Path) -> SessionWorkspaceRecord | None:
        path = self._record_path(state_dir)
        if not path.is_file():
            return None
        try:
            return SessionWorkspaceRecord.model_validate(json.loads(path.read_text(encoding="utf-8")))
        except Exception:  # noqa: BLE001
            return None

    def _require_record(self, state_dir: Path, *, session_partition_key: str) -> SessionWorkspaceRecord:
        record = self._read_record(state_dir)
        if record is None:
            raise RuntimeError(f"workspace metadata missing for session: {session_partition_key}")
        return record

    def _write_record(self, state_dir: Path, record: SessionWorkspaceRecord) -> None:
        state_dir.mkdir(parents=True, exist_ok=True)
        self._record_path(state_dir).write_text(
            json.dumps(record.model_dump(mode="json", exclude_none=True), ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    def _write_manifest(self, *, state_dir: Path, record: SessionWorkspaceRecord) -> None:
        manifest = {
            "workspace_id": record.workspace_id,
            "generation": record.generation,
            "root": record.workspace_root,
            "created_at_ms": _now_ms(),
            "digest": record.snapshot_digest,
            "bytes": record.snapshot_bytes,
        }
        self._manifest_path(state_dir).write_text(
            json.dumps(manifest, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
