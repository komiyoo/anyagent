from __future__ import annotations

import asyncio
import json
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Protocol

from anyagent.protocol.admin_storage import AdminSandboxRuntimeDiagnostics, AdminSandboxWorkspaceRef
from anyagent.storage import LeaseLockHandle


def _safe_partition_key(session_partition_key: str) -> str:
    return session_partition_key.replace("/", "_").replace(":", "_")


def _serialize_runtime_diagnostics(record: AdminSandboxWorkspaceRef) -> str | None:
    if record.runtime_diagnostics is None:
        return None
    return json.dumps(record.runtime_diagnostics.model_dump(mode="json", exclude_none=True), ensure_ascii=False)


def _decode_workspace_row(raw: dict[str, Any]) -> AdminSandboxWorkspaceRef:
    runtime_payload = raw.pop("runtime_diagnostics_json", None)
    if runtime_payload:
        try:
            raw["runtime_diagnostics"] = AdminSandboxRuntimeDiagnostics.model_validate(json.loads(runtime_payload))
        except Exception:  # noqa: BLE001
            raw["runtime_diagnostics"] = None
    return AdminSandboxWorkspaceRef.model_validate(raw)


class WorkspaceMetadataStore(Protocol):
    async def get(self, *, session_partition_key: str) -> AdminSandboxWorkspaceRef | None: ...

    async def list(self) -> list[AdminSandboxWorkspaceRef]: ...

    async def upsert(self, *, record: AdminSandboxWorkspaceRef) -> AdminSandboxWorkspaceRef: ...

    async def delete(self, *, session_partition_key: str) -> bool: ...

    async def aclose(self) -> None: ...


class WorkspaceLeaseStore(Protocol):
    async def acquire(self, *, key: str) -> LeaseLockHandle | None: ...

    async def release(self, *, handle: LeaseLockHandle) -> bool: ...

    async def aclose(self) -> None: ...


@dataclass(slots=True)
class InMemoryWorkspaceLeaseStore:
    """Reference lease for serializing workspace control-plane operations."""

    ttl_ms: int
    wait_timeout_ms: int
    _guard: asyncio.Lock = field(default_factory=asyncio.Lock)
    _owners: dict[str, str] = field(default_factory=dict)

    async def acquire(self, *, key: str) -> LeaseLockHandle | None:
        owner = f"mem:{key}"
        deadline = asyncio.get_running_loop().time() + (self.wait_timeout_ms / 1000.0)
        while True:
            async with self._guard:
                if key not in self._owners:
                    self._owners[key] = owner
                    return LeaseLockHandle(key=key, owner=owner)
            if asyncio.get_running_loop().time() >= deadline:
                return None
            await asyncio.sleep(0.05)

    async def release(self, *, handle: LeaseLockHandle) -> bool:
        async with self._guard:
            if self._owners.get(handle.key) != handle.owner:
                return False
            self._owners.pop(handle.key, None)
            return True

    async def aclose(self) -> None:
        return None


@dataclass(slots=True)
class RedisWorkspaceLeaseStore:
    """Redis-backed workspace lease using Core RedisLeaseLock."""

    lock: Any
    ttl_ms: int
    wait_timeout_ms: int
    redis: Any | None = None

    async def acquire(self, *, key: str) -> LeaseLockHandle | None:
        return await self.lock.acquire(
            key=key,
            owner=f"workspace:{key}",
            ttl_ms=self.ttl_ms,
            wait_timeout_ms=self.wait_timeout_ms,
        )

    async def release(self, *, handle: LeaseLockHandle) -> bool:
        return await self.lock.release(key=handle.key, owner=handle.owner)

    async def aclose(self) -> None:
        if self.redis is not None:
            await self.redis.aclose()


