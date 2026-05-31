from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass
from typing import Any

from anyagent.server.db.postgres_schema import PostgresSchemaPolicy
from anyagent.storage.settings import StorageSettings


@dataclass(slots=True)
class SessionRecord:
    session_partition_key: str
    agent_id: str
    session_key: str
    snapshot_json: dict[str, Any]
    snapshot_version: int


class SessionSnapshotVersionConflict(Exception):
    def __init__(
        self,
        *,
        session_partition_key: str,
        expected_snapshot_version: int | None,
        actual_snapshot_version: int | None,
    ) -> None:
        self.session_partition_key = session_partition_key
        self.expected_snapshot_version = expected_snapshot_version
        self.actual_snapshot_version = actual_snapshot_version
        super().__init__(
            "session snapshot version conflict"
            f" (session_partition_key={session_partition_key!r},"
            f" expected={expected_snapshot_version!r},"
            f" actual={actual_snapshot_version!r})"
        )


class InMemorySessionStore:
    def __init__(self) -> None:
        self._sessions: dict[str, SessionRecord] = {}
        self._lock = asyncio.Lock()

    async def get(self, *, session_partition_key: str) -> SessionRecord | None:
        async with self._lock:
            record = self._sessions.get(session_partition_key)
            if record is None:
                return None
            return _clone_record(record)

    async def upsert(
        self,
        *,
        session_partition_key: str,
        agent_id: str,
        session_key: str,
        snapshot_json: dict[str, Any],
        expected_snapshot_version: int | None,
    ) -> SessionRecord:
        async with self._lock:
            current = self._sessions.get(session_partition_key)
            actual_snapshot_version = None if current is None else current.snapshot_version
            if actual_snapshot_version != expected_snapshot_version:
                raise SessionSnapshotVersionConflict(
                    session_partition_key=session_partition_key,
                    expected_snapshot_version=expected_snapshot_version,
                    actual_snapshot_version=actual_snapshot_version,
                )
            version = 0 if current is None else current.snapshot_version + 1
            record = SessionRecord(
                session_partition_key=session_partition_key,
                agent_id=agent_id,
                session_key=session_key,
                snapshot_json=_clone_json(snapshot_json),
                snapshot_version=version,
            )
            self._sessions[session_partition_key] = record
            return _clone_record(record)


class RedisSessionStoreAdapter:
    async def hgetall(self, key: str) -> dict[str, str]: ...
    async def eval(self, script: str, numkeys: int, *keys_and_args: Any) -> Any: ...
    async def pexpire(self, key: str, time_ms: int) -> Any: ...