@dataclass(slots=True)
class LocalFileWorkspaceMetadataStore:
    """Local file metadata store for reference and single-node persistence."""

    root_dir: Path

    def __post_init__(self) -> None:
        self.root_dir.mkdir(parents=True, exist_ok=True)

    async def get(self, *, session_partition_key: str) -> AdminSandboxWorkspaceRef | None:
        path = self.root_dir / f"{_safe_partition_key(session_partition_key)}.json"
        if not path.is_file():
            return None
        try:
            return AdminSandboxWorkspaceRef.model_validate(json.loads(path.read_text(encoding="utf-8")))
        except Exception:  # noqa: BLE001
            return None

    async def list(self) -> list[AdminSandboxWorkspaceRef]:
        out: list[AdminSandboxWorkspaceRef] = []
        for path in sorted(self.root_dir.glob("*.json")):
            try:
                out.append(AdminSandboxWorkspaceRef.model_validate(json.loads(path.read_text(encoding="utf-8"))))
            except Exception:  # noqa: BLE001
                continue
        return out

    async def upsert(self, *, record: AdminSandboxWorkspaceRef) -> AdminSandboxWorkspaceRef:
        path = self.root_dir / f"{_safe_partition_key(record.session_partition_key)}.json"
        path.write_text(
            json.dumps(record.model_dump(mode="json", exclude_none=True), ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        return record

    async def delete(self, *, session_partition_key: str) -> bool:
        path = self.root_dir / f"{_safe_partition_key(session_partition_key)}.json"
        if not path.exists():
            return False
        path.unlink()
        return True

    async def aclose(self) -> None:
        return None


class PostgresWorkspaceMetadataStore:
    """PostgreSQL metadata store for workspace session refs."""

    def __init__(self, *, engine: Any, schema_name: str | None = None) -> None:
        try:
            from sqlalchemy import BIGINT, TEXT, Column, MetaData, String, Table
        except ModuleNotFoundError as exc:
            raise RuntimeError("postgres workspace metadata backend requires optional dependency: anyagent[postgres]") from exc

        self._engine = engine
        schema = (schema_name or "public").strip() or "public"
        self._metadata = MetaData(schema=schema)
        self._table = Table(
            "workspace_sessions",
            self._metadata,
            Column("session_partition_key", String(512), primary_key=True),
            Column("workspace_id", String(255), nullable=False),
            Column("state", String(64), nullable=False),
            Column("generation", BIGINT, nullable=False, default=0),
            Column("tenant_id", String(255), nullable=True),
            Column("sandbox_id", String(255), nullable=True),
            Column("workspace_root", String(1024), nullable=True),
            Column("snapshot_uri", TEXT, nullable=True),
            Column("snapshot_digest", String(255), nullable=True),
            Column("snapshot_bytes", BIGINT, nullable=True),
            Column("last_accessed_at_ms", BIGINT, nullable=True),
            Column("hot_expires_at_ms", BIGINT, nullable=True),
            Column("cold_expires_at_ms", BIGINT, nullable=True),
            Column("failure_code", String(255), nullable=True),
            Column("failure_message", TEXT, nullable=True),
            Column("runtime_diagnostics_json", TEXT, nullable=True),
        )

    async def ensure_schema(self) -> None:
        async with self._engine.begin() as conn:
            await conn.run_sync(self._metadata.create_all)
            full_table_name = f"{self._metadata.schema}.{self._table.name}" if self._metadata.schema else self._table.name
            await conn.exec_driver_sql(
                f"ALTER TABLE {full_table_name} ADD COLUMN IF NOT EXISTS runtime_diagnostics_json TEXT"
            )

    async def get(self, *, session_partition_key: str) -> AdminSandboxWorkspaceRef | None:
        from sqlalchemy import select

        stmt = select(self._table).where(self._table.c.session_partition_key == session_partition_key).limit(1)
        async with self._engine.connect() as conn:
            row = (await conn.execute(stmt)).mappings().first()
        return None if row is None else _decode_workspace_row(dict(row))

    async def list(self) -> list[AdminSandboxWorkspaceRef]:
        from sqlalchemy import select

        stmt = select(self._table).order_by(self._table.c.session_partition_key.asc())
        async with self._engine.connect() as conn:
            rows = (await conn.execute(stmt)).mappings().all()
        return [_decode_workspace_row(dict(row)) for row in rows]

    async def upsert(self, *, record: AdminSandboxWorkspaceRef) -> AdminSandboxWorkspaceRef:
        from sqlalchemy import insert, select, update

        values = record.model_dump(mode="json", exclude_none=True)
        values["runtime_diagnostics_json"] = _serialize_runtime_diagnostics(record)
        values.pop("runtime_diagnostics", None)
        async with self._engine.begin() as conn:
            existing = (
                await conn.execute(
                    select(self._table.c.session_partition_key).where(
                        self._table.c.session_partition_key == record.session_partition_key
                    )
                )
            ).first()
            if existing is None:
                await conn.execute(insert(self._table).values(**values))
            else:
                await conn.execute(
                    update(self._table)
                    .where(self._table.c.session_partition_key == record.session_partition_key)
                    .values(**values)
                )
        return record

    async def delete(self, *, session_partition_key: str) -> bool:
        from sqlalchemy import delete

        stmt = delete(self._table).where(self._table.c.session_partition_key == session_partition_key)
        async with self._engine.begin() as conn:
            result = await conn.execute(stmt)
        return bool(result.rowcount)

    async def aclose(self) -> None:
        await self._engine.dispose()


def build_redis_workspace_lease_store(
    *,
    redis_dsn: str,
    namespace: str,
    ttl_ms: int,
    wait_timeout_ms: int,
) -> RedisWorkspaceLeaseStore:
    try:
        from redis.asyncio import Redis
    except ModuleNotFoundError as exc:
        raise RuntimeError("redis workspace lease backend requires optional dependency: anyagent[redis]") from exc

    from anyagent.storage.external import RedisLeaseLock

    redis = Redis.from_url(redis_dsn)
    lock = RedisLeaseLock(redis=redis, namespace=namespace)
    return RedisWorkspaceLeaseStore(
        lock=lock,
        ttl_ms=ttl_ms,
        wait_timeout_ms=wait_timeout_ms,
        redis=redis,
    )


@asynccontextmanager
async def hold_workspace_lease(
    *,
    store: WorkspaceLeaseStore,
    key: str,
) -> Any:
    handle = await store.acquire(key=key)
    if handle is None:
        raise RuntimeError(f"workspace lease acquire timeout: {key}")
    try:
        yield handle
    finally:
        await store.release(handle=handle)