class RedisSessionStore:
    _UPSERT_SCRIPT = """
local current_version = redis.call('HGET', KEYS[1], 'snapshot_version')
local expected = ARGV[1]
local matches = false
if expected == '__none__' then
  matches = current_version == false
else
  matches = current_version ~= false and tostring(current_version) == expected
end
if not matches then
  if current_version == false then
    return {0, '__none__', ''}
  end
  return {0, tostring(current_version), ''}
end
local next_version = 0
if current_version ~= false then
  next_version = tonumber(current_version) + 1
end
redis.call('HSET', KEYS[1],
  'agent_id', ARGV[2],
  'session_key', ARGV[3],
  'snapshot_json', ARGV[4],
  'snapshot_version', tostring(next_version)
)
return {1, tostring(next_version)}
""".strip()
    _WRITE_RECORD_SCRIPT = """
redis.call('HSET', KEYS[1],
  'agent_id', ARGV[1],
  'session_key', ARGV[2],
  'snapshot_json', ARGV[3],
  'snapshot_version', ARGV[4]
)
return 1
""".strip()

    def __init__(
        self,
        *,
        redis_dsn: str,
        namespace: str = "anyagent",
        adapter: RedisSessionStoreAdapter | None = None,
        retention_s: int = 24 * 60 * 60,
    ) -> None:
        self._redis_dsn = redis_dsn
        self._namespace = namespace.strip() or "anyagent"
        self._adapter = adapter
        self._retention_ms = max(1, int(retention_s * 1000))

    async def get(self, *, session_partition_key: str) -> SessionRecord | None:
        adapter = await self._get_adapter()
        key = build_redis_session_store_key(namespace=self._namespace, session_partition_key=session_partition_key)
        raw = await adapter.hgetall(key)
        if not isinstance(raw, dict) or not raw:
            return None
        snapshot_json_raw = raw.get("snapshot_json")
        try:
            snapshot_json = json.loads(snapshot_json_raw) if isinstance(snapshot_json_raw, str) else {}
        except Exception:  # noqa: BLE001
            snapshot_json = {}
        if not isinstance(snapshot_json, dict):
            snapshot_json = {}
        return SessionRecord(
            session_partition_key=session_partition_key,
            agent_id=str(raw.get("agent_id") or ""),
            session_key=str(raw.get("session_key") or ""),
            snapshot_json=snapshot_json,
            snapshot_version=int(raw.get("snapshot_version") or 0),
        )

    async def upsert(
        self,
        *,
        session_partition_key: str,
        agent_id: str,
        session_key: str,
        snapshot_json: dict[str, Any],
        expected_snapshot_version: int | None,
    ) -> SessionRecord:
        adapter = await self._get_adapter()
        key = build_redis_session_store_key(namespace=self._namespace, session_partition_key=session_partition_key)
        expected = "__none__" if expected_snapshot_version is None else str(int(expected_snapshot_version))
        payload = json.dumps(snapshot_json, ensure_ascii=False)
        result = await adapter.eval(
            self._UPSERT_SCRIPT,
            1,
            key,
            expected,
            agent_id,
            session_key,
            payload,
        )
        if not isinstance(result, (list, tuple)) or not result:
            raise RuntimeError("unexpected redis session store upsert result")
        applied = int(result[0] or 0)
        if applied <= 0:
            actual_raw = result[1] if len(result) > 1 else "__none__"
            actual = None if actual_raw in {None, "", "__none__"} else int(actual_raw)
            raise SessionSnapshotVersionConflict(
                session_partition_key=session_partition_key,
                expected_snapshot_version=expected_snapshot_version,
                actual_snapshot_version=actual,
            )
        await adapter.pexpire(key, self._retention_ms)
        next_version = int(result[1] if len(result) > 1 and str(result[1]).strip() else 0)
        return SessionRecord(
            session_partition_key=session_partition_key,
            agent_id=agent_id,
            session_key=session_key,
            snapshot_json=_clone_json(snapshot_json),
            snapshot_version=next_version,
        )

    async def write_record(self, record: SessionRecord) -> SessionRecord:
        adapter = await self._get_adapter()
        key = build_redis_session_store_key(
            namespace=self._namespace,
            session_partition_key=record.session_partition_key,
        )
        await adapter.eval(
            self._WRITE_RECORD_SCRIPT,
            1,
            key,
            record.agent_id,
            record.session_key,
            json.dumps(record.snapshot_json, ensure_ascii=False),
            str(int(record.snapshot_version)),
        )
        await adapter.pexpire(key, self._retention_ms)
        return _clone_record(record)

    async def _get_adapter(self) -> RedisSessionStoreAdapter:
        if self._adapter is not None:
            return self._adapter
        try:
            from redis import asyncio as redis_asyncio  # type: ignore[import-not-found]
        except Exception as e:  # noqa: BLE001
            raise RuntimeError("redis session store requires `redis` package to be installed") from e
        client = redis_asyncio.from_url(self._redis_dsn, encoding="utf-8", decode_responses=True)
        self._adapter = client
        return client


class CachedSessionStore:
    """
    PG 为主、Redis 为热层：
    - 读：先 Redis，miss 再 PG，并回填 Redis
    - 写：先 PG，再 best-effort 刷新 Redis
    """

    def __init__(self, *, primary: PostgresSessionStore, cache: RedisSessionStore) -> None:
        self._primary = primary
        self._cache = cache

    async def get(self, *, session_partition_key: str) -> SessionRecord | None:
        cached = await self._cache.get(session_partition_key=session_partition_key)
        if cached is not None:
            return cached
        record = await self._primary.get(session_partition_key=session_partition_key)
        if record is not None:
            await self._cache.write_record(record)
        return record

    async def upsert(
        self,
        *,
        session_partition_key: str,
        agent_id: str,
        session_key: str,
        snapshot_json: dict[str, Any],
        expected_snapshot_version: int | None,
    ) -> SessionRecord:
        record = await self._primary.upsert(
            session_partition_key=session_partition_key,
            agent_id=agent_id,
            session_key=session_key,
            snapshot_json=snapshot_json,
            expected_snapshot_version=expected_snapshot_version,
        )
        await self._cache.write_record(record)
        return record


class PostgresSessionStore:
    def __init__(
        self,
        *,
        postgres_dsn: str,
        postgres_schema: str = "public",
        schema_policy: PostgresSchemaPolicy = "migrate",
    ) -> None:
        try:
            from anyagent.storage.external import PostgresSessionStore as ExternalPostgresSessionStore
            from anyagent.storage.external import create_external_sql_engine, resolve_external_sql_backend_config
        except Exception as e:  # noqa: BLE001
            raise RuntimeError(
                "postgres session store requires installing anyagent[postgres]"
                " (and anyagent[redis] when using the cached external store)"
            ) from e

        _ = schema_policy
        config = resolve_external_sql_backend_config(
            postgres_dsn=postgres_dsn,
            mysql_dsn=None,
            redis_dsn=None,
            schema_name=postgres_schema,
            namespace="anyagent",
            dialect="postgresql",
        )
        self._engine = create_external_sql_engine(config)
        self._store = ExternalPostgresSessionStore(engine=self._engine, schema_name=postgres_schema)

    async def get(self, *, session_partition_key: str) -> SessionRecord | None:
        record = await self._store.get(session_partition_key=session_partition_key)
        return None if record is None else _local_session_record(record)

    async def upsert(
        self,
        *,
        session_partition_key: str,
        agent_id: str,
        session_key: str,
        snapshot_json: dict[str, Any],
        expected_snapshot_version: int | None,
    ) -> SessionRecord:
        if expected_snapshot_version is None:
            record = await self._store.create_if_absent(
                session_partition_key=session_partition_key,
                agent_id=agent_id,
                session_key=session_key,
                snapshot_json=snapshot_json,
            )
            return _local_session_record(record)

        ok, latest = await self._store.update_snapshot_cas(
            session_partition_key=session_partition_key,
            expected_snapshot_version=expected_snapshot_version,
            snapshot_json=snapshot_json,
            agent_id=agent_id,
            session_key=session_key,
        )
        if not ok:
            raise SessionSnapshotVersionConflict(
                session_partition_key=session_partition_key,
                expected_snapshot_version=expected_snapshot_version,
                actual_snapshot_version=None if latest is None else latest.snapshot_version,
            )
        if latest is None:
            raise RuntimeError("postgres session store CAS update returned no record")
        return _local_session_record(latest)


def _clone_record(record: SessionRecord) -> SessionRecord:
    return SessionRecord(
        session_partition_key=record.session_partition_key,
        agent_id=record.agent_id,
        session_key=record.session_key,
        snapshot_json=_clone_json(record.snapshot_json),
        snapshot_version=record.snapshot_version,
    )


def _clone_json(value: dict[str, Any]) -> dict[str, Any]:
    return dict(value)


def build_redis_session_store(*, namespace: str | None = None, redis_dsn: str | None = None) -> RedisSessionStore:
    settings = StorageSettings()
    effective_dsn = redis_dsn or (str(settings.redis_dsn) if settings.redis_dsn is not None else None)
    if effective_dsn is None:
        raise RuntimeError("redis session store requires REDIS_DSN")
    effective_namespace = namespace or settings.redis_namespace
    return RedisSessionStore(
        redis_dsn=effective_dsn,
        namespace=effective_namespace,
        retention_s=settings.session_store_retention_s,
    )


def build_postgres_session_store(*, postgres_dsn: str | None = None, postgres_schema: str | None = None) -> PostgresSessionStore:
    settings = StorageSettings()
    effective_dsn = postgres_dsn or (str(settings.postgres_dsn) if settings.postgres_dsn is not None else None)
    if effective_dsn is None:
        raise RuntimeError("postgres session store requires POSTGRES_DSN")
    effective_schema = postgres_schema or settings.postgres_schema
    return PostgresSessionStore(
        postgres_dsn=effective_dsn,
        postgres_schema=effective_schema,
        schema_policy=settings.postgres_schema_policy,
    )


def build_cached_session_store() -> CachedSessionStore:
    return CachedSessionStore(
        primary=build_postgres_session_store(),
        cache=build_redis_session_store(),
    )


def build_redis_session_store_key(*, namespace: str, session_partition_key: str) -> str:
    ns = namespace.strip() or "anyagent"
    return f"{ns}:session:{session_partition_key}"


def _local_session_record(record: Any) -> SessionRecord:
    return SessionRecord(
        session_partition_key=str(getattr(record, "session_partition_key", "") or ""),
        agent_id=str(getattr(record, "agent_id", "") or ""),
        session_key=str(getattr(record, "session_key", "") or ""),
        snapshot_json=getattr(record, "snapshot_json", {}) if isinstance(getattr(record, "snapshot_json", None), dict) else {},
        snapshot_version=int(getattr(record, "snapshot_version", 0) or 0),
    )
